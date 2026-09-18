"""Independent LAN coverage service; no imports from the existing VULA app."""
from __future__ import annotations

import getpass
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from datetime import timedelta, datetime, timezone

from flask import Flask, abort, jsonify, render_template, request, session, redirect
from shapely.geometry import Point, shape
from werkzeug.security import check_password_hash, generate_password_hash

from importers import MAX_BYTES, CLIENT_COLUMNS, normalize, read_geo, read_table

OPERATORS = {"IAM": "#2563eb", "INWI": "#9333ea", "ORANGE": "#f97316"}
DATASETS = (*OPERATORS, "pco", "occupation", "clients")
DEFAULT_VISIBILITY = {**{key: True for key in OPERATORS}, "pco": True, "occupation": True, "clients": False}


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS state (name TEXT PRIMARY KEY, payload TEXT NOT NULL, updated TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO state VALUES (?, ?, ?)", ("secret", json.dumps(secrets.token_hex(32)), ""))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, name, default=None):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM state WHERE name=?", (name,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, name, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO state VALUES (?, ?, ?)",
                       (name, json.dumps(value, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))

    def summary(self):
        with self.connect() as db:
            rows = db.execute("SELECT name,payload,updated FROM state").fetchall()
        return {name: {"count": len(json.loads(payload)), "updated": updated}
                for name, payload, updated in rows if name in DATASETS}


def parse_gps(value):
    import re
    text = str(value).strip()
    if "/" in text or ";" in text:
        parts = re.split(r"[/;]", text)
        parts = [p.strip().replace(",", ".") for p in parts]
    else:
        parts = re.split(r"[,\s]+", text)
    if len(parts) != 2:
        raise ValueError("Saisissez latitude, longitude. Exemple : 34.035175, -4.987058")
    lat, lon = map(float, parts)
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude ou longitude hors limites.")
    return lat, lon


def create_app(data_dir=None, testing=False):
    app = Flask(__name__)
    store = Store(Path(data_dir or os.getenv("COVERAGE_DATA_DIR", Path(__file__).parent / "data")) / "coverage.sqlite3")
    prefix = os.getenv("COVERAGE_PREFIX", "").rstrip("/")
    app.config.update(SECRET_KEY=store.get("secret"), MAX_CONTENT_LENGTH=MAX_BYTES,
                      SESSION_COOKIE_NAME="coverage_session", SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_PATH=prefix or "/",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=4), TESTING=testing)
    app.extensions["coverage_store"] = store
    attempts = []
    attempt_lock = threading.Lock()

    def visibility():
        return {**DEFAULT_VISIBILITY, **store.get("visibility", {})}

    def admin():
        # Changing the password immediately revokes old sessions.
        return bool(session.get("admin") and hmac.compare_digest(session.get("auth_version", ""), store.get("auth_version", "missing")))

    @app.before_request
    def protect():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(24)
        if request.path.startswith("/api/admin/") and not admin():
            abort(401, "Connexion administrateur requise.")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            token = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
            if not hmac.compare_digest(session["csrf"], token):
                abort(403, "Session expirée. Actualisez la page.")

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def error(exc):
        return jsonify(error="Fichier trop volumineux (20 Mo maximum)." if exc.code == 413 else exc.description), exc.code

    @app.context_processor
    def context():
        return dict(base=prefix, csrf=session.get("csrf"), operators=OPERATORS, datasets=DATASETS,
                    client_columns=CLIENT_COLUMNS)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify(ok=True, prefix=prefix)

    @app.route("/admin", methods=["GET", "POST"])
    def admin_page():
        message = None
        if request.method == "POST":
            with attempt_lock:
                now = time.monotonic()
                attempts[:] = [t for t in attempts if now - t < 60]
                if len(attempts) >= 10:
                    abort(429, "Trop de tentatives. Réessayez dans une minute.")
                attempts.append(now)
            password_hash = store.get("password")
            password = request.form.get("password", "")
            if password_hash and len(password) <= 256 and check_password_hash(password_hash, password):
                session.clear()
                session.update(admin=True, auth_version=store.get("auth_version"), csrf=secrets.token_hex(24))
                session.permanent = True
                return redirect("/admin")
            message = "Mot de passe incorrect ou administration non initialisée sur le serveur."
        return render_template("admin.html", authenticated=admin(), message=message,
                               initialized=bool(store.get("password")))

    @app.post("/api/admin/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/admin/status")
    def admin_status():
        return jsonify(visibility=visibility(), datasets=store.summary())

    @app.post("/api/admin/visibility")
    def save_visibility():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != set(DATASETS) or any(type(v) is not bool for v in body.values()):
            abort(400, "Configuration de visibilité invalide.")
        store.put("visibility", body)
        return jsonify(ok=True)

    @app.post("/api/admin/import/<kind>")
    def upload(kind):
        if kind not in DATASETS:
            abort(400, "Jeu de données inconnu.")
        file = request.files.get("file")
        if not file or not file.filename:
            abort(400, "Sélectionnez un fichier.")
        try:
            raw = file.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                abort(413)
            records = read_geo(raw, file.filename, points=kind == "pco") if kind in (*OPERATORS, "pco") else read_table(raw, file.filename, kind)
        except Exception as exc:
            # Parsing errors do not alter the last successful dataset.
            if isinstance(exc, ValueError):
                abort(400, str(exc))
            app.logger.warning("Rejected %s import (%s)", kind, type(exc).__name__)
            abort(400, "Fichier invalide ou non compatible. Vérifiez son format et son contenu.")
        store.put(kind, records)
        return jsonify(ok=True, count=len(records))

    @app.post("/api/admin/clear/<kind>")
    def clear(kind):
        if kind not in DATASETS:
            abort(400, "Jeu de données inconnu.")
        store.put(kind, [])
        return jsonify(ok=True)

    @app.get("/api/map")
    def map_data():
        visible = visibility()
        features = []
        for operator, color in OPERATORS.items():
            if visible[operator]:
                for feature in store.get(operator, []):
                    feature["properties"].update(operator=operator, color=color)
                    features.append(feature)
        if visible["pco"]:
            occupation = {normalize(r["pco"]): r for r in store.get("occupation", [])} if visible["occupation"] else {}
            for feature in store.get("pco", []):
                props = feature["properties"]
                props["kind"] = "pco"
                if normalize(props["name"]) in occupation:
                    props["occupation"] = occupation[normalize(props["name"])]
                features.append(feature)
        return jsonify(type="FeatureCollection", features=features, visibility=visible)

    @app.get("/api/lookup")
    def lookup():
        try:
            lat, lon = parse_gps(request.args.get("gps", ""))
        except (ValueError, TypeError) as exc:
            abort(400, str(exc))
        visible = visibility()
        point = Point(lon, lat)
        matches = []
        for operator, color in OPERATORS.items():
            if visible[operator]:
                zones = [f["properties"]["name"] for f in store.get(operator, []) if shape(f["geometry"]).covers(point)]
                if zones:
                    matches.append(dict(operator=operator, color=color, zones=zones))
        return jsonify(lat=lat, lon=lon, matches=matches)

    @app.get("/api/clients")
    def clients():
        if not visibility()["clients"]:
            abort(403, "La base clients n'est pas accessible aux utilisateurs.")
        query = normalize(request.args.get("q", ""))
        if len(query) < 2:
            abort(400, "Saisissez au moins deux caractères.")
        try:
            page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            abort(400, "Page invalide.")
        rows = [r for r in store.get("clients", []) if any(query in normalize(v) for v in r.values())]
        return jsonify(rows=rows[(page-1)*50:page*50], total=len(rows), page=page)

    return app


def setup(app, force=False):
    store = app.extensions["coverage_store"]
    if store.get("password") and not force:
        return
    print("\nCouverture FTTH - creation du mot de passe administrateur (12 caracteres minimum).")
    while True:
        password = getpass.getpass("Mot de passe : ")
        confirmation = getpass.getpass("Confirmation : ")
        if 12 <= len(password) <= 256 and password == confirmation:
            store.put("password", generate_password_hash(password))
            store.put("auth_version", secrets.token_hex(16))
            print("Administration initialisee.\n")
            return
        print("Les mots de passe doivent etre identiques et contenir au moins 12 caracteres.")


if __name__ == "__main__":
    application = create_app()
    if "--setup" in sys.argv or "--reset-admin" in sys.argv:
        setup(application, force="--reset-admin" in sys.argv)
    else:
        from waitress import serve
        host = os.getenv("COVERAGE_HOST", "0.0.0.0")
        port = int(os.getenv("COVERAGE_PORT", "5060"))
        print(f"Couverture FTTH : http://127.0.0.1:{port}/ | Administration : /admin", flush=True)
        print(f"Reseau local : http://IP_DU_PC:{port}/ (ecoute sur {host})", flush=True)
        serve(application, host=host, port=port, threads=8, max_request_body_size=MAX_BYTES)
