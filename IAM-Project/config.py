"""Small JSON configuration store for the local Selenium application."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "data" / "config.json"
CONFIG_LOCK = Lock()

WIMTECH_URL = (
    "http://wimtech/Mutation/mutationIndividuelleGPON.jsf?"
    "a=PFPOTT%5D%5CG&b=Nnuq}o7-./1&load=1"
)
WIAM_URL = (
    "https://wiam/commande_recherche_critere.jsp?"
    "mfunc=941&oid=L5%3A35574&ctx=M"
)
COMMANDES_URL = "https://10.96.18.189/commandes"

FIXED_URLS = {
    "wimtech_url": WIMTECH_URL,
    "wiam_url": WIAM_URL,
    "commandes_url": COMMANDES_URL,
}

DEFAULT_CONFIG = {
    **FIXED_URLS,
    "test_login": "I10260472",
    "timeout_seconds": 20,
    "execution_mode": "visible",
    "headless": False,
    "debug_mode": False,
    "action_delay_seconds": 0,
    "wiam_username": "",
    "wiam_password": "",
}


def load_config() -> dict:
    with CONFIG_LOCK:
        if not CONFIG_PATH.exists():
            return dict(DEFAULT_CONFIG)
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(DEFAULT_CONFIG)

    result = dict(DEFAULT_CONFIG)
    if isinstance(saved, dict):
        result.update({key: saved[key] for key in DEFAULT_CONFIG if key in saved})
        # Migrate configurations created before the three execution modes.
        if "execution_mode" not in saved:
            result["execution_mode"] = (
                "headless" if bool(saved.get("headless", False)) else "visible"
            )
    if result.get("execution_mode") not in {"visible", "headless", "http"}:
        result["execution_mode"] = "visible"
    # Keep the legacy key for all existing Selenium collectors.  In HTTP mode,
    # unsupported pages deliberately fall back to a visible Chrome window.
    result["headless"] = result["execution_mode"] == "headless"
    # These internal endpoints are application constants, not user settings.
    # Always override legacy values that may still exist in config.json.
    result.update(FIXED_URLS)
    return result


def save_config(payload: dict) -> dict:
    current = load_config()
    login = str(payload.get("test_login", current["test_login"])).strip()

    if not login:
        raise ValueError("Le Login de test est obligatoire.")

    try:
        timeout = int(payload.get("timeout_seconds", current["timeout_seconds"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("Le délai doit être un nombre entier.") from exc
    if timeout < 5 or timeout > 120:
        raise ValueError("Le délai doit être compris entre 5 et 120 secondes.")

    try:
        action_delay = float(payload.get("action_delay_seconds", current["action_delay_seconds"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("Le délai Debug Selenium doit être un nombre.") from exc
    if action_delay < 0 or action_delay > 60:
        raise ValueError("Le délai Debug Selenium doit être compris entre 0 et 60 secondes.")

    wiam_password = str(payload.get("wiam_password", "")).strip() or current["wiam_password"]
    execution_mode = payload.get("execution_mode")
    if execution_mode is None:
        if "headless" in payload:
            execution_mode = "headless" if bool(payload["headless"]) else "visible"
        else:
            execution_mode = current.get("execution_mode", "visible")
    execution_mode = str(execution_mode).strip().lower()
    if execution_mode not in {"visible", "headless", "http"}:
        raise ValueError("Mode d’exécution invalide.")
    result = {
        **FIXED_URLS,
        "test_login": login,
        "timeout_seconds": timeout,
        "execution_mode": execution_mode,
        "headless": execution_mode == "headless",
        "debug_mode": bool(payload.get("debug_mode", current["debug_mode"])),
        "action_delay_seconds": action_delay,
        "wiam_username": str(payload.get("wiam_username", current["wiam_username"])).strip(),
        "wiam_password": wiam_password,
    }

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_suffix(".tmp")
    with CONFIG_LOCK:
        temporary.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(CONFIG_PATH)
    return result
