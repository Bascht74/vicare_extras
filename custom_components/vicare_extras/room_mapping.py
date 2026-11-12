"""Learn which room a radiator thermostat belongs to (no Home Assistant imports).

The Viessmann API names the thermostats of a room only in ``rooms.<n>.actors``
and that property is missing in the basic API plan. What every plan shows is
the setpoint of each thermostat (``trv.temperature``) and the setpoints of
each room. All thermostats of a room follow the room's setpoint, so a room
whose setpoints differ from a thermostat's setpoint cannot be its room.

The learner keeps, per thermostat, the rooms that are ruled out:

* A room is ruled out when the thermostat's setpoint equals none of the
  room's setpoints for ``STABLE_SECONDS`` without either side changing. The
  waiting time covers the delay with which a battery powered thermostat picks
  up a new setpoint.
* While a thermostat's setpoint equals no room of its gateway at all, nothing
  is ruled out: it was changed at the thermostat itself, which holds for a
  limited time only.
* A thermostat is assigned once exactly one room is left and that room has
  matched at least once.
* If every room got ruled out (for instance after the thermostat was moved
  to another room), learning starts over for that thermostat.

Which level (normal, reduced, comfort) a room is in right now is not part of
the basic API plan either, so a thermostat fits a room when its setpoint
equals ANY of the room's setpoints. That is slower but never rules out the
right room just because the schedule switched. Rooms that share a setpoint
stay candidates until the setpoints move apart: by the night setback, or by
a change in the ViCare app.

Checked against live data of one installation (12 rooms, 16 thermostats,
2026-11-12): 6 thermostats were unambiguous at first sight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .features import prop_value

# A mismatch has to last this long, unchanged, before a room is ruled out.
STABLE_SECONDS = 1800.0
# Setpoints are multiples of 0.5 K; this only absorbs float noise.
TOLERANCE = 0.05

# Every setpoint a room can show: the effective one and all levels. A
# thermostat matches a room when its setpoint equals any of them.
ROOM_SETPOINT_FEATURES = (
    "rooms.{n}.temperature.levels.heating",
    "rooms.{n}.temperature.levels.normal.heating",
    "rooms.{n}.temperature.levels.reduced.heating",
    "rooms.{n}.temperature.levels.comfort.heating",
    "rooms.{n}.temperature.levels.normal.perceived",
    "rooms.{n}.temperature.levels.reduced.perceived",
    "rooms.{n}.temperature.levels.comfort.perceived",
    "rooms.{n}.operating.programs.normalHeating",
    "rooms.{n}.operating.programs.reducedHeating",
    "rooms.{n}.operating.programs.comfortHeating",
)
ROOM_SETPOINT_PROPERTY = "temperature"

type Signature = tuple[float, tuple[float, ...]]


def room_setpoints(features: dict[str, dict[str, Any]], room: int) -> tuple[float, ...]:
    """Return the distinct setpoints a room shows, sorted."""
    values: set[float] = set()
    for template in ROOM_SETPOINT_FEATURES:
        value = prop_value(
            features.get(template.replace("{n}", str(room))), ROOM_SETPOINT_PROPERTY
        )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        values.add(float(value))
    return tuple(sorted(values))


def matches(setpoint: float, room_values: tuple[float, ...]) -> bool:
    """Return True when a thermostat setpoint equals one of a room's setpoints."""
    return any(abs(setpoint - value) <= TOLERANCE for value in room_values)


@dataclass(slots=True)
class _Thermostat:
    """What is known about one thermostat."""

    # Persisted.
    eliminated: set[str] = field(default_factory=set)
    confirmed: dict[str, int] = field(default_factory=dict)
    resets: int = 0
    # Runtime only.
    rooms: tuple[str, ...] = ()
    pending: dict[str, tuple[Signature, float]] = field(default_factory=dict)
    last_match: dict[str, Signature] = field(default_factory=dict)


class RoomLearner:
    """Rule out rooms per thermostat until one is left.

    Thermostats and rooms are identified by strings the caller chooses (they
    are stored). ``observe`` is fed once per look at the data.
    """

    def __init__(self, stored: dict[str, Any] | None = None) -> None:
        """Initialize, optionally from what ``as_dict`` returned earlier."""
        self._thermostats: dict[str, _Thermostat] = {}
        for key, item in ((stored or {}).get("thermostats") or {}).items():
            if not isinstance(item, dict):
                continue
            confirmed = item.get("confirmed")
            self._thermostats[str(key)] = _Thermostat(
                eliminated={str(room) for room in item.get("eliminated") or []},
                confirmed=(
                    {str(room): int(count) for room, count in confirmed.items()}
                    if isinstance(confirmed, dict)
                    else {}
                ),
                resets=int(item.get("resets") or 0),
            )

    def as_dict(self) -> dict[str, Any]:
        """Return what has to be stored."""
        return {
            "thermostats": {
                key: {
                    "eliminated": sorted(state.eliminated),
                    "confirmed": dict(sorted(state.confirmed.items())),
                    "resets": state.resets,
                }
                for key, state in sorted(self._thermostats.items())
            }
        }

    def observe(
        self,
        now: float,
        thermostats: dict[str, float],
        rooms: dict[str, tuple[float, ...]],
    ) -> bool:
        """Take one look at the thermostats and rooms of ONE gateway.

        ``thermostats`` maps thermostat id → setpoint, ``rooms`` maps room id
        → setpoints of the room (rooms without any setpoint are left out by
        the caller or passed with an empty tuple; they are ignored). Returns
        True when something worth storing changed.
        """
        usable = {room: values for room, values in rooms.items() if values}
        changed = False
        for key, setpoint in thermostats.items():
            state = self._thermostats.get(key)
            if state is None:
                state = self._thermostats[key] = _Thermostat()
                changed = True
            state.rooms = tuple(sorted(usable))
            if not usable:
                state.pending.clear()
                continue
            # Forget rooms that no longer exist.
            stale = state.eliminated - set(usable)
            if stale:
                state.eliminated -= stale
                changed = True

            matching = {room for room, values in usable.items() if matches(setpoint, values)}
            if not matching:
                # Set at the thermostat itself (or not synchronised yet).
                state.pending.clear()
                continue

            for room, values in usable.items():
                signature: Signature = (setpoint, values)
                if room in matching:
                    state.pending.pop(room, None)
                    if room not in state.eliminated and state.last_match.get(room) != signature:
                        # A new situation in which the room fits.
                        state.last_match[room] = signature
                        state.confirmed[room] = state.confirmed.get(room, 0) + 1
                        changed = True
                    continue
                if room in state.eliminated:
                    continue
                pending = state.pending.get(room)
                if pending is None or pending[0] != signature:
                    state.pending[room] = (signature, now)
                elif now - pending[1] >= STABLE_SECONDS:
                    state.eliminated.add(room)
                    state.confirmed.pop(room, None)
                    state.pending.pop(room, None)
                    changed = True

            if not set(usable) - state.eliminated:
                # Everything ruled out: what was learned no longer holds.
                state.eliminated.clear()
                state.confirmed.clear()
                state.pending.clear()
                state.last_match.clear()
                state.resets += 1
                changed = True
        return changed

    def candidates(self, key: str) -> list[str]:
        """Return the rooms a thermostat can still belong to."""
        state = self._thermostats.get(key)
        if state is None:
            return []
        return [room for room in state.rooms if room not in state.eliminated]

    def assigned(self, key: str) -> str | None:
        """Return the room of a thermostat once it is the only one left."""
        state = self._thermostats.get(key)
        if state is None:
            return None
        left = self.candidates(key)
        if len(left) == 1 and state.confirmed.get(left[0], 0) >= 1:
            return left[0]
        return None

    def forget(self, key: str) -> bool:
        """Drop everything learned about a thermostat."""
        return self._thermostats.pop(key, None) is not None
