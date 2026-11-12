"""Checks against the real PyViCare code (no network, fake HTTP session).

Skipped unless PyViCare is importable. Either install it (``pip install
PyViCare==2.63.0``) or point ``PYVICARE_SRC`` at a source checkout. When
authlib is missing, a minimal stand-in from ``stubs_authlib`` is used.

These tests pin down the PyViCare behaviour this integration relies on:
* looking at ``_cache`` never performs a request, a public read may;
* how ``oauth_manager.get`` reports "not found", rate limiting and non-JSON
  answers.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import importlib.util
import os
from pathlib import Path
import sys

import pytest

if source := os.environ.get("PYVICARE_SRC"):
    sys.path.insert(0, source)
if importlib.util.find_spec("PyViCare") is None:
    pytest.skip("PyViCare is not installed", allow_module_level=True)
if importlib.util.find_spec("authlib") is None:
    sys.path.append(str(Path(__file__).parent / "stubs_authlib"))

from PyViCare.PyViCareAbstractOAuthManager import (  # noqa: E402
    API_BASE_URL,
    AbstractViCareOAuthManager,
)
from PyViCare.PyViCareCachedServiceViaGateway import (  # noqa: E402
    ViCareCachedServiceViaGateway,
)
from PyViCare.PyViCareService import ViCareDeviceAccessor  # noqa: E402
import requests  # noqa: E402

from custom_components.vicare_extras import bridge  # noqa: E402
from custom_components.vicare_extras.errors import ViCareExtrasError  # noqa: E402
from custom_components.vicare_extras.event_history import (  # noqa: E402
    fetch_event_history,
)
from homeassistant.config_entries import ConfigEntry  # noqa: E402

from . import fakes  # noqa: E402
from .test_event_history import FALLBACK, PRIMARY, event, page  # noqa: E402


class CountingManager:
    """OAuth manager double for the cached service: counts requests."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str):
        self.urls.append(url)
        return fakes.gateway_payload()


def test_api_base_url_is_iot_v2() -> None:
    assert API_BASE_URL == "https://api.viessmann-climatesolutions.com/iot/v2"


def test_looking_at_the_cache_never_requests_but_public_reads_can() -> None:
    manager = CountingManager()
    service = ViCareCachedServiceViaGateway(manager, 60)
    accessor = ViCareDeviceAccessor(fakes.INSTALLATION_ID, fakes.GATEWAY_SERIAL, "0")

    # Before the built-in integration fetched anything: nothing cached.
    assert bridge.peek_payload(service) is None
    assert manager.urls == []

    # The built-in coordinator does this once per minute (1 API call).
    service.clear_cache()
    payload = service.fetch_all_features(accessor)
    assert len(manager.urls) == 1
    assert "includeDevicesFeatures=true" in manager.urls[0]

    for _ in range(100):
        assert bridge.peek_payload(service) is payload
    assert bridge.cache_age_seconds(service) is not None
    assert len(manager.urls) == 1

    # Even with an expired cache a look costs nothing ...
    service._cacheTime = datetime.now() - timedelta(hours=1)
    assert service.is_cache_invalid()
    assert bridge.peek_payload(service) is payload
    assert len(manager.urls) == 1
    # ... whereas PyViCare's public accessor would now spend an API call.
    service.getProperty(accessor, "heating.power.consumption.dhw")
    assert len(manager.urls) == 2

    # During the refresh of the built-in integration the cache is empty.
    service.clear_cache()
    assert bridge.peek_payload(service) is None
    assert len(manager.urls) == 2


def test_bridge_with_real_device_config_and_service() -> None:
    # PyViCareDeviceConfig pulls in the device classes, which need "Deprecated".
    pytest.importorskip("deprecated")
    from PyViCare.PyViCareDeviceConfig import PyViCareDeviceConfig  # noqa: PLC0415

    service = ViCareCachedServiceViaGateway(CountingManager(), 60)
    accessor = ViCareDeviceAccessor(fakes.INSTALLATION_ID, fakes.GATEWAY_SERIAL, "0")
    config = PyViCareDeviceConfig(accessor, service, "E3_Vitocal_16", "Online", "heating", [])
    service.fetch_all_features(accessor)

    entry = ConfigEntry(domain="vicare", entry_id="vicare")
    entry.runtime_data = fakes.FakeViCareData(
        fakes.FakeClient(fakes.FakeOAuthManager(), [config]),
        [fakes.FakeViCareDevice(config, fakes.HEAT_PUMP_SERIAL)],
    )
    (ref,) = bridge.collect_devices(entry)

    assert ref.identifier == fakes.HEAT_PUMP_IDENTIFIER
    assert ref.device_type == "heating"
    assert ref.model == "E3_Vitocal_16"
    assert ref.service is service
    names = [f["feature"] for f in bridge.device_features(bridge.peek_payload(service), "0")]
    assert "heating.power.consumption.dhw" in names
    assert "tcu.wifi" not in names


class FakeResponse:
    def __init__(self, status_code: int, body=None, text: str | None = None) -> None:
        self.status_code = status_code
        self._body = body
        self._text = text
        self.headers = {
            "content-type": "application/json" if text is None else "text/html"
        }

    def json(self):
        if self._text is not None:
            raise requests.exceptions.JSONDecodeError("Expecting value", self._text, 0)
        return self._body


class FakeSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def get(self, url: str, **kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


class Manager(AbstractViCareOAuthManager):
    """Real PyViCare request handling on top of a fake session."""

    def __init__(self, session: FakeSession) -> None:
        super().__init__(session)
        self.renewals = 0

    def renewToken(self) -> None:  # noqa: N802
        self.renewals += 1


def fetch(manager: Manager, **kwargs):
    return fetch_event_history(manager, 2323232, last_n_days=30, limit=1000, max_pages=5, **kwargs)


def test_event_history_through_real_oauth_manager() -> None:
    session = FakeSession(FakeResponse(200, page([event(n=1)], "c1")), FakeResponse(200, page([event(n=2)])))
    result = fetch(Manager(session))

    assert session.urls[0] == f"{API_BASE_URL}{PRIMARY}?lastNDays=30&limit=1000"
    assert session.urls[1].endswith("&cursor=c1")
    assert result["count"] == 2
    assert result["endpoint"] == PRIMARY


@pytest.mark.parametrize(
    "not_found",
    [
        FakeResponse(404, {"viErrorId": "x", "statusCode": 404, "errorType": "ROUTE_NOT_FOUND", "message": "x"}),
        FakeResponse(404, text="<html>Not Found</html>"),
    ],
)
def test_real_not_found_answers_trigger_the_fallback(not_found) -> None:
    session = FakeSession(not_found, FakeResponse(200, page([event()])))
    result = fetch(Manager(session))
    assert [url.split("?")[0] for url in session.urls] == [
        f"{API_BASE_URL}{PRIMARY}",
        f"{API_BASE_URL}{FALLBACK}",
    ]
    assert result["endpoint"] == FALLBACK


def test_real_rate_limit_error_is_mapped() -> None:
    body = {
        "viErrorId": "x",
        "statusCode": 429,
        "errorType": "RATE_LIMIT_EXCEEDED",
        "message": "API calls rate limit has been exceeded.",
        "extendedPayload": {"name": "ViCare day limit", "requestCountLimit": 1450, "limitReset": 1794441600000},
    }
    session = FakeSession(FakeResponse(429, body))
    with pytest.raises(ViCareExtrasError) as err:
        fetch(Manager(session))
    assert err.value.translation_key == "rate_limited"
    assert err.value.placeholders["reset"].endswith("UTC")
    assert len(session.urls) == 1


def test_real_server_error_is_mapped() -> None:
    session = FakeSession(FakeResponse(502, text="<html>Bad Gateway</html>"))
    with pytest.raises(ViCareExtrasError) as err:
        fetch(Manager(session))
    assert err.value.translation_key == "server_error"
    assert len(session.urls) == 1


def test_expired_token_is_renewed_by_pyvicare_not_by_us() -> None:
    session = FakeSession(FakeResponse(401, {"error": "EXPIRED TOKEN"}), FakeResponse(200, page([event()])))
    manager = Manager(session)
    result = fetch(manager)
    assert manager.renewals == 1
    assert result["count"] == 1
    assert result["api_calls"] == 1  # the retry is PyViCare's, not counted by us
