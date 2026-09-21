"""Fixtures for tests that run the integration inside Home Assistant.

The Modbus client is the seam: everything above it — config flow, coordinator,
entities — is the real code, and the client is replaced by a mock answering
with decoded values, as ``RecTemovexClient.async_read_all`` does.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rec_temovex.const import CONF_DEVICE_ID, DOMAIN
from custom_components.rec_temovex.registers import REGISTERS

# A running unit in cascade room control on a mild day: recovering heat, no
# valve open, fans at normal flow, a water coil.
UNIT_DATA: dict[str, float | int | bool] = {
    "outdoor_temperature": 12.3,
    "supply_temperature": 19.8,
    "extract_temperature": 22.1,
    "exhaust_temperature": 14.1,
    "room_temperature": 21.4,
    "frost_protection_temperature": 25.0,
    "room_unit_temperature": 0.0,
    "desired_temperature": 21.0,
    "supply_fan_speed": 46,
    "exhaust_fan_speed": 46,
    "heating_valve": 0,
    "cooling_valve": 0,
    "preheat_valve": 0,
    "bypass_output": 0.0,
    "filter_time_left": 2100,
    "regulation_mode": 2,
    "supply_setpoint": 19.5,
    "exhaust_setpoint": 21.0,
    "room_setpoint": 21.0,
    "away_setpoint_offset": 2,
    "supply_setpoint_max": 28.0,
    "supply_setpoint_min": 15.0,
    "supply_fan_min": 30,
    "exhaust_fan_min": 30,
    "supply_fan_normal": 46,
    "exhaust_fan_normal": 46,
    "supply_fan_forced": 70,
    "exhaust_fan_forced": 70,
    "supply_fan_max": 100,
    "exhaust_fan_max": 100,
    "supply_fan_kitchen": 80,
    "exhaust_fan_kitchen": 20,
    "supply_fan_stove": 80,
    "exhaust_fan_stove": 20,
    "supply_fan_night_cooling": 70,
    "exhaust_fan_night_cooling": 70,
    "fan_mode": 1,
    "heating_mode": 2,
    "bypass_mode": 2,
    "preheat_setpoint": -5.0,
    "preheat_electric_mode": 2,
    "preheat_outdoor_limit": -10.0,
    "preheat_damper_mode": 0,
    "heat_type": 0,
    "cooling_mode": 0,
    "away": False,
    "night_cooling_enabled": False,
    "cool_recycling_enabled": False,
    "supply_fan_running": True,
    "exhaust_fan_running": True,
    "defrosting": False,
    "frost_risk": False,
    "supply_fan_alarm": False,
    "exhaust_fan_alarm": False,
    "electric_heater_alarm": False,
    "filter_guard_alarm": False,
    "supply_fan_manual_alarm": False,
    "exhaust_fan_manual_alarm": False,
    "filter_alarm": False,
    "fire_alarm": False,
}

TCP_INPUT: dict[str, Any] = {
    "host": "192.0.2.10",
    "port": 502,
    CONF_DEVICE_ID: 1,
    "name": "Rec Temovex",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture
def unit_data() -> dict[str, float | int | bool]:
    """A fresh copy per test, so tests can bend it."""
    return dict(UNIT_DATA)


@pytest.fixture
def mock_client(
    unit_data: dict[str, float | int | bool],
) -> Generator[MagicMock]:
    """Replace the Modbus client wherever the integration constructs one."""
    client = MagicMock()
    client.async_read_all = AsyncMock(side_effect=lambda: dict(unit_data))
    client.async_write = AsyncMock()
    client.register_keys = tuple(r.key for r in REGISTERS if r.verified)
    client.close = MagicMock()
    with (
        patch("custom_components.rec_temovex.RecTemovexClient", return_value=client),
        patch(
            "custom_components.rec_temovex.config_flow.RecTemovexClient",
            return_value=client,
        ),
    ):
        yield client


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A TCP entry, as the config flow creates it."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Rec Temovex",
        data={**TCP_INPUT, "type": "tcp"},
        unique_id="192.0.2.10:502:1",
    )
