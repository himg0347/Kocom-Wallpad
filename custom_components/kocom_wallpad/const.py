"""Constants for the Kocom Wallpad integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

# ?? ����: Ÿ�� üũ �ÿ��� import
if TYPE_CHECKING:
    from .pywallpad.packet import KocomPacket

from .pywallpad.packet import (
    LightPacket,
    OutletPacket,
    ThermostatPacket,
    ACPacket,
    FanPacket,
    IAQPacket,
    GasPacket,
    MotionPacket,
    EVPacket,
)

from homeassistant.const import Platform
import logging

# Domain and logging
DOMAIN = "kocom_wallpad"
LOGGER = logging.getLogger(__package__)

# Default configuration
DEFAULT_PORT = 8899
DEFAULT_TIMEOUT = 5

# Device information
BRAND_NAME = "Kocom"
MANUFACTURER = "KOCOM Co., Ltd"
MODEL = "Smart Wallpad"
SW_VERSION = "1.0.6"

# Device attributes
DEVICE_TYPE = "device_type"
ROOM_ID = "room_id"
SUB_ID = "sub_id"

# State attributes
PACKET_DATA = "packet_data"
LAST_DATA = "last_data"

# ?? ����: �ùٸ� Ÿ�� ��Ʈ�� ����
PLATFORM_MAPPING: dict[type, Platform] = {
    LightPacket: Platform.LIGHT,
    OutletPacket: Platform.SWITCH,
    ThermostatPacket: Platform.CLIMATE,
    ACPacket: Platform.CLIMATE,
    FanPacket: Platform.FAN,
    IAQPacket: Platform.SENSOR,
    GasPacket: Platform.SWITCH,
    MotionPacket: Platform.BINARY_SENSOR,
    EVPacket: Platform.SWITCH,
}

# ?? ����: �߰� �����
SUPPORTED_PLATFORMS = list(PLATFORM_MAPPING.values())

# Brightness constants
MIN_BRIGHTNESS = 1
MAX_BRIGHTNESS = 255
DEFAULT_BRIGHTNESS = 255

# Connection constants
MAX_RETRIES = 5
RETRY_DELAY = 0.25
PACKET_TIMEOUT = 2.0

# ?? ����: ���� �Լ���
def validate_platform_mapping() -> bool:
    """Validate platform mapping consistency."""
    try:
        for packet_type, platform in PLATFORM_MAPPING.items():
            if not isinstance(platform, Platform):
                LOGGER.error(f"Invalid platform type for {packet_type}: {platform}")
                return False
        return True
    except Exception as e:
        LOGGER.error(f"Platform mapping validation failed: {e}")
        return False

def get_platform_for_packet(packet_type: type) -> Platform | None:
    """Get platform for packet type with validation."""
    return PLATFORM_MAPPING.get(packet_type)

# ?? ����: �ʱ�ȭ �� ����
if not validate_platform_mapping():
    LOGGER.warning("Platform mapping validation failed during initialization")
