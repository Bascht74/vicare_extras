"""Room and radiator thermostat model (no Home Assistant imports).

How ViCare Smart Climate is laid out, according to Viessmann's service manual
"Einzelraumregelung mit ViCare Smart Climate" (6221420, 2/2025), PyViCare
2.63.0 and its test responses, and ViEventLog:

* Rooms live on the virtual ``roomControl`` device as ``rooms.<n>`` (name,
  type, ``actors``: the devices assigned to the room) and ``rooms.<n>.*``.
* Radiator thermostats (TRV), climate sensors and floor heating thermostats
  are zigbee devices of their own. ``rooms.<n>.actors`` lists their device
  ids; that is the link between a room and its thermostats.
* The room is the real control: all thermostats of a room follow the room's
  setpoint. A change made at a thermostat itself only holds for a limited
  time (24 h with Viessmann One Base, 2 h with Vitoconnect), then the room
  schedule applies again. The room temperature is the mean of the climate
  sensors of the room, or of the thermostats when the room has none.

Setpoints are read from the cached features. A setpoint can only be changed
when its feature advertises an executable command (see ``commands.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .commands import NumberCommand, number_command
from .features import prop_value
from .specs import room_indexes, room_name

# Candidates for "the" setpoint of a room, in order of preference. The first
# one that can be written wins; if none can, the first readable one is shown.
ROOM_SETPOINT_FEATURES = (
    "rooms.{n}.temperature.levels.normal.perceived",
    "rooms.{n}.temperature.levels.normal.heating",
    "rooms.{n}.operating.programs.normalHeating",
)
ROOM_SETPOINT_COMMANDS = ("setTemperature",)
ROOM_SETPOINT_PROPERTY = "temperature"

TRV_SETPOINT_FEATURE = "trv.temperature"
TRV_SETPOINT_COMMANDS = ("setTargetTemperature",)
TRV_SETPOINT_PROPERTY = "value"
TRV_TEMPERATURE_FEATURE = "device.sensors.temperature"
TRV_VALVE_FEATURE = "trv.valve.position"

ACTION_HEATING = "heating"
ACTION_COOLING = "cooling"
ACTION_IDLE = "idle"


@dataclass(frozen=True, slots=True)
class Setpoint:
    """A readable setpoint and, if the API offers one, the command to set it."""

    feature: str
    prop: str
    value: float
    command: NumberCommand | None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def sensor_value(feature: dict[str, Any] | None) -> float | None:
    """Return the value of a ``*.sensors.*`` feature unless it is not connected."""
    status = prop_value(feature, "status")
    if isinstance(status, str) and status != "connected":
        return None
    return _number(prop_value(feature, "value"))


def room_setpoint(features: dict[str, dict[str, Any]], room: int) -> Setpoint | None:
    """Return the setpoint of a room: the first writable one, else readable."""
    readable: list[Setpoint] = []
    for template in ROOM_SETPOINT_FEATURES:
        name = template.replace("{n}", str(room))
        feature = features.get(name)
        value = _number(prop_value(feature, ROOM_SETPOINT_PROPERTY))
        if value is None:
            continue
        setpoint = Setpoint(
            name,
            ROOM_SETPOINT_PROPERTY,
            value,
            number_command(feature, ROOM_SETPOINT_COMMANDS),
        )
        if setpoint.command is not None:
            return setpoint
        readable.append(setpoint)
    return readable[0] if readable else None


def room_action(features: dict[str, dict[str, Any]], room: int) -> str | None:
    """Return heating/cooling/idle from ``rooms.<n>.operating.state.demand``."""
    demand = prop_value(features.get(f"rooms.{room}.operating.state"), "demand")
    if not isinstance(demand, str):
        return None
    if demand in (ACTION_HEATING, ACTION_COOLING):
        return demand
    return ACTION_IDLE


def room_actors(features: dict[str, dict[str, Any]], room: int) -> list[str]:
    """Return the device ids assigned to a room (``rooms.<n>.actors``)."""
    actors = prop_value(features.get(f"rooms.{room}"), "actors")
    if not isinstance(actors, list):
        return []
    return [
        str(actor["deviceId"])
        for actor in actors
        if isinstance(actor, dict) and actor.get("deviceId") is not None
    ]


def is_trv(features: dict[str, dict[str, Any]]) -> bool:
    """Return True when the features are those of a radiator thermostat."""
    return _number(prop_value(features.get(TRV_SETPOINT_FEATURE), TRV_SETPOINT_PROPERTY)) is not None


def trv_setpoint(features: dict[str, dict[str, Any]]) -> Setpoint | None:
    """Return the setpoint of a radiator thermostat."""
    feature = features.get(TRV_SETPOINT_FEATURE)
    value = _number(prop_value(feature, TRV_SETPOINT_PROPERTY))
    if value is None:
        return None
    return Setpoint(
        TRV_SETPOINT_FEATURE,
        TRV_SETPOINT_PROPERTY,
        value,
        number_command(feature, TRV_SETPOINT_COMMANDS),
    )


def trv_valve_position(features: dict[str, dict[str, Any]]) -> float | None:
    """Return the valve opening of a radiator thermostat in percent."""
    return _number(prop_value(features.get(TRV_VALVE_FEATURE), "position"))


def trv_action(features: dict[str, dict[str, Any]]) -> str | None:
    """Return heating while the valve is open, idle when closed."""
    position = trv_valve_position(features)
    if position is None:
        return None
    return ACTION_HEATING if position > 0 else ACTION_IDLE


def room_of_device(
    room_control_features: dict[str, dict[str, Any]], device_id: str
) -> tuple[int, str | None] | None:
    """Return (room index, room name) of the room a device is assigned to."""
    for room in room_indexes(room_control_features):
        if device_id in room_actors(room_control_features, room):
            return room, room_name(room_control_features, room)
    return None
