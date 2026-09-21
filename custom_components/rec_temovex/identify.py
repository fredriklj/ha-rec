"""Tell a Rec Temovex unit apart from whatever else answers on the bus.

Modbus has no way to ask a device what it is. Any device at the given address
will answer reads of holding and input registers with *something*, so a wrong
device ID — an energy meter on the same bus, say — reads without error and
produces an entry full of nonsense. What a Rec Temovex does have is a set of
registers whose values can only fall inside narrow ranges: temperatures a house
and its outdoor air can plausibly be at, a room setpoint someone would live
with, mode registers with a handful of legal values, fan speeds in percent.
A different device fails several of these at once.

The ranges are deliberately generous. The cost of rejecting a real unit — an
installation that cannot be added at all — is far higher than the cost of
letting an odd one through, so each check only rules out what no Rec Temovex
could report. Nothing here imports Home Assistant.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# Everything below needs these to say anything at all. A device that answers
# none of them was already rejected when reading; one that answers only some
# is not this unit.
REQUIRED_KEYS: tuple[str, ...] = (
    "outdoor_temperature",
    "supply_temperature",
    "extract_temperature",
    "exhaust_temperature",
    "regulation_mode",
    "room_setpoint",
    "supply_setpoint_min",
    "supply_setpoint_max",
    "supply_fan_normal",
    "exhaust_fan_normal",
    "fan_mode",
)

# (low, high), inclusive, in the decoded unit.
RANGES: dict[str, tuple[float, float]] = {
    # The air path. Outdoor and exhaust follow the weather; supply is heated or
    # cooled towards the room; extract is the house itself, which may be cold
    # but is not frozen solid.
    "outdoor_temperature": (-45, 50),
    "supply_temperature": (-30, 60),
    "extract_temperature": (-10, 50),
    "exhaust_temperature": (-45, 50),
    # Setpoints someone would actually choose. Zero, the value an unrelated
    # register most often holds, is outside every one of them.
    "room_setpoint": (5, 40),
    "supply_setpoint_min": (0, 60),
    "supply_setpoint_max": (5, 60),
    # Enumerations.
    "regulation_mode": (0, 3),
    "fan_mode": (0, 8),
    "heating_mode": (0, 2),
    "bypass_mode": (0, 2),
    "cooling_mode": (0, 2),
    # Fan speed settings are percentages, and normal flow is never zero on a
    # unit that ventilates a house.
    "supply_fan_min": (0, 100),
    "exhaust_fan_min": (0, 100),
    "supply_fan_normal": (1, 100),
    "exhaust_fan_normal": (1, 100),
    "supply_fan_forced": (0, 100),
    "exhaust_fan_forced": (0, 100),
    "supply_fan_max": (0, 100),
    "exhaust_fan_max": (0, 100),
}

AIR_TEMPERATURES: tuple[str, ...] = (
    "outdoor_temperature",
    "supply_temperature",
    "extract_temperature",
    "exhaust_temperature",
)


@dataclass(frozen=True)
class IdentityProblem:
    """One reason the device does not look like a Rec Temovex."""

    key: str
    reason: str

    def __str__(self) -> str:
        """Render for a log line."""
        return f"{self.key}: {self.reason}"


def identity_problems(
    data: Mapping[str, float | int | bool],
) -> list[IdentityProblem]:
    """Check a first read against what a Rec Temovex can report.

    Returns an empty list when the device looks like one.
    """
    problems = [
        IdentityProblem(key, "not answered") for key in REQUIRED_KEYS if key not in data
    ]

    for key, (low, high) in RANGES.items():
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, bool) or not low <= float(value) <= high:
            problems.append(IdentityProblem(key, f"{value!r} outside {low}..{high}"))

    # Four sensors in different places do not all read exactly zero; four
    # empty registers do.
    temperatures = [data[key] for key in AIR_TEMPERATURES if key in data]
    if len(temperatures) == len(AIR_TEMPERATURES) and all(
        float(value) == 0 for value in temperatures
    ):
        problems.append(IdentityProblem("temperatures", "all exactly zero"))

    low, high = data.get("supply_setpoint_min"), data.get("supply_setpoint_max")
    if low is not None and high is not None and float(low) > float(high):
        problems.append(
            IdentityProblem(
                "supply_setpoint_min", f"{low!r} above the maximum {high!r}"
            )
        )

    return problems
