"""Tests for the on-demand event history request."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from custom_components.vicare_extras.const import EVENT_HISTORY_PATHS
from custom_components.vicare_extras.errors import ViCareExtrasError
from custom_components.vicare_extras.event_history import (
    fetch_event_history,
    path_template,
)

from . import fakes

# The hyphenated path is the one that works live; the path from Viessmann's
# documentation is the fallback.
PRIMARY = "/events-history/installations/2323232/events"
FALLBACK = "/eventhistory/installations/2323232/events"
NOT_FOUND = {"viErrorId": "x", "statusCode": 404, "errorType": "ROUTE_NOT_FOUND", "message": "Not Found"}


def event(event_type: str = "device-message-status", n: int = 0) -> dict:
    return {
        "eventType": event_type,
        "createdAt": f"2026-11-12T08:00:{n:02d}.000Z",
        "eventTimestamp": f"2026-11-12T08:00:{n:02d}.000Z",
        "gatewaySerial": fakes.GATEWAY_SERIAL,
        "body": {"errorCode": f"S.{n}"},
    }


def page(events: list[dict], next_cursor: str | None = None) -> dict:
    return {"cursor": {"next": next_cursor} if next_cursor else {}, "data": events}


def fetch(manager: fakes.FakeOAuthManager, **kwargs):
    arguments = {"last_n_days": 30, "limit": 1000, "max_pages": 5} | kwargs
    return fetch_event_history(manager, 2323232, **arguments)


def query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def test_hyphenated_path_is_tried_first() -> None:
    assert EVENT_HISTORY_PATHS[0].format(installation_id=2323232) == PRIMARY
    assert EVENT_HISTORY_PATHS[1].format(installation_id=2323232) == FALLBACK


def test_single_page() -> None:
    manager = fakes.FakeOAuthManager(page([event(n=1), event(n=2)]))
    result = fetch(manager)

    assert len(manager.urls) == 1
    assert urlsplit(manager.urls[0]).path == PRIMARY  # relative to PyViCare's /iot/v2
    assert query(manager.urls[0]) == {"lastNDays": "30", "limit": "1000"}
    assert result == {
        "installation_id": "2323232",
        "endpoint": PRIMARY,
        "count": 2,
        "fetched_count": 2,
        "pages": 1,
        "api_calls": 1,
        "truncated": False,
        "next_cursor": None,
        "events": [event(n=1), event(n=2)],
    }


def test_follows_cursor_until_exhausted() -> None:
    manager = fakes.FakeOAuthManager(
        page([event(n=1)], "c1"), page([event(n=2)], "c2"), page([event(n=3)])
    )
    result = fetch(manager)

    assert [query(url).get("cursor") for url in manager.urls] == [None, "c1", "c2"]
    assert all(query(url)["lastNDays"] == "30" for url in manager.urls)
    assert result["count"] == 3
    assert result["pages"] == result["api_calls"] == 3
    assert result["next_cursor"] is None
    assert result["truncated"] is False


def test_stops_at_max_pages_and_returns_cursor() -> None:
    manager = fakes.FakeOAuthManager(
        page([event(n=1)], "c1"), page([event(n=2)], "c2"), page([event(n=3)], "c3")
    )
    result = fetch(manager, max_pages=2)

    assert len(manager.urls) == 2
    assert result["count"] == 2
    assert result["api_calls"] == 2
    assert result["truncated"] is True
    assert result["next_cursor"] == "c2"


def test_continue_with_cursor() -> None:
    manager = fakes.FakeOAuthManager(page([event(n=3)]))
    result = fetch(manager, cursor="c2")
    assert query(manager.urls[0])["cursor"] == "c2"
    assert result["count"] == 1


def test_stops_on_repeated_cursor_and_empty_page() -> None:
    manager = fakes.FakeOAuthManager(page([event(n=1)], "same"), page([event(n=2)], "same"))
    result = fetch(manager)
    assert len(manager.urls) == 2
    assert result["next_cursor"] is None

    manager = fakes.FakeOAuthManager(page([], "more"))
    result = fetch(manager)
    assert len(manager.urls) == 1
    assert result["count"] == 0
    assert result["next_cursor"] == "more"
    assert result["truncated"] is False


@pytest.mark.parametrize(
    "first_answer",
    [
        NOT_FOUND,
        {"statusCode": 410, "message": "Gone"},
        {"errorType": "RESOURCE_NOT_FOUND"},
        fakes.non_json_error(),
    ],
)
def test_falls_back_to_second_path_on_not_found(first_answer) -> None:
    manager = fakes.FakeOAuthManager(first_answer, page([event(n=1)], "c1"), page([event(n=2)]))
    result = fetch(manager)

    assert [urlsplit(url).path for url in manager.urls] == [PRIMARY, FALLBACK, FALLBACK]
    assert result["endpoint"] == FALLBACK
    assert result["count"] == 2
    assert result["pages"] == 2
    assert result["api_calls"] == 3  # the failed probe counts as well


def test_both_paths_not_found() -> None:
    manager = fakes.FakeOAuthManager(NOT_FOUND, NOT_FOUND)
    with pytest.raises(ViCareExtrasError) as err:
        fetch(manager)
    assert err.value.translation_key == "event_history_not_found"
    assert PRIMARY in err.value.placeholders["endpoints"]
    assert FALLBACK in err.value.placeholders["endpoints"]
    assert len(manager.urls) == 2


def test_not_found_on_later_page_does_not_switch_path() -> None:
    manager = fakes.FakeOAuthManager(page([event()], "c1"), NOT_FOUND)
    with pytest.raises(ViCareExtrasError) as err:
        fetch(manager)
    assert err.value.translation_key == "api_error"
    assert len(manager.urls) == 2


def test_preferred_path_order_is_respected() -> None:
    manager = fakes.FakeOAuthManager(page([event()]))
    result = fetch(manager, paths=tuple(reversed(EVENT_HISTORY_PATHS)))
    assert result["endpoint"] == FALLBACK
    assert path_template(result["endpoint"], 2323232, EVENT_HISTORY_PATHS) == EVENT_HISTORY_PATHS[1]
    assert path_template(None, 2323232, EVENT_HISTORY_PATHS) is None


def test_rate_limit_is_not_retried_on_other_path() -> None:
    manager = fakes.FakeOAuthManager(fakes.PyViCareRateLimitError())
    with pytest.raises(ViCareExtrasError) as err:
        fetch(manager)
    assert err.value.translation_key == "rate_limited"
    assert err.value.placeholders == {"reset": "2026-11-13 00:00 UTC"}
    assert len(manager.urls) == 1


@pytest.mark.parametrize(
    ("answer", "key"),
    [
        ({"statusCode": 429, "errorType": "RATE_LIMIT_EXCEEDED"}, "rate_limited"),
        ({"statusCode": 403, "errorType": "FORBIDDEN", "message": "no"}, "event_history_forbidden"),
        ({"statusCode": 401, "error": "UNAUTHORIZED"}, "event_history_forbidden"),
        ({"statusCode": 400, "errorType": "VALIDATION", "message": "bad"}, "api_error"),
        ({"error": "invalid_request"}, "api_error"),
        ({"something": "else"}, "invalid_response"),
        (["not", "a", "dict"], "invalid_response"),
        ({"data": "not a list"}, "invalid_response"),
        (fakes.PyViCareInternalServerError("boom"), "server_error"),
        (RuntimeError("boom"), "unexpected_error"),
        (KeyError("extendedPayload"), "unexpected_error"),
    ],
)
def test_errors_are_mapped(answer, key) -> None:
    manager = fakes.FakeOAuthManager(answer)
    with pytest.raises(ViCareExtrasError) as err:
        fetch(manager)
    assert err.value.translation_key == key
    assert not err.value.validation
    assert len(manager.urls) == 1


def test_single_event_type_is_filtered_by_server_and_client() -> None:
    manager = fakes.FakeOAuthManager(page([event("device-error"), event("feature-changed")]))
    result = fetch(manager, event_types=["device-error"])
    assert query(manager.urls[0])["eventType"] == "device-error"
    assert [e["eventType"] for e in result["events"]] == ["device-error"]
    assert result["count"] == 1
    assert result["fetched_count"] == 2


def test_several_event_types_are_filtered_locally_only() -> None:
    manager = fakes.FakeOAuthManager(
        page([event("device-error"), event("feature-changed"), event("gateway-online")])
    )
    result = fetch(manager, event_types=["device-error", "gateway-online"])
    assert "eventType" not in query(manager.urls[0])
    assert [e["eventType"] for e in result["events"]] == ["device-error", "gateway-online"]


def test_gateway_serials_and_edited_by_are_passed_to_the_api() -> None:
    manager = fakes.FakeOAuthManager(page([]))
    fetch(manager, gateway_serials=["111", " 222 "], edited_by="user@example.com", last_n_days=7, limit=50)
    assert query(manager.urls[0]) == {
        "lastNDays": "7",
        "limit": "50",
        "gatewaySerials": "111,222",
        "editedBy": "user@example.com",
    }


def test_non_dict_events_are_dropped() -> None:
    manager = fakes.FakeOAuthManager({"data": [event(), "junk", None]})
    assert fetch(manager)["count"] == 1


def test_installation_id_is_url_quoted() -> None:
    manager = fakes.FakeOAuthManager(page([]))
    fetch_event_history(manager, "12/../3", last_n_days=1, limit=1, max_pages=1)
    assert urlsplit(manager.urls[0]).path == "/events-history/installations/12%2F..%2F3/events"
