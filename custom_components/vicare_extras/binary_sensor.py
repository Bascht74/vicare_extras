"""Binary sensors of the ViCare Extras integration.

All values come from ``ViCareExtrasCoordinator``, which only mirrors what the
built-in vicare integration has already fetched. No entity causes an API call.
The entities are listed in ``specs.py``.
"""

from __future__ import annotations

from functools import partial

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import specs
from .coordinator import ViCareExtrasConfigEntry, ViCareExtrasCoordinator
from .entity import (
    Target,
    ViCareExtrasValueEntity,
    async_setup_discovery,
    create_value_entities,
)

# Entities only read coordinator data, nothing to throttle.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ViCareExtrasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create binary sensors for every feature that exists, now or later."""
    coordinator = entry.runtime_data
    create = partial(
        create_value_entities,
        specs.PLATFORM_BINARY_SENSOR,
        ViCareExtrasBinarySensor,
        coordinator,
    )
    entry.async_on_unload(async_setup_discovery(coordinator, create, async_add_entities))


class ViCareExtrasBinarySensor(ViCareExtrasValueEntity, BinarySensorEntity):
    """A boolean property of a ViCare feature."""

    def __init__(
        self,
        coordinator: ViCareExtrasCoordinator,
        target: Target,
        spec: specs.ValueSpec,
        index: int | None,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, target, spec, index)
        if spec.device_class is not None:
            self._attr_device_class = BinarySensorDeviceClass(spec.device_class)
        if spec.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        """Return the state of the property."""
        return specs.read_value(self._spec, self._features, self._index)
