"""On-demand access to the Viessmann event history.

Endpoint (relative to PyViCare's base URL ``.../iot/v2``)::

    GET /events-history/installations/{installationId}/events
    query: lastNDays | date | timestamp (mutually exclusive), limit (default
           50, max 1000), cursor, eventType, gatewaySerials, editedBy, origins
    response: {"cursor": {"next": "<opaque>"}, "data": [event, ...]}

The hyphenated path is the one that answers when called through PyViCare
(confirmed live). Viessmann's API documentation names
``/eventhistory/installations/{installationId}/events``; that path answered
"not found" and is only kept as a fallback.

The request goes through ``oauth_manager.get()`` of the PyViCare client the
built-in integration already authenticated. PyViCare prepends its base URL
(``https://api.viessmann-climatesolutions.com/iot/v2``), renews the token when
needed and raises its own exceptions for rate limiting and server errors. This
module never touches tokens or the HTTP session itself.

``fetch_event_history`` blocks (HTTP via ``requests``) and must run in the
executor. Every page is one API call that counts against the daily quota.

No Home Assistant imports; PyViCare exceptions are recognised by class name so
this module does not depend on a specific PyViCare version being importable.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import logging
from typing import Any
from urllib.parse import quote, urlencode

from .const import EVENT_HISTORY_PATHS
from .errors import ViCareExtrasError

_LOGGER = logging.getLogger(__name__)

_NOT_FOUND_STATUS = (404, 410)
_FORBIDDEN_STATUS = (401, 403)
_MAX_TEXT = 300


class _EndpointUnavailable(Exception):
    """The requested path does not exist (or did not answer with JSON)."""


def _short(value: Any) -> str:
    text = str(value)
    return text if len(text) <= _MAX_TEXT else f"{text[:_MAX_TEXT]}…"


def _class_names(err: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(err).__mro__}


def _map_exception(err: Exception) -> Exception:
    """Translate an exception raised by ``oauth_manager.get``."""
    names = _class_names(err)
    if "PyViCareRateLimitError" in names:
        reset = getattr(err, "limitResetDate", None)
        try:
            reset_text = f"{reset:%Y-%m-%d %H:%M} UTC"
        except (TypeError, ValueError):
            reset_text = "unknown"
        return ViCareExtrasError("rate_limited", {"reset": reset_text})
    if "PyViCareInternalServerError" in names:
        # PyViCare wraps every OSError into this class, including the JSON
        # decoding error of a non-JSON body (e.g. an HTML "not found" page).
        if isinstance(err.__cause__, ValueError):
            return _EndpointUnavailable("the answer was not JSON")
        return ViCareExtrasError(
            "server_error", {"message": _short(getattr(err, "message", err))}
        )
    if "PyViCareDeviceCommunicationError" in names:
        return ViCareExtrasError(
            "server_error", {"message": _short(getattr(err, "message", err))}
        )
    if "PyViCareNotPaidForError" in names:
        return ViCareExtrasError(
            "event_history_forbidden",
            {"status": "-", "message": _short(getattr(err, "message", err))},
        )
    return ViCareExtrasError(
        "unexpected_error", {"error": f"{type(err).__name__}: {_short(err)}"}
    )


def _check_error_response(response: Any) -> None:
    """Raise for a response that is not an event page."""
    if not isinstance(response, dict):
        raise ViCareExtrasError(
            "invalid_response", {"detail": f"type {type(response).__name__}"}
        )
    if isinstance(response.get("data"), list):
        return

    status = response.get("statusCode")
    error_type = response.get("errorType") or response.get("error")
    message = response.get("message") or response.get("error_description") or ""

    if status in _NOT_FOUND_STATUS or "NOT_FOUND" in str(error_type).upper():
        raise _EndpointUnavailable(f"status {status}")
    if status in _FORBIDDEN_STATUS:
        raise ViCareExtrasError(
            "event_history_forbidden",
            {"status": status, "message": _short(message or error_type or "")},
        )
    if status == 429:
        raise ViCareExtrasError("rate_limited", {"reset": "unknown"})
    if status is not None or error_type is not None:
        raise ViCareExtrasError(
            "api_error",
            {
                "status": status if status is not None else "-",
                "error_type": _short(error_type or "-"),
                "message": _short(message or "-"),
            },
        )
    raise ViCareExtrasError(
        "invalid_response", {"detail": f"keys {sorted(map(str, response))[:10]}"}
    )


def _request(oauth_manager: Any, path: str, params: dict[str, str]) -> dict[str, Any]:
    """Perform one request and return the event page."""
    url = f"{path}?{urlencode(params)}"
    try:
        response = oauth_manager.get(url)
    except Exception as err:  # noqa: BLE001 - mapped to a readable error
        raise _map_exception(err) from err
    _check_error_response(response)
    return response


def _next_cursor(response: dict[str, Any]) -> str | None:
    cursor = response.get("cursor")
    if isinstance(cursor, dict):
        cursor = cursor.get("next")
    return cursor if isinstance(cursor, str) and cursor else None


def _clean(values: Iterable[Any] | None) -> list[str]:
    return [str(value).strip() for value in (values or ()) if str(value).strip()]


def path_template(
    endpoint: str | None, installation_id: str | int, paths: Sequence[str]
) -> str | None:
    """Return the path template an endpoint returned by a fetch was built from."""
    installation = quote(str(installation_id), safe="")
    for path in paths:
        if path.format(installation_id=installation) == endpoint:
            return path
    return None


def fetch_event_history(
    oauth_manager: Any,
    installation_id: str | int,
    *,
    last_n_days: int,
    limit: int,
    max_pages: int,
    event_types: Iterable[str] | None = None,
    gateway_serials: Iterable[str] | None = None,
    edited_by: str | None = None,
    cursor: str | None = None,
    paths: Sequence[str] = EVENT_HISTORY_PATHS,
) -> dict[str, Any]:
    """Fetch up to ``max_pages`` pages of the event history (blocking).

    The first request tries ``paths`` in order and moves on to the next path
    only when the answer is "not found". Later pages stay on the path that
    worked.
    """
    types = _clean(event_types)
    serials = _clean(gateway_serials)

    params: dict[str, str] = {"lastNDays": str(last_n_days), "limit": str(limit)}
    if len(types) == 1:
        # A single type is filtered by the server. The syntax for several
        # values is not documented, so several types are filtered locally.
        params["eventType"] = types[0]
    if serials:
        params["gatewaySerials"] = ",".join(serials)
    if edited_by:
        params["editedBy"] = edited_by

    installation = quote(str(installation_id), safe="")
    candidates = [path.format(installation_id=installation) for path in paths]

    events: list[dict[str, Any]] = []
    endpoint: str | None = None
    next_cursor = cursor or None
    truncated = False
    api_calls = 0
    pages = 0

    while True:
        page_params = dict(params)
        if next_cursor:
            page_params["cursor"] = next_cursor

        if endpoint is None:
            for candidate in candidates:
                api_calls += 1
                try:
                    response = _request(oauth_manager, candidate, page_params)
                except _EndpointUnavailable as err:
                    _LOGGER.debug("Event history path %s unavailable: %s", candidate, err)
                    continue
                endpoint = candidate
                break
            else:
                raise ViCareExtrasError(
                    "event_history_not_found", {"endpoints": ", ".join(candidates)}
                )
        else:
            api_calls += 1
            try:
                response = _request(oauth_manager, endpoint, page_params)
            except _EndpointUnavailable as err:
                raise ViCareExtrasError(
                    "api_error",
                    {"status": "404", "error_type": "-", "message": _short(err)},
                ) from err

        pages += 1
        page_events = [item for item in response["data"] if isinstance(item, dict)]
        events.extend(page_events)

        new_cursor = _next_cursor(response)
        if new_cursor is None or new_cursor == next_cursor:
            next_cursor = None
            break
        next_cursor = new_cursor
        if not page_events:
            break
        if pages >= max_pages:
            truncated = True
            break

    fetched = len(events)
    if types:
        wanted = set(types)
        events = [event for event in events if event.get("eventType") in wanted]

    return {
        "installation_id": str(installation_id),
        "endpoint": endpoint,
        "count": len(events),
        "fetched_count": fetched,
        "pages": pages,
        "api_calls": api_calls,
        "truncated": truncated,
        "next_cursor": next_cursor,
        "events": events,
    }
