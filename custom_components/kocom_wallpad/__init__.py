"""The Kocom Wallpad component."""

from __future__ import annotations

from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .gateway import KocomGateway
from .const import DOMAIN, LOGGER

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.FAN,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Kocom Wallpad integration."""
    gateway: KocomGateway = KocomGateway(hass, entry)
    
    if not await gateway.async_connect():
        await gateway.async_disconnect()
        return False
    
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = gateway
    await gateway.async_update_entity_registry()
    await gateway.async_start()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, gateway.async_close)
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the Kocom Wallpad integration."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        gateway: KocomGateway = hass.data[DOMAIN].pop(entry.entry_id)
        await gateway.async_disconnect()
    
    return unload_ok
