"""Number platform for Rec Temovex.

The unit's settings — the flow each operating mode runs at, the cascade limits,
the preheater's thresholds — are writable holding registers. They belong here
rather than as read-only sensors: a setting you can see but not change is a
setting you have to walk over to the unit to adjust.

The fire alarm flows are the exception and are not exposed at all. They decide
how the unit evacuates smoke, and nothing on a dashboard should be able to
change that.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RecTemovexConfigEntry, RecTemovexCoordinator
from .entity import RecTemovexEntity


@dataclass(frozen=True, kw_only=True)
class RecTemovexNumberDescription(NumberEntityDescription):
    """Describes a Rec Temovex number."""

    register_key: str


def _flow(key: str, **kwargs) -> RecTemovexNumberDescription:
    """Build a fan speed setting, as a percentage of full speed."""
    return RecTemovexNumberDescription(
        key=key,
        register_key=key,
        translation_key=key,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        **kwargs,
    )


def _temperature(
    key: str, low: float, high: float, step: float = 0.5, **kwargs
) -> RecTemovexNumberDescription:
    """Build a temperature setting."""
    return RecTemovexNumberDescription(
        key=key,
        register_key=key,
        translation_key=key,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=low,
        native_max_value=high,
        native_step=step,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        **kwargs,
    )


NUMBERS: tuple[RecTemovexNumberDescription, ...] = (
    # Fan speeds, supply and extract, for each operating mode.
    _flow("supply_fan_min"),
    _flow("exhaust_fan_min"),
    _flow("supply_fan_normal"),
    _flow("exhaust_fan_normal"),
    _flow("supply_fan_forced"),
    _flow("exhaust_fan_forced"),
    _flow("supply_fan_max"),
    _flow("exhaust_fan_max"),
    _flow("supply_fan_kitchen", entity_registry_enabled_default=False),
    _flow("exhaust_fan_kitchen", entity_registry_enabled_default=False),
    _flow("supply_fan_stove", entity_registry_enabled_default=False),
    _flow("exhaust_fan_stove", entity_registry_enabled_default=False),
    _flow("supply_fan_night_cooling", entity_registry_enabled_default=False),
    _flow("exhaust_fan_night_cooling", entity_registry_enabled_default=False),
    # The bounds the cascade may compute a supply setpoint within.
    _temperature("supply_setpoint_max", 0, 60),
    _temperature("supply_setpoint_min", 0, 60),
    # How far the setpoint moves when away.
    _temperature("away_setpoint_offset", -10, 10, step=1),
    # The preheater's own thresholds. Few units have one, so disabled at first.
    _temperature("preheat_setpoint", -20, 20, entity_registry_enabled_default=False),
    _temperature(
        "preheat_outdoor_limit", -40, 20, entity_registry_enabled_default=False
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RecTemovexConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the settings this unit's map covers."""
    coordinator = entry.runtime_data
    configured = set(coordinator.client.register_keys)
    async_add_entities(
        RecTemovexNumber(coordinator, entry, description)
        for description in NUMBERS
        if description.register_key in configured
    )


class RecTemovexNumber(RecTemovexEntity, NumberEntity):
    """A writable register exposed as a settable value."""

    entity_description: RecTemovexNumberDescription

    def __init__(
        self,
        coordinator: RecTemovexCoordinator,
        entry: RecTemovexConfigEntry,
        description: RecTemovexNumberDescription,
    ) -> None:
        """Initialise the number."""
        super().__init__(coordinator, entry, description.register_key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return the current setting."""
        value = self._value
        return None if isinstance(value, bool) or value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Write a new setting."""
        await self.coordinator.async_write(self._key, value)
