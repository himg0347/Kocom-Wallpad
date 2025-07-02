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
from .const import DOMAIN, LOGGER, MIN_BRIGHTNESS, MAX_BRIGHTNESS, DEFAULT_BRIGHTNESS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kocom light platform."""
    try:
        gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]
        
        @callback
        def async_add_light(packet: KocomPacket) -> None:
            """Add new light entity."""
            try:
                if isinstance(packet, LightPacket):
                    entity = KocomLightEntity(gateway, packet)
                    async_add_entities([entity])
                    LOGGER.debug(f"Added light entity: {entity.unique_id}")
                else:
                    LOGGER.warning(f"Invalid packet type for light: {type(packet)}")
            except Exception as e:
                LOGGER.error(f"Failed to add light entity: {e}")

        # ??     :        ƼƼ  ߰          ó  
        existing_entities = gateway.get_entities(Platform.LIGHT)
        for entity in existing_entities:
            async_add_light(entity)
            
        entry.async_on_unload(
            async_dispatcher_connect(hass, f"{DOMAIN}_light_add", async_add_light)
        )
        
        LOGGER.info(f"Light platform setup completed with {len(existing_entities)} entities")
        
    except Exception as e:
        LOGGER.error(f"Failed to setup light platform: {e}")
        raise


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
        self._last_brightness = DEFAULT_BRIGHTNESS
        
        # ??     :  ʱ ȭ             Ȯ  
        self._update_brightness_support()

    def _update_brightness_support(self) -> None:
        """Update brightness support based on device state."""
        try:
            device_state = self.packet._device.state
            
            # ??     :                 
            if not device_state:
                LOGGER.warning(f"No device state for light {self.unique_id}")
                return
            
            #          Ȯ  
            if device_state.get(BRIGHTNESS) is not None and device_state.get(LEVEL):
                self.has_brightness = True
                self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
                self._attr_color_mode = ColorMode.BRIGHTNESS
                
                # ??     :         ִ         
                level_list = device_state.get(LEVEL, [])
                if isinstance(level_list, (list, tuple)) and level_list:
                    self.max_brightness = len(level_list)
                else:
                    LOGGER.warning(f"Invalid LEVEL data for {self.unique_id}: {level_list}")
                    self.max_brightness = 3  #  ⺻  
                    
                LOGGER.debug(f"Light {self.unique_id} supports brightness: max={self.max_brightness}")
            else:
                self.has_brightness = False
                self._attr_supported_color_modes = {ColorMode.ONOFF}
                self._attr_color_mode = ColorMode.ONOFF
                
        except Exception as e:
            LOGGER.error(f"Error updating brightness support for {self.unique_id}: {e}")
            #         ⺻       
            self.has_brightness = False
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        try:
            # ??     :            Ȯ   (            )
            self._update_brightness_support()
            
            device_state = self.packet._device.state
            if not device_state:
                return False
                
            return device_state.get(POWER, False)
            
        except Exception as e:
            LOGGER.error(f"Error getting power state for {self.unique_id}: {e}")
            return False
    
    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        if not self.has_brightness:
            return None
            
        try:
            device_state = self.packet._device.state
            if not device_state:
                return None
            
            current_brightness = device_state.get(BRIGHTNESS)
            level_list = device_state.get(LEVEL, [])
            
            # ??     :            
            if current_brightness is None:
                return None
                
            # ??     :           Ȯ  
            if not isinstance(level_list, (list, tuple)):
                LOGGER.warning(f"Invalid LEVEL data for {self.unique_id}")
                return DEFAULT_BRIGHTNESS
            
            # ??     :        Ⱑ                     
            if current_brightness not in level_list:
                #  ִ           
                return MAX_BRIGHTNESS
            
            # ??     :  ùٸ          (255     )
            if self.max_brightness > 0:
                brightness_ratio = (level_list.index(current_brightness) + 1) / self.max_brightness
                calculated_brightness = int(brightness_ratio * MAX_BRIGHTNESS)
                
                #          
                return max(MIN_BRIGHTNESS, min(MAX_BRIGHTNESS, calculated_brightness))
            
            return DEFAULT_BRIGHTNESS
            
        except Exception as e:
            LOGGER.error(f"Error calculating brightness for {self.unique_id}: {e}")
            return self._last_brightness
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on light."""
        try:
            if self.has_brightness and ATTR_BRIGHTNESS in kwargs:
                # ??     :              
                requested_brightness = int(kwargs[ATTR_BRIGHTNESS])
                
                #          
                requested_brightness = max(MIN_BRIGHTNESS, min(MAX_BRIGHTNESS, requested_brightness))
                
                # ??     :  ùٸ          
                device_state = self.packet._device.state
                level_list = device_state.get(LEVEL, [])
                
                if not level_list:
                    LOGGER.error(f"No brightness levels available for {self.unique_id}")
                    #  ⺻ ON           ü
                    make_packet = self.packet.make_power_status(True)
                else:
                    #   ⸦       ε        ȯ
                    brightness_ratio = requested_brightness / MAX_BRIGHTNESS
                    level_index = int(brightness_ratio * len(level_list))
                    level_index = max(0, min(len(level_list) - 1, level_index))
                    
                    target_brightness = level_list[level_index]
                    
                    LOGGER.debug(f"Setting brightness for {self.unique_id}: {requested_brightness} -> level {target_brightness}")
                    make_packet = self.packet.make_brightness_status(target_brightness)
                    
                self._last_brightness = requested_brightness
            else:
                #  Ϲ  ON    
                make_packet = self.packet.make_power_status(True)

            await self.send_packet(make_packet)
            
        except Exception as e:
            LOGGER.error(f"Failed to turn on light {self.unique_id}: {e}")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off light."""
        try:
            make_packet = self.packet.make_power_status(False)
            await self.send_packet(make_packet)
            
        except Exception as e:
            LOGGER.error(f"Failed to turn off light {self.unique_id}: {e}")

    # ??     :            Ʈ    ȣ  Ǵ   ޼   
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        try:
            super()._handle_coordinator_update()
            
            #            Ȯ  
            self._update_brightness_support()
            
        except Exception as e:
            LOGGER.error(f"Error handling coordinator update for {self.unique_id}: {e}")

    # ??     :               ߰   Ӽ 
    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        try:
            attrs = super().extra_state_attributes or {}
            
            device_state = self.packet._device.state
            if device_state:
                attrs.update({
                    "has_brightness": self.has_brightness,
                    "max_brightness": self.max_brightness,
                    "device_brightness": device_state.get(BRIGHTNESS),
                    "device_levels": device_state.get(LEVEL),
                    "last_brightness": self._last_brightness,
                })
            
            return attrs
            
        except Exception as e:
            LOGGER.error(f"Error getting extra attributes for {self.unique_id}: {e}")
            return None
