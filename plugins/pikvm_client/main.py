"""
PiKVM Client Service Plugin - управление PiKVM устройствами через HTTP API и WebSocket.
"""
import logging
import threading
import websocket
import asyncio
from typing import Dict, Any, Optional
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from home_console_sdk.plugin import InternalPluginBase

# Импорты из src
import sys
from pathlib import Path

# Добавляем путь к src для импортов
plugin_dir = Path(__file__).parent
src_dir = plugin_dir / "src"
sys.path.insert(0, str(src_dir))

from settings import PikvmSettings, PikvmDeviceConfig
from controllers.pikvm import PikvmController
from controllers.WebSocket import PikvmWebSocketClient

logger = logging.getLogger(__name__)


class PikvmClientPlugin(InternalPluginBase):
    """Плагин для управления PiKVM устройствами."""
    
    id = "pikvm_client"
    name = "PiKVM Client Service"
    version = "1.0.0"
    description = "Plugin for controlling PiKVM devices via HTTP API and WebSocket"
    
    async def on_load(self):
        """Инициализация плагина."""
        self.router = APIRouter()
        
        # Инициализируем настройки из конфигурации плагина
        self.settings = self._create_settings()
        
        # Словарь контроллеров по device_id
        self.controllers: Dict[str, PikvmController] = {}
        # Словарь WebSocket клиентов по device_id
        self.websocket_clients: Dict[str, PikvmWebSocketClient] = {}
        self.websocket_threads: Dict[str, threading.Thread] = {}
        
        # Сохраняем ссылку на event loop для публикации событий из потоков
        try:
            self._main_event_loop = asyncio.get_running_loop()
        except RuntimeError:
            # Если loop не запущен (например, при тестировании), будет None
            self._main_event_loop = None
        
        # Получаем список всех устройств
        devices = self.settings.get_all_devices()
        
        if not devices:
            logger.warning("⚠️ PiKVM Client plugin loaded but not configured. Please configure devices via plugin configuration.")
        else:
            # Создаем контроллеры для каждого устройства
            for device_config in devices:
                try:
                    controller = PikvmController(device_config, device_id=device_config.device_id)
                    self.controllers[device_config.device_id] = controller
                    logger.info(f"✅ PikvmController initialized for device '{device_config.device_id}' ({device_config.host})")
                    
                    # Тестируем HTTP соединение
                    try:
                        http_status = controller.test_http_connect()
                        logger.info(f"HTTP Connection Status for '{device_config.device_id}': {http_status}")
                    except Exception as e:
                        logger.warning(f"HTTP connection test failed for '{device_config.device_id}': {e}")
                    
                    # Запускаем WebSocket клиент (если включен)
                    enable_ws = self.config.get('enable_websocket', True) if hasattr(self.config, 'get') else True
                    if enable_ws:
                        self._start_websocket_client(device_config.device_id, controller)
                except Exception as e:
                    logger.error(f"Failed to initialize controller for device '{device_config.device_id}': {e}")
        
        # Регистрируем роуты
        self._register_routes()
        
        logger.info(f"✅ PiKVM Client plugin loaded with {len(self.controllers)} device(s)")
    
    def _create_settings(self) -> PikvmSettings:
        """Создать настройки из конфигурации плагина."""
        # Получаем конфигурацию плагина
        # plugin.config может быть объектом PluginConfig или словарем
        if hasattr(self.config, 'get'):
            # Это объект PluginConfig из SDK
            config_get = lambda key, default=None: self.config.get(key, default)
        elif isinstance(self.config, dict):
            # Это словарь
            config_get = lambda key, default=None: self.config.get(key, default)
        else:
            # Неизвестный тип, используем пустой словарь
            config_get = lambda key, default=None: default
        
        # Используем значения из конфига или переменные окружения
        # Фильтруем None значения, чтобы Pydantic не ругался
        settings_dict = {}
        
        # Проверяем, есть ли список устройств в конфиге
        devices_config = config_get('devices')
        if devices_config and isinstance(devices_config, list):
            # Новый формат: список устройств
            devices = []
            for device_data in devices_config:
                if isinstance(device_data, dict):
                    devices.append(PikvmDeviceConfig(**device_data))
            settings_dict['devices'] = devices
        else:
            # Старый формат: одно устройство через host
            host = config_get('host') or os.getenv('PIKVM_HOST')
            if host:
                settings_dict['host'] = host
            
            username = config_get('username') or os.getenv('PIKVM_USERNAME', 'admin')
            if username:
                settings_dict['username'] = username
            
            password = config_get('password') or os.getenv('PIKVM_PASSWORD', 'admin')
            if password:
                settings_dict['password'] = password
            
            secret = config_get('secret') or os.getenv('PIKVM_SECRET')
            if secret:
                settings_dict['secret'] = secret
        
        debug = config_get('debug')
        if debug is None:
            debug = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')
        settings_dict['debug'] = debug
        
        settings = PikvmSettings(**settings_dict)
        
        # Настраиваем логирование
        settings.configure_logging()
        
        return settings
    
    def _start_websocket_client(self, device_id: str, controller: PikvmController):
        """Запустить WebSocket клиент для устройства."""
        try:
            if self.settings.debug:
                websocket.enableTrace(True)
            
            # Создаем callback для публикации событий через event bus
            # Используем метод плагина напрямую - он уже async и работает с event bus
            async def emit_event(event_name: str, data: dict):
                """Callback для публикации событий через event bus плагина"""
                try:
                    # Используем метод emit_event из InternalPluginBase
                    # Он автоматически добавляет префикс plugin_id
                    await self.emit_event(event_name, data)
                except Exception as e:
                    logger.warning(f"Failed to emit event '{event_name}' via event bus: {e}")
            
            ws_client = PikvmWebSocketClient(
                controller, 
                device_id=device_id,
                event_emitter=emit_event if self._main_event_loop else None,
                main_event_loop=self._main_event_loop
            )
            self.websocket_clients[device_id] = ws_client
            ws_thread = threading.Thread(target=ws_client.connect)
            ws_thread.daemon = True
            ws_thread.start()
            self.websocket_threads[device_id] = ws_thread
            logger.info(f"WebSocket client started successfully for device '{device_id}'")
        except Exception as e:
            logger.error(f"Failed to start WebSocket client for device '{device_id}': {e}")
    
    def _register_routes(self):
        """Зарегистрировать FastAPI роуты."""
        # System info
        self.router.add_api_route(
            "/info", 
            self.get_system_info, 
            methods=["GET"],
            operation_id="pikvm_client_get_system_info"
        )
        
        # Power control
        self.router.add_api_route(
            "/power", 
            self.get_power_state, 
            methods=["GET"],
            operation_id="pikvm_client_get_power_state"
        )
        self.router.add_api_route(
            "/power", 
            self.control_power, 
            methods=["POST"],
            operation_id="pikvm_client_control_power"
        )
        self.router.add_api_route(
            "/power/click", 
            self.click_power_button, 
            methods=["POST"],
            operation_id="pikvm_client_click_power_button"
        )
        
        # GPIO control
        self.router.add_api_route(
            "/gpio", 
            self.get_gpio_state, 
            methods=["GET"],
            operation_id="pikvm_client_get_gpio_state"
        )
        self.router.add_api_route(
            "/gpio/switch", 
            self.switch_gpio, 
            methods=["POST"],
            operation_id="pikvm_client_switch_gpio"
        )
        self.router.add_api_route(
            "/gpio/pulse", 
            self.pulse_gpio, 
            methods=["POST"],
            operation_id="pikvm_client_pulse_gpio"
        )
        
        # MSD management
        self.router.add_api_route(
            "/msd", 
            self.get_msd_state, 
            methods=["GET"],
            operation_id="pikvm_client_get_msd_state"
        )
        
        # System logs
        self.router.add_api_route(
            "/logs", 
            self.get_system_logs, 
            methods=["GET"],
            operation_id="pikvm_client_get_system_logs"
        )
        
        # Health check
        self.router.add_api_route(
            "/health", 
            self.health_check, 
            methods=["GET"],
            operation_id="pikvm_client_health_check"
        )
        
        # List devices
        self.router.add_api_route(
            "/devices", 
            self.list_devices, 
            methods=["GET"],
            operation_id="pikvm_client_list_devices"
        )
    
    # ========== API Endpoints ==========
    
    def _get_controller(self, device_id: Optional[str] = None) -> PikvmController:
        """Получить контроллер для устройства."""
        if not self.controllers:
            raise HTTPException(
                status_code=503, 
                detail="Plugin is not configured. Please configure devices via plugin configuration."
            )
        
        # Если device_id не указан и есть только одно устройство, используем его
        if not device_id:
            if len(self.controllers) == 1:
                device_id = list(self.controllers.keys())[0]
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"device_id is required. Available devices: {list(self.controllers.keys())}"
                )
        
        controller = self.controllers.get(device_id)
        if not controller:
            raise HTTPException(
                status_code=404,
                detail=f"Device '{device_id}' not found. Available devices: {list(self.controllers.keys())}"
            )
        
        return controller
    
    async def list_devices(self):
        """Получить список всех настроенных устройств."""
        try:
            devices = []
            for device_id, controller in self.controllers.items():
                device_config = self.settings.get_device_config(device_id)
                devices.append({
                    "device_id": device_id,
                    "host": device_config.host if device_config else controller.host,
                    "enabled": device_config.enabled if device_config else True
                })
            return JSONResponse({"devices": devices, "count": len(devices)})
        except Exception as e:
            logger.error(f"Error listing devices: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_system_info(self, device_id: Optional[str] = None, fields: Optional[str] = None):
        """Получить информацию о системе PiKVM."""
        controller = self._get_controller(device_id)
        try:
            fields_list = fields.split(',') if fields else None
            info = controller.get_system_info(fields=fields_list)
            info['device_id'] = device_id or list(self.controllers.keys())[0]
            return JSONResponse(info)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting system info: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_power_state(self, device_id: Optional[str] = None):
        """Получить состояние питания."""
        controller = self._get_controller(device_id)
        try:
            state = controller.get_atx_state()
            state['device_id'] = device_id or list(self.controllers.keys())[0]
            return JSONResponse(state)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting power state: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def control_power(self, payload: Dict[str, Any]):
        """Управление питанием."""
        device_id = payload.get('device_id')
        controller = self._get_controller(device_id)
        try:
            action = payload.get('action', 'on')
            wait = payload.get('wait', False)
            result = controller.power_control(action=action, wait=wait)
            result['device_id'] = device_id or list(self.controllers.keys())[0]
            
            # Публикуем событие
            await self.emit_event("power.controlled", {
                "device_id": device_id or list(self.controllers.keys())[0],
                "action": action,
                "wait": wait,
                "result": result
            })
            
            return JSONResponse(result)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error controlling power: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def click_power_button(self, payload: Dict[str, Any]):
        """Нажать кнопку питания."""
        device_id = payload.get('device_id')
        controller = self._get_controller(device_id)
        try:
            button = payload.get('button', 'power')
            wait = payload.get('wait', False)
            result = controller.power_button_click(button=button, wait=wait)
            result['device_id'] = device_id or list(self.controllers.keys())[0]
            
            # Публикуем событие
            await self.emit_event("power.button_clicked", {
                "device_id": device_id or list(self.controllers.keys())[0],
                "button": button,
                "wait": wait,
                "result": result
            })
            
            return JSONResponse(result)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error clicking power button: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_gpio_state(self, device_id: Optional[str] = None):
        """Получить состояние GPIO."""
        controller = self._get_controller(device_id)
        try:
            state = controller.get_gpio_state()
            state['device_id'] = device_id or list(self.controllers.keys())[0]
            return JSONResponse(state)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting GPIO state: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def switch_gpio(self, payload: Dict[str, Any]):
        """Переключить GPIO канал."""
        device_id = payload.get('device_id')
        controller = self._get_controller(device_id)
        try:
            channel = payload.get('channel')
            state = payload.get('state')
            wait = payload.get('wait', False)
            
            if channel is None or state is None:
                raise HTTPException(status_code=400, detail="channel and state are required")
            
            result = controller.switch_gpio(channel=channel, state=state, wait=wait)
            result['device_id'] = device_id or list(self.controllers.keys())[0]
            
            # Публикуем событие
            await self.emit_event("gpio.switched", {
                "device_id": device_id or list(self.controllers.keys())[0],
                "channel": channel,
                "state": state,
                "wait": wait,
                "result": result
            })
            
            return JSONResponse(result)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error switching GPIO: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def pulse_gpio(self, payload: Dict[str, Any]):
        """Импульс GPIO канала."""
        device_id = payload.get('device_id')
        controller = self._get_controller(device_id)
        try:
            channel = payload.get('channel')
            delay = payload.get('delay')
            wait = payload.get('wait', False)
            
            if channel is None:
                raise HTTPException(status_code=400, detail="channel is required")
            
            result = controller.pulse_gpio(channel=channel, delay=delay, wait=wait)
            result['device_id'] = device_id or list(self.controllers.keys())[0]
            
            # Публикуем событие
            await self.emit_event("gpio.pulsed", {
                "device_id": device_id or list(self.controllers.keys())[0],
                "channel": channel,
                "delay": delay,
                "wait": wait,
                "result": result
            })
            
            return JSONResponse(result)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error pulsing GPIO: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_msd_state(self, device_id: Optional[str] = None):
        """Получить состояние MSD."""
        controller = self._get_controller(device_id)
        try:
            state = controller.get_msd_state()
            state['device_id'] = device_id or list(self.controllers.keys())[0]
            return JSONResponse(state)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting MSD state: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_system_logs(self, device_id: Optional[str] = None, follow: bool = False, seek: Optional[int] = None):
        """Получить логи системы."""
        controller = self._get_controller(device_id)
        try:
            logs = controller.get_system_log(follow=follow, seek=seek)
            return JSONResponse({"logs": logs, "device_id": device_id or list(self.controllers.keys())[0]})
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting system logs: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def health_check(self, device_id: Optional[str] = None):
        """Проверка здоровья плагина или конкретного устройства."""
        if not self.controllers:
            return JSONResponse({
                "status": "not_configured",
                "configured": False,
                "message": "Plugin is not configured. Please configure devices via plugin configuration."
            }, status_code=503)
        
        # Если device_id не указан, возвращаем общий статус
        if not device_id:
            devices_health = {}
            overall_healthy = True
            
            for dev_id, controller in self.controllers.items():
                try:
                    http_status = controller.test_http_connect()
                    ws_active = self.websocket_threads.get(dev_id) is not None and self.websocket_threads[dev_id].is_alive() if dev_id in self.websocket_threads else False
                    devices_health[dev_id] = {
                        "status": "healthy" if http_status == 200 else "degraded",
                        "http_connection": http_status == 200,
                        "websocket_active": ws_active
                    }
                    if http_status != 200:
                        overall_healthy = False
                except Exception as e:
                    devices_health[dev_id] = {
                        "status": "unhealthy",
                        "error": str(e)
                    }
                    overall_healthy = False
            
            health = {
                "status": "healthy" if overall_healthy else "degraded",
                "configured": True,
                "devices": devices_health
            }
            
            status_code = 200 if health["status"] == "healthy" else 503
            return JSONResponse(health, status_code=status_code)
        
        # Проверка конкретного устройства
        try:
            controller = self._get_controller(device_id)
            http_status = controller.test_http_connect()
            ws_active = self.websocket_threads.get(device_id) is not None and self.websocket_threads[device_id].is_alive() if device_id in self.websocket_threads else False
            
            health = {
                "status": "healthy" if http_status == 200 else "degraded",
                "device_id": device_id,
                "configured": True,
                "http_connection": http_status == 200,
                "websocket_active": ws_active
            }
            
            status_code = 200 if health["status"] == "healthy" else 503
            return JSONResponse(health, status_code=status_code)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in health check for device '{device_id}': {e}", exc_info=True)
            return JSONResponse({
                "status": "unhealthy",
                "device_id": device_id,
                "configured": True,
                "error": str(e)
            }, status_code=503)
    
    async def on_unload(self):
        """Очистка при выгрузке плагина."""
        try:
            # Останавливаем все WebSocket клиенты
            for device_id, ws_client in self.websocket_clients.items():
                try:
                    ws_client.stop()
                    logger.info(f"Stopped WebSocket client for device '{device_id}'")
                except Exception as e:
                    logger.error(f"Error stopping WebSocket client for device '{device_id}': {e}")
            
            logger.info("👋 PiKVM Client plugin unloaded")
        except Exception as e:
            logger.error(f"Error during plugin unload: {e}", exc_info=True)

