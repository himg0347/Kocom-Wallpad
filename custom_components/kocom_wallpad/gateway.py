"""Gateway module for Kocom Wallpad."""

from __future__ import annotations

import asyncio
from typing import Optional

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

        # ??     :            
        if not self.host or not self.port:
            raise ValueError("Host and port must be provided")

        self.connection = Connection(self.host, self.port)
        self.client: Optional[KocomClient] = None
        self.entities: dict[Platform, dict[str, KocomPacket]] = {}
        
        # ??     :            ? 
        self._is_starting = False
        self._is_stopping = False
        self._packet_lock = asyncio.Lock()  #   ? o      u      
        self._entity_callbacks: set = set()  #  ?      
    
    async def async_connect(self) -> bool:
        """Connect to the gateway."""
        try:
            LOGGER.debug(f"Attempting to connect to {self.host}:{self.port}")
            
            # ??     : connection.connect()   ?   ?  
            connection_success = await self.connection.connect()
            if not connection_success:
                LOGGER.error("Connection method returned False")
                return False
            
            # ??     :             ?  
            if not self.connection.is_connected():
                LOGGER.error("Connection established but status check failed")
                return False
            
            # ??     : ?   ? ?  ? ?
            try:
                self.client = KocomClient(self.connection)
                LOGGER.info(f"Successfully connected to {self.host}:{self.port}")
                return True
            except Exception as e:
                LOGGER.error(f"Failed to initialize client: {e}")
                await self.connection.close()
                return False
                
        except Exception as e:
            LOGGER.error(f"Connection failed with exception: {e}")
            return False
    
    async def async_disconnect(self) -> None:
        """Disconnect from the gateway."""
        if self._is_stopping:
            return
        
        self._is_stopping = True
        LOGGER.debug("Starting gateway disconnect")
        
        try:
            # ??     :  u?           
            # 1.  ?      
            self._entity_callbacks.clear()
            
            # 2. ?   ? ?     
            if self.client:
                try:
                    await self.client.stop()
                    LOGGER.debug("Client stopped successfully")
                except Exception as e:
                    LOGGER.warning(f"Error stopping client: {e}")
                finally:
                    self.client = None
            
            # 3.   ??     
            try:
                self.entities.clear()
                LOGGER.debug("Entities cleared")
            except Exception as e:
                LOGGER.warning(f"Error clearing entities: {e}")
            
            # 4.          
            try:
                await self.connection.close()
                LOGGER.debug("Connection closed")
            except Exception as e:
                LOGGER.warning(f"Error closing connection: {e}")
                
        except Exception as e:
            LOGGER.error(f"Error during disconnect: {e}")
        finally:
            self._is_stopping = False

    async def async_start(self) -> None:
        """Start the gateway."""
        if self._is_starting:
            LOGGER.warning("Gateway start already in progress")
            return
        
        if not self.client:
            raise RuntimeError("Client not initialized. Call async_connect() first.")
        
        self._is_starting = True
        try:
            LOGGER.debug("Starting gateway client")
            
            # ??     : ?   ? ?           o  
            try:
                await self.client.start()
                LOGGER.debug("Client started successfully")
            except Exception as e:
                LOGGER.error(f"Failed to start client: {e}")
                raise
            
            # ??     :  ?           o  
            try:
                callback_id = self.client.add_device_callback(self._handle_device_update)
                self._entity_callbacks.add(callback_id)
                LOGGER.debug("Device callback registered")
            except Exception as e:
                LOGGER.error(f"Failed to register callback: {e}")
                # ?   ? ?     
                await self.client.stop()
                raise
                
        except Exception as e:
            LOGGER.error(f"Gateway start failed: {e}")
            raise
        finally:
            self._is_starting = False
        
    async def async_close(self, event: Event) -> None:
        """Close the gateway."""
        LOGGER.debug("Gateway close requested")
        await self.async_disconnect()
    
    def get_entities(self, platform: Platform) -> list[KocomPacket]:
        """Get the entities for the platform."""
        return list(self.entities.get(platform, {}).values())

    async def _async_fetch_last_packets(self, entity_id: str) -> list[KocomPacket]:
        """Fetch the last packets for the entity."""
        try:
            restored_states = restore_state.async_get(self.hass)
            state = restored_states.last_states.get(entity_id)
            
            if not state or not state.extra_data:
                LOGGER.debug(f"No restored state found for {entity_id}")
                return []
            
            state_dict = state.extra_data.as_dict()
            packet_data = state_dict.get(PACKET_DATA)
            if not packet_data:
                LOGGER.debug(f"No packet data in restored state for {entity_id}")
                return []
            
            # ??     :    ?       o  
            try:
                packet = decode_base64_to_bytes(packet_data)
            except Exception as e:
                LOGGER.warning(f"Failed to decode packet data for {entity_id}: {e}")
                return []
            
            last_data = state_dict.get(LAST_DATA)
            LOGGER.debug(f"Restored last data for {entity_id}: {last_data}")

            # ??     :  ?       o  
            try:
                packets = PacketParser.parse_state(packet, last_data)
                LOGGER.debug(f"Successfully parsed {len(packets)} packets for {entity_id}")
                return packets
            except Exception as e:
                LOGGER.warning(f"Failed to parse packet for {entity_id}: {e}")
                return []
                
        except Exception as e:
            LOGGER.error(f"Error fetching last packets for {entity_id}: {e}")
            return []
    
    async def async_update_entity_registry(self) -> None:
        """Update the entity registry."""
        try:
            entity_registry = er.async_get(self.hass)
            entities = er.async_entries_for_config_entry(
                entity_registry, self.entry.entry_id
            )
            
            LOGGER.debug(f"Found {len(entities)} entities to restore")
            
            # ??     :   ? o             
            restore_tasks = []
            for entity in entities:
                task = self._restore_single_entity(entity.entity_id)
                restore_tasks.append(task)
            
            #           ?       ?      
            if restore_tasks:
                results = await asyncio.gather(*restore_tasks, return_exceptions=True)
                
                #     ?  
                success_count = 0
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        LOGGER.warning(f"Failed to restore entity {entities[i].entity_id}: {result}")
                    else:
                        success_count += result
                
                LOGGER.info(f"Successfully restored {success_count} entities")
            
        except Exception as e:
            LOGGER.error(f"Error updating entity registry: {e}")
    
    async def _restore_single_entity(self, entity_id: str) -> int:
        """Restore a single entity and return count of restored packets."""
        try:
            packets = await self._async_fetch_last_packets(entity_id)
            restored_count = 0
            
            for packet in packets:
                try:
                    await self._handle_device_update(packet)
                    restored_count += 1
                except Exception as e:
                    LOGGER.warning(f"Failed to handle restored packet for {entity_id}: {e}")
            
            return restored_count
        except Exception as e:
            LOGGER.warning(f"Failed to restore entity {entity_id}: {e}")
            return 0
    
    async def _handle_device_update(self, packet: KocomPacket) -> None:
        """Handle device update with improved safety."""
        if not packet:
            LOGGER.warning("Received null packet")
            return
        
        # ??     :    u      
        async with self._packet_lock:
            try:
                # ??     :   ?     
                if not hasattr(packet, '_device') or not packet._device:
                    LOGGER.warning(f"Packet missing device information: {packet}")
                    return
                
                device = packet._device
                
                # ??     :     ?           
                if not all(hasattr(device, attr) for attr in ['device_type', 'room_id', 'sub_id']):
                    LOGGER.warning(f"Device missing required attributes: {device}")
                    return
                
                platform = self.parse_platform(packet)
                if platform is None:
                    LOGGER.debug(f"No platform mapping for packet type: {type(packet).__name__}")
                    return
                
                # ??     : dev_id           o  
                try:
                    dev_id = create_dev_id(device.device_type, device.room_id, device.sub_id)
                except Exception as e:
                    LOGGER.warning(f"Failed to create device ID: {e}")
                    return
                
                # ??     :         ? ?
                if platform not in self.entities:
                    self.entities[platform] = {}
                
                # ??     :  ?      ?  
                is_new_entity = dev_id not in self.entities[platform]
                
                #   ??    /      ?
                self.entities[platform][dev_id] = packet
                
                # ??     :   ?           o  
                try:
                    if is_new_entity:
                        add_signal = f"{DOMAIN}_{platform.value}_add"
                        async_dispatcher_send(self.hass, add_signal, packet)
                        LOGGER.debug(f"New entity added: {dev_id} ({platform.value})")
                    
                    packet_update_signal = f"{DOMAIN}_{self.host}_{dev_id}"
                    async_dispatcher_send(self.hass, packet_update_signal, packet)
                    
                except Exception as e:
                    LOGGER.warning(f"Failed to send update signal for {dev_id}: {e}")
                
            except Exception as e:
                LOGGER.error(f"Error handling device update: {e}")
        
    def parse_platform(self, packet: KocomPacket) -> Platform | None:
        """Parse the platform from the packet with improved validation."""
        try:
            # ??     :   ? ?       
            if not isinstance(packet, KocomPacket):
                LOGGER.warning(f"Invalid packet type: {type(packet)}")
                return None
            
            platform = PLATFORM_MAPPING.get(type(packet))
            if platform is None:
                LOGGER.debug(f"No platform mapping for: {type(packet).__name__}")
                return None
            
            # ??     : sub_id            
            platform_packet_types = (ThermostatPacket, FanPacket, EVPacket)
            if isinstance(packet, platform_packet_types):
                try:
                    sub_id = getattr(packet._device, 'sub_id', None) if packet._device else None
                    if sub_id:
                        if ERROR in sub_id:
                            platform = Platform.BINARY_SENSOR
                        elif CO2 in sub_id or TEMPERATURE in sub_id:
                            platform = Platform.SENSOR
                        elif sub_id in {DIRECTION, FLOOR}:  # EV
                            platform = Platform.SENSOR
                except Exception as e:
                    LOGGER.warning(f"Error checking sub_id: {e}")
                    #  ?            
                    
            return platform
            
        except Exception as e:
            LOGGER.error(f"Error parsing platform: {e}")
            return None
    
    # ??     :      ?    ?     ? 
    def is_connected(self) -> bool:
        """Check if gateway is connected and ready."""
        return (
            self.connection.is_connected() and 
            self.client is not None and 
            not self._is_stopping
        )
    
    def get_stats(self) -> dict:
        """Get gateway statistics."""
        return {
            "connected": self.is_connected(),
            "host": self.host,
            "port": self.port,
            "entities_count": sum(len(entities) for entities in self.entities.values()),
            "platforms": list(self.entities.keys()),
            "callbacks_count": len(self._entity_callbacks),
            "is_starting": self._is_starting,
            "is_stopping": self._is_stopping,
        }
