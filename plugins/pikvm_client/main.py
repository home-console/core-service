"""
PiKVM Client Service Plugin - управление PiKVM устройствами через HTTP API и WebSocket.
"""
import logging
import threading
import websocket
import pymongo
from datetime import datetime, timezone
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

from settings import PikvmSettings
from controllers.pikvm import PikvmController
from controllers.WebSocket import PikvmWebSocketClient

logger = logging.getLogger(__name__)


class MongoDBHandler:
    """Обработчик MongoDB для сохранения WebSocket событий."""
    
    def __init__(self, settings: PikvmSettings):
        self.client = None
        self.db = None
        self.collection = None
        self.is_connected = False
        self.settings = settings

        try:
            self.client = pymongo.MongoClient(
                settings.mongodb_uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000
            )
            self.client.admin.command('ismaster')
            self.db = self.client[settings.mongodb_database]
            self.collection = self.db[settings.mongodb_collection]
            self.is_connected = True
            logger.info("MongoDB connection established successfully")
        except pymongo.errors.ConnectionFailure as e:
            logger.warning(f"Could not connect to MongoDB: {e}. Continuing without database.")
        except Exception as e:
            logger.warning(f"Unexpected error connecting to MongoDB: {e}. Continuing without database.")

    def save_websocket_event(self, event_data: Dict[str, Any]):
        """Сохранить WebSocket событие в MongoDB."""
        if not self.is_connected:
            logger.debug("MongoDB not connected. Skipping event save.")
            return

        try:
            event_data['timestamp'] = datetime.now(timezone.utc)
            result = self.collection.insert_one(event_data)
            logger.debug(f"Saved event to MongoDB. Insert ID: {result.inserted_id}")
        except Exception as e:
            logger.error(f"Failed to save event to MongoDB: {e}")

    def close(self):
        """Закрыть соединение с MongoDB."""
        if self.client:
            try:
                self.client.close()
                logger.info("MongoDB connection closed")
            except Exception as e:
                logger.warning(f"Error closing MongoDB connection: {e}")
            finally:
                self.is_connected = False


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
        
        # Проверяем, заданы ли обязательные настройки
        if not self.settings.host:
            logger.warning("⚠️ PiKVM Client plugin loaded but not configured. Please set PIKVM_HOST, PIKVM_USERNAME, and PIKVM_PASSWORD via environment variables or plugin configuration.")
            self.controller = None
            self.mongodb_handler = None
            self.websocket_thread = None
            self.websocket_client = None
        else:
            # Создаем контроллер
            self.controller = PikvmController(self.settings)
            logger.info("PikvmController initialized successfully")
            
            # Инициализируем MongoDB handler (опционально)
            self.mongodb_handler = MongoDBHandler(self.settings)
            
            # Тестируем HTTP соединение
            try:
                http_status = self.controller.test_http_connect()
                logger.info(f"HTTP Connection Status: {http_status}")
            except Exception as e:
                logger.warning(f"HTTP connection test failed: {e}")
            
            # Запускаем WebSocket клиент (если включен)
            self.websocket_thread = None
            self.websocket_client = None
            if self.config.get('enable_websocket', True) if hasattr(self.config, 'get') else True:
                self._start_websocket_client()
        
        # Регистрируем роуты
        self._register_routes()
        
        logger.info("✅ PiKVM Client plugin loaded")
    
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
        
        mongodb_uri = config_get('mongodb_uri') or os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
        if mongodb_uri:
            settings_dict['mongodb_uri'] = mongodb_uri
        
        mongodb_database = config_get('mongodb_database') or os.getenv('MONGODB_DATABASE', 'pikvm_data')
        if mongodb_database:
            settings_dict['mongodb_database'] = mongodb_database
        
        mongodb_collection = config_get('mongodb_collection') or os.getenv('MONGODB_COLLECTION', 'websocket_events')
        if mongodb_collection:
            settings_dict['mongodb_collection'] = mongodb_collection
        
        debug = config_get('debug')
        if debug is None:
            debug = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')
        settings_dict['debug'] = debug
        
        settings = PikvmSettings(**settings_dict)
        
        # Настраиваем логирование
        settings.configure_logging()
        
        return settings
    
    def _start_websocket_client(self):
        """Запустить WebSocket клиент."""
        try:
            if self.settings.debug:
                websocket.enableTrace(True)
            
            self.websocket_client = PikvmWebSocketClient(self.controller, self.mongodb_handler)
            self.websocket_thread = threading.Thread(target=self.websocket_client.connect)
            self.websocket_thread.daemon = True
            self.websocket_thread.start()
            logger.info("WebSocket client started successfully")
        except Exception as e:
            logger.error(f"Failed to start WebSocket client: {e}")
    
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
    
    # ========== API Endpoints ==========
    
    def _check_configured(self):
        """Проверить, что плагин настроен."""
        if not self.controller:
            raise HTTPException(
                status_code=503, 
                detail="Plugin is not configured. Please set PIKVM_HOST, PIKVM_USERNAME, and PIKVM_PASSWORD."
            )
    
    async def get_system_info(self, fields: Optional[str] = None):
        """Получить информацию о системе PiKVM."""
        self._check_configured()
        try:
            fields_list = fields.split(',') if fields else None
            info = self.controller.get_system_info(fields=fields_list)
            return JSONResponse(info)
        except Exception as e:
            logger.error(f"Error getting system info: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_power_state(self):
        """Получить состояние питания."""
        self._check_configured()
        try:
            state = self.controller.get_atx_state()
            return JSONResponse(state)
        except Exception as e:
            logger.error(f"Error getting power state: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def control_power(self, payload: Dict[str, Any]):
        """Управление питанием."""
        self._check_configured()
        try:
            action = payload.get('action', 'on')
            wait = payload.get('wait', False)
            result = self.controller.power_control(action=action, wait=wait)
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"Error controlling power: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def click_power_button(self, payload: Dict[str, Any]):
        """Нажать кнопку питания."""
        self._check_configured()
        try:
            button = payload.get('button', 'power')
            wait = payload.get('wait', False)
            result = self.controller.power_button_click(button=button, wait=wait)
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"Error clicking power button: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_gpio_state(self):
        """Получить состояние GPIO."""
        self._check_configured()
        try:
            state = self.controller.get_gpio_state()
            return JSONResponse(state)
        except Exception as e:
            logger.error(f"Error getting GPIO state: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def switch_gpio(self, payload: Dict[str, Any]):
        """Переключить GPIO канал."""
        self._check_configured()
        try:
            channel = payload.get('channel')
            state = payload.get('state')
            wait = payload.get('wait', False)
            
            if channel is None or state is None:
                raise HTTPException(status_code=400, detail="channel and state are required")
            
            result = self.controller.switch_gpio(channel=channel, state=state, wait=wait)
            return JSONResponse(result)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error switching GPIO: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def pulse_gpio(self, payload: Dict[str, Any]):
        """Импульс GPIO канала."""
        self._check_configured()
        try:
            channel = payload.get('channel')
            delay = payload.get('delay')
            wait = payload.get('wait', False)
            
            if channel is None:
                raise HTTPException(status_code=400, detail="channel is required")
            
            result = self.controller.pulse_gpio(channel=channel, delay=delay, wait=wait)
            return JSONResponse(result)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error pulsing GPIO: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_msd_state(self):
        """Получить состояние MSD."""
        self._check_configured()
        try:
            state = self.controller.get_msd_state()
            return JSONResponse(state)
        except Exception as e:
            logger.error(f"Error getting MSD state: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_system_logs(self, follow: bool = False, seek: Optional[int] = None):
        """Получить логи системы."""
        self._check_configured()
        try:
            logs = self.controller.get_system_log(follow=follow, seek=seek)
            return JSONResponse({"logs": logs})
        except Exception as e:
            logger.error(f"Error getting system logs: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    async def health_check(self):
        """Проверка здоровья плагина."""
        if not self.controller:
            return JSONResponse({
                "status": "not_configured",
                "configured": False,
                "message": "Plugin is not configured. Please set PIKVM_HOST, PIKVM_USERNAME, and PIKVM_PASSWORD."
            }, status_code=503)
        
        try:
            # Проверяем HTTP соединение
            http_status = self.controller.test_http_connect()
            
            health = {
                "status": "healthy" if http_status == 200 else "degraded",
                "configured": True,
                "http_connection": http_status == 200,
                "websocket_active": self.websocket_thread is not None and self.websocket_thread.is_alive() if self.websocket_thread else False,
                "mongodb_connected": self.mongodb_handler.is_connected if self.mongodb_handler else False
            }
            
            status_code = 200 if health["status"] == "healthy" else 503
            return JSONResponse(health, status_code=status_code)
        except Exception as e:
            logger.error(f"Error in health check: {e}", exc_info=True)
            return JSONResponse({
                "status": "unhealthy",
                "configured": True,
                "error": str(e)
            }, status_code=503)
    
    async def on_unload(self):
        """Очистка при выгрузке плагина."""
        try:
            # Останавливаем WebSocket клиент
            if self.websocket_client:
                self.websocket_client.stop()
            
            # Закрываем MongoDB соединение
            if self.mongodb_handler:
                self.mongodb_handler.close()
            
            logger.info("👋 PiKVM Client plugin unloaded")
        except Exception as e:
            logger.error(f"Error during plugin unload: {e}", exc_info=True)

