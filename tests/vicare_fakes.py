"""Fakes that mimic PyViCare objects and the runtime data of the vicare integration.

Shapes follow Home Assistant core 2026.11.1 (``ViCareData``, ``ViCareDevice``)
and PyViCare 2.63.0 (``PyViCareDeviceConfig``, ``ViCareDeviceAccessor``,
``ViCareCachedServiceViaGateway``). All data is synthetic. No Home Assistant
imports, so both test suites (``tests/unit`` and ``tests/ha``) can use it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"

INSTALLATION_ID = 2323232
GATEWAY_SERIAL = "7571381500000001"
HEAT_PUMP_SERIAL = "7733738100000002"
VICARE_ENTRY_ID = "vicare-entry-1"
HEAT_PUMP_IDENTIFIER = f"{GATEWAY_SERIAL}_{HEAT_PUMP_SERIAL}"
TRV_DEVICE_ID = "zigbee-1234567890abcdef"
TRV_IDENTIFIER = f"{GATEWAY_SERIAL}_zigbee_1234567890abcdef"
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
    name: str,
    properties: dict[str, Any],
    device_id: str | None = "0",
    commands: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a feature object like the Viessmann API delivers it."""
    path = f"/installations/{INSTALLATION_ID}/gateways/{GATEWAY_SERIAL}"
    if device_id is not None:
        path += f"/devices/{device_id}"
    result: dict[str, Any] = {
        "apiVersion": 1,
        "commands": commands or {},
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


def number_command(
    name: str,
    param: str,
    *,
    executable: bool = True,
    minimum: float = 8,
    maximum: float = 30,
    step: float = 0.5,
) -> dict[str, Any]:
    """Build a command object like the Viessmann API puts into a feature."""
    return {
        name: {
            "uri": f"{BASE}/…/commands/{name}",
            "name": name,
            "isExecutable": executable,
            "params": {
                param: {
                    "type": "number",
                    "required": True,
                    "constraints": {"min": minimum, "max": maximum, "stepping": step},
                }
            },
        }
    }


def trv_features(
    device_id: str = TRV_DEVICE_ID,
    *,
    temperature_status: str | None = "connected",
    executable: bool = True,
    valve: float = 17,
) -> list[dict[str, Any]]:
    """Return the features of a radiator thermostat.

    Synthetic, modelled on PyViCare's test response zigbee_zk03840_trv.json.
    """
    temperature: dict[str, Any] = {}
    if temperature_status is not None:
        temperature["status"] = {"type": "string", "value": temperature_status}
        if temperature_status == "connected":
            temperature["value"] = {"type": "number", "unit": "celsius", "value": 20.8}
    items = [
        ("device.sensors.temperature", temperature, None),
        ("device.power.battery", {"level": {"type": "number", "unit": "percent", "value": 92}}, None),
        ("device.name", {"name": {"type": "string", "value": "Thermostat Wohnzimmer"}}, None),
        ("trv.childLock", {"status": {"type": "string", "value": "inactive"}}, None),
        (
            "trv.temperature",
            {"value": {"type": "number", "unit": "celsius", "value": 20}},
            number_command("setTargetTemperature", "temperature", executable=executable),
        ),
        ("trv.valve.position", {"position": {"type": "number", "unit": "percent", "value": valve}}, None),
    ]
    return [feature(name, props, device_id, commands) for name, props, commands in items]


def vitocal_features() -> list[dict[str, Any]]:
    """Return the feature list of a Vitocal 250-A (structure from a real device)."""
    data = json.loads((FIXTURES / "vitocal250a_features.json").read_text(encoding="utf-8"))
    return data["data"]


def room_features(
    room: int = 0,
    name: str | None = "Wohnzimmer",
    *,
    writable: str | None = None,
    executable: bool = True,
    actors: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Return rooms.<n>.* features like a ViCare room control delivers them.

    Synthetic: modelled on PyViCare's RoomControl fixtures and accessors, not
    on a real installation. ``writable`` names the setpoint feature (suffix
    after ``rooms.<n>.``) that carries a ``setTemperature`` command, as
    ViEventLog uses it for ``temperature.levels.normal.perceived``.
    """

    def value(val: Any, unit: str | None = None, kind: str = "number") -> dict[str, Any]:
        result = {"type": kind, "value": val}
        if unit:
            result["unit"] = unit
        return result

    def temperature(val: float) -> dict[str, Any]:
        return {"temperature": value(val, "celsius")}

    prefix = f"rooms.{room}"
    connected = value("connected", kind="string")
    base: dict[str, Any] = {
        "type": value("livingroom", kind="string"),
        "actors": value(
            [{"deviceId": actor, "heatingCircuit": 0} for actor in actors], kind="array"
        ),
    }
    if name is not None:
        base["name"] = value(name, kind="string")
    items = {
        prefix: base,
        f"{prefix}.sensors.temperature": {"status": connected, "value": value(21.4, "celsius")},
        f"{prefix}.sensors.humidity": {"status": connected, "value": value(48, "percent")},
        f"{prefix}.co2": {"concentration": value(650, "partsPerMillion")},
        f"{prefix}.condensationRisk": {"value": value(False, kind="boolean")},
        f"{prefix}.sensors.openWindow": {"value": value(True, kind="boolean")},
        f"{prefix}.childLock": {"active": value(False, kind="boolean"), "status": value("inactive", kind="string")},
        f"{prefix}.temperature.levels.normal.heating": temperature(21),
        f"{prefix}.temperature.levels.reduced.heating": temperature(18),
        f"{prefix}.temperature.levels.comfort.heating": temperature(23),
        f"{prefix}.temperature.levels.normal.perceived": temperature(21),
        f"{prefix}.temperature.levels.normal.cooling": {},
        f"{prefix}.operating.state": {
            "level": value("normal", kind="string"),
            "demand": value("heating", kind="string"),
            "reason": value("schedule", kind="string"),
            "modifier": value("none", kind="string"),
        },
        f"{prefix}.configuration.openWindow": {"active": value(True, kind="boolean")},
    }
    return [
        feature(
            name_,
            props,
            "RoomControl-1",
            number_command("setTemperature", "targetTemperature", executable=executable)
            if writable is not None and name_ == f"{prefix}.{writable}"
            else None,
        )
        for name_, props in items.items()
    ]


def room_control_only_flags() -> list[dict[str, Any]]:
    """Return what a room control without rooms delivers (seen on a real system)."""
    names = ["rooms.features", "rooms.features.remotePresenceProbability"]
    for channel in range(4):
        names += [
            f"rooms.features.supplyChannel{channel}FTDC",
            f"rooms.features.supplyChannel{channel}FTDCUseValveInformation",
            f"rooms.features.supplyChannel{channel}PumpControl",
        ]
    return [
        feature(name_, {} if name_ == "rooms.features" else {"active": {"type": "boolean", "value": False}}, "RoomControl-1")
        for name_ in names
    ]


def gateway_payload(
    heat_pump: list[dict[str, Any]] | None = None,
    rooms: list[dict[str, Any]] | None = None,
    extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the payload of the gateway bulk request (all devices at once)."""
    return {
        "data": [
            feature("gateway.devices", {"devices": {"type": "DeviceList", "value": []}}, None),
            *(heat_pump_features() if heat_pump is None else heat_pump),
            feature("tcu.wifi", {"strength": {"type": "number", "value": -60}}, "TCU"),
            *(
                [feature("rooms", {"enabled": {"type": "array", "value": ["0"]}}, "RoomControl-1")]
                if rooms is None
                else rooms
            ),
            *(extra or []),
        ]
    }


class FakeCachedService:
    """Mimics PyViCare's cached gateway service; any fetch fails the test."""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        self._cache = payload
        self._cacheTime = datetime.now()
        self._cacheDuration = 60
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


class ViCareService:
    """Same class name as PyViCare's plain service: posts a command.

    Records the call and answers with ``answer`` (or raises it).
    """

    answer: Any
    commands: list[tuple[str, str, str, Any]]

    def setProperty(self, accessor: Any, property_name: str, action: str, data: Any) -> Any:  # noqa: N802
        self.commands.append((accessor.device_id, property_name, action, data))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class FakeCommandService(FakeCachedService, ViCareService):
    """A service that accepts commands, like PyViCare's cached service.

    Reads still fail the test. As in PyViCare, ``setProperty`` of the cached
    service posts through ``ViCareService.setProperty`` and then empties the
    cache; ``cache_clears`` counts how often that happened.
    """

    def __init__(self, payload: dict[str, Any] | None, answer: Any = None) -> None:
        super().__init__(payload)
        self.answer = {"data": {"success": True, "reason": "COMMAND_EXECUTION_SUCCESS"}} if answer is None else answer
        self.commands = []
        self.cache_clears = 0

    def setProperty(self, accessor: Any, property_name: str, action: str, data: Any) -> Any:  # noqa: N802
        response = ViCareService.setProperty(self, accessor, property_name, action, data)
        self._cache = None
        self.cache_clears += 1
        return response


class FakeOtherCommandService(FakeCachedService):
    """A command service whose class hierarchy has no ``ViCareService``."""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        super().__init__(payload)
        self.commands: list[tuple[str, str, str, Any]] = []

    def setProperty(self, accessor: Any, property_name: str, action: str, data: Any) -> Any:  # noqa: N802
        self.commands.append((accessor.device_id, property_name, action, data))
        self._cache = None
        return {"data": {"success": True}}


class PyViCareCommandError(Exception):
    """Same class name as PyViCare's error."""

    def __init__(self, reason: str = "COMMAND_EXECUTION_ERROR") -> None:
        super().__init__(f"Command failed. Reason given was: {reason}")
        self.message = f"Command failed with status code 502. Reason given was: {reason}"


class FakeViCareCoordinator:
    """Mimics the built-in ViCareCoordinator (a DataUpdateCoordinator)."""

    def __init__(self, seconds: int = 60) -> None:
        self.update_interval = timedelta(seconds=seconds)


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
        self.coordinator: Any = None


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
    with_trv: bool = False,
    service: FakeCachedService | None = None,
) -> tuple[FakeViCareData, FakeCachedService]:
    """Build runtime data: heat pump set up, gateway and room control not.

    ``with_trv`` adds a radiator thermostat the built-in integration has set
    up. All devices share one service and one coordinator (one gateway).
    """
    if service is None:
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
    configs = [tcu, heat_pump, room]
    devices = [FakeViCareDevice(heat_pump, HEAT_PUMP_SERIAL)]
    if with_trv:
        trv = FakeDeviceConfig(
            FakeAccessor(INSTALLATION_ID, GATEWAY_SERIAL, TRV_DEVICE_ID),
            service,
            "Smart_zigbee_trv",
            "zigbee",
        )
        configs.append(trv)
        devices.append(FakeViCareDevice(trv, TRV_DEVICE_ID))
    coordinator = FakeViCareCoordinator()
    for device in devices:
        device.coordinator = coordinator
    client = FakeClient(oauth_manager or FakeOAuthManager(), configs)
    return FakeViCareData(client, devices), service
