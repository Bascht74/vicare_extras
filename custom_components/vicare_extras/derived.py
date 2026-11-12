"""Values derived from several cached features (no Home Assistant imports).

Operating state
---------------
``operating_state`` condenses the heat pump's state into one value for a
history timeline. Inputs, all from the cached feature list:

* ``device.messages.status.raw``: the status messages that are active right
  now. Observed on a Vitocal 250-A: every code appears once with the time it
  became active, and codes that end (e.g. S.123 "heat pump off" when the
  heat pump starts) disappear from the list. The event history confirms the
  model: each ``device-message-status`` event carries ``active: true/false``.
* ``heating.valves.fourThreeWay.position``: where the 4/3-way valve points.
* ``heating.outdoor.defrosting``, ``heating.compressors.N`` and
  ``heating.secondaryCircuit.operation.state`` as fallback.

Mapping (meaning of the codes as in Viessmann's service manual 6200041)::

    heating.outdoor.defrosting.active == true          -> defrost
    newest active code of S.123 ... S.129:
        S.123 heat pump off                            -> off
        S.124 heat pump in its pre-run phase           -> preflow
        S.125 heat pump heating
              valve position is a hot water position   -> dhw
              otherwise                                -> heating
        S.126 heat pump cooling                        -> cooling
        S.127 heat pump prepares defrosting            -> defrost
        S.128 heat pump defrosting                     -> defrost
        S.129 heat pump in its run-on phase            -> afterflow
    none of these codes active (fallback, coarser):
        no compressor active                           -> off
        valve position is a hot water position         -> dhw
        secondary circuit state == "cooling"           -> cooling
        otherwise                                      -> heating

``heating`` covers space heating through the buffer cylinder or a heating
circuit; the valve position is given as an attribute. Preflow and afterflow
can only be told from the status messages.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .const import FEATURE_MESSAGES_STATUS
from .features import message_entries, prop_value
from .messages import normalize_code
from .specs import state_key

STATE_OFF = "off"
STATE_PREFLOW = "preflow"
STATE_HEATING = "heating"
STATE_DHW = "dhw"
STATE_COOLING = "cooling"
STATE_DEFROST = "defrost"
STATE_AFTERFLOW = "afterflow"

OPERATING_STATES = (
    STATE_OFF,
    STATE_PREFLOW,
    STATE_HEATING,
    STATE_DHW,
    STATE_COOLING,
    STATE_DEFROST,
    STATE_AFTERFLOW,
)

PHASE_CODES = {
    "S.123": STATE_OFF,
    "S.124": STATE_PREFLOW,
    "S.125": STATE_HEATING,
    "S.126": STATE_COOLING,
    "S.127": STATE_DEFROST,
    "S.128": STATE_DEFROST,
    "S.129": STATE_AFTERFLOW,
}

# Values of heating.valves.fourThreeWay.position that mean "hot water".
DHW_VALVE_POSITIONS = frozenset(
    {"domesticHotWater", "climateCircuitTwoDefrostDomesticHotWater"}
)

FEATURE_VALVE_POSITION = "heating.valves.fourThreeWay.position"
FEATURE_DEFROSTING = "heating.outdoor.defrosting"
FEATURE_SECONDARY_STATE = "heating.secondaryCircuit.operation.state"
FEATURE_HEAT_PRODUCTION = "heating.heat.production.current"
FEATURE_POWER_CONSUMPTION = "heating.power.consumption.current"

# Codes of the instantaneous heating water heater (service manual 6200041):
# S.130 off, S.131-S.133 stage 1-3 active, S.217-S.219 stage 1-3 inactive.
HEATING_ROD_STAGE_ACTIVE = ("S.131", "S.132", "S.133")
HEATING_ROD_CODES = frozenset(
    {"S.130", *HEATING_ROD_STAGE_ACTIVE, "S.217", "S.218", "S.219"}
)

# Below this power (kW) a COP is noise: the compressor is off or starting.
COP_MINIMUM_KW = 0.2

SCHEDULE_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SCHEDULE_NONE = "none"
SCHEDULE_INACTIVE = "inactive"


def active_status_messages(
    features: dict[str, dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Return the active status messages (newest first), None without feature."""
    if FEATURE_MESSAGES_STATUS not in features:
        return None
    return message_entries(features[FEATURE_MESSAGES_STATUS])


def active_status_codes(features: dict[str, dict[str, Any]]) -> list[str] | None:
    """Return the distinct active status codes, sorted by number."""
    entries = active_status_messages(features)
    if entries is None:
        return None
    codes = {
        code
        for entry in entries
        if (code := normalize_code(entry.get("errorCode"))) is not None
    }
    return sorted(codes, key=lambda code: (code[0], int(code[2:])))


def _compressor_active(features: dict[str, dict[str, Any]]) -> bool | None:
    states = [
        prop_value(feature, "active")
        for name, feature in features.items()
        if name.startswith("heating.compressors.") and name.count(".") == 2
    ]
    states = [state for state in states if isinstance(state, bool)]
    return any(states) if states else None


def operating_state(
    features: dict[str, dict[str, Any]],
) -> tuple[str | None, dict[str, Any]]:
    """Return the operating state and how it was derived (see module doc)."""
    valve = prop_value(features.get(FEATURE_VALVE_POSITION), "value")
    valve = valve if isinstance(valve, str) else None
    details: dict[str, Any] = {
        "basis": None,
        "status_code": None,
        "valve_position": state_key(valve),
    }

    if prop_value(features.get(FEATURE_DEFROSTING), "active") is True:
        details["basis"] = "defrosting"
        return STATE_DEFROST, details

    for entry in active_status_messages(features) or []:  # newest first
        code = normalize_code(entry.get("errorCode"))
        if code not in PHASE_CODES:
            continue
        state = PHASE_CODES[code]
        if state == STATE_HEATING and valve in DHW_VALVE_POSITIONS:
            state = STATE_DHW
        details["basis"] = "status_message"
        details["status_code"] = code
        return state, details

    compressor = _compressor_active(features)
    if compressor is None:
        return None, details
    details["basis"] = "compressor"
    if not compressor:
        return STATE_OFF, details
    if valve in DHW_VALVE_POSITIONS:
        return STATE_DHW, details
    if prop_value(features.get(FEATURE_SECONDARY_STATE), "currentValue") == "cooling":
        return STATE_COOLING, details
    return STATE_HEATING, details


def heating_rod_stage(features: dict[str, dict[str, Any]]) -> int | None:
    """Return how many stages of the heating water heater are active (0-3).

    None when the status messages say nothing about the heater.
    """
    codes = active_status_codes(features)
    if codes is None or not HEATING_ROD_CODES.intersection(codes):
        return None
    return sum(1 for code in HEATING_ROD_STAGE_ACTIVE if code in codes)


def _kilowatt(feature: dict[str, Any] | None) -> float | None:
    value = prop_value(feature, "value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    properties = feature.get("properties") if isinstance(feature, dict) else None
    unit = properties["value"].get("unit") if isinstance(properties, dict) else None
    return value / 1000 if unit == "watt" else float(value)


def current_cop(features: dict[str, dict[str, Any]]) -> float | None:
    """Return heat production / power consumption, None when not meaningful."""
    heat = _kilowatt(features.get(FEATURE_HEAT_PRODUCTION))
    power = _kilowatt(features.get(FEATURE_POWER_CONSUMPTION))
    if heat is None or power is None:
        return None
    if heat < COP_MINIMUM_KW or power < COP_MINIMUM_KW:
        return None
    return round(heat / power, 2)


def _minutes(value: Any) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    hours, _, minutes = value.partition(":")
    try:
        return int(hours) * 60 + int(minutes)
    except ValueError:
        return None


def schedule_today(feature: dict[str, Any] | None, now: datetime) -> list[dict[str, Any]]:
    """Return today's time slots of a schedule feature, sorted by start."""
    entries = prop_value(feature, "entries")
    slots = entries.get(SCHEDULE_DAYS[now.weekday()]) if isinstance(entries, dict) else None
    if not isinstance(slots, list):
        return []
    valid = [slot for slot in slots if isinstance(slot, dict)]
    return sorted(valid, key=lambda slot: _minutes(slot.get("start")) or 0)


def schedule_mode(feature: dict[str, Any] | None, now: datetime) -> str | None:
    """Return the mode the schedule asks for right now.

    ``inactive`` when the schedule is switched off, ``none`` outside all time
    slots, None when the feature has no entries. ``now`` must be local time of
    the heating system (Home Assistant's local time is used).
    """
    if not isinstance(prop_value(feature, "entries"), dict):
        return None
    if prop_value(feature, "active") is False:
        return SCHEDULE_INACTIVE
    minute = now.hour * 60 + now.minute
    for slot in schedule_today(feature, now):
        start = _minutes(slot.get("start"))
        end = _minutes(slot.get("end"))
        if start is None or end is None:
            continue
        if start <= minute < end:
            return state_key(slot.get("mode")) or SCHEDULE_NONE
    return SCHEDULE_NONE
