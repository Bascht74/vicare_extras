"""Checks against the real PyViCare code (no network, fake HTTP session).

Skipped unless PyViCare is importable. Either install it (``pip install
PyViCare==2.63.0``) or point ``PYVICARE_SRC`` at a source checkout. When
authlib is missing, a minimal stand-in from ``stubs_authlib`` is used.

These tests pin down the PyViCare behaviour this integration relies on:
* looking at ``_cache`` never performs a request, a public read may;
* how ``oauth_manager.get`` reports "not found", rate limiting and non-JSON
  answers;
* how ``service.setProperty`` sends a command and reports a rejected one;
* the room and thermostat model, against PyViCare's test responses.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import importlib.util
import json
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

from custom_components.vicare_extras import (  # noqa: E402
    bridge,
    commands,
    thermostats,
)
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
        self.posts: list[tuple[str, str]] = []

    def get(self, url: str, **kwargs):
        self.urls.append(url)
        return self.responses.pop(0)

    def post(self, url: str, data=None, **kwargs):
        self.posts.append((url, data))
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


# ------------------------------------------------------------------ commands

ROOM_COMMAND = commands.NumberCommand(
    feature="rooms.0.operating.programs.normalHeating",
    name="setTemperature",
    param="targetTemperature",
    minimum=8.0,
    maximum=30.0,
    step=0.5,
)
ROOM_ACCESSOR = ViCareDeviceAccessor(fakes.INSTALLATION_ID, fakes.GATEWAY_SERIAL, "RoomControl-1")


def test_command_goes_through_real_set_property_as_one_post() -> None:
    session = FakeSession(FakeResponse(200, {"data": {"success": True, "reason": "COMMAND_EXECUTION_SUCCESS"}}))
    service = ViCareCachedServiceViaGateway(Manager(session), 60)
    payload = fakes.gateway_payload()  # what the built-in integration fetched
    service._cache = payload
    service._cacheTime = datetime.now()

    assert commands.execute(service, ROOM_ACCESSOR, ROOM_COMMAND, 21.5) == 21.5

    assert session.urls == []  # no read
    assert session.posts == [
        (
            f"{API_BASE_URL}/features/installations/{fakes.INSTALLATION_ID}/gateways/"
            f"{fakes.GATEWAY_SERIAL}/devices/RoomControl-1/features/"
            "rooms.0.operating.programs.normalHeating/commands/setTemperature",
            '{"targetTemperature": 21.5}',
        )
    ]
    # The command went out through ViCareService.setProperty, which only
    # posts. The cache keeps its content, so the built-in integration does
    # not fetch again before its next regular poll.
    assert bridge.peek_payload(service) is payload
    assert not service.is_cache_invalid()
    assert session.urls == []


def test_pyvicare_cached_set_property_would_empty_the_cache() -> None:
    """Why the command is not sent through the cached service's method."""
    session = FakeSession(FakeResponse(200, {"data": {"success": True}}))
    service = ViCareCachedServiceViaGateway(Manager(session), 60)
    service._cache = fakes.gateway_payload()
    service._cacheTime = datetime.now()

    service.setProperty(ROOM_ACCESSOR, ROOM_COMMAND.feature, ROOM_COMMAND.name, {"targetTemperature": 21})

    assert bridge.peek_payload(service) is None
    assert service.is_cache_invalid()  # the next read of anyone fetches again


def test_whole_numbers_are_sent_as_integers() -> None:
    session = FakeSession(FakeResponse(200, {"data": {"success": True}}))
    service = ViCareCachedServiceViaGateway(Manager(session), 60)
    commands.execute(service, ROOM_ACCESSOR, ROOM_COMMAND, 21.0)
    assert session.posts[0][1] == '{"targetTemperature": 21}'


def test_real_rejected_command_is_mapped() -> None:
    body = {
        "viErrorId": "x",
        "statusCode": 400,
        "errorType": "COMMAND_EXECUTION_ERROR",
        "message": "Command execution error.",
        "extendedPayload": {"reason": "COMMAND_NOT_EXECUTABLE"},
    }
    session = FakeSession(FakeResponse(400, body))
    service = ViCareCachedServiceViaGateway(Manager(session), 60)
    with pytest.raises(ViCareExtrasError) as err:
        commands.execute(service, ROOM_ACCESSOR, ROOM_COMMAND, 21.5)
    assert err.value.translation_key == "command_failed"
    assert "COMMAND_NOT_EXECUTABLE" in err.value.placeholders["reason"]
    assert len(session.posts) == 1  # no retry


def test_real_rate_limit_on_a_command_is_mapped() -> None:
    body = {
        "viErrorId": "x",
        "statusCode": 429,
        "errorType": "RATE_LIMIT_EXCEEDED",
        "message": "API calls rate limit has been exceeded.",
        "extendedPayload": {"name": "ViCare day limit", "requestCountLimit": 1450, "limitReset": 1794441600000},
    }
    service = ViCareCachedServiceViaGateway(Manager(FakeSession(FakeResponse(429, body))), 60)
    with pytest.raises(ViCareExtrasError) as err:
        commands.execute(service, ROOM_ACCESSOR, ROOM_COMMAND, 21.5)
    assert err.value.translation_key == "rate_limited"


def test_out_of_range_value_never_reaches_pyvicare() -> None:
    session = FakeSession()
    service = ViCareCachedServiceViaGateway(Manager(session), 60)
    with pytest.raises(ViCareExtrasError) as err:
        commands.execute(service, ROOM_ACCESSOR, ROOM_COMMAND, 35)
    assert err.value.translation_key == "value_out_of_range"
    assert session.posts == []


# ----------------------------------------------- PyViCare's test responses


def _response(name: str) -> list[dict]:
    source = os.environ.get("PYVICARE_SRC")
    path = Path(source or "") / "tests" / "response" / name
    if not source or not path.is_file():
        pytest.skip(f"PyViCare test response {name} is not available")
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _features(data: list[dict], device_id: str) -> dict[str, dict]:
    return {
        feature["feature"]: feature
        for feature in bridge.device_features({"data": data}, device_id)
    }


def test_room_and_thermostat_model_against_gateway_response() -> None:
    """Vitodens with one room and one radiator thermostat assigned to it."""
    data = _response("gatewayWithDevices/heatbox2/Vitodens-300-W-WB3D-with-TRV.json")
    rooms = _features(data, "RoomControl-1")
    trv_id = "zigbee-1234567890abcdef"
    trv = _features(data, trv_id)

    # The room names its thermostats, the thermostat does not name its room.
    assert thermostats.room_actors(rooms, 0) == [trv_id]
    assert thermostats.room_of_device(rooms, trv_id) == (0, "Arbeitszimmer")
    assert not any(name.startswith("rooms.") for name in trv)

    # normal.perceived and normal.heating are readable but offer no command
    # here; the executable setTemperature sits on operating.programs.normalHeating.
    setpoint = thermostats.room_setpoint(rooms, 0)
    assert setpoint.feature == "rooms.0.operating.programs.normalHeating"
    assert setpoint.value == 20.0
    assert setpoint.command == commands.NumberCommand(
        feature="rooms.0.operating.programs.normalHeating",
        name="setTemperature",
        param="targetTemperature",
        minimum=8.0,
        maximum=30.0,
        step=0.5,
    )
    assert thermostats.room_action(rooms, 0) == "heating"

    assert thermostats.is_trv(trv)
    trv_setpoint = thermostats.trv_setpoint(trv)
    assert trv_setpoint.feature == "trv.temperature"
    assert trv_setpoint.command.name == "setTargetTemperature"
    assert trv_setpoint.command.param == "temperature"
    assert (trv_setpoint.command.minimum, trv_setpoint.command.maximum, trv_setpoint.command.step) == (8.0, 30.0, 0.5)


def test_room_control_response_without_commands_is_read_only() -> None:
    """RoomControl.json carries no commands: setpoint readable, not writable."""
    rooms = _features(_response("RoomControl.json"), "RoomControl-1") or {
        feature["feature"]: feature for feature in _response("RoomControl.json")
    }
    setpoint = thermostats.room_setpoint(rooms, 0)
    assert setpoint.feature == "rooms.0.temperature.levels.normal.perceived"
    assert setpoint.command is None
    assert thermostats.room_actors(rooms, 0) == []  # no rooms.0 feature in this file
    assert thermostats.sensor_value(rooms["rooms.0.sensors.temperature"]) is not None


@pytest.mark.parametrize(
    ("name", "is_trv"),
    [
        ("zigbee_zk03840_trv.json", True),
        ("zigbee_zk03839_cs.json", False),  # climate sensor
        ("zigbee_zk03838_fht_main.json", False),  # floor heating thermostat
        ("zigbee_zk03838_fht_channel.json", False),
        ("zigbee_zk05390_repeater.json", False),
    ],
)
def test_only_radiator_thermostats_count_as_trv(name, is_trv) -> None:
    features = {feature["feature"]: feature for feature in _response(name)}
    assert thermostats.is_trv(features) is is_trv
    assert (thermostats.trv_setpoint(features) is not None) is is_trv
    if is_trv:
        assert thermostats.trv_setpoint(features).command.name == "setTargetTemperature"
        assert thermostats.sensor_value(features["device.sensors.temperature"]) == 21.5
        assert thermostats.trv_action(features) == "heating"  # valve at 2 %


# ------------------------------------------------------------ send (as given)


def test_send_posts_an_unadvertised_command_through_real_pyvicare() -> None:
    session = FakeSession(FakeResponse(200, {"data": {"success": True, "reason": "COMMAND_EXECUTION_SUCCESS"}}))
    service = ViCareCachedServiceViaGateway(Manager(session), 60)
    payload = fakes.gateway_payload()
    service._cache = payload
    service._cacheTime = datetime.now()

    result = commands.send(
        service,
        ROOM_ACCESSOR,
        "rooms.0.temperature.levels.normal.perceived",
        "setTemperature",
        {"targetTemperature": 21.5},
    )

    assert result == {"success": True, "response": {"data": {"success": True, "reason": "COMMAND_EXECUTION_SUCCESS"}}}
    assert session.posts == [
        (
            f"{API_BASE_URL}/features/installations/{fakes.INSTALLATION_ID}/gateways/"
            f"{fakes.GATEWAY_SERIAL}/devices/RoomControl-1/features/"
            "rooms.0.temperature.levels.normal.perceived/commands/setTemperature",
            '{"targetTemperature": 21.5}',
        )
    ]
    assert session.urls == []
    assert bridge.peek_payload(service) is payload  # cache untouched


def test_send_returns_what_real_pyvicare_reports_for_a_rejection() -> None:
    body = {
        "viErrorId": "req-123",
        "statusCode": 404,
        "errorType": "COMMAND_NOT_FOUND",
        "message": "Command not found",
        "extendedPayload": {"reason": "COMMAND_NOT_FOUND"},
    }
    session = FakeSession(FakeResponse(404, body))
    service = ViCareCachedServiceViaGateway(Manager(session), 60)

    result = commands.send(service, ROOM_ACCESSOR, "rooms.0.schedule", "setSchedule", {})

    assert result["success"] is False
    # PyViCare raises PyViCareCommandError, or hands the answer back when its
    # "raise on command failure" switch is off: both are reported as data.
    response = result["response"]
    if "error_type" in response:
        assert response["error_type"] == "PyViCareCommandError"
        assert response["status_code"] == 404
        assert "COMMAND_NOT_FOUND" in response["message"]
    else:
        assert response == body
    assert len(session.posts) == 1
