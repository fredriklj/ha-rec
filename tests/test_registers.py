"""Tests for the register map and the read block planner."""

from __future__ import annotations

import pytest
from rec_temovex.registers import (
    REGISTERS,
    DataType,
    RegisterDef,
    RegisterKind,
    plan_blocks,
)


def _holding(address: int, key: str | None = None, **kwargs) -> RegisterDef:
    return RegisterDef(
        key=key or f"h{address}",
        kind=RegisterKind.HOLDING,
        address=address,
        **kwargs,
    )


def test_register_keys_are_unique():
    keys = [r.key for r in REGISTERS]
    assert len(keys) == len(set(keys))


def test_no_two_registers_share_an_address_in_the_same_space():
    seen: set[tuple[RegisterKind, int]] = set()
    for reg in REGISTERS:
        for offset in range(reg.count):
            slot = (reg.kind, reg.address + offset)
            assert slot not in seen, f"{reg.key} overlaps at {slot}"
            seen.add(slot)


def test_adjacent_registers_merge_into_one_block():
    blocks = plan_blocks([_holding(0), _holding(1), _holding(2)])
    assert len(blocks) == 1
    assert blocks[0].address == 0
    assert blocks[0].count == 3
    assert set(blocks[0].keys) == {"h0", "h1", "h2"}


def test_small_gap_is_bridged():
    blocks = plan_blocks([_holding(0), _holding(4)], max_gap=8)
    assert len(blocks) == 1
    assert blocks[0].count == 5


def test_large_gap_splits_the_block():
    blocks = plan_blocks([_holding(0), _holding(40)], max_gap=8)
    assert len(blocks) == 2
    assert [b.address for b in blocks] == [0, 40]


def test_block_respects_the_register_ceiling():
    regs = [_holding(a) for a in range(0, 100, 2)]
    blocks = plan_blocks(regs, max_gap=8, max_registers=16)
    assert all(b.count <= 16 for b in blocks)
    covered = {k for b in blocks for k in b.keys}
    assert covered == {r.key for r in regs}


def test_address_spaces_never_share_a_block():
    regs = [
        _holding(0),
        RegisterDef(key="i0", kind=RegisterKind.INPUT, address=0),
        RegisterDef(key="c0", kind=RegisterKind.COIL, address=0),
    ]
    blocks = plan_blocks(regs)
    assert len(blocks) == 3
    assert {b.kind for b in blocks} == {
        RegisterKind.HOLDING,
        RegisterKind.INPUT,
        RegisterKind.COIL,
    }


def test_32_bit_register_occupies_two_words():
    reg = _holding(10, data_type=DataType.INT32)
    assert reg.count == 2
    blocks = plan_blocks([reg])
    assert blocks[0].count == 2


def test_every_register_is_covered_by_exactly_one_block():
    blocks = plan_blocks(REGISTERS)
    covered = [k for b in blocks for k in b.keys]
    assert sorted(covered) == sorted(r.key for r in REGISTERS)


@pytest.mark.parametrize(
    ("raw", "scale", "offset", "expected"),
    [
        (215, 0.1, 0.0, 21.5),
        (-35, 0.1, 0.0, -3.5),
        (3, 1.0, 0.0, 3),
        (100, 0.5, 5.0, 55.0),
    ],
)
def test_decode_applies_scale_and_offset(raw, scale, offset, expected):
    reg = _holding(0, scale=scale, offset=offset, precision=2)
    assert reg.decode(raw) == pytest.approx(expected)


def test_encode_round_trips_through_decode():
    reg = _holding(0, scale=0.1, precision=1)
    assert reg.decode(reg.encode(21.5)) == pytest.approx(21.5)


def test_encode_rounds_rather_than_truncating():
    reg = _holding(0, scale=0.1)
    # The old integration truncated here, losing half a degree.
    assert reg.encode(21.49) == 215


def test_off_is_both_a_hvac_mode_and_a_fan_mode():
    """Both write register value 0, so they cannot disagree."""
    from rec_temovex.const import FAN_MODE_OFF, FAN_MODES, SELECTABLE_FAN_MODES

    assert FAN_MODES[0] == FAN_MODE_OFF
    assert SELECTABLE_FAN_MODES[0] == FAN_MODE_OFF


def test_serial_stop_bits_follow_the_parity():
    """A Modbus RTU character is eleven bits, however the parity is set."""
    from rec_temovex.transport import SerialTransport

    assert SerialTransport(port="/dev/ttyUSB0", parity="N").stopbits == 2
    assert SerialTransport(port="/dev/ttyUSB0", parity="E").stopbits == 1
    assert SerialTransport(port="/dev/ttyUSB0", parity="O").stopbits == 1


def test_the_serial_client_speaks_rtu_not_socket_framing():
    """TCP framing over a serial line reads nothing at all.

    Also pins the settings pymodbus is handed, since the stop bits are derived
    rather than passed in by the user.
    """
    from unittest.mock import patch

    from pymodbus import FramerType
    from rec_temovex.transport import SerialTransport

    with patch("rec_temovex.transport.AsyncModbusSerialClient") as client:
        SerialTransport(port="/dev/ttyUSB0", baudrate=9600, parity="N").build(5.0)

    _, kwargs = client.call_args
    assert client.call_args[0][0] == "/dev/ttyUSB0"
    assert kwargs["framer"] is FramerType.RTU
    assert kwargs["baudrate"] == 9600
    assert kwargs["bytesize"] == 8
    assert kwargs["parity"] == "N"
    assert kwargs["stopbits"] == 2


def test_serial_support_declares_pyserial():
    """pymodbus does not pull pyserial in, and fails at runtime without it."""
    import json

    from conftest import COMPONENT

    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert any(r.startswith("pyserial") for r in manifest["requirements"])


def test_transport_is_chosen_by_the_entry_type():
    from rec_temovex.transport import (
        SerialTransport,
        TcpTransport,
        transport_from_config,
    )

    tcp = transport_from_config({"type": "tcp", "host": "10.0.0.5", "port": 502})
    assert isinstance(tcp, TcpTransport)
    assert str(tcp) == "10.0.0.5:502"

    serial = transport_from_config(
        {"type": "serial", "serial_port": "/dev/ttyUSB0", "baudrate": 19200}
    )
    assert isinstance(serial, SerialTransport)
    assert serial.baudrate == 19200
    assert "19200" in str(serial)

    # An entry written before serial support existed has no type at all.
    legacy = transport_from_config({"host": "10.0.0.5"})
    assert isinstance(legacy, TcpTransport)
    assert legacy.port == 502


def test_the_baud_rate_default_matches_its_options():
    """A select selector type-checks before it looks at the options.

    An int default against string options makes the serial form reject itself
    on submit, before the step handler is ever reached — and the only way out
    is to open the dropdown and pick the same value again.
    """
    from rec_temovex.const import (
        BAUDRATE_OPTIONS,
        DEFAULT_BAUDRATE,
        DEFAULT_BAUDRATE_OPTION,
    )

    assert all(isinstance(option, str) for option in BAUDRATE_OPTIONS)
    assert isinstance(DEFAULT_BAUDRATE_OPTION, str)
    assert DEFAULT_BAUDRATE_OPTION in BAUDRATE_OPTIONS
    assert int(DEFAULT_BAUDRATE_OPTION) == DEFAULT_BAUDRATE


def test_a_typed_in_baud_rate_is_validated_not_crashed_on():
    """The box accepts free text, so anything can arrive."""
    import pytest
    from rec_temovex.transport import coerce_baudrate

    assert coerce_baudrate("9600") == 9600
    assert coerce_baudrate(19200) == 19200
    assert coerce_baudrate("57 600") == 57600

    for junk in ("", "9600 bps", "fast", "-9600", "0", "99999999"):
        with pytest.raises(ValueError):
            coerce_baudrate(junk)


def test_stove_kitchen_and_fire_are_decoded_but_not_selectable():
    """Regin distinguishes the flow from the function, and so do we.

    The digital input list calls them "Stove mode", "Kitchen mode" and "Fire
    Alarm"; the fan mode register calls the same values "Stove flow", "Kitchen
    flow" and "Fire flow", while every value that means the same thing in both
    lists is worded identically. Writing the register therefore selects an
    unbalanced flow without the timer, the blocked bypass or the dampers.
    """
    from rec_temovex.const import FAN_MODES, SELECTABLE_FAN_MODES

    for mode in ("stove", "kitchen", "fire"):
        assert mode in FAN_MODES, mode
        assert mode not in SELECTABLE_FAN_MODES, mode

    # And the ordinary flow levels still are selectable.
    for mode in ("off", "auto", "eco", "boost", "max"):
        assert mode in SELECTABLE_FAN_MODES, mode

    # Fixed minimum is redundant beside ECO, which starts there and is allowed
    # to rise. It still decodes.
    assert "min" in FAN_MODES
    assert "min" not in SELECTABLE_FAN_MODES


def test_every_reportable_fan_mode_has_a_translation():
    """A mode the unit can enter from its panel still has to display."""
    import json

    from conftest import COMPONENT
    from rec_temovex.const import FAN_MODES

    for name in ("strings.json", "translations/en.json", "translations/sv.json"):
        data = json.loads((COMPONENT / name).read_text())
        states = data["entity"]["climate"]["ventilation"]["state_attributes"][
            "fan_mode"
        ]["state"]
        for mode in FAN_MODES:
            if mode == "off":
                continue
            assert mode in states, f"{mode} missing from {name}"


def test_away_offset_is_whole_degrees():
    """SetPAdj arrives unscaled: the 2 C default read back as 0.2 when scaled."""
    from rec_temovex.registers import REGISTER_BY_KEY

    reg = REGISTER_BY_KEY["away_setpoint_offset"]
    assert reg.decode(2) == 2
    assert reg.encode(3) == 3


def test_icons_refer_to_entities_that_exist():
    """hassfest rejects icon translations for keys no entity uses."""
    import json
    import re

    from conftest import COMPONENT

    icons = json.loads((COMPONENT / "icons.json").read_text())["entity"]
    strings = json.loads((COMPONENT / "strings.json").read_text())["entity"]
    for domain, entries in icons.items():
        for key, entry in entries.items():
            assert key in strings[domain], f"{domain}.{key} has an icon but no entity"
            found = [entry["default"]] if "default" in entry else []
            found += entry.get("state", {}).values()
            for attr_icons in entry.get("state_attributes", {}).values():
                found += attr_icons.get("state", {}).values()
                if "default" in attr_icons:
                    found.append(attr_icons["default"])
            assert found, f"{domain}.{key} has an icon entry without icons"
            for icon in found:
                assert re.fullmatch(r"mdi:[a-z0-9-]+", icon), icon
