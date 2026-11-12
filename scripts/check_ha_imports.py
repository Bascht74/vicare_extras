#!/usr/bin/env python3
"""Check every Home Assistant import of the integration against a core checkout.

Usage:  python scripts/check_ha_imports.py /path/to/home-assistant-core

For each ``from homeassistant.x import name`` in custom_components/ the script
verifies that the module exists in the checkout and that ``name`` is defined
or imported at module level there. The core sources are only read as text,
never executed. This catches renamed or removed APIs; it cannot check call
signatures or runtime behaviour.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "vicare_extras"


def module_file(core: Path, module: str) -> Path | None:
    base = core.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def defines(source: str, name: str) -> bool:
    escaped = re.escape(name)
    patterns = (
        rf"^(?:class|def|async def)\s+{escaped}\b",
        rf"^(?:type\s+)?{escaped}\s*(?::[^=\n]+)?=",
        rf"^(?:from\s+\S+\s+)?import\s+(?:.*\b)?{escaped}\b",
        rf"^\s+{escaped},?\s*(?:#.*)?$",  # name inside a parenthesised import
        rf"\bas\s+{escaped}\b",
    )
    return any(re.search(pattern, source, re.MULTILINE) for pattern in patterns)


def main() -> int:
    if len(sys.argv) != 2 or not (core := Path(sys.argv[1])).joinpath("homeassistant").is_dir():
        print(__doc__)
        return 2

    problems: list[str] = []
    checked = 0
    for path in sorted(COMPONENT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            if not node.module.startswith("homeassistant"):
                continue
            file = module_file(core, node.module)
            if file is None:
                problems.append(f"{path.name}:{node.lineno}: module {node.module} not found")
                continue
            source = file.read_text(encoding="utf-8")
            for alias in node.names:
                checked += 1
                submodule = module_file(core, f"{node.module}.{alias.name}")
                if submodule is None and not defines(source, alias.name):
                    problems.append(
                        f"{path.name}:{node.lineno}: {node.module}.{alias.name} not found"
                    )
    if problems:
        print("\n".join(f"FAIL: {problem}" for problem in problems))
        return 1
    print(f"OK: {checked} imported Home Assistant names exist in {core}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
