"""Fan Platform for Kocom Wallpad."""

from __future__ import annotations

from typing import Any, Optional

from homeassistant.components.fan import FanEntity, FanEntityFeature

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .pywallpad.const import POWER, VENT_MODE, FAN_SPEED
from .pywallpad.enums import VentMode, FanSpeed
from .pywallpad.packet import KocomPacket, FanPacket

from .gateway import KocomGateway
from .entity import KocomEntity
from .const import DOMAIN, LOGGER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kocom fan platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]
    
    @callback
    def async_add_fan(packet: KocomPacket) -> None:
        """Add new fan entity."""
        if isinstance(packet, FanPacket):
            async_add_entities([KocomFanEntity(gateway, packet)])
    
    for entity in gateway.get_entities(Platform.FAN):
        async_add_fan(entity)
        
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_fan_add", async_add_fan)
    )


class KocomFanEntity(KocomEntity, FanEntity):
    """Representation of a Kocom fan."""

    _attr_supported_features = (
        FanEntityFeature.SET_SPEED |
        FanEntityFeature.TURN_OFF |
        FanEntityFeature.TURN_ON |
        FanEntityFeature.PRESET_MODE
    )
    _attr_speed_count = 3
    _attr_preset_modes = list(VentMode.__members__.keys())
    _attr_speed_list = [
        FanSpeed.LOW.value,
        FanSpeed.MEDIUM.value,
        FanSpeed.HIGH.value,
    ]

    def __init__(
        self,
        gateway: KocomGateway,
        packet: KocomPacket,
    ) -> None:
        """Initialize the fan."""
        super().__init__(gateway, packet)

    @property
    def is_on(self) -> bool:
        """Return the state of the fan."""
        return self.packet._device.state[POWER]

    @property
    def percentage(self) -> int:
        """Return the current speed percentage."""
        fan_speed = self.packet._device.state[FAN_SPEED]
        if fan_speed == FanSpeed.OFF:
            return 0
        return ordered_list_item_to_percentage(self._attr_speed_list, fan_speed.value)
        
    @property
    def preset_mode(self) -> str:
        """Return the current preset mode."""
        vent_mode = self.packet._device.state[VENT_MODE]
        return vent_mode.name
    
    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        if percentage == 0:
            fan_speed = FanSpeed.OFF
        else:
            speed_item = percentage_to_ordered_list_item(self._attr_speed_list, percentage)
            fan_speed = FanSpeed(speed_item)

        make_packet = self.packet.make_fan_speed(fan_speed)
        await self.send_packet(make_packet)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        vent_mode = VentMode[preset_mode]
        make_packet = self.packet.make_vent_mode(vent_mode)
        await self.send_packet(make_packet)

    async def async_turn_on(
        self,
        speed: Optional[str] = None,
        percentage: Optional[int] = None,
        preset_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        make_packet = self.packet.make_power_status(True)
        await self.send_packet(make_packet)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        make_packet = self.packet.make_power_status(False)
        await self.send_packet(make_packet)
