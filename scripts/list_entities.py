#!/usr/bin/env python3
"""Print the entity list of the integration as a Markdown table.

Run from the repository root:  python scripts/list_entities.py [--report]

The table is generated from ``specs.py`` and the translations, so it cannot
drift from the code. ``--report`` adds the English name and the key column.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "vicare_extras"

_spec = importlib.util.spec_from_file_location("vicare_extras_specs", COMPONENT / "specs.py")
specs = importlib.util.module_from_spec(_spec)
sys.modules["vicare_extras_specs"] = specs
_spec.loader.exec_module(specs)

SPECIAL_UNITS = {
    specs.SPECIAL_HISTORY: "kWh",
    specs.SPECIAL_SUMMARY: "kWh",
}


def names(language: str) -> dict[str, dict[str, str]]:
    data = json.loads((COMPONENT / "translations" / f"{language}.json").read_text(encoding="utf-8"))
    return {
        domain: {key: value["name"] for key, value in entities.items()}
        for domain, entities in data["entity"].items()
    }


def rows() -> list[dict[str, str]]:
    de, en = names("de"), names("en")
    result = []
    for spec in specs.ALL_SPECS:
        result.append(
            {
                "scope": spec.scope,
                "platform": spec.platform,
                "key": spec.key,
                "de": de[spec.platform][spec.key],
                "en": en[spec.platform][spec.key],
                "unit": "" if spec.kind != specs.KIND_NUMBER else (spec.unit or ""),
                "enabled": "ja" if spec.enabled else "nein",
                "source": " / ".join(f"`{feature}` → `{prop}`" for feature, prop in spec.sources),
            }
        )
    for spec in specs.SPECIAL_SPECS:
        result.append(
            {
                "scope": specs.SCOPE_HEATING,
                "platform": "sensor",
                "key": spec.key,
                "de": de["sensor"][spec.key],
                "en": en["sensor"][spec.key],
                "unit": SPECIAL_UNITS.get(spec.kind, ""),
                "enabled": "ja" if spec.enabled else "nein",
                "source": (" + " if spec.require == "all" else " / ").join(f"`{feature}`" for feature in spec.features),
            }
        )
    return result


def main() -> int:
    report = "--report" in sys.argv
    for scope, title in ((specs.SCOPE_HEATING, "Heizgerät"), (specs.SCOPE_ROOM, "Räume")):
        print(f"\n**{title}**\n")
        if report:
            print("| Plattform | Key | Name (de) | Name (en) | Einheit | Standard aktiv | Quelle |")
            print("| --- | --- | --- | --- | --- | --- | --- |")
        else:
            print("| Plattform | Name | Einheit | Standard aktiv | Quelle |")
            print("| --- | --- | --- | --- | --- |")
        for row in rows():
            if row["scope"] != scope:
                continue
            if report:
                print(f"| {row['platform']} | `{row['key']}` | {row['de']} | {row['en']} | {row['unit']} | {row['enabled']} | {row['source']} |")
            else:
                print(f"| {row['platform']} | {row['de']} | {row['unit']} | {row['enabled']} | {row['source']} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
