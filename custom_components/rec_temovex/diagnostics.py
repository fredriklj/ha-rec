"""Diagnostics support for Rec Temovex."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import RecTemovexConfigEntry
from .registers import REGISTERS

TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RecTemovexConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        # The kind only: str(transport) carries the host, which is redacted
        # out of entry.data a few lines up.
        "transport": coordinator.client.transport.kind,
        "connected": coordinator.client.connected,
        "dead_registers": list(coordinator.client.dead_keys),
        "read_blocks": [
            {
                "kind": str(block.kind),
                "address": block.address,
                "count": block.count,
                "keys": list(block.keys),
            }
            for block in coordinator.client.blocks
        ],
        "values": dict(coordinator.data or {}),
        "register_map": [
            {
                "key": reg.key,
                "kind": str(reg.kind),
                "address": reg.address,
                "data_type": str(reg.data_type),
                "scale": reg.scale,
                "writable": reg.writable,
                "verified": reg.verified,
                "note": reg.note,
            }
            for reg in REGISTERS
        ],
    }
