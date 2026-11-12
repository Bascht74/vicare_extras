"""Tests for the learner that finds the room of a radiator thermostat.

The first scenario uses the setpoints of a real installation (12 rooms,
16 thermostats, 2026-11-12); everything else is synthetic.
"""

from __future__ import annotations

from custom_components.vicare_extras.room_mapping import (
    STABLE_SECONDS,
    RoomLearner,
    matches,
    room_setpoints,
)

from . import fakes

# Room → (normal, reduced) as the real installation showed them.
REAL_ROOMS = {
    "r0": (23.0, 24.0),
    "r2": (23.5, 26.0),
    "r3": (23.0, 24.0),
    "r4": (23.0,),
    "r5": (23.0, 25.0),
    "r6": (23.0, 24.5),
    "r7": (18.5, 20.0),
    "r8": (18.5, 20.0),
    "r9": (23.0, 23.5),
    "r10": (18.5, 20.0),
    "r11": (19.5, 20.0),
}
REAL_TRVS = {
    "buero_links": 24.0,
    "buero_rechts": 24.0,
    "wz_1": 26.0,
    "wz_2": 26.0,
    "kueche": 24.0,
    "arbeitszimmer": 23.0,
    "flur": 25.0,
    "bad_eg": 24.5,
    "bettina": 20.0,
    "bad_og": 20.0,
    "schlafzimmer": 23.5,
}


def settle(learner: RoomLearner, trvs, rooms, start: float = 0.0) -> float:
    """Feed the same situation until mismatches count; return the end time."""
    learner.observe(start, trvs, rooms)
    end = start + STABLE_SECONDS
    learner.observe(end, trvs, rooms)
    return end


def test_room_setpoints_collects_all_levels() -> None:
    features = {item["feature"]: item for item in fakes.room_features(3)}
    assert room_setpoints(features, 3) == (18.0, 21.0, 23.0)
    assert room_setpoints(features, 4) == ()
    assert matches(21.0, (18.0, 21.0)) and not matches(21.5, (18.0, 21.0))


def test_real_installation_first_sight() -> None:
    learner = RoomLearner()
    settle(learner, REAL_TRVS, REAL_ROOMS)

    assert learner.assigned("wz_1") == "r2"
    assert learner.assigned("wz_2") == "r2"
    assert learner.assigned("flur") == "r5"
    assert learner.assigned("bad_eg") == "r6"
    # 23.5 °C is also the reduced setpoint of the living room, and 23 °C the
    # reduced setpoint of many rooms: which level a room is in is not known,
    # so these stay open until the setpoints move apart.
    assert learner.candidates("schlafzimmer") == ["r2", "r9"]
    assert learner.candidates("arbeitszimmer") == ["r0", "r3", "r4", "r5", "r6", "r9"]
    # Two rooms with identical setpoints cannot be told apart.
    assert learner.assigned("kueche") is None
    assert learner.candidates("kueche") == ["r0", "r3"]
    assert learner.candidates("bettina") == ["r10", "r11", "r7", "r8"]


def test_real_installation_after_the_first_night() -> None:
    learner = RoomLearner()
    end = settle(learner, REAL_TRVS, REAL_ROOMS)
    # At night every thermostat shows the reduced setpoint of its room.
    night = {**REAL_TRVS, "schlafzimmer": 23.0, "wz_1": 23.5, "wz_2": 23.5, "bettina": 19.5}
    settle(learner, night, REAL_ROOMS, end + 60)
    assert learner.assigned("schlafzimmer") == "r9"
    assert learner.assigned("wz_1") == "r2"
    assert learner.assigned("bettina") == "r11"


def test_nothing_is_ruled_out_before_the_waiting_time() -> None:
    learner = RoomLearner()
    learner.observe(0, REAL_TRVS, REAL_ROOMS)
    learner.observe(STABLE_SECONDS - 1, REAL_TRVS, REAL_ROOMS)
    assert learner.assigned("wz_1") is None
    assert len(learner.candidates("wz_1")) == len(REAL_ROOMS)


def test_a_change_restarts_the_waiting_time() -> None:
    rooms = {"a": (20.0,), "b": (22.0,)}
    learner = RoomLearner()
    learner.observe(0, {"trv": 20.0}, rooms)
    # Room b changes shortly before it would have been ruled out.
    rooms = {"a": (20.0,), "b": (22.5,)}
    learner.observe(STABLE_SECONDS - 10, {"trv": 20.0}, rooms)
    learner.observe(STABLE_SECONDS + 10, {"trv": 20.0}, rooms)
    assert learner.candidates("trv") == ["a", "b"]
    learner.observe(2 * STABLE_SECONDS, {"trv": 20.0}, rooms)
    assert learner.assigned("trv") == "a"


def test_night_setback_separates_rooms() -> None:
    rooms = {"r7": (18.5, 20.0), "r11": (19.5, 20.0)}
    learner = RoomLearner()
    end = settle(learner, {"trv": 20.0}, rooms)
    assert learner.candidates("trv") == ["r11", "r7"]
    # At night the thermostat follows the reduced setpoint of its room.
    settle(learner, {"trv": 19.5}, rooms, end + 60)
    assert learner.assigned("trv") == "r11"


def test_setpoint_changed_at_the_thermostat_rules_nothing_out() -> None:
    rooms = {"a": (20.0,), "b": (22.0,)}
    learner = RoomLearner()
    # 27 °C fits no room at all: somebody turned the thermostat itself.
    settle(learner, {"trv": 27.0}, rooms)
    assert learner.candidates("trv") == ["a", "b"]
    assert learner.assigned("trv") is None


def test_learning_starts_over_when_every_room_is_ruled_out() -> None:
    rooms = {"a": (20.0,), "b": (22.0,)}
    learner = RoomLearner()
    end = settle(learner, {"trv": 20.0}, rooms)
    assert learner.assigned("trv") == "a"
    # The thermostat was moved to room b.
    end = settle(learner, {"trv": 22.0}, rooms, end + 60)
    assert learner.assigned("trv") is None
    assert learner.candidates("trv") == ["a", "b"]
    assert learner.as_dict()["thermostats"]["trv"]["resets"] == 1
    settle(learner, {"trv": 22.0}, rooms, end + 60)
    assert learner.assigned("trv") == "b"


def test_single_room_is_assigned_after_its_first_match() -> None:
    learner = RoomLearner()
    assert learner.observe(0, {"trv": 21.0}, {"only": (18.0, 21.0)}) is True
    assert learner.assigned("trv") == "only"
    # The same situation again changes nothing that has to be stored.
    assert learner.observe(60, {"trv": 21.0}, {"only": (18.0, 21.0)}) is False


def test_rooms_without_setpoint_and_removed_rooms() -> None:
    learner = RoomLearner()
    end = settle(learner, {"trv": 20.0}, {"a": (20.0,), "b": (22.0,), "empty": ()})
    assert learner.assigned("trv") == "a"
    # Room b is deleted in the app, a new room c appears: c is a candidate.
    learner.observe(end + 60, {"trv": 20.0}, {"a": (20.0,), "c": (20.0,)})
    assert learner.candidates("trv") == ["a", "c"]
    assert learner.as_dict()["thermostats"]["trv"]["eliminated"] == []


def test_state_survives_a_restart() -> None:
    learner = RoomLearner()
    settle(learner, REAL_TRVS, REAL_ROOMS)
    restored = RoomLearner(learner.as_dict())
    # Candidates are known again after the first look.
    assert restored.assigned("wz_1") is None
    restored.observe(0, REAL_TRVS, REAL_ROOMS)
    assert restored.assigned("wz_1") == "r2"
    assert restored.candidates("kueche") == ["r0", "r3"]
    assert RoomLearner({"thermostats": {"x": "broken"}}).as_dict() == {"thermostats": {}}


def test_forget() -> None:
    learner = RoomLearner()
    learner.observe(0, {"trv": 21.0}, {"only": (21.0,)})
    assert learner.forget("trv") is True
    assert learner.forget("trv") is False
    assert learner.candidates("trv") == []
