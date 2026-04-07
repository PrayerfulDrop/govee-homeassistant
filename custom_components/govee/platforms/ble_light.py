"""BLE light entity for Govee BLE lights within the govee integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from ..coordinator_ble import GoveeBLECoordinator

_LOGGER = logging.getLogger(__name__)

_HA_MAX = 255


def _remap(value: float, in_min: float, in_max: float, out_min: float, out_max: float) -> float:
    return out_min + (value - in_min) / (in_max - in_min) * (out_max - out_min)


class GoveeBLELightEntity(CoordinatorEntity[GoveeBLECoordinator], LightEntity):
    """Light entity for a directly-connected Govee BLE device.

    Registered under the govee domain so cloud and BLE devices
    appear under the same integration in the UI.
    """

    _attr_has_entity_name = True
    _attr_name = None  # use device name
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_color_mode = ColorMode.RGB

    def __init__(self, coordinator: GoveeBLECoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.device_address
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_address)},
            name=coordinator.device_name,
            manufacturer="Govee",
            model=coordinator.device_name,
            serial_number=coordinator.device_address,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.state if self.coordinator.data else None

    @property
    def brightness(self) -> int | None:
        return self.coordinator.data.brightness if self.coordinator.data else None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        return self.coordinator.data.color if self.coordinator.data else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_state(True)

        if ATTR_BRIGHTNESS in kwargs:
            raw = kwargs[ATTR_BRIGHTNESS]
            mapped = round(_remap(raw, 1, _HA_MAX, 0, _HA_MAX))
            await self.coordinator.async_set_brightness(mapped)

        if ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            await self.coordinator.async_set_color(r, g, b)

        await self.coordinator.async_send_buffer()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_state(False)
        await self.coordinator.async_send_buffer()
