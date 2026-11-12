"""Which thermostat belongs to which room, and what follows from it.

Home Assistant side of ``room_mapping.py``. On every look of the coordinator:

1. The learner is fed with the setpoints of the rooms and thermostats of each
   gateway. If the API lists the thermostats of a room (``rooms.<n>.actors``,
   not in the basic API plan), that list wins over what was learned.
2. A thermostat with a known room gets the room device as "via device", so it
   shows up as a connected device of its room. A link somebody else set is
   left alone, and the link is removed again when the room is no longer known.
3. A room the API gives no name for is named after the Home Assistant area
   its thermostats are in (or, when several rooms share that area, after its
   only thermostat if the user named it). Only the default name "Raum N" /
   "Room N" is replaced; a name the user gave the room device always stays.
   A room device without area gets the area of its thermostats once.

What was learned is stored in ``.storage`` and survives restarts. Nothing in
here talks to the Viessmann API.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.storage import Store

from . import specs, thermostats
from .bridge import DeviceRef
from .const import (
    DEVICE_TYPE_ROOM_CONTROL,
    DEVICE_TYPE_ZIGBEE,
    DOMAIN,
    VICARE_DOMAIN,
)
from .room_mapping import RoomLearner, room_setpoints

if TYPE_CHECKING:
    from .coordinator import DeviceSnapshot

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SAVE_DELAY_SECONDS = 10

SOURCE_API = "api"
SOURCE_LEARNED = "learned"


def storage_key(entry_id: str) -> str:
    """Return the key of the ``.storage`` file of a config entry."""
    return f"{DOMAIN}.{entry_id}.rooms"


def room_id(control: DeviceRef, room: int) -> str:
    """Return the id of a room: the identifier of its device, too."""
    return f"{control.ref_id}_room_{room}"


@dataclass(frozen=True, slots=True)
class RoomRef:
    """A room as seen by a thermostat."""

    room_id: str
    index: int
    api_name: str | None
    # How the room was found: listed by the API or learned (None: candidate).
    source: str | None = None


def _group(device: DeviceRef) -> tuple[str, str]:
    return (device.installation_id, device.gateway_serial)


class RoomLinkManager:
    """Keep track of the rooms of the thermostats."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize; ``async_load`` reads what was learned earlier."""
        self._hass = hass
        self._entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self.learner = RoomLearner()
        # Stored: via links this integration set (thermostat → room device),
        # names it gave rooms, rooms it gave an area.
        self._links: dict[str, str] = {}
        self._names: dict[str, str] = {}
        self._areas: set[str] = set()
        # From the last look.
        self._rooms: dict[str, RoomRef] = {}
        self._trvs: dict[str, DeviceRef] = {}
        self._api_rooms: dict[tuple[tuple[str, str], str], str] = {}
        self._room_thermostats: dict[str, list[str]] = {}

    # ------------------------------------------------------------- storage

    async def async_load(self) -> None:
        """Read what was learned before the last restart."""
        try:
            stored = await self._store.async_load()
        except Exception:  # noqa: BLE001 - start empty rather than not at all
            _LOGGER.warning("Could not read the stored room assignment", exc_info=True)
            return
        if not isinstance(stored, dict):
            return
        self.learner = RoomLearner(stored)
        links = stored.get("links")
        names = stored.get("names")
        areas = stored.get("areas")
        if isinstance(links, dict):
            self._links = {str(key): str(value) for key, value in links.items()}
        if isinstance(names, dict):
            self._names = {str(key): str(value) for key, value in names.items()}
        if isinstance(areas, list):
            self._areas = {str(item) for item in areas}

    def _data(self) -> dict[str, Any]:
        return {
            **self.learner.as_dict(),
            "links": dict(sorted(self._links.items())),
            "names": dict(sorted(self._names.items())),
            "areas": sorted(self._areas),
        }

    def _save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY_SECONDS)

    # ------------------------------------------------------------- learning

    def observe(self, snapshots: dict[str, DeviceSnapshot], now: float) -> None:
        """Feed the learner and apply what is known. Never raises."""
        try:
            dirty = self._learn(snapshots, now)
            dirty = self._sync_registry() or dirty
        except Exception:  # noqa: BLE001 - never fail the coordinator over this
            _LOGGER.debug("Room assignment failed", exc_info=True)
            return
        if dirty:
            self._save()

    def _learn(self, snapshots: dict[str, DeviceSnapshot], now: float) -> bool:
        rooms: dict[tuple[str, str], dict[str, tuple[float, ...]]] = {}
        trvs: dict[tuple[str, str], dict[str, float]] = {}
        self._rooms = {}
        self._trvs = {}
        self._api_rooms = {}
        fresh: set[tuple[str, str]] = set()
        for snapshot in snapshots.values():
            device = snapshot.device
            features = snapshot.features
            group = _group(device)
            if device.device_type == DEVICE_TYPE_ROOM_CONTROL:
                for index in specs.room_indexes(features):
                    rid = room_id(device, index)
                    self._rooms[rid] = RoomRef(rid, index, specs.room_name(features, index))
                    rooms.setdefault(group, {})[rid] = room_setpoints(features, index)
                    for actor in thermostats.room_actors(features, index):
                        self._api_rooms[(group, actor)] = rid
                if snapshot.updated == now:
                    fresh.add(group)
            elif device.device_type == DEVICE_TYPE_ZIGBEE and (
                setpoint := thermostats.trv_setpoint(features)
            ):
                self._trvs[device.ref_id] = device
                # A snapshot kept from an earlier look says nothing new.
                if snapshot.updated == now:
                    trvs.setdefault(group, {})[device.ref_id] = setpoint.value

        changed = False
        for group, group_trvs in trvs.items():
            if group in fresh and rooms.get(group):
                changed = self.learner.observe(now, group_trvs, rooms[group]) or changed
        return changed

    # -------------------------------------------------------------- lookups

    def room_of(self, trv: DeviceRef) -> RoomRef | None:
        """Return the room of a thermostat: from the API, else learned."""
        rid = self._api_rooms.get((_group(trv), trv.device_id))
        source = SOURCE_API
        if rid is None:
            rid = self.learner.assigned(trv.ref_id)
            source = SOURCE_LEARNED
        room = self._rooms.get(rid) if rid is not None else None
        if room is None:
            return None
        return RoomRef(room.room_id, room.index, room.api_name, source)

    def candidates_of(self, trv: DeviceRef) -> list[RoomRef]:
        """Return the rooms a thermostat can still belong to."""
        if (room := self.room_of(trv)) is not None:
            return [room]
        return [
            self._rooms[rid]
            for rid in self.learner.candidates(trv.ref_id)
            if rid in self._rooms
        ]

    def learned_name(self, rid: str) -> str | None:
        """Return the name this integration found for a room, if any."""
        return self._names.get(rid)

    def thermostats_of(self, rid: str) -> list[str]:
        """Return the names of the thermostats assigned to a room."""
        return list(self._room_thermostats.get(rid, []))

    def room_label(self, room: RoomRef) -> str:
        """Return the name of a room as Home Assistant shows it."""
        entry = self._room_device(room.room_id)
        if entry is not None:
            name = getattr(entry, "name_by_user", None) or getattr(entry, "name", None)
            if name:
                return str(name)
        return room.api_name or self._names.get(room.room_id) or self._default_name(room.index)

    def diagnostics(self) -> list[dict[str, Any]]:
        """Return the state per thermostat without serial numbers."""
        result = []
        for ref_id, device in sorted(self._trvs.items()):
            room = self.room_of(device)
            result.append(
                {
                    "device_id": f"zigbee-...{device.device_id[-4:]}",
                    "room": room.index if room else None,
                    "source": room.source if room else None,
                    "candidates": [item.index for item in self.candidates_of(device)],
                    "linked": ref_id in self._links,
                }
            )
        return result

    # ------------------------------------------------------------- registry

    def _default_name(self, index: int) -> str:
        language = str(getattr(self._hass.config, "language", "") or "").lower()
        return f"Raum {index}" if language.startswith("de") else f"Room {index}"

    def _room_device(self, rid: str) -> Any | None:
        try:
            return dr.async_get(self._hass).async_get_device_by_identifier(
                (DOMAIN, rid), self._entry.entry_id
            )
        except Exception:  # noqa: BLE001
            return None

    def _trv_device(self, device: DeviceRef) -> Any | None:
        if device.identifier is None or device.entry_id is None:
            return None
        return dr.async_get(self._hass).async_get_device_by_identifier(
            (VICARE_DOMAIN, device.identifier), device.entry_id
        )

    def _sync_registry(self) -> bool:
        """Link thermostats to rooms, name rooms. Returns True if to be stored."""
        registry = dr.async_get(self._hass)
        dirty = False
        by_room: dict[str, list[Any]] = {}

        for ref_id, device in self._trvs.items():
            entry = self._trv_device(device)
            if entry is None:
                continue
            room = self.room_of(device)
            room_entry = self._room_device(room.room_id) if room else None
            linked = self._links.get(ref_id)
            via = getattr(entry, "via_device_id", None)
            if room is not None and room_entry is not None:
                by_room.setdefault(room.room_id, []).append(entry)
                if via != room_entry.id and (via is None or via == linked):
                    registry.async_update_device(entry.id, via_device_id=room_entry.id)
                    via = room_entry.id
                if via == room_entry.id and linked != room_entry.id:
                    self._links[ref_id] = room_entry.id
                    dirty = True
            elif room is None and linked is not None:
                if via == linked:
                    registry.async_update_device(entry.id, via_device_id=None)
                del self._links[ref_id]
                dirty = True

        self._room_thermostats = {
            rid: sorted(
                str(getattr(entry, "name_by_user", None) or getattr(entry, "name", None) or "")
                for entry in entries
            )
            for rid, entries in by_room.items()
        }
        return self._name_rooms(registry, by_room) or dirty

    def _name_rooms(self, registry: Any, by_room: dict[str, list[Any]]) -> bool:
        dirty = False
        areas: dict[str, str | None] = {}
        for rid, entries in by_room.items():
            found = {getattr(entry, "area_id", None) for entry in entries}
            areas[rid] = next(iter(found)) if len(found) == 1 else None
        shared = Counter(area for area in areas.values() if area)

        names: dict[str, str] = {}
        for rid, entries in by_room.items():
            area_id = areas[rid]
            name: str | None = None
            if area_id and shared[area_id] == 1:
                area = ar.async_get(self._hass).async_get_area(area_id)
                name = getattr(area, "name", None)
            elif len(entries) == 1:
                name = getattr(entries[0], "name_by_user", None)
            if name:
                names[rid] = str(name)
        duplicates = {name for name, count in Counter(names.values()).items() if count > 1}

        for rid in by_room:
            room = self._rooms.get(rid)
            room_entry = self._room_device(rid)
            if room is None or room_entry is None:
                continue
            previous = self._names.get(rid)
            name = names.get(rid)
            if name and name not in duplicates and name != previous:
                self._names[rid] = name
                dirty = True
            wanted = self._names.get(rid)
            current = getattr(room_entry, "name", None)
            replaceable = {previous, f"Raum {room.index}", f"Room {room.index}"}
            if (
                wanted
                and room.api_name is None
                and current != wanted
                and current in replaceable
            ):
                registry.async_update_device(room_entry.id, name=wanted)
            area_id = areas[rid]
            if (
                area_id
                and rid not in self._areas
                and getattr(room_entry, "area_id", None) is None
            ):
                registry.async_update_device(room_entry.id, area_id=area_id)
                self._areas.add(rid)
                dirty = True
        return dirty
