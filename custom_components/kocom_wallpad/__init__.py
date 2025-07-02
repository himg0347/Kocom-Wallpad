"""The Kocom Wallpad component."""

from __future__ import annotations

from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

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
    # ?? 개선: 전체 예외 처리 추가
    try:
        LOGGER.info(f"Setting up Kocom Wallpad integration for {entry.title}")
        
        # ?? 개선: 게이트웨이 초기화 예외 처리
        try:
            gateway: KocomGateway = KocomGateway(hass, entry)
        except Exception as e:
            LOGGER.error(f"Failed to initialize gateway: {e}")
            raise ConfigEntryError(f"Gateway initialization failed: {e}")
        
        # ?? 개선: 연결 실패 시 상세한 처리
        try:
            connection_success = await gateway.async_connect()
            if not connection_success:
                LOGGER.error("Failed to establish connection to wallpad")
                await _safe_cleanup_gateway(gateway)
                raise ConfigEntryNotReady("Cannot connect to wallpad device")
                
        except Exception as e:
            LOGGER.error(f"Connection attempt failed: {e}")
            await _safe_cleanup_gateway(gateway)
            raise ConfigEntryNotReady(f"Connection failed: {e}")
        
        # ?? 개선: 데이터 저장 전 검증
        hass.data.setdefault(DOMAIN, {})
        if entry.entry_id in hass.data[DOMAIN]:
            LOGGER.warning(f"Entry {entry.entry_id} already exists, cleaning up old instance")
            old_gateway = hass.data[DOMAIN][entry.entry_id]
            await _safe_cleanup_gateway(old_gateway)
        
        hass.data[DOMAIN][entry.entry_id] = gateway
        
        # ?? 개선: 엔티티 등록 예외 처리
        try:
            await gateway.async_update_entity_registry()
            await gateway.async_start()
        except Exception as e:
            LOGGER.error(f"Failed to initialize entities: {e}")
            # 정리 작업
            hass.data[DOMAIN].pop(entry.entry_id, None)
            await _safe_cleanup_gateway(gateway)
            raise ConfigEntryError(f"Entity initialization failed: {e}")

        # ?? 개선: 플랫폼 설정 예외 처리
        try:
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        except Exception as e:
            LOGGER.error(f"Failed to setup platforms: {e}")
            # 정리 작업
            hass.data[DOMAIN].pop(entry.entry_id, None)
            await _safe_cleanup_gateway(gateway)
            raise ConfigEntryError(f"Platform setup failed: {e}")
        
        # ?? 개선: 종료 이벤트 리스너 등록
        def _handle_stop_event(event):
            """Handle Home Assistant stop event."""
            hass.async_create_task(_safe_cleanup_gateway(gateway))
        
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _handle_stop_event)
        )

        LOGGER.info(f"Kocom Wallpad integration setup completed for {entry.title}")
        return True

    except (ConfigEntryError, ConfigEntryNotReady):
        # 이미 처리된 예외는 재발생
        raise
    except Exception as e:
        LOGGER.error(f"Unexpected error during setup: {e}")
        raise ConfigEntryError(f"Setup failed with unexpected error: {e}")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the Kocom Wallpad integration."""
    LOGGER.info(f"Unloading Kocom Wallpad integration for {entry.title}")
    
    try:
        # ?? 개선: 플랫폼 언로드 예외 처리
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        
        if unload_ok:
            # ?? 개선: 게이트웨이 정리 예외 처리
            gateway: KocomGateway = hass.data[DOMAIN].pop(entry.entry_id, None)
            if gateway:
                await _safe_cleanup_gateway(gateway)
            else:
                LOGGER.warning(f"Gateway not found for entry {entry.entry_id}")
            
            LOGGER.info(f"Successfully unloaded Kocom Wallpad integration for {entry.title}")
        else:
            LOGGER.error(f"Failed to unload platforms for {entry.title}")
    
    except Exception as e:
        LOGGER.error(f"Error during unload: {e}")
        # ?? 개선: 에러가 있어도 강제 정리 시도
        gateway: KocomGateway = hass.data[DOMAIN].pop(entry.entry_id, None)
        if gateway:
            await _safe_cleanup_gateway(gateway)
        unload_ok = False
    
    return unload_ok


# ?? 개선: 안전한 정리 함수 추가
async def _safe_cleanup_gateway(gateway: KocomGateway) -> None:
    """Safely cleanup gateway resources."""
    if gateway is None:
        return
        
    try:
        LOGGER.debug("Starting gateway cleanup")
        
        # 연결 해제 시도
        try:
            await gateway.async_disconnect()
        except Exception as e:
            LOGGER.warning(f"Error during gateway disconnect: {e}")
        
        # 추가 정리 작업 (게이트웨이에 close 메서드가 있는 경우)
        if hasattr(gateway, 'async_close'):
            try:
                await gateway.async_close()
            except Exception as e:
                LOGGER.warning(f"Error during gateway close: {e}")
        
        LOGGER.debug("Gateway cleanup completed")
        
    except Exception as e:
        LOGGER.error(f"Critical error during gateway cleanup: {e}")


# ?? 개선: 통합구성요소 상태 확인 함수 추가
async def async_get_integration_status(hass: HomeAssistant, entry_id: str) -> dict:
    """Get integration status for diagnostics."""
    if DOMAIN not in hass.data or entry_id not in hass.data[DOMAIN]:
        return {"status": "not_loaded", "error": "Integration not found"}
    
    try:
        gateway: KocomGateway = hass.data[DOMAIN][entry_id]
        
        # 게이트웨이 상태 확인
        status = {
            "status": "loaded",
            "connected": hasattr(gateway, 'is_connected') and gateway.is_connected(),
            "entities_count": len(getattr(gateway, 'entities', [])),
        }
        
        # 연결 통계 추가 (connection 객체가 있는 경우)
        if hasattr(gateway, 'connection') and hasattr(gateway.connection, 'get_connection_stats'):
            status["connection_stats"] = gateway.connection.get_connection_stats()
        
        return status
        
    except Exception as e:
        return {"status": "error", "error": str(e)}
