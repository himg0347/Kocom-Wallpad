"""Packet class for py wallpad."""

from __future__ import annotations

from typing import Any, ClassVar
from copy import deepcopy
from dataclasses import dataclass, field
import time

from .const import (
    _LOGGER,
    POWER,
    BRIGHTNESS,
    LEVEL,
    INDEX,
    AWAY_MODE,
    TARGET_TEMP,
    CURRENT_TEMP,
    STATE,
    ERROR_CODE,
    HOTWATER_STATE,
    HOTWATER_TEMP,
    HEATWATER_TEMP,
    ERROR,
    OP_MODE,
    FAN_MODE,
    VENT_MODE,
    FAN_SPEED,
    PRESET_LIST,
    SPEED_LIST,
    PM10,
    PM25,
    CO2,
    VOC,
    TEMPERATURE,
    HUMIDITY,
    TIME,
    DIRECTION,
    FLOOR,
)
from .enums import (
    DeviceType,
    PacketType,
    Command,
    OpMode,    # AC 
    FanMode,   # AC
    VentMode,  # Fan
    FanSpeed,  # Fan
    Direction, # EV
)


@dataclass
class Device:
    """Device class for Kocom devices."""
    device_type: str
    device_id: str
    room_id: str | None = None
    state: dict[str, Any] = field(default_factory=dict)
    sub_id: str | None = None

    def __repr__(self) -> str:
        """Return a string representation of the device."""
        return f"Device(device_type={self.device_type}, device_id={self.device_id}, room_id={self.room_id}, state={self.state}, sub_id={self.sub_id})"
    

class KocomPacket:
    """Base class for Kocom packets."""

    def __init__(self, packet: bytes) -> None:
        """Initialize the packet."""
        self.packet = packet
        self.packet_type = PacketType(packet[3] >> 4)
        self.sequence = packet[3] & 0x0F
        self.dest = packet[5:7]
        self.src = packet[7:9]
        self.command = Command(packet[9])
        self.value = packet[10:18]
        self.checksum = packet[18]
        self._last_recv_time = time.time()
        self._device: Device = None
        self._last_data: dict[str, Any] = {}

    def __repr__(self) -> str:
        """Return a string representation of the packet."""
        return f"KocomPacket(packet_type={self.packet_type.name}, sequence={self.sequence}, dest={self.dest.hex()}, src={self.src.hex()}, command={self.command.name}, value={self.value.hex()}, checksum={hex(self.checksum)})"
    
    @property
    def device_type(self) -> DeviceType:
        """Return the device type."""
        return DeviceType(self.src[0])
    
    @property
    def room_id(self) -> str:
        """Return the room ID."""
        return str(self.src[1])
    
    @property
    def device_id(self) -> str:
        """Return the device ID."""
        return f"{self.device_name()}_{self.room_id}"
    
    def device_name(self, upper=False) -> str:
        """Return the device name."""
        if upper:
            return self.device_type.name.upper()
        return self.device_type.name.lower()
    
    def parse_data(self) -> list[Device]:
        """Parse data from the packet."""
        _LOGGER.warning("Parsing not implemented for %s", self.device_name())
        return []
    
    def make_packet(self, command: Command, value_packet: bytearray) -> bytearray:
        """Make a packet."""
        if self.value != bytes(value_packet):
            _LOGGER.debug("Packet value changed from %s to %s", self.value.hex(), value_packet.hex())
            self.value = bytes(value_packet)
        
        header = bytearray([0x30, 0xBC, 0x00])
        if self.device_type == DeviceType.EV:
            address = self.dest + self.src
        else:
            address = self.src + self.dest
        command_byte = bytearray([command.value])
        return header + bytearray(address) + command_byte + value_packet


class LightPacket(KocomPacket):
    """Handles packets for light devices."""

    _class_last_data: ClassVar[dict[str, dict[str, Any]]] = {}

    def __init__(self, packet: bytes) -> None:
        """Initialize the packet."""
        super().__init__(packet)
        if self.device_id not in self._class_last_data:
            self._class_last_data[self.device_id] = {
                INDEX: [],
                BRIGHTNESS: []
            }
        self._last_data.update(self._class_last_data)

    def parse_data(self) -> list[Device]:
        """Parse light-specific data."""
        devices: list[Device] = []

        for i, value in enumerate(self.value[:8]):
            power_state = value == 0xFF
            brightness = value if not power_state else 0

            if power_state and i not in self._last_data[self.device_id][INDEX]:
                self._last_data[self.device_id][INDEX].append(i)
                self._last_data[self.device_id][INDEX].sort()
                _LOGGER.debug(
                    "New light discovered - Room: %s, Index: %s, Current indices: %s",
                    self.room_id, i, self._last_data[self.device_id][INDEX]
                )
            
            if (brightness > 0 and 
                i in self._last_data[self.device_id][INDEX] and
                brightness not in self._last_data[self.device_id][BRIGHTNESS]):
                self._last_data[self.device_id][BRIGHTNESS].append(brightness)
                self._last_data[self.device_id][BRIGHTNESS].sort()
                _LOGGER.debug(
                    "New brightness level discovered - Room: %s, Index: %s, Level: %s, Current levels: %s",
                    self.room_id, i, brightness, self._last_data[self.device_id][BRIGHTNESS]
                )
            
            if i in self._last_data[self.device_id][INDEX]:
                state = {POWER: power_state}
                has_brightness = bool(self._last_data[self.device_id][BRIGHTNESS])

                if has_brightness:
                    state[POWER] = value > 0
                    state[BRIGHTNESS] = brightness
                    state[LEVEL] = self._last_data[self.device_id][BRIGHTNESS]
                
                device = Device(
                    device_type=self.device_name(),
                    room_id=self.room_id,
                    device_id=self.device_id,
                    state=state,
                    sub_id=str(i),
                )
                devices.append(device)
                
        return devices
    
    def make_scan(self) -> bytearray:
        """Make a scan packet."""
        return super().make_packet(Command.SCAN, bytearray(self.value))
    
    def make_power_status(self, power: bool) -> bytearray:
        """Make a power status packet."""
        sub_id = int(self._device.sub_id)
        value = bytearray(self.value)
        value[sub_id] = 0xFF if power else 0x00
        return super().make_packet(Command.STATUS, value)
    
    def make_brightness_status(self, brightness: int) -> bytearray:
        """Make a brightness status packet."""
        sub_id = int(self._device.sub_id)
        value = bytearray(self.value)
        value[sub_id] = brightness
        return super().make_packet(Command.STATUS, value)


class OutletPacket(KocomPacket):
    """Handles packets for outlet devices."""

    _class_last_data: ClassVar[dict[str, dict[str, Any]]] = {}

    def __init__(self, packet: bytes) -> None:
        """Initialize the packet."""
        super().__init__(packet)
        if self.device_id not in self._class_last_data:
            self._class_last_data[self.device_id] = {
                INDEX: [],
            }
        self._last_data.update(self._class_last_data)

    def parse_data(self) -> list[Device]:
        """Parse outlet-specific data."""
        devices: list[Device] = []
        
        for i, value in enumerate(self.value[:8]):
            power_state = value == 0xFF

            if power_state and i not in self._last_data[self.device_id][INDEX]:
                self._last_data[self.device_id][INDEX].append(i)
                self._last_data[self.device_id][INDEX].sort()
                _LOGGER.debug(
                    "New valid outlet discovered - Room: %s, Index: %s, Current valid indices: %s",
                    self.room_id, i, self._last_data[self.device_id][INDEX]
                )

            if i in self._last_data[self.device_id][INDEX]:
                device = Device(
                    device_type=self.device_name(),
                    room_id=self.room_id,
                    device_id=self.device_id,
                    state={POWER: power_state},
                    sub_id=str(i),
                )
                devices.append(device)

        return devices
    
    def make_scan(self) -> bytearray:
        """Make a scan packet."""
        return super().make_packet(Command.SCAN, bytearray(self.value))
    
    def make_power_status(self, power: bool) -> bytearray:
        """Make a power status packet."""
        sub_id = int(self._device.sub_id)
        value = bytearray(self.value)
        value[sub_id] = 0xFF if power else 0x00
        return super().make_packet(Command.STATUS, value)
    

class ThermostatPacket(KocomPacket):
    """Handles packets for thermostat devices."""

    _class_last_data: ClassVar[dict[str, dict[str, Any]]] = {}

    def __init__(self, packet: bytes) -> None:
        """Initialize the packet."""
        super().__init__(packet)
        if self.device_id not in self._class_last_data:
            self._class_last_data[self.device_id] = {
                HOTWATER_STATE: False,
                TARGET_TEMP: 22,
            }
        self._last_data.update(self._class_last_data)

    def parse_data(self) -> list[Device]:
        """Parse thermostat-specific data."""
        devices: list[Device] = []

        power_state = self.value[0] >> 4 == 1
        hotwater_state = self.value[0] & 0x0F == 2
        away_mode = self.value[1] & 0x0F == 1
        target_temp = self.value[2]
        current_temp = self.value[4]
        hotwater_temp = self.value[3]
        heatwater_temp = self.value[5]
        error_code = self.value[6]
        boiler_error = self.value[7]
        
        if hotwater_state and not self._last_data[self.device_id][HOTWATER_STATE]:
            _LOGGER.debug(f"Hotwater state changed to {hotwater_state}.")
            self._last_data[self.device_id][HOTWATER_STATE] = True

        if power_state and self._last_data[self.device_id][TARGET_TEMP] != target_temp:
            _LOGGER.debug(f"Target temp changed to {target_temp}.")
            self._last_data[self.device_id][TARGET_TEMP] = target_temp

        devices.append(
            Device(
                device_type=self.device_name(),
                room_id=self.room_id,
                device_id=self.device_id,
                state={
                    POWER: power_state,
                    AWAY_MODE: away_mode,
                    TARGET_TEMP: self._last_data[self.device_id][TARGET_TEMP],
                    CURRENT_TEMP: current_temp,
                }
            )
        )

        if self.room_id == '0':
            devices.append(
                Device(
                    device_type=self.device_name(),
                    device_id=self.device_id,
                    state={STATE: error_code != 0, ERROR_CODE: error_code},
                    sub_id=ERROR,
                )
            )
            devices.append(
                Device(
                    device_type=self.device_name(),
                    device_id=self.device_id,
                    state={STATE: boiler_error != 0, ERROR_CODE: boiler_error},
                    sub_id=f"boiler {ERROR}",
                )
            )

        if self._last_data[self.device_id][HOTWATER_STATE] and self.room_id == '0':
            if hotwater_temp > 0:
                _LOGGER.debug(f"Supports hot water temperature in thermostat.")
                devices.append(
                    Device(
                        device_type=self.device_name(),
                        room_id=None,
                        device_id=self.device_id,
                        state={HOTWATER_TEMP: hotwater_temp},
                        sub_id=f"hotwater {TEMPERATURE}",
                    )
                )
            if heatwater_temp > 0:
                _LOGGER.debug(f"Supports heat water temperature in thermostat.")
                devices.append(
                    Device(
                        device_type=self.device_name(),
                        room_id=None,
                        device_id=self.device_id,
                        state={HEATWATER_TEMP: heatwater_temp},
                        sub_id=f"heatwater {TEMPERATURE}",
                    )
                )
            
        return devices
    
    def make_scan(self) -> bytearray:
        """Make a scan packet."""
        return super().make_packet(Command.SCAN, bytearray(self.value))
    
    def make_power_status(self, power: bool) -> bytearray:
        """Make a power status packet."""
        value = bytearray(self.value)
        value[0] = 0x11 if power else 0x01
        value[1] = 0x00
        return super().make_packet(Command.STATUS, value)
    
    def make_away_status(self, away_mode: bool) -> bytearray:
        """Make an away status packet."""
        value = bytearray(self.value)
        value[0] = 0x11
        value[1] = 0x01 if away_mode else 0x00
        return super().make_packet(Command.STATUS, value)
    
    def make_target_temp(self, target_temp: int) -> bytearray:
        """Make a target temperature packet."""
        value = bytearray(self.value)
        value[2] = target_temp
        return super().make_packet(Command.STATUS, value)


class ACPacket(KocomPacket):
    """Handles packets for AC devices."""

    def parse_data(self) -> list[Device]:
        """Parse AC-specific data."""
        power_state = self.value[0] == 0x10
        op_mode = OpMode(self.value[1])
        fan_mode = FanMode(self.value[2])
        current_temp = self.value[4]
        target_temp = self.value[5]

        device = Device(
            device_type=self.device_name(upper=True),
            room_id=self.room_id,
            device_id=self.device_id,
            state={
                POWER: power_state,
                OP_MODE: op_mode,
                FAN_MODE: fan_mode,
                CURRENT_TEMP: current_temp,
                TARGET_TEMP: target_temp
            },
        )
        return [device]
    
    def make_scan(self) -> bytearray:
        """Make a scan packet."""
        return super().make_packet(Command.SCAN, bytearray(self.value))
    
    def make_power_status(self, power: bool) -> bytearray:
        """Make a power status packet."""
        value = bytearray(self.value)
        value[0] = 0x10 if power else 0x00
        return super().make_packet(Command.STATUS, value)
    
    def make_op_mode(self, op_mode: OpMode) -> bytearray:
        """Make an operation mode packet."""
        value = bytearray(self.value)
        value[0] = 0x10
        value[1] = op_mode.value
        return super().make_packet(Command.STATUS, value)
    
    def make_fan_mode(self, fan_mode: FanMode) -> bytearray:
        """Make a fan mode packet."""
        value = bytearray(self.value)
        value[2] = fan_mode.value
        return super().make_packet(Command.STATUS, value)
    
    def make_target_temp(self, target_temp: int) -> bytearray:
        """Make a target temperature packet."""
        value = bytearray(self.value)
        value[5] = target_temp
        return super().make_packet(Command.STATUS, value)
    

class FanPacket(KocomPacket):
    """Handles packets for fan devices."""
    
    _class_last_data: ClassVar[dict[str, dict[str, Any]]] = {}

    def __init__(self, packet: bytes) -> None:
        """Initialize the packet."""
        super().__init__(packet)
        if self.device_id not in self._class_last_data:
            self._class_last_data[self.device_id] = {
                CO2: False,
            }
        self._last_data.update(self._class_last_data)

    def parse_data(self) -> list[Device]:
        """Parse fan-specific data."""
        devices: list[Device] = []

        power_state = self.value[0] >> 4 == 1
        co2 = self.value[0] & 0x0F == 1
        vent_mode = VentMode(self.value[1])
        fan_speed = FanSpeed(self.value[2])
        co2_state = (self.value[4] * 100) + self.value[5]
        error_code = self.value[6]

        preset_list = list(VentMode.__members__.keys())
        speed_list = list(FanSpeed.__members__.keys())

        if co2 and not self._last_data[self.device_id][CO2]:
            _LOGGER.debug(f"CO2 detected: {co2_state}")
            self._last_data[self.device_id][CO2] = True

        devices.append(
            Device(
                device_type=self.device_name(),
                room_id=self.room_id,
                device_id=self.device_id,
                state={
                    POWER: power_state,
                    VENT_MODE: vent_mode,
                    FAN_SPEED: fan_speed,
                    PRESET_LIST: preset_list,
                    SPEED_LIST: speed_list,
                }
            )
        )
        devices.append(
            Device(
                device_type=self.device_name(),
                device_id=self.device_id,
                state={STATE: error_code != 0, ERROR_CODE: error_code},
                sub_id=ERROR,
            )
        )
        
        if self._last_data[self.device_id][CO2]:
            devices.append(
                Device(
                    device_type=self.device_name(),
                    room_id=self.room_id,
                    device_id=self.device_id,
                    state={STATE: co2_state},
                    sub_id=CO2,
                )
            )
    
        return devices
    
    def make_scan(self) -> bytearray:
        """Make a scan packet."""
        return super().make_packet(Command.SCAN, bytearray(self.value))
    
    def make_power_status(self, power: bool) -> bytearray:
        """Make a power status packet."""
        value = bytearray(self.value)
        value[0] = 0x11 if power else 0x00
        return super().make_packet(Command.STATUS, value)
    
    def make_vent_mode(self, vent_mode: VentMode) -> bytearray:
        """Make a vent mode packet."""
        value = bytearray(self.value)
        value[0] = 0x00 if vent_mode == VentMode.NONE else 0x11
        value[1] = vent_mode.value
        return super().make_packet(Command.STATUS, value)

    def make_fan_speed(self, fan_speed: FanSpeed) -> bytearray:
        """Make a fan speed packet."""
        value = bytearray(self.value)
        value[0] = 0x00 if fan_speed == FanSpeed.OFF else 0x11
        value[2] = fan_speed.value
        return super().make_packet(Command.STATUS, value)

    
class IAQPacket(KocomPacket):
    """Handles packets for IAQ devices."""

    def parse_data(self) -> list[Device]:
        """Parse IAQ-specific data."""
        devices: list[Device] = []

        sensor_mapping = {
            PM10: self.value[0],
            PM25: self.value[1],
            CO2: int.from_bytes(self.value[2:4], 'big'),
            VOC: int.from_bytes(self.value[4:6], 'big'),
            TEMPERATURE: self.value[6],
            HUMIDITY: self.value[7],
        }

        for sensor_id, state in sensor_mapping.items():
            if state > 0:
                _LOGGER.debug(f"{sensor_id}: {state}")
                device = Device(
                    device_type=self.device_name(upper=True),
                    device_id=self.device_id,
                    state={STATE: state},
                    sub_id=sensor_id,
                )
                devices.append(device)

        return devices
    
    def make_scan(self) -> bytearray:
        """Make a scan packet."""
        return super().make_packet(Command.SCAN, bytearray(self.value))


class GasPacket(KocomPacket):
    """Handles packets for gas devices."""
    
    def parse_data(self) -> list[Device]:
        """Parse gas-specific data."""
        device = Device(
            device_type=self.device_name(),
            room_id=self.room_id,
            device_id=self.device_id,
            state={POWER: self.command == Command.ON},
        )
        return [device]
    
    def make_scan(self) -> bytearray:
        """Make a scan packet."""
        return super().make_packet(Command.SCAN, bytearray(self.value))
    
    def make_power_status(self, power: bool) -> bytearray:
        """Make a power status packet."""
        if power:
            _LOGGER.debug(f"Gas device is on. Ignoring power status.")
            return
        return super().make_packet(Command.OFF, bytearray(self.value))
    

class MotionPacket(KocomPacket):
    """Handles packets for motion devices."""

    def parse_data(self) -> list[Device]:
        """Parse motion-specific data."""
        device = Device(
            device_type=self.device_name(),
            room_id=self.room_id,
            device_id=self.device_id,
            state={STATE: self.command == Command.DETECT, TIME: time.time()},
        )
        return [device]


class EVPacket(KocomPacket):
    """Handles packets for EV devices."""

    _class_last_data: ClassVar[dict[str, dict[str, Any]]] = {}

    def __init__(self, packet: bytes) -> None:
        """Initialize the packet."""
        super().__init__(packet)
        if self.device_id not in self._class_last_data:
            self._class_last_data[self.device_id] = {
                FLOOR: False,
            }
        self._last_data.update(self._class_last_data)

    def parse_data(self) -> list[Device]:
        """Parse EV-specific data."""
        devices: list[Device] = []

        power_state = False
        direction_state = Direction(self.value[0])
        floor_state = self.value[1]

        if self._last_data[self.device_id][FLOOR]:
            floor_state = floor_state if floor_state > 0 else "대기"
        
        devices.append(
            Device(
                device_type=self.device_name(upper=True),
                room_id=self.room_id,
                device_id=self.device_id,
                state={POWER: power_state},
            )
        )
        devices.append(
            Device(
                device_type=self.device_name(upper=True),
                room_id=self.room_id,
                device_id=self.device_id,
                state={STATE: direction_state.name},
                sub_id=DIRECTION,
            )
        )

        if (isinstance(floor_state, int) and (floor_state > 0)) or self._last_data[self.device_id][FLOOR]:
            _LOGGER.debug(f"Support EV floor: {floor_state}")
            self._last_data[self.device_id][FLOOR] = True
            
            devices.append(
                Device(
                    device_type=self.device_name(upper=True),
                    room_id=self.room_id,
                    device_id=self.device_id,
                    state={STATE: floor_state},
                    sub_id=FLOOR,
                )
            )
        
        return devices
    
    def make_power_status(self, power: bool) -> bytearray:
        """Make a power status packet."""
        if not power:
            _LOGGER.debug(f"EV device is off. Ignoring power status.")
            return
        return super().make_packet(Command.ON, bytearray(self.value))


class PacketParser:
    """Parses raw Kocom packets into specific device classes."""

    @staticmethod
    def parse(packet_data: bytes) -> KocomPacket:
        """Parse a raw packet into a specific packet class."""
        device_type = packet_data[7]
        return PacketParser._get_packet_instance(device_type, packet_data)

    @staticmethod
    def parse_state(packet: bytes, last_data: dict[str, Any] = None) -> list[KocomPacket]:
        """Parse device states from a packet."""
        base_packet = PacketParser.parse(packet)
        
        # Skip unsupported packet types
        if base_packet.device_type == DeviceType.WALLPAD:
            return []
        if base_packet.packet_type == PacketType.RECV and base_packet.command == Command.SCAN:
            return []

        # Update base packet's last_data if provided
        if last_data:
            base_packet._last_data.update(last_data)

        # Generate packets for each device
        parsed_packets: list[KocomPacket] = []
        for device_data in base_packet.parse_data():
            device_packet = deepcopy(base_packet)
            device_packet._device = device_data
            parsed_packets.append(device_packet)
        
        return parsed_packets

    @staticmethod
    def _get_packet_instance(device_type: int, packet_data: bytes) -> KocomPacket:
        """Retrieve the appropriate packet class based on device type."""
        device_class_map = {
            DeviceType.LIGHT.value: LightPacket,
            DeviceType.OUTLET.value: OutletPacket,
            DeviceType.THERMOSTAT.value: ThermostatPacket,
            DeviceType.AC.value: ACPacket,
            DeviceType.FAN.value: FanPacket,
            DeviceType.IAQ.value: IAQPacket,
            DeviceType.GAS.value: GasPacket,
            DeviceType.MOTION.value: MotionPacket,
            DeviceType.EV.value: EVPacket,
            DeviceType.WALLPAD.value: KocomPacket,
        }

        packet_class = device_class_map.get(device_type)
        if packet_class is None:
            _LOGGER.error(f"Unknown device type: {hex(device_type)}, data: {packet_data.hex()}")
            return KocomPacket(packet_data)
        
        if packet_data[5] == DeviceType.EV.value and packet_class == KocomPacket:
            packet_data = bytearray(packet_data)
            packet_data[5] = 0x01
            packet_data[7] = 0x44
            _LOGGER.debug(f"EV device detected from wallpad: {packet_data.hex()}")
            return EVPacket(bytes(packet_data))
        
        return packet_class(packet_data)
