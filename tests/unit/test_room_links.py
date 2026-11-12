"""Tests for linking thermostats to rooms and naming rooms after them.

Synthetic features; the setpoints follow what a real installation showed.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntry

from custom_components.vicare_extras.bridge import DeviceRef
from custom_components.vicare_extras.coordinator import DeviceSnapshot
from custom_components.vicare_extras.room_links import (
    RoomLinkManager,
    room_id,
    storage_key,
)
from custom_components.vicare_extras.room_mapping import STABLE_SECONDS

from . import fakes
from .fakes import Platforms

GATEWAY = "GW1"
VICARE_ENTRY = "vicare-entry"
CONTROL = DeviceRef(
    VICARE_ENTRY, "1", GATEWAY, "RoomControl-1", "roomControl", "Smart_RoomControl_51",
    None, None, None,
)


def trv_ref(name: str) -> DeviceRef:
    return DeviceRef(
        VICARE_ENTRY, "1", GATEWAY, f"zigbee-{name}", "zigbee", "eTRV", None,
        f"{GATEWAY}_zigbee_{name}", None,
    )


def room_features(rooms: dict[int, tuple[float, float]], **extra: Any) -> dict[str, dict]:
    features: dict[str, dict] = {}
    for index, (normal, reduced) in rooms.items():
        for level, value in (("normal", normal), ("reduced", reduced)):
            name = f"rooms.{index}.temperature.levels.{level}.heating"
            features[name] = {"feature": name, "properties": {"temperature": {"value": value}}}
    for name, properties in extra.items():
        features[name] = {"feature": name, "properties": properties}
    return features


def trv_features(setpoint: float) -> dict[str, dict]:
    return {
        "trv.temperature": {
            "feature": "trv.temperature",
            "properties": {"value": {"value": setpoint}},
        }
    }


class Site:
    """A fake hass with rooms 2 and 5, three thermostats and their devices."""

    ROOMS = {2: (26.0, 23.5), 5: (25.0, 23.0)}
    TRVS = {"a": 26.0, "b": 26.0, "c": 25.0}

    def __init__(self) -> None:
        self.hass = fakes.FakeHass()
        self.entry = ConfigEntry(domain="vicare_extras", entry_id="extras")
        self.hass.area_registry.add("wohnzimmer", "Wohnzimmer")
        self.hass.area_registry.add("flur", "Flur")
        self.devices = self.hass.device_registry
        for name, user_name, area in (
            ("a", "WZ links", "wohnzimmer"),
            ("b", "WZ rechts", "wohnzimmer"),
            ("c", "Flur EG", "flur"),
        ):
            self.devices.add(
                DeviceEntry(
                    id=f"trv-{name}",
                    identifiers={("vicare", f"{GATEWAY}_zigbee_{name}")},
                    config_entry_id=VICARE_ENTRY,
                    name="Smart Device eTRV",
                    name_by_user=user_name,
                    area_id=area,
                )
            )
        for index in self.ROOMS:
            self.devices.add(
                DeviceEntry(
                    id=f"room-{index}",
                    identifiers={("vicare_extras", room_id(CONTROL, index))},
                    config_entry_id="extras",
                    name=f"Raum {index}",
                )
            )
        self.manager = RoomLinkManager(self.hass, self.entry)
        self.rooms = dict(self.ROOMS)
        self.trvs = dict(self.TRVS)
        self.extra: dict[str, Any] = {}
        self.now = 0.0

    def snapshots(self, now: float) -> dict[str, DeviceSnapshot]:
        result = {
            CONTROL.ref_id: DeviceSnapshot(CONTROL, room_features(self.rooms, **self.extra), now)
        }
        for name, setpoint in self.trvs.items():
            ref = trv_ref(name)
            result[ref.ref_id] = DeviceSnapshot(ref, trv_features(setpoint), now)
        return result

    def look(self, seconds: float = 0.0) -> None:
        self.now += seconds
        self.manager.observe(self.snapshots(self.now), self.now)

    def settle(self) -> None:
        self.look()
        self.look(STABLE_SECONDS)

    def device(self, device_id: str) -> DeviceEntry:
        return self.devices.async_get(device_id)

    def stored(self) -> dict[str, Any]:
        return self.hass.data["__storage__"][storage_key("extras")]


def test_thermostats_are_linked_and_rooms_named() -> None:
    site = Site()
    site.look()
    manager = site.manager
    # Nothing is known after the first look.
    assert manager.room_of(trv_ref("a")) is None
    assert [room.index for room in manager.candidates_of(trv_ref("a"))] == [2, 5]
    assert site.device("trv-a").via_device_id is None

    site.look(STABLE_SECONDS)
    room = manager.room_of(trv_ref("a"))
    assert (room.index, room.source) == (2, "learned")
    assert manager.room_of(trv_ref("c")).index == 5
    assert [room.index for room in manager.candidates_of(trv_ref("a"))] == [2]

    # Thermostats hang below their room.
    assert site.device("trv-a").via_device_id == "room-2"
    assert site.device("trv-b").via_device_id == "room-2"
    assert site.device("trv-c").via_device_id == "room-5"
    # Rooms take name and area of the area their thermostats are in.
    assert site.device("room-2").name == "Wohnzimmer"
    assert site.device("room-2").area_id == "wohnzimmer"
    assert site.device("room-5").name == "Flur"
    assert manager.room_label(room) == "Wohnzimmer"
    assert manager.thermostats_of(room.room_id) == ["WZ links", "WZ rechts"]
    assert manager.learned_name(room.room_id) == "Wohnzimmer"

    stored = site.stored()
    assert stored["links"][trv_ref("a").ref_id] == "room-2"
    assert stored["names"][room.room_id] == "Wohnzimmer"
    assert stored["areas"] == sorted(room_id(CONTROL, index) for index in (2, 5))
    assert manager.diagnostics()[0] == {
        "device_id": "zigbee-...ee-a",
        "room": 2,
        "source": "learned",
        "candidates": [2],
        "linked": True,
    }


def test_names_and_areas_set_by_the_user_stay() -> None:
    site = Site()
    site.devices.async_update_device("room-2", name_by_user="Stube", area_id="flur")
    site.devices.async_update_device("room-5", name="Diele")
    site.settle()
    # name_by_user is never touched, and it is what the thermostat shows.
    assert site.device("room-2").name_by_user == "Stube"
    assert site.device("room-2").area_id == "flur"
    assert site.manager.room_label(site.manager.room_of(trv_ref("a"))) == "Stube"
    # A name that is not the default "Raum N" is not replaced.
    assert site.device("room-5").name == "Diele"

    # The area is given once: removed by the user, it stays removed.
    site.devices.async_update_device("room-5", area_id=None)
    site.look(60)
    assert site.device("room-5").area_id is None


def test_room_named_by_the_api_keeps_its_name() -> None:
    site = Site()
    site.extra = {"rooms.2": {"name": {"value": "Salon"}}}
    site.devices.async_update_device("room-2", name="Salon")
    site.settle()
    assert site.device("room-2").name == "Salon"
    assert site.manager.room_label(site.manager.room_of(trv_ref("a"))) == "Salon"


def test_rooms_sharing_an_area_are_named_after_their_thermostat() -> None:
    site = Site()
    site.trvs = {"a": 26.0, "c": 25.0}
    site.devices.async_update_device("trv-c", area_id="wohnzimmer")
    site.settle()
    assert site.device("room-2").name == "WZ links"
    assert site.device("room-5").name == "Flur EG"

    # Two thermostats in such a room: no name can be derived.
    other = Site()
    other.devices.async_update_device("trv-c", area_id="wohnzimmer")
    other.settle()
    assert other.device("room-2").name == "Raum 2"
    assert other.device("room-5").name == "Flur EG"


def test_room_name_follows_a_renamed_area() -> None:
    site = Site()
    site.settle()
    site.hass.area_registry.add("wohnzimmer", "Wohnen")
    site.look(60)
    assert site.device("room-2").name == "Wohnen"


def test_foreign_link_is_left_alone_and_own_link_removed() -> None:
    site = Site()
    site.devices.async_update_device("trv-a", via_device_id="somebody-else")
    site.settle()
    assert site.device("trv-a").via_device_id == "somebody-else"
    assert trv_ref("a").ref_id not in site.stored()["links"]
    assert site.device("trv-c").via_device_id == "room-5"

    # Thermostat c now fits no room it was left with: learning starts over
    # and the link this integration set is taken back.
    site.trvs["c"] = 26.0
    site.look(60)
    site.look(STABLE_SECONDS)
    assert site.manager.room_of(trv_ref("c")) is None
    assert site.device("trv-c").via_device_id is None
    assert trv_ref("c").ref_id not in site.stored()["links"]
    # Starting over means waiting again before a room is ruled out.
    site.look(60)
    site.look(STABLE_SECONDS)
    assert site.device("trv-c").via_device_id == "room-2"


def test_actors_from_the_api_win() -> None:
    site = Site()
    site.extra = {
        "rooms.5": {"actors": {"value": [{"deviceId": "zigbee-a", "heatingCircuit": 0}]}}
    }
    site.settle()
    room = site.manager.room_of(trv_ref("a"))
    assert (room.index, room.source) == (5, "api")
    assert site.device("trv-a").via_device_id == "room-5"
    assert site.manager.room_of(trv_ref("b")).source == "learned"


def test_candidates_are_sorted_by_room_number() -> None:
    site = Site()
    site.rooms = {2: (26.0, 23.5), 10: (26.0, 23.5), 11: (25.0, 23.0)}
    site.look()
    assert [room.index for room in site.manager.candidates_of(trv_ref("a"))] == [2, 10, 11]


def test_kept_snapshots_teach_nothing() -> None:
    site = Site()
    site.look()
    # The built-in integration is refreshing: the old snapshots are kept.
    stale = site.snapshots(0.0)
    site.manager.observe(stale, STABLE_SECONDS)
    site.manager.observe(stale, 2 * STABLE_SECONDS)
    assert site.manager.room_of(trv_ref("a")) is None


def test_missing_devices_do_not_break_anything() -> None:
    site = Site()
    site.devices.devices.pop("room-2")
    site.devices.devices.pop("trv-c")
    site.settle()
    # The room is known, the link waits for the room device.
    assert site.manager.room_of(trv_ref("a")).index == 2
    assert site.device("trv-a").via_device_id is None
    assert site.manager.room_label(site.manager.room_of(trv_ref("a"))) == "Raum 2"


def test_assignment_survives_a_restart() -> None:
    site = Site()
    site.settle()
    manager = RoomLinkManager(site.hass, site.entry)
    asyncio.run(manager.async_load())
    assert manager.learned_name(room_id(CONTROL, 2)) == "Wohnzimmer"
    manager.observe(site.snapshots(0.0), 0.0)
    assert manager.room_of(trv_ref("a")).index == 2
    assert manager.room_of(trv_ref("c")).index == 5


def test_remove_entry_deletes_the_store() -> None:
    from custom_components import vicare_extras

    site = Site()
    site.settle()
    assert storage_key("extras") in site.hass.data["__storage__"]
    asyncio.run(vicare_extras.async_remove_entry(site.hass, site.entry))
    assert storage_key("extras") not in site.hass.data["__storage__"]


def test_platforms_show_candidates_and_learned_room_name() -> None:
    payload = fakes.gateway_payload([], fakes.room_features(0, name=None), fakes.trv_features())
    hass, _ = fakes.make_hass(payload, with_trv=True)
    platforms = Platforms(hass).setup()
    thermostat = next(
        entity for entity in platforms.climates
        if entity.unique_id == f"{fakes.TRV_IDENTIFIER}-climate"
    )
    attributes = thermostat.extra_state_attributes
    # 20 °C at the thermostat, 18/21/23 °C in the room: no match yet.
    assert attributes["room"] is None
    assert attributes["room_source"] is None
    assert attributes["room_candidates"] == ["Raum 0"]
    room = next(entity for entity in platforms.climates if entity is not thermostat)
    assert room.device_info.name == "Raum 0"
    assert room.extra_state_attributes["thermostats"] == []
