"""Direct BLE API for Govee lights.

Implements the Govee BLE protocol for direct local control
of Govee BLE lights without cloud connectivity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum

import bleak_retry_connector
from bleak import BleakClient, BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic

_LOGGER = logging.getLogger(__name__)

WRITE_CHARACTERISTIC_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"
READ_CHARACTERISTIC_UUID = "00010203-0405-0607-0809-0a0b0c0d2b10"

BLE_DISCOVERY_NAMES: tuple[str, ...] = ("Govee_", "ihoment_", "GBK_")


class LedPacketHead(IntEnum):
    COMMAND = 0x33
    REQUEST = 0xAA


class LedPacketCmd(IntEnum):
    POWER = 0x01
    BRIGHTNESS = 0x04
    COLOR = 0x05
    SEGMENT = 0xA5


class LedColorType(IntEnum):
    SEGMENTS = 0x15
    SINGLE = 0x02
    LEGACY = 0x0D


@dataclass
class LedPacket:
    head: LedPacketHead
    cmd: LedPacketCmd
    payload: bytes | list = b""


def _generate_checksum(frame: bytes) -> bytes:
    checksum = 0
    for b in frame:
        checksum ^= b
    return bytes([checksum & 0xFF])


def _generate_frame(packet: LedPacket) -> bytes:
    cmd = packet.cmd & 0xFF
    frame = bytes([packet.head, cmd]) + bytes(packet.payload)
    frame += bytes([0] * (19 - len(frame)))
    frame += _generate_checksum(frame)
    return frame


def _verify_checksum(frame: bytes) -> bool:
    return frame[-1:] == _generate_checksum(frame[:-1])


class GoveeBLEClient:
    """Direct BLE client for a single Govee BLE light.

    Buffers commands and transmits them in one connection pass.
    Reconnects automatically via bleak_retry_connector.
    """

    state: bool | None = None
    brightness: int | None = None
    color: tuple[int, int, int] | None = None

    def __init__(
        self,
        ble_device: BLEDevice,
        update_callback,
        segmented: bool = False,
    ) -> None:
        self._ble_device = ble_device
        self._segmented = segmented
        self._packet_buffer: list[LedPacket] = []
        self._client: BleakClient | None = None
        self._update_callback = update_callback

    @property
    def address(self) -> str:
        return self._ble_device.address

    async def _ensure_connected(self) -> None:
        if self._client is not None and self._client.is_connected:
            return
        await self._connect()

    async def _connect(self) -> None:
        self._client = await bleak_retry_connector.establish_connection(
            BleakClient, self._ble_device, self.address
        )
        await self._client.start_notify(READ_CHARACTERISTIC_UUID, self._handle_receive)

    async def _transmit_packet(self, packet: LedPacket) -> None:
        frame = _generate_frame(packet)
        await self._client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, frame, False)

    async def _handle_request_response(self, packet: LedPacket) -> None:
        match packet.cmd:
            case LedPacketCmd.POWER:
                self.state = packet.payload[0] == 0x01
            case LedPacketCmd.BRIGHTNESS:
                raw = packet.payload[0]
                self.brightness = int(raw / 100 * 255) if self._segmented else raw
            case LedPacketCmd.COLOR:
                self.color = (packet.payload[1], packet.payload[2], packet.payload[3])
            case LedPacketCmd.SEGMENT:
                self.color = (packet.payload[2], packet.payload[3], packet.payload[4])

    async def _handle_receive(
        self, characteristic: BleakGATTCharacteristic, frame: bytearray
    ) -> None:
        if not _verify_checksum(bytes(frame)):
            _LOGGER.warning("BLE packet checksum mismatch for %s", self.address)
            return
        packet = LedPacket(
            head=frame[0],
            cmd=frame[1],
            payload=bytes(frame[2:-1]),
        )
        if packet.head == LedPacketHead.REQUEST:
            await self._handle_request_response(packet)
            await self._update_callback()

    def _queue(
        self,
        cmd: LedPacketCmd,
        payload: bytes | list = b"",
        request: bool = False,
        repeat: int = 3,
    ) -> None:
        head = LedPacketHead.REQUEST if request else LedPacketHead.COMMAND
        packet = LedPacket(head, cmd, payload)
        self._packet_buffer.extend([packet] * repeat)

    async def send_buffer(self) -> None:
        """Flush all buffered packets over BLE."""
        if not self._packet_buffer:
            return
        await self._ensure_connected()
        for packet in self._packet_buffer:
            await self._transmit_packet(packet)
        self._packet_buffer.clear()

    # -- State request helpers --

    def request_state(self) -> None:
        self._queue(LedPacketCmd.POWER, request=True)

    def request_brightness(self) -> None:
        self._queue(LedPacketCmd.BRIGHTNESS, request=True)

    def request_color(self) -> None:
        if self._segmented:
            self._queue(LedPacketCmd.SEGMENT, b"\x01", request=True)
        else:
            self._queue(LedPacketCmd.COLOR, request=True)

    # -- Command helpers --

    def set_state(self, state: bool) -> None:
        if self.state == state:
            return
        self._queue(LedPacketCmd.POWER, [0x01 if state else 0x00])
        self.request_state()

    def set_brightness(self, brightness: int) -> None:
        if self.brightness == brightness:
            return
        payload = round(brightness / 255 * 100) if self._segmented else round(brightness)
        self._queue(LedPacketCmd.BRIGHTNESS, [payload])
        self.request_brightness()

    def set_color(self, red: int, green: int, blue: int) -> None:
        if self.color == (red, green, blue):
            return
        if self._segmented:
            self._queue(
                LedPacketCmd.COLOR,
                [LedColorType.SEGMENTS, 0x01, red, green, blue, 0, 0, 0, 0, 0, 0xFF, 0xFF],
            )
        else:
            self._queue(LedPacketCmd.COLOR, [LedColorType.SINGLE, red, green, blue])
            self._queue(LedPacketCmd.COLOR, [LedColorType.LEGACY, red, green, blue])
        self.request_color()
