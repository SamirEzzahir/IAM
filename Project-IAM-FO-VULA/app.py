import atexit
import logging
import os
from pathlib import Path
from time import monotonic
from uuid import uuid4
from threading import Event, Lock, Thread

from flask import Flask, jsonify, request, send_file
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

BASE_DIR = Path(__file__).resolve().parent
HTML_FILE = BASE_DIR / "index.html"

DEFAULT_WIMTECH_URL = (
    "http://wimtech/EtudeAuto/commandeGpon.jsf?"
    "load=1&destination=showPasApasGponPage&"
    "a=PFPOTT%5D%5CG&b=Nnuq}o7-./1&load=1"
)
WIMTECH_URL = os.getenv("WIMTECH_URL", "").strip() or DEFAULT_WIMTECH_URL
WAIT_TIMEOUT = int(os.getenv("SELENIUM_WAIT_TIMEOUT", "25"))
SESSION_TTL_SECONDS = int(os.getenv("SELENIUM_SESSION_TTL_SECONDS", "900"))

logging.basicConfig(
    level=os.getenv("APP_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("vula-control-center")

app = Flask(__name__)
sessions = {}
sessions_lock = Lock()
cleanup_stop = Event()


class BrowserSession:
    def __init__(self, driver):
        self.driver = driver
        self.last_used = monotonic()
        self.operation_lock = Lock()

    def touch(self):
        self.last_used = monotonic()


def build_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-insecure-localhost")
    options.add_argument("--disable-notifications")
    return webdriver.Chrome(options=options)


def close_session(session_id):
    with sessions_lock:
        session = sessions.pop(session_id, None)
    if session:
        try:
            session.driver.quit()
        except Exception:
            logger.exception("Could not close Selenium session %s", session_id)


def cleanup_expired_sessions():
    now = monotonic()
    expired = []
    with sessions_lock:
        for session_id, session in list(sessions.items()):
            if now - session.last_used < SESSION_TTL_SECONDS:
                continue
            if not session.operation_lock.acquire(blocking=False):
                continue
            sessions.pop(session_id, None)
            expired.append((session_id, session))

    for session_id, session in expired:
        try:
            session.driver.quit()
            logger.info("Closed expired Selenium session %s", session_id)
        except Exception:
            logger.exception("Could not close expired Selenium session %s", session_id)
        finally:
            session.operation_lock.release()


def cleanup_worker():
    while not cleanup_stop.wait(60):
        cleanup_expired_sessions()


def shutdown_sessions():
    cleanup_stop.set()
    with sessions_lock:
        session_ids = list(sessions)
    for session_id in session_ids:
        close_session(session_id)


Thread(target=cleanup_worker, name="selenium-session-cleanup", daemon=True).start()
atexit.register(shutdown_sessions)


def extract_value(driver, label):
    xpath = (
        "//div[@id='BDIV_tpins']//tr[td[1][normalize-space()="
        f"'{label} :']]//td[2]"
    )
    try:
        return driver.find_element(By.XPATH, xpath).text.strip()
    except Exception:
        return ""


def has_cmd_error(driver):
    try:
        msgs = driver.find_elements(By.CSS_SELECTOR, ".errorMessagesStyle")
        return any(
            "impossible de lancer l'etude pour cette demande" in
            (m.text or "").strip().lower()
            for m in msgs
        )
    except Exception:
        return False


@app.get("/")
def index():
    return send_file(HTML_FILE)


@app.post("/api/etude-pas-a-pas")
def etude_pas_a_pas():
    payload = request.get_json(silent=True) or {}
    cmd = str(payload.get("cmd", "")).strip()
    if not cmd:
        return jsonify(ok=False, error="Numéro CMD manquant."), 400

    driver = None
    session_id = None
    try:
        driver = build_driver()
        wait = WebDriverWait(driver, WAIT_TIMEOUT)
        driver.get(WIMTECH_URL)

        cmd_input = wait.until(EC.presence_of_element_located((By.ID, "frm:inputDe")))
        cmd_input.clear()
        cmd_input.send_keys(cmd)
        wait.until(EC.element_to_be_clickable((By.ID, "frm:b_et"))).click()

        # Wait for either the WimTech CMD error or the address block.
        wait.until(lambda d: has_cmd_error(d) or len(d.find_elements(By.ID, "BDIV_tpins")) > 0)

        if has_cmd_error(driver):
            driver.quit()
            driver = None
            return jsonify(ok=False, error="cant find cmd", code="CMD_NOT_FOUND"), 404

        wait.until(lambda d: any(extract_value(d, x) for x in ("Province", "Commune", "Quartier", "Voie")))

        province = extract_value(driver, "Province")
        commune = extract_value(driver, "Commune")
        quartier = extract_value(driver, "Quartier")
        voie = extract_value(driver, "Voie")

        if not any((province, commune, quartier, voie)):
            driver.quit()
            driver = None
            return jsonify(ok=False, error="Adresse d'installation non trouvée pour ce CMD."), 404

        address = " ".join(x for x in (province, commune, quartier, voie) if x)

        # Keep this exact Chrome window alive for Apply Étude.
        session_id = uuid4().hex
        with sessions_lock:
            sessions[session_id] = BrowserSession(driver)
        driver = None
        logger.info("Created Selenium session %s for CMD %s", session_id, cmd)

        return jsonify(
            ok=True, session_id=session_id, cmd=cmd,
            province=province, commune=commune, quartier=quartier,
            voie=voie, address=address
        )

    except TimeoutException:
        logger.warning("CMD search timed out for %s", cmd)
        return jsonify(ok=False, error="Délai dépassé pendant la recherche CMD."), 504
    except WebDriverException:
        logger.exception("Selenium/Chrome failed while searching CMD %s", cmd)
        return jsonify(ok=False, error="Erreur Selenium/Chrome. Consultez les journaux de l'application."), 500
    except Exception:
        logger.exception("Unexpected failure while searching CMD %s", cmd)
        return jsonify(ok=False, error="Erreur interne pendant la recherche CMD."), 500
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


@app.post("/api/apply-etude")
def apply_etude():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id", "")).strip()
    pco = str(payload.get("pco", "")).strip()

    if not session_id or not pco:
        return jsonify(ok=False, error="Session ou PCO manquant."), 400

    with sessions_lock:
        session = sessions.get(session_id)
    if session is None:
        return jsonify(ok=False, error="Session WimTech expirée. Relancez la recherche CMD."), 404

    parts = [x.strip() for x in pco.split("-") if x.strip()]
    if len(parts) < 2:
        return jsonify(ok=False, error=f"Format PCO invalide : {pco}"), 400

    odf = parts[0]
    zone_reseau = "-".join(parts[:-1])

    if not session.operation_lock.acquire(blocking=False):
        return jsonify(ok=False, error="Une étude est déjà en cours pour cette session."), 409

    session.touch()
    driver = session.driver

    try:
        wait = WebDriverWait(driver, WAIT_TIMEOUT)

        # Two possible states:
        # 1) First Apply Étude -> we are still on the page containing frm:butt_auto.
        # 2) After a saturated PCO + Annuler -> WimTech stays directly on the form
        #    containing fr:inputRep / fr:inputZr / fr:inputEquipAmont.
        #
        # If the form is already visible, DO NOT click frm:butt_auto again.

        def etude_form_ready(d):
            try:
                rep = d.find_elements(By.ID, "fr:inputRep")
                zr = d.find_elements(By.ID, "fr:inputZr")
                po = d.find_elements(By.ID, "fr:inputEquipAmont")
                return (
                    rep and zr and po
                    and rep[0].is_displayed()
                    and zr[0].is_displayed()
                    and po[0].is_displayed()
                )
            except Exception:
                return False

        if not etude_form_ready(driver):
            wait.until(EC.element_to_be_clickable((By.ID, "frm:butt_auto"))).click()
            wait.until(etude_form_ready)

        # RichFaces/Ajax can replace these input nodes after any interaction.
        # Never keep WebElement references longer than necessary.
        # Re-find the element immediately before clear/send_keys.

        def set_input_value(element_id, value):
            last_error = None
            for _ in range(4):
                try:
                    el = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, element_id))
                    )
                    el.clear()

                    # Re-find after clear because RichFaces may refresh the DOM.
                    el = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, element_id))
                    )
                    el.send_keys(value)
                    return
                except Exception as exc:
                    last_error = exc
            raise last_error

        set_input_value("fr:inputRep", odf)
        set_input_value("fr:inputZr", zone_reseau)
        set_input_value("fr:inputEquipAmont", pco)

        # Re-find the button too, because the form may have been refreshed.
        wait.until(EC.element_to_be_clickable((By.ID, "fr:b_et"))).click()

        # After "Lancer Etude", WimTech can show:
        # 1) normal validation -> fr:bt_ok
        # 2) "Création d'une fibre sans constitution" -> cancel with fr:bt_ann
        def modal_state(d):
            try:
                page_text = (d.find_element(By.TAG_NAME, "body").text or "").lower()

                if (
                    "création d'une fibre sans constitution" in page_text
                    or "creation d'une fibre sans constitution" in page_text
                ):
                    try:
                        if d.find_element(By.ID, "fr:bt_ann").is_displayed():
                            return "SATURATED"
                    except Exception:
                        pass

                try:
                    if d.find_element(By.ID, "fr:bt_ok").is_displayed():
                        return "OK"
                except Exception:
                    pass

                return False
            except Exception:
                return False

        state = wait.until(modal_state)

        if state == "SATURATED":
            # Cancel this PCO attempt, but KEEP the same Chrome/session open
            # so the user can click Apply Étude on another PCO.
            wait.until(EC.element_to_be_clickable((By.ID, "fr:bt_ann"))).click()

            # Wait until the modal is gone / the study form is usable again.
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: not any(
                        el.is_displayed()
                        for el in d.find_elements(By.ID, "fr:bt_ann")
                    )
                )
            except Exception:
                pass

            return jsonify(
                ok=True,
                status="PCO_SATURE",
                keep_session=True,
                message="pco saturé réellement",
                odf=odf,
                zone_reseau=zone_reseau,
                pco=pco
            )

        wait.until(EC.element_to_be_clickable((By.ID, "fr:bt_ok"))).click()
        close_session(session_id)
        return jsonify(
            ok=True,
            status="FINISHED",
            message="Étude lancée et validée avec succès.",
            odf=odf,
            zone_reseau=zone_reseau,
            pco=pco
        )

    except TimeoutException:
        # Keep Chrome open for troubleshooting/retry.
        logger.warning("Apply Étude timed out for session %s and PCO %s", session_id, pco)
        return jsonify(ok=False, error="Délai dépassé pendant Apply Étude. Chrome reste ouvert."), 504
    except Exception:
        logger.exception("Apply Étude failed for session %s and PCO %s", session_id, pco)
        return jsonify(ok=False, error="Erreur interne pendant Apply Étude. Consultez les journaux de l'application."), 500
    finally:
        session.touch()
        session.operation_lock.release()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
