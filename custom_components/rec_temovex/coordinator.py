"""Polling coordinator for a Rec Temovex unit."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .modbus import RecTemovexClient, RecTemovexError

_LOGGER = logging.getLogger(__name__)

type RecTemovexConfigEntry = ConfigEntry[RecTemovexCoordinator]


class RecTemovexCoordinator(DataUpdateCoordinator[dict[str, float | int | bool]]):
    """Fetch the whole register map in a handful of block reads."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: RecTemovexConfigEntry,
        client: RecTemovexClient,
        scan_interval: int,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, float | int | bool]:
        """Read all registers once."""
        try:
            return await self.client.async_read_all()
        except RecTemovexError as err:
            raise UpdateFailed(str(err)) from err

    async def async_write(self, key: str, value: float | bool) -> None:
        """Write a register and reflect it in the UI straight away.

        The written value is applied optimistically rather than polled back.
        Requesting a refresh here would fire immediately on the first write
        after a quiet period, which on a slow RS485 bus tends to read back the
        old value and then sit on it until the next scheduled poll — worse than
        showing what was just written. The scheduled poll, whose timer this
        resets, remains the source of truth and corrects the value if the unit
        disagreed.

        The value is only applied for a register the last poll actually
        returned, so a write cannot conjure a key that is otherwise absent and
        make an unavailable entity flicker into life for one cycle.
        """
        try:
            await self.client.async_write(key, value)
        except RecTemovexError as err:
            # Surfaces as a toast on the user's action rather than as a silent
            # failure in the log.
            raise HomeAssistantError(str(err)) from err

        if self.data is not None and key in self.data:
            self.async_set_updated_data({**self.data, key: value})
