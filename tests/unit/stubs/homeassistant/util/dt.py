"""Stub of homeassistant.util.dt."""

from datetime import datetime

# Tests set this to pin the clock.
NOW: datetime | None = None


def now(time_zone=None):
    return NOW or datetime.now()
