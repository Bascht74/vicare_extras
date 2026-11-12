"""Declarative list of the feature-backed entities (no Home Assistant imports).

Every entry maps one property of one ViCare feature to one entity. The
Home Assistant platforms (``sensor.py``, ``binary_sensor.py``) turn the
entries into entities; keeping the list here makes it testable without Home
Assistant and gives one place to look up "which entity reads which feature".

Only features the built-in ``vicare`` integration does not already expose are
listed (checked against core 2026.11.1 and a real Vitocal 250-A feature dump).

Feature templates may contain ``{n}``: one entity is created per matching
index (``heating.compressors.0...``, ``rooms.3...``).
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

SCOPE_HEATING = "heating"
SCOPE_ROOM = "room"
SCOPE_TRV = "trv"

PLATFORM_SENSOR = "sensor"
PLATFORM_BINARY_SENSOR = "binary_sensor"

KIND_NUMBER = "number"
KIND_ENUM = "enum"
KIND_BOOL = "bool"

# ViCare unit -> Home Assistant unit string.
UNITS = {
    "celsius": "°C",
    "kelvin": "K",
    "percent": "%",
    "kilowatt": "kW",
    "watt": "W",
    "kilowattHour": "kWh",
    "wattHour": "Wh",
    "bar": "bar",
    "revolutionsPerSecond": "rps",
    "partsPerMillion": "ppm",
    "liter/hour": "L/h",
    "hour": "h",
}

# How the index of a feature is shown in the entity name.
NUMBER_NONE = "none"  # no index in the feature
NUMBER_AS_IS = "as_is"  # "{number}" = API index (heating circuits)
NUMBER_PLUS_ONE = "plus_one"  # "{number}" = API index + 1 (fans, valves)
# "{suffix}" is empty for index 0 and " 2", " 3", ... for further instances
# (compressors, economizers: usually there is exactly one).
NUMBER_SUFFIX = "suffix"


@dataclass(frozen=True, slots=True)
class ValueSpec:
    """One entity backed by one feature property."""

    key: str
    # (feature template, property) candidates; the first existing one wins.
    sources: tuple[tuple[str, str], ...]
    platform: str = PLATFORM_SENSOR
    kind: str = KIND_NUMBER
    scope: str = SCOPE_HEATING
    device_class: str | None = None
    # Unit used when the API reports none; the API unit wins when known.
    unit: str | None = None
    measurement: bool = True  # state_class measurement for numbers
    precision: int | None = None
    enabled: bool = True
    diagnostic: bool = False
    numbering: str = NUMBER_NONE
    # Extra state attributes: (attribute name, property of the same feature).
    attributes: tuple[tuple[str, str], ...] = ()
    # For booleans read from a string property: the value that means "on".
    on_value: str | None = None
    # Numbers below this are reported as unknown (e.g. "-1 W" = no limit).
    minimum: float | None = None

    @property
    def indexed(self) -> bool:
        """Return True when the feature template contains an index."""
        return "{n}" in self.sources[0][0]


def _spec(key: str, feature: str, prop: str = "value", **kwargs: Any) -> ValueSpec:
    return ValueSpec(key=key, sources=((feature, prop),), **kwargs)


TEMPERATURE = {"device_class": "temperature", "unit": "°C", "precision": 1}
PERCENT = {"unit": "%", "precision": 0}
POWER_KW = {"device_class": "power", "unit": "kW", "precision": 2}
CONFIG = {"enabled": False, "diagnostic": True}
BINARY = {"platform": PLATFORM_BINARY_SENSOR, "kind": KIND_BOOL, "measurement": False}
ENUM = {"kind": KIND_ENUM, "device_class": "enum", "measurement": False}

HEATING_SPECS: tuple[ValueSpec, ...] = (
    # --- 4/3-way valve and secondary circuit ---------------------------------
    _spec("four_three_way_valve_position", "heating.valves.fourThreeWay.position", **ENUM),
    _spec(
        "secondary_circuit_state",
        "heating.secondaryCircuit.operation.state",
        "currentValue",
        attributes=(("target_value", "targetValue"),),
        **ENUM,
    ),
    _spec(
        "four_three_way_valve_current",
        "heating.secondaryCircuit.valves.fourThreeWay",
        "current",
        **PERCENT,
    ),
    _spec(
        "four_three_way_valve_target",
        "heating.secondaryCircuit.valves.fourThreeWay",
        "target",
        **PERCENT,
    ),
    # --- power ---------------------------------------------------------------
    _spec("heat_production_current", "heating.heat.production.current", **POWER_KW),
    _spec("power_consumption_current", "heating.power.consumption.current", **POWER_KW),
    # --- compressor ----------------------------------------------------------
    _spec(
        "compressor_speed",
        "heating.compressors.{n}.speed.current",
        unit="rps",
        precision=1,
        numbering=NUMBER_SUFFIX,
    ),
    _spec(
        "compressor_speed_setpoint",
        "heating.compressors.{n}.speed.setpoint",
        unit="rps",
        precision=1,
        numbering=NUMBER_SUFFIX,
    ),
    _spec(
        "compressor_oil_temperature",
        "heating.compressors.{n}.sensors.temperature.oil",
        numbering=NUMBER_SUFFIX,
        **TEMPERATURE,
    ),
    _spec(
        "compressor_motor_chamber_temperature",
        "heating.compressors.{n}.sensors.temperature.motorChamber",
        numbering=NUMBER_SUFFIX,
        **TEMPERATURE,
    ),
    _spec(
        "crankcase_heater",
        "heating.compressors.{n}.heater.crankcase",
        "active",
        device_class="running",
        numbering=NUMBER_SUFFIX,
        **BINARY,
    ),
    # --- refrigerant circuit, outdoor unit -----------------------------------
    _spec(
        "economizer_liquid_temperature",
        "heating.economizers.{n}.sensors.temperature.liquid",
        numbering=NUMBER_SUFFIX,
        **TEMPERATURE,
    ),
    _spec(
        "expansion_valve_target",
        "heating.sensors.valve.{n}.expansion.target",
        numbering=NUMBER_PLUS_ONE,
        **PERCENT,
    ),
    _spec(
        "primary_fan_speed",
        "heating.primaryCircuit.fans.{n}.current",
        numbering=NUMBER_PLUS_ONE,
        **PERCENT,
    ),
    _spec("defrosting", "heating.outdoor.defrosting", "active", device_class="running", **BINARY),
    _spec(
        "evaporator_base_heater",
        "heating.evaporators.{n}.heater.base",
        "active",
        device_class="running",
        numbering=NUMBER_SUFFIX,
        **BINARY,
    ),
    _spec(
        "condensate_pan_heater",
        "heating.heater.condensatePan",
        "active",
        device_class="running",
        **BINARY,
    ),
    _spec("fan_ring_heater", "heating.heater.fanRing", "active", device_class="running", **BINARY),
    _spec(
        "primary_four_three_way_valve",
        "heating.primaryCircuit.valves.fourThreeWay",
        "active",
        enabled=False,
        **BINARY,
    ),
    # --- internal pump -------------------------------------------------------
    _spec(
        "internal_pump",
        "heating.boiler.pumps.internal",
        "status",
        device_class="running",
        on_value="on",
        **BINARY,
    ),
    _spec("internal_pump_speed", "heating.boiler.pumps.internal.current", **PERCENT),
    _spec("internal_pump_target", "heating.boiler.pumps.internal.target", **PERCENT),
    # --- instantaneous heating water heater ("heating rod") -------------------
    _spec("heating_rod", "heating.heatingRod", "active", **BINARY),
    _spec(
        "heating_rod_dhw_approved",
        "heating.configuration.heatingRod.dhw",
        "useApproved",
        **BINARY,
        **CONFIG,
    ),
    _spec(
        "heating_rod_heating_approved",
        "heating.configuration.heatingRod.heating",
        "useApproved",
        **BINARY,
        **CONFIG,
    ),
    _spec(
        "heating_rod_max_outside_temperature",
        "heating.heatingRod.maximumOutsideTemperature",
        **TEMPERATURE,
        **CONFIG,
    ),
    _spec(
        "secondary_heat_generator",
        "heating.secondaryHeatGenerator",
        "active",
        attributes=(("connection_type", "connectionType"),),
        **BINARY,
    ),
    # --- heating circuits ----------------------------------------------------
    _spec(
        "circuit_active_program",
        "heating.circuits.{n}.operating.programs.active",
        numbering=NUMBER_AS_IS,
        **ENUM,
    ),
    _spec(
        "circuit_temperature_level_min",
        "heating.circuits.{n}.temperature.levels",
        "min",
        numbering=NUMBER_AS_IS,
        **TEMPERATURE,
        **CONFIG,
    ),
    _spec(
        "circuit_temperature_level_max",
        "heating.circuits.{n}.temperature.levels",
        "max",
        numbering=NUMBER_AS_IS,
        **TEMPERATURE,
        **CONFIG,
    ),
    _spec(
        "circuit_summer_eco_threshold",
        "heating.circuits.{n}.configuration.summerEco.absolute",
        "threshold",
        numbering=NUMBER_AS_IS,
        attributes=(("active", "active"),),
        **TEMPERATURE,
        **CONFIG,
    ),
    # --- secondary circuit, boiler -------------------------------------------
    _spec(
        "secondary_return_minimum_temperature",
        "heating.secondaryCircuit.temperature.return.minimum",
        **TEMPERATURE,
        **CONFIG,
    ),
    _spec("boiler_temperature", "heating.boiler.temperature.current", enabled=False, **TEMPERATURE),
    # --- power limitation (section 14a EnWG) ---------------------------------
    _spec("power_limitation", "device.power.consumption.limitation", **ENUM),
    _spec(
        "power_status_consumption",
        "device.power.statusReport.consumption",
        "status",
        attributes=(("limit", "limit"),),
        **ENUM,
    ),
    _spec(
        "power_consumption_limit",
        "device.power.statusReport.consumption",
        "limit",
        device_class="power",
        unit="W",
        precision=0,
        minimum=0,
    ),
    _spec(
        "power_status_production",
        "device.power.statusReport.production",
        "status",
        attributes=(("limit", "limit"),),
        enabled=False,
        **ENUM,
    ),
    # --- domestic hot water --------------------------------------------------
    _spec("dhw_hygiene", "heating.dhw.hygiene", "enabled", diagnostic=True, **BINARY),
    _spec("dhw_scald_protection", "heating.dhw.scaldProtection", "active", diagnostic=True, **BINARY),
    # --- locks and programs --------------------------------------------------
    _spec("external_lock", "heating.external.lock", "active", **BINARY),
    _spec("device_external_lock", "device.lock.external", "active", enabled=False, **BINARY),
    _spec("malfunction_lock", "device.lock.malfunction", "active", device_class="problem", **BINARY),
    _spec(
        "holiday_program",
        "heating.operating.programs.holiday",
        "active",
        attributes=(("start", "start"), ("end", "end")),
        **BINARY,
    ),
    _spec(
        "holiday_at_home_program",
        "heating.operating.programs.holidayAtHome",
        "active",
        attributes=(("start", "start"), ("end", "end")),
        **BINARY,
    ),
)

ROOM = {"scope": SCOPE_ROOM}
ROOM_SETPOINT = {**TEMPERATURE, **ROOM, "measurement": False}

ROOM_SPECS: tuple[ValueSpec, ...] = (
    _spec("room_temperature", "rooms.{n}.sensors.temperature", **TEMPERATURE, **ROOM),
    _spec(
        "room_humidity",
        "rooms.{n}.sensors.humidity",
        device_class="humidity",
        unit="%",
        precision=0,
        **ROOM,
    ),
    ValueSpec(
        key="room_co2",
        sources=(("rooms.{n}.co2", "concentration"), ("rooms.{n}.sensors.co2", "value")),
        device_class="carbon_dioxide",
        unit="ppm",
        precision=0,
        **ROOM,
    ),
    ValueSpec(
        key="room_setpoint_normal_heating",
        sources=(
            ("rooms.{n}.temperature.levels.normal.heating", "temperature"),
            ("rooms.{n}.operating.programs.normalHeating", "temperature"),
        ),
        **ROOM_SETPOINT,
    ),
    ValueSpec(
        key="room_setpoint_reduced_heating",
        sources=(
            ("rooms.{n}.temperature.levels.reduced.heating", "temperature"),
            ("rooms.{n}.operating.programs.reducedHeating", "temperature"),
        ),
        **ROOM_SETPOINT,
    ),
    ValueSpec(
        key="room_setpoint_comfort_heating",
        sources=(
            ("rooms.{n}.temperature.levels.comfort.heating", "temperature"),
            ("rooms.{n}.operating.programs.comfortHeating", "temperature"),
        ),
        **ROOM_SETPOINT,
    ),
    _spec(
        "room_setpoint_normal_cooling",
        "rooms.{n}.temperature.levels.normal.cooling",
        "temperature",
        enabled=False,
        **ROOM_SETPOINT,
    ),
    _spec(
        "room_setpoint_reduced_cooling",
        "rooms.{n}.temperature.levels.reduced.cooling",
        "temperature",
        enabled=False,
        **ROOM_SETPOINT,
    ),
    _spec(
        "room_setpoint_normal_perceived",
        "rooms.{n}.temperature.levels.normal.perceived",
        "temperature",
        enabled=False,
        **ROOM_SETPOINT,
    ),
    _spec(
        "room_setpoint_comfort_perceived",
        "rooms.{n}.temperature.levels.comfort.perceived",
        "temperature",
        enabled=False,
        **ROOM_SETPOINT,
    ),
    _spec(
        "room_operating_level",
        "rooms.{n}.operating.state",
        "level",
        attributes=(("demand", "demand"), ("reason", "reason"), ("modifier", "modifier")),
        **ENUM,
        **ROOM,
    ),
    ValueSpec(
        key="room_window_open",
        sources=(
            ("rooms.{n}.sensors.openWindow", "value"),
            ("rooms.{n}.sensors.window.openState", "value"),
        ),
        device_class="window",
        **BINARY,
        **ROOM,
    ),
    _spec(
        "room_condensation_risk",
        "rooms.{n}.condensationRisk",
        device_class="problem",
        **BINARY,
        **ROOM,
    ),
    _spec("room_child_lock", "rooms.{n}.childLock", "active", diagnostic=True, **BINARY, **ROOM),
)

ALL_SPECS: tuple[ValueSpec, ...] = HEATING_SPECS + ROOM_SPECS

# States the enum sensors are known to take (after ``state_key``). Other
# values the API may send are added to the entity's options at runtime, so an
# unknown value shows up untranslated instead of breaking the entity.
ENUM_STATES: dict[str, tuple[str, ...]] = {
    # domesticHotWater, climateCircuitOne and climatCircuitTwoDefrost [sic]
    # were seen on real devices; the others are from ViEventLog's label table.
    "four_three_way_valve_position": (
        "domestic_hot_water",
        "climate_circuit_one",
        "climat_circuit_two_defrost",
        "climate_circuit_two_defrost_domestic_hot_water",
        "heating",
        "cooling",
        "defrost",
        "standby",
        "off",
    ),
    "secondary_circuit_state": ("heating", "cooling", "standby", "off"),
    "circuit_active_program": (
        "comfort",
        "comfort_heating",
        "comfort_cooling",
        "comfort_energy_saving",
        "comfort_cooling_energy_saving",
        "eco",
        "fixed",
        "forced_last_from_schedule",
        "frostprotection",
        "normal",
        "normal_heating",
        "normal_cooling",
        "normal_energy_saving",
        "normal_cooling_energy_saving",
        "reduced",
        "reduced_heating",
        "reduced_cooling",
        "reduced_energy_saving",
        "reduced_cooling_energy_saving",
        "standby",
        "summer_eco",
    ),
    "power_limitation": ("14a_off",),
    "power_status_consumption": ("unlimited_autonomous", "init"),
    "power_status_production": ("unlimited_autonomous", "init"),
    "room_operating_level": ("normal", "reduced", "comfort"),
}

SPECIAL_HISTORY = "history"
SPECIAL_SUMMARY = "summary"
SPECIAL_MESSAGES = "messages"
SPECIAL_LAST_STATUS = "last_status_message"
SPECIAL_ACTIVE_STATUS = "active_status_messages"
SPECIAL_OPERATING_STATE = "operating_state"
SPECIAL_HEATING_ROD_STAGE = "heating_rod_stage"
SPECIAL_COP = "cop"
SPECIAL_SCHEDULE = "schedule"


@dataclass(frozen=True, slots=True)
class SpecialSpec:
    """A sensor with its own logic (several features or computed values)."""

    key: str
    kind: str
    # The sensor is created when ``require`` of these features exist
    # ("any" or "all"); templates may contain "{n}".
    features: tuple[str, ...]
    require: str = "any"
    enabled: bool = True
    numbering: str = NUMBER_NONE

    @property
    def indexed(self) -> bool:
        """Return True when the feature template contains an index."""
        return "{n}" in self.features[0]


def _summary(key: str, feature: str, enabled: bool = True) -> SpecialSpec:
    return SpecialSpec(key=key, kind=SPECIAL_SUMMARY, features=(feature,), enabled=enabled)


_STATUS = "device.messages.status.raw"

SPECIAL_SPECS: tuple[SpecialSpec, ...] = (
    SpecialSpec("power_consumption_dhw_history", SPECIAL_HISTORY, ("heating.power.consumption.dhw",)),
    SpecialSpec("power_consumption_heating_history", SPECIAL_HISTORY, ("heating.power.consumption.heating",)),
    SpecialSpec("power_consumption_total_history", SPECIAL_HISTORY, ("heating.power.consumption.total",)),
    _summary("heat_production_dhw_summary", "heating.heat.production.summary.dhw"),
    _summary("heat_production_heating_summary", "heating.heat.production.summary.heating"),
    _summary("heat_production_cooling_summary", "heating.heat.production.summary.cooling", False),
    _summary("power_consumption_cooling_summary", "heating.power.consumption.summary.cooling", False),
    _summary(
        "heating_rod_power_consumption_dhw_summary",
        "heating.heatingRod.power.consumption.summary.dhw",
    ),
    _summary(
        "heating_rod_power_consumption_heating_summary",
        "heating.heatingRod.power.consumption.summary.heating",
    ),
    SpecialSpec(
        "messages",
        SPECIAL_MESSAGES,
        (_STATUS, "device.messages.info.raw", "device.messages.service.raw"),
    ),
    SpecialSpec("last_status_message", SPECIAL_LAST_STATUS, (_STATUS,)),
    SpecialSpec("active_status_messages", SPECIAL_ACTIVE_STATUS, (_STATUS,)),
    SpecialSpec("operating_state", SPECIAL_OPERATING_STATE, (_STATUS, "heating.compressors.0")),
    SpecialSpec(
        "heating_rod_stage",
        SPECIAL_HEATING_ROD_STAGE,
        (_STATUS, "heating.heatingRod"),
        require="all",
    ),
    SpecialSpec(
        "cop_current",
        SPECIAL_COP,
        ("heating.heat.production.current", "heating.power.consumption.current"),
        require="all",
    ),
    SpecialSpec("dhw_schedule", SPECIAL_SCHEDULE, ("heating.dhw.schedule",)),
    SpecialSpec(
        "dhw_circulation_schedule",
        SPECIAL_SCHEDULE,
        ("heating.dhw.pumps.circulation.schedule",),
    ),
    SpecialSpec(
        "circuit_heating_schedule",
        SPECIAL_SCHEDULE,
        ("heating.circuits.{n}.heating.schedule",),
        numbering=NUMBER_AS_IS,
    ),
)

# Modes a schedule sensor can show besides the modes of the time slots.
SCHEDULE_STATES = (
    "none",
    "inactive",
    "on",
    "off",
    "normal",
    "reduced",
    "comfort",
    "5_25_cycles",
    "5_10_cycles",
)

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NOT_KEY = re.compile(r"[^a-z0-9]+")
_ROOM_FEATURE = re.compile(r"^rooms\.(\d+)(?:\.|$)")


def state_key(value: Any) -> str | None:
    """Turn an API enum value into a translatable state.

    ``domesticHotWater`` -> ``domestic_hot_water``, ``14aOff`` -> ``14a_off``,
    ``5/25-cycles`` -> ``5_25_cycles``.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    key = _NOT_KEY.sub("_", _CAMEL.sub("_", value.strip()).lower()).strip("_")
    return key or None


def _pattern(template: str) -> re.Pattern[str]:
    return re.compile("^" + re.escape(template).replace(r"\{n\}", r"(\d+)") + "$")


_PATTERNS: dict[str, re.Pattern[str]] = {}


def _match(template: str, name: str) -> re.Match[str] | None:
    pattern = _PATTERNS.get(template)
    if pattern is None:
        pattern = _PATTERNS[template] = _pattern(template)
    return pattern.match(name)


def _property(feature: dict[str, Any], prop: str) -> dict[str, Any] | None:
    properties = feature.get("properties")
    value = properties.get(prop) if isinstance(properties, dict) else None
    return value if isinstance(value, dict) and "value" in value else None


def find_source(
    spec: ValueSpec, features: dict[str, dict[str, Any]], index: int | None
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return (feature, property object) of the first existing source."""
    for template, prop in spec.sources:
        name = template if index is None else template.replace("{n}", str(index))
        feature = features.get(name)
        if feature is None:
            continue
        if (found := _property(feature, prop)) is not None:
            return feature, found
    return None


def find_indexes(spec: ValueSpec, features: dict[str, dict[str, Any]]) -> list[int | None]:
    """Return the indexes for which a spec has a source with the property.

    Non-indexed specs yield ``[None]`` when the property exists, else ``[]``.
    """
    if not spec.indexed:
        return [None] if find_source(spec, features, None) is not None else []
    indexes: set[int] = set()
    for template, _ in spec.sources:
        for name in features:
            if (match := _match(template, name)) is not None:
                indexes.add(int(match.group(1)))
    return [index for index in sorted(indexes) if find_source(spec, features, index) is not None]


def read_value(
    spec: ValueSpec, features: dict[str, dict[str, Any]], index: int | None
) -> Any:
    """Return the entity state for a spec: number, state key or bool."""
    source = find_source(spec, features, index)
    if source is None:
        return None
    raw = source[1].get("value")
    if spec.kind == KIND_BOOL:
        if spec.on_value is not None:
            return raw == spec.on_value if isinstance(raw, str) else None
        return raw if isinstance(raw, bool) else None
    if spec.kind == KIND_ENUM:
        return state_key(raw)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if spec.minimum is not None and raw < spec.minimum:
        return None
    return raw


def read_unit(
    spec: ValueSpec, features: dict[str, dict[str, Any]], index: int | None
) -> str | None:
    """Return the Home Assistant unit: mapped API unit, else the spec default."""
    source = find_source(spec, features, index)
    api_unit = source[1].get("unit") if source is not None else None
    if isinstance(api_unit, str) and api_unit in UNITS:
        return UNITS[api_unit]
    return spec.unit


def read_attributes(
    spec: ValueSpec, features: dict[str, dict[str, Any]], index: int | None
) -> dict[str, Any]:
    """Return the extra attributes of a spec."""
    source = find_source(spec, features, index)
    if source is None or not spec.attributes:
        return {}
    feature = source[0]
    result: dict[str, Any] = {}
    for attribute, prop in spec.attributes:
        found = _property(feature, prop)
        if found is not None:
            value = found.get("value")
            # Enum sensors show their string attributes like their state.
            if spec.kind == KIND_ENUM and isinstance(value, str):
                value = state_key(value)
            result[attribute] = value
    return result


def name_placeholders(spec: ValueSpec, index: int | None) -> dict[str, str]:
    """Return the placeholders for the translated entity name."""
    if index is None or spec.numbering == NUMBER_NONE:
        return {}
    if spec.numbering == NUMBER_AS_IS:
        return {"number": str(index)}
    if spec.numbering == NUMBER_PLUS_ONE:
        return {"number": str(index + 1)}
    return {"suffix": "" if index == 0 else f" {index + 1}"}


def unique_suffix(spec: ValueSpec, index: int | None) -> str:
    """Return the part of the unique id after the device identifier."""
    if index is None or spec.scope == SCOPE_ROOM:
        return spec.key
    return f"{spec.key}-{index}"


def room_indexes(features: dict[str, dict[str, Any]]) -> list[int]:
    """Return the indexes of the rooms present in a room control's features."""
    indexes = {
        int(match.group(1))
        for name in features
        if (match := _ROOM_FEATURE.match(name)) is not None
    }
    return sorted(indexes)


def room_name(features: dict[str, dict[str, Any]], index: int) -> str | None:
    """Return the name the user gave a room, if the API tells it."""
    feature = features.get(f"rooms.{index}")
    found = _property(feature, "name") if feature is not None else None
    name = found.get("value") if found is not None else None
    return name.strip() if isinstance(name, str) and name.strip() else None


def special_indexes(
    spec: SpecialSpec, features: dict[str, dict[str, Any]]
) -> list[int | None]:
    """Return the indexes for which a special sensor has to exist."""
    if spec.indexed:
        indexes: set[int] = set()
        for name in features:
            if (match := _match(spec.features[0], name)) is not None:
                indexes.add(int(match.group(1)))
        return sorted(indexes)
    present = [name in features for name in spec.features]
    wanted = all(present) if spec.require == "all" else any(present)
    return [None] if wanted else []


def special_placeholders(spec: SpecialSpec, index: int | None) -> dict[str, str]:
    """Return the placeholders for the translated entity name."""
    if index is None or spec.numbering == NUMBER_NONE:
        return {}
    return {"number": str(index if spec.numbering == NUMBER_AS_IS else index + 1)}
