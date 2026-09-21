"""Sensor platform for Rec Temovex."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ELECTRIC_HEATING,
    FLOW_ECO,
    FLOW_ECO2,
    FLOW_FORCED,
    FLOW_MIN,
    FLOW_NORMAL,
    FLOW_OFF,
    FLOW_STATES,
    FLOW_TOLERANCE,
    HEAT_TYPES,
    OPERATING_STATES,
    STATE_BYPASS,
    STATE_COOLING,
    STATE_DEFROSTING,
    STATE_HEATING,
    STATE_OFF,
    STATE_RECYCLING,
    WATER_HEATING,
)
from .coordinator import RecTemovexConfigEntry, RecTemovexCoordinator
from .entity import RecTemovexEntity, for_heat_type

FLOW_INPUTS = ("supply_fan_speed", "supply_fan_min", "supply_fan_normal")

STATE_INPUTS = ("heating_valve", "cooling_valve", "bypass_output")

EFFICIENCY_INPUTS = ("supply_temperature", "extract_temperature", "outdoor_temperature")

# Below this indoor/outdoor difference the efficiency ratio is dominated by
# sensor noise, so it is reported as unknown rather than as a spike.
MIN_EFFICIENCY_SPAN = 3.0


@dataclass(frozen=True, kw_only=True)
class RecTemovexSensorDescription(SensorEntityDescription):
    """Describes a Rec Temovex sensor."""

    register_key: str
    # Some inputs are only populated when they are the configured source. An
    # unused one sits at exactly zero, which is not a temperature anybody's
    # house is at, so it is reported as unknown rather than as 0 degrees.
    zero_is_unused: bool = False
    # For outputs that are either doing something or not: the icon to show at
    # zero and above it. Icon translations can only match exact states, which
    # a percentage rarely is, so this is the one place the icon is computed.
    icon_idle: str | None = None
    icon_active: str | None = None
    # Only created when the unit's heater is one of these types.
    heat_types: tuple[int, ...] | None = None


def _temperature(key: str, **kwargs) -> RecTemovexSensorDescription:
    """Build a temperature sensor description."""
    return RecTemovexSensorDescription(
        key=key,
        register_key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        **kwargs,
    )


def _percentage(key: str, **kwargs) -> RecTemovexSensorDescription:
    """Build a percentage sensor description."""
    return RecTemovexSensorDescription(
        key=key,
        register_key=key,
        translation_key=key,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        **kwargs,
    )


SENSORS: tuple[RecTemovexSensorDescription, ...] = (
    _temperature("outdoor_temperature"),
    _temperature("supply_temperature"),
    _temperature("extract_temperature"),
    _temperature("exhaust_temperature"),
    _temperature("room_temperature", zero_is_unused=True),
    _temperature(
        "room_unit_temperature",
        zero_is_unused=True,
        entity_registry_enabled_default=False,
    ),
    # Frost protection guards a water coil; an electric heater has no sensor
    # there, so the input reads whatever an open circuit reads.
    _temperature(
        "frost_protection_temperature",
        entity_category=EntityCategory.DIAGNOSTIC,
        heat_types=WATER_HEATING,
    ),
    _temperature("desired_temperature"),
    _percentage("supply_fan_speed"),
    _percentage("exhaust_fan_speed"),
    # One output, named for what it drives.
    _percentage(
        "heating_valve",
        icon_idle="mdi:valve-closed",
        icon_active="mdi:valve-open",
        heat_types=WATER_HEATING,
    ),
    RecTemovexSensorDescription(
        key="electric_heater",
        register_key="heating_valve",
        translation_key="electric_heater",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon_idle="mdi:radiator-off",
        icon_active="mdi:radiator",
        heat_types=ELECTRIC_HEATING,
    ),
    _percentage(
        "cooling_valve", icon_idle="mdi:valve-closed", icon_active="mdi:valve-open"
    ),
    # Few units have a preheater, so its entities start out disabled.
    _percentage(
        "preheat_valve",
        icon_idle="mdi:valve-closed",
        icon_active="mdi:valve-open",
        entity_registry_enabled_default=False,
    ),
    _percentage("bypass_output"),
    RecTemovexSensorDescription(
        key="filter_time_left",
        register_key="filter_time_left",
        translation_key="filter_time_left",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RecTemovexConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for every register this unit's map covers."""
    coordinator = entry.runtime_data
    configured = set(coordinator.client.register_keys)

    entities: list[SensorEntity] = [
        RecTemovexSensor(coordinator, entry, for_heat_type(coordinator, description))
        for description in SENSORS
        if description.register_key in configured
    ]

    if "heat_type" in configured:
        entities.append(RecTemovexHeatTypeSensor(coordinator, entry))

    if all(key in configured for key in EFFICIENCY_INPUTS):
        entities.append(RecTemovexEfficiencySensor(coordinator, entry))

    if all(key in configured for key in FLOW_INPUTS):
        entities.append(RecTemovexFlowStateSensor(coordinator, entry))

    if all(key in configured for key in STATE_INPUTS):
        entities.append(RecTemovexOperatingStateSensor(coordinator, entry))

    async_add_entities(entities)


class RecTemovexSensor(RecTemovexEntity, SensorEntity):
    """A single register exposed as a sensor."""

    entity_description: RecTemovexSensorDescription

    def __init__(
        self,
        coordinator: RecTemovexCoordinator,
        entry: RecTemovexConfigEntry,
        description: RecTemovexSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(
            coordinator, entry, description.register_key, unique_key=description.key
        )
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        """Return the decoded register value."""
        value = self._value
        if isinstance(value, bool):
            return None
        if value == 0 and self.entity_description.zero_is_unused:
            return None
        return value

    @property
    def icon(self) -> str | None:
        """Open or closed valve, for outputs that describe one."""
        description = self.entity_description
        if description.icon_active is None:
            return super().icon
        value = self._value
        if isinstance(value, bool) or value is None:
            return description.icon_idle
        return description.icon_active if value > 0 else description.icon_idle


class RecTemovexEfficiencySensor(RecTemovexEntity, SensorEntity):
    """Temperature efficiency of the heat exchanger, computed from the air path.

    (supply - outdoor) / (extract - outdoor), the standard temperature ratio.
    It is only meaningful while the exchanger is actually recovering heat, so
    it reports unknown when indoor and outdoor air are close together.
    """

    _attr_translation_key = "heat_recovery_efficiency"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(
        self, coordinator: RecTemovexCoordinator, entry: RecTemovexConfigEntry
    ) -> None:
        """Initialise the computed sensor."""
        super().__init__(
            coordinator,
            entry,
            "supply_temperature",
            unique_key="heat_recovery_efficiency",
        )

    @property
    def native_value(self) -> float | None:
        """Compute the temperature ratio."""
        data = self._data
        try:
            supply = float(data["supply_temperature"])
            extract = float(data["extract_temperature"])
            outdoor = float(data["outdoor_temperature"])
        except (KeyError, TypeError, ValueError):
            return None

        span = extract - outdoor
        if abs(span) < MIN_EFFICIENCY_SPAN:
            return None

        # Rounded here rather than left to the display, so the recorder is not
        # storing fifteen significant figures of a ratio of two one-decimal
        # measurements.
        return round(max(0.0, min(100.0, (supply - outdoor) / span * 100.0)), 1)


class RecTemovexFlowStateSensor(RecTemovexEntity, SensorEntity):
    """Where the airflow sits between its configured speeds.

    This is what the unit's own display shows: below normal flow it is saving
    energy and reads ECO, above normal it is working harder to carry heat or
    cool and reads ECO2. Neither is a mode you select — they are consequences
    of the ECO and ECO2 functions acting on the flow — so the only way to see
    them from outside is to compare the actual fan output against the
    configured min, normal and forced speeds, which is what this does.
    """

    _attr_translation_key = "flow_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(FLOW_STATES)

    def __init__(
        self, coordinator: RecTemovexCoordinator, entry: RecTemovexConfigEntry
    ) -> None:
        """Initialise the flow state sensor."""
        super().__init__(
            coordinator, entry, "supply_fan_speed", unique_key="flow_state"
        )

    @property
    def native_value(self) -> str | None:
        """Classify the current supply fan output."""
        data = self._data
        try:
            speed = float(data["supply_fan_speed"])
            minimum = float(data["supply_fan_min"])
            normal = float(data["supply_fan_normal"])
        except (KeyError, TypeError, ValueError):
            return None

        forced = data.get("supply_fan_forced")
        forced = float(forced) if forced is not None else None

        if speed <= 0:
            return FLOW_OFF
        if speed <= minimum + FLOW_TOLERANCE:
            return FLOW_MIN
        if speed < normal - FLOW_TOLERANCE:
            return FLOW_ECO
        if speed <= normal + FLOW_TOLERANCE:
            return FLOW_NORMAL
        if forced is not None and speed >= forced - FLOW_TOLERANCE:
            return FLOW_FORCED
        return FLOW_ECO2


class RecTemovexOperatingStateSensor(RecTemovexEntity, SensorEntity):
    """What the unit is doing with the air, in its own terms.

    Home Assistant's HVAC actions have no value for an open bypass, and
    reporting it as cooling overstates what is happening: the bypass only stops
    heat being recovered, it does not actively cool. So the four states the
    unit really has live here instead, and hvac_action stays inside the
    vocabulary Home Assistant defines.

    The precedence is the controller's: cooling wins over an open bypass, which
    wins over heating, and recovering heat is what it does the rest of the time.
    """

    _attr_translation_key = "operating_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(OPERATING_STATES)

    def __init__(
        self, coordinator: RecTemovexCoordinator, entry: RecTemovexConfigEntry
    ) -> None:
        """Initialise the operating state sensor."""
        super().__init__(
            coordinator, entry, "heating_valve", unique_key="operating_state"
        )

    @property
    def native_value(self) -> str | None:
        """Classify what the unit is doing."""
        data = self._data
        if not any(key in data for key in STATE_INPUTS):
            return None

        fan_mode = data.get("fan_mode")
        if fan_mode is not None and int(fan_mode) == 0:
            return STATE_OFF
        if data.get("defrosting"):
            return STATE_DEFROSTING

        state = STATE_RECYCLING
        if float(data.get("heating_valve") or 0) > 0:
            state = STATE_HEATING
        if float(data.get("bypass_output") or 0) > 0:
            state = STATE_BYPASS
        if float(data.get("cooling_valve") or 0) > 0:
            state = STATE_COOLING
        return state


class RecTemovexHeatTypeSensor(RecTemovexEntity, SensorEntity):
    """What the heating output drives, as set at commissioning."""

    _attr_translation_key = "heat_type"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(HEAT_TYPES.values())
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: RecTemovexCoordinator, entry: RecTemovexConfigEntry
    ) -> None:
        """Initialise the heater type sensor."""
        super().__init__(coordinator, entry, "heat_type")

    @property
    def native_value(self) -> str | None:
        """Name the configured heater type."""
        value = self._value
        if value is None or isinstance(value, bool):
            return None
        return HEAT_TYPES.get(int(value))
