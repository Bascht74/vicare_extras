"""Stub of homeassistant.core."""

from enum import StrEnum
from typing import Any


def callback(func):
    return func


class HomeAssistant:
    """Placeholder, the tests use tests.unit.fakes.FakeHass."""


class SupportsResponse(StrEnum):
    NONE = "none"
    OPTIONAL = "optional"
    ONLY = "only"


class ServiceCall:
    def __init__(self, hass, domain, service, data=None, return_response=False):
        self.hass = hass
        self.domain = domain
        self.service = service
        self.data = dict(data or {})
        self.return_response = return_response


ServiceResponse = dict[str, Any] | None
