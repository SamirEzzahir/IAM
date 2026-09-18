"""Local reverse proxy and process supervisor for the FO tools."""

from __future__ import annotations

import atexit
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
WELCOME_PAGE = ROOT / "welcome.html"
GATEWAY_HOST = os.getenv("GATEWAY_HOST", "127.0.0.1")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "80"))


@dataclass(frozen=True)
class Service:
    key: str
    label: str
    prefix: str
    project_dir: Path
    port: int
    health_path: str = "/"

    @property
    def python(self) -> Path:
        return self.project_dir / ".venv" / "Scripts" / "python.exe"


SERVICES = (
    Service("cuiver", "Cuiver", "/Cuiver", ROOT / "IAM-ADSL", 5001),
    Service("fo", "FO", "/FO", ROOT / "IAM-Project", 5055, "/api/health"),
    Service("vula", "VULA", "/VULA", ROOT / "Project-IAM-FO-VULA", 5000),
    Service("coverage", "Couverture FTTH", "/Coverage", ROOT / "Coverage-Map", 5060, "/api/health"),
)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

children: list[subprocess.Popen] = []


def port_is_open(port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def start_services() -> None:
    for service in SERVICES:
        if port_is_open(service.port):
            if service.key == "coverage":
                connection = http.client.HTTPConnection("127.0.0.1", service.port, timeout=3)
                try:
                    connection.request("GET", "/api/health")
                    payload = json.loads(connection.getresponse().read())
                    if payload.get("prefix") != service.prefix:
                        raise RuntimeError("Stop the standalone Coverage-Map server before starting the portal (port 5060).")
                finally:
                    connection.close()
            print(f"[reuse] {service.label} is already listening on port {service.port}.")
            continue
        if not service.python.is_file():
            raise RuntimeError(
                f"Python environment missing for {service.label}: {service.python}"
            )

        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        if service.key == "fo":
            environment["OPEN_BROWSER"] = "0"
            environment["APP_HOST"] = "127.0.0.1"
            environment["APP_PORT"] = str(service.port)
        if service.key == "coverage":
            environment["COVERAGE_HOST"] = "127.0.0.1"
            environment["COVERAGE_PORT"] = str(service.port)
            environment["COVERAGE_PREFIX"] = service.prefix

        process = subprocess.Popen(
            [str(service.python), "app.py"],
            cwd=service.project_dir,
            env=environment,
        )
        children.append(process)
        print(f"[start] {service.label} on internal port {service.port}.")


def stop_services() -> None:
    for process in children:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 4
    for process in children:
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()


def wait_for_services(timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    waiting = {service.port: service for service in SERVICES}
    while waiting and time.monotonic() < deadline:
        for port in list(waiting):
            if port_is_open(port):
                service = waiting.pop(port)
                print(f"[ready] {service.label}: http://127.0.0.1:{port}")
        if waiting:
            time.sleep(0.2)

    if waiting:
        names = ", ".join(service.label for service in waiting.values())
        raise RuntimeError(f"Services did not become ready: {names}")


def find_service(path: str) -> tuple[Service | None, str]:
    for service in SERVICES:
        if path == service.prefix:
            return service, ""
        if path.startswith(service.prefix + "/"):
            upstream_path = path[len(service.prefix) :] or "/"
            return service, upstream_path
    return None, path


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FO-Gateway/1.0"

    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # Browsers commonly close an idle HTTP/1.1 connection after they
            # receive the response. That is normal and does not need a trace.
            pass

    def do_GET(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def do_OPTIONS(self) -> None:
        self._dispatch()

    def _dispatch(self) -> None:
        parsed = urlsplit(self.path)

        if parsed.path == "/":
            self._serve_welcome(head_only=self.command == "HEAD")
            return
        if parsed.path == "/status":
            self._serve_status(head_only=self.command == "HEAD")
            return

        service, upstream_path = find_service(parsed.path)
        if service is None:
            self._send_text(404, "Page introuvable")
            return
        if not upstream_path:
            location = service.prefix + "/"
            if parsed.query:
                location += "?" + parsed.query
            self.send_response(308)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if parsed.query:
            upstream_path += "?" + parsed.query
        self._proxy(service, upstream_path)

    def _serve_welcome(self, head_only: bool = False) -> None:
        try:
            body = WELCOME_PAGE.read_bytes()
        except OSError as exc:
            self._send_text(500, f"Welcome page unavailable: {exc}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _serve_status(self, head_only: bool = False) -> None:
        payload = {
            service.key: {
                "online": port_is_open(service.port),
                "label": service.label,
                "path": service.prefix + "/",
            }
            for service in SERVICES
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _proxy(self, service: Service, upstream_path: str) -> None:
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(content_length) if content_length else None
        headers = {
            name: value
            for name, value in self.headers.items()
            if name.lower() not in HOP_BY_HOP_HEADERS
            and name.lower() not in {"host", "content-length"}
        }
        headers["Host"] = f"127.0.0.1:{service.port}"
        headers["X-Forwarded-Host"] = self.headers.get("Host", "")
        headers["X-Forwarded-Prefix"] = service.prefix
        if body is not None:
            headers["Content-Length"] = str(len(body))

        connection = http.client.HTTPConnection("127.0.0.1", service.port, timeout=3600)
        try:
            connection.request(self.command, upstream_path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            self.send_response(response.status, response.reason)
            for name, value in response.getheaders():
                lower_name = name.lower()
                if lower_name in HOP_BY_HOP_HEADERS or lower_name == "content-length":
                    continue
                if lower_name == "location" and value.startswith("/"):
                    value = service.prefix + value
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response_body)
        except (ConnectionError, OSError, http.client.HTTPException) as exc:
            self._send_text(502, f"{service.label} indisponible: {exc}")
        finally:
            connection.close()

    def _send_text(self, status: int, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[gateway] {self.address_string()} - {format % args}")


def open_portal() -> None:
    time.sleep(0.8)
    browser_host = "127.0.0.1" if GATEWAY_HOST == "0.0.0.0" else GATEWAY_HOST
    webbrowser.open(f"http://{browser_host}:{GATEWAY_PORT}/")


def main() -> int:
    atexit.register(stop_services)
    try:
        start_services()
        wait_for_services()
        server = ThreadingHTTPServer((GATEWAY_HOST, GATEWAY_PORT), GatewayHandler)
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        stop_services()
        return 1

    address = f"http://{GATEWAY_HOST}:{GATEWAY_PORT}/"
    print(f"\nFO portal is ready: {address}")
    if GATEWAY_HOST == "0.0.0.0":
        print(f"LAN access: http://IP_DU_PC:{GATEWAY_PORT}/ (private network only)")
    print("Press Ctrl+C to stop the portal and its services.\n")
    if os.getenv("OPEN_BROWSER", "1").lower() in {"1", "true", "yes"}:
        threading.Thread(target=open_portal, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping FO portal...")
    finally:
        server.server_close()
        stop_services()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
