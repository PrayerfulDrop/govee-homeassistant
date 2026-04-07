"""BLE DataUpdateCoordinator for Govee BLE lights."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api.ble_direct import GoveeBLEClient
from .const import CONF_BLE_SEGMENTED, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class GoveeBLEState:
    """Snapshot of BLE device state."""

    state: bool | None = None
    brightness: int | None = None
    color: tuple[int, int, int] | None = None


class GoveeBLECoordinator(DataUpdateCoordinator[GoveeBLEState]):
    """Coordinator for a single Govee BLE light.

    Each BLE config entry gets its own coordinator instance.
    State is fetched by polling (every 15s) and pushed immediately
    when the device responds to a command request.
    """

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.device_name: str = config_entry.data[CONF_NAME]
        self.device_address: str = config_entry.data[CONF_ADDRESS]
        segmented: bool = config_entry.data.get(CONF_BLE_SEGMENTED, True)

        ble_device = bluetooth.async_ble_device_from_address(
            hass, self.device_address, connectable=False
        )
        assert ble_device, f"BLE device {self.device_address} not found"

        self._ble_client = GoveeBLEClient(ble_device, self._async_push_update, segmented)

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_ble ({self.device_address})",
            update_method=self._async_update_data,
            update_interval=timedelta(seconds=15),
        )

    def _snapshot(self) -> GoveeBLEState:
        return GoveeBLEState(
            state=self._ble_client.state,
            brightness=self._ble_client.brightness,
            color=self._ble_client.color,
        )

    async def _async_push_update(self) -> None:
        """Called by BLE client when device pushes a state response."""
        self.async_set_updated_data(self._snapshot())

    async def _async_update_data(self) -> GoveeBLEState:
        """Poll all state from the device."""
        self._ble_client.request_state()
        self._ble_client.request_brightness()
        self._ble_client.request_color()
        await self._ble_client.send_buffer()
        return self._snapshot()

    # -- Control API --

    async def async_set_state(self, state: bool) -> None:
        self._ble_client.set_state(state)

    async def async_set_brightness(self, brightness: int) -> None:
        self._ble_client.set_brightness(brightness)

    async def async_set_color(self, red: int, green: int, blue: int) -> None:
        self._ble_client.set_color(red, green, blue)

    async def async_send_buffer(self) -> None:
        await self._ble_client.send_buffer()

    async def async_shutdown(self) -> None:
        """Clean up — BLE client holds no persistent connection."""
        pass
