"""Connection class for Kocom Wallpad."""

from __future__ import annotations

from typing import Optional
import time
import asyncio

from .const import LOGGER


class Connection:
    """Connection class."""
    
    def __init__(self, host: str, port: int) -> None:
        """Initialize the Connection."""
        self.host: str = host
        self.port: int = port

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.reconnect_attempts: int = 0
        self.last_reconnect_attempt: Optional[float] = None
        self.next_attempt_time: Optional[float] = None
        
        # ?? 개선: 추가 상태 관리
        self.max_reconnect_attempts: int = 10  # 최대 재연결 시도
        self.last_send_time: float = 0  # 마지막 패킷 전송 시간
        self.packet_interval: float = 0.8  # 코콤 권장 간격
        self._connection_lock = asyncio.Lock()  # 동시 연결 방지

    async def connect(self) -> bool:
        """Establish a connection."""
        async with self._connection_lock:
            try:
                # ?? 개선: 타임아웃 설정
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=10.0
                )
                self.reconnect_attempts = 0
                self.next_attempt_time = None
                LOGGER.info(f"Connection established to {self.host}:{self.port}")
                return True
                
            except asyncio.TimeoutError:
                LOGGER.error(f"Connection timeout to {self.host}:{self.port}")
                return False
            except Exception as e:
                LOGGER.error(f"Connection failed: {e}")
                return False

    def is_connected(self) -> bool:
        """Check if the connection is active."""
        if self.writer is None:
            return False
        
        # ?? 개선: 실제 연결 상태 확인
        if self.writer.is_closing():
            return False
            
        # 추가 검증: 소켓 상태 확인
        try:
            transport = self.writer.get_extra_info('socket')
            if transport is None:
                return False
            return True
        except Exception:
            return False

    async def reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff."""
        # ?? 개선: 최대 시도 횟수 제한
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            LOGGER.error(f"Max reconnection attempts ({self.max_reconnect_attempts}) reached. Giving up.")
            return False

        # 기존 연결 정리
        await self._close_connection()

        current_time = time.time()
        
        # 재연결 간격 제어
        if self.next_attempt_time and current_time < self.next_attempt_time:
            wait_time = self.next_attempt_time - current_time
            LOGGER.info(f"Waiting {wait_time:.1f} seconds before next reconnection attempt.")
            await asyncio.sleep(wait_time)
        
        self.reconnect_attempts += 1
        delay = min(2 ** self.reconnect_attempts, 60)
        self.last_reconnect_attempt = current_time
        self.next_attempt_time = current_time + delay
        
        LOGGER.info(f"Reconnection attempt {self.reconnect_attempts}/{self.max_reconnect_attempts}")
        
        # ?? 개선: 무한루프 방지 - connect() 직접 호출
        success = await self.connect()
        
        if success:
            LOGGER.info(f"Successfully reconnected on attempt {self.reconnect_attempts}")
            self.reconnect_attempts = 0
            self.next_attempt_time = None
            return True
        else:
            LOGGER.warning(f"Reconnection attempt {self.reconnect_attempts} failed")
            return False

    async def send(self, packet: bytearray) -> bool:
        """Send a packet with proper interval control."""
        if not self.is_connected():
            LOGGER.warning("Cannot send packet: not connected")
            return False

        try:
            # ?? 개선: 패킷 전송 간격 준수
            current_time = time.time()
            elapsed = current_time - self.last_send_time
            
            if elapsed < self.packet_interval:
                wait_time = self.packet_interval - elapsed
                await asyncio.sleep(wait_time)
            
            self.writer.write(packet)
            await self.writer.drain()
            
            self.last_send_time = time.time()
            return True
            
        except Exception as e:
            LOGGER.error(f"Failed to send packet: {e}")
            # ?? 개선: 즉시 재연결하지 않고 상태만 확인
            if not self.is_connected():
                LOGGER.info("Connection lost, will attempt reconnection on next operation")
            return False

    async def receive(self, read_byte: int = 2048, timeout: float = 2.0) -> Optional[bytes]:
        """Receive data with timeout."""
        if not self.is_connected():
            return None
            
        try:
            # ?? 개선: 타임아웃 설정 추가
            return await asyncio.wait_for(
                self.reader.read(read_byte), 
                timeout=timeout
            )
        except asyncio.TimeoutError:
            LOGGER.debug("Receive timeout - no data available")
            return None
        except Exception as e:
            LOGGER.error(f"Failed to receive data: {e}")
            return None

    async def _close_connection(self) -> None:
        """Internal method to close connection safely."""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                LOGGER.debug(f"Error during connection close: {e}")
            finally:
                self.writer = None
                self.reader = None
    
    async def close(self) -> None:
        """Close the connection."""
        LOGGER.info("Closing connection")
        await self._close_connection()

    # ?? 개선: 연결 상태 리셋 메서드 추가
    def reset_reconnect_attempts(self) -> None:
        """Reset reconnection attempt counter."""
        self.reconnect_attempts = 0
        self.next_attempt_time = None

    # ?? 개선: 연결 통계 메서드 추가
    def get_connection_stats(self) -> dict:
        """Get connection statistics."""
        return {
            "connected": self.is_connected(),
            "reconnect_attempts": self.reconnect_attempts,
            "max_attempts": self.max_reconnect_attempts,
            "last_send_time": self.last_send_time,
            "packet_interval": self.packet_interval
        }


async def test_connection(host: str, port: int, timeout: int = 5) -> bool:
    """Test the connection with a timeout."""
    connection = Connection(host, port)
    try:
        # ?? 개선: 연결 결과 확인
        success = await asyncio.wait_for(connection.connect(), timeout=timeout)
        
        if success and connection.is_connected():
            LOGGER.info("Connection test successful")
            return True
        else:
            LOGGER.error("Connection test failed")
            return False
            
    except asyncio.TimeoutError:
        LOGGER.error("Connection test timed out")
        return False
    except Exception as e:
        LOGGER.error(f"Connection test failed: {e}")
        return False
    finally:
        await connection.close()
