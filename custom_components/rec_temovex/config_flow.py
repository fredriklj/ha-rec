"""Config flow for Rec Temovex."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_TYPE,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .const import (
    BAUDRATE_OPTIONS,
    CONF_BAUDRATE,
    CONF_DEVICE_ID,
    CONF_PARITY,
    CONF_SERIAL_PORT,
    DEFAULT_BAUDRATE_OPTION,
    DEFAULT_DEVICE_ID,
    DEFAULT_NAME,
    DEFAULT_PARITY,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PARITIES,
    TRANSPORT_SERIAL,
    TRANSPORT_TCP,
)
from .coordinator import RecTemovexConfigEntry
from .identify import identity_problems
from .modbus import (
    RecTemovexClient,
    RecTemovexConnectionError,
    RecTemovexProtocolError,
)
from .transport import coerce_baudrate, transport_from_config

_LOGGER = logging.getLogger(__name__)

# A plain box rather than a bare Range, which the frontend draws as a slider.
_DEVICE_ID = NumberSelector(
    NumberSelectorConfig(min=0, max=247, step=1, mode=NumberSelectorMode.BOX)
)

STEP_TCP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_DEVICE_ID, default=DEFAULT_DEVICE_ID): _DEVICE_ID,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
)

STEP_SERIAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERIAL_PORT): cv.string,
        # The default has to be a string: a select selector type-checks its
        # value before looking at the options, so an int default makes the
        # form reject itself before this step is ever entered.
        vol.Optional(CONF_BAUDRATE, default=DEFAULT_BAUDRATE_OPTION): SelectSelector(
            SelectSelectorConfig(
                options=list(BAUDRATE_OPTIONS),
                mode=SelectSelectorMode.DROPDOWN,
                custom_value=True,
            )
        ),
        vol.Optional(CONF_PARITY, default=DEFAULT_PARITY): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=parity, label=parity) for parity in PARITIES
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(CONF_DEVICE_ID, default=DEFAULT_DEVICE_ID): _DEVICE_ID,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
)


class RecTemovexConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI configuration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask how the unit is reached.

        The unit only speaks RS485. This is about what sits between it and
        Home Assistant: a gateway or daemon offering Modbus TCP, or an RS485
        adapter plugged into the host.
        """
        return self.async_show_menu(
            step_id="user", menu_options=[TRANSPORT_TCP, TRANSPORT_SERIAL]
        )

    async def async_step_tcp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a Modbus TCP endpoint."""
        return await self._async_step_transport(
            TRANSPORT_TCP, STEP_TCP_SCHEMA, user_input
        )

    async def async_step_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a serial RS485 adapter."""
        return await self._async_step_transport(
            TRANSPORT_SERIAL, STEP_SERIAL_SCHEMA, user_input
        )

    async def _async_step_transport(
        self,
        transport: str,
        schema: vol.Schema,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        """Validate either kind of connection and create the entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**user_input, CONF_TYPE: transport}
            # The selectors hand back strings and floats, and the baud rate box
            # accepts anything typed into it.
            data[CONF_DEVICE_ID] = int(data[CONF_DEVICE_ID])
            if CONF_BAUDRATE in data:
                try:
                    data[CONF_BAUDRATE] = coerce_baudrate(data[CONF_BAUDRATE])
                except ValueError:
                    return self.async_show_form(
                        step_id=transport,
                        data_schema=self.add_suggested_values_to_schema(
                            schema, user_input
                        ),
                        errors={CONF_BAUDRATE: "invalid_baudrate"},
                    )

            await self.async_set_unique_id(_unique_id(data))
            self._abort_if_unique_id_configured()

            client = RecTemovexClient(transport_from_config(data), data[CONF_DEVICE_ID])
            try:
                values = await client.async_read_all()
            except RecTemovexConnectionError:
                errors["base"] = "cannot_connect"
            except RecTemovexProtocolError as err:
                # Something that speaks Modbus answered. If it says the
                # addresses do not exist, the device ID is almost certainly
                # wrong; if it merely failed to answer, that is a bad moment on
                # the bus and worth retrying rather than a misdiagnosis.
                errors["base"] = "invalid_device" if err.permanent else "cannot_connect"
            else:
                # Anything at the given address answers register reads, so a
                # clean read proves nothing. The values have to look like a
                # ventilation unit's before this becomes an entry.
                if problems := identity_problems(values):
                    _LOGGER.warning(
                        "Device %s does not look like a Rec Temovex: %s",
                        data[CONF_DEVICE_ID],
                        "; ".join(str(problem) for problem in problems),
                    )
                    errors["base"] = "not_rec_temovex"
                else:
                    return self.async_create_entry(title=data[CONF_NAME], data=data)
            finally:
                client.close()

        return self.async_show_form(
            step_id=transport,
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: RecTemovexConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return RecTemovexOptionsFlow()


def _unique_id(data: dict[str, Any]) -> str:
    """Identify one connection.

    A serial port is opened exclusively, so a second entry on the same device
    path could never load even for a different unit on the same bus — the port
    itself is the identity. A TCP endpoint can be shared, so there the device
    ID is part of it.
    """
    if data[CONF_TYPE] == TRANSPORT_SERIAL:
        return data[CONF_SERIAL_PORT]
    return f"{data[CONF_HOST]}:{data[CONF_PORT]}:{data[CONF_DEVICE_ID]}"


class RecTemovexOptionsFlow(OptionsFlow):
    """Let the user tune the poll interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
                }
            ),
        )
