from uuid import uuid4
from threading import Lock
import re
import time
import unicodedata

from flask import jsonify, render_template, request
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, StaleElementReferenceException

from .services.pdf_extractor import (
    MAX_PDF_BYTES,
    PDFExtractionError,
    extract_cmds_from_pdf_bytes,
)
from .application import create_app
from .config import (
    VA_MUTATION_URL,
    WAIT_TIMEOUT_SECONDS,
    WIMTECH_URL,
)

WAIT_TIMEOUT = WAIT_TIMEOUT_SECONDS

app = create_app()
sessions = {}
sessions_lock = Lock()
va_controls = {}
va_controls_lock = Lock()

def va_set_control(session_id, paused=None):
    with va_controls_lock:
        state = va_controls.setdefault(session_id, {"paused": False})
        if paused is not None:
            state["paused"] = bool(paused)
        return dict(state)

def va_checkpoint(session_id, delay_seconds=0):
    """Pause safely, then wait the configured number of seconds.

    The delay is interruptible: pressing Pause freezes the countdown and
    Resume continues with the remaining delay.
    """
    try:
        remaining = max(0.0, float(delay_seconds or 0))
    except Exception:
        remaining = 0.0

    last_tick = time.monotonic()

    while True:
        with va_controls_lock:
            paused = va_controls.get(session_id, {}).get("paused", False)

        if paused:
            time.sleep(0.10)
            last_tick = time.monotonic()
            continue

        if remaining <= 0:
            return

        now = time.monotonic()
        remaining -= max(0.0, now - last_tick)
        last_tick = now

        if remaining > 0:
            time.sleep(min(0.10, remaining))


def va_plain_delay(delay_seconds=0):
    """Delay used before the Selenium session ID is returned to the browser."""
    try:
        delay = max(0.0, float(delay_seconds or 0))
    except Exception:
        delay = 0.0
    if delay:
        time.sleep(delay)

def va_clear_control(session_id):
    with va_controls_lock:
        va_controls.pop(session_id, None)


def build_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-insecure-localhost")
    options.add_argument("--disable-notifications")
    return webdriver.Chrome(options=options)


def close_session(session_id):
    with sessions_lock:
        driver = sessions.pop(session_id, None)
    if driver:
        try:
            driver.quit()
        except Exception:
            pass


def normalize_text(value):
    value = str(value or "")
    value = unicodedata.normalize("NFD", value)
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return " ".join(value.upper().split())


def contains_unknown(value):
    """True for INCONNU / INCONNUE and case/accent variants."""
    return "INCONNU" in normalize_text(value)


def address_requires_manual_check(address):
    """Stop automation when Quartier OR Voie is unknown."""
    return contains_unknown(address.get("quartier")) or contains_unknown(address.get("voie"))


def extract_value(driver, label):
    xpath = (
        "//div[@id='BDIV_tpins']//tr[td[1][normalize-space()="
        f"'{label} :']]//td[2]"
    )
    for _ in range(4):
        try:
            return driver.find_element(By.XPATH, xpath).text.strip()
        except StaleElementReferenceException:
            continue
        except Exception:
            return ""
    return ""


def has_cmd_error(driver):
    try:
        messages = driver.find_elements(By.CSS_SELECTOR, ".errorMessagesStyle")
        text = " ".join((m.text or "") for m in messages).lower()
        return "impossible de lancer l'etude pour cette demande" in text
    except Exception:
        return False


def has_technical_error(driver):
    """Detect the WimTech 'Erreur Technique' page.

    We intentionally do not depend on the Java exception text because it can
    change. The recovery button fr:button + BDIV_tp are stable enough signals.
    """
    try:
        buttons = driver.find_elements(By.ID, "fr:button")
        boxes = driver.find_elements(By.ID, "BDIV_tp")
        if not buttons or not boxes:
            return False
        if not buttons[0].is_displayed():
            return False
        page_text = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
        return "erreur technique" in page_text or "retourner page acceuil" in page_text
    except Exception:
        return False


def extract_installation_address(driver):
    return {
        "province": extract_value(driver, "Province"),
        "commune": extract_value(driver, "Commune"),
        "quartier": extract_value(driver, "Quartier"),
        "voie": extract_value(driver, "Voie"),
    }


def search_cmd_on_current_page(driver, cmd):
    """Search CMD using the already-open Selenium session and return address."""
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    cmd_input = wait.until(EC.element_to_be_clickable((By.ID, "frm:inputDe")))
    cmd_input.clear()
    cmd_input = wait.until(EC.element_to_be_clickable((By.ID, "frm:inputDe")))
    cmd_input.send_keys(cmd)
    wait.until(EC.element_to_be_clickable((By.ID, "frm:b_et"))).click()

    wait.until(
        lambda d: has_cmd_error(d)
        or any(el.is_displayed() for el in d.find_elements(By.ID, "BDIV_tpins"))
    )

    if has_cmd_error(driver):
        raise ValueError("cant find cmd")

    wait.until(
        lambda d: any(
            extract_value(d, name)
            for name in ("Province", "Commune", "Quartier", "Voie")
        )
    )

    address = extract_installation_address(driver)
    if not address["province"] and not address["commune"]:
        raise ValueError("Adresse d'installation non trouvée.")
    return address


def recover_from_technical_error(driver, cmd):
    """Return home, reopen Etude Pas à Pas and rerun the same CMD."""
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    # 1) Retourner page acceuil
    wait.until(EC.element_to_be_clickable((By.ID, "fr:button"))).click()

    # 2) Etude Pas à Pas
    wait.until(EC.element_to_be_clickable((By.ID, "fr:et_pas"))).click()

    # 3) Search the same CMD again.
    return search_cmd_on_current_page(driver, cmd)


def split_constitution(value):
    parts = [x.strip() for x in str(value or "").split("-") if x.strip()]
    if len(parts) < 2:
        raise ValueError(f"Constitution invalide : {value}")
    rep = parts[0]
    sr = "-".join(parts[:-1])
    pc_sr = "-".join(parts)
    return rep, sr, pc_sr


def is_va_radian_zone(value):
    parts = [x.strip() for x in str(value or "").split("-") if x.strip()]
    return len(parts) >= 2 and "00" in parts[1]


def split_va_sr_constitution(value):
    """VA uses SR identity, with an exception for radial zones.

    Normal example:
      FOF-BS01-332/2
      -> Rep    = FOF
      -> SR     = FOF-BS01
      -> SR/PCO = FOF-BS01-BS01

    Radial-zone exception (SR contains "00"):
      FOF-BS00-11542/1
      -> Rep    = FOF
      -> SR     = FOF-BS00
      -> SR/PCO = FOF-BS00-11542/1   (keep original constitution)
    """
    parts = [x.strip() for x in str(value or "").split("-") if x.strip()]
    if len(parts) < 2:
        raise ValueError(f"Constitution VA invalide : {value}")

    rep = parts[0]
    sr_name = parts[1]
    sr = f"{rep}-{sr_name}"

    # Zone radian: if the SR segment contains "00", preserve the source
    # Constitution exactly for the SR/PCO field.
    if "00" in sr_name:
        sr_pco = "-".join(parts)
    else:
        sr_pco = f"{rep}-{sr_name}-{sr_name}"

    return rep, sr, sr_pco


def form_ready(driver):
    try:
        ids = ("fr:inputRep", "fr:inputZr", "fr:inputEquipAmont")
        for element_id in ids:
            els = driver.find_elements(By.ID, element_id)
            if not els or not els[0].is_displayed():
                return False
        return True
    except Exception:
        return False


def set_input_value(driver, element_id, value):
    last_error = None
    for _ in range(5):
        try:
            el = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, element_id))
            )
            el.clear()
            el = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, element_id))
            )
            el.send_keys(value)
            return
        except Exception as exc:
            last_error = exc
    raise last_error


def result_table_state(driver):
    """Classify the WimTech result table before confirming the study.

    A PC-only row (for example ``PC 832/2``) is not a valid transport path.
    It must be cancelled so Bulk Auto Étude can test the next Constitution.
    A transport row is valid whether or not a PC row is also displayed.
    """
    try:
        box = driver.find_element(By.ID, "BDIV_tit_res")
        if not box.is_displayed():
            return False

        has_usable_pair = False
        selects = box.find_elements(By.CSS_SELECTOR, "select[id^='frm:prx']")
        for sel in selects:
            try:
                options = sel.find_elements(By.TAG_NAME, "option")
                values = [str(o.get_attribute("value") or "").strip() for o in options]
                if any(v not in ("", "0") for v in values):
                    has_usable_pair = True
                    break
            except StaleElementReferenceException:
                return False

        if not has_usable_pair:
            return "SATURATED"

        # A tt_combo selector is the stable signal for a transport row. Do not
        # infer transport from outprx: a PC-only result can display one too.
        has_transport = bool(
            box.find_elements(By.CSS_SELECTOR, "select[id^='frm:tt_combo']")
        )
        has_pc = bool(re.search(r"\bPC\s+[^\s]+", normalize_text(box.text)))

        if has_transport:
            return "TRANSPORT_READY"
        if has_pc:
            return "PC_ONLY"
        return "NO_PATH"
    except Exception:
        return False


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/extract-cmd-pdf")
def extract_cmd_pdf_api():
    """Extract Cuivre CMDs from an uploaded PDF without starting Selenium."""
    uploaded = request.files.get("pdf")
    mode = str(request.form.get("mode", "")).strip().lower()

    if uploaded is None or not uploaded.filename:
        return jsonify(ok=False, error="Sélectionnez un fichier PDF."), 400
    if mode not in {"etude", "va"}:
        return jsonify(ok=False, error="Mode d'extraction invalide."), 400

    # Read at most one byte above the accepted size so oversized uploads are
    # rejected without loading an arbitrarily large file into memory.
    pdf_bytes = uploaded.stream.read(MAX_PDF_BYTES + 1)
    if len(pdf_bytes) > MAX_PDF_BYTES:
        return jsonify(ok=False, error="Le fichier PDF dépasse la limite de 20 Mo."), 413

    try:
        result = extract_cmds_from_pdf_bytes(pdf_bytes, mode)
    except PDFExtractionError as exc:
        return jsonify(ok=False, error=str(exc)), 400

    return jsonify(ok=True, filename=uploaded.filename, **result)


@app.post("/api/recherche-cmd")
def recherche_cmd():
    payload = request.get_json(silent=True) or {}
    cmd = str(payload.get("cmd", "")).strip()
    allow_unknown_address = payload.get("allow_unknown_address") is True
    if not cmd:
        return jsonify(ok=False, error="Numéro CMD manquant."), 400

    driver = None
    try:
        driver = build_driver()
        wait = WebDriverWait(driver, WAIT_TIMEOUT)
        driver.get(WIMTECH_URL)

        try:
            address = search_cmd_on_current_page(driver, cmd)
        except ValueError as exc:
            if str(exc) == "cant find cmd":
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = None
                return jsonify(ok=False, code="CMD_NOT_FOUND", error="cant find cmd"), 404
            raise

        province = address["province"]
        commune = address["commune"]
        quartier = address["quartier"]
        voie = address["voie"]

        manual_choice = address_requires_manual_check(address)

        # Bulk Auto Étude keeps the safety stop. Semi-Auto explicitly opts in
        # so its Selenium session stays open and the operator can choose a
        # Constitution manually from the Excel candidates.
        if manual_choice and not allow_unknown_address:
            try:
                driver.quit()
            except Exception:
                pass
            driver = None
            return jsonify(
                ok=True,
                status="MANUAL_REQUIRED",
                message="Should verify manual",
                cmd=cmd,
                province=province,
                commune=commune,
                quartier=quartier,
                voie=voie,
            )

        session_id = uuid4().hex
        with sessions_lock:
            sessions[session_id] = driver
        va_set_control(session_id, paused=False)
        driver = None

        return jsonify(
            ok=True,
            status="MANUAL_CHOICE" if manual_choice else "ADDRESS_READY",
            manual_choice=manual_choice,
            session_id=session_id,
            cmd=cmd,
            province=province,
            commune=commune,
            quartier=quartier,
            voie=voie,
        )

    except TimeoutException:
        return jsonify(ok=False, error="Délai dépassé pendant la recherche CMD."), 504
    except WebDriverException as exc:
        return jsonify(ok=False, error=f"Erreur Selenium/Chrome : {exc.msg}"), 500
    except Exception as exc:
        return jsonify(ok=False, error=f"Erreur : {exc}"), 500
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


@app.post("/api/close-session")
def close_session_api():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id", "")).strip()
    if session_id:
        close_session(session_id)
    return jsonify(ok=True)


@app.post("/api/apply-etude")
def apply_etude():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id", "")).strip()
    constitution = str(payload.get("constitution", "")).strip()
    cmd = str(payload.get("cmd", "")).strip()

    if not session_id or not constitution or not cmd:
        return jsonify(ok=False, error="Session, CMD ou Constitution manquante."), 400

    with sessions_lock:
        driver = sessions.get(session_id)
    if driver is None:
        return jsonify(ok=False, error="Session WimTech expirée. Relancez le CMD."), 404

    try:
        rep, sr, pc_sr = split_constitution(constitution)
        is_radian_zone = is_va_radian_zone(constitution)
        wait = WebDriverWait(driver, WAIT_TIMEOUT)

        # First attempt: click Lancez Etude Pas À Pas.
        # After Annuler on a saturated PC, WimTech can already be on the form;
        # in that case fill directly without clicking frm:butt_auto again.
        if not form_ready(driver):
            wait.until(EC.element_to_be_clickable((By.ID, "frm:butt_auto"))).click()

            # WimTech sometimes returns its JSF "Erreur Technique" page here.
            # Wait for either the normal study form OR the technical error page.
            page_state = wait.until(
                lambda d: "FORM" if form_ready(d)
                else ("TECHNICAL_ERROR" if has_technical_error(d) else False)
            )

            if page_state == "TECHNICAL_ERROR":
                try:
                    address = recover_from_technical_error(driver, cmd)
                except ValueError as exc:
                    return jsonify(
                        ok=False,
                        code="RECOVERY_FAILED",
                        error=f"Erreur technique récupérée, mais la relance CMD a échoué : {exc}",
                    ), 500

                # Keep the SAME Selenium session alive. The user must choose
                # Apply Étude again from the refreshed Excel result list.
                return jsonify(
                    ok=True,
                    status="TECHNICAL_ERROR_RECOVERED",
                    keep_session=True,
                    message="Erreur technique WimTech récupérée. Choisissez de nouveau une ligne Apply Étude.",
                    province=address["province"],
                    commune=address["commune"],
                    quartier=address["quartier"],
                    voie=address["voie"],
                )
        set_input_value(driver, "fr:inputRep", rep)
        set_input_value(driver, "fr:inputZr", sr)
        set_input_value(driver, "fr:inputEquipAmont", pc_sr)
        wait.until(EC.element_to_be_clickable((By.ID, "fr:b_et"))).click()

        state = wait.until(result_table_state)

        # Radial zones (for example FAD-FAD00-1211) do not expose the normal
        # second transport row. Their result is valid as soon as WimTech has
        # displayed the result table, so they must be confirmed directly.
        if not is_radian_zone and state in {"SATURATED", "PC_ONLY", "NO_PATH"}:
            wait.until(EC.element_to_be_clickable((By.ID, "formulaire:bt_ann"))).click()
            # Keep Chrome/session open so another Apply Étude can be tried.
            return jsonify(
                ok=True,
                status="PC_SATURE",
                keep_session=True,
                result_state=state,
                message="pc saturé",
                repartiteur=rep,
                zone_reseau=sr,
                pc_sr=pc_sr,
            )

        wait.until(
            EC.element_to_be_clickable((By.ID, "formulaire:bt_ok"))
        ).click()
        close_session(session_id)
        va_clear_control(session_id)
        return jsonify(
            ok=True,
            status="FINISHED",
            message="Étude validée / cohérence vérifiée.",
            repartiteur=rep,
            zone_reseau=sr,
            pc_sr=pc_sr,
        )

    except TimeoutException:
        return jsonify(
            ok=False,
            error="Délai dépassé pendant Apply Étude. Chrome reste ouvert.",
        ), 504
    except Exception as exc:
        return jsonify(ok=False, error=f"Erreur Apply Étude : {exc}"), 500


def va_extract_address(driver):
    def txt(element_id):
        try:
            return driver.find_element(By.ID, element_id).text.strip()
        except Exception:
            return ""
    return {
        "province": txt("frm:outid03"),
        "commune": txt("frm:outid05"),
        "quartier": txt("frm:outid07"),
        "voie": txt("frm:outid09"),
    }


def va_cmd_invalid(driver):
    try:
        el = driver.find_element(By.ID, "frm:ot_4")
        return "incorrect" in normalize_text(el.text).lower()
    except Exception:
        return False


def va_wait_click(
    driver,
    element_id,
    timeout=WAIT_TIMEOUT,
    session_id=None,
    delay_seconds=0,
):
    """Re-find before clicking and respect VA Pause/Delay."""
    if session_id:
        va_checkpoint(session_id, delay_seconds)
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.ID, element_id))
    ).click()


def va_select_all_old_constitutions(
    driver,
    session_id=None,
    delay_seconds=0,
):
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    wait.until(EC.presence_of_element_located((By.ID, "frm:constitutionList")))

    checkboxes = driver.find_elements(
        By.XPATH,
        "//table[@id='frm:constitutionList']//input[@type='checkbox']"
    )
    count = 0

    for index in range(len(checkboxes)):
        if session_id:
            va_checkpoint(session_id, delay_seconds)

        # Re-find every time because selecting can trigger DOM changes.
        current = driver.find_elements(
            By.XPATH,
            "//table[@id='frm:constitutionList']//input[@type='checkbox']"
        )
        if index >= len(current):
            break

        try:
            cb = current[index]
            if not cb.is_selected():
                driver.execute_script("arguments[0].click();", cb)
            count += 1
        except StaleElementReferenceException:
            current = driver.find_elements(
                By.XPATH,
                "//table[@id='frm:constitutionList']//input[@type='checkbox']"
            )
            if index < len(current):
                driver.execute_script("arguments[0].click();", current[index])
                count += 1

    return count


def va_delete_old_constitutions(
    driver,
    session_id=None,
    delay_seconds=0,
):
    count = va_select_all_old_constitutions(
        driver,
        session_id=session_id,
        delay_seconds=delay_seconds,
    )

    if count == 0:
        return 0

    # Supprimer
    va_wait_click(
        driver, "frm:dataTable82",
        session_id=session_id, delay_seconds=delay_seconds
    )

    # Confirmation modal
    va_wait_click(
        driver, "frm:dataTable94",
        session_id=session_id, delay_seconds=delay_seconds
    )

    # Motif Basculement / Fiabilisation = BSFB
    if session_id:
        va_checkpoint(session_id, delay_seconds)

    radio = WebDriverWait(driver, WAIT_TIMEOUT).until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "input[name='frm:motif_menu'][value='BSFB']")
        )
    )
    if not radio.is_selected():
        driver.execute_script("arguments[0].click();", radio)

    # Valider motif
    va_wait_click(
        driver, "frm:v_but_va",
        session_id=session_id, delay_seconds=delay_seconds
    )

    # Final confirmation
    va_wait_click(
        driver, "frm:v_but_ano",
        session_id=session_id, delay_seconds=delay_seconds
    )

    return count


def _expand_label_node(driver, label, session_id=None, delay_seconds=0):
    """Expand one RichFaces tree label if its child container is hidden."""
    try:
        label_id = label.get_attribute("id") or ""
        if not label_id.startswith("frm:l_"):
            return False

        content_id = label_id[len("frm:l_"):] + "_na"
        content = driver.find_element(By.ID, content_id)

        if content.value_of_css_property("display") == "none":
            if session_id:
                va_checkpoint(session_id, delay_seconds)
            driver.execute_script("arguments[0].click();", label)
            return True
    except Exception:
        pass
    return False


def _normalize_tree_text(text):
    return normalize_text(text or "").upper()


def _transport_head_priority(text):
    """Return the requested VA priority: MSAN, then TT, then TTR."""
    normalized = _normalize_tree_text(text)
    if "TETE" not in normalized:
        return None
    if "MSAN" in normalized:
        return 0
    if re.search(r"\bTT\b", normalized):
        return 1
    if "TTR" in normalized:
        return 2
    return None


def _transport_head_ids(driver):
    """Return eligible TETE IDs sorted by priority and then page order."""
    heads = []
    seen = set()
    for page_order, label in enumerate(
        driver.find_elements(By.CSS_SELECTOR, "label.labelStyle")
    ):
        try:
            priority = _transport_head_priority(label.text)
            label_id = label.get_attribute("id") or ""
            if priority is None or not label_id or label_id in seen:
                continue
            seen.add(label_id)
            heads.append((priority, page_order, label_id))
        except Exception:
            continue
    heads.sort(key=lambda item: (item[0], item[1]))
    return [label_id for _, _, label_id in heads]


def _has_transport_tree(driver):
    try:
        return bool(_transport_head_ids(driver))
    except Exception:
        return False


def _has_pair_level(driver):
    try:
        return any(
            "PAIRE-" in _normalize_tree_text(label.text)
            for label in driver.find_elements(By.CSS_SELECTOR, "label.labelStyle")
        )
    except Exception:
        return False


def _transport_path_key(tete_text, reglette_text, cable_text, cable_index):
    return "|".join((
        _normalize_tree_text(tete_text),
        _normalize_tree_text(reglette_text),
        _normalize_tree_text(cable_text),
        str(cable_index),
    ))


def _public_transport_path(path):
    if not path:
        return None
    return {
        key: value
        for key, value in path.items()
        if not key.startswith("_")
    }


def _find_transport_cable_links(container):
    return container.find_elements(
        By.XPATH,
        ".//a[contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CABL') "
        "or contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CLFI')]"
    )


def va_open_next_transport_path(
    driver,
    tried_path_keys=None,
    session_id=None,
    delay_seconds=0,
):
    """Open the next untested TETE -> REGLETTE -> CABL/CLFI path.

    Every eligible cable is considered. TETE nodes are always ordered MSAN,
    TT, then TTR. ``tried_path_keys`` prevents returning to a cable whose
    28 pairs were already checked.
    """
    tried_path_keys = set(tried_path_keys or ())

    for tete_id in _transport_head_ids(driver):
        try:
            tete = driver.find_element(By.ID, tete_id)
            tete_text = (tete.text or "").strip()
            tete_priority = _transport_head_priority(tete_text)
            tete_type = ("MSAN", "TT", "TTR")[tete_priority]
            _expand_label_node(
                driver, tete,
                session_id=session_id,
                delay_seconds=delay_seconds,
            )

            tete_container_id = tete_id[len("frm:l_"):] + "_na"
            tete_container = driver.find_element(By.ID, tete_container_id)

            reg_ids = []
            for reg in tete_container.find_elements(By.CSS_SELECTOR, "label.labelStyle"):
                try:
                    if "REGLETTE" in _normalize_tree_text(reg.text):
                        reg_id = reg.get_attribute("id")
                        if reg_id:
                            reg_ids.append(reg_id)
                except Exception:
                    continue

            for reg_id in reg_ids:
                try:
                    reg = driver.find_element(By.ID, reg_id)
                    reg_text = (reg.text or "").strip()
                    _expand_label_node(
                        driver, reg,
                        session_id=session_id,
                        delay_seconds=delay_seconds,
                    )

                    reg_container_id = reg_id[len("frm:l_"):] + "_na"
                    reg_container = driver.find_element(By.ID, reg_container_id)
                    cable_links = _find_transport_cable_links(reg_container)

                    if not cable_links:
                        cable_label_ids = []
                        for cab_label in reg_container.find_elements(
                            By.CSS_SELECTOR, "label.labelStyle"
                        ):
                            try:
                                cable_text = _normalize_tree_text(cab_label.text)
                                if "CABL" in cable_text or "CLFI" in cable_text:
                                    cable_label_id = cab_label.get_attribute("id")
                                    if cable_label_id:
                                        cable_label_ids.append(cable_label_id)
                            except Exception:
                                continue

                        for cable_label_id in cable_label_ids:
                            cable_label = driver.find_element(By.ID, cable_label_id)
                            _expand_label_node(
                                driver, cable_label,
                                session_id=session_id,
                                delay_seconds=delay_seconds,
                            )

                        # RichFaces can refresh this subtree during expansion.
                        reg_container = driver.find_element(By.ID, reg_container_id)
                        cable_links = _find_transport_cable_links(reg_container)

                    for cable_index, link in enumerate(cable_links):
                        try:
                            cable_text = (link.text or "").strip()
                            path_key = _transport_path_key(
                                tete_text,
                                reg_text,
                                cable_text,
                                cable_index,
                            )
                            if path_key in tried_path_keys:
                                continue

                            if session_id:
                                va_checkpoint(session_id, delay_seconds)

                            # WimTech keeps the transport tree on this page.
                            # Open the cable in place, leave the current TETE
                            # expanded, then continue with the next path.
                            old_source = driver.page_source
                            driver.execute_script("arguments[0].click();", link)
                            try:
                                WebDriverWait(driver, WAIT_TIMEOUT).until(
                                    lambda current_driver: (
                                        current_driver.page_source != old_source
                                        and _has_pair_level(current_driver)
                                    )
                                )
                            except Exception:
                                pass

                            return {
                                "tete": tete_text,
                                "transport_type": tete_type,
                                "reglette": reg_text,
                                "cable": cable_text,
                                "_key": path_key,
                            }
                        except StaleElementReferenceException:
                            break
                        except Exception:
                            continue

                except StaleElementReferenceException:
                    continue
                except Exception:
                    continue

        except Exception:
            continue

    return None


def va_open_first_transport_path(driver, session_id=None, delay_seconds=0):
    """Backward-compatible wrapper that opens the first priority path."""
    return va_open_next_transport_path(
        driver,
        tried_path_keys=set(),
        session_id=session_id,
        delay_seconds=delay_seconds,
    )


def va_return_to_transport_tree(
    driver,
    path=None,
    session_id=None,
    delay_seconds=0,
):
    """Continue on the same page; never use browser Back or another tab."""
    try:
        WebDriverWait(driver, min(WAIT_TIMEOUT, 5)).until(
            lambda current_driver: _has_transport_tree(current_driver)
        )
        return True
    except Exception:
        return False


def va_rebuild_transport_tree(
    driver,
    cmd,
    rep,
    sr,
    pc_sr,
    session_id=None,
    delay_seconds=0,
):
    """Recreate the transport tree only if WimTech unexpectedly removes it.

    The old Constitution was already deleted before traversal began. This
    recovery only reloads the CMD, reopens Add Constitution, refills the same
    REP/SR/PC and launches the tree again; it does not delete anything twice.
    """
    if not all((cmd, rep, sr, pc_sr)):
        return False

    try:
        if session_id:
            va_checkpoint(session_id, delay_seconds)

        driver.get(VA_MUTATION_URL)
        wait = WebDriverWait(driver, WAIT_TIMEOUT)

        radio = wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "input[name='frm:radionRechrche'][value='NDEM']")
            )
        )
        if not radio.is_selected():
            driver.execute_script("arguments[0].click();", radio)

        if session_id:
            va_checkpoint(session_id, delay_seconds)
        set_input_value(driver, "frm:in_2", cmd)
        va_wait_click(
            driver, "frm:bt_1",
            session_id=session_id,
            delay_seconds=delay_seconds,
        )

        state = wait.until(
            lambda current_driver:
            "INVALID" if va_cmd_invalid(current_driver)
            else (
                "VALID"
                if current_driver.find_elements(By.ID, "frm:bt_2")
                else False
            )
        )
        if state == "INVALID":
            return False

        va_wait_click(
            driver, "frm:bt_2",
            session_id=session_id,
            delay_seconds=delay_seconds,
        )
        wait.until(EC.presence_of_element_located((By.ID, "frm:constitutionList")))

        va_wait_click(
            driver, "frm:dataTable81",
            session_id=session_id,
            delay_seconds=delay_seconds,
        )
        wait.until(EC.presence_of_element_located((By.ID, "fr:inputRep")))

        va_checkpoint(session_id, delay_seconds)
        set_input_value(driver, "fr:inputRep", rep)
        va_checkpoint(session_id, delay_seconds)
        set_input_value(driver, "fr:inputZr", sr)
        va_checkpoint(session_id, delay_seconds)
        set_input_value(driver, "fr:inputEquipAmont", pc_sr)

        va_wait_click(
            driver, "fr:b_et",
            session_id=session_id,
            delay_seconds=delay_seconds,
        )
        wait.until(lambda current_driver: _has_transport_tree(current_driver))
        return True
    except Exception:
        return False


def va_click_first_pair_by_status(
    driver,
    pair_status,
    session_id=None,
    delay_seconds=0,
):
    """Click the first pair matching a normalized status and having (+)."""
    normalized_status = _normalize_tree_text(pair_status)
    for _ in range(10):
        labels = driver.find_elements(By.CSS_SELECTOR, "label.labelStyle")

        for label in labels:
            try:
                text = _normalize_tree_text(label.text)
                if normalized_status == "PAIRE-EN COURS DECON":
                    matches_status = (
                        "PAIRE-" in text
                        and "EN COURS" in text
                        and "DECON" in text
                    )
                else:
                    matches_status = normalized_status in text

                if not matches_status:
                    continue

                parent = label.find_element(By.XPATH, "..")
                links = parent.find_elements(By.CSS_SELECTOR, "a[title='Muter vers']")
                if not links:
                    continue

                pair_text = (label.text or "").strip()

                if session_id:
                    va_checkpoint(session_id, delay_seconds)

                driver.execute_script("arguments[0].click();", links[0])
                return pair_text

            except StaleElementReferenceException:
                continue
            except Exception:
                continue

        time.sleep(0.25)

    return None


def va_click_first_free_pair(driver, session_id=None, delay_seconds=0):
    """Backward-compatible PAIRE-Libre selector."""
    return va_click_first_pair_by_status(
        driver,
        "PAIRE-LIBRE",
        session_id=session_id,
        delay_seconds=delay_seconds,
    )


def va_navigate_transport_and_choose_pair(
    driver,
    cmd=None,
    rep=None,
    sr=None,
    pc_sr=None,
    session_id=None,
    delay_seconds=0,
):
    """Search all paths for Libre, then all again for En cours decon."""
    tested_paths = []

    search_passes = (
        ("PAIRE-LIBRE", "PAIRE-Libre"),
        ("PAIRE-EN COURS DECON", "PAIRE-En cours decon"),
    )

    for pair_status, pair_status_label in search_passes:
        tried_path_keys = set()

        while True:
            path = va_open_next_transport_path(
                driver,
                tried_path_keys=tried_path_keys,
                session_id=session_id,
                delay_seconds=delay_seconds,
            )
            if not path:
                break

            tried_path_keys.add(path["_key"])
            public_path = _public_transport_path(path)
            public_path["pair_status_sought"] = pair_status_label
            tested_paths.append(public_path)

            try:
                WebDriverWait(driver, WAIT_TIMEOUT).until(
                    lambda current_driver: _has_pair_level(current_driver)
                )
            except Exception:
                pass

            pair = va_click_first_pair_by_status(
                driver,
                pair_status,
                session_id=session_id,
                delay_seconds=delay_seconds,
            )
            if pair:
                return public_path, pair, tested_paths

            if not va_return_to_transport_tree(
                driver,
                path=path,
                session_id=session_id,
                delay_seconds=delay_seconds,
            ):
                rebuilt = va_rebuild_transport_tree(
                    driver,
                    cmd=cmd,
                    rep=rep,
                    sr=sr,
                    pc_sr=pc_sr,
                    session_id=session_id,
                    delay_seconds=delay_seconds,
                )
                if not rebuilt:
                    raise TimeoutException(
                        "Impossible de restaurer ou reconstruire l'arbre transport."
                    )

    return None, None, tested_paths


def va_open_radian_cable(driver, session_id=None, delay_seconds=0):
    """Radian zone flow:
       PC xxxx -> cable link (CABL...) -> pair-level page.
    """
    # Find a PC node.
    labels = driver.find_elements(By.CSS_SELECTOR, "label.labelStyle")
    pc_ids = []
    for label in labels:
        try:
            txt = _normalize_tree_text(label.text)
            if txt.startswith("PC "):
                lid = label.get_attribute("id")
                if lid:
                    pc_ids.append(lid)
        except Exception:
            pass

    for pc_id in pc_ids:
        try:
            pc = driver.find_element(By.ID, pc_id)
            pc_text = (pc.text or "").strip()

            _expand_label_node(
                driver, pc,
                session_id=session_id,
                delay_seconds=delay_seconds
            )

            pc_container_id = pc_id[len("frm:l_"):] + "_na"
            pc_container = driver.find_element(By.ID, pc_container_id)

            # Cable may be an <a> directly under PC, or a label depending on page version.
            links = pc_container.find_elements(
                By.XPATH,
                ".//a[contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CABL') "
                "or contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CLFI')]"
            )

            if not links:
                # If cable is rendered as a label, expand it and look for inner <a>.
                cable_label_ids = []
                for lab in pc_container.find_elements(By.CSS_SELECTOR, "label.labelStyle"):
                    try:
                        txt = _normalize_tree_text(lab.text)
                        if "CABL" in txt or "CLFI" in txt:
                            lid = lab.get_attribute("id")
                            if lid:
                                cable_label_ids.append(lid)
                    except Exception:
                        pass

                for lid in cable_label_ids:
                    lab = driver.find_element(By.ID, lid)
                    _expand_label_node(
                        driver, lab,
                        session_id=session_id,
                        delay_seconds=delay_seconds
                    )
                    lab_container_id = lid[len("frm:l_"):] + "_na"
                    lab_container = driver.find_element(By.ID, lab_container_id)
                    links.extend(
                        lab_container.find_elements(
                            By.XPATH,
                            ".//a[contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CABL') "
                            "or contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CLFI')]"
                        )
                    )

            if not links:
                continue

            link = links[0]
            cable_text = (link.text or "").strip()

            if session_id:
                va_checkpoint(session_id, delay_seconds)

            old_source = driver.page_source
            driver.execute_script("arguments[0].click();", link)

            try:
                WebDriverWait(driver, WAIT_TIMEOUT).until(
                    lambda d: (
                        d.page_source != old_source
                        and any(
                            "PAIRE-" in _normalize_tree_text(x.text)
                            for x in d.find_elements(By.CSS_SELECTOR, "label.labelStyle")
                        )
                    )
                )
            except Exception:
                pass

            return {"pc": pc_text, "cable": cable_text}

        except StaleElementReferenceException:
            continue
        except Exception:
            continue

    return None


def va_navigate_radian_and_choose_pair(driver, session_id=None, delay_seconds=0):
    """PC -> cable -> pair level -> first PAIRE-Libre (+)."""
    path = va_open_radian_cable(
        driver,
        session_id=session_id,
        delay_seconds=delay_seconds
    )
    if not path:
        return None, None

    try:
        WebDriverWait(driver, WAIT_TIMEOUT).until(
            lambda d: any(
                "PAIRE-" in _normalize_tree_text(x.text)
                for x in d.find_elements(By.CSS_SELECTOR, "label.labelStyle")
            )
        )
    except Exception:
        pass

    pair = va_click_first_free_pair(
        driver,
        session_id=session_id,
        delay_seconds=delay_seconds
    )
    return path, pair


@app.post("/api/re-etude-va/start")
def re_etude_va_start():
    payload = request.get_json(silent=True) or {}
    cmd = str(payload.get("cmd", "")).strip()
    try:
        delay_seconds = max(0.0, float(payload.get("delay_seconds", 0) or 0))
    except Exception:
        delay_seconds = 0.0

    if not cmd:
        return jsonify(ok=False, error="Numéro CMD manquant."), 400

    driver = None
    try:
        driver = build_driver()
        wait = WebDriverWait(driver, WAIT_TIMEOUT)
        driver.get(VA_MUTATION_URL)

        # Recherche par NDEM.
        radio = wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "input[name='frm:radionRechrche'][value='NDEM']")
            )
        )
        if not radio.is_selected():
            driver.execute_script("arguments[0].click();", radio)

        va_plain_delay(delay_seconds)
        set_input_value(driver, "frm:in_2", cmd)

        va_plain_delay(delay_seconds)
        va_wait_click(driver, "frm:bt_1")

        # Either invalid designation or Valider button.
        state = wait.until(
            lambda d:
            "INVALID" if va_cmd_invalid(d)
            else ("VALID" if d.find_elements(By.ID, "frm:bt_2") else False)
        )

        if state == "INVALID":
            try:
                driver.quit()
            except Exception:
                pass
            driver = None
            return jsonify(
                ok=False,
                code="INVALID_CMD",
                error="Le numéro designation est incorrect!"
            ), 404

        va_plain_delay(delay_seconds)
        va_wait_click(driver, "frm:bt_2")

        wait.until(EC.presence_of_element_located((By.ID, "BDIV_tpins")))
        wait.until(EC.presence_of_element_located((By.ID, "frm:constitutionList")))
        address = va_extract_address(driver)

        if address_requires_manual_check(address):
            try:
                driver.quit()
            except Exception:
                pass
            driver = None
            return jsonify(
                ok=True,
                status="MANUAL_REQUIRED",
                message="Should verify manual",
                cmd=cmd,
                **address
            )

        session_id = uuid4().hex
        with sessions_lock:
            sessions[session_id] = driver
        driver = None

        return jsonify(
            ok=True,
            status="ADDRESS_READY",
            session_id=session_id,
            cmd=cmd,
            **address
        )

    except TimeoutException:
        return jsonify(ok=False, error="Délai dépassé pendant la préparation Ré-Étude VA."), 504
    except Exception as exc:
        return jsonify(ok=False, error=f"Erreur Ré-Étude VA : {exc}"), 500
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


@app.post("/api/re-etude-va/pause")
def re_etude_va_pause():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return jsonify(ok=False, error="Session manquante."), 400
    with sessions_lock:
        exists = session_id in sessions
    if not exists:
        return jsonify(ok=False, error="Session VA expirée."), 404
    va_set_control(session_id, paused=True)
    return jsonify(ok=True, status="PAUSED")


@app.post("/api/re-etude-va/resume")
def re_etude_va_resume():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return jsonify(ok=False, error="Session manquante."), 400
    with sessions_lock:
        exists = session_id in sessions
    if not exists:
        return jsonify(ok=False, error="Session VA expirée."), 404
    va_set_control(session_id, paused=False)
    return jsonify(ok=True, status="RUNNING")


@app.post("/api/re-etude-va/execute")
def re_etude_va_execute():
    payload = request.get_json(silent=True) or {}
    session_id = str(payload.get("session_id", "")).strip()
    constitution = str(payload.get("constitution", "")).strip()
    cmd = str(payload.get("cmd", "")).strip()
    try:
        delay_seconds = max(0.0, float(payload.get("delay_seconds", 0) or 0))
    except Exception:
        delay_seconds = 0.0

    if not session_id or not constitution or not cmd:
        return jsonify(
            ok=False,
            error="Session, CMD ou Constitution manquante.",
        ), 400

    with sessions_lock:
        driver = sessions.get(session_id)
    if driver is None:
        return jsonify(ok=False, error="Session VA expirée. Relancez le CMD."), 404

    try:
        rep, sr, pc_sr = split_va_sr_constitution(constitution)
        is_radian = is_va_radian_zone(constitution)
        wait = WebDriverWait(driver, WAIT_TIMEOUT)

        # 1. Suppression ancienne constitution.
        deleted_count = va_delete_old_constitutions(
            driver,
            session_id=session_id,
            delay_seconds=delay_seconds,
        )

        # 2. Ajouter nouvelle constitution.
        va_wait_click(
            driver, "frm:dataTable81",
            session_id=session_id, delay_seconds=delay_seconds
        )
        wait.until(EC.presence_of_element_located((By.ID, "fr:inputRep")))

        va_checkpoint(session_id, delay_seconds)
        set_input_value(driver, "fr:inputRep", rep)

        va_checkpoint(session_id, delay_seconds)
        set_input_value(driver, "fr:inputZr", sr)

        va_checkpoint(session_id, delay_seconds)
        set_input_value(driver, "fr:inputEquipAmont", pc_sr)

        va_wait_click(
            driver, "fr:b_et",
            session_id=session_id, delay_seconds=delay_seconds
        )

        # 3. Navigate according to VA zone type.
        wait.until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, "label.labelStyle")) > 0
        )

        if is_radian:
            transport_path, pair_label = va_navigate_radian_and_choose_pair(
                driver,
                session_id=session_id,
                delay_seconds=delay_seconds,
            )
            tested_transport_paths = (
                [_public_transport_path(transport_path)]
                if transport_path else []
            )
        else:
            (
                transport_path,
                pair_label,
                tested_transport_paths,
            ) = va_navigate_transport_and_choose_pair(
                driver,
                cmd=cmd,
                rep=rep,
                sr=sr,
                pc_sr=pc_sr,
                session_id=session_id,
                delay_seconds=delay_seconds,
            )

        if not pair_label:
            close_session(session_id)
            va_clear_control(session_id)
            return jsonify(
                ok=True,
                status="NO_FREE_PAIR",
                message=(
                    "Aucune PAIRE-Libre ni PAIRE-En cours decon trouvée "
                    "- should verify manual"
                ),
                repartiteur=rep,
                sr=sr,
                pc_sr=pc_sr,
                deleted_count=deleted_count,
                zone_type="RADIAN" if is_radian else "SR",
                tested_transport_paths=tested_transport_paths,
                tested_transport_count=len(tested_transport_paths),
            )

        # 4. Confirmation after (+).
        va_wait_click(
            driver, "frm:dataTable94",
            session_id=session_id, delay_seconds=delay_seconds
        )

        # 5. Checkbox + final validations.
        checkbox = wait.until(EC.element_to_be_clickable((By.ID, "frm:ch_11")))
        if not checkbox.is_selected():
            driver.execute_script("arguments[0].click();", checkbox)

        va_wait_click(
            driver, "frm:bt_va",
            session_id=session_id, delay_seconds=delay_seconds
        )
        va_wait_click(
            driver, "frm:v_but_ano",
            session_id=session_id, delay_seconds=delay_seconds
        )

        close_session(session_id)
        va_clear_control(session_id)
        return jsonify(
            ok=True,
            status="FINISHED",
            message="Ré-Étude VA terminée avec succès.",
            repartiteur=rep,
            sr=sr,
            pc_sr=pc_sr,
            paire=pair_label,
            transport_path=transport_path,
            tested_transport_paths=tested_transport_paths,
            tested_transport_count=len(tested_transport_paths),
            deleted_count=deleted_count,
            zone_type="RADIAN" if is_radian else "SR",
        )

    except TimeoutException:
        return jsonify(
            ok=False,
            error="Délai dépassé pendant Ré-Étude VA. Chrome reste ouvert.",
        ), 504
    except Exception as exc:
        return jsonify(
            ok=False,
            error=f"Erreur exécution Ré-Étude VA : {exc}"
        ), 500



if __name__ == "__main__":
    from iam_adsl.config import HOST, PORT

    app.run(host=HOST, port=PORT, debug=False)
