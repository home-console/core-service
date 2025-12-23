"""
Plugin Mode Manager: управление режимами работы плагинов (internal/external/dual).

Отвечает за:
- Переключение между режимами работы плагинов
- Мониторинг состояния плагинов в разных режимах
- Управление процессами для embedded плагинов
- Управление подключениями для external плагинов
"""
import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from typing import Dict, Optional, Any, Callable
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path

from .plugin_loader import PluginLoader
from .plugin_registry import external_plugin_registry, ExternalPlugin


logger = logging.getLogger(__name__)


class PluginMode(Enum):
    """Режимы работы плагина"""
    IN_PROCESS = "in_process"        # как встроенный плагин (default)
    MICROSERVICE = "microservice"    # как внешний микросервис
    EMBEDDED = "embedded"            # как subprocess внутри core
    HYBRID = "hybrid"                # поддерживает несколько режимов


@dataclass
class PluginModeInfo:
    """Информация о режиме работы плагина"""
    plugin_id: str
    current_mode: PluginMode
    supported_modes: list[PluginMode]
    mode_switch_supported: bool = True
    embedded_process: Optional[subprocess.Popen] = None
    external_service_url: Optional[str] = None
    health_status: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)


class PluginModeManager:
    """
    Централизованный менеджер режимов работы плагинов.
    
    Позволяет:
    - Переключать плагины между internal/external режимами
    - Управлять embedded subprocess для internal плагинов
    - Управлять подключениями к external сервисам
    - Мониторить состояние плагинов в разных режимах
    """
    
    def __init__(self, plugin_loader: PluginLoader):
        self.plugin_loader = plugin_loader
        self.mode_states: Dict[str, PluginModeInfo] = {}
        self._lock = asyncio.Lock()
        logger.info("PluginModeManager initialized")
    
    def _get_plugin_mode_info(self, plugin_id: str) -> PluginModeInfo:
        """Получить или создать информацию о режиме плагина"""
        if plugin_id not in self.mode_states:
            # Для инфраструктурных плагинов устанавливаем специфичные настройки
            is_infrastructure_plugin = plugin_id == "client_manager"

            current_mode = PluginMode.IN_PROCESS  # по умолчанию
            supported_modes = [PluginMode.IN_PROCESS]  # по умолчанию

            # Для инфраструктурных плагинов устанавливаем более широкий набор поддерживаемых режимов
            if is_infrastructure_plugin:
                supported_modes = [PluginMode.IN_PROCESS, PluginMode.EMBEDDED, PluginMode.MICROSERVICE]

            # Попробуем определить из БД или плагина
            # Проверим, есть ли плагин загружен
            if plugin_id in self.plugin_loader.plugins:
                plugin = self.plugin_loader.plugins[plugin_id]
                if hasattr(plugin, 'manifest') and plugin.manifest:
                    # Проверим из manifest
                    manifest_modes = plugin.manifest.get('supported_modes', [])
                    if manifest_modes:
                        supported_modes = [PluginMode(mode) for mode in manifest_modes if mode in [m.value for m in PluginMode]]

                    runtime_mode = plugin.manifest.get('runtime_mode')
                    if runtime_mode and runtime_mode in [m.value for m in PluginMode]:
                        current_mode = PluginMode(runtime_mode)

            # Для инфраструктурных плагинов также проверим переменные окружения
            if is_infrastructure_plugin:
                cm_mode = os.getenv("CM_MODE", "external").lower()
                if cm_mode == "embedded":
                    current_mode = PluginMode.EMBEDDED  # или PluginMode.IN_PROCESS - зависит от реализации
                elif cm_mode == "external":
                    current_mode = PluginMode.MICROSERVICE

            # Определяем, поддерживает ли плагин переключение режимов
            mode_switch_supported = True
            if is_infrastructure_plugin:
                # Инфраструктурные плагины поддерживают переключение, но с ограничениями
                mode_switch_supported = True

            self.mode_states[plugin_id] = PluginModeInfo(
                plugin_id=plugin_id,
                current_mode=current_mode,
                supported_modes=supported_modes,
                mode_switch_supported=mode_switch_supported,
                config={}
            )

        return self.mode_states[plugin_id]
    
    async def get_mode_status(self, plugin_id: str) -> Dict[str, Any]:
        """Получить статус режима работы плагина"""
        info = self._get_plugin_mode_info(plugin_id)
        
        status = {
            "plugin_id": plugin_id,
            "current_mode": info.current_mode.value,
            "supported_modes": [m.value for m in info.supported_modes],
            "mode_switch_supported": info.mode_switch_supported,
            "health_status": info.health_status,
            "process_info": {
                "embedded_pid": info.embedded_process.pid if info.embedded_process and info.embedded_process.poll() is None else None,
                "external_service_url": info.external_service_url,
                "is_healthy": await self._check_health(plugin_id)
            }
        }
        
        return status
    
    async def _check_health(self, plugin_id: str) -> bool:
        """Проверить здоровье плагина в текущем режиме"""
        info = self._get_plugin_mode_info(plugin_id)

        # Для инфраструктурных плагинов используем специальную логику
        is_infrastructure_plugin = plugin_id == "client_manager"

        if info.current_mode == PluginMode.EMBEDDED:
            # Проверяем subprocess
            if info.embedded_process and info.embedded_process.poll() is None:
                return True
            return False
        elif info.current_mode == PluginMode.MICROSERVICE:
            # Проверяем через registry
            if external_plugin_registry.is_registered(plugin_id):
                return await external_plugin_registry.health_check(plugin_id)
            return False
        elif info.current_mode == PluginMode.IN_PROCESS:
            # Для in_process проверяем через plugin_loader
            plugin_loaded = plugin_id in self.plugin_loader.plugins

            # Для инфраструктурных плагинов дополнительно проверим специфичные условия
            if is_infrastructure_plugin and plugin_loaded:
                # Для client_manager проверим, что он полностью инициализирован
                plugin = self.plugin_loader.plugins[plugin_id]
                # Можно добавить дополнительные проверки инициализации плагина
                return True  # Если плагин загружен, считаем его здоровым

            return plugin_loaded
        else:
            # Неизвестный режим - считаем нездоровым
            return False
    
    async def switch_mode(self, plugin_id: str, target_mode: PluginMode, restart: bool = True) -> Dict[str, Any]:
        """
        Переключить плагин в указанный режим.
        
        Args:
            plugin_id: ID плагина
            target_mode: Целевой режим
            restart: Перезапустить плагин в новом режиме
        
        Returns:
            Dict с результатом переключения
        """
        async with self._lock:
            info = self._get_plugin_mode_info(plugin_id)
            
            # Проверяем поддержку режима
            if target_mode not in info.supported_modes:
                raise ValueError(f"Plugin {plugin_id} does not support mode {target_mode.value}")
            
            # Проверяем, нужно ли переключать
            if info.current_mode == target_mode:
                logger.info(f"Plugin {plugin_id} already in mode {target_mode.value}")
                return {
                    "status": "no_change",
                    "plugin_id": plugin_id,
                    "current_mode": target_mode.value,
                    "message": f"Plugin already in {target_mode.value} mode"
                }
            
            logger.info(f"Switching plugin {plugin_id} from {info.current_mode.value} to {target_mode.value}")
            
            # Остановить текущий режим
            await self._stop_current_mode(plugin_id, info)
            
            # Установить новый режим
            info.current_mode = target_mode
            
            # Запустить в новом режиме если нужно
            if restart:
                await self._start_in_mode(plugin_id, info)
            
            # Обновить статус
            info.health_status = await self._check_health(plugin_id)
            
            result = {
                "status": "switched",
                "plugin_id": plugin_id,
                "old_mode": info.current_mode.value if info.current_mode != target_mode else info.current_mode.value,
                "new_mode": target_mode.value,
                "restart_applied": restart,
                "health_status": info.health_status
            }
            
            logger.info(f"Successfully switched plugin {plugin_id} to mode {target_mode.value}")
            return result
    
    async def _stop_current_mode(self, plugin_id: str, info: PluginModeInfo):
        """Остановить плагин в текущем режиме"""
        # Для инфраструктурных плагинов (например, client_manager) используем специальную логику
        is_infrastructure_plugin = plugin_id == "client_manager"

        if info.current_mode == PluginMode.IN_PROCESS:
            # Выгрузить из plugin_loader
            if plugin_id in self.plugin_loader.plugins:
                if is_infrastructure_plugin:
                    # Для инфраструктурных плагинов не выгружаем, а сохраняем в специальном состоянии
                    logger.warning(f"Infrastructure plugin {plugin_id} cannot be unloaded from memory, skipping unload")
                else:
                    await self.plugin_loader.unload_plugin(plugin_id)

        elif info.current_mode == PluginMode.EMBEDDED:
            # Остановить subprocess
            if info.embedded_process:
                await self._stop_embedded_process(info.embedded_process)
                info.embedded_process = None

        elif info.current_mode == PluginMode.MICROSERVICE:
            # Отменить регистрацию в external_plugin_registry
            external_plugin_registry.unregister(plugin_id)
    
    async def _start_in_mode(self, plugin_id: str, info: PluginModeInfo):
        """Запустить плагин в указанном режиме"""
        # Для инфраструктурных плагинов (например, client_manager) используем специальную логику
        is_infrastructure_plugin = plugin_id == "client_manager"

        if info.current_mode == PluginMode.IN_PROCESS:
            # Загрузить через plugin_loader
            if is_infrastructure_plugin:
                # Для инфраструктурных плагинов сначала проверим, не загружен ли он уже
                if plugin_id not in self.plugin_loader.plugins:
                    # Установим правильный режим в окружении для инфраструктурных плагинов
                    if 'CM_MODE' not in info.config.get('env', {}):
                        os.environ['CM_MODE'] = 'embedded'  # По умолчанию для in-process client_manager
                    await self.plugin_loader.reload_plugin(plugin_id)
            else:
                await self.plugin_loader.reload_plugin(plugin_id)

        elif info.current_mode == PluginMode.EMBEDDED:
            # Запустить как subprocess
            info.embedded_process = await self._start_embedded_process(plugin_id)

        elif info.current_mode == PluginMode.MICROSERVICE:
            # Зарегистрировать в external_plugin_registry
            # Получим URL из конфига или env
            base_url = info.config.get('base_url') or os.getenv(f'{plugin_id.upper()}_BASE_URL')
            if base_url:
                external_plugin_registry.register(plugin_id, base_url)
            else:
                logger.warning(f"No base URL found for external plugin {plugin_id}")

        # Для инфраструктурных плагинов обновим переменные окружения в соответствии с режимом
        if is_infrastructure_plugin:
            if info.current_mode == PluginMode.MICROSERVICE:
                os.environ['CM_MODE'] = 'external'
            elif info.current_mode in [PluginMode.EMBEDDED, PluginMode.IN_PROCESS]:
                os.environ['CM_MODE'] = 'embedded'
    
    async def _start_embedded_process(self, plugin_id: str) -> Optional[subprocess.Popen]:
        """Запустить плагин как embedded subprocess"""
        # Для специфических плагинов (например, client_manager) используем специальную логику
        if plugin_id == "client_manager":
            # Используем существующий embed helper для client_manager
            try:
                from .plugins.client_manager.embed import start_embedded_with_manager
                proc = await asyncio.get_event_loop().run_in_executor(None, start_embedded_with_manager)
                if proc:
                    logger.info(f"Started embedded client_manager process, PID: {proc.pid}")
                    return proc
            except Exception as e:
                logger.error(f"Failed to start embedded client_manager via helper: {e}")
                return None

        # Для других плагинов используем общий подход
        # Попробуем найти скрипт запуска
        # Проверим стандартные пути
        possible_paths = [
            f"external-plugins/{plugin_id}/run_server.py",
            f"external_plugins/{plugin_id}/run_server.py",
            f"plugins/{plugin_id}/run_server.py",
            f"external-plugins/{plugin_id}/main.py",
            f"external_plugins/{plugin_id}/main.py",
            f"plugins/{plugin_id}/main.py",
        ]

        run_script_path = None
        for path in possible_paths:
            full_path = os.path.join(os.getcwd(), path)
            if os.path.exists(full_path):
                run_script_path = full_path
                break

        if not run_script_path:
            # Если не нашли скрипт, попробуем найти в PLUGINS_DIR
            plugins_dir = os.getenv("PLUGINS_DIR")
            if plugins_dir:
                plugin_dir = os.path.join(plugins_dir, plugin_id)
                for script_name in ["run_server.py", "main.py"]:
                    script_path = os.path.join(plugin_dir, script_name)
                    if os.path.exists(script_path):
                        run_script_path = script_path
                        break

        if not run_script_path:
            logger.error(f"Could not find run script for embedded plugin {plugin_id}")
            return None

        python = sys.executable or "python"
        cmd = [python, run_script_path]

        # Создаем специфичное окружение для embedded плагина
        env_vars = os.environ.copy()
        # Устанавливаем режим embedded
        env_vars['CM_MODE'] = 'embedded'  # для совместимости
        env_vars[f'{plugin_id.upper()}_MODE'] = 'embedded'
        env_vars['PLUGIN_MODE'] = 'embedded'

        # Запускаем процесс
        try:
            proc = subprocess.Popen(
                cmd,
                env=env_vars,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

            # Небольшая пауза, чтобы процесс успел подняться
            t0 = time.time()
            timeout = 10.0  # Увеличим таймаут для embedded процессов
            while time.time() - t0 < timeout:
                if proc.poll() is None:
                    # процесс все еще запущен
                    logger.info(f"Started embedded process for {plugin_id}, PID: {proc.pid}")
                    return proc
                time.sleep(0.1)

            # Процесс завершился быстро - ошибка
            logger.error(f"Embedded process for {plugin_id} exited quickly with code: {proc.poll()}")
            return None

        except Exception as e:
            logger.error(f"Failed to start embedded process for {plugin_id}: {e}")
            return None
    
    async def _stop_embedded_process(self, proc: subprocess.Popen):
        """Остановить embedded subprocess"""
        if not proc or proc.poll() is not None:
            return  # уже остановлен

        try:
            logger.info(f"Stopping embedded process PID: {proc.pid}")
            # Попробуем graceful terminate
            proc.send_signal(signal.SIGTERM)  # Сначала пробуем SIGTERM
            try:
                proc.wait(timeout=5.0)  # Больше времени для graceful shutdown
                logger.info(f"Embedded process PID: {proc.pid} stopped gracefully")
                return
            except subprocess.TimeoutExpired:
                logger.warning(f"Graceful shutdown timeout for PID: {proc.pid}, trying SIGKILL")
                proc.kill()  # Если не отреагировал, используем SIGKILL
                proc.wait(timeout=2.0)
                logger.info(f"Embedded process PID: {proc.pid} killed")
        except Exception as e:
            logger.error(f"Error stopping embedded process PID: {proc.pid}: {e}")
            try:
                proc.kill()  # Финальная попытка убить процесс
            except Exception:
                pass
    
    async def set_plugin_config(self, plugin_id: str, config: Dict[str, Any]):
        """Установить конфигурацию плагина"""
        info = self._get_plugin_mode_info(plugin_id)
        info.config.update(config)
        
        # Если плагин уже работает в external режиме, обновим в registry
        if info.current_mode == PluginMode.MICROSERVICE:
            if external_plugin_registry.is_registered(plugin_id):
                # Обновление в registry не поддерживается напрямую, нужно перерегистрировать
                external_plugin_registry.unregister(plugin_id)
                base_url = config.get('base_url')
                if base_url:
                    external_plugin_registry.register(plugin_id, base_url)
    
    async def get_supported_modes(self, plugin_id: str) -> list[PluginMode]:
        """Получить поддерживаемые режимы для плагина"""
        info = self._get_plugin_mode_info(plugin_id)
        return info.supported_modes
    
    async def is_mode_supported(self, plugin_id: str, mode: PluginMode) -> bool:
        """Проверить, поддерживается ли режим для плагина"""
        supported_modes = await self.get_supported_modes(plugin_id)
        return mode in supported_modes
    
    async def list_mode_status(self) -> Dict[str, Dict[str, Any]]:
        """Получить статус всех плагинов"""
        all_plugins = set(self.plugin_loader.plugins.keys())
        all_plugins.update(self.mode_states.keys())
        
        result = {}
        for plugin_id in all_plugins:
            try:
                result[plugin_id] = await self.get_mode_status(plugin_id)
            except Exception as e:
                logger.error(f"Error getting mode status for {plugin_id}: {e}")
                result[plugin_id] = {
                    "plugin_id": plugin_id,
                    "error": str(e),
                    "current_mode": "unknown"
                }
        
        return result
    
    async def cleanup(self):
        """Очистка ресурсов при завершении"""
        # Остановить все embedded процессы
        for plugin_id, info in self.mode_states.items():
            if info.current_mode == PluginMode.EMBEDDED and info.embedded_process:
                await self._stop_embedded_process(info.embedded_process)
        
        # Очистить registry
        for plugin_id in list(external_plugin_registry.plugins.keys()):
            external_plugin_registry.unregister(plugin_id)


# Global instance
plugin_mode_manager: Optional[PluginModeManager] = None


def get_plugin_mode_manager() -> PluginModeManager:
    """Получить глобальный экземпляр PluginModeManager"""
    global plugin_mode_manager
    if plugin_mode_manager is None:
        raise RuntimeError("PluginModeManager not initialized. Call init_plugin_mode_manager first.")
    return plugin_mode_manager


def init_plugin_mode_manager(plugin_loader: PluginLoader) -> PluginModeManager:
    """Инициализировать глобальный экземпляр PluginModeManager"""
    global plugin_mode_manager
    plugin_mode_manager = PluginModeManager(plugin_loader)
    return plugin_mode_manager


__all__ = [
    "PluginMode", 
    "PluginModeInfo", 
    "PluginModeManager", 
    "get_plugin_mode_manager", 
    "init_plugin_mode_manager"
]