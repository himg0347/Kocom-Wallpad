"""Light Platform for Kocom Wallpad - Fix Version."""
from __future__ import annotations

import asyncio
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

# 🔧 수정 1: 간단한 설정 (복잡한 시스템 제거)
SIMPLE_COMMAND_DELAY = 0.1  # 짧은 대기시간
GLOBAL_LOCK = asyncio.Lock()  # 최소한의 보호만


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
        
        # 🔧 수정 2: 간단한 초기화
        if self.is_brightness:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
    
    @property
    def is_brightness(self) -> bool:
        """Return whether brightness is supported."""
        try:
            device_data = self.packet._last_data.get(self.packet.device_id, {})
            bri_lv = device_data.get("bri_lv")
            return bool(bri_lv)
        except (AttributeError, KeyError, TypeError):
            return False
    
    @property
    def max_brightness(self) -> int:
        """Return the maximum supported brightness."""
        try:
            device_data = self.packet._last_data.get(self.packet.device_id, {})
            bri_lv = device_data.get("bri_lv", [])
            # 🔧 수정 3: 문제없던 계산 방식 복원
            return len(bri_lv) if bri_lv else 3
        except (AttributeError, KeyError, TypeError):
            return 3
    
    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        try:
            return bool(self.packet._device.state.get(POWER, False))
        except (AttributeError, KeyError, TypeError):
            return False
    
    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        if not self.is_brightness:
            return 255 if self.is_on else 0
            
        try:
            current_brightness = self.packet._device.state.get(BRIGHTNESS, 0)
            level_list = self.packet._device.state.get(LEVEL, [])
            
            if not level_list:
                return 255 if self.is_on else 0
            
            # 🔧 수정 4: 밝기 계산 (원본 코드의 오류만 수정)
            if current_brightness not in level_list:
                return 255 if self.is_on else 0
            
            # 원본과 최대한 유사하게 유지하되 오류만 수정
            max_level = len(level_list)
            level_index = level_list.index(current_brightness) + 1
            
            # 원본: ((225 // self.max_brightness) * brightness) + 1
            # 수정: 225 → 255, // → /, +1 제거로 범위 문제 해결
            brightness_255 = int((level_index * 255) / max_level)
            return max(1, min(255, brightness_255))
            
        except (AttributeError, KeyError, TypeError, ValueError, ZeroDivisionError):
            return 255 if self.is_on else 0
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on light - minimal protection."""
        # 🔧 수정 5: 최소한의 락만 사용 (호환성 유지)
        async with GLOBAL_LOCK:
            try:
                if self.is_brightness and ATTR_BRIGHTNESS in kwargs:
                    await self._handle_brightness_command(kwargs[ATTR_BRIGHTNESS])
                else:
                    await self._handle_power_command(True)
                    
                # 🔧 수정 6: 짧은 대기시간
                await asyncio.sleep(SIMPLE_COMMAND_DELAY)
                
            except Exception as e:
                LOGGER.error("Failed to turn on light %s: %s", self.entity_id, e)
                raise
    
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off light."""
        async with GLOBAL_LOCK:
            try:
                await self._handle_power_command(False)
                await asyncio.sleep(SIMPLE_COMMAND_DELAY)
                
            except Exception as e:
                LOGGER.error("Failed to turn off light %s: %s", self.entity_id, e)
                raise
    
    async def _handle_brightness_command(self, ha_brightness: int) -> None:
        """Handle brightness control command."""
        try:
            level_list = self.packet._device.state.get(LEVEL, [])
            if not level_list:
                # 밝기 레벨이 없으면 단순 ON
                await self._handle_power_command(True)
                return
            
            # 🔧 수정 7: 밝기 변환 (원본 오류만 수정)
            max_level = len(level_list)
            
            # 원본: brightness = ((brightness * 3) // 225) + 1
            # 수정: 하드코딩된 3을 max_level로, 225를 255로, // 제거, +1 제거
            level_index = max(1, min(max_level, int((ha_brightness * max_level) / 255)))
            target_brightness = level_list[level_index - 1]  # 0-based index
            
            make_packet = self.packet.make_brightness_status(target_brightness)
            await self.send_packet(make_packet)
            
        except Exception as e:
            LOGGER.error("Brightness command error for %s: %s", self.entity_id, e)
            raise
    
    async def _handle_power_command(self, power_on: bool) -> None:
        """Handle power on/off command."""
        try:
            make_packet = self.packet.make_power_status(power_on)
            await self.send_packet(make_packet)
            
        except Exception as e:
            LOGGER.error("Power command error for %s: %s", self.entity_id, e)
            raise
    
    # 🔧 수정 8: 속성 (디버깅 정보만 최소한 추가)
    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return device specific state attributes."""
        try:
            return {
                "device_id": self.packet.device_id,
                "supports_brightness": self.is_brightness,
                "max_brightness_level": self.max_brightness,
            }
        except Exception:
            return None