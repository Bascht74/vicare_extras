#!/usr/bin/env python3
"""Build custom_components/vicare_extras/data/message_codes.json.

Run from the repository root:  python scripts/build_message_codes.py

Input: scripts/message_sources/messages_de.txt with one "CODE|SOURCE|TEXT"
line per message ("#" starts a comment). The texts are this project's own
wording; SOURCE says where the meaning comes from (see the header of that
file). Sources that are not confirmed by a Viessmann document are marked
``"verified": false`` and the integration shows their texts as unverified.

With --check the script only verifies that the JSON file is up to date.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FILE = ROOT / "scripts" / "message_sources" / "messages_de.txt"
TARGET = ROOT / "custom_components" / "vicare_extras" / "data" / "message_codes.json"
CODE = re.compile(r"^([A-Z])\.0*(\d+)$")

NOTE = (
    "Wording by the ViCare Extras project (not copied from any manual). "
    "'source' names where the meaning of a code comes from; entries with "
    "'verified': false are not confirmed by a Viessmann document."
)

SOURCES = {
    "viessmann": {
        "verified": True,
        "meaning_from": (
            "Viessmann service manual 'Viessmann One Base. Systemkonfiguration und "
            "Diagnose für Wärmepumpen mit Viessmann One Base', 6200041 "
            "(DE 6/2024 and DE 7/2024), Vitocal 150-A, 151-A, 250-A, 252-A"
        ),
    },
    "viessmann_6221420": {
        "verified": True,
        "meaning_from": (
            "Viessmann service manual 'Einzelraumregelung mit ViCare Smart "
            "Climate', 6221420, DE 2/2025"
        ),
    },
    "viessmann_6179923": {
        "verified": True,
        "meaning_from": (
            "Viessmann service manual for heat pumps with Viessmann One Base, "
            "6179923, DE 3/2022 (Vitocal 200-S/222-S, 250-A/252-A, 250-AH)"
        ),
    },
    "vieventlog": {
        "verified": False,
        "meaning_from": (
            "ViEventLog, error_codes.go, commit bd40a11 "
            "(https://github.com/mschneider82/vieventlog, MIT, "
            "Copyright (c) 2025 Matthias Schneider); text as in that project"
        ),
    },
    "fhem": {
        "verified": False,
        "meaning_from": (
            "FHEM module 98_vitoconnect.pm, commit 38dac8d "
            "(https://github.com/fhem/fhem-mirror); text as in that project"
        ),
    },
}


def normalize(code: str) -> str:
    """Return the canonical spelling: letter, dot, number without leading zeros."""
    match = CODE.match(code.strip().upper())
    if match is None:
        raise ValueError(f"not a message code: {code!r}")
    return f"{match.group(1)}.{int(match.group(2))}"


def build() -> dict:
    codes: dict[str, dict[str, object]] = {}
    for number, line in enumerate(SOURCE_FILE.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("|", 2)
        if len(parts) != 3 or not parts[2].strip():
            raise ValueError(f"{SOURCE_FILE.name}:{number}: expected CODE|SOURCE|TEXT")
        code, source, text = normalize(parts[0]), parts[1].strip(), parts[2].strip()
        if source not in SOURCES:
            raise ValueError(f"{SOURCE_FILE.name}:{number}: unknown source {source!r}")
        if code in codes:
            raise ValueError(f"{SOURCE_FILE.name}:{number}: {code} listed twice")
        entry: dict[str, object] = {"de": text, "source": source}
        if not SOURCES[source]["verified"]:
            entry["verified"] = False
        codes[code] = entry
    ordered = dict(sorted(codes.items(), key=lambda item: (item[0][0], int(item[0][2:]))))
    return {"version": 2, "note": NOTE, "sources": SOURCES, "codes": ordered}


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
