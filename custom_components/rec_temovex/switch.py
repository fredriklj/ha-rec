"""Switch platform for Rec Temovex."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RecTemovexConfigEntry, RecTemovexCoordinator
from .entity import RecTemovexEntity
from .registers import REGISTER_BY_KEY


@dataclass(frozen=True, kw_only=True)
class RecTemovexSwitchDescription(SwitchEntityDescription):
    """Describes a Rec Temovex switch."""

    register_key: str


SWITCHES: tuple[RecTemovexSwitchDescription, ...] = (
    RecTemovexSwitchDescription(
        key="heating_mode",
        register_key="heating_mode",
        translation_key="heating_mode",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
    ),
    RecTemovexSwitchDescription(
        key="preheat_electric_mode",
        register_key="preheat_electric_mode",
        translation_key="preheat_electric_mode",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    RecTemovexSwitchDescription(
        key="preheat_damper_mode",
        register_key="preheat_damper_mode",
        translation_key="preheat_damper_mode",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    RecTemovexSwitchDescription(
        key="cooling_mode",
        register_key="cooling_mode",
        translation_key="cooling_mode",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
    ),
    RecTemovexSwitchDescription(
        key="bypass_mode",
        register_key="bypass_mode",
        translation_key="bypass_mode",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
    ),
    RecTemovexSwitchDescription(
        key="night_cooling_enabled",
        register_key="night_cooling_enabled",
        translation_key="night_cooling_enabled",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
    ),
    RecTemovexSwitchDescription(
        key="cool_recycling_enabled",
        register_key="cool_recycling_enabled",
        translation_key="cool_recycling_enabled",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RecTemovexConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""
    coordinator = entry.runtime_data
    configured = set(coordinator.client.register_keys)
    async_add_entities(
        RecTemovexSwitch(coordinator, entry, description)
        for description in SWITCHES
        if description.register_key in configured
    )


class RecTemovexSwitch(RecTemovexEntity, SwitchEntity):
    """A coil, or a Corrigo mode register, driven as a switch.

    The mode registers are three-state: 0 off, 1 manual, 2 auto. Switching one
    on puts it back in auto, which is what the controller ships as. Manual
    still reads as on, because the function is running — it is just running on
    a fixed output rather than on the controller's own regulation.
    """

    entity_description: RecTemovexSwitchDescription

    def __init__(
        self,
        coordinator: RecTemovexCoordinator,
        entry: RecTemovexConfigEntry,
        description: RecTemovexSwitchDescription,
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, entry, description.register_key)
        self.entity_description = description
        self._register = REGISTER_BY_KEY[description.register_key]

    @property
    def is_on(self) -> bool | None:
        """True unless the register holds its off value."""
        value = self._value
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        return int(value) != self._register.off_value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Surface the raw mode, so manual is distinguishable from auto."""
        value = self._value
        if isinstance(value, bool) or value is None:
            return None
        return {"mode": int(value)}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Write the on value."""
        await self.coordinator.async_write(self._key, self._register.on_value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Write the off value."""
        await self.coordinator.async_write(self._key, self._register.off_value)
