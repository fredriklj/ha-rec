"""How to reach the unit: Modbus TCP, or RS485 straight off a serial port.

The unit itself only speaks RS485. Whether that arrives as TCP from a gateway
or a daemon, or as a serial device on the Home Assistant host, is a property of
the installation rather than of the protocol, so it is kept apart from the rest
of the client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from pymodbus import FramerType
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.client.base import ModbusBaseClient

from .const import (
    CONF_BAUDRATE,
    CONF_PARITY,
    CONF_SERIAL_PORT,
    DEFAULT_BAUDRATE,
    DEFAULT_PARITY,
    DEFAULT_PORT,
    TRANSPORT_SERIAL,
)


@dataclass(frozen=True, kw_only=True)
class TcpTransport:
    """A Modbus TCP endpoint — a gateway, or a daemon bridging to RS485."""

    host: str
    port: int = DEFAULT_PORT
    kind: ClassVar[str] = "tcp"

    def build(self, timeout: float) -> ModbusBaseClient:
        """Create the pymodbus client."""
        return AsyncModbusTcpClient(
            self.host,
            port=self.port,
            timeout=timeout,
            name=f"rec_temovex@{self}",
        )

    def __str__(self) -> str:
        """Describe the endpoint for logs and error messages."""
        return f"{self.host}:{self.port}"


@dataclass(frozen=True, kw_only=True)
class SerialTransport:
    """An RS485 adapter on the Home Assistant host, speaking Modbus RTU."""

    port: str
    baudrate: int = DEFAULT_BAUDRATE
    parity: str = DEFAULT_PARITY
    kind: ClassVar[str] = "serial"

    @property
    def stopbits(self) -> int:
        """Stop bits, which follow from the parity rather than being chosen.

        A Modbus RTU character is eleven bits. With a parity bit that leaves
        one stop bit; without one, two. The unit's own manual says the same:
        "None medfor 2 stoppbitar, Odd och Even medfor 1 stoppbit".
        """
        return 2 if self.parity == "N" else 1

    def build(self, timeout: float) -> ModbusBaseClient:
        """Create the pymodbus client."""
        return AsyncModbusSerialClient(
            self.port,
            framer=FramerType.RTU,
            baudrate=self.baudrate,
            bytesize=8,
            parity=self.parity,
            stopbits=self.stopbits,
            timeout=timeout,
            name=f"rec_temovex@{self}",
        )

    def __str__(self) -> str:
        """Describe the port for logs and error messages."""
        return f"{self.port} ({self.baudrate} {self.parity}{self.stopbits})"


# A plain alias rather than a "type" statement: the protocol layer is tested
# on its own, and there is no reason to require the Python version Home
# Assistant happens to need in order to do that.
Transport = TcpTransport | SerialTransport


def coerce_baudrate(value: str | int) -> int:
    """Turn a baud rate from the form into an int, or say why it is not one.

    The baud rate selector accepts a typed-in value, so anything can arrive:
    "57 600", "9600 bps", or an empty box. Raising ValueError here lets the
    config flow show a field error rather than an unknown-error traceback.
    """
    if isinstance(value, int):
        rate = value
    else:
        text = str(value).strip().replace(" ", "")
        if not text.isdigit():
            raise ValueError(f"{value!r} is not a baud rate")
        rate = int(text)
    if not 50 <= rate <= 1_000_000:
        raise ValueError(f"{rate} is out of range for a baud rate")
    return rate


def transport_from_config(data: dict[str, Any]) -> Transport:
    """Build the transport a config entry describes.

    The keys are spelled out rather than imported from Home Assistant, so this
    module stays free of it along with the rest of the protocol layer. They are
    the same strings as CONF_TYPE, CONF_HOST and CONF_PORT.
    """
    if data.get("type") == TRANSPORT_SERIAL:
        return SerialTransport(
            port=data[CONF_SERIAL_PORT],
            baudrate=coerce_baudrate(data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)),
            parity=data.get(CONF_PARITY, DEFAULT_PARITY),
        )
    return TcpTransport(
        host=data["host"],
        port=data.get("port", DEFAULT_PORT),
    )
