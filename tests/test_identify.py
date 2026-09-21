"""Tests for telling a Rec Temovex apart from other devices on the bus."""

from __future__ import annotations

import pytest
from rec_temovex.identify import RANGES, REQUIRED_KEYS, identity_problems
from rec_temovex.registers import REGISTER_BY_KEY

# Raw register words as a running unit reports them, decoded through the real
# map so the test also catches a scaling change that would break the check.
UNIT_RAW = {
    "outdoor_temperature": 123,  # 12.3 C
    "supply_temperature": 198,
    "extract_temperature": 221,
    "exhaust_temperature": 141,
    "regulation_mode": 2,
    "room_setpoint": 210,  # 21.0 C
    "supply_setpoint_min": 150,
    "supply_setpoint_max": 280,
    "supply_fan_min": 30,
    "exhaust_fan_min": 30,
    "supply_fan_normal": 46,
    "exhaust_fan_normal": 46,
    "supply_fan_forced": 70,
    "exhaust_fan_forced": 70,
    "supply_fan_max": 100,
    "exhaust_fan_max": 100,
    "fan_mode": 1,
    "heating_mode": 2,
    "bypass_mode": 2,
    "cooling_mode": 0,
}


def _decode(raw: dict[str, int]) -> dict[str, float | int | bool]:
    return {key: REGISTER_BY_KEY[key].decode(value) for key, value in raw.items()}


def test_a_running_unit_passes():
    assert identity_problems(_decode(UNIT_RAW)) == []


def test_a_stopped_unit_in_winter_passes():
    raw = {
        **UNIT_RAW,
        "fan_mode": 0,
        "outdoor_temperature": -250,
        "supply_temperature": -180,
        "exhaust_temperature": -240,
        "extract_temperature": 120,
    }
    assert identity_problems(_decode(raw)) == []


def test_all_zero_registers_are_rejected():
    """An idle device, or a meter with nothing in those addresses."""
    problems = identity_problems(_decode(dict.fromkeys(UNIT_RAW, 0)))
    keys = {problem.key for problem in problems}
    assert {"room_setpoint", "supply_fan_normal", "temperatures"} <= keys


def test_an_energy_meter_is_rejected():
    """Voltages, currents and counters land where the unit keeps its values."""
    meter = {
        key: value
        for key, value in zip(
            UNIT_RAW,
            (
                2301,
                2298,
                2305,
                0,
                12,
                4999,
                1532,
                0,
                65535,
                1,
                3,
                0,
                812,
                17,
                0,
                9,
                400,
                50,
                2,
                1,
            ),
            strict=True,
        )
    }
    assert len(identity_problems(_decode(meter))) >= 5


def test_missing_registers_are_rejected():
    data = _decode(UNIT_RAW)
    del data["room_setpoint"]
    assert [str(p) for p in identity_problems(data)] == ["room_setpoint: not answered"]


@pytest.mark.parametrize(
    ("key", "raw"),
    [
        ("regulation_mode", 7),
        ("fan_mode", 9),
        ("supply_fan_normal", 0),
        ("supply_fan_max", 460),
        ("room_setpoint", 0),
        ("extract_temperature", 900),
    ],
)
def test_one_value_out_of_range_is_named(key, raw):
    problems = identity_problems(_decode({**UNIT_RAW, key: raw}))
    assert [problem.key for problem in problems] == [key]


def test_supply_limits_must_be_ordered():
    problems = identity_problems(
        _decode({**UNIT_RAW, "supply_setpoint_min": 300, "supply_setpoint_max": 200})
    )
    assert [problem.key for problem in problems] == ["supply_setpoint_min"]


def test_every_checked_key_is_in_the_map():
    for key in (*REQUIRED_KEYS, *RANGES):
        assert REGISTER_BY_KEY[key].verified, key
