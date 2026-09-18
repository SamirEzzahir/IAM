"""One independent polling worker; Outlook COM objects never leave its thread."""

from __future__ import annotations

import copy
import hashlib
import sys
from datetime import date, datetime, timezone
from threading import Event, Lock, Thread

from outlook_tables import SUBJECTS, extract_rows, matches_subject


def validate_options(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Configuration Outlook invalide.")
    folder = str(payload.get("folder", "")).strip().replace("\\", "/").strip("/")
    if len(folder) > 500 or (folder and any(part.strip() in {"", ".", ".."} for part in folder.split("/"))):
        raise ValueError("Indiquez un dossier, par exemple Archivage ou FTTH/Activations.")
    mode = str(payload.get("mode", "new"))
    if mode not in {"new", "since"}:
        raise ValueError("Choisissez les nouveaux emails ou une date de début.")
    since = str(payload.get("since", "")) if mode == "since" else ""
    if mode == "since":
        try:
            start_date = date.fromisoformat(since)
        except ValueError as exc:
            raise ValueError("Choisissez une date de début valide.") from exc
        if start_date > date.today():
            raise ValueError("La date de début ne peut pas être dans le futur.")
    try:
        interval = int(payload.get("interval", 30))
    except (TypeError, ValueError) as exc:
        raise ValueError("L’intervalle doit être un nombre de secondes.") from exc
    if not 10 <= interval <= 3600:
        raise ValueError("L’intervalle doit être compris entre 10 et 3600 secondes.")
    return {"folder": folder, "mode": mode, "since": since, "interval": interval}


def resolve_folder(namespace, path: str):
    """Accept paths relative to Inbox, the mailbox root, or the Outlook profile."""
    inbox = namespace.GetDefaultFolder(6)
    parts = [value.strip() for value in path.replace("\\", "/").split("/") if value.strip()]
    if not parts:
        return inbox
    # Existing Inbox-relative paths retain priority. A sibling like Archivage
    # is under Inbox.Parent; a full mailbox/archive path starts at namespace.
    roots = [inbox]
    try:
        roots.append(inbox.Parent)
    except Exception:
        pass
    roots.append(namespace)
    for root in roots:
        folder = root
        try:
            for part in parts:
                folder = folder.Folders.Item(part)
            return folder
        except Exception:
            continue
    raise ValueError(
        f"Dossier Outlook introuvable : {path}. Utilisez son nom (Archivage), "
        "un chemin (Archivage/FTTH), ou le chemin complet affiché dans Outlook "
        "(Nom de la boîte/Archivage). La boîte de réception reste surveillée."
    )


def folder_identity(folder) -> tuple[str, str]:
    return str(folder.StoreID), str(folder.EntryID)


def message_identity(message, store_id: str) -> str:
    # Internet Message-ID survives moving a message between Outlook folders.
    try:
        identity = message.PropertyAccessor.GetProperty(
            "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
        )
    except Exception:
        identity = ""
    identity = identity or str(message.EntryID)
    if not identity:
        raise ValueError("Email sans identifiant Outlook ; collecte reportée.")
    return hashlib.sha256(f"{store_id}\n{identity}".encode("utf-8")).hexdigest()


def utc_received(value) -> datetime:
    # Outlook's COM datetime has a timezone; a naive value uses the PC timezone.
    return value.astimezone(timezone.utc)


class OutlookCollector:
    def __init__(self, store):
        self.store = store
        self.lock = Lock()
        self.stop_event = Event()
        self.thread = None
        self.state = {"status": "STOPPED", "error": None, "last_scan": None,
                      "started_at": None, "logs": [], "folder_label": "", "export_error": None}

    def log(self, level: str, message: str):
        with self.lock:
            self.state["logs"].append({"time": datetime.now(timezone.utc).isoformat(),
                                       "level": level, "message": message})
            self.state["logs"] = self.state["logs"][-100:]

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def status(self):
        with self.lock:
            state = copy.deepcopy(self.state)
        return {**state, **self.store.summary(), "settings": self.store.settings(),
                "subjects": list(SUBJECTS)}

    def start(self, payload: dict):
        options = validate_options(payload)
        if sys.platform != "win32":
            raise ValueError("Cette collecte nécessite Outlook classique sur le PC Windows qui exécute /FO.")
        try:
            import pythoncom  # noqa: F401
            import win32com.client  # noqa: F401
        except ImportError as exc:
            raise ValueError("Le module Outlook manque. Relancez install.bat dans IAM-Project.") from exc
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                raise ValueError("La surveillance Outlook est déjà active.")
            now = datetime.now(timezone.utc)
            # Date-only inputs mean midnight in the Outlook PC's local timezone.
            cutoff = datetime.fromisoformat(options["since"]).astimezone(timezone.utc) if options["mode"] == "since" else now
            self.store.save_settings(options)
            self.stop_event = Event()
            self.state.update(status="STARTING", error=None, last_scan=None,
                              started_at=now.isoformat(), folder_label="", export_error=None, logs=[])
            self.thread = Thread(target=self.run, args=(options, cutoff), daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                self.state["status"] = "STOPPING"
                self.stop_event.set()

    def scan(self, folder, cutoff: datetime) -> int:
        # DASL date comparisons use UTC. Restrict reduces COM traffic on large inboxes.
        stamp = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        items = folder.Items.Restrict(f'@SQL="urn:schemas:httpmail:datereceived" >= \'{stamp}\'')
        items.Sort("[ReceivedTime]", False)
        imported = 0
        for index in range(1, items.Count + 1):
            if self.stop_event.is_set():
                break
            try:
                message = items.Item(index)
                if message.Class != 43:
                    continue
                subject = str(message.Subject or "")
                if not matches_subject(subject) or utc_received(message.ReceivedTime) < cutoff:
                    continue
                key = message_identity(message, str(folder.StoreID))
                if self.store.seen(key):
                    continue
                rows = extract_rows(str(message.HTMLBody or ""))
                metadata = {"subject": subject, "sender": str(message.SenderEmailAddress or message.SenderName or ""),
                            "received": utc_received(message.ReceivedTime).isoformat(),
                            "folder": str(folder.FolderPath)}
                if self.store.record(key, metadata, rows):
                    imported += len(rows)
                    self.log("SUCCESS" if rows else "WARNING", f"{subject} : {len(rows)} ligne(s) collectée(s)." if rows else
                             f"{subject} : aucun tableau compatible trouvé dans le corps du mail.")
            except Exception:
                # Do not checkpoint a failed item; the next poll can retry it.
                self.log("WARNING", "Un email n’a pas pu être lu ; nouvel essai à la prochaine vérification.")
        self.update(last_scan=datetime.now(timezone.utc).isoformat())
        return imported

    def scan_folders(self, namespace, path: str, cutoff: datetime) -> int:
        """Always poll Inbox, plus the optional folder, with isolated failures."""
        folders = [namespace.GetDefaultFolder(6)]
        errors = []
        if path:
            try:
                extra = resolve_folder(namespace, path)
                if folder_identity(extra) != folder_identity(folders[0]):
                    folders.append(extra)
            except ValueError as exc:
                errors.append(str(exc))
        self.update(folder_label=" + ".join(str(folder.FolderPath) for folder in folders))
        imported = 0
        for folder in folders:
            if self.stop_event.is_set():
                break
            try:
                imported += self.scan(folder, cutoff)
            except Exception:
                errors.append(f"Lecture impossible : {folder.FolderPath}. Nouvel essai à la prochaine vérification.")
        self.update(error=" ".join(errors) if errors else None)
        return imported

    def run(self, options: dict, cutoff: datetime):
        import pythoncom
        import win32com.client

        initialized = False
        namespace = outlook = None
        try:
            pythoncom.CoInitialize()
            initialized = True
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            with self.lock:
                if not self.stop_event.is_set():
                    self.state["status"] = "RUNNING"
            self.log("INFO", "Surveillance Outlook démarrée. Les emails déjà collectés sont ignorés.")
            export_dirty = True  # Recover a stale/missing Excel snapshot after restart.
            while not self.stop_event.is_set():
                try:
                    export_dirty = bool(self.scan_folders(namespace, options["folder"], cutoff)) or export_dirty
                except Exception:
                    self.update(error="Outlook est indisponible. Nouvelle tentative à la prochaine vérification.")
                    self.log("WARNING", "Vérifiez la connexion Outlook et le dossier sélectionné.")
                if export_dirty:
                    try:
                        self.store.write_excel()
                        export_dirty = False
                        self.update(export_error=None)
                    except OSError:
                        self.update(export_error="Fermez collecte_outlook.xlsx dans Excel pour actualiser le fichier. Les données restent sauvegardées et téléchargeables.")
                self.stop_event.wait(options["interval"])
            self.update(status="STOPPED")
            self.log("INFO", "Surveillance arrêtée. Les données collectées sont conservées.")
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else "Impossible d’accéder à Outlook. Ouvrez Outlook classique avec votre compte sur ce PC, puis relancez la surveillance."
            self.update(status="ERROR", error=message)
            self.log("ERROR", message)
        finally:
            namespace = outlook = None
            if initialized:
                pythoncom.CoUninitialize()
