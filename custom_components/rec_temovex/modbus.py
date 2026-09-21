"""Async protocol layer between the Rec Temovex unit and Home Assistant.

Nothing in here knows about Home Assistant. It speaks Modbus on one side and
plain Python values keyed by register name on the other, which keeps this
module liftable into a standalone PyPI package later on.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pymodbus.client.mixin import ModbusClientMixin
from pymodbus.exceptions import ModbusException

from .const import DEFAULT_TIMEOUT, MESSAGE_GAP
from .registers import (
    BIT_KINDS,
    VERIFIED_REGISTERS,
    DataType,
    ReadBlock,
    RegisterDef,
    RegisterKind,
    plan_blocks,
)
from .transport import Transport

_LOGGER = logging.getLogger(__name__)

# pymodbus 3.10 removed BinaryPayloadDecoder in favour of these converters.
_DATATYPE: dict[DataType, Any] = {
    DataType.INT16: ModbusClientMixin.DATATYPE.INT16,
    DataType.UINT16: ModbusClientMixin.DATATYPE.UINT16,
    DataType.INT32: ModbusClientMixin.DATATYPE.INT32,
    DataType.UINT32: ModbusClientMixin.DATATYPE.UINT32,
}


# Modbus exception codes that mean "this address or function does not exist on
# this device". Only these justify giving up on a register.
_PERMANENT_EXCEPTIONS = frozenset(
    {
        0x01,  # illegal function
        0x02,  # illegal data address
        0x03,  # illegal data value
    }
)
# Everything else — device busy, memory parity, gateway path unavailable, and
# above all 0x0B "gateway target device failed to respond" — says the request
# was fine but the answer did not arrive. A TCP-to-RS485 gateway emits these
# routinely on a loaded bus, and treating one as proof that a register does not
# exist is how an integration quietly loses half its entities.


class RecTemovexError(Exception):
    """Base error for this integration."""


class RecTemovexConnectionError(RecTemovexError):
    """The unit could not be reached."""


class RecTemovexProtocolError(RecTemovexError):
    """The unit answered with a Modbus exception response."""

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        """Record whether the unit said "never" or merely "not now"."""
        super().__init__(message)
        self.permanent = permanent


class RecTemovexClient:
    """Serialised Modbus client for one ventilation unit, over any transport."""

    def __init__(
        self,
        transport: Transport,
        device_id: int,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        registers: tuple[RegisterDef, ...] = VERIFIED_REGISTERS,
    ) -> None:
        """Create a client. No I/O happens until the first read."""
        self._transport = transport
        self._device_id = device_id
        self._registers = {r.key: r for r in registers}
        # The starting plan. async_read_all refines it in place if the unit
        # turns out not to have some of these addresses; the original is kept
        # so the client can never end up with nothing to ask for.
        self._initial_blocks = plan_blocks(registers)
        self._blocks = list(self._initial_blocks)
        self._dead_keys: set[str] = set()
        # pymodbus is explicitly not safe against concurrent calls on one
        # client, and a shared RS485 bus behind the gateway is even less so.
        self._lock = asyncio.Lock()
        self._client = transport.build(timeout)

    @property
    def transport(self) -> Transport:
        """How this client reaches the unit."""
        return self._transport

    @property
    def blocks(self) -> list[ReadBlock]:
        """Read blocks this client will issue per update cycle."""
        return self._blocks

    @property
    def register_keys(self) -> tuple[str, ...]:
        """Keys this client is configured to read.

        Entities are built from this, not from what a given poll happened to
        return, so a truncated response does not silently delete entities.
        """
        return tuple(key for key in self._registers if key not in self._dead_keys)

    @property
    def dead_keys(self) -> tuple[str, ...]:
        """Registers this unit reported it does not have."""
        return tuple(sorted(self._dead_keys))

    @property
    def connected(self) -> bool:
        """Whether the socket is currently up."""
        return self._client.connected

    async def _async_connect_locked(self) -> None:
        if self._client.connected:
            return
        try:
            connected = await self._client.connect()
        except (TimeoutError, ModbusException, OSError) as err:
            raise RecTemovexConnectionError(
                f"Could not connect to {self._transport}: {err}"
            ) from err
        if not connected:
            raise RecTemovexConnectionError(f"Could not connect to {self._transport}")

    def close(self) -> None:
        """Close the connection."""
        self._client.close()

    async def async_read_all(self) -> dict[str, float | int | bool]:
        """Read every configured register and return decoded values.

        A connection problem fails the whole poll — there is nothing sensible
        to report when the unit is unreachable.

        An *illegal address* is different, and is what makes gap bridging safe.
        Such a block is re-planned into tighter blocks and retried within the
        same poll; a register that is illegal on its own is dropped from the
        plan. So the plan starts optimistic and converges on the coarsest one
        the unit actually accepts.

        Every other exception code — busy, gateway timeout — means "not now",
        not "never". Those leave the plan alone and simply cost this poll's
        value for that block, because a gateway having a bad second must not
        permanently delete an entity.
        """
        values: dict[str, float | int | bool] = {}

        async with self._lock:
            await self._async_connect_locked()

            queue = list(self._blocks)
            plan: list[ReadBlock] = []
            rejected = 0

            first = True
            while queue:
                block = queue.pop(0)
                if not first:
                    # The Corrigo requires a gap between messages: 3.5 character
                    # times, or 14 when it shares the RS485 line with another
                    # controller. The gateway may or may not enforce it.
                    await asyncio.sleep(MESSAGE_GAP)
                first = False
                try:
                    raw = await self._async_read_block(block)
                except RecTemovexProtocolError as err:
                    if not err.permanent:
                        _LOGGER.debug("Skipping %s this poll: %s", block, err)
                        plan.append(block)
                        rejected += 1
                        continue

                    finer = self._refine(block)
                    if finer is None and not block.keys:
                        continue
                    if finer is None:
                        _LOGGER.warning(
                            "Unit does not have register %s (%s %s), dropping it: %s",
                            block.keys[0],
                            block.kind,
                            block.address,
                            err,
                        )
                        self._dead_keys.add(block.keys[0])
                        continue
                    _LOGGER.debug(
                        "Unit rejected %s %s+%s; retrying as %s smaller reads",
                        block.kind,
                        block.address,
                        block.count,
                        len(finer),
                    )
                    queue[0:0] = finer
                    continue

                plan.append(block)
                values.update(self._decode_block(block, raw))

            # Committed only once the whole poll got through; a connection
            # error part way leaves the previous plan in place. Never commit an
            # empty plan — a device that answers nothing must still be asked
            # again next time, or the integration would go quiet for good.
            self._blocks = plan or self._initial_blocks

        if not values and rejected:
            raise RecTemovexProtocolError(
                "Unit rejected every read this poll", permanent=False
            )
        if not values and self._registers:
            raise RecTemovexProtocolError(
                "Unit has none of the registers in the map — check the device ID",
                permanent=True,
            )

        return values

    def _refine(self, block: ReadBlock) -> list[ReadBlock] | None:
        """Split a rejected block into smaller ones, or None if it is a single.

        First drop any bridged gaps, since reading an unmapped address is the
        likeliest cause. Only if the block was already contiguous does it fall
        back to one request per register.
        """
        registers = [self._registers[key] for key in block.keys]
        if len(registers) <= 1:
            return None

        tighter = plan_blocks(registers, max_gap=0)
        if len(tighter) > 1:
            return tighter

        return [
            ReadBlock(reg.kind, reg.address, reg.count, (reg.key,)) for reg in registers
        ]

    async def _async_read_block(self, block: ReadBlock) -> list[int] | list[bool]:
        """Issue one Modbus read. Caller holds the lock."""
        try:
            if block.kind is RegisterKind.COIL:
                result = await self._client.read_coils(
                    block.address, count=block.count, device_id=self._device_id
                )
            elif block.kind is RegisterKind.DISCRETE:
                result = await self._client.read_discrete_inputs(
                    block.address, count=block.count, device_id=self._device_id
                )
            elif block.kind is RegisterKind.INPUT:
                result = await self._client.read_input_registers(
                    block.address, count=block.count, device_id=self._device_id
                )
            else:
                result = await self._client.read_holding_registers(
                    block.address, count=block.count, device_id=self._device_id
                )
        except (TimeoutError, ModbusException, OSError) as err:
            raise RecTemovexConnectionError(
                f"Reading {block.kind} {block.address}+{block.count} failed: {err}"
            ) from err

        if result.isError():
            code = getattr(result, "exception_code", None)
            raise RecTemovexProtocolError(
                f"Unit returned an error for {block.kind} "
                f"{block.address}+{block.count}: {result}",
                permanent=code in _PERMANENT_EXCEPTIONS,
            )

        if block.kind in BIT_KINDS:
            # Bit reads pad the list out to a byte boundary.
            return list(result.bits[: block.count])
        return list(result.registers)

    def _decode_block(
        self, block: ReadBlock, raw: list[int] | list[bool]
    ) -> dict[str, float | int | bool]:
        """Slice a block's raw payload into individual register values."""
        values: dict[str, float | int | bool] = {}
        for key in block.keys:
            reg = self._registers[key]
            start = reg.address - block.address
            chunk = raw[start : start + reg.count]
            if len(chunk) < reg.count:
                # A gateway that answers with fewer registers than asked for.
                # Worth noticing, since the value silently goes missing.
                _LOGGER.warning(
                    "Short read: %s %s+%s returned %s registers, %s needs %s",
                    block.kind,
                    block.address,
                    block.count,
                    len(raw),
                    key,
                    reg.count,
                )
                continue
            if reg.kind in BIT_KINDS or reg.data_type is DataType.BOOL:
                values[key] = bool(chunk[0])
                continue
            decoded = ModbusClientMixin.convert_from_registers(
                chunk, _DATATYPE[reg.data_type]
            )
            values[key] = reg.decode(decoded)  # type: ignore[arg-type]
        return values

    async def async_write(self, key: str, value: float | bool) -> None:
        """Write a single register or coil by its map key."""
        reg = self._registers.get(key)
        if reg is None or not reg.writable:
            raise RecTemovexError(f"Register {key!r} is not writable")

        async with self._lock:
            await self._async_connect_locked()
            try:
                if reg.kind is RegisterKind.COIL:
                    result = await self._client.write_coil(
                        reg.address, bool(value), device_id=self._device_id
                    )
                elif reg.data_type is DataType.BOOL:
                    # A flag living in a holding register, not a coil.
                    result = await self._client.write_register(
                        reg.address, int(bool(value)), device_id=self._device_id
                    )
                else:
                    # Always via convert_to_registers: it is what turns a
                    # negative value into its two's complement word. Handing a
                    # raw negative int to write_register raises struct.error.
                    payload = ModbusClientMixin.convert_to_registers(
                        reg.encode(float(value)), _DATATYPE[reg.data_type]
                    )
                    if len(payload) == 1:
                        result = await self._client.write_register(
                            reg.address, payload[0], device_id=self._device_id
                        )
                    else:
                        result = await self._client.write_registers(
                            reg.address, payload, device_id=self._device_id
                        )
            except (TimeoutError, ModbusException, OSError) as err:
                raise RecTemovexConnectionError(f"Writing {key} failed: {err}") from err

        if result.isError():
            raise RecTemovexProtocolError(f"Unit rejected write to {key}: {result}")
