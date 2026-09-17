"""Read-only WIAM CMD-to-Login lookup over an HTTP session."""

from __future__ import annotations

import os
import warnings
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning


def _text(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split()) if element else ""


def _form_values(form) -> dict[str, str]:
    """Collect ordinary successful controls from an HTML form."""

    values: dict[str, str] = {}
    for control in form.select("input[name], textarea[name], select[name]"):
        if control.has_attr("disabled"):
            continue
        name = str(control.get("name") or "").strip()
        if not name:
            continue
        tag = control.name.lower()
        control_type = str(control.get("type") or "text").lower()
        if control_type in {"button", "file", "image", "reset", "submit"}:
            continue
        if control_type in {"checkbox", "radio"} and not control.has_attr("checked"):
            continue
        if tag == "select":
            option = control.select_one("option[selected]") or control.select_one("option")
            values[name] = str(option.get("value", _text(option))) if option else ""
        elif tag == "textarea":
            values[name] = control.get_text()
        else:
            values[name] = str(control.get("value") or "")
    return values


class WiamHttpClient:
    """Keep WIAM authentication cookies and perform read-only searches."""

    def __init__(self, config: dict):
        self.url = str(config.get("wiam_url") or "").strip()
        self.username = str(config.get("wiam_username") or "").strip()
        self.password = str(config.get("wiam_password") or "")
        self.timeout = int(config.get("timeout_seconds") or 20)
        self.verify_tls = os.getenv("WIAM_VERIFY_TLS", "0").lower() in {
            "1", "true", "yes", "on",
        }
        if not self.url:
            raise ValueError("URL WIAM absente.")
        if not self.username or not self.password:
            raise ValueError("Configurez le Login et le mot de passe WIAM.")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "FB-EMM/1.0 (WIAM read-only HTTP client)",
            "Accept": "text/html,application/xhtml+xml",
        })
        self._authenticated = False

    def close(self) -> None:
        self.session.close()

    def _request(self, method: str, url: str, **kwargs):
        try:
            with warnings.catch_warnings():
                if not self.verify_tls:
                    warnings.simplefilter("ignore", InsecureRequestWarning)
                response = self.session.request(
                    method,
                    url,
                    timeout=self.timeout,
                    verify=self.verify_tls,
                    allow_redirects=True,
                    **kwargs,
                )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            raise ValueError(f"WIAM HTTP inaccessible : {exc}") from exc

    def _submit(self, response, form, values: dict[str, str]):
        action = str(form.get("action") or response.url).strip()
        if action.lower().startswith("javascript:"):
            raise ValueError("Formulaire WIAM HTTP non compatible (action JavaScript).")
        target = urljoin(response.url, action)
        method = str(form.get("method") or "get").strip().lower()
        if method == "post":
            return self._request("POST", target, data=values)
        return self._request("GET", target, params=values)

    @staticmethod
    def _soup(response) -> BeautifulSoup:
        return BeautifulSoup(response.content, "html.parser")

    def _authenticate(self):
        response = self._request("GET", self.url)
        soup = self._soup(response)
        login_field = soup.select_one("#login, input[name='login']")
        password_field = soup.select_one("#password, input[type='password']")
        if not login_field and not password_field:
            self._authenticated = True
            return response
        if not login_field or not password_field:
            raise ValueError("Formulaire d’authentification WIAM incomplet.")
        form = login_field.find_parent("form") or password_field.find_parent("form")
        if form is None:
            raise ValueError("Formulaire d’authentification WIAM introuvable.")
        values = _form_values(form)
        login_name = str(login_field.get("name") or login_field.get("id") or "login")
        password_name = str(password_field.get("name") or password_field.get("id") or "password")
        values[login_name] = self.username
        values[password_name] = self.password
        response = self._submit(response, form, values)
        authenticated_soup = self._soup(response)
        if authenticated_soup.select_one("#login, input[name='login']"):
            raise ValueError("Authentification WIAM HTTP refusée.")
        self._authenticated = True
        return response

    def _open_search_page(self):
        response = self._authenticate() if not self._authenticated else self._request("GET", self.url)
        soup = self._soup(response)
        if soup.select_one("input[name='num_commande']"):
            return response, soup

        # WIAM can redirect to Accueil after authentication.  Retry the fixed
        # Commandes URL with the authenticated session, then follow its menu
        # link if the redirect still lands on Accueil.
        response = self._request("GET", self.url)
        soup = self._soup(response)
        if soup.select_one("input[name='num_commande']"):
            return response, soup
        link = next(
            (
                anchor for anchor in soup.select("a[href]")
                if "commande_recherche_critere.jsp" in str(anchor.get("href") or "").lower()
            ),
            None,
        )
        if link is None:
            raise ValueError("Page de recherche CMD WIAM introuvable en mode HTTP.")
        response = self._request("GET", urljoin(response.url, str(link.get("href"))))
        soup = self._soup(response)
        if not soup.select_one("input[name='num_commande']"):
            raise ValueError("Champ CMD WIAM introuvable en mode HTTP.")
        return response, soup

    def lookup_login(self, command: str) -> str:
        response, soup = self._open_search_page()
        command_field = soup.select_one("input[name='num_commande']")
        form = command_field.find_parent("form") if command_field else None
        if form is None:
            raise ValueError("Formulaire de recherche CMD WIAM introuvable.")
        values = _form_values(form)
        values["num_commande"] = str(command).strip()
        search_radio = form.select_one("input[type='radio'][value='1'][name]")
        if search_radio is not None:
            values[str(search_radio.get("name"))] = "1"
        response = self._submit(response, form, values)
        cells = self._soup(response).select("td.datalistfield")
        login = _text(cells[1]) if len(cells) >= 2 else ""
        if not login:
            raise ValueError(f"Aucun Login WIAM trouvé pour {command}.")
        return login

