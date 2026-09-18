import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from openpyxl import Workbook
from werkzeug.security import generate_password_hash

from app import create_app, DEFAULT_VISIBILITY, parse_gps
from importers import read_geo, read_table


def zone(name="Zone test", holes=False):
    rings = [[[0,0],[4,0],[4,4],[0,4],[0,0]]]
    if holes:
        rings.append([[1,1],[1,2],[2,2],[2,1],[1,1]])
    return {"type":"Feature", "geometry":{"type":"Polygon", "coordinates":rings}, "properties":{"name":name, "private":"MUST_NOT_LEAK"}}


class CoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = "test-password-only-123"
        cls.password_hash = generate_password_hash(cls.password)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name, testing=True)
        self.store = self.app.extensions["coverage_store"]
        self.store.put("password", self.password_hash)
        self.store.put("auth_version", "test-version")
        self.client = self.app.test_client()
        self.client.get("/")

    def token(self):
        with self.client.session_transaction() as session:
            return session["csrf"]

    def login(self):
        result = self.client.post("/admin", data={"csrf":self.token(), "password":self.password})
        self.assertEqual(result.status_code, 302)

    def post(self, path, **kwargs):
        return self.client.post(path, headers={"X-CSRF-Token":self.token()}, **kwargs)

    def upload(self, kind, body, filename):
        return self.post("/api/admin/import/" + kind, data={"file":(io.BytesIO(body), filename)})

    def test_pages_and_default_private_clients(self):
        for url in ["/", "/admin", "/static/map.js", "/static/vendor/leaflet.js", "/api/health"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            response.close()
        self.assertEqual(self.client.get("/api/clients?q=test").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/status").status_code, 401)
        self.assertEqual(self.post("/api/admin/clear/IAM").status_code, 401)

    def test_login_csrf_logout_and_password_revocation(self):
        self.assertEqual(self.client.post("/admin", data={"password":self.password}).status_code, 403)
        self.login()
        self.assertEqual(self.client.get("/api/admin/status").status_code, 200)
        self.assertEqual(self.client.post("/api/admin/clear/IAM").status_code, 403)
        self.store.put("auth_version", "new-version")
        self.assertEqual(self.client.get("/api/admin/status").status_code, 401)
        self.login()
        self.assertEqual(self.post("/api/admin/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/admin/status").status_code, 401)

    def test_rate_limit(self):
        for _ in range(10):
            self.client.post("/admin", data={"csrf":self.token(), "password":"wrong"})
        self.assertEqual(self.client.post("/admin", data={"csrf":self.token(), "password":"wrong"}).status_code, 429)

    def test_import_lookup_holes_boundaries_and_overlap(self):
        self.login()
        self.assertEqual(self.upload("IAM", json.dumps(zone(holes=True)).encode(), "zones.geojson").json["count"], 1)
        self.upload("ORANGE", json.dumps(zone()).encode(), "zones.json")
        result = self.client.get("/api/lookup?gps=3,3").json
        self.assertEqual([m["operator"] for m in result["matches"]], ["IAM", "ORANGE"])
        self.assertEqual([m["operator"] for m in self.client.get("/api/lookup?gps=1.5,1.5").json["matches"]], ["ORANGE"])
        self.assertEqual(len(self.client.get("/api/lookup?gps=0,0").json["matches"]), 2)
        self.assertEqual(self.client.get("/api/lookup?gps=10,10").json["matches"], [])
        self.assertNotIn("MUST_NOT_LEAK", self.client.get("/api/map").text)

    def test_hidden_layers_blocked_in_all_user_apis(self):
        self.login()
        self.upload("IAM", json.dumps(zone()).encode(), "zones.json")
        self.store.put("clients", [{"Nom Client":"PRIVATE"}])
        settings = {**DEFAULT_VISIBILITY, "IAM":False, "clients":False, "pco":False}
        self.assertEqual(self.post("/api/admin/visibility", json=settings).status_code, 200)
        self.assertEqual(self.client.get("/api/map").json["features"], [])
        self.assertEqual(self.client.get("/api/lookup?gps=3,3").json["matches"], [])
        self.assertNotIn("PRIVATE", self.client.get("/api/clients?q=private").text)
        self.assertEqual(self.post("/api/admin/visibility", json={"IAM":"yes"}).status_code, 400)

    def test_pco_occupation_hidden_without_leaking(self):
        self.login()
        feature = {"type":"Feature", "properties":{"name":"PCO-01"}, "geometry":{"type":"Point","coordinates":[3,3]}}
        self.upload("pco", json.dumps(feature).encode(), "points.geojson")
        self.upload("occupation", b"PCO,NBRE_OCCUPE,NBRE_PORT\nPCO-01,3,8", "occupation.csv")
        self.assertEqual(self.client.get("/api/map").json["features"][0]["properties"]["occupation"]["free"], 5)
        self.post("/api/admin/visibility", json={**DEFAULT_VISIBILITY,"occupation":False})
        self.assertNotIn("occupation", self.client.get("/api/map").json["features"][0]["properties"])

    def test_invalid_import_keeps_previous_dataset(self):
        self.login()
        self.upload("IAM", json.dumps(zone()).encode(), "valid.geojson")
        invalid = zone(); invalid["geometry"]["coordinates"] = [[[0,0],[2,2],[2,0],[0,2],[0,0]]]
        self.assertEqual(self.upload("IAM", json.dumps(invalid).encode(), "invalid.geojson").status_code, 400)
        self.assertEqual(len(self.store.get("IAM")), 1)
        self.assertEqual(self.upload("IAM", b"bad", "file.kmz").status_code, 400)
        self.assertEqual(len(self.store.get("IAM")), 1)
        self.assertEqual(self.post("/api/admin/clear/IAM").status_code, 200)
        self.assertEqual(self.store.get("IAM"), [])

    def test_client_import_search_and_pagination(self):
        self.login()
        data = "PCO,Nom Client,Login,Unwanted\n" + "\n".join(f"P-{n},Test Élise,user{n},SECRET" for n in range(53))
        self.assertEqual(self.upload("clients", data.encode(), "clients.csv").json["count"], 53)
        self.post("/api/admin/visibility", json={**DEFAULT_VISIBILITY,"clients":True})
        result = self.client.get("/api/clients?q=elise").json
        self.assertEqual(result["total"], 53)
        self.assertEqual(len(result["rows"]), 50)
        self.assertNotIn("SECRET", str(result))
        self.assertEqual(len(self.client.get("/api/clients?q=elise&page=2").json["rows"]), 3)
        self.assertEqual(self.client.get("/api/clients?q=x").status_code, 400)
        self.assertEqual(self.client.get("/api/clients?q=elise&page=bad").status_code, 400)

    def test_persistence_and_prefix(self):
        self.store.put("IAM", [zone()])
        with patch.dict(os.environ, {"COVERAGE_PREFIX":"/Coverage"}):
            app = create_app(self.tmp.name, testing=True)
        with app.test_client() as client:
            response = client.get("/")
            self.assertIn('src="/Coverage/static/map.js"', response.text)
            self.assertIn("Path=/Coverage", response.headers["Set-Cookie"])
            self.assertEqual(client.get("/api/health").json["prefix"], "/Coverage")
        self.assertEqual(app.extensions["coverage_store"].get("IAM"), [zone()])


class ImporterTests(unittest.TestCase):
    def test_gps_formats_and_invalid_values(self):
        for value in ["34.5,-5.2", "34.5 -5.2", "34,5 / -5,2", "34,5; -5,2"]:
            self.assertEqual(parse_gps(value), (34.5, -5.2))
        for value in ["", "nan,2", "91,1", "1,181", "1,2,3"]:
            with self.assertRaises(ValueError): parse_gps(value)

    def test_kml_kmz_points_and_holes(self):
        kml = b'''<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>Test PCO</name><Point><coordinates>-5,34,0</coordinates></Point></Placemark><Placemark><name>Zone</name><Polygon><outerBoundaryIs><LinearRing><coordinates>0,0 4,0 4,4 0,4 0,0</coordinates></LinearRing></outerBoundaryIs><innerBoundaryIs><LinearRing><coordinates>1,1 1,2 2,2 2,1 1,1</coordinates></LinearRing></innerBoundaryIs></Polygon></Placemark></Document></kml>'''
        self.assertEqual(read_geo(kml,"file.kml",points=True)[0]["geometry"]["coordinates"], (-5.,34.))
        output = io.BytesIO()
        with zipfile.ZipFile(output,"w") as archive: archive.writestr("nested/doc.kml",kml)
        result = read_geo(output.getvalue(),"file.kmz")
        self.assertEqual(len(result[0]["geometry"]["coordinates"][0]), 2)

    def test_unsafe_xml_and_invalid_wgs84(self):
        raw = b'<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///C:/Windows/win.ini">]><kml><Placemark><name>&x;</name></Placemark></kml>'
        with self.assertRaises(Exception): read_geo(raw,"file.kml")
        feature = zone(); feature["geometry"]["coordinates"][0][1][0] = 900
        with self.assertRaises(ValueError): read_geo(json.dumps(feature).encode(),"file.json")

    def test_xlsx_csv_and_invalid_occupation(self):
        workbook = Workbook(); workbook.active.append(["PCO","NBRE_OCCUPE","NBRE_PORT"]); workbook.active.append(["P1",3,8])
        output = io.BytesIO(); workbook.save(output); workbook.close()
        self.assertEqual(read_table(output.getvalue(),"o.xlsx","occupation")[0]["free"],5)
        self.assertEqual(read_table(b"PCO;NBRE_OCCUPE;NBRE_PORT\nP1;8;8","o.csv","occupation")[0]["free"],0)
        for value in [b"PCO,NBRE_OCCUPE,NBRE_PORT\nP1,9,8", b"PCO,NBRE_OCCUPE,NBRE_PORT\nP1,1.5,8", b"PCO,NBRE_OCCUPE,NBRE_PORT\nP1,1,8\nP1,2,8", b"A,B\n1,2"]:
            with self.assertRaises(ValueError): read_table(value,"o.csv","occupation")


if __name__ == "__main__":
    unittest.main()
