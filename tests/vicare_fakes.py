"""Fakes that mimic PyViCare objects and the runtime data of the vicare integration.

Shapes follow Home Assistant core 2026.11.1 (``ViCareData``, ``ViCareDevice``)
and PyViCare 2.63.0 (``PyViCareDeviceConfig``, ``ViCareDeviceAccessor``,
``ViCareCachedServiceViaGateway``). All data is synthetic. No Home Assistant
imports, so both test suites (``tests/unit`` and ``tests/ha``) can use it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

INSTALLATION_ID = 2323232
GATEWAY_SERIAL = "7571381500000001"
HEAT_PUMP_SERIAL = "7733738100000002"
VICARE_ENTRY_ID = "vicare-entry-1"
HEAT_PUMP_IDENTIFIER = f"{GATEWAY_SERIAL}_{HEAT_PUMP_SERIAL}"
BASE = "https://api.viessmann-climatesolutions.com/iot/v2/features"


class PyViCareRateLimitError(Exception):
    """Same class name as PyViCare's error (errors are matched by name)."""

    def __init__(self, reset: datetime | None = None) -> None:
        super().__init__("API rate limit exceeded")
        self.limitResetDate = reset or datetime(2026, 11, 13, 0, 0)


class PyViCareInternalServerError(Exception):
    """Same class name as PyViCare's error."""

    def __init__(self, message: str = "Internal error") -> None:
        super().__init__(message)
        self.message = message


def non_json_error() -> PyViCareInternalServerError:
    """Return what PyViCare raises for a non-JSON body (cause: ValueError)."""
    err = PyViCareInternalServerError("Expecting value: line 1 column 1 (char 0)")
    err.__cause__ = ValueError("Expecting value")
    return err


def feature(
    name: str, properties: dict[str, Any], device_id: str | None = "0"
) -> dict[str, Any]:
    """Build a feature object like the Viessmann API delivers it."""
    path = f"/installations/{INSTALLATION_ID}/gateways/{GATEWAY_SERIAL}"
    if device_id is not None:
        path += f"/devices/{device_id}"
    result: dict[str, Any] = {
        "apiVersion": 1,
        "commands": {},
        "feature": name,
        "gatewayId": GATEWAY_SERIAL,
        "isEnabled": True,
        "isReady": True,
        "properties": properties,
        "timestamp": "2026-11-12T08:00:00.000Z",
        "uri": f"{BASE}{path}/features/{name}",
    }
    if device_id is not None:
        result["deviceId"] = device_id
    return result


def consumption(day: list[float]) -> dict[str, Any]:
    read_at = {"type": "string", "value": "2026-11-12T07:59:00.000Z"}
    return {
        "day": {"type": "array", "unit": "kilowattHour", "value": day},
        "dayValueReadAt": read_at,
        "week": {"type": "array", "unit": "kilowattHour", "value": [20.5, 31.0, 28.4, 0, 0, 0]},
        "weekValueReadAt": read_at,
        "month": {"type": "array", "unit": "kilowattHour", "value": [51.5] + [0] * 12},
        "monthValueReadAt": read_at,
        "year": {"type": "array", "unit": "kilowattHour", "value": [51.5, 0]},
        "yearValueReadAt": read_at,
    }


def summary(current_day: float) -> dict[str, Any]:
    def number(value: float) -> dict[str, Any]:
        return {"type": "number", "unit": "kilowattHour", "value": value}

    return {
        "currentDay": number(current_day),
        "currentMonth": number(61.8),
        "currentYear": number(3382.9),
        "lastMonth": number(389.9),
        "lastSevenDays": number(96.7),
    }


def messages(*entries: tuple[str, str, str]) -> dict[str, Any]:
    return {
        "entries": {
            "type": "array",
            "value": [
                {
                    "accessLevel": "customer",
                    "audiences": ["IS-SUPPLIER"],
                    "errorCode": code,
                    "priority": priority,
                    "timestamp": timestamp,
                }
                for code, timestamp, priority in entries
            ],
        }
    }


def heat_pump_features() -> list[dict[str, Any]]:
    return [
        feature("heating.power.consumption.dhw", consumption([2.6, 5.8, 3.5, 2.3, 1.8, 5.1, 3.4, 5.4])),
        feature("heating.power.consumption.heating", consumption([7.1, 9.0, 8.2, 0, 0, 0, 0, 0])),
        feature("heating.power.consumption.total", consumption([9.7, 14.8, 11.7, 0, 0, 0, 0, 0])),
        feature("heating.heat.production.summary.dhw", summary(9.6)),
        feature("heating.heat.production.summary.heating", summary(31.2)),
        feature(
            "device.messages.status.raw",
            messages(
                ("S.123", "2026-11-12T06:00:00.000Z", "status"),
                ("S.134", "2026-11-12T07:30:00.000Z", "status"),
                ("S.165", "2026-11-11T20:00:00.000Z", "status"),
            ),
        ),
        feature("device.messages.info.raw", messages(("I.114", "2026-11-11T19:00:00.000Z", "info"))),
        feature("device.messages.service.raw", messages()),
        feature(
            "heating.sensors.temperature.outside",
            {"value": {"type": "number", "unit": "celsius", "value": 6.5}},
        ),
    ]


def gateway_payload(heat_pump: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build the payload of the gateway bulk request (all devices at once)."""
    return {
        "data": [
            feature("gateway.devices", {"devices": {"type": "DeviceList", "value": []}}, None),
            *(heat_pump_features() if heat_pump is None else heat_pump),
            feature("tcu.wifi", {"strength": {"type": "number", "value": -60}}, "TCU"),
            feature("rooms", {"enabled": {"type": "array", "value": ["0"]}}, "RoomControl-1"),
        ]
    }


class FakeCachedService:
    """Mimics PyViCare's cached gateway service; any fetch fails the test."""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        self._cache = payload
        self._cacheTime = datetime.now()
        self.api_calls = 0

    def _fail(self) -> None:
        self.api_calls += 1
        raise AssertionError("ViCare Extras must never trigger an API request")

    def fetch_all_features(self, accessor: Any) -> Any:
        self._fail()

    def getProperty(self, accessor: Any, property_name: str) -> Any:  # noqa: N802
        self._fail()

    def setProperty(self, *args: Any) -> Any:  # noqa: N802
        self._fail()


class FakeAccessor:
    def __init__(self, installation_id: int, serial: str, device_id: str) -> None:
        self.id = installation_id
        self.serial = serial
        self.device_id = device_id


class FakeDeviceConfig:
    """Mimics PyViCareDeviceConfig."""

    def __init__(self, accessor: FakeAccessor, service: Any, model: str, device_type: str) -> None:
        self.accessor = accessor
        self.service = service
        self.device_id = accessor.device_id
        self.device_model = model
        self.device_type = device_type
        self.status = "Online"
        self.roles: list[str] = []

    def getConfig(self) -> FakeAccessor:  # noqa: N802
        return self.accessor


class FakeApiDevice:
    """Mimics a PyViCare device (HeatPump)."""

    def __init__(self, accessor: FakeAccessor, service: Any) -> None:
        self.accessor = accessor
        self.service = service


class FakeViCareDevice:
    """Mimics homeassistant.components.vicare.types.ViCareDevice."""

    def __init__(self, config: FakeDeviceConfig, serial: str | None) -> None:
        self.config = config
        self.api = FakeApiDevice(config.accessor, config.service)
        self.serial = serial
        self.coordinator = None


class FakeOAuthManager:
    """Mimics PyViCare's OAuth manager with scripted answers."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.urls: list[str] = []

    def get(self, url: str) -> Any:
        self.urls.append(url)
        if not self.answers:
            raise AssertionError(f"unexpected request: {url}")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def post(self, url: str, data: Any) -> Any:
        raise AssertionError("ViCare Extras must never send commands")


class FakeClient:
    """Mimics PyViCare.PyViCare."""

    def __init__(self, oauth_manager: Any, all_devices: list[FakeDeviceConfig]) -> None:
        self.oauth_manager = oauth_manager
        self.all_devices = all_devices
        self.devices = all_devices


class FakeViCareData:
    """Mimics homeassistant.components.vicare.types.ViCareData."""

    def __init__(self, client: FakeClient, devices: list[FakeViCareDevice]) -> None:
        self.client = client
        self.devices = devices


def make_runtime_data(
    payload: dict[str, Any] | None = None,
    oauth_manager: Any = None,
    *,
    empty_cache: bool = False,
) -> tuple[FakeViCareData, FakeCachedService]:
    """Build runtime data: heat pump set up, gateway and room control not."""
    service = FakeCachedService(None if empty_cache else (payload or gateway_payload()))
    heat_pump = FakeDeviceConfig(
        FakeAccessor(INSTALLATION_ID, GATEWAY_SERIAL, "0"), service, "E3_Vitocal_16", "heating"
    )
    tcu = FakeDeviceConfig(
        FakeAccessor(INSTALLATION_ID, GATEWAY_SERIAL, "TCU"), service, "E3_TCU10_x07", "tcu"
    )
    room = FakeDeviceConfig(
        FakeAccessor(INSTALLATION_ID, GATEWAY_SERIAL, "RoomControl-1"),
        service,
        "E3_RoomControl_One_522",
        "roomControl",
    )
    client = FakeClient(oauth_manager or FakeOAuthManager(), [tcu, heat_pump, room])
    return FakeViCareData(client, [FakeViCareDevice(heat_pump, HEAT_PUMP_SERIAL)]), service
