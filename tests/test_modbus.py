"""Tests for the protocol layer, against a fake Modbus client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rec_temovex.modbus import (
    RecTemovexClient,
    RecTemovexProtocolError,
)
from rec_temovex.registers import (
    DataType,
    RegisterDef,
    RegisterKind,
)
from rec_temovex.transport import TcpTransport

REGISTERS = (
    RegisterDef(
        key="setpoint",
        kind=RegisterKind.HOLDING,
        address=1,
        scale=0.1,
        precision=1,
        writable=True,
        verified=True,
    ),
    RegisterDef(
        key="mode",
        kind=RegisterKind.HOLDING,
        address=2,
        data_type=DataType.UINT16,
        writable=True,
        verified=True,
    ),
    RegisterDef(
        key="supply",
        kind=RegisterKind.INPUT,
        address=0,
        scale=0.1,
        precision=1,
        verified=True,
    ),
    RegisterDef(
        key="away",
        kind=RegisterKind.COIL,
        address=6,
        data_type=DataType.BOOL,
        writable=True,
        verified=True,
    ),
)


def _ok(*, registers=None, bits=None):
    result = MagicMock()
    result.isError.return_value = False
    result.registers = registers or []
    result.bits = bits or []
    return result


ILLEGAL_ADDRESS = 0x02
GATEWAY_NO_RESPONSE = 0x0B


def _error(code=ILLEGAL_ADDRESS):
    """A Modbus exception response. Illegal address unless told otherwise."""
    result = MagicMock()
    result.isError.return_value = True
    result.exception_code = code
    return result


@pytest.fixture
def client():
    with patch.object(TcpTransport, "build") as build:
        inner = build.return_value
        inner.connected = True
        inner.connect = AsyncMock(return_value=True)
        inner.read_holding_registers = AsyncMock()
        inner.read_input_registers = AsyncMock()
        inner.read_coils = AsyncMock()
        inner.write_register = AsyncMock(return_value=_ok())
        inner.write_coil = AsyncMock(return_value=_ok())
        transport = TcpTransport(host="host", port=502)
        yield RecTemovexClient(transport, 1, registers=REGISTERS), inner


async def test_read_all_decodes_every_register(client):
    api, inner = client
    inner.read_holding_registers.return_value = _ok(registers=[215, 1])
    inner.read_input_registers.return_value = _ok(registers=[188])
    inner.read_coils.return_value = _ok(bits=[True, False, False, False])

    values = await api.async_read_all()

    assert values == {
        "setpoint": pytest.approx(21.5),
        "mode": 1,
        "supply": pytest.approx(18.8),
        "away": True,
    }


async def test_holding_registers_are_read_in_one_request(client):
    api, inner = client
    inner.read_holding_registers.return_value = _ok(registers=[215, 1])
    inner.read_input_registers.return_value = _ok(registers=[188])
    inner.read_coils.return_value = _ok(bits=[True])

    await api.async_read_all()

    # Two adjacent holding registers, one round trip.
    assert inner.read_holding_registers.await_count == 1
    inner.read_holding_registers.assert_awaited_once_with(1, count=2, device_id=1)


async def test_padded_coil_bits_are_trimmed(client):
    api, inner = client
    inner.read_holding_registers.return_value = _ok(registers=[215, 1])
    inner.read_input_registers.return_value = _ok(registers=[188])
    # read_coils pads to a whole byte; only the first bit is ours.
    inner.read_coils.return_value = _ok(bits=[False] + [True] * 7)

    values = await api.async_read_all()

    assert values["away"] is False


async def test_a_wholly_unsupported_block_drops_only_its_own_values(client):
    api, inner = client
    # Neither the block nor its individual registers are supported.
    inner.read_holding_registers.return_value = _error()
    inner.read_input_registers.return_value = _ok(registers=[188])
    inner.read_coils.return_value = _ok(bits=[True])

    values = await api.async_read_all()

    assert "setpoint" not in values
    assert "mode" not in values
    # The rest of the poll still lands.
    assert values["supply"] == pytest.approx(18.8)
    assert values["away"] is True


async def test_write_scales_the_value_back_to_raw(client):
    api, inner = client

    await api.async_write("setpoint", 21.5)

    inner.write_register.assert_awaited_once_with(1, 215, device_id=1)


async def test_write_coil_uses_the_coil_call(client):
    api, inner = client

    await api.async_write("away", True)

    inner.write_coil.assert_awaited_once_with(6, True, device_id=1)


async def test_writing_a_read_only_register_is_refused(client):
    api, _ = client

    with pytest.raises(Exception, match="not writable"):
        await api.async_write("supply", 1.0)


async def test_negative_value_is_written_as_twos_complement(client):
    api, inner = client

    await api.async_write("setpoint", -3.5)

    # -35 would raise struct.error if handed to write_register raw.
    inner.write_register.assert_awaited_once_with(1, 65501, device_id=1)


async def test_rejected_block_falls_back_to_single_reads(client):
    api, inner = client
    inner.read_input_registers.return_value = _ok(registers=[188])
    inner.read_coils.return_value = _ok(bits=[True])
    # The two-register holding block is refused; register 1 is fine on its own,
    # register 2 is genuinely unsupported.
    inner.read_holding_registers.side_effect = [
        _error(),
        _ok(registers=[215]),
        _error(),
    ]

    values = await api.async_read_all()

    assert values["setpoint"] == pytest.approx(21.5)
    assert "mode" not in values
    assert values["supply"] == pytest.approx(18.8)


async def test_a_dead_register_is_not_retried_every_poll(client):
    api, inner = client
    inner.read_input_registers.return_value = _ok(registers=[188])
    inner.read_coils.return_value = _ok(bits=[True])
    inner.read_holding_registers.side_effect = [
        _error(),
        _ok(registers=[215]),
        _error(),
    ]
    await api.async_read_all()

    inner.read_holding_registers.side_effect = None
    inner.read_holding_registers.return_value = _ok(registers=[216])
    inner.read_holding_registers.reset_mock()

    values = await api.async_read_all()

    # Only the register that works is asked for again.
    assert inner.read_holding_registers.await_count == 1
    inner.read_holding_registers.assert_awaited_once_with(1, count=1, device_id=1)
    assert values["setpoint"] == pytest.approx(21.6)


async def test_a_single_rejected_register_is_dropped_not_fatal(client):
    api, inner = client
    inner.read_holding_registers.return_value = _ok(registers=[215, 1])
    inner.read_coils.return_value = _ok(bits=[True])
    # The input block holds exactly one register, so there is nothing to refine.
    inner.read_input_registers.return_value = _error()

    values = await api.async_read_all()

    assert "supply" not in values
    assert api.dead_keys == ("supply",)
    assert values["setpoint"] == pytest.approx(21.5)


async def test_a_unit_without_any_of_the_registers_raises(client):
    api, inner = client
    inner.read_holding_registers.return_value = _error()
    inner.read_input_registers.return_value = _error()
    inner.read_coils.return_value = _error()

    # This is what a wrong device ID looks like, and the config flow reports it
    # as such rather than creating an entry with no entities.
    with pytest.raises(RecTemovexProtocolError, match="check the device ID"):
        await api.async_read_all()


async def test_a_transient_gateway_error_does_not_drop_the_register(client):
    api, inner = client
    inner.read_input_registers.return_value = _ok(registers=[188])
    inner.read_coils.return_value = _ok(bits=[True])
    # 0x0B: the gateway could not get an answer off the bus in time. This says
    # nothing about whether the register exists.
    inner.read_holding_registers.return_value = _error(GATEWAY_NO_RESPONSE)

    first = await api.async_read_all()
    assert "setpoint" not in first

    inner.read_holding_registers.return_value = _ok(registers=[215, 1])
    inner.read_holding_registers.reset_mock()

    second = await api.async_read_all()

    # Still asked for, still as one block: nothing was refined or given up on.
    inner.read_holding_registers.assert_awaited_once_with(1, count=2, device_id=1)
    assert second["setpoint"] == pytest.approx(21.5)
    assert second["mode"] == 1


async def test_a_wholly_transient_poll_fails_but_keeps_the_plan(client):
    api, inner = client
    inner.read_holding_registers.return_value = _error(GATEWAY_NO_RESPONSE)
    inner.read_input_registers.return_value = _error(GATEWAY_NO_RESPONSE)
    inner.read_coils.return_value = _error(GATEWAY_NO_RESPONSE)

    with pytest.raises(RecTemovexProtocolError, match="this poll"):
        await api.async_read_all()

    assert api.dead_keys == ()

    # A bad second must not silence the client for good.
    inner.read_holding_registers.return_value = _ok(registers=[215, 1])
    inner.read_input_registers.return_value = _ok(registers=[188])
    inner.read_coils.return_value = _ok(bits=[True])

    values = await api.async_read_all()

    assert set(values) == {"setpoint", "mode", "supply", "away"}


async def test_refining_drops_bridged_gaps_before_going_register_by_register():
    from rec_temovex.modbus import RecTemovexClient
    from rec_temovex.registers import ReadBlock

    # Two pairs of adjacent registers with an unmapped gap bridged between them.
    regs = tuple(
        RegisterDef(key=f"r{a}", kind=RegisterKind.INPUT, address=a, verified=True)
        for a in (0, 1, 6, 7)
    )
    api = RecTemovexClient(TcpTransport(host="host", port=502), 3, registers=regs)

    (block,) = api.blocks
    assert (block.address, block.count) == (0, 8)

    finer = api._refine(block)

    # The gap is dropped first; single reads are the last resort, not the first.
    assert [(b.address, b.count) for b in finer] == [(0, 2), (6, 2)]
    assert api._refine(finer[0]) == [
        ReadBlock(RegisterKind.INPUT, 0, 1, ("r0",)),
        ReadBlock(RegisterKind.INPUT, 1, 1, ("r1",)),
    ]
    assert api._refine(ReadBlock(RegisterKind.INPUT, 0, 1, ("r0",))) is None


def test_the_real_map_is_read_in_a_handful_of_requests():
    from rec_temovex.registers import VERIFIED_REGISTERS, plan_blocks

    blocks = plan_blocks(VERIFIED_REGISTERS)

    # Four address spaces and nearly forty values, in single-figure requests.
    assert len(blocks) <= 10, [(b.kind, b.address, b.count) for b in blocks]

    covered = sorted(k for b in blocks for k in b.keys)
    assert covered == sorted(r.key for r in VERIFIED_REGISTERS)

    # Nothing exceeds what the Corrigo will answer in one message.
    assert all(b.count <= 47 for b in blocks)


async def test_discrete_inputs_use_function_two():
    """Regin's "input status registers" are discrete inputs, not coils."""
    from rec_temovex.modbus import RecTemovexClient

    regs = (
        RegisterDef(
            key="filter",
            kind=RegisterKind.DISCRETE,
            address=73,
            data_type=DataType.BOOL,
            verified=True,
        ),
    )
    with patch.object(TcpTransport, "build") as build:
        inner = build.return_value
        inner.connected = True
        inner.connect = AsyncMock(return_value=True)
        inner.read_discrete_inputs = AsyncMock(return_value=_ok(bits=[True] * 8))
        inner.read_coils = AsyncMock()

        api = RecTemovexClient(TcpTransport(host="host", port=502), 3, registers=regs)
        values = await api.async_read_all()

    inner.read_discrete_inputs.assert_awaited_once_with(73, count=1, device_id=3)
    inner.read_coils.assert_not_awaited()
    assert values == {"filter": True}


def test_regin_addresses_are_recorded_one_higher():
    """Every note carries the Regin number, which is the address plus one."""
    import re

    from rec_temovex.registers import REGISTERS

    for reg in REGISTERS:
        match = re.search(r"Regin (\d+)", reg.note)
        assert match, f"{reg.key} does not cite its Regin number"
        assert int(match.group(1)) == reg.address + 1, reg.key


def test_temperatures_are_scaled_and_percentages_are_not():
    """Regin's scale factor of ten holds for temperatures, not percentages.

    A running unit settled this: at 46 % the fan reports 46 on its analogue
    output *and* 46 in its setpoint register. Scaling either one showed a fan
    running at 5 %, and made the airflow sensor read forced flow while the unit
    sat at normal. The bypass damper is the one percentage that does carry the
    factor.
    """
    from rec_temovex.registers import REGISTER_BY_KEY

    percentages = (
        "supply_fan_speed",
        "exhaust_fan_speed",
        "heating_valve",
        "cooling_valve",
        "supply_fan_min",
        "supply_fan_normal",
        "supply_fan_forced",
        "supply_fan_max",
        "exhaust_fan_normal",
    )
    for key in percentages:
        assert REGISTER_BY_KEY[key].scale == 1.0, key
        assert REGISTER_BY_KEY[key].decode(46) == 46, key

    temperatures = (
        "supply_temperature",
        "room_setpoint",
        "supply_setpoint_max",
        "preheat_outdoor_limit",
    )
    for key in temperatures:
        assert REGISTER_BY_KEY[key].scale == 0.1, key
        assert REGISTER_BY_KEY[key].decode(215) == pytest.approx(21.5), key

    assert REGISTER_BY_KEY["bypass_output"].scale == 0.1

    for key in ("fan_mode", "regulation_mode", "filter_time_left"):
        assert REGISTER_BY_KEY[key].scale == 1.0, key


def test_the_flow_state_compares_like_with_like():
    """The measured speed and the configured speeds must share a scale.

    They did not, and the sensor read forced flow on a unit sitting at normal.
    """
    from rec_temovex.registers import REGISTER_BY_KEY

    measured = REGISTER_BY_KEY["supply_fan_speed"].scale
    for key in ("supply_fan_min", "supply_fan_normal", "supply_fan_forced"):
        assert REGISTER_BY_KEY[key].scale == measured, key


def test_extract_and_exhaust_follow_the_wiring_not_the_regin_label():
    """REC wires J9 as uteluft, tilluft, frånluft, avluft.

    Regin's English labels for AI3 and AI4 are the other way round, so going
    by the label alone swaps the two sensors — which a real unit showed.
    """
    from rec_temovex.registers import REGISTER_BY_KEY

    assert REGISTER_BY_KEY["extract_temperature"].address == 15
    assert REGISTER_BY_KEY["exhaust_temperature"].address == 16


def test_efficiency_uses_the_air_drawn_from_the_rooms():
    """The temperature ratio needs extract air, not exhaust air.

    With the two swapped the sensor divides by the wrong span and reports
    nonsense. sensor.py imports Home Assistant, so the tuple is read from the
    source rather than imported.
    """
    import ast

    from conftest import COMPONENT
    from rec_temovex.const import ROOM_TEMPERATURE_SOURCES

    tree = ast.parse((COMPONENT / "sensor.py").read_text())
    inputs = next(
        ast.literal_eval(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "EFFICIENCY_INPUTS"
            for t in node.targets
        )
    )

    assert "extract_temperature" in inputs
    assert "exhaust_temperature" not in inputs
    assert ROOM_TEMPERATURE_SOURCES[0] == "room_temperature"


def test_every_fan_mode_the_controller_can_report_has_a_name():
    """Fan_Mode runs 0-8; a short list would raise IndexError on stove mode."""
    from rec_temovex.const import FAN_MODES

    assert len(FAN_MODES) == 9
    assert FAN_MODES[0] == "off"
    assert FAN_MODES[3] == "boost"
    assert len(set(FAN_MODES)) == len(FAN_MODES)
