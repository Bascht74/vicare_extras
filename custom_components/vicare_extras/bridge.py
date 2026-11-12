"""Read-only bridge to the internals of the built-in ``vicare`` integration.

Everything that depends on internals of Home Assistant's ``vicare`` integration
or of PyViCare lives in this module, so there is exactly one place to adapt if
those internals change. Verified against Home Assistant core 2026.11.1 and
PyViCare 2.63.0:

* ``entry.runtime_data`` is a ``ViCareData(client, devices)``.
* ``client`` is a ``PyViCare`` instance; ``client.oauth_manager`` is the
  authenticated OAuth manager, ``client.all_devices`` lists every device as a
  ``PyViCareDeviceConfig``.
* ``devices`` is a list of ``ViCareDevice(config, api, serial, coordinator)``;
  only these devices have a device registry entry.
* ``config.service`` is a ``ViCareCachedServiceViaGateway`` shared by all
  devices of a gateway. Its ``_cache`` attribute holds the last payload of the
  bulk feature request (``{"data": [feature, ...]}``) or ``None``.

Nothing in here calls a PyViCare method that can perform a request: the cache
is only looked at (``_cache`` is read, never refreshed), so using this module
costs zero API calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any

from .const import VICARE_DOMAIN
from .errors import ViCareExtrasError

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeviceRef:
    """A ViCare device as known to the built-in integration."""

    entry_id: str | None
    installation_id: str
    gateway_serial: str
    device_id: str
    device_type: str | None
    model: str | None
    serial: str | None
    # Identifier of the device registry entry created by the built-in
    # integration, None for devices the built-in integration does not set up.
    identifier: str | None
    service: Any = field(compare=False, repr=False)

    @property
    def key(self) -> tuple[str, str, str]:
        """Return a key that is unique across installations."""
        return (self.installation_id, self.gateway_serial, self.device_id)

    @property
    def label(self) -> str:
        """Return a short human readable label."""
        return f"{self.model or 'unknown'} (id {self.device_id})"


def loaded_vicare_entries(hass: Any) -> list[Any]:
    """Return the loaded config entries of the built-in integration."""
    manager = hass.config_entries
    try:
        return list(manager.async_loaded_entries(VICARE_DOMAIN))
    except AttributeError:
        # Home Assistant versions without async_loaded_entries.
        return [
            entry
            for entry in manager.async_entries(VICARE_DOMAIN)
            if getattr(entry.state, "value", entry.state) == "loaded"
        ]


def require_vicare_entries(hass: Any) -> list[Any]:
    """Return the loaded entries or raise a translated error."""
    if not (entries := loaded_vicare_entries(hass)):
        raise ViCareExtrasError("vicare_not_loaded")
    return entries


def get_runtime_data(entry: Any) -> Any:
    """Return the runtime data of a loaded vicare entry."""
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        raise ViCareExtrasError(
            "vicare_incompatible", {"detail": "config entry has no runtime_data"}
        )
    return runtime_data


def get_oauth_manager(runtime_data: Any) -> Any:
    """Return the authenticated PyViCare OAuth manager."""
    client = getattr(runtime_data, "client", None)
    oauth_manager = getattr(client, "oauth_manager", None)
    if oauth_manager is None or not callable(getattr(oauth_manager, "get", None)):
        raise ViCareExtrasError(
            "vicare_incompatible",
            {"detail": "runtime_data.client.oauth_manager.get is missing"},
        )
    return oauth_manager


def _vicare_identifier(gateway_serial: str, serial: str | None, device_id: str) -> str:
    """Build the device identifier exactly like the built-in ViCareEntity."""
    if serial is not None:
        return f"{gateway_serial}_{serial.replace('-', '_')}"
    return f"{gateway_serial}_{device_id}"


def _device_ref(
    config: Any,
    *,
    entry_id: str | None,
    api: Any = None,
    serial: str | None = None,
    registered: bool,
) -> DeviceRef:
    """Build a DeviceRef from a PyViCareDeviceConfig."""
    accessor = config.getConfig()
    gateway_serial = str(accessor.serial)
    device_id = str(accessor.device_id)
    service = getattr(config, "service", None)
    if service is None:
        service = getattr(api, "service", None)
    if serial is not None and not isinstance(serial, str):
        serial = None
    return DeviceRef(
        entry_id=entry_id,
        installation_id=str(accessor.id),
        gateway_serial=gateway_serial,
        device_id=device_id,
        device_type=getattr(config, "device_type", None),
        model=getattr(config, "device_model", None),
        serial=serial,
        identifier=(
            _vicare_identifier(gateway_serial, serial, device_id)
            if registered
            else None
        ),
        service=service,
    )


def collect_devices(entry: Any) -> list[DeviceRef]:
    """Return all devices of a loaded vicare entry.

    Devices set up by the built-in integration come first (they carry the
    device registry identifier), followed by the remaining devices of the
    account such as the gateway or the virtual room control.
    """
    runtime_data = get_runtime_data(entry)
    entry_id = getattr(entry, "entry_id", None)
    refs: dict[tuple[str, str, str], DeviceRef] = {}
    problems: list[str] = []

    try:
        registered = list(runtime_data.devices)
    except (AttributeError, TypeError) as err:
        raise ViCareExtrasError(
            "vicare_incompatible", {"detail": f"runtime_data.devices: {err}"}
        ) from err

    for device in registered:
        try:
            ref = _device_ref(
                device.config,
                entry_id=entry_id,
                api=getattr(device, "api", None),
                serial=getattr(device, "serial", None),
                registered=True,
            )
        except (AttributeError, TypeError) as err:
            problems.append(str(err))
            continue
        refs.setdefault(ref.key, ref)

    client = getattr(runtime_data, "client", None)
    try:
        all_configs = list(getattr(client, "all_devices", None) or [])
    except TypeError:
        all_configs = []
    for config in all_configs:
        try:
            ref = _device_ref(config, entry_id=entry_id, registered=False)
        except (AttributeError, TypeError) as err:
            problems.append(str(err))
            continue
        refs.setdefault(ref.key, ref)

    if problems:
        _LOGGER.debug("Skipped ViCare devices with unexpected structure: %s", problems)
    if not refs and problems:
        raise ViCareExtrasError("vicare_incompatible", {"detail": problems[0]})
    return list(refs.values())


def collect_all_devices(hass: Any) -> list[DeviceRef]:
    """Return the devices of all loaded vicare entries."""
    refs: list[DeviceRef] = []
    for entry in require_vicare_entries(hass):
        refs.extend(collect_devices(entry))
    return refs


def peek_payload(service: Any) -> dict[str, Any] | None:
    """Return the payload PyViCare has cached, without triggering a request.

    Returns None when nothing is cached at the moment (the built-in
    integration empties the cache right before each refresh).

    This reads the private attribute ``_cache`` of PyViCare's cached service on
    purpose: every public accessor (``getProperty``, ``fetch_all_features``)
    performs an API request when the cache is empty or expired, and this
    integration must never cause one.
    """
    if service is None or not hasattr(service, "_cache"):
        raise ViCareExtrasError("cache_unsupported")
    payload = service._cache  # noqa: SLF001
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload
    return None


def cache_age_seconds(service: Any) -> float | None:
    """Return the age of the cached payload in seconds, if it can be told."""
    cache_time = getattr(service, "_cacheTime", None)
    if not isinstance(cache_time, datetime):
        return None
    try:
        # PyViCare stores a naive local timestamp (ViCareTimer().now()).
        now = datetime.now(cache_time.tzinfo)
        return max(0.0, round((now - cache_time).total_seconds(), 1))
    except (TypeError, ValueError, OverflowError):
        return None


def device_features(payload: dict[str, Any], device_id: str) -> list[dict[str, Any]]:
    """Return the features of one device from a (gateway wide) payload.

    Mirrors PyViCare's ``filter_features_for_device``: a feature belongs to a
    device when its URI contains ``/devices/<id>/``. The ``deviceId`` field is
    accepted as well.
    """
    segment = f"/devices/{device_id}/"
    result: list[dict[str, Any]] = []
    for feature in payload.get("data", []):
        if not isinstance(feature, dict) or not isinstance(feature.get("feature"), str):
            continue
        uri = feature.get("uri")
        if (isinstance(uri, str) and segment in uri) or (
            str(feature.get("deviceId")) == device_id
        ):
            result.append(feature)
    return result
