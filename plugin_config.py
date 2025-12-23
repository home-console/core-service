"""
Plugin Configuration System: централизованное управление конфигурацией плагинов.

Отвечает за:
- Загрузку конфигурации из различных источников (файлы, env vars, БД)
- Валидацию конфигурации плагинов
- Управление режимами работы на основе конфигурации
- Поддержку различных форматов конфигурации (YAML, JSON)
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
import yaml

from pydantic import BaseModel, ValidationError
from .plugin_mode_manager import PluginMode


logger = logging.getLogger(__name__)


class ConfigSource(Enum):
    """Источники конфигурации"""
    FILE = "file"
    ENV = "env"
    DATABASE = "database"
    DEFAULT = "default"


@dataclass
class PluginConfig:
    """Конфигурация плагина"""
    plugin_id: str
    mode: PluginMode = PluginMode.IN_PROCESS
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    source: ConfigSource = ConfigSource.DEFAULT
    health_check_interval: int = 30
    restart_policy: str = "always"  # always, on_failure, never
    resources: Dict[str, Any] = field(default_factory=dict)  # memory, cpu limits
    dependencies: list[str] = field(default_factory=list)
    supported_modes: list[PluginMode] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class PluginConfigManager:
    """Менеджер конфигурации плагинов"""
    
    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = config_dir or os.getenv("PLUGIN_CONFIG_DIR", "./config")
        self.configs: Dict[str, PluginConfig] = {}
        self._lock = asyncio.Lock()
        
        # Создаем директорию конфигов если не существует
        Path(self.config_dir).mkdir(parents=True, exist_ok=True)
        
        logger.info(f"PluginConfigManager initialized with config dir: {self.config_dir}")
    
    async def load_all_configs(self):
        """Загрузить все конфигурации плагинов"""
        # Загрузить из файлов
        await self._load_from_files()
        
        # Загрузить из переменных окружения
        await self._load_from_env()
        
        # Загрузить из БД (если доступна)
        await self._load_from_database()
    
    async def _load_from_files(self):
        """Загрузить конфигурации из файлов"""
        config_extensions = ['.yaml', '.yml', '.json']
        
        for file_path in Path(self.config_dir).iterdir():
            if file_path.suffix.lower() in config_extensions:
                try:
                    if file_path.suffix.lower() in ['.yaml', '.yml']:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            config_data = yaml.safe_load(f)
                    else:  # .json
                        with open(file_path, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                    
                    if isinstance(config_data, dict):
                        # Это конфиг для одного плагина
                        await self._process_plugin_config(config_data, ConfigSource.FILE)
                    elif isinstance(config_data, list):
                        # Это список конфигов
                        for plugin_config in config_data:
                            await self._process_plugin_config(plugin_config, ConfigSource.FILE)
                
                except Exception as e:
                    logger.error(f"Error loading config from {file_path}: {e}")
    
    async def _load_from_env(self):
        """Загрузить конфигурации из переменных окружения"""
        # Проверяем переменные вида PLUGIN_{ID}_{PARAM}
        for key, value in os.environ.items():
            if key.startswith('PLUGIN_') and '_' in key[7:]:  # PLUGIN_
                parts = key[7:].split('_', 1)  # Разделяем на ID и PARAM
                if len(parts) == 2:
                    plugin_id = parts[0].lower()
                    param = parts[1].lower()
                    
                    # Создаем или обновляем конфиг для плагина
                    if plugin_id not in self.configs:
                        self.configs[plugin_id] = PluginConfig(plugin_id=plugin_id)
                    
                    config = self.configs[plugin_id]
                    
                    # Обработка специальных параметров
                    if param == 'mode':
                        try:
                            mode = PluginMode(value.lower())
                            config.mode = mode
                        except ValueError:
                            logger.warning(f"Invalid mode '{value}' for plugin {plugin_id}")
                    elif param == 'enabled':
                        config.enabled = value.lower() in ['true', '1', 'yes', 'on']
                    elif param == 'health_check_interval':
                        try:
                            config.health_check_interval = int(value)
                        except ValueError:
                            logger.warning(f"Invalid health_check_interval '{value}' for plugin {plugin_id}")
    
    async def _load_from_database(self):
        """Загрузить конфигурации из БД (заглушка, будет реализована позже)"""
        # Пока что заглушка - в реальном приложении здесь будет код для загрузки из БД
        pass
    
    async def _process_plugin_config(self, config_data: Dict[str, Any], source: ConfigSource):
        """Обработать конфигурацию плагина"""
        try:
            plugin_id = config_data.get('plugin_id') or config_data.get('id')
            if not plugin_id:
                logger.warning(f"Config missing plugin_id: {config_data}")
                return
            
            # Создаем или обновляем конфиг
            if plugin_id not in self.configs:
                self.configs[plugin_id] = PluginConfig(plugin_id=plugin_id)
            
            config = self.configs[plugin_id]
            
            # Обновляем поля
            if 'mode' in config_data:
                try:
                    config.mode = PluginMode(config_data['mode'])
                except ValueError:
                    logger.warning(f"Invalid mode '{config_data['mode']}' for plugin {plugin_id}")
            
            if 'enabled' in config_data:
                config.enabled = bool(config_data['enabled'])
            
            if 'config' in config_data:
                config.config.update(config_data['config'])
            
            if 'health_check_interval' in config_data:
                config.health_check_interval = int(config_data['health_check_interval'])
            
            if 'restart_policy' in config_data:
                config.restart_policy = str(config_data['restart_policy'])
            
            if 'resources' in config_data:
                config.resources.update(config_data['resources'])
            
            if 'dependencies' in config_data:
                config.dependencies.extend(config_data['dependencies'])
            
            if 'supported_modes' in config_data:
                supported_modes = []
                for mode_str in config_data['supported_modes']:
                    try:
                        supported_modes.append(PluginMode(mode_str))
                    except ValueError:
                        logger.warning(f"Invalid supported mode '{mode_str}' for plugin {plugin_id}")
                config.supported_modes = supported_modes
            
            if 'metadata' in config_data:
                config.metadata.update(config_data['metadata'])
            
            config.source = source
            
            logger.info(f"Loaded config for plugin {plugin_id} from {source.value}")
            
        except Exception as e:
            logger.error(f"Error processing config for plugin: {e}")
    
    async def get_config(self, plugin_id: str) -> Optional[PluginConfig]:
        """Получить конфигурацию плагина"""
        if plugin_id not in self.configs:
            # Создаем конфиг по умолчанию
            self.configs[plugin_id] = PluginConfig(plugin_id=plugin_id)
        
        return self.configs[plugin_id]
    
    async def set_config(self, plugin_id: str, config: PluginConfig):
        """Установить конфигурацию плагина"""
        async with self._lock:
            self.configs[plugin_id] = config
    
    async def update_config(self, plugin_id: str, updates: Dict[str, Any]) -> PluginConfig:
        """Обновить конфигурацию плагина"""
        async with self._lock:
            if plugin_id not in self.configs:
                self.configs[plugin_id] = PluginConfig(plugin_id=plugin_id)
            
            config = self.configs[plugin_id]
            
            # Обновляем поля
            for key, value in updates.items():
                if hasattr(config, key):
                    if key == 'mode' and isinstance(value, str):
                        try:
                            setattr(config, key, PluginMode(value))
                        except ValueError:
                            logger.warning(f"Invalid mode value '{value}' for plugin {plugin_id}")
                    elif key == 'supported_modes' and isinstance(value, list):
                        supported_modes = []
                        for mode_str in value:
                            try:
                                supported_modes.append(PluginMode(mode_str))
                            except ValueError:
                                logger.warning(f"Invalid supported mode '{mode_str}' for plugin {plugin_id}")
                        setattr(config, key, supported_modes)
                    else:
                        setattr(config, key, value)
                else:
                    # Добавляем в пользовательскую конфигурацию
                    config.config[key] = value
            
            logger.info(f"Updated config for plugin {plugin_id}")
            return config
    
    async def save_config_to_file(self, plugin_id: str, format: str = 'yaml'):
        """Сохранить конфигурацию плагина в файл"""
        config = await self.get_config(plugin_id)
        if not config:
            raise ValueError(f"No config found for plugin {plugin_id}")
        
        file_path = Path(self.config_dir) / f"{plugin_id}.{format}"
        
        config_dict = {
            'plugin_id': config.plugin_id,
            'mode': config.mode.value,
            'enabled': config.enabled,
            'config': config.config,
            'health_check_interval': config.health_check_interval,
            'restart_policy': config.restart_policy,
            'resources': config.resources,
            'dependencies': config.dependencies,
            'supported_modes': [m.value for m in config.supported_modes],
            'metadata': config.metadata
        }
        
        try:
            if format.lower() == 'json':
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(config_dict, f, indent=2, ensure_ascii=False)
            else:  # yaml
                with open(file_path, 'w', encoding='utf-8') as f:
                    yaml.dump(config_dict, f, default_flow_style=False, allow_unicode=True)
            
            logger.info(f"Saved config for plugin {plugin_id} to {file_path}")
            
        except Exception as e:
            logger.error(f"Error saving config for plugin {plugin_id}: {e}")
            raise
    
    async def list_configs(self) -> Dict[str, PluginConfig]:
        """Получить все конфигурации"""
        return self.configs.copy()
    
    async def validate_config(self, config: PluginConfig) -> bool:
        """Проверить валидность конфигурации"""
        # Проверяем, что поддерживаемый режим входит в список поддерживаемых
        if config.supported_modes and config.mode not in config.supported_modes:
            logger.warning(f"Configured mode {config.mode.value} not in supported modes for plugin {config.plugin_id}")
            return False
        
        return True
    
    async def get_mode_config(self, plugin_id: str, mode: PluginMode) -> Dict[str, Any]:
        """Получить конфигурацию для конкретного режима"""
        config = await self.get_config(plugin_id)
        if not config:
            config = await self.get_default_config(plugin_id)

        # Возвращаем общую конфигурацию
        mode_config = config.config.copy()

        # Добавляем специфичные для режима параметры
        mode_config.update({
            'mode': mode.value,
            'enabled': config.enabled,
            'health_check_interval': config.health_check_interval,
            'restart_policy': config.restart_policy,
            'resources': config.resources.copy(),
            'dependencies': config.dependencies.copy(),
            'metadata': config.metadata.copy()
        })

        # Для инфраструктурных плагинов (например, client_manager) используем специфичную логику
        is_infrastructure_plugin = plugin_id == "client_manager"
        if is_infrastructure_plugin:
            if mode == PluginMode.MICROSERVICE:
                # Для external режима client_manager
                base_url = mode_config.get('base_url') or os.getenv('CM_BASE_URL') or 'http://client_manager:10000'
                mode_config['base_url'] = base_url
                mode_config['cm_mode'] = 'external'
            elif mode in [PluginMode.EMBEDDED, PluginMode.IN_PROCESS]:
                # Для embedded/in-process режима client_manager
                base_url = mode_config.get('base_url') or os.getenv('CM_BASE_URL') or 'http://127.0.0.1:10000'
                mode_config['base_url'] = base_url
                mode_config['cm_mode'] = 'embedded'
        else:
            # Для обычных плагинов
            # Для external режима добавляем URL
            if mode == PluginMode.MICROSERVICE:
                base_url = mode_config.get('base_url') or os.getenv(f'{plugin_id.upper()}_BASE_URL')
                if base_url:
                    mode_config['base_url'] = base_url

            # Для embedded режима добавляем пути
            elif mode == PluginMode.EMBEDDED:
                run_script = mode_config.get('run_script') or os.getenv(f'{plugin_id.upper()}_RUN_SCRIPT')
                if run_script:
                    mode_config['run_script'] = run_script

        return mode_config
    
    async def get_default_config(self, plugin_id: str) -> PluginConfig:
        """Получить конфигурацию по умолчанию для плагина"""
        return PluginConfig(
            plugin_id=plugin_id,
            mode=PluginMode.IN_PROCESS,
            enabled=True,
            config={},
            health_check_interval=30,
            restart_policy="always",
            resources={},
            dependencies=[],
            supported_modes=[PluginMode.IN_PROCESS],
            metadata={}
        )


# Global instance
_plugin_config_manager: Optional[PluginConfigManager] = None


def get_plugin_config_manager() -> PluginConfigManager:
    """Получить глобальный экземпляр PluginConfigManager"""
    global _plugin_config_manager
    if _plugin_config_manager is None:
        raise RuntimeError("PluginConfigManager not initialized. Call init_plugin_config_manager first.")
    return _plugin_config_manager


def init_plugin_config_manager(config_dir: Optional[str] = None) -> PluginConfigManager:
    """Инициализировать глобальный экземпляр PluginConfigManager"""
    global _plugin_config_manager
    _plugin_config_manager = PluginConfigManager(config_dir)
    return _plugin_config_manager


# Example configuration file content
EXAMPLE_CONFIG_YAML = """
plugin_id: client_manager
mode: embedded
enabled: true
config:
  port: 10000
  host: "127.0.0.1"
  workers: 1
health_check_interval: 30
restart_policy: "always"
resources:
  memory: "512MB"
  cpu: "0.5"
supported_modes:
  - "in_process"
  - "embedded"
  - "microservice"
metadata:
  version: "1.0.0"
  description: "Client manager plugin configuration"
"""

EXAMPLE_CONFIG_JSON = """
{
  "plugin_id": "weather_service",
  "mode": "microservice",
  "enabled": true,
  "config": {
    "api_key": "your_api_key_here",
    "update_interval": 300
  },
  "health_check_interval": 60,
  "restart_policy": "on_failure",
  "resources": {
    "memory": "256MB",
    "cpu": "0.25"
  },
  "supported_modes": [
    "microservice",
    "in_process"
  ],
  "metadata": {
    "version": "1.0.0",
    "description": "Weather service plugin configuration"
  }
}
"""

__all__ = [
    "ConfigSource",
    "PluginConfig",
    "PluginConfigManager",
    "get_plugin_config_manager",
    "init_plugin_config_manager",
    "EXAMPLE_CONFIG_YAML",
    "EXAMPLE_CONFIG_JSON"
]