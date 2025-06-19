"""Light Platform for Kocom Wallpad."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import LightEntity, ColorMode, ATTR_BRIGHTNESS

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .pywallpad.const import POWER, BRIGHTNESS, LEVEL
from .pywallpad.packet import KocomPacket, LightPacket

from .gateway import KocomGateway
from .entity import KocomEntity
from .const import DOMAIN, LOGGER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kocom light platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]
    
    @callback
    def async_add_light(packet: KocomPacket) -> None:
        """Add new light entity."""
        if isinstance(packet, LightPacket):
            async_add_entities([KocomLightEntity(gateway, packet)])

    for entity in gateway.get_entities(Platform.LIGHT):
        async_add_light(entity)
        
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_light_add", async_add_light)
    )


class KocomLightEntity(KocomEntity, LightEntity):
    """Representation of a Kocom light."""

    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF
    
    def __init__(
        self,
        gateway: KocomGateway,
        packet: KocomPacket,
    ) -> None:
        """Initialize the light."""
        super().__init__(gateway, packet)
        self.has_brightness = False
        self.max_brightness = 0

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        if self.packet._device.state.get(BRIGHTNESS):
            self.has_brightness = True
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self.max_brightness = len(self.packet._device.state[LEVEL]) + 1

        return self.packet._device.state[POWER]
    
    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        if self.packet._device.state[BRIGHTNESS] not in self.packet._device.state[LEVEL]:
            return 255
        return ((225 // self.max_brightness) * self.packet._device.state[BRIGHTNESS]) + 1
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on light."""
        if self.has_brightness:
            brightness = int(kwargs.get(ATTR_BRIGHTNESS, 255))
            brightness = ((brightness * 3) // 225) + 1
            if brightness not in self.packet._device.state[LEVEL]:
                brightness = 255
            make_packet = self.packet.make_brightness_status(brightness)
        else:
            make_packet = self.packet.make_power_status(True)

        await self.send_packet(make_packet)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off light."""
        make_packet = self.packet.make_power_status(False)
        await self.send_packet(make_packet)
