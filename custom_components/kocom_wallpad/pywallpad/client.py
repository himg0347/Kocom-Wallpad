"""Client for py wallpad."""

from __future__ import annotations

import asyncio
from queue import Queue, Empty
from typing import Optional, Callable, Awaitable
import weakref

from ..connection import Connection

from .crc import verify_checksum, calculate_checksum
from .packet import PacketParser
from .const import _LOGGER, PREFIX_HEADER, SUFFIX_HEADER


class PacketQueue:
    """Manages the queue for packet transmission with thread safety."""

    def __init__(self):
        self._queue = Queue()
        self._pause = asyncio.Event()
        self._pause.set()  # Initially not paused
        self._has_items = asyncio.Event()
        self._lock = asyncio.Lock()  # ?? ����: ���ü� ����

    async def add_packet(self, packet: bytes) -> None:
        """Add a packet to the queue safely."""
        async with self._lock:
            try:
                self._queue.put_nowait(packet)
                self._has_items.set()
                _LOGGER.debug(f"Added packet to queue: {packet.hex()}")
            except Exception as e:
                _LOGGER.error(f"Failed to add packet to queue: {e}")

    async def get_packet(self) -> Optional[bytes]:
        """Get a packet from the queue safely."""
        async with self._lock:
            try:
                packet = self._queue.get_nowait()
                
                # ?? ����: ť ���� ��Ȯ�� Ȯ��
                if self._queue.empty():
                    self._has_items.clear()
                    
                return packet
            except Empty:
                self._has_items.clear()
                return None
            except Exception as e:
                _LOGGER.error(f"Error getting packet from queue: {e}")
                return None

    async def pause(self) -> None:
        """Pause the queue processing."""
        self._pause.clear()
        _LOGGER.debug("Queue processing paused")

    async def resume(self) -> None:
        """Resume the queue processing."""
        self._pause.set()
        _LOGGER.debug("Queue processing resumed")

    async def wait_for_packet(self) -> None:
        """Wait until there is a packet in the queue."""
        await self._has_items.wait()

    async def wait_for_resume(self) -> None:
        """Wait until the queue is resumed."""
        await self._pause.wait()

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return self._queue.empty()

    def size(self) -> int:
        """Get queue size."""
        return self._queue.qsize()


class KocomClient:
    """Client for the Kocom Wallpad."""

    def __init__(
        self,
        connection: Connection,
        timeout: float = 0.25,
        max_retries: int = 5
    ) -> None:
        """Initialize the KocomClient."""
        self.connection = connection
        self.timeout = timeout
        self.max_retries = max_retries

        self.tasks: list[asyncio.Task] = []
        self.device_callbacks: list[Callable[[dict], Awaitable[None]]] = []
        self.packet_queue = PacketQueue()
        
        # ?? ����: ���� ����
        self._is_running = False
        self._listen_task: Optional[asyncio.Task] = None
        self._queue_task: Optional[asyncio.Task] = None
        self._callback_lock = asyncio.Lock()  # �ݹ� ���� ���ü� ����

    async def start(self) -> None:
        """Start the client."""
        if self._is_running:
            _LOGGER.warning("Client is already running")
            return
            
        _LOGGER.info("Starting Kocom Client...")
        
        try:
            self._is_running = True
            
            # ?? ����: �½�ũ ���� ����
            self._listen_task = asyncio.create_task(self._listen())
            self._queue_task = asyncio.create_task(self._process_queue())
            
            self.tasks = [self._listen_task, self._queue_task]
            
            _LOGGER.info("Kocom Client started successfully")
            
        except Exception as e:
            _LOGGER.error(f"Failed to start client: {e}")
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop the client."""
        if not self._is_running:
            return
            
        _LOGGER.info("Stopping Kocom Client...")
        self._is_running = False
        
        try:
            # ?? ����: �½�ũ �����ϰ� ���
            tasks_to_cancel = []
            
            if self._listen_task and not self._listen_task.done():
                tasks_to_cancel.append(self._listen_task)
            if self._queue_task and not self._queue_task.done():
                tasks_to_cancel.append(self._queue_task)
            
            # �߰� �½�ũ�鵵 ���
            for task in self.tasks:
                if task and not task.done() and task not in tasks_to_cancel:
                    tasks_to_cancel.append(task)
            
            # ��� �½�ũ ���
            for task in tasks_to_cancel:
                task.cancel()
            
            # ��� �Ϸ� ���
            if tasks_to_cancel:
                await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            
            # ?? ����: ������ ����
            self.tasks.clear()
            self.device_callbacks.clear()
            
            _LOGGER.info("Kocom Client stopped successfully")
            
        except Exception as e:
            _LOGGER.error(f"Error during client stop: {e}")

    def add_device_callback(self, callback: Callable[[dict], Awaitable[None]]) -> int:
        """Add callback for device updates and return callback ID."""
        callback_id = len(self.device_callbacks)
        self.device_callbacks.append(callback)
        _LOGGER.debug(f"Added device callback {callback_id}")
        return callback_id

    def remove_device_callback(self, callback_id: int) -> bool:
        """Remove device callback by ID."""
        try:
            if 0 <= callback_id < len(self.device_callbacks):
                self.device_callbacks[callback_id] = None  # None���� ��ŷ
                _LOGGER.debug(f"Removed device callback {callback_id}")
                return True
            return False
        except Exception as e:
            _LOGGER.error(f"Error removing callback {callback_id}: {e}")
            return False
    
    async def _listen(self) -> None:
        """Listen for incoming packets with improved error handling."""
        consecutive_errors = 0
        max_consecutive_errors = 10
        
        _LOGGER.debug("Starting packet listener")
        
        while self._is_running:
            try:
                # ?? ����: ���� ���� Ȯ��
                if not self.connection.is_connected():
                    _LOGGER.warning("Connection lost in listener, waiting...")
                    await asyncio.sleep(1.0)
                    consecutive_errors += 1
                    
                    if consecutive_errors >= max_consecutive_errors:
                        _LOGGER.error("Too many consecutive connection errors, stopping listener")
                        break
                    continue
                
                receive_data = await self.connection.receive(timeout=2.0)
                if receive_data is None:
                    continue
                
                # ?? ����: ���� ���� ī���� ����
                consecutive_errors = 0
                
                # ��Ŷ ���� �� ó��
                packet_list = self.extract_packets(receive_data)
                if not packet_list:
                    continue
                
                # ?? ����: ��Ŷ�� ���� ó��
                for packet in packet_list:
                    await self._process_received_packet(packet)
                    
            except asyncio.CancelledError:
                _LOGGER.debug("Listen task cancelled")
                break
            except Exception as e:
                consecutive_errors += 1
                _LOGGER.error(f"Error in listener (consecutive: {consecutive_errors}): {e}")
                
                # ?? ����: �ʹ� ���� ���� ���� �� �ߴ�
                if consecutive_errors >= max_consecutive_errors:
                    _LOGGER.error("Too many consecutive errors in listener, stopping")
                    break
                
                # ª�� ��� �� ��õ�
                await asyncio.sleep(min(consecutive_errors * 0.1, 2.0))
        
        _LOGGER.debug("Packet listener stopped")

    async def _process_received_packet(self, packet: bytes) -> None:
        """Process a single received packet."""
        try:
            # üũ�� ����
            if not verify_checksum(packet):
                _LOGGER.debug(f"Checksum verification failed: {packet.hex()}")
                return

            # ��Ŷ �Ľ�
            try:
                parsed_packets = PacketParser.parse_state(packet)
            except Exception as e:
                _LOGGER.warning(f"Failed to parse packet {packet.hex()}: {e}")
                return
            
            # ?? ����: �Ľ̵� ��Ŷ ó��
            for parsed_packet in parsed_packets:
                if parsed_packet:
                    _LOGGER.debug(f"Received: {type(parsed_packet).__name__}")
                    await self._notify_callbacks(parsed_packet)
                    
        except Exception as e:
            _LOGGER.error(f"Error processing packet {packet.hex()}: {e}")

    async def _notify_callbacks(self, parsed_packet) -> None:
        """Notify all callbacks about packet with error isolation."""
        async with self._callback_lock:
            active_callbacks = [cb for cb in self.device_callbacks if cb is not None]
            
            if not active_callbacks:
                return
            
            # ?? ����: �ݹ麰 ���� ���� ó��
            callback_tasks = []
            for i, callback in enumerate(active_callbacks):
                task = self._safe_callback_execution(callback, parsed_packet, i)
                callback_tasks.append(task)
            
            # ��� �ݹ��� ���ķ� ����
            if callback_tasks:
                await asyncio.gather(*callback_tasks, return_exceptions=True)

    async def _safe_callback_execution(self, callback, packet, callback_id: int) -> None:
        """Safely execute a callback with timeout."""
        try:
            await asyncio.wait_for(callback(packet), timeout=5.0)
        except asyncio.TimeoutError:
            _LOGGER.warning(f"Callback {callback_id} timed out")
        except Exception as e:
            _LOGGER.error(f"Callback {callback_id} failed: {e}")
    
    def extract_packets(self, data: bytes) -> list[bytes]:
        """Extract packets from the received data with improved validation."""
        packets: list[bytes] = []
        start = 0

        try:
            while start < len(data):
                start_pos = data.find(PREFIX_HEADER, start)
                if start_pos == -1:
                    break

                end_pos = data.find(SUFFIX_HEADER, start_pos + len(PREFIX_HEADER))
                if end_pos == -1:
                    break

                packet = data[start_pos:end_pos + len(SUFFIX_HEADER)]
                
                # ?? ����: ��Ŷ ���� ����
                if len(packet) < len(PREFIX_HEADER) + len(SUFFIX_HEADER) + 1:  # �ּ� ����
                    _LOGGER.debug(f"Packet too short: {packet.hex()}")
                    start = end_pos + len(SUFFIX_HEADER)
                    continue
                
                packets.append(packet)
                start = end_pos + len(SUFFIX_HEADER)

            return packets
            
        except Exception as e:
            _LOGGER.error(f"Error extracting packets: {e}")
            return []
    
    async def _process_queue(self) -> None:
        """Process packets in the queue with improved error handling."""
        _LOGGER.debug("Starting queue processor")
        
        while self._is_running:
            try:
                # ��Ŷ�� �簳 ���� ���
                await asyncio.gather(
                    self.packet_queue.wait_for_packet(),
                    self.packet_queue.wait_for_resume(),
                )

                packet = await self.packet_queue.get_packet()
                if packet is None:
                    continue
                
                # ?? ����: ���� ���� Ȯ�� �� ����
                if not self.connection.is_connected():
                    _LOGGER.warning("Cannot send packet: connection lost")
                    await asyncio.sleep(1.0)
                    continue
                
                await self._send_packet_with_retry(packet)
                    
            except asyncio.CancelledError:
                _LOGGER.debug("Queue processor cancelled")
                break
            except Exception as e:
                _LOGGER.error(f"Error in queue processor: {e}")
                await asyncio.sleep(0.1)  # ª�� ��� �� ��õ�
        
        _LOGGER.debug("Queue processor stopped")

    async def _send_packet_with_retry(self, packet: bytes) -> bool:
        """Send packet with retry logic."""
        retries = 0
        
        while retries < self.max_retries and self._is_running:
            try:
                # ?? ����: ��õ� �� ���� ���� ��Ȯ��
                if not self.connection.is_connected():
                    _LOGGER.warning(f"Connection lost during retry {retries}")
                    return False
                
                _LOGGER.debug(f"Sending packet (attempt {retries + 1}): {packet.hex()}")
                
                success = await self.connection.send(packet)
                if success:
                    _LOGGER.debug("Packet sent successfully")
                    return True
                else:
                    _LOGGER.warning(f"Send failed on attempt {retries + 1}")
                    
            except Exception as e:
                _LOGGER.error(f"Send error on attempt {retries + 1}: {e}")
            
            retries += 1
            if retries < self.max_retries:
                await asyncio.sleep(self.timeout * retries)  # ������ �����
        
        _LOGGER.error(f"Failed to send packet after {self.max_retries} attempts: {packet.hex()}")
        return False

    async def send_packet(self, packet: bytearray) -> bool:
        """Send a packet to the device with validation."""
        try:
            if not self._is_running:
                _LOGGER.warning("Cannot send packet: client not running")
                return False
            
            # ?? ����: ��Ŷ ��� �߰�
            packet_copy = bytearray(packet)  # ���� ���� ����
            packet_copy[:0] = PREFIX_HEADER
            
            # ?? ����: üũ�� ��� ����
            checksum = calculate_checksum(packet_copy)
            if checksum is None:
                _LOGGER.error(f"Checksum calculation failed: {packet_copy.hex()}")
                return False
            
            packet_copy.append(checksum)
            packet_copy.extend(SUFFIX_HEADER)
            
            # ?? ����: ���� üũ�� ����
            if not verify_checksum(packet_copy):
                _LOGGER.error(f"Final checksum verification failed: {packet_copy.hex()}")
                return False
            
            await self.packet_queue.add_packet(bytes(packet_copy))
            return True
            
        except Exception as e:
            _LOGGER.error(f"Error preparing packet for send: {e}")
            return False

    # ?? ����: ���� ��ȸ �޼����
    def is_running(self) -> bool:
        """Check if client is running."""
        return self._is_running

    def get_stats(self) -> dict:
        """Get client statistics."""
        return {
            "is_running": self._is_running,
            "active_callbacks": len([cb for cb in self.device_callbacks if cb is not None]),
            "queue_size": self.packet_queue.size(),
            "queue_empty": self.packet_queue.is_empty(),
            "connection_status": self.connection.is_connected() if self.connection else False,
            "active_tasks": len([t for t in self.tasks if t and not t.done()]),
        }

    # ?? ����: ť ���� �޼����
    async def pause_queue(self) -> None:
        """Pause packet queue processing."""
        await self.packet_queue.pause()

    async def resume_queue(self) -> None:
        """Resume packet queue processing."""
        await self.packet_queue.resume()

    async def clear_queue(self) -> int:
        """Clear all pending packets and return count cleared."""
        cleared_count = 0
        try:
            while not self.packet_queue.is_empty():
                if await self.packet_queue.get_packet() is not None:
                    cleared_count += 1
                else:
                    break
            _LOGGER.info(f"Cleared {cleared_count} packets from queue")
            return cleared_count
        except Exception as e:
            _LOGGER.error(f"Error clearing queue: {e}")
            return cleared_count
                    