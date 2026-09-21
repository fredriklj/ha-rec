"""Climate platform for Rec Temovex."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DOMAIN,
    FAN_MODE_AUTO,
    FAN_MODE_OFF,
    FAN_MODES,
    MAX_TEMP,
    MIN_TEMP,
    PRESET_AWAY,
    PRESET_HOME,
    ROOM_TEMPERATURE_SOURCES,
    SELECTABLE_FAN_MODES,
    SETPOINT_KEY,
    STATE_BYPASS,
    STATE_RECYCLING,
    TEMP_STEP,
)
from .coordinator import RecTemovexConfigEntry, RecTemovexCoordinator
from .entity import RecTemovexEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RecTemovexConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the climate entity."""
    coordinator = entry.runtime_data
    if SETPOINT_KEY in coordinator.client.register_keys:
        async_add_entities([RecTemovexClimate(coordinator, entry)])


class RecTemovexClimate(RecTemovexEntity, ClimateEntity):
    """The ventilation unit as a climate entity.

    The integration assumes cascade room control, so this is the room
    temperature against the room setpoint. The controller works out a supply
    air setpoint from that on its own, bounded by the min and max supply
    setpoint, which are exposed separately as diagnostics.

    The unit has no user selectable heat/cool mode — it regulates to the
    setpoint and heats, recovers or bypasses as needed — so the HVAC mode is
    AUTO when it is running and OFF when it is not. FAN_ONLY would be a lie:
    the unit does heat. Which of those it is doing right now is reported
    through hvac_action, and how hard it is ventilating through fan_mode.

    Off is both an HVAC mode and a fan mode. They write the same register, so
    they cannot disagree: the fan mode card and the thermostat card each get a
    way to stop the unit, and either one restarts it.
    """

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = TEMP_STEP
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_preset_modes = [PRESET_HOME, PRESET_AWAY]
    _attr_translation_key = "ventilation"
    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.OFF]
    _attr_fan_modes = list(SELECTABLE_FAN_MODES)

    def __init__(
        self, coordinator: RecTemovexCoordinator, entry: RecTemovexConfigEntry
    ) -> None:
        """Initialise the climate entity."""
        super().__init__(coordinator, entry, SETPOINT_KEY, unique_key="climate")

        configured = set(coordinator.client.register_keys)
        self._has_fan_mode = "fan_mode" in configured
        self._has_preset = "away" in configured

        features = ClimateEntityFeature.TARGET_TEMPERATURE
        if self._has_fan_mode:
            features |= (
                ClimateEntityFeature.FAN_MODE
                | ClimateEntityFeature.TURN_ON
                | ClimateEntityFeature.TURN_OFF
            )
        else:
            self._attr_hvac_modes = [HVACMode.AUTO]
        if self._has_preset:
            features |= ClimateEntityFeature.PRESET_MODE
        self._attr_supported_features = features

        # Remembered so that turning the unit back on restores what was running
        # rather than guessing — starting from what the first poll found, or a
        # unit found running in boost comes back in auto after a stop.
        self._last_running_mode = FAN_MODE_AUTO
        self._remember_running_mode()

    @property
    def current_temperature(self) -> float | None:
        """Room temperature, the value the cascade regulates on.

        Which register carries it depends on where the unit's room sensor is
        wired, so the sources are tried in order. A reading of exactly zero
        means that source is not in use — a heated room is never 0.0 — rather
        than a room at freezing point.
        """
        for key in ROOM_TEMPERATURE_SOURCES:
            value = self._data.get(key)
            if value is None:
                continue
            if float(value) != 0.0:
                return float(value)
        return None

    @property
    def target_temperature(self) -> float | None:
        """Room setpoint."""
        value = self._value
        return float(value) if value is not None else None

    @property
    def fan_mode(self) -> str | None:
        """Current operating mode, off included.

        Every value the register can hold is decoded, including the three that
        cannot be selected, so a unit put into stove or kitchen flow from its
        own panel reports what it is actually doing.
        """
        raw = self._data.get("fan_mode")
        if raw is None or not 0 <= int(raw) < len(FAN_MODES):
            return None
        return FAN_MODES[int(raw)]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Remember the last mode the fans actually ran in."""
        self._remember_running_mode()
        super()._handle_coordinator_update()

    def _remember_running_mode(self) -> None:
        """Note the current mode if it is one to come back to."""
        mode = self.fan_mode
        # Only remember a mode that can be set again and that runs the fans;
        # coming back from stove flow has to land somewhere the unit accepts,
        # and turning the unit on must not select off.
        if mode in SELECTABLE_FAN_MODES and mode != FAN_MODE_OFF:
            self._last_running_mode = mode

    @property
    def _is_stopped(self) -> bool | None:
        """Whether the unit is switched off."""
        raw = self._data.get("fan_mode")
        if raw is not None:
            return int(raw) == FAN_MODES.index(FAN_MODE_OFF)
        flags = [
            self._data[key]
            for key in ("supply_fan_running", "exhaust_fan_running")
            if key in self._data
        ]
        if not flags:
            return None
        return not any(bool(flag) for flag in flags)

    @property
    def _fans_standing_still(self) -> bool:
        """Both fans reported stopped, whatever the mode register says.

        A unit held by an external stop, a timer or an alarm is not ventilating
        even though its mode is not off, and that is what hvac_action is for.
        """
        flags = [
            self._data[key]
            for key in ("supply_fan_running", "exhaust_fan_running")
            if key in self._data
        ]
        return bool(flags) and not any(bool(flag) for flag in flags)

    @property
    def hvac_mode(self) -> HVACMode:
        """OFF when the unit is switched off, otherwise AUTO."""
        if self._has_fan_mode and self._is_stopped:
            return HVACMode.OFF
        return HVACMode.AUTO

    @property
    def hvac_action(self) -> HVACAction | str | None:
        """What the unit is doing, in its own four states.

        Heating, cooling, defrosting and off use Home Assistant's own values,
        so dashboards colour them as usual. Recycling heat and an open bypass
        have no counterpart in Home Assistant's list, so they are reported as
        "recycling" and "bypass" and translated through strings.json. Anything
        that only understands the standard values will show those two raw.

        The precedence is the controller's: cooling beats an open bypass, which
        beats heating, and recovering heat is what it does the rest of the time.
        """
        data = self._data
        if self._is_stopped or self._fans_standing_still:
            return HVACAction.OFF
        if data.get("defrosting"):
            return HVACAction.DEFROSTING

        action: HVACAction | str = STATE_RECYCLING
        if float(data.get("heating_valve") or 0) > 0:
            action = HVACAction.HEATING
        if float(data.get("bypass_output") or 0) > 0:
            action = STATE_BYPASS
        if float(data.get("cooling_valve") or 0) > 0:
            action = HVACAction.COOLING
        return action

    @property
    def preset_mode(self) -> str | None:
        """Home or away."""
        away = self._data.get("away")
        if away is None:
            return None
        return PRESET_AWAY if away else PRESET_HOME

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new room setpoint."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        clamped = min(max(float(temperature), MIN_TEMP), MAX_TEMP)
        await self.coordinator.async_write(SETPOINT_KEY, clamped)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set a new operating mode."""
        if fan_mode not in SELECTABLE_FAN_MODES:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="fan_mode_not_selectable",
                translation_placeholders={"mode": fan_mode},
            )
        await self.coordinator.async_write("fan_mode", FAN_MODES.index(fan_mode))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Stop the fans, or start them again."""
        if not self._has_fan_mode:
            return
        if hvac_mode is HVACMode.OFF:
            await self.coordinator.async_write(
                "fan_mode", FAN_MODES.index(FAN_MODE_OFF)
            )
        else:
            await self.async_set_fan_mode(self._last_running_mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Switch between home and away."""
        await self.coordinator.async_write("away", preset_mode == PRESET_AWAY)
