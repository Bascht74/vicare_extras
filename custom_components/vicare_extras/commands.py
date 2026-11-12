"""Send a command to the Viessmann API (no Home Assistant imports).

Commands are the only write access of this integration and are only sent when
the user changes a target temperature in Home Assistant, never on a schedule.

Only commands the API itself advertises are used: the cached feature object
carries a ``commands`` object such as::

    "commands": {"setTemperature": {
        "name": "setTemperature", "isExecutable": true, "uri": "...",
        "params": {"targetTemperature": {"type": "number", "required": true,
                   "constraints": {"min": 8, "max": 30, "stepping": 0.5}}}}}

``number_command`` reads name, parameter and limits from there; a command that
is missing or not executable is not offered.

The command is sent through the PyViCare service of the built-in integration
(same login, one POST). ``execute`` blocks and must run in the executor.

One command is one API call. PyViCare's *cached* service empties its cache
after ``setProperty``; the built-in integration would then fetch everything
again on its next read (its binary sensors, climate entities and so on read
every 30 s), which is a second API call per command. To avoid that, the
command is sent with ``setProperty`` of PyViCare's plain ``ViCareService``
base class (found by name in the class hierarchy), which only posts. The
cache keeps its content until the next regular poll of the built-in
integration; until then the entity shows the value that was sent. If that
base class is not found, ``service.setProperty`` is used as it is (and
PyViCare empties the cache).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
import logging
from typing import Any

from .errors import ViCareExtrasError

_LOGGER = logging.getLogger(__name__)
_MAX_TEXT = 300


@dataclass(frozen=True, slots=True)
class NumberCommand:
    """A command with exactly one required numeric parameter."""

    feature: str
    name: str
    param: str
    minimum: float | None
    maximum: float | None
    step: float | None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def number_command(
    feature: dict[str, Any] | None, names: tuple[str, ...]
) -> NumberCommand | None:
    """Return the first executable command of ``names`` the feature offers."""
    commands = feature.get("commands") if isinstance(feature, dict) else None
    if not isinstance(commands, dict) or not isinstance(feature.get("feature"), str):
        return None
    for name in names:
        command = commands.get(name)
        if not isinstance(command, dict) or command.get("isExecutable") is not True:
            continue
        params = command.get("params")
        if not isinstance(params, dict):
            continue
        required = {
            key: value
            for key, value in params.items()
            if isinstance(value, dict) and value.get("required") is True
        }
        if len(required) != 1:
            continue
        param, definition = next(iter(required.items()))
        if definition.get("type") != "number":
            continue
        constraints = definition.get("constraints")
        constraints = constraints if isinstance(constraints, dict) else {}
        return NumberCommand(
            feature=feature["feature"],
            name=name,
            param=param,
            minimum=_number(constraints.get("min")),
            maximum=_number(constraints.get("max")),
            step=_number(constraints.get("stepping")),
        )
    return None


def check_value(command: NumberCommand, value: Any) -> float:
    """Return the value as float or raise when it violates the API's limits."""
    number = _number(value)
    low, high = command.minimum, command.maximum
    if number is None or (low is not None and number < low) or (
        high is not None and number > high
    ):
        raise ViCareExtrasError(
            "value_out_of_range",
            {
                "value": value,
                "min": "-" if low is None else f"{low:g}",
                "max": "-" if high is None else f"{high:g}",
            },
            validation=True,
        )
    return number


def _short(value: Any) -> str:
    text = str(value)
    return text if len(text) <= _MAX_TEXT else f"{text[:_MAX_TEXT]}…"


def _map_exception(err: Exception) -> ViCareExtrasError:
    names = {cls.__name__ for cls in type(err).__mro__}
    message = _short(getattr(err, "message", None) or err)
    if "PyViCareRateLimitError" in names:
        reset = getattr(err, "limitResetDate", None)
        try:
            reset_text = f"{reset:%Y-%m-%d %H:%M} UTC"
        except (TypeError, ValueError):
            reset_text = "unknown"
        return ViCareExtrasError("rate_limited", {"reset": reset_text})
    if "PyViCareCommandError" in names:
        return ViCareExtrasError("command_failed", {"reason": message})
    if "PyViCareInternalServerError" in names or "PyViCareDeviceCommunicationError" in names:
        return ViCareExtrasError("server_error", {"message": message})
    return ViCareExtrasError(
        "unexpected_error", {"error": f"{type(err).__name__}: {_short(err)}"}
    )


def _check_response(response: Any) -> None:
    """Raise when the answer of the API reports a failed command."""
    if not isinstance(response, dict):
        return
    status = response.get("statusCode")
    if isinstance(status, int) and status >= 400:
        payload = response.get("extendedPayload")
        reason = payload.get("reason") if isinstance(payload, dict) else None
        reason = reason or response.get("message") or response.get("errorType")
        raise ViCareExtrasError("command_failed", {"reason": _short(reason or status)})
    data = response.get("data")
    if isinstance(data, dict) and data.get("success") is False:
        raise ViCareExtrasError(
            "command_failed", {"reason": _short(data.get("reason") or "success: false")}
        )


def _sender(service: Any) -> Callable[..., Any] | None:
    """Return the callable that posts a command for this service.

    Preferably ``ViCareService.setProperty`` (only posts); otherwise the
    service's own ``setProperty`` (the cached services also empty the cache).
    """
    for cls in type(service).__mro__:
        method = cls.__dict__.get("setProperty")
        if cls.__name__ == "ViCareService" and callable(method):
            return partial(method, service)
    method = getattr(service, "setProperty", None)
    return method if callable(method) else None


def execute(service: Any, accessor: Any, command: NumberCommand, value: Any) -> float:
    """Send the command (blocking, one API call). Returns the value sent."""
    number = check_value(command, value)
    send = _sender(service)
    if accessor is None or send is None:
        raise ViCareExtrasError(
            "vicare_incompatible", {"detail": "service.setProperty is not available"}
        )
    # Send whole numbers as int, like the Viessmann apps do.
    payload = {command.param: int(number) if number.is_integer() else number}
    try:
        response = send(accessor, command.feature, command.name, payload)
    except Exception as err:  # noqa: BLE001 - mapped to a readable error
        raise _map_exception(err) from err
    _check_response(response)
    _LOGGER.debug("Command %s on %s sent", command.name, command.feature)
    return number
