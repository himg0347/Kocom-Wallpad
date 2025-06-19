"""Binary Sensor Platform for Kocom Wallpad."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .pywallpad.const import STATE, ERROR_CODE, TIME
from .pywallpad.enums import DeviceType
from .pywallpad.packet import (
    KocomPacket,
    ThermostatPacket,
    FanPacket,
    MotionPacket,
)

from .gateway import KocomGateway
from .entity import KocomEntity
from .const import DOMAIN, LOGGER, DEVICE_TYPE, ROOM_ID, SUB_ID


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kocom binary sensor platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]
    
    @callback
    def async_add_binary_sensor(packet: KocomPacket) -> None:
        """Add new binary sensor entity."""
        if isinstance(packet, (ThermostatPacket, FanPacket, MotionPacket)):
            async_add_entities([KocomBinarySensorEntity(gateway, packet)])
    
    for entity in gateway.get_entities(Platform.BINARY_SENSOR):
        async_add_binary_sensor(entity)
        
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_binary_sensor_add", async_add_binary_sensor)
    )


class KocomBinarySensorEntity(KocomEntity, BinarySensorEntity):
    """Representation of a Kocom binary sensor."""
    
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        gateway: KocomGateway,
        packet: KocomPacket,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(gateway, packet)
        self._attr_is_on = self.packet._device.state[STATE]
        self._attr_extra_state_attributes = {
            DEVICE_TYPE: self.packet._device.device_type,
            ROOM_ID: self.packet._device.room_id,
            SUB_ID: self.packet._device.sub_id,
            ERROR_CODE: self.packet._device.state[ERROR_CODE],
        }

        if self.packet.device_type == DeviceType.MOTION:
            self._attr_device_class = BinarySensorDeviceClass.MOTION
            del self._attr_extra_state_attributes[ERROR_CODE]
            self._attr_extra_state_attributes[TIME] = self.packet._device.state[TIME]
