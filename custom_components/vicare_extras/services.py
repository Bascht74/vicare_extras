"""Actions of the ViCare Extras integration.

``get_features`` and ``get_event_history`` are response-only and read-only.
``send_command`` is an expert action for administrators that posts one
command as given. All are registered once in ``async_setup`` and look up the
loaded ``vicare`` config entry at call time.

API usage
---------
``get_features``       0 API calls. Reads the payload PyViCare has in memory.
``get_event_history``  1 API call per page fetched (at most ``max_pages``),
                       plus 1 call when the first path answers "not found"
                       and the fallback path is tried.
``send_command``       exactly 1 API call (one POST), whatever the answer.
"""

from __future__ import annotations

import asyncio
import copy
from functools import partial
import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.service import async_register_admin_service

from . import bridge, commands
from .const import (
    ATTR_COMMAND,
    ATTR_CURSOR,
    ATTR_DEVICE_ID,
    ATTR_DEVICE_TYPE,
    ATTR_EDITED_BY,
    ATTR_EVENT_TYPE,
    ATTR_FEATURE,
    ATTR_FULL,
    ATTR_GATEWAY_SERIAL,
    ATTR_GATEWAY_SERIALS,
    ATTR_INSTALLATION_ID,
    ATTR_LAST_N_DAYS,
    ATTR_LIMIT,
    ATTR_MAX_PAGES,
    ATTR_PARAMS,
    ATTR_PREFIX,
    ATTR_VICARE_DEVICE_ID,
    CACHE_WAIT_ATTEMPTS,
    CACHE_WAIT_SECONDS,
    DATA_EVENT_HISTORY_PATH,
    DEFAULT_LAST_N_DAYS,
    DEFAULT_LIMIT,
    DEFAULT_MAX_PAGES,
    DEVICE_TYPE_HEATING,
    DOMAIN,
    EVENT_HISTORY_PATHS,
    MAX_LAST_N_DAYS,
    MAX_LIMIT,
    MAX_MAX_PAGES,
    SERVICE_GET_EVENT_HISTORY,
    SERVICE_GET_FEATURES,
    SERVICE_SEND_COMMAND,
    VICARE_DOMAIN,
)
from .errors import ViCareExtrasError
from .event_history import fetch_event_history, path_template
from .features import slim_feature
from .messages import decode_event

_LOGGER = logging.getLogger(__name__)


def _string_list(value: Any) -> list[str]:
    """Accept a string (comma separated) or a list of strings."""
    if isinstance(value, str):
        items: list[Any] = value.split(",")
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise vol.Invalid("expected a string or a list of strings")
    return [str(item).strip() for item in items if str(item).strip()]


def _id_string(value: Any) -> str:
    """Accept an id given as number or string."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise vol.Invalid("expected a number or a string")
    if not (text := str(value).strip()):
        raise vol.Invalid("must not be empty")
    return text


# Feature and command names end up in the URL of the request.
_FEATURE_NAME = re.compile(r"[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*")
_COMMAND_NAME = re.compile(r"[A-Za-z0-9_-]+")


def _name(pattern: re.Pattern[str]) -> Any:
    def validate(value: Any) -> str:
        if not isinstance(value, str) or not pattern.fullmatch(text := value.strip()):
            raise vol.Invalid("not a valid name")
        return text

    return validate


GET_EVENT_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_LAST_N_DAYS, default=DEFAULT_LAST_N_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_LAST_N_DAYS)
        ),
        vol.Optional(ATTR_LIMIT, default=DEFAULT_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_LIMIT)
        ),
        vol.Optional(ATTR_MAX_PAGES, default=DEFAULT_MAX_PAGES): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_MAX_PAGES)
        ),
        vol.Optional(ATTR_INSTALLATION_ID): _id_string,
        vol.Optional(ATTR_EVENT_TYPE): _string_list,
        vol.Optional(ATTR_GATEWAY_SERIALS): _string_list,
        vol.Optional(ATTR_EDITED_BY): cv.string,
        vol.Optional(ATTR_CURSOR): cv.string,
    }
)

GET_FEATURES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): _string_list,
        vol.Optional(ATTR_VICARE_DEVICE_ID): _id_string,
        vol.Optional(ATTR_DEVICE_TYPE): cv.string,
        vol.Optional(ATTR_PREFIX): cv.string,
        vol.Optional(ATTR_FULL, default=False): cv.boolean,
    }
)


SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_VICARE_DEVICE_ID): _id_string,
        vol.Required(ATTR_FEATURE): _name(_FEATURE_NAME),
        vol.Required(ATTR_COMMAND): _name(_COMMAND_NAME),
        # No schema default: the handler treats a missing value as {}.
        vol.Optional(ATTR_PARAMS): dict,
        # Only needed when several gateways have a device with the same id.
        vol.Optional(ATTR_GATEWAY_SERIAL): _id_string,
    }
)


def _ha_error(err: ViCareExtrasError) -> HomeAssistantError:
    """Convert an internal error into a translated Home Assistant error."""
    error_class = ServiceValidationError if err.validation else HomeAssistantError
    return error_class(
        translation_domain=DOMAIN,
        translation_key=err.translation_key,
        translation_placeholders=err.placeholders,
    )


def _unexpected(err: Exception) -> HomeAssistantError:
    """Convert an unexpected exception without leaking more than its text."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="unexpected_error",
        translation_placeholders={"error": f"{type(err).__name__}: {str(err)[:300]}"},
    )


# --------------------------------------------------------------------------
# get_event_history
# --------------------------------------------------------------------------


def _resolve_installation(
    hass: HomeAssistant, requested: str | None
) -> tuple[Any, str, list[str]]:
    """Return (runtime_data, installation id, gateway serials)."""
    installations: dict[str, tuple[Any, list[str]]] = {}
    for entry in bridge.require_vicare_entries(hass):
        runtime_data = bridge.get_runtime_data(entry)
        for ref in bridge.collect_devices(entry):
            _, serials = installations.setdefault(
                ref.installation_id, (runtime_data, [])
            )
            if ref.gateway_serial not in serials:
                serials.append(ref.gateway_serial)

    if not installations:
        raise ViCareExtrasError("no_installation")
    if requested is None:
        installation_id = next(iter(installations))
    elif requested in installations:
        installation_id = requested
    else:
        raise ViCareExtrasError(
            "installation_not_found",
            {"installation_id": requested, "known": ", ".join(installations)},
            validation=True,
        )
    runtime_data, serials = installations[installation_id]
    return runtime_data, installation_id, serials


async def _async_get_event_history(call: ServiceCall) -> ServiceResponse:
    """Fetch the event history of an installation (causes API calls)."""
    hass = call.hass
    data = call.data
    store: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    preferred = store.get(DATA_EVENT_HISTORY_PATH)
    # Stable sort: the path that worked last time goes first.
    paths = sorted(EVENT_HISTORY_PATHS, key=lambda path: path != preferred)

    try:
        runtime_data, installation_id, known_serials = _resolve_installation(
            hass, data.get(ATTR_INSTALLATION_ID)
        )
        oauth_manager = bridge.get_oauth_manager(runtime_data)
        # PyViCare uses requests and may renew the token through the event
        # loop, so this must run in the executor.
        result = await hass.async_add_executor_job(
            partial(
                fetch_event_history,
                oauth_manager,
                installation_id,
                last_n_days=data[ATTR_LAST_N_DAYS],
                limit=data[ATTR_LIMIT],
                max_pages=data[ATTR_MAX_PAGES],
                event_types=data.get(ATTR_EVENT_TYPE),
                gateway_serials=data.get(ATTR_GATEWAY_SERIALS),
                edited_by=data.get(ATTR_EDITED_BY),
                cursor=data.get(ATTR_CURSOR),
                paths=paths,
            )
        )
    except ViCareExtrasError as err:
        raise _ha_error(err) from err
    except Exception as err:  # noqa: BLE001 - surface as readable action error
        _LOGGER.debug("Unexpected error fetching the event history", exc_info=True)
        raise _unexpected(err) from err

    if (used := path_template(result["endpoint"], installation_id, paths)) is not None:
        store[DATA_EVENT_HISTORY_PATH] = used
    # Add "decoded"/"summary" to the events; the raw fields stay untouched.
    language = getattr(hass.config, "language", "de") or "de"
    result["events"] = [decode_event(event, language) for event in result["events"]]
    result["known_gateway_serials"] = known_serials
    _LOGGER.debug(
        "Event history: %s events, %s page(s), %s API call(s)",
        result["count"],
        result["pages"],
        result["api_calls"],
    )
    return result


# --------------------------------------------------------------------------
# get_features
# --------------------------------------------------------------------------


def _select_devices(hass: HomeAssistant, data: Any) -> list[bridge.DeviceRef]:
    """Return the devices matching the selection of a get_features call."""
    refs = bridge.collect_all_devices(hass)
    selected = False

    if device_ids := data.get(ATTR_DEVICE_ID):
        selected = True
        registry = dr.async_get(hass)
        identifiers: set[str] = set()
        for device_id in device_ids:
            if (device := registry.async_get(device_id)) is None:
                raise ViCareExtrasError("device_not_found", validation=True)
            identifiers.update(
                identifier[1]
                for identifier in device.identifiers
                if identifier[0] == VICARE_DOMAIN
            )
        refs = [ref for ref in refs if ref.identifier in identifiers]

    if (vicare_device_id := data.get(ATTR_VICARE_DEVICE_ID)) is not None:
        selected = True
        refs = [ref for ref in refs if ref.device_id == vicare_device_id]

    if device_type := data.get(ATTR_DEVICE_TYPE):
        selected = True
        wanted = device_type.strip().lower()
        refs = [ref for ref in refs if str(ref.device_type).lower() == wanted]

    if not selected:
        # Default: the heating device(s); every device if there is none.
        heating = [ref for ref in refs if ref.device_type == DEVICE_TYPE_HEATING]
        refs = heating or refs

    if not refs:
        raise ViCareExtrasError("device_not_found", validation=True)
    return refs


async def _async_wait_for_payload(ref: bridge.DeviceRef) -> dict[str, Any]:
    """Return the cached payload, waiting briefly while vicare refreshes."""
    for attempt in range(CACHE_WAIT_ATTEMPTS):
        if (payload := bridge.peek_payload(ref.service)) is not None:
            return payload
        if attempt + 1 < CACHE_WAIT_ATTEMPTS:
            await asyncio.sleep(CACHE_WAIT_SECONDS)
    raise ViCareExtrasError("no_cached_data", {"device": ref.label})


async def _async_get_features(call: ServiceCall) -> ServiceResponse:
    """Return raw feature objects from the cache (never causes an API call)."""
    hass = call.hass
    data = call.data
    prefix: str = (data.get(ATTR_PREFIX) or "").strip()
    full: bool = data.get(ATTR_FULL, False)

    try:
        devices: list[dict[str, Any]] = []
        for ref in _select_devices(hass, data):
            payload = await _async_wait_for_payload(ref)
            selected = sorted(
                (
                    feature
                    for feature in bridge.device_features(payload, ref.device_id)
                    if feature["feature"].startswith(prefix)
                ),
                key=lambda feature: feature["feature"],
            )
            devices.append(
                {
                    "device_id": ref.device_id,
                    "device_type": ref.device_type,
                    "model": ref.model,
                    "installation_id": ref.installation_id,
                    "gateway_serial": ref.gateway_serial,
                    "cache_age_seconds": bridge.cache_age_seconds(ref.service),
                    "count": len(selected),
                    "features": [slim_feature(item, full=full) for item in selected],
                }
            )
    except ViCareExtrasError as err:
        raise _ha_error(err) from err

    response = {
        "source": "cache",
        "api_calls": 0,
        "count": sum(device["count"] for device in devices),
        "devices": devices,
    }
    # Hand out a private copy so nothing can alter PyViCare's cached payload.
    return await hass.async_add_executor_job(copy.deepcopy, response)


# --------------------------------------------------------------------------
# send_command
# --------------------------------------------------------------------------


def _command_target(hass: HomeAssistant, data: Any) -> bridge.DeviceRef:
    """Return the one device a send_command call names."""
    refs = [
        ref
        for ref in bridge.collect_all_devices(hass)
        if ref.device_id == data[ATTR_VICARE_DEVICE_ID]
    ]
    if serial := data.get(ATTR_GATEWAY_SERIAL):
        refs = [ref for ref in refs if ref.gateway_serial == serial]
    if not refs:
        raise ViCareExtrasError("device_not_found", validation=True)
    if len(refs) > 1:
        raise ViCareExtrasError(
            "device_ambiguous",
            {"gateways": ", ".join(sorted({ref.gateway_serial for ref in refs}))},
            validation=True,
        )
    return refs[0]


def _cached_feature(ref: bridge.DeviceRef, name: str) -> dict[str, Any] | None:
    """Return the cached feature object, if there is one (no API call)."""
    try:
        payload = bridge.peek_payload(ref.service)
    except ViCareExtrasError:
        return None
    if payload is None:
        return None
    for feature in bridge.device_features(payload, ref.device_id):
        if feature.get("feature") == name:
            return feature
    return None


async def _async_send_command(call: ServiceCall) -> ServiceResponse:
    """Post one command as given (expert action, exactly one API call).

    Not limited to commands the feature advertises: the point is to see what
    the API answers. Rejections by the API are returned, not raised.
    """
    hass = call.hass
    data = call.data
    feature: str = data[ATTR_FEATURE]
    command: str = data[ATTR_COMMAND]
    try:
        ref = _command_target(hass, data)
        is_advertised, executable = commands.advertised(
            _cached_feature(ref, feature), command
        )
        # PyViCare uses requests: executor. The plain ViCareService.setProperty
        # is used, so the cache of the built-in integration is not emptied.
        result = await hass.async_add_executor_job(
            commands.send,
            ref.service,
            ref.accessor,
            feature,
            command,
            dict(data.get(ATTR_PARAMS) or {}),
        )
    except ViCareExtrasError as err:
        raise _ha_error(err) from err

    _LOGGER.debug(
        "send_command %s on %s (device %s): success=%s",
        command,
        feature,
        ref.device_id,
        result["success"],
    )
    if not call.return_response:
        return None
    return {
        "sent": True,
        "advertised": is_advertised,
        "executable": executable,
        "api_calls": 1,
        "success": result["success"],
        "response": await hass.async_add_executor_job(
            copy.deepcopy, result["response"]
        ),
    }


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_EVENT_HISTORY,
        _async_get_event_history,
        schema=GET_EVENT_HISTORY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_FEATURES,
        _async_get_features,
        schema=GET_FEATURES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    # Writes to the heating system: administrators only.
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_SEND_COMMAND,
        _async_send_command,
        schema=SEND_COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
