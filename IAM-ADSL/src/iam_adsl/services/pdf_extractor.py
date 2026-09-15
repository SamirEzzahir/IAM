"""Extract Cuivre CMD numbers from operational PDF tables.

This module is intentionally independent from Flask and Selenium so it can be
reused in another application or from the command line.

Required PDF columns:
    Ccna, etat, Dde Wiam, dde sara

Supported modes:
    etude: Ccna empty, etat EI/IR/EE
    va:    Ccna empty, etat VA

For both modes, ``Dde Wiam`` must either start with ``D`` (degroupage) or be a
decimal number (IAM ADSL). The extracted CMD is the decimal ``dde sara`` value.
Rows with a non-empty Ccna value, including FO, are always ignored.
"""

from __future__ import annotations

import argparse
from collections import Counter
from io import BytesIO
import json
from pathlib import Path
import re
import unicodedata
from typing import BinaryIO, Dict, Iterable, Optional, Tuple, Union

import pdfplumber


MAX_PDF_BYTES = 20 * 1024 * 1024
VALID_MODES = {"etude", "va"}
ETUDE_STATES = {"EI", "IR", "EE"}


class PDFExtractionError(ValueError):
    """Raised when a PDF cannot be read as a compatible CMD table."""


def _text(value: object) -> str:
    """Return normalized single-line cell text."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _compact(value: object) -> str:
    """Return a value without whitespace, useful for identifiers."""
    return re.sub(r"\s+", "", _text(value))


def _header_key(value: object) -> str:
    value = unicodedata.normalize("NFKD", _text(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", value.casefold())


HEADER_ALIASES = {
    "ccna": {"ccna"},
    "etat": {"etat", "state", "status"},
    "dde_wiam": {"ddewiam", "demandewiam"},
    "dde_sara": {"ddesara", "demandesara"},
}


def _find_header(row: Iterable[object]) -> Optional[Dict[str, int]]:
    keys = [_header_key(cell) for cell in row]
    mapping: dict[str, int] = {}
    for field, aliases in HEADER_ALIASES.items():
        for index, key in enumerate(keys):
            if key in aliases:
                mapping[field] = index
                break
    return mapping if len(mapping) == len(HEADER_ALIASES) else None


def classify_cuivre_row(
    ccna: object,
    etat: object,
    dde_wiam: object,
    dde_sara: object,
    mode: str,
) -> Tuple[Optional[str], Optional[str], str]:
    """Classify one row.

    Returns ``(cmd, classification, ignored_reason)``. When the row is kept,
    ``ignored_reason`` is an empty string. This public function is useful when
    callers already have rows from Excel, CSV, a database, or another parser.
    """
    mode = _text(mode).casefold()
    if mode not in VALID_MODES:
        raise ValueError("mode must be 'etude' or 'va'")

    ccna_value = _compact(ccna).upper()
    state = _compact(etat).upper()
    wiam = _compact(dde_wiam).upper()
    sara = _compact(dde_sara)

    # Cuivre only: FO and every other non-empty Ccna value are excluded.
    if ccna_value:
        return None, None, "ccna_not_empty"

    expected_states = ETUDE_STATES if mode == "etude" else {"VA"}
    if state not in expected_states:
        return None, None, "etat_not_matching"

    if not sara.isdecimal():
        return None, None, "dde_sara_not_decimal"

    if wiam.startswith("D"):
        classification = (
            "cuivre_degroupage_adsl" if mode == "etude"
            else "cuivre_degroupage"
        )
    elif wiam.isdecimal():
        classification = "cuivre_iam_adsl"
    else:
        return None, None, "dde_wiam_invalid"

    return sara, classification, ""


def _extract_from_pdf(pdf: pdfplumber.PDF, mode: str) -> dict:
    commands: list[str] = []
    seen_commands: set[str] = set()
    classifications: Counter[str] = Counter()
    ignored: Counter[str] = Counter()
    compatible_tables = 0
    rows_seen = 0

    for page in pdf.pages:
        for table in page.extract_tables() or []:
            header: Optional[Dict[str, int]] = None
            for row in table or []:
                if not row:
                    continue

                possible_header = _find_header(row)
                if possible_header is not None:
                    header = possible_header
                    compatible_tables += 1
                    continue

                if header is None:
                    continue

                max_index = max(header.values())
                if len(row) <= max_index:
                    ignored["incomplete_row"] += 1
                    continue

                rows_seen += 1
                cmd, classification, reason = classify_cuivre_row(
                    row[header["ccna"]],
                    row[header["etat"]],
                    row[header["dde_wiam"]],
                    row[header["dde_sara"]],
                    mode,
                )
                if cmd is None:
                    ignored[reason or "not_matching"] += 1
                    continue

                if cmd in seen_commands:
                    ignored["duplicate_cmd"] += 1
                    continue

                seen_commands.add(cmd)
                commands.append(cmd)
                classifications[classification or "unknown"] += 1

    if compatible_tables == 0:
        raise PDFExtractionError(
            "Aucun tableau compatible trouvé. Le PDF doit contenir les colonnes "
            "Ccna, etat, Dde Wiam et dde sara. Les PDF scannés nécessitent un OCR."
        )

    return {
        "mode": mode,
        "commands": commands,
        "count": len(commands),
        "classifications": dict(classifications),
        "ignored": dict(ignored),
        "pages": len(pdf.pages),
        "compatible_tables": compatible_tables,
        "rows_seen": rows_seen,
    }


def extract_cmds_from_pdf_bytes(pdf_bytes: bytes, mode: str) -> dict:
    """Extract commands from PDF bytes and return a JSON-serializable result."""
    mode = _text(mode).casefold()
    if mode not in VALID_MODES:
        raise PDFExtractionError("Mode invalide : utilisez 'etude' ou 'va'.")
    if not pdf_bytes:
        raise PDFExtractionError("Le fichier PDF est vide.")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise PDFExtractionError("Le fichier PDF dépasse la limite de 20 Mo.")
    if not pdf_bytes.lstrip().startswith(b"%PDF-"):
        raise PDFExtractionError("Le fichier sélectionné n'est pas un PDF valide.")

    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            return _extract_from_pdf(pdf, mode)
    except PDFExtractionError:
        raise
    except Exception as exc:
        raise PDFExtractionError(f"Lecture PDF impossible : {exc}") from exc


def extract_cmds_from_pdf(
    source: Union[str, Path, BinaryIO],
    mode: str,
) -> dict:
    """Extract commands from a path or an already-open binary stream."""
    if hasattr(source, "read"):
        data = source.read()
    else:
        data = Path(source).read_bytes()
    return extract_cmds_from_pdf_bytes(data, mode)


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract Cuivre CMD numbers from a compatible PDF table."
    )
    parser.add_argument("pdf", type=Path, help="PDF file to read")
    parser.add_argument(
        "--mode", choices=sorted(VALID_MODES), required=True,
        help="etude for EI/IR/EE, or va for VA",
    )
    parser.add_argument(
        "--json", action="store_true", help="print the complete JSON result",
    )
    return parser


def main() -> int:
    args = _build_cli().parse_args()
    try:
        result = extract_cmds_from_pdf(args.pdf, args.mode)
    except (OSError, PDFExtractionError) as exc:
        raise SystemExit(f"Erreur: {exc}") from exc

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("\n".join(result["commands"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
