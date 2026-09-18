"""Normalize FTTH tables from Outlook HTML without executing mail content."""

from __future__ import annotations

import json
import re
import unicodedata

from bs4 import BeautifulSoup


SUBJECTS = (
    "Activation commande FTTH", "Creation CD FTTH", "CREATION GPON",
    "commandes GPON", "Activation Mise en",
)
PARSER_VERSION = 2
COLUMNS = (
    ("commande", "Commande"), ("ont", "ONT"), ("version", "Version"),
    ("technologie", "Technologie"), ("client", "Client"), ("login", "Login"),
    ("msan", "MSAN"), ("odf", "ODF"), ("pco", "PCO"), ("brin", "Brin"),
    ("type_pco", "Type PCO"), ("pose_pco", "Pose PCO"),
    ("pose_splitter", "Pose nouveau splitter"), ("gps_pco", "GPS PCO"),
    ("gps_splitter", "GPS nouveau splitter"), ("longueur", "Longueur"),
    ("autres", "Autres colonnes"),
)


def clean(value: str) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", clean(value)).casefold()
    return "".join(c for c in value if not unicodedata.combining(c))


def matches_subject(subject: str) -> bool:
    return any(normalized(fragment) in normalized(subject) for fragment in SUBJECTS)


def header_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalized(value))


ALIASES = {
    "commande": ("Commande GPON", "COM", "Commande", "CMD"),
    "ont": ("ONT",), "version": ("Version",), "technologie": ("Technologie",),
    "client": ("Intitulé client", "Nom du client", "Nom client", "Client"),
    "login": ("Login",), "odf": ("MSAN / SRO", "ODF", "SRO"),
    "msan": ("MSAN", "MSAN OLT"),
    "pco": ("PCO",), "brin": ("brin", "num de Brin", "Numéro de brin"),
    "type_pco": ("catégorie", "TYPE DE PCO", "Type PCO"),
    "pose_pco": ("Pose PCO(O/N)", "Pose PCO", "NOUVEAU PCO"),
    "pose_splitter": ("Pose Nouveau Splitter O/N", "Pose nouveau splitter",),
    "gps_pco": ("GPS PCO",), "gps_x": ("CGPS PCO x", "GPS PCO x"),
    "gps_y": ("CGPS PCO y", "GPS PCO y"),
    "gps_splitter": ("GPS NV Splitter", "GPS nouveau splitter"),
    "longueur": ("1FO", "LONGEUR", "Longueur"),
}
HEADER_MAP = {header_key(alias): key for key, aliases in ALIASES.items() for alias in aliases}


def table_grid(table) -> list[list[str]]:
    """Expand merged cells while excluding rows belonging to nested tables."""
    grid, carried = [], {}
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells = tr.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        # Outlook layout tables often wrap the real data table.
        if any(cell.find("table") for cell in cells):
            carried = {}
            continue
        row = {column: value for column, (value, _remaining) in carried.items()}
        next_carried = {
            column: (value, remaining - 1)
            for column, (value, remaining) in carried.items() if remaining > 1
        }
        column = 0
        for cell in cells:
            while column in row:
                column += 1
            try:
                colspan = min(100, max(1, int(cell.get("colspan", 1))))
                rowspan = min(100, max(1, int(cell.get("rowspan", 1))))
            except (TypeError, ValueError):
                colspan = rowspan = 1
            value = clean(cell.get_text(" ", strip=True))
            for offset in range(colspan):
                row[column + offset] = value
                if rowspan > 1:
                    next_carried[column + offset] = (value, rowspan - 1)
            column += colspan
        carried = next_carried
        grid.append([row.get(i, "") for i in range(max(row, default=-1) + 1)])
    return grid


def extract_rows(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    for ignored in soup(["script", "style"]):
        ignored.decompose()
    results, seen = [], set()
    for table in soup.find_all("table"):
        headers = keys = None
        for cells in table_grid(table):
            candidate = [HEADER_MAP.get(header_key(cell)) for cell in cells]
            if "commande" in candidate and len(set(candidate) - {None}) >= 3:
                headers, keys = cells, candidate
                continue
            if keys is None or len(cells) != len(keys):
                continue
            row = {key: "" for key, _label in COLUMNS}
            extras, odf, coordinates = {}, [], {}
            for header, key, value in zip(headers, keys, cells):
                if not value:
                    continue
                if key == "odf":
                    if value not in odf:
                        odf.append(value)
                elif key in {"gps_x", "gps_y"}:
                    coordinates[key] = value
                elif key:
                    if not row[key]:
                        row[key] = value
                    elif row[key] != value:
                        row[key] += " | " + value
                else:
                    extras[header or "Sans titre"] = value
            if not row["commande"] or not any(row[k] for k in ("ont", "client", "login", "pco")):
                continue
            row["odf"] = " | ".join(odf)
            if coordinates:
                pair = " / ".join(coordinates.get(key, "—") for key in ("gps_x", "gps_y"))
                row["gps_pco"] = " | ".join(filter(None, (row["gps_pco"], pair)))
            row["autres"] = json.dumps(extras, ensure_ascii=False) if extras else ""
            signature = tuple(row.items())
            if signature not in seen:
                seen.add(signature)
                results.append(row)
    return results
