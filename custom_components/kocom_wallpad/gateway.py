"""Gateway module for Kocom Wallpad."""

from __future__ import annotations

from homeassistant.const import Platform, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, Event
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers import entity_registry as er, restore_state

from dataclasses import dataclass

from .pywallpad.client import KocomClient
from .pywallpad.const import ERROR, CO2, TEMPERATURE, DIRECTION, FLOOR
from .pywallpad.packet import (
    KocomPacket,
    ThermostatPacket,
    FanPacket,
    EVPacket,
    PacketParser,
)

from .connection import Connection
from .util import create_dev_id, decode_base64_to_bytes
from .const import LOGGER, DOMAIN, PACKET_DATA, LAST_DATA, PLATFORM_MAPPING


class KocomGateway:
    """Represents a Kocom Wallpad gateway."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the KocomGateway."""
        self.hass = hass
        self.entry = entry
        self.host = entry.data.get(CONF_HOST)
        self.port = entry.data.get(CONF_PORT)

        self.connection = Connection(self.host, self.port)
        self.client: KocomClient = KocomClient(self.connection)
        self.entities: dict[Platform, dict[str, KocomPacket]] = {}
    
    async def async_connect(self) -> bool:
        """Connect to the gateway."""
        try:
            await self.connection.connect()
            return self.connection.is_connected()
        except Exception as e:
            LOGGER.error(f"Failed to connect to the gateway: {e}")
            return False
    
    async def async_disconnect(self) -> None:
        """Disconnect from the gateway."""
        if self.client:
            await self.client.stop()
        self.entities.clear()
        await self.connection.close()

    async def async_start(self) -> None:
        """Start the gateway."""
        await self.client.start()
        self.client.add_device_callback(self._handle_device_update)
        
    async def async_close(self, event: Event) -> None:
        """Close the gateway."""
        await self.async_disconnect()
    
    def get_entities(self, platform: Platform) -> list[KocomPacket]:
        """Get the entities for the platform."""
        return list(self.entities.get(platform, {}).values())

    async def _async_fetch_last_packets(self, entity_id: str) -> list[KocomPacket]:
        """Fetch the last packets for the entity."""
        restored_states = restore_state.async_get(self.hass)
        state = restored_states.last_states.get(entity_id)
        
        if not state or not state.extra_data:
            return []
        
        packet_data = state.extra_data.as_dict().get(PACKET_DATA)
        if not packet_data:
            return []
        
        packet = decode_base64_to_bytes(packet_data)
        last_data = state.extra_data.as_dict().get(LAST_DATA)
        LOGGER.debug(f"Last data: {last_data}")

        return PacketParser.parse_state(packet, last_data)
    
    async def async_update_entity_registry(self) -> None:
        """Update the entity registry."""
        entity_registry = er.async_get(self.hass)
        entities = er.async_entries_for_config_entry(
            entity_registry, self.entry.entry_id
        )
        for entity in entities:
            packets = await self._async_fetch_last_packets(entity.entity_id)
            for packet in packets:
                await self._handle_device_update(packet)
    
    async def _handle_device_update(self, packet: KocomPacket) -> None:
        """Handle device update."""
        platform = self.parse_platform(packet)
        if platform is None:
            LOGGER.error(f"Failed to parse platform from packet: {packet}")
            return
        
        if platform not in self.entities:
            self.entities[platform] = {}
        
        device = packet._device
        dev_id = create_dev_id(device.device_type, device.room_id, device.sub_id)

        if dev_id not in self.entities[platform]:
            self.entities[platform][dev_id] = packet

            add_signal = f"{DOMAIN}_{platform.value}_add"
            async_dispatcher_send(self.hass, add_signal, packet)
        
        packet_update_signal = f"{DOMAIN}_{self.host}_{dev_id}"
        async_dispatcher_send(self.hass, packet_update_signal, packet)
        
    def parse_platform(self, packet: KocomPacket) -> Platform | None:
        """Parse the platform from the packet."""
        platform = PLATFORM_MAPPING.get(type(packet))
        if platform is None:
            LOGGER.warning(f"Unrecognized platform type: {type(packet).__name__}")
            return None
        
        platform_packet_types = (ThermostatPacket, FanPacket, EVPacket)
        if isinstance(packet, platform_packet_types) and (sub_id := packet._device.sub_id):
            if ERROR in sub_id:
                platform = Platform.BINARY_SENSOR
            elif CO2 in sub_id:
                platform = Platform.SENSOR
            elif TEMPERATURE in sub_id:
                platform = Platform.SENSOR
            elif sub_id in {DIRECTION, FLOOR}:  # EV
                platform = Platform.SENSOR
                
        return platform
    