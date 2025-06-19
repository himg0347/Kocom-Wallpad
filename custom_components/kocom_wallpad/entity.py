"""Entity classes for Kocom Wallpad."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity, RestoredExtraData
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .pywallpad.packet import KocomPacket

from .gateway import KocomGateway
from .util import process_string, create_dev_id, encode_bytes_to_base64
from .const import (
    DOMAIN,
    LOGGER,
    BRAND_NAME,
    MANUFACTURER,
    MODEL,
    SW_VERSION,
    DEVICE_TYPE,
    ROOM_ID,
    SUB_ID,
    PACKET_DATA,
    LAST_DATA,
)


class KocomEntity(RestoreEntity):
    """Base class for Kocom Wallpad entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    
    def __init__(
        self,
        gateway: KocomGateway,
        packet: KocomPacket,
    ) -> None:
        """Initialize the Kocom Wallpad entity."""
        self.gateway = gateway
        self.packet = packet
        self.packet_update_signal = f"{DOMAIN}_{self.gateway.host}_{self.device_id}"
        
        self._attr_unique_id = f"{BRAND_NAME}_{self.device_id}-{self.gateway.host}"
        self._attr_name = f"{BRAND_NAME} {self.device_name}"
        self._attr_extra_state_attributes = {
            DEVICE_TYPE: self.packet._device.device_type,
            ROOM_ID: self.packet._device.room_id,
            SUB_ID: self.packet._device.sub_id,
        }
        
    @property
    def device_id(self) -> str:
        """Return the device id."""
        return create_dev_id(
            self.packet._device.device_type,
            self.packet._device.room_id,
            self.packet._device.sub_id
        )
    
    @property
    def device_name(self) -> str:
        """Return the device name."""
        return process_string(self.device_id.replace("_", " "))
    
    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.gateway.host}_{self.packet._device.device_type}")},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=f"{BRAND_NAME} {process_string(self.packet._device.device_type)}",
            sw_version=SW_VERSION,
            via_device=(DOMAIN, self.gateway.host),
        )
        
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.gateway.connection.is_connected()
    
    @callback
    def async_handle_packet_update(self, packet: KocomPacket) -> None:
        """Handle packet update."""
        if self.packet.packet != packet.packet:
            self.packet = packet
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self.packet_update_signal,
                self.async_handle_packet_update
            )
        )
    
    @property
    def extra_restore_state_data(self) -> RestoredExtraData:
        """Return extra state data to be restored."""
        extra_data = {
            PACKET_DATA: encode_bytes_to_base64(self.packet.packet),
            LAST_DATA: self.packet._last_data,
        }
        return RestoredExtraData(extra_data)
    
    async def send_packet(self, packet: bytes) -> None:
        """Send a packet to the gateway."""
        await self.gateway.client.send_packet(packet)
