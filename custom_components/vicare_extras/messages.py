"""Decode Viessmann One Base message codes (S., I., A., P., F.).

The table lives in ``data/message_codes.json`` (built by
``scripts/build_message_codes.py``). Primary source is Viessmann's service
manual 6200041; texts marked ``vieventlog`` fill codes that manual does not
list. Unknown codes degrade gracefully: the text is ``None`` and callers show
the raw code.

No Home Assistant imports. ``load_table`` reads a file, so Home Assistant
calls it once in the executor during setup; afterwards lookups are in memory.
"""

from __future__ import annotations

from functools import lru_cache
import json
import logging
from pathlib import Path
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

TABLE_PATH = Path(__file__).parent / "data" / "message_codes.json"

CATEGORIES = {
    "S": "status",
    "I": "info",
    "A": "warning",
    "P": "maintenance",
    "F": "fault",
}

_CODE = re.compile(r"^\s*([A-Za-z])\.0*(\d+)\s*$")


def normalize_code(code: Any) -> str | None:
    """Return ``S.123`` for ``s.0123`` and None for anything else."""
    if not isinstance(code, str) or (match := _CODE.match(code)) is None:
        return None
    return f"{match.group(1).upper()}.{int(match.group(2))}"


def category(code: Any) -> str | None:
    """Return status/info/warning/maintenance/fault for a code."""
    normalized = normalize_code(code)
    return CATEGORIES.get(normalized[0]) if normalized else None


@lru_cache(maxsize=1)
def load_table() -> dict[str, dict[str, str]]:
    """Read the code table (blocking file access, cached)."""
    try:
        data = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
        codes = data["codes"]
        if not isinstance(codes, dict):
            raise TypeError("codes is not an object")
    except (OSError, ValueError, KeyError, TypeError) as err:
        _LOGGER.warning("Message code table could not be read: %s", err)
        return {}
    return codes


def describe(code: Any, language: str = "de") -> dict[str, Any]:
    """Return code, text, source and category for a message code.

    The text is taken in the requested language and falls back to German
    (the only language the sources provide). Unknown codes get text None.
    """
    normalized = normalize_code(code)
    raw = code if isinstance(code, str) else None
    entry = load_table().get(normalized or "", {})
    text = entry.get(language[:2].lower()) or entry.get("de")
    return {
        "code": normalized or raw,
        "text": text,
        "source": entry.get("source") if text else None,
        "category": category(code),
    }


def label(code: Any, language: str = "de") -> str | None:
    """Return the text of a code, or the raw code when it is unknown."""
    info = describe(code, language)
    return info["text"] or info["code"]


def decode_entries(
    entries: list[dict[str, Any]], language: str = "de"
) -> list[dict[str, Any]]:
    """Add ``text`` (and ``source``) to message entries with an errorCode."""
    decoded: list[dict[str, Any]] = []
    for entry in entries:
        info = describe(entry.get("errorCode"), language)
        item = dict(entry)
        item["text"] = info["text"]
        if info["source"]:
            item["source"] = info["source"]
        decoded.append(item)
    return decoded


def _format_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def decode_event(event: dict[str, Any], language: str = "de") -> dict[str, Any]:
    """Return a copy of an event-history event with readable additions.

    The raw event is kept as it is; these keys are added when possible:

    ``decoded``  for ``device-message-*`` / ``device-error`` events: code,
                 text, source, category and the ``active`` flag of the body.
    ``summary``  one readable line. Messages: ``S.123: Wärmepumpe aus``.
                 ``feature-changed``: ``<feature>: <command>(<arguments>)``.
    """
    result = dict(event)
    body = event.get("body")
    if not isinstance(body, dict):
        return result
    event_type = str(event.get("eventType") or "")

    if "errorCode" in body and (
        event_type.startswith("device-message") or event_type == "device-error"
    ):
        info = describe(body.get("errorCode"), language)
        if isinstance(body.get("active"), bool):
            info["active"] = body["active"]
        result["decoded"] = info
        if info["code"]:
            result["summary"] = (
                f"{info['code']}: {info['text']}" if info["text"] else info["code"]
            )
    elif event_type == "feature-changed" and body.get("featureName"):
        summary = str(body["featureName"])
        if command := body.get("commandName"):
            arguments = body.get("commandBody")
            if isinstance(arguments, dict):
                rendered = ", ".join(
                    f"{key}={_format_value(value)}" for key, value in arguments.items()
                )
            elif arguments is None:
                rendered = ""
            else:
                rendered = _format_value(arguments)
            summary = f"{summary}: {command}({rendered})"
        result["summary"] = summary
    return result
