"""Exercise the real HTTP proxy, including cookie paths and login redirects."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

from werkzeug.serving import make_server, WSGIRequestHandler
from werkzeug.security import generate_password_hash
from app import create_app

spec = importlib.util.spec_from_file_location("coverage_gateway_test", Path(__file__).resolve().parents[2] / "gateway.py")
gateway = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gateway
spec.loader.exec_module(gateway)


class QuietWSGI(WSGIRequestHandler):
    def log_request(self, *args, **kwargs): pass


class QuietGateway(gateway.GatewayHandler):
    def log_message(self, *args, **kwargs): pass


class GatewayTests(unittest.TestCase):
    def test_proxy_login_assets_upload_and_unchanged_routes(self):
        self.assertEqual(gateway.find_service("/FO/api/health")[0].key, "fo")
        self.assertEqual(gateway.find_service("/VULA/")[0].key, "vula")
        self.assertEqual(gateway.find_service("/Cuiver/")[0].key, "cuiver")
        self.assertEqual(gateway.find_service("/Coverage/api/map")[1], "/api/map")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"COVERAGE_PREFIX":"/Coverage"}):
            app = create_app(directory, testing=True)
            store = app.extensions["coverage_store"]
            store.put("password", generate_password_hash("synthetic-password"))
            store.put("auth_version", "synthetic-version")
            upstream = make_server("127.0.0.1", 0, app, request_handler=QuietWSGI)
            thread = threading.Thread(target=upstream.serve_forever, daemon=True)
            thread.start()
            service = gateway.Service("coverage","Couverture FTTH","/Coverage",Path(directory),upstream.server_port)
            proxy = gateway.ThreadingHTTPServer(("127.0.0.1",0), QuietGateway)
            proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
            proxy_thread.start()
            try:
                with patch.object(gateway,"SERVICES",(service,)):
                    connection = http.client.HTTPConnection("127.0.0.1",proxy.server_port,timeout=5)
                    try:
                        connection.request("GET","/Coverage")
                        response = connection.getresponse(); response.read()
                        self.assertEqual(response.status,308)
                        self.assertEqual(response.getheader("Location"),"/Coverage/")
                        connection.request("GET","/Coverage/admin")
                        response = connection.getresponse(); html = response.read().decode()
                        cookie = response.getheader("Set-Cookie").split(";",1)[0]
                        csrf = re.search(r'name="csrf-token" content="([^"]+)"',html)[1]
                        connection.request("POST","/Coverage/admin",urlencode({"csrf":csrf,"password":"synthetic-password"}),{"Content-Type":"application/x-www-form-urlencoded","Cookie":cookie})
                        response = connection.getresponse(); response.read()
                        self.assertEqual(response.status,302)
                        self.assertEqual(response.getheader("Location"),"/Coverage/admin")
                        self.assertIn("Path=/Coverage",response.getheader("Set-Cookie"))
                        cookie = response.getheader("Set-Cookie").split(";",1)[0]
                        connection.request("GET","/Coverage/api/admin/status",headers={"Cookie":cookie})
                        response = connection.getresponse()
                        self.assertEqual(response.status,200)
                        self.assertFalse(json.loads(response.read())["visibility"]["clients"])
                        for path in ["/Coverage/static/map.js","/Coverage/static/vendor/leaflet.css","/Coverage/api/map","/"]:
                            connection.request("GET",path)
                            response = connection.getresponse(); body = response.read()
                            self.assertEqual(response.status,200)
                            if path == "/": self.assertIn(b'href="/Coverage/"',body)
                    finally: connection.close()
            finally:
                proxy.shutdown(); proxy.server_close(); proxy_thread.join(5)
                upstream.shutdown(); upstream.server_close(); thread.join(5)


if __name__ == "__main__": unittest.main()
