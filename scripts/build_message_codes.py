#!/usr/bin/env python3
"""Build custom_components/vicare_extras/data/message_codes.json.

Run from the repository root:  python scripts/build_message_codes.py

Inputs (plain "CODE|TEXT" lines, "#" starts a comment):
  scripts/message_sources/viessmann_6200041_de.txt   Viessmann service manual
  scripts/message_sources/vieventlog_de.txt          ViEventLog error_codes.go

The Viessmann text wins. ViEventLog texts are only taken for codes the
Viessmann document does not list, and are marked with source "vieventlog".
With --check the script only verifies that the JSON file is up to date.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "scripts" / "message_sources"
TARGET = ROOT / "custom_components" / "vicare_extras" / "data" / "message_codes.json"
CODE = re.compile(r"^([A-Z])\.0*(\d+)$")

META = {
    "viessmann": {
        "title": (
            "Serviceanleitung für die Fachkraft: Viessmann One Base. "
            "Systemkonfiguration und Diagnose für Wärmepumpen mit Viessmann One Base"
        ),
        "document": "6200041, DE 6/2024",
        "products": "Vitocal 150-A, 151-A, 250-A, 252-A",
        "language": "de",
    },
    "vieventlog": {
        "title": "ViEventLog, error_codes.go",
        "url": "https://github.com/mschneider82/vieventlog",
        "commit": "bd40a11e4789c381d5e3ff1712c039dbdcb1a1b9",
        "license": "MIT, Copyright (c) 2025 Matthias Schneider",
        "language": "de",
    },
}


def normalize(code: str) -> str:
    """Return the canonical spelling: letter, dot, number without leading zeros."""
    match = CODE.match(code.strip().upper())
    if match is None:
        raise ValueError(f"not a message code: {code!r}")
    return f"{match.group(1)}.{int(match.group(2))}"


def read(name: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, line in enumerate((SOURCES / name).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        code, _, text = line.partition("|")
        if not text.strip():
            raise ValueError(f"{name}:{number}: no text")
        result.setdefault(normalize(code), text.strip())
    return result


def build() -> dict:
    viessmann = read("viessmann_6200041_de.txt")
    vieventlog = read("vieventlog_de.txt")
    codes: dict[str, dict[str, str]] = {}
    for code, text in viessmann.items():
        codes[code] = {"de": text, "source": "viessmann"}
    for code, text in vieventlog.items():
        codes.setdefault(code, {"de": text, "source": "vieventlog"})
    ordered = dict(sorted(codes.items(), key=lambda item: (item[0][0], int(item[0][2:]))))
    return {"version": 1, "sources": META, "codes": ordered}


def main() -> int:
    content = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if "--check" in sys.argv:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != content:
            print(f"FAIL: {TARGET.relative_to(ROOT)} is not up to date, run the script")
            return 1
        print(f"OK: {TARGET.relative_to(ROOT)} is up to date")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(content, encoding="utf-8")
    table = json.loads(content)["codes"]
    by_class: dict[str, dict[str, int]] = {}
    for code, entry in table.items():
        counts = by_class.setdefault(code[0], {})
        counts[entry["source"]] = counts.get(entry["source"], 0) + 1
    print(f"wrote {TARGET.relative_to(ROOT)}: {len(table)} codes {by_class}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
