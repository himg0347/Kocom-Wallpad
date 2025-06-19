"""Sensor Platform for Kocom Wallpad."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)

from homeassistant.const import (
    Platform,
    UnitOfTemperature,
    PERCENTAGE,
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_MILLION,
    CONCENTRATION_PARTS_PER_BILLION,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .pywallpad.const import (
    STATE,
    PM10,
    PM25,
    CO2,
    VOC,
    TEMPERATURE,
    HUMIDITY,
    FLOOR,
)
from .pywallpad.enums import DeviceType
from .pywallpad.packet import (
    KocomPacket,
    FanPacket,
    IAQPacket,
    EVPacket,
)

from .gateway import KocomGateway
from .entity import KocomEntity
from .const import DOMAIN, LOGGER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kocom sensor platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]
    
    @callback
    def async_add_sensor(packet: KocomPacket) -> None:
        """Add new sensor entity."""
        if isinstance(packet, (FanPacket, IAQPacket, EVPacket)):
            async_add_entities([KocomSensorEntity(gateway, packet)])
    
    for entity in gateway.get_entities(Platform.SENSOR):
        async_add_sensor(entity)
        
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_sensor_add", async_add_sensor)
    )


class KocomSensorEntity(KocomEntity, SensorEntity):
    """Representation of a Kocom sensor."""
    
    def __init__(
        self,
        gateway: KocomGateway,
        packet: KocomPacket,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(gateway, packet)

        if self.packet.device_type != DeviceType.EV:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        """Return the state of the sensor."""
        return self.packet._device.state[STATE]
    
    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return the device class of the sensor."""
        if self.packet._device.sub_id == CO2:
            return SensorDeviceClass.CO2
        elif self.packet._device.sub_id == PM10:
            return SensorDeviceClass.PM10
        elif self.packet._device.sub_id == PM25:
            return SensorDeviceClass.PM25
        elif self.packet._device.sub_id == VOC:
            return SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS
        elif self.packet._device.sub_id == TEMPERATURE:
            return SensorDeviceClass.TEMPERATURE
        elif self.packet._device.sub_id == HUMIDITY:
            return SensorDeviceClass.HUMIDITY
        return None
    
    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the native unit of measurement."""
        if self.packet._device.sub_id == CO2:
            return CONCENTRATION_PARTS_PER_MILLION
        elif self.packet._device.sub_id == PM10:
            return CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
        elif self.packet._device.sub_id == PM25:
            return CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
        elif self.packet._device.sub_id == VOC:
            return CONCENTRATION_PARTS_PER_BILLION
        elif self.packet._device.sub_id == TEMPERATURE:
            return UnitOfTemperature.CELSIUS
        elif self.packet._device.sub_id == HUMIDITY:
            return PERCENTAGE
        elif self.packet._device.sub_id == FLOOR:
            return "층"
        return None
