"""Base entity and discovery shared by the sensor and binary sensor platforms."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import specs
from .bridge import DeviceRef
from .const import (
    DEVICE_TYPE_HEATING,
    DEVICE_TYPE_ROOM_CONTROL,
    DEVICE_TYPE_ZIGBEE,
    DOMAIN,
    VICARE_DOMAIN,
)
from .coordinator import DeviceSnapshot, ViCareExtrasCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Target:
    """Where an entity lives: a vicare device or one room of a room control."""

    device: DeviceRef
    room: int | None = None
    room_name: str | None = None

    @property
    def unique_prefix(self) -> str:
        """Return the first part of the unique ids of this target."""
        if self.room is None:
            return self.device.ref_id
        return f"{self.device.ref_id}_room_{self.room}"


def find_vicare_device(hass: HomeAssistant, device: DeviceRef) -> Any | None:
    """Return the device registry entry of the built-in integration, if any.

    Since Home Assistant 2026 a device belongs to exactly one config entry, so
    entities are not linked through ``device_info`` (that would create a
    second device). Instead the existing device entry is attached to the
    entity. If it cannot be found the entity is created without a device.
    """
    if device.identifier is None or device.entry_id is None:
        return None
    try:
        return dr.async_get(hass).async_get_device_by_identifier(
            (VICARE_DOMAIN, device.identifier), device.entry_id
        )
    except Exception:  # noqa: BLE001 - never fail entity setup over the link
        _LOGGER.debug("Could not look up the ViCare device", exc_info=True)
        return None


def find_gateway_heating_device(
    coordinator: ViCareExtrasCoordinator, device: DeviceRef
) -> Any | None:
    """Return the built-in integration's device of the heat generator.

    The first heating device on the same gateway that the built-in integration
    has set up. Room devices name it as their "via device", so a room shows up
    as a connected device of the heat pump. None when there is no such device.
    """
    for snapshot in (coordinator.data or {}).values():
        other = snapshot.device
        if (
            other.device_type == DEVICE_TYPE_HEATING
            and other.identifier is not None
            and other.gateway_serial == device.gateway_serial
            and other.installation_id == device.installation_id
            and (entry := find_vicare_device(coordinator.hass, other)) is not None
        ):
            return entry
    return None


def default_room_name(hass: HomeAssistant, room: int) -> str:
    """Return the name of a room the API gives no name for.

    "Raum N" when Home Assistant's language is German, otherwise "Room N".
    """
    language = str(getattr(hass.config, "language", "") or "").lower()
    return f"Raum {room}" if language.startswith("de") else f"Room {room}"


def iter_targets(
    snapshot: DeviceSnapshot,
) -> Iterator[tuple[str, Target, dict[str, dict[str, Any]]]]:
    """Yield (scope, target, features) for a device snapshot."""
    device = snapshot.device
    if device.device_type == DEVICE_TYPE_HEATING:
        yield specs.SCOPE_HEATING, Target(device), snapshot.features
    elif device.device_type == DEVICE_TYPE_ROOM_CONTROL:
        for room in specs.room_indexes(snapshot.features):
            yield (
                specs.SCOPE_ROOM,
                Target(device, room, specs.room_name(snapshot.features, room)),
                snapshot.features,
            )
    elif device.device_type == DEVICE_TYPE_ZIGBEE:
        # Radiator thermostats; the climate platform decides by the features.
        yield specs.SCOPE_TRV, Target(device), snapshot.features


@callback
def async_setup_discovery(
    coordinator: ViCareExtrasCoordinator,
    create: Callable[[str, Target, dict[str, dict[str, Any]], set[str]], list[Any]],
    async_add_entities: Callable[[list[Any]], None],
) -> Callable[[], None]:
    """Create entities now and whenever new features show up.

    ``create`` gets the scope, the target, the features and the set of unique
    ids that already exist; it returns the new entities and adds their unique
    ids to the set. Returns the function that stops the discovery.
    """
    known: set[str] = set()

    @callback
    def _async_discover() -> None:
        new_entities: list[Any] = []
        for snapshot in (coordinator.data or {}).values():
            for scope, target, features in iter_targets(snapshot):
                new_entities.extend(create(scope, target, features, known))
        if new_entities:
            async_add_entities(new_entities)

    _async_discover()
    return coordinator.async_add_listener(_async_discover)


class ViCareExtrasEntity(CoordinatorEntity[ViCareExtrasCoordinator]):
    """Base class: reads mirrored features, never talks to the API."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ViCareExtrasCoordinator,
        target: Target,
        key: str,
        unique_suffix: str | None = None,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        """Initialize the entity and link it to its device."""
        super().__init__(coordinator)
        self._ref_id = target.device.ref_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{target.unique_prefix}-{unique_suffix or key}"
        if placeholders:
            self._attr_translation_placeholders = placeholders
        if target.room is None:
            # Attach to the device of the built-in integration (no device_info).
            self.device_entry = find_vicare_device(coordinator.hass, target.device)
        else:
            # The built-in integration has no device for rooms: one device per
            # room, owned by this integration. A device cannot belong to the
            # built-in integration's entry, so the room is linked to the heat
            # generator of its gateway as "via device" instead. Home Assistant
            # applies name and link to an existing device on every start; a
            # name the user set (name_by_user) is kept.
            info: dict[str, Any] = {
                "identifiers": {(DOMAIN, target.unique_prefix)},
                "name": target.room_name
                or default_room_name(coordinator.hass, target.room),
                "manufacturer": "Viessmann",
                "model": "ViCare room",
            }
            via = find_gateway_heating_device(coordinator, target.device)
            if via is not None and getattr(via, "id", None):
                info["via_device_id"] = via.id
            self._attr_device_info = DeviceInfo(**info)

    @property
    def _features(self) -> dict[str, dict[str, Any]]:
        """Return the mirrored features of this entity's device."""
        snapshot = (self.coordinator.data or {}).get(self._ref_id)
        return snapshot.features if snapshot is not None else {}

    def _has_data(self) -> bool:
        """Return True while the data this entity needs is present."""
        raise NotImplementedError

    @property
    def available(self) -> bool:
        """Return True while the mirrored data contains this entity's source."""
        return super().available and self._has_data()


class ViCareExtrasValueEntity(ViCareExtrasEntity):
    """An entity described by a ``ValueSpec``."""

    def __init__(
        self,
        coordinator: ViCareExtrasCoordinator,
        target: Target,
        spec: specs.ValueSpec,
        index: int | None,
    ) -> None:
        """Initialize the entity."""
        self._spec = spec
        self._index = target.room if spec.scope == specs.SCOPE_ROOM else index
        super().__init__(
            coordinator,
            target,
            spec.key,
            specs.unique_suffix(spec, index),
            None
            if spec.scope == specs.SCOPE_ROOM
            else specs.name_placeholders(spec, index),
        )
        self._attr_entity_registry_enabled_default = spec.enabled

    def _has_data(self) -> bool:
        return specs.find_source(self._spec, self._features, self._index) is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the extra attributes named in the spec."""
        if not self._spec.attributes:
            return None
        return specs.read_attributes(self._spec, self._features, self._index)


def create_value_entities(
    platform: str,
    entity_class: Callable[..., Any],
    coordinator: ViCareExtrasCoordinator,
    scope: str,
    target: Target,
    features: dict[str, dict[str, Any]],
    known: set[str],
) -> list[Any]:
    """Create the not yet existing ``ValueSpec`` entities of a platform."""
    entities: list[Any] = []
    for spec in specs.ALL_SPECS:
        if spec.platform != platform or spec.scope != scope:
            continue
        if scope == specs.SCOPE_ROOM:
            indexes: list[int | None] = (
                [target.room]
                if specs.find_source(spec, features, target.room) is not None
                else []
            )
        else:
            indexes = specs.find_indexes(spec, features)
        for index in indexes:
            unique_id = f"{target.unique_prefix}-{specs.unique_suffix(spec, index)}"
            if unique_id in known:
                continue
            known.add(unique_id)
            entities.append(entity_class(coordinator, target, spec, index))
    return entities
