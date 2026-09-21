"""The config flow, end to end against a mocked client."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rec_temovex.const import DOMAIN
from custom_components.rec_temovex.modbus import (
    RecTemovexConnectionError,
    RecTemovexProtocolError,
)

from .conftest import TCP_INPUT


async def _submit_tcp(hass: HomeAssistant, user_input=TCP_INPUT):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "tcp"}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def test_tcp_creates_entry(hass: HomeAssistant, mock_client: MagicMock):
    result = await _submit_tcp(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["type"] == "tcp"
    assert result["data"]["device_id"] == 1
    assert result["result"].unique_id == "192.0.2.10:502:1"
    mock_client.close.assert_called_once()


async def test_device_id_from_the_box_is_an_int(
    hass: HomeAssistant, mock_client: MagicMock
):
    """The number selector hands back a float."""
    result = await _submit_tcp(hass, {**TCP_INPUT, "device_id": 3.0})
    assert result["data"]["device_id"] == 3
    assert isinstance(result["data"]["device_id"], int)


async def test_unreachable(hass: HomeAssistant, mock_client: MagicMock):
    mock_client.async_read_all.side_effect = RecTemovexConnectionError("down")
    result = await _submit_tcp(hass)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_missing_registers(hass: HomeAssistant, mock_client: MagicMock):
    mock_client.async_read_all.side_effect = RecTemovexProtocolError(
        "illegal address", permanent=True
    )
    result = await _submit_tcp(hass)
    assert result["errors"] == {"base": "invalid_device"}


async def test_a_bad_moment_on_the_bus_is_not_a_wrong_device(
    hass: HomeAssistant, mock_client: MagicMock
):
    mock_client.async_read_all.side_effect = RecTemovexProtocolError("busy")
    result = await _submit_tcp(hass)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_another_device_is_refused(
    hass: HomeAssistant, mock_client: MagicMock, unit_data, caplog
):
    """What happened with the energy meter: every read works, nothing fits."""
    unit_data.update(
        outdoor_temperature=230.1,
        supply_temperature=229.8,
        extract_temperature=0.0,
        room_setpoint=0.0,
        supply_fan_normal=0,
        fan_mode=4999,
    )
    result = await _submit_tcp(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "not_rec_temovex"}
    assert "room_setpoint" in caplog.text
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_the_form_can_be_corrected_after_a_refusal(
    hass: HomeAssistant, mock_client: MagicMock, unit_data
):
    good = dict(unit_data)
    unit_data.update(room_setpoint=0.0, supply_fan_normal=0)
    result = await _submit_tcp(hass)
    assert result["errors"] == {"base": "not_rec_temovex"}

    unit_data.update(good)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**TCP_INPUT, "device_id": 2}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_same_endpoint_twice_aborts(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
):
    config_entry.add_to_hass(hass)
    result = await _submit_tcp(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_serial_rejects_a_nonsense_baud_rate(
    hass: HomeAssistant, mock_client: MagicMock
):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "serial"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"serial_port": "/dev/ttyUSB0", "baudrate": "fast", "parity": "N"},
    )
    assert result["errors"] == {"baudrate": "invalid_baudrate"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"serial_port": "/dev/ttyUSB0", "baudrate": "19200", "parity": "N"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["baudrate"] == 19200
    assert result["result"].unique_id == "/dev/ttyUSB0"


async def test_options_set_the_scan_interval(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {"scan_interval": 60}
