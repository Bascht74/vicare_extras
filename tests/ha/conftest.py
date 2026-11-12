"""Tests against the real Home Assistant.

NOT EXECUTED by the author: Home Assistant could not be installed in the
environment this integration was written in. They are meant for a development
machine with ``pytest-homeassistant-custom-component`` (which brings Home
Assistant) and ``PyViCare`` installed:

    pytest tests/ha

Run them in their own pytest session, never together with ``tests/unit``
(which replaces the ``homeassistant`` package by stand-ins).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# The plugin registers itself when installed; without it nothing is collected.
if importlib.util.find_spec("pytest_homeassistant_custom_component") is None:
    collect_ignore_glob = ["test_*.py"]


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/vicare_extras."""
    return
