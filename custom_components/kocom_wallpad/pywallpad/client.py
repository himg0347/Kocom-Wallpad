"""Client for py wallpad."""

from __future__ import annotations

import asyncio
from queue import Queue
from typing import Optional, Callable, Awaitable

from ..connection import Connection

from .crc import verify_checksum, calculate_checksum
from .packet import PacketParser
from .const import _LOGGER, PREFIX_HEADER, SUFFIX_HEADER


class PacketQueue:
    """Manages the queue for packet transmission."""

    def __init__(self):
        self._queue = Queue()
        self._pause = asyncio.Event()
        self._pause.set()  # Initially not paused
        self._has_items = asyncio.Event()

    def add_packet(self, packet: bytes):
        """Add a packet to the queue."""
        self._queue.put(packet)
        self._has_items.set()

    def get_packet(self) -> Optional[bytes]:
        """Get a packet from the queue."""
        try:
            packet = self._queue.get_nowait()
            if self._queue.empty():
                self._has_items.clear()  # Reset if the queue is empty
            return packet
        except Exception:
            return None

    async def pause(self):
        """Pause the queue processing."""
        self._pause.clear()

    async def resume(self):
        """Resume the queue processing."""
        self._pause.set()

    async def wait_for_packet(self):
        """Wait until there is a packet in the queue."""
        await self._has_items.wait()

    async def wait_for_resume(self):
        """Wait until the queue is resumed."""
        await self._pause.wait()


class KocomClient:
    """Client for the Kocom Wallpad."""

    def __init__(
        self,
        connection: Connection,
        timeout: float = 0.25,
        max_retries = 5
    ) -> None:
        """Initialize the KocomClient."""
        self.connection = connection
        self.timeout = timeout
        self.max_retries = max_retries

        self.tasks: list[asyncio.Task] = []
        self.device_callbacks: list[Callable[[dict], Awaitable[None]]] = []
        self.packet_queue = PacketQueue()

    async def start(self) -> None:
        """Start the client."""
        _LOGGER.debug("Starting Kocom Client...")
        self.tasks.append(asyncio.create_task(self._listen()))
        self.tasks.append(asyncio.create_task(self._process_queue()))

    async def stop(self) -> None:
        """Stop the client."""
        _LOGGER.debug("Stopping Kocom Client...")
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()
        self.device_callbacks.clear()

    def add_device_callback(self, callback: Callable[[dict], Awaitable[None]]) -> None:
        """Add callback for device updates."""
        self.device_callbacks.append(callback)
    
    async def _listen(self) -> None:
        """Listen for incoming packets."""
        while self.connection.is_connected():
            try:
                receive_data = await self.connection.receive()
                if receive_data is None:
                    continue
                
                packet_list = self.extract_packets(receive_data)
                for packet in packet_list:
                    if not verify_checksum(packet):
                        _LOGGER.debug("Checksum verification failed for packet: %s", packet.hex())
                        continue

                    parsed_packets = PacketParser.parse_state(packet)
                    for parsed_packet in parsed_packets:
                        _LOGGER.debug(
                            "Received packet: %s, %s, %s", 
                            parsed_packet, parsed_packet._device, parsed_packet._last_data
                        )
                        for callback in self.device_callbacks:
                            await callback(parsed_packet)
            except Exception as e:
                _LOGGER.error(f"Error receiving data: {e}", exc_info=True)
    
    def extract_packets(self, data: bytes) -> list[bytes]:
        """Extract packets from the received data."""
        packets: list[bytes] = []
        start = 0

        while start < len(data):
            start_pos = data.find(PREFIX_HEADER, start)
            if start_pos == -1:
                break

            end_pos = data.find(SUFFIX_HEADER, start_pos + len(PREFIX_HEADER))
            if end_pos == -1:
                break

            packet = data[start_pos:end_pos + len(SUFFIX_HEADER)]
            packets.append(packet)

            start = end_pos + len(SUFFIX_HEADER)

        return packets
    
    async def _process_queue(self) -> None:
        """Process packets in the queue."""
        while self.connection.is_connected():
            await asyncio.gather(
                self.packet_queue.wait_for_packet(),
                self.packet_queue.wait_for_resume(),
            )

            packet = self.packet_queue.get_packet()
            if packet:
                retries = 0
                while retries < self.max_retries:
                    try:
                        _LOGGER.debug(f"Sending packet: {packet.hex()}, Retries: {retries}")
                        await self.connection.send(packet)
                        break
                    except Exception as e:
                        retries += 1
                        _LOGGER.error(f"Send error: {e}. Retry {retries}/{self.max_retries}")
                        await asyncio.sleep(self.timeout)
                else:
                    _LOGGER.error(f"Max retries reached for packet: {packet.hex()}")

    async def send_packet(self, packet: bytearray) -> None:
        """Send a packet to the device."""
        packet[:0] = PREFIX_HEADER
        if (checksum := calculate_checksum(packet)) is None:
            _LOGGER.error("Checksum calculation failed for packet: %s", packet.hex())
            return
        packet.append(checksum)
        packet.extend(SUFFIX_HEADER)
        if not verify_checksum(packet):
            _LOGGER.error("Checksum verification failed for packet: %s", packet.hex())
            return
        self.packet_queue.add_packet(packet)
