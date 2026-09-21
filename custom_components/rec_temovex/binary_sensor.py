"""Binary sensor platform for Rec Temovex.

Categories follow one rule: what the unit is doing right now is a plain entity,
anything that affects or may come to affect how it runs — alarms, the filter,
frost protection — is diagnostic.

Most of these are Regin "input status registers" — Modbus discrete inputs —
read straight off the controller. Heating, cooling and bypass are the
exception: the unit reports those as valve positions in percent, so the
percentage is the sensor and this is the "is it doing anything" view of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ELECTRIC_HEATING, WATER_HEATING
from .coordinator import RecTemovexConfigEntry, RecTemovexCoordinator
from .entity import RecTemovexEntity, for_heat_type


@dataclass(frozen=True, kw_only=True)
class RecTemovexBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Rec Temovex binary sensor."""

    register_key: str
    # A value strictly above this counts as on, for the percentage registers.
    threshold: float = 0.0
    # Only created when the unit's heater is one of these types.
    heat_types: tuple[int, ...] | None = None


BINARY_SENSORS: tuple[RecTemovexBinarySensorDescription, ...] = (
    RecTemovexBinarySensorDescription(
        key="heating_active",
        register_key="heating_valve",
        translation_key="heating_active",
        # Duplicates the valve and the operating state; kept for automations.
        entity_registry_enabled_default=False,
    ),
    RecTemovexBinarySensorDescription(
        key="cooling_active",
        register_key="cooling_valve",
        translation_key="cooling_active",
        # Duplicates the valve and the operating state; kept for automations.
        entity_registry_enabled_default=False,
    ),
    RecTemovexBinarySensorDescription(
        key="bypass_active",
        register_key="bypass_output",
        translation_key="bypass_active",
        device_class=BinarySensorDeviceClass.OPENING,
        # Duplicates the valve and the operating state; kept for automations.
        entity_registry_enabled_default=False,
    ),
    RecTemovexBinarySensorDescription(
        key="supply_fan_running",
        register_key="supply_fan_running",
        translation_key="supply_fan_running",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    RecTemovexBinarySensorDescription(
        key="exhaust_fan_running",
        register_key="exhaust_fan_running",
        translation_key="exhaust_fan_running",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    RecTemovexBinarySensorDescription(
        key="defrosting",
        register_key="defrosting",
        translation_key="defrosting",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    RecTemovexBinarySensorDescription(
        key="filter_alarm",
        register_key="filter_alarm",
        translation_key="filter_alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RecTemovexBinarySensorDescription(
        key="filter_guard_alarm",
        register_key="filter_guard_alarm",
        translation_key="filter_guard_alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RecTemovexBinarySensorDescription(
        key="frost_risk",
        register_key="frost_risk",
        translation_key="frost_risk",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        heat_types=WATER_HEATING,
    ),
    RecTemovexBinarySensorDescription(
        key="electric_heater_alarm",
        register_key="electric_heater_alarm",
        translation_key="electric_heater_alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        heat_types=ELECTRIC_HEATING,
    ),
    RecTemovexBinarySensorDescription(
        key="supply_fan_alarm",
        register_key="supply_fan_alarm",
        translation_key="supply_fan_alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RecTemovexBinarySensorDescription(
        key="exhaust_fan_alarm",
        register_key="exhaust_fan_alarm",
        translation_key="exhaust_fan_alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RecTemovexBinarySensorDescription(
        key="supply_fan_manual_alarm",
        register_key="supply_fan_manual_alarm",
        translation_key="supply_fan_manual_alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RecTemovexBinarySensorDescription(
        key="exhaust_fan_manual_alarm",
        register_key="exhaust_fan_manual_alarm",
        translation_key="exhaust_fan_manual_alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RecTemovexBinarySensorDescription(
        key="fire_alarm",
        register_key="fire_alarm",
        translation_key="fire_alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RecTemovexConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    configured = set(coordinator.client.register_keys)
    async_add_entities(
        RecTemovexBinarySensor(
            coordinator, entry, for_heat_type(coordinator, description)
        )
        for description in BINARY_SENSORS
        if description.register_key in configured
    )


class RecTemovexBinarySensor(RecTemovexEntity, BinarySensorEntity):
    """A register exposed as an on/off state."""

    entity_description: RecTemovexBinarySensorDescription

    def __init__(
        self,
        coordinator: RecTemovexCoordinator,
        entry: RecTemovexConfigEntry,
        description: RecTemovexBinarySensorDescription,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(
            coordinator,
            entry,
            description.register_key,
            unique_key=description.key,
        )
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """True when the register is set, or above its threshold."""
        value = self._value
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        return value > self.entity_description.threshold
