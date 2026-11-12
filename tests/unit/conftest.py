"""Configuration of the unit tests.

These tests run without Home Assistant: the minimal stand-ins in ``stubs/``
are put first on ``sys.path`` (also when Home Assistant happens to be
installed, so the result does not depend on the environment). They exercise
this integration's own logic; they do not prove compatibility with the real
Home Assistant. Tests against the real Home Assistant live in ``tests/ha``.

Run with:  pytest tests/unit
"""

from __future__ import annotations

from pathlib import Path
import sys

_HERE = Path(__file__).parent
_REPO = _HERE.parent.parent

if "homeassistant" in sys.modules or "voluptuous" in sys.modules:
    raise RuntimeError(
        "tests/unit must run in its own pytest session (pytest tests/unit)"
    )

sys.path.insert(0, str(_HERE / "stubs"))
sys.path.insert(0, str(_REPO))
