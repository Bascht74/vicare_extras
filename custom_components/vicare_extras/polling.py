"""Optional: slow down the polling of the built-in vicare integration.

The built-in integration (core 2026.11.1) polls each gateway with one
``ViCareCoordinator`` whose ``update_interval`` is 60 s times the number of
gateways; every poll is one API call. With the option "poll interval of the
ViCare integration" this module raises that interval, which is the only way
this integration can save API calls.

How the built-in objects are reached (all guarded, see ``_targets``)::

    entry.runtime_data.devices[i].coordinator     ViCareCoordinator, one per
                                                  gateway, shared by its devices
    coordinator.update_interval                   datetime.timedelta
    entry.runtime_data.devices[i].config.service  PyViCare cached service
    service._cacheDuration                        seconds PyViCare trusts its cache

What is changed, and only while the option is set:

* ``coordinator.update_interval`` becomes the requested interval, never less
  than what the built-in integration computed itself. Home Assistant uses the
  new value when it schedules the next poll, i.e. after the poll that is
  already scheduled.
* ``service._cacheDuration`` becomes at least the interval plus a margin.
  Otherwise every PyViCare read between two polls (after the 60 s cache had
  expired) would fetch again and the saving would be lost.

The original values are remembered per object and put back when the option
is cleared or the integration is unloaded. After the vicare entry reloads it
has new objects with their original values; ``apply`` runs on every look of
the mirror coordinator and treats them like the first time.

If the structure differs (other core version) nothing is changed and one
warning is logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any
import weakref

from . import bridge
from .const import CACHE_MARGIN_SECONDS

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _Changed:
    """One object whose attribute was changed, with the value to put back."""

    ref: weakref.ReferenceType[Any]
    attribute: str
    original: Any
    applied: Any

    def restore(self) -> bool:
        """Put the original value back unless someone else changed it since."""
        target = self.ref()
        if target is None or getattr(target, self.attribute, None) != self.applied:
            return False
        setattr(target, self.attribute, self.original)
        return True


def _targets(hass: Any) -> list[tuple[Any, list[Any]]]:
    """Return (coordinator, [services]) of every loaded vicare entry.

    Raises AttributeError/TypeError when the structure is not the expected one.
    """
    found: dict[int, tuple[Any, list[Any]]] = {}
    for entry in bridge.loaded_vicare_entries(hass):
        for device in entry.runtime_data.devices:
            coordinator = device.coordinator
            if coordinator is None:
                continue
            if not isinstance(coordinator.update_interval, timedelta):
                raise TypeError("coordinator.update_interval is not a timedelta")
            _, services = found.setdefault(id(coordinator), (coordinator, []))
            service = device.config.service
            if all(service is not known for known in services):
                services.append(service)
    return list(found.values())


def builtin_interval_seconds(hass: Any) -> float | None:
    """Return the shortest poll interval of the built-in coordinators."""
    try:
        intervals = [
            coordinator.update_interval.total_seconds()
            for coordinator, _ in _targets(hass)
        ]
    except (AttributeError, TypeError):
        return None
    return min(intervals) if intervals else None


class PollIntervalManager:
    """Apply and restore the poll interval of the built-in integration."""

    def __init__(self, seconds: int | None) -> None:
        """Initialize; ``seconds`` None means "leave the built-in alone"."""
        self.seconds = seconds
        self._changed: list[_Changed] = []
        self._warned = False

    def _already_changed(self, target: Any, attribute: str) -> bool:
        return any(
            change.ref() is target and change.attribute == attribute
            for change in self._changed
        )

    def apply(self, hass: Any) -> None:
        """Set the interval on every built-in coordinator not yet handled."""
        if self.seconds is None:
            return
        self._changed = [change for change in self._changed if change.ref() is not None]
        try:
            targets = _targets(hass)
            for coordinator, services in targets:
                if self._already_changed(coordinator, "update_interval"):
                    continue
                original: timedelta = coordinator.update_interval
                seconds = max(float(self.seconds), original.total_seconds())
                if seconds == original.total_seconds():
                    continue
                applied = timedelta(seconds=seconds)
                # Check the services before changing anything.
                durations = [(service, service._cacheDuration) for service in services]  # noqa: SLF001
                if any(
                    isinstance(duration, bool) or not isinstance(duration, (int, float))
                    for _, duration in durations
                ):
                    raise TypeError("service._cacheDuration is not a number")

                coordinator.update_interval = applied
                self._changed.append(
                    _Changed(weakref.ref(coordinator), "update_interval", original, applied)
                )
                for service, duration in durations:
                    wanted = int(seconds) + CACHE_MARGIN_SECONDS
                    if duration >= wanted or self._already_changed(service, "_cacheDuration"):
                        continue
                    service._cacheDuration = wanted  # noqa: SLF001
                    self._changed.append(
                        _Changed(weakref.ref(service), "_cacheDuration", duration, wanted)
                    )
                _LOGGER.info(
                    "Poll interval of the ViCare integration set to %d s (was %d s)",
                    seconds,
                    original.total_seconds(),
                )
        except (AttributeError, TypeError) as err:
            if not self._warned:
                self._warned = True
                _LOGGER.warning(
                    "The poll interval of the ViCare integration cannot be changed, "
                    "its internal structure is not the expected one (%s)",
                    err,
                )

    def restore(self) -> None:
        """Put back every value this manager changed."""
        for change in self._changed:
            if change.restore() and change.attribute == "update_interval":
                _LOGGER.info(
                    "Poll interval of the ViCare integration restored to %d s",
                    change.original.total_seconds(),
                )
        self._changed = []
