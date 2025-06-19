"""Enums for py wallpad."""

from enum import IntEnum

class DeviceType(IntEnum):
    """Device types for Kocom devices."""
    WALLPAD = 0x01
    LIGHT = 0x0E
    GAS = 0x2C
    DOORLOCK = 0x33
    THERMOSTAT = 0x36
    AC = 0x39
    OUTLET = 0x3B
    EV = 0x44
    FAN = 0x48
    MOTION = 0x60
    IGNORE = 0x86
    IAQ = 0x98

class Command(IntEnum):
    """Commands for Kocom devices."""
    STATUS = 0x00
    ON = 0x01
    OFF = 0x02
    DETECT = 0x04
    SCAN = 0x3A

class PacketType(IntEnum):
    """Packet types for Kocom devices."""
    SEND = 0x0B
    RECV = 0x0D

class OpMode(IntEnum):
    """Operating modes for AC devices."""
    COOL = 0x00
    FAN_ONLY = 0x01
    DRY = 0x02
    AUTO = 0x03

class FanMode(IntEnum):
    """Fan modes for fans."""
    OFF = 0x00
    LOW = 0x01
    MEDIUM = 0x02
    HIGH = 0x03

class VentMode(IntEnum):
    """Ventilation modes for fans."""
    NONE = 0x00
    VENTILATION = 0x01
    AUTO = 0x02
    BYPASS = 0x03
    NIGHT = 0x05
    AIR_PURIFIER = 0x08

class FanSpeed(IntEnum):
    """Fan speeds for fans."""
    OFF = 0x00
    LOW = 0x40
    MEDIUM = 0x80
    HIGH = 0xC0

class Direction(IntEnum):
    """Direction for EV devices."""
    IDLE = 0x00
    DOWN = 0x01
    UP = 0x02
    ARRIVAL = 0x03
