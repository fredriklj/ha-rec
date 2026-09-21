#!/usr/bin/env python3
"""Dump a Rec Temovex unit's Modbus registers so the map can be filled in.

This runs outside Home Assistant. Point it at the same Modbus TCP endpoint the
integration uses and it walks the address space, printing every register that
answers, alongside plausible interpretations of the raw value.

    python scripts/scan_registers.py 192.168.1.10 --device-id 1

Temperatures are the easy ones to spot: a raw value in the 150-250 range that
tracks the weather is almost certainly tenths of a degree. Watch a register
over time with --watch to tell a setpoint from a measurement.

Nothing here writes to the unit.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import sys
import time

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

KINDS = ("holding", "input", "coil")


@dataclass
class Reading:
    """One register and what it answered with."""

    kind: str
    address: int
    raw: int | bool

    def interpretations(self) -> str:
        """Plausible meanings of the raw value."""
        if isinstance(self.raw, bool):
            return "on" if self.raw else "off"

        signed = self.raw - 0x10000 if self.raw > 0x7FFF else self.raw
        parts = [f"raw={self.raw}"]
        if signed != self.raw:
            parts.append(f"signed={signed}")
        if -1000 <= signed <= 1000:
            parts.append(f"/10={signed / 10:.1f}")
        return "  ".join(parts)


async def _read_one(
    client: AsyncModbusTcpClient, kind: str, address: int, device_id: int
) -> Reading | None:
    """Read a single address, returning None if the unit refuses it."""
    try:
        if kind == "coil":
            result = await client.read_coils(address, count=1, device_id=device_id)
        elif kind == "input":
            result = await client.read_input_registers(
                address, count=1, device_id=device_id
            )
        else:
            result = await client.read_holding_registers(
                address, count=1, device_id=device_id
            )
    except (TimeoutError, ModbusException, OSError) as err:
        # A dropped connection mid-scan should not throw away everything found
        # so far.
        print(f"  {address:>5}  (read failed: {err})")
        return None

    if result.isError():
        return None

    raw = bool(result.bits[0]) if kind == "coil" else int(result.registers[0])
    return Reading(kind, address, raw)


async def scan(args: argparse.Namespace) -> int:
    """Walk the address space and print what answers."""
    client = AsyncModbusTcpClient(args.host, port=args.port, timeout=args.timeout)
    if not await client.connect():
        print(f"Could not connect to {args.host}:{args.port}", file=sys.stderr)
        return 1

    try:
        for kind in args.kinds:
            print(f"\n=== {kind} registers {args.start}..{args.end} ===")
            found = 0
            for address in range(args.start, args.end + 1):
                reading = await _read_one(client, kind, address, args.device_id)
                # Pause on every address, not only the ones that answered: an
                # unanswered read is a timeout, which is when the bus is under
                # the most strain.
                await asyncio.sleep(args.delay)
                if reading is None:
                    continue
                found += 1
                print(f"  {address:>5}  {reading.interpretations()}")
            if not found:
                print("  (nothing answered)")
    finally:
        client.close()

    return 0


async def watch(args: argparse.Namespace) -> int:
    """Poll one address repeatedly so changing values stand out."""
    client = AsyncModbusTcpClient(args.host, port=args.port, timeout=args.timeout)
    if not await client.connect():
        print(f"Could not connect to {args.host}:{args.port}", file=sys.stderr)
        return 1

    kind = args.kinds[0]
    print(f"Watching {kind} {args.watch}. Ctrl-C to stop.")
    try:
        while True:
            reading = await _read_one(client, kind, args.watch, args.device_id)
            stamp = time.strftime("%H:%M:%S")
            if reading is None:
                print(f"{stamp}  (no answer)")
            else:
                print(f"{stamp}  {reading.interpretations()}")
            await asyncio.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
    return 0


def main() -> int:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="Modbus TCP host")
    parser.add_argument("--port", type=int, default=502)
    parser.add_argument("--device-id", type=int, default=1)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=64)
    parser.add_argument(
        "--kinds",
        nargs="+",
        choices=KINDS,
        default=list(KINDS),
        help="Which address spaces to scan",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.05,
        help="Pause between reads, to be kind to the RS485 bus",
    )
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument(
        "--watch",
        type=int,
        help="Instead of scanning, poll this one address repeatedly",
    )
    parser.add_argument("--interval", type=float, default=2.0)

    args = parser.parse_args()
    runner = watch if args.watch is not None else scan
    return asyncio.run(runner(args))


if __name__ == "__main__":
    raise SystemExit(main())
