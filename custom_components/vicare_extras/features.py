"""Turn raw ViCare feature objects into sensor values and action responses.

Pure functions, no Home Assistant and no PyViCare imports.

A feature object as delivered by the Viessmann API looks like this::

    {
        "feature": "heating.power.consumption.dhw",
        "timestamp": "2025-10-05T05:14:18.020Z",
        "isEnabled": true, "isReady": true,
        "properties": {
            "day": {"type": "array", "unit": "kilowattHour", "value": [2.6, 5.8, ...]},
            "dayValueReadAt": {"type": "string", "value": "2025-10-05T05:14:16.233Z"},
            ...
        },
        "commands": {...}, "uri": "...", "deviceId": "0", "gatewayId": "..."
    }
"""

from __future__ import annotations

import re
from typing import Any

from .const import (
    FEATURE_MESSAGES_INFO,
    FEATURE_MESSAGES_SERVICE,
    FEATURE_MESSAGES_STATUS,
    MESSAGE_LIST_LIMIT,
)

HISTORY_PERIODS = ("day", "week", "month", "year")
MESSAGE_KEYS = ("errorCode", "timestamp", "priority")
MESSAGE_FEATURES = {
    "status": FEATURE_MESSAGES_STATUS,
    "info": FEATURE_MESSAGES_INFO,
    "service": FEATURE_MESSAGES_SERVICE,
}
SLIM_FEATURE_KEYS = ("feature", "timestamp", "isEnabled", "isReady", "properties")

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def snake_case(name: str) -> str:
    """Convert a camelCase property name to snake_case."""
    return _CAMEL_RE.sub("_", name).lower()


def _properties(feature: dict[str, Any] | None) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature, dict) else None
    return props if isinstance(props, dict) else {}


def prop_value(feature: dict[str, Any] | None, name: str) -> Any:
    """Return ``properties.<name>.value`` or None."""
    prop = _properties(feature).get(name)
    return prop.get("value") if isinstance(prop, dict) else None


def prop_unit(feature: dict[str, Any] | None, name: str) -> str | None:
    """Return ``properties.<name>.unit`` or None."""
    prop = _properties(feature).get(name)
    unit = prop.get("unit") if isinstance(prop, dict) else None
    return unit if isinstance(unit, str) else None


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def history_value(feature: dict[str, Any] | None) -> float | int | None:
    """Return today's value (first element of the ``day`` array)."""
    day = prop_value(feature, "day")
    if isinstance(day, list) and day:
        return _number(day[0])
    return None


def history_unit(feature: dict[str, Any] | None) -> str | None:
    """Return the raw ViCare unit of the ``day`` array."""
    return prop_unit(feature, "day")


def history_attributes(feature: dict[str, Any] | None) -> dict[str, Any]:
    """Return the history arrays and their read timestamps."""
    attributes: dict[str, Any] = {}
    for period in HISTORY_PERIODS:
        values = prop_value(feature, period)
        if isinstance(values, list):
            attributes[period] = list(values)
        read_at = prop_value(feature, f"{period}ValueReadAt")
        if isinstance(read_at, str):
            attributes[f"{period}_value_read_at"] = read_at
    return attributes


def summary_value(feature: dict[str, Any] | None) -> float | int | None:
    """Return the ``currentDay`` value of a summary feature."""
    return _number(prop_value(feature, "currentDay"))


def summary_unit(feature: dict[str, Any] | None) -> str | None:
    """Return the raw ViCare unit of a summary feature."""
    return prop_unit(feature, "currentDay")


def summary_attributes(feature: dict[str, Any] | None) -> dict[str, Any]:
    """Return every numeric summary property under a snake_case key."""
    attributes: dict[str, Any] = {}
    for name in _properties(feature):
        value = _number(prop_value(feature, name))
        if value is not None:
            attributes[snake_case(name)] = value
    return attributes


def message_entries(feature: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the message entries of a ``device.messages.*.raw`` feature.

    Entries are reduced to errorCode, timestamp and priority and sorted newest
    first. ISO 8601 UTC timestamps sort correctly as strings.
    """
    raw = prop_value(feature, "entries")
    if not isinstance(raw, list):
        return []
    entries = [
        {key: entry.get(key) for key in MESSAGE_KEYS if key in entry}
        for entry in raw
        if isinstance(entry, dict)
    ]
    entries.sort(key=lambda entry: str(entry.get("timestamp") or ""), reverse=True)
    return entries


def messages_state(
    features: dict[str, dict[str, Any]],
) -> tuple[str | None, dict[str, Any]]:
    """Return the newest status code and the message attributes."""
    attributes: dict[str, Any] = {}
    newest_status: dict[str, Any] | None = None
    for name, feature_name in MESSAGE_FEATURES.items():
        if feature_name not in features:
            continue
        entries = message_entries(features[feature_name])
        attributes[name] = entries[:MESSAGE_LIST_LIMIT]
        attributes[f"{name}_count"] = len(entries)
        if name == "status" and entries:
            newest_status = entries[0]
    code = newest_status.get("errorCode") if newest_status else None
    attributes["newest_status_timestamp"] = (
        newest_status.get("timestamp") if newest_status else None
    )
    return (str(code) if code is not None else None), attributes


def slim_feature(feature: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    """Return the feature for an action response.

    By default only name, timestamp, enabled/ready flags and properties are
    returned; ``full`` returns the object as delivered by the API (including
    commands, URI, device and gateway id).
    """
    if full:
        return dict(feature)
    return {key: feature[key] for key in SLIM_FEATURE_KEYS if key in feature}
