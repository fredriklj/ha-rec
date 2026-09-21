"""What the integration creates, and how the climate entity reads the unit."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rec_temovex.modbus import RecTemovexConnectionError


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entry_for(
    hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str
) -> er.RegistryEntry:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        platform, "rec_temovex", f"{entry.entry_id}_{key}"
    )
    assert entity_id, f"{platform}.{key} was not created"
    return registry.async_get(entity_id)


def _climate_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    return _entry_for(hass, entry, CLIMATE_DOMAIN, "climate").entity_id


async def _poll(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


# --- Setup and teardown -------------------------------------------------------


async def test_setup_and_unload(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
):
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    mock_client.close.assert_called()


async def test_unreachable_unit_retries_and_closes_the_client(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
):
    mock_client.async_read_all.side_effect = RecTemovexConnectionError("down")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_client.close.assert_called()


async def test_other_regulation_modes_are_warned_about(
    hass: HomeAssistant, mock_client, unit_data, config_entry, caplog
):
    unit_data["regulation_mode"] = 0
    await _setup(hass, config_entry)
    assert "assumes cascade room" in caplog.text


# --- Heater type -------------------------------------------------------------

WATER_ONLY = (
    ("sensor", "heating_valve"),
    ("sensor", "frost_protection_temperature"),
    ("binary_sensor", "frost_risk"),
)
ELECTRIC_ONLY = (
    ("sensor", "electric_heater"),
    ("binary_sensor", "electric_heater_alarm"),
)


@pytest.mark.parametrize(
    ("heat_type", "enabled", "disabled"),
    [
        (0, WATER_ONLY, ELECTRIC_ONLY),
        (2, WATER_ONLY, ELECTRIC_ONLY),
        (1, ELECTRIC_ONLY, WATER_ONLY),
    ],
)
async def test_the_other_heater_type_is_created_disabled(
    hass: HomeAssistant,
    mock_client,
    unit_data,
    config_entry,
    heat_type,
    enabled,
    disabled,
):
    unit_data["heat_type"] = heat_type
    await _setup(hass, config_entry)

    for platform, key in enabled:
        assert _entry_for(hass, config_entry, platform, key).disabled_by is None, key
    for platform, key in disabled:
        entity = _entry_for(hass, config_entry, platform, key)
        assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION, key


async def test_unknown_heater_type_enables_everything(
    hass: HomeAssistant, mock_client, unit_data, config_entry
):
    del unit_data["heat_type"]
    await _setup(hass, config_entry)

    for platform, key in (*WATER_ONLY, *ELECTRIC_ONLY):
        assert _entry_for(hass, config_entry, platform, key).disabled_by is None, key


async def test_heater_type_is_reported(hass, mock_client, unit_data, config_entry):
    unit_data["heat_type"] = 1
    await _setup(hass, config_entry)
    entity_id = _entry_for(hass, config_entry, "sensor", "heat_type").entity_id
    assert hass.states.get(entity_id).state == "electric"


async def test_preheat_entities_start_disabled(hass, mock_client, config_entry):
    await _setup(hass, config_entry)
    for platform, key in (
        ("sensor", "preheat_valve"),
        ("switch", "preheat_electric_mode"),
        ("switch", "preheat_damper_mode"),
        ("number", "preheat_setpoint"),
        ("number", "preheat_outdoor_limit"),
    ):
        entity = _entry_for(hass, config_entry, platform, key)
        assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION, key


# --- Climate: what the unit is doing -------------------------------------------


@pytest.mark.parametrize(
    ("changes", "action"),
    [
        ({}, "recycling"),
        ({"heating_valve": 35}, HVACAction.HEATING),
        ({"bypass_output": 100.0}, "bypass"),
        ({"cooling_valve": 20}, HVACAction.COOLING),
        # The controller's precedence: cooling over bypass over heating.
        ({"heating_valve": 35, "bypass_output": 40.0}, "bypass"),
        ({"bypass_output": 40.0, "cooling_valve": 20}, HVACAction.COOLING),
        ({"defrosting": True, "heating_valve": 35}, HVACAction.DEFROSTING),
        ({"fan_mode": 0}, HVACAction.OFF),
        ({"supply_fan_running": False, "exhaust_fan_running": False}, HVACAction.OFF),
    ],
)
async def test_hvac_action(
    hass: HomeAssistant, mock_client, unit_data, config_entry, changes, action
):
    unit_data.update(changes)
    await _setup(hass, config_entry)
    state = hass.states.get(_climate_id(hass, config_entry))
    assert state.attributes[ATTR_HVAC_ACTION] == action


async def test_room_temperature_falls_back_past_an_unused_source(
    hass: HomeAssistant, mock_client, unit_data, config_entry
):
    unit_data.update(room_temperature=0.0, room_unit_temperature=20.7)
    await _setup(hass, config_entry)
    state = hass.states.get(_climate_id(hass, config_entry))
    assert state.attributes["current_temperature"] == 20.7


# --- Climate: fan modes -------------------------------------------------------


async def test_fan_modes_offered(hass, mock_client, config_entry):
    await _setup(hass, config_entry)
    state = hass.states.get(_climate_id(hass, config_entry))
    assert state.attributes["fan_modes"] == ["off", "auto", "eco", "boost", "max"]
    assert state.attributes[ATTR_FAN_MODE] == "auto"


async def test_off_is_a_fan_mode(hass, mock_client, unit_data, config_entry):
    await _setup(hass, config_entry)
    climate = _climate_id(hass, config_entry)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {"entity_id": climate, ATTR_FAN_MODE: "off"},
        blocking=True,
    )
    mock_client.async_write.assert_awaited_with("fan_mode", 0)

    state = hass.states.get(climate)
    assert state.attributes[ATTR_FAN_MODE] == "off"
    assert state.state == HVACMode.OFF


async def test_turning_on_restores_the_last_running_mode(
    hass, mock_client, unit_data, config_entry
):
    unit_data["fan_mode"] = 3  # boost
    await _setup(hass, config_entry)
    climate = _climate_id(hass, config_entry)

    unit_data["fan_mode"] = 0
    await _poll(hass, config_entry)
    assert hass.states.get(climate).state == HVACMode.OFF

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {"entity_id": climate, ATTR_HVAC_MODE: HVACMode.AUTO},
        blocking=True,
    )
    mock_client.async_write.assert_awaited_with("fan_mode", 3)


async def test_stove_flow_is_reported_but_not_selectable(
    hass, mock_client, unit_data, config_entry
):
    unit_data["fan_mode"] = 5  # stove
    await _setup(hass, config_entry)
    climate = _climate_id(hass, config_entry)
    assert hass.states.get(climate).attributes[ATTR_FAN_MODE] == "stove"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_FAN_MODE,
            {"entity_id": climate, ATTR_FAN_MODE: "stove"},
            blocking=True,
        )
    mock_client.async_write.assert_not_awaited()


# --- Sensors ------------------------------------------------------------------


async def test_unused_room_unit_reads_unknown(
    hass, mock_client, unit_data, config_entry
):
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    entity = _entry_for(hass, config_entry, "sensor", "room_unit_temperature")
    # Disabled by default, so enable it and reload to see its state.
    registry.async_update_entity(entity.entity_id, disabled_by=None)
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity.entity_id).state == "unknown"


@pytest.mark.parametrize(
    ("speed", "expected"),
    [
        (0, "off"),
        (30, "min"),
        (40, "eco"),
        (46, "normal"),
        (60, "eco2"),
        (70, "forced"),
    ],
)
async def test_flow_state(hass, mock_client, unit_data, config_entry, speed, expected):
    unit_data["supply_fan_speed"] = speed
    await _setup(hass, config_entry)
    entity_id = _entry_for(hass, config_entry, "sensor", "flow_state").entity_id
    assert hass.states.get(entity_id).state == expected


async def test_efficiency(hass, mock_client, unit_data, config_entry):
    unit_data.update(
        outdoor_temperature=0.0, extract_temperature=20.0, supply_temperature=16.0
    )
    await _setup(hass, config_entry)
    entity_id = _entry_for(
        hass, config_entry, "sensor", "heat_recovery_efficiency"
    ).entity_id
    assert float(hass.states.get(entity_id).state) == 80.0


async def test_a_register_missing_from_a_poll_goes_unavailable(
    hass, mock_client, unit_data, config_entry
):
    await _setup(hass, config_entry)
    entity_id = _entry_for(hass, config_entry, "sensor", "supply_temperature").entity_id
    assert hass.states.get(entity_id).state == "19.8"

    del unit_data["supply_temperature"]
    await _poll(hass, config_entry)
    assert hass.states.get(entity_id).state == "unavailable"


# --- Writes -------------------------------------------------------------------


async def test_switch_writes_auto_and_off(hass, mock_client, config_entry):
    await _setup(hass, config_entry)
    entity_id = _entry_for(hass, config_entry, "switch", "cooling_mode").entity_id
    assert hass.states.get(entity_id).state == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    mock_client.async_write.assert_awaited_with("cooling_mode", 2)
    assert hass.states.get(entity_id).state == "on"


async def test_number_writes_the_value(hass, mock_client, config_entry):
    await _setup(hass, config_entry)
    entity_id = _entry_for(hass, config_entry, "number", "supply_fan_normal").entity_id
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": 52}, blocking=True
    )
    mock_client.async_write.assert_awaited_with("supply_fan_normal", 52)
    assert float(hass.states.get(entity_id).state) == 52


async def test_setpoint_is_clamped(hass, mock_client, config_entry):
    await _setup(hass, config_entry)
    climate = _climate_id(hass, config_entry)
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {"entity_id": climate, "temperature": 22.5},
        blocking=True,
    )
    mock_client.async_write.assert_awaited_with("room_setpoint", 22.5)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, "recycling"),
        ({"heating_valve": 35}, "heating"),
        ({"heating_valve": 35, "bypass_output": 40.0}, "bypass"),
        ({"bypass_output": 40.0, "cooling_valve": 20}, "cooling"),
        ({"defrosting": True}, "defrosting"),
        ({"fan_mode": 0}, "off"),
    ],
)
async def test_operating_state(
    hass, mock_client, unit_data, config_entry, changes, expected
):
    unit_data.update(changes)
    await _setup(hass, config_entry)
    entity_id = _entry_for(hass, config_entry, "sensor", "operating_state").entity_id
    assert hass.states.get(entity_id).state == expected


# --- Grouping -----------------------------------------------------------------


async def test_entity_categories(hass, mock_client, config_entry):
    """Now is a sensor, may-affect is diagnostic, settable is configuration.

    Which leaves the climate entity alone under controls.
    """
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, config_entry.entry_id)

    controls = [
        e.entity_id
        for e in entities
        if e.domain in ("climate", "switch", "number") and e.entity_category is None
    ]
    assert controls == [_climate_id(hass, config_entry)]

    for e in entities:
        if e.domain in ("switch", "number"):
            assert e.entity_category is EntityCategory.CONFIG, e.entity_id

    diagnostic = {"filter_alarm", "filter_guard_alarm", "frost_risk", "fire_alarm"}
    primary = {"supply_fan_running", "exhaust_fan_running", "defrosting"}
    for key in diagnostic:
        entity = _entry_for(hass, config_entry, "binary_sensor", key)
        assert entity.entity_category is EntityCategory.DIAGNOSTIC, key
    for key in primary:
        entity = _entry_for(hass, config_entry, "binary_sensor", key)
        assert entity.entity_category is None, key
