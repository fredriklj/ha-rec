"""Shared entity base for Rec Temovex."""

from __future__ import annotations

from dataclasses import replace

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER, MODEL
from .coordinator import RecTemovexConfigEntry, RecTemovexCoordinator


def for_heat_type[D](coordinator: RecTemovexCoordinator, description: D) -> D:
    """Disable, rather than drop, an entity meant for another heater type.

    It is still registered, so if the heater type was read wrongly — or the
    unit is recommissioned — the entity is one click away, not missing.
    """
    if heat_type_matches(coordinator, description.heat_types):
        return description
    return replace(description, entity_registry_enabled_default=False)


def heat_type_matches(
    coordinator: RecTemovexCoordinator, heat_types: tuple[int, ...] | None
) -> bool:
    """Whether an entity limited to some heater types belongs on this unit.

    The heater type is read in the first poll, before any platform is set up.
    If it could not be read, everything is created rather than guessing.
    """
    if heat_types is None:
        return True
    heat_type = (coordinator.data or {}).get("heat_type")
    return heat_type is None or int(heat_type) in heat_types


class RecTemovexEntity(CoordinatorEntity[RecTemovexCoordinator]):
    """Base class giving every entity a unique id and a shared device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RecTemovexCoordinator,
        entry: RecTemovexConfigEntry,
        key: str,
        *,
        unique_key: str | None = None,
    ) -> None:
        """Initialise the entity.

        ``key`` is the register this entity reads. ``unique_key`` distinguishes
        entities that share a register — a percentage and the flag derived from
        it — so their unique ids do not collide.
        """
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{unique_key or key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title or DEFAULT_NAME,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def _data(self) -> dict[str, float | int | bool]:
        """Last polled values, never None."""
        return self.coordinator.data or {}

    @property
    def available(self) -> bool:
        """Only report a value when the last poll actually produced one."""
        return super().available and self._key in self._data

    @property
    def _value(self) -> float | int | bool | None:
        """Raw decoded value for this entity's register."""
        return self._data.get(self._key)
