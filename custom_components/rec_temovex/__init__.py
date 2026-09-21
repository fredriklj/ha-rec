"""The Rec Temovex integration."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICE_ID,
    DEFAULT_DEVICE_ID,
    DEFAULT_SCAN_INTERVAL,
    REGULATION_NAMES,
    REGULATION_ROOM,
)
from .coordinator import RecTemovexConfigEntry, RecTemovexCoordinator
from .modbus import RecTemovexClient
from .transport import transport_from_config

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: RecTemovexConfigEntry) -> bool:
    """Set up Rec Temovex from a config entry."""
    client = RecTemovexClient(
        transport_from_config(dict(entry.data)),
        entry.data.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID),
    )

    coordinator = RecTemovexCoordinator(
        hass,
        entry,
        client,
        entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    try:
        # Raises ConfigEntryNotReady itself when the first poll fails; the
        # client still has to be closed, or every retry leaks a socket and a
        # pymodbus reconnect task.
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        client.close()
        raise

    _warn_if_not_room_control(coordinator.data)

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RecTemovexConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.client.close()
    return unloaded


async def _async_update_listener(
    hass: HomeAssistant, entry: RecTemovexConfigEntry
) -> None:
    """Reload when the scan interval changes."""
    await hass.config_entries.async_reload(entry.entry_id)


def _warn_if_not_room_control(data: dict[str, float | int | bool]) -> None:
    """Say so if the unit is not set up the way this integration assumes.

    The climate entity shows room temperature against the room setpoint, which
    is only the temperature the unit is actually regulating in cascade room
    control. Everything else keeps working; the thermostat is the part that
    would mislead.
    """
    regulation = data.get("regulation_mode")
    if regulation is None or int(regulation) == REGULATION_ROOM:
        return

    _LOGGER.warning(
        "This unit is set to %s, but the integration assumes cascade room "
        "control. Sensors and switches are unaffected; the climate entity's "
        "temperature and setpoint will not be the ones the unit regulates on",
        REGULATION_NAMES.get(int(regulation), f"regulation mode {regulation}"),
    )
