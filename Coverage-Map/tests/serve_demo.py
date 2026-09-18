"""Ephemeral synthetic fixture server for optional browser smoke tests only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.append(str(ROOT.parent))
from app import create_app
from importers import read_geo, read_table
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server, WSGIRequestHandler
import gateway


class QuietWSGI(WSGIRequestHandler):
    def log_request(self, *args, **kwargs): pass


class QuietGateway(gateway.GatewayHandler):
    def log_message(self, *args, **kwargs): pass


if __name__ == "__main__":
    os.environ["COVERAGE_PREFIX"] = "/Coverage"
    with tempfile.TemporaryDirectory(prefix="coverage-demo-") as directory:
        application = create_app(directory)
        store = application.extensions["coverage_store"]
        store.put("password", generate_password_hash("synthetic-test-password"))
        store.put("auth_version", "synthetic-version")
        for key in ("IAM","INWI","ORANGE"):
            store.put(key,read_geo((ROOT/"examples/zone.geojson").read_bytes(),"zone.geojson"))
        store.put("pco",read_geo((ROOT/"examples/pco.geojson").read_bytes(),"pco.geojson",points=True))
        for key in ("occupation","clients"):
            store.put(key,read_table((ROOT/f"examples/{key}.csv").read_bytes(),f"{key}.csv",key))
        upstream = make_server("127.0.0.1",0,application,threaded=True,request_handler=QuietWSGI)
        thread = threading.Thread(target=upstream.serve_forever,daemon=True); thread.start()
        gateway.SERVICES = (gateway.Service("coverage","Couverture FTTH","/Coverage",ROOT,upstream.server_port),)
        proxy = gateway.ThreadingHTTPServer(("127.0.0.1",0),QuietGateway)
        proxy_thread = threading.Thread(target=proxy.serve_forever,daemon=True); proxy_thread.start()
        print(f"READY http://127.0.0.1:{proxy.server_port}",flush=True)
        try:
            sys.stdin.readline()
        finally:
            proxy.shutdown(); proxy.server_close(); proxy_thread.join(5)
            upstream.shutdown(); upstream.server_close(); thread.join(5)
