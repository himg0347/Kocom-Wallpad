from __future__ import annotations

import asyncio
import time
from typing import Callable, Awaitable
from dataclasses import dataclass

from ..connection import RS485Connection
from .crc import (
    verify_checksum,
    verify_crc,
    calculate_checksum,
    calculate_crc,
)
from .packet import (
    KocomPacket,
    PacketParser,
    DoorPhoneParser,
)
from .const import _LOGGER, HEADER, TAILER


@dataclass
class PacketQueue:
    """A queue of packets to be sent."""
    packet: bytearray
    try_to_retry: bool
    retries: int = 0


class KocomClient:
    """Client for the Kocom Wallpad."""

    def __init__(self, connection: RS485Connection) -> None:
        """Initialize the KocomClient."""
        self.connection = connection
        self.max_retries: int = 4
        self.packets: bytes = bytes()

        self.tasks: list[asyncio.Task] = []
        self.device_callbacks: list[Callable[[KocomPacket], Awaitable[None]]] = []
        self.packet_queue: asyncio.Queue[PacketQueue] = asyncio.Queue()
        self.last_packet = None

    async def start(self) -> None:
        """Start the client."""
        _LOGGER.debug("Starting Kocom Client...")
        self.tasks.append(asyncio.create_task(self.connection.reconnect_manager()))
        self.tasks.append(asyncio.create_task(self._listen()))
        self.tasks.append(asyncio.create_task(self._process_queue()))

    async def stop(self) -> None:
        """Stop the client."""
        _LOGGER.debug("Stopping Kocom Client...")
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()
        self.device_callbacks.clear()
        self.last_packet = None

    def add_device_callback(self, callback: Callable[[KocomPacket], Awaitable[None]]) -> None:
        """Add callback for device updates."""
        self.device_callbacks.append(callback)

    async def _listen(self) -> None:
        """Listen for incoming packets."""
        while True:
            try:
                if not self.connection.is_connected:
                    await asyncio.sleep(0.1)
                    continue

                receive_data = await self.connection.receive()
                if not receive_data:
                    await asyncio.sleep(0.1)
                    continue

                packets = self.parse_packets(receive_data)
                for packet in packets:
                    await self._process_packet(packet)
            except ValueError as ve:
                _LOGGER.error(f"Error processing packet: {ve}", exc_info=True)
                await asyncio.sleep(0.5)
            except Exception as e:
                _LOGGER.error(f"Error receiving data: {e}", exc_info=True)
                await asyncio.sleep(0.5)

    def parse_packets(self, data: bytes) -> list[bytes]:
        """Extract 21-byte packets with specific start/end markers."""
        packets: list[bytes] = []

        for byte in data:
            self.packets += bytes([byte])
            if len(self.packets) < 21:
                continue

            if self.packets[:2] == HEADER and self.packets[-2:] == TAILER:
                packets.append(self.packets)
                self.packets = bytes()
            elif len(self.packets) > 21:
                self.packets = self.packets[1:]

        return packets

    async def _process_packet(self, packet: bytes) -> None:
        """Process a single packet."""
        parser, log_message = None, None

        if verify_checksum(packet):
            parser, log_message = PacketParser, "Received packet"
        elif verify_crc(packet):
            parser, log_message = DoorPhoneParser, "Received door phone"
        else:
            _LOGGER.debug(f"Invalid packet received: {packet.hex()}")
            return

        if parser:
            parsed_packets = parser.parse_state(packet)
            for parsed_packet in parsed_packets:
                _LOGGER.debug(
                    f"{log_message}: {parsed_packet}, {parsed_packet._device}, {parsed_packet._last_data}"
                )
                self.last_packet = parsed_packet

                if parsed_packet._device is None:
                    continue

                for callback in self.device_callbacks:
                    try:
                        await callback(parsed_packet)
                    except Exception as e:
                        _LOGGER.error(f"Error in callback: {e}", exc_info=True)

    async def _process_queue(self) -> None:
        """Process packets in the queue."""
        while True:
            try:
                queue = await self.packet_queue.get()
                _LOGGER.debug(f"Sending packet: {queue.packet.hex()}")
                await self.connection.send(queue.packet)

                if not (self.last_packet and self.last_packet._device):
                    self.packet_queue.task_done()
                    continue

                try:
                    packet = PacketParser.parse_state(queue.packet)
                    found_match = False
                    start_time = time.time()

                    while (time.time() - start_time) < 1.0:
                        if self.last_packet is None:
                            await asyncio.sleep(0.2)
                            continue

                        for p in packet:
                            if self.last_packet._device.state == p._device.state:
                                found_match = True
                                self.last_packet = None
                                break

                        if found_match:
                            break
                        await asyncio.sleep(0.1)

                    if not found_match and queue.try_to_retry:
                        _LOGGER.debug("Not received ACK, retrying...")
                        await self._handle_retry(queue)
                    else:
                        _LOGGER.debug(f"Command success: {queue.packet.hex()}")
                        self.packet_queue.task_done()

                except Exception as e:
                    _LOGGER.error(f"Error processing response: {e}", exc_info=True)
                    await self._handle_retry(queue)

            except Exception as e:
                _LOGGER.error(f"Error processing queue: {e}", exc_info=True)
                await asyncio.sleep(0.5)

    async def _handle_retry(self, queue: PacketQueue) -> None:
        """Handle command retry."""
        if queue.retries >= self.max_retries:
            _LOGGER.error(f"Command failed after {self.max_retries} retries: {queue.packet.hex()}")
            self.packet_queue.task_done()
            return

        queue.retries += 1
        delay = 0.1 * (2 ** queue.retries)
        _LOGGER.debug(f"Retrying command (attempt {queue.retries}) after {delay:.2f}s: {queue.packet.hex()}")
        await asyncio.sleep(delay)
        await self.packet_queue.put(queue)

    async def send_packet(self, packet: bytearray | list[tuple[bytearray, float | None]]) -> None:
        """Send a packet to the device."""
        if isinstance(packet, list):
            for p, delay in packet:
                if delay is not None:
                    await asyncio.sleep(delay)

                p[:0] = HEADER
                if (crc := calculate_crc(p)) is None:
                    _LOGGER.error(f"Failed to calculate crc for packet: {p.hex()}")
                    continue

                p.extend(crc)
                p.extend(TAILER)

                if not verify_crc(p):
                    _LOGGER.error(f"Failed to verify crc for packet: {p.hex()}")
                    continue

                queue = PacketQueue(packet=p, try_to_retry=False)
                await self.packet_queue.put(queue)
        else:
            packet[:0] = HEADER
            if (sum := calculate_checksum(packet)) is None:
                _LOGGER.error(f"Failed to calculate checksum for packet: {packet.hex()}")
                return

            packet.append(sum)
            packet.extend(TAILER)

            if not verify_checksum(packet):
                _LOGGER.error(f"Failed to verify checksum for packet: {packet.hex()}")
                return

            queue = PacketQueue(packet=packet, try_to_retry=True)
            await self.packet_queue.put(queue)
