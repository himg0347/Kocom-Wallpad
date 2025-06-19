"""Climate platform for Kocom Wallpad."""

from __future__ import annotations

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACMode,
    PRESET_AWAY,
    PRESET_NONE,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
)

from homeassistant.const import Platform, UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .pywallpad.const import (
    POWER,
    AWAY_MODE,
    OP_MODE,
    FAN_MODE,
    CURRENT_TEMP,
    TARGET_TEMP,
)
from .pywallpad.enums import OpMode, FanMode
from .pywallpad.packet import KocomPacket, ThermostatPacket, ACPacket

from .gateway import KocomGateway
from .entity import KocomEntity
from .const import DOMAIN, LOGGER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kocom climate platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]
    
    @callback
    def async_add_climate(packet: KocomPacket) -> None:
        """Add new climate entity."""
        if isinstance(packet, ThermostatPacket):
            async_add_entities([KocomThermostatEntity(gateway, packet)])
        elif isinstance(packet, ACPacket):
            async_add_entities([KocomACEntity(gateway, packet)])
    
    for entity in gateway.get_entities(Platform.CLIMATE):
        async_add_climate(entity)
        
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_climate_add", async_add_climate)
    )


class KocomThermostatEntity(KocomEntity, ClimateEntity):
    """Representation of a Kocom thermostat."""

    _enable_turn_on_off_backwards_compatibility = False
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [PRESET_AWAY, PRESET_NONE]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.PRESET_MODE
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_max_temp = 40
    _attr_min_temp = 5
    _attr_target_temperature_step = 1

    def __init__(self, gateway: KocomGateway, packet: KocomPacket) -> None:
        """Initialize the thermostat."""
        super().__init__(gateway, packet)

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""
        return HVACMode.HEAT if self.packet._device.state[POWER] else HVACMode.OFF

    @property
    def preset_mode(self) -> str:
        """Return the current preset mode."""
        return PRESET_AWAY if self.packet._device.state[AWAY_MODE] else PRESET_NONE

    @property
    def current_temperature(self) -> int:
        """Return the current temperature."""
        return self.packet._device.state[CURRENT_TEMP]

    @property
    def target_temperature(self) -> int:
        """Return the target temperature."""
        return self.packet._device.state[TARGET_TEMP]

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        hvac_to_power = {
            HVACMode.OFF: False,
            HVACMode.HEAT: True,
        }
        power = hvac_to_power.get(hvac_mode)
        if power is None:
            raise ValueError(f"Unknown HVAC mode: {hvac_mode}")

        make_packet = self.packet.make_power_status(power)
        await self.send_packet(make_packet)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode."""
        preset_to_away = {
            PRESET_AWAY: True,
            PRESET_NONE: False,
        }
        away_mode = preset_to_away.get(preset_mode)
        if away_mode is None:
            raise ValueError(f"Unknown preset mode: {preset_mode}")

        make_packet = self.packet.make_away_status(away_mode)
        await self.send_packet(make_packet)

    async def async_set_temperature(self, **kwargs) -> None:
        """Set the target temperature."""
        if ATTR_TEMPERATURE not in kwargs:
            raise ValueError("Missing temperature")
        
        target_temp = int(kwargs[ATTR_TEMPERATURE])
        make_packet = self.packet.make_target_temp(target_temp)
        await self.send_packet(make_packet)


class KocomACEntity(KocomEntity, ClimateEntity):
    """Representation of a Kocom climate."""

    _enable_turn_on_off_backwards_compatibility = False
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.FAN_ONLY,
        HVACMode.DRY,
        HVACMode.AUTO,
    ]
    _attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.FAN_MODE
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_max_temp = 30
    _attr_min_temp = 18
    _attr_target_temperature_step = 1

    def __init__(self, gateway: KocomGateway, packet: KocomPacket) -> None:
        """Initialize the climate."""
        super().__init__(gateway, packet)

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        if self.packet._device.state[POWER]:
            op_mode = self.packet._device.state[OP_MODE]
            return {
                OpMode.COOL: HVACMode.COOL,
                OpMode.FAN_ONLY: HVACMode.FAN_ONLY,
                OpMode.DRY: HVACMode.DRY,
                OpMode.AUTO: HVACMode.AUTO,
            }.get(op_mode, HVACMode.OFF)
        return HVACMode.OFF

    @property
    def fan_mode(self) -> str:
        """Return current fan mode."""
        return {
            FanMode.LOW: FAN_LOW,
            FanMode.MEDIUM: FAN_MEDIUM,
            FanMode.HIGH: FAN_HIGH,
        }.get(self.packet._device.state[FAN_MODE])

    @property
    def current_temperature(self) -> int:
        """Return the current temperature."""
        return self.packet._device.state[CURRENT_TEMP]

    @property
    def target_temperature(self) -> int:
        """Return the target temperature."""
        return self.packet._device.state[TARGET_TEMP]

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set a new target HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            make_packet = self.packet.make_power_status(False)
        else:
            hvac_to_op_mode = {
                HVACMode.COOL: OpMode.COOL,
                HVACMode.FAN_ONLY: OpMode.FAN_ONLY,
                HVACMode.DRY: OpMode.DRY,
                HVACMode.AUTO: OpMode.AUTO,
            }
            op_mode = hvac_to_op_mode.get(hvac_mode)
            if op_mode is None:
                raise ValueError(f"Unknown HVAC mode: {hvac_mode}")
            make_packet = self.packet.make_op_mode(op_mode)

        await self.send_packet(make_packet)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set a new target fan mode."""
        fan_speed = {
            FAN_LOW: FanMode.LOW,
            FAN_MEDIUM: FanMode.MEDIUM,
            FAN_HIGH: FanMode.HIGH,
        }.get(fan_mode)
        if fan_speed is None:
            raise ValueError(f"Unknown fan mode: {fan_mode}")

        make_packet = self.packet.make_fan_mode(fan_speed)
        await self.send_packet(make_packet)

    async def async_set_temperature(self, **kwargs) -> None:
        """Set a new target temperature."""
        if ATTR_TEMPERATURE not in kwargs:
            raise ValueError("Missing temperature")
        
        target_temp = int(kwargs[ATTR_TEMPERATURE])
        make_packet = self.packet.make_target_temp(target_temp)
        await self.send_packet(make_packet)
