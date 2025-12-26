"""
Plugin Lifecycle Manager - управление жизненным циклом плагинов.
Обеспечивает мониторинг, перезапуск, безопасную изоляцию и управление ресурсами плагинов.
"""
import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
import threading
from datetime import datetime
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class PluginState(Enum):
    """Состояния плагина"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"
    UNRESPONSIVE = "unresponsive"


@dataclass
class PluginInfo:
    """Информация о плагине"""
    id: str
    name: str
    version: str
    path: str
    type: str  # internal, external, embedded
    state: PluginState = PluginState.STOPPED
    process: Optional[subprocess.Popen] = None
    last_start: Optional[datetime] = None
    last_stop: Optional[datetime] = None
    restart_count: int = 0
    max_restarts: int = 5
    restart_window: int = 300  # 5 минут
    health_check_interval: int = 30
    resources: Dict[str, Any] = field(default_factory=dict)  # memory, cpu limits
    dependencies: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)


class PluginLifecycleManager:
    """
    Менеджер жизненного цикла плагинов.
    
    Отвечает за:
    - Запуск/остановку плагинов
    - Мониторинг состояния
    - Перезапуск упавших плагинов
    - Управление ресурсами
    - Безопасную изоляцию
    """
    
    def __init__(self):
        self.plugins: Dict[str, PluginInfo] = {}
        self._monitor_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._shutdown = False
        logger.info("PluginLifecycleManager initialized")
    
    async def register_plugin(
        self,
        plugin_id: str,
        name: str,
        version: str,
        path: str,
        plugin_type: str = "external",
        dependencies: List[str] = None,
        resources: Dict[str, Any] = None,
        env: Dict[str, str] = None
    ) -> PluginInfo:
        """Зарегистрировать новый плагин"""
        async with self._lock:
            plugin_info = PluginInfo(
                id=plugin_id,
                name=name,
                version=version,
                path=path,
                type=plugin_type,
                dependencies=dependencies or [],
                resources=resources or {},
                env=env or {}
            )
            self.plugins[plugin_id] = plugin_info
            logger.info(f"Registered plugin: {plugin_id} ({plugin_type})")
            return plugin_info
    
    async def start_plugin(self, plugin_id: str) -> bool:
        """Запустить плагин"""
        if plugin_id not in self.plugins:
            logger.error(f"Plugin {plugin_id} not registered")
            return False
        
        plugin_info = self.plugins[plugin_id]
        
        # Проверяем зависимости
        if not await self._check_dependencies(plugin_id):
            logger.error(f"Dependencies not satisfied for plugin {plugin_id}")
            plugin_info.state = PluginState.ERROR
            return False
        
        try:
            # Обновляем состояние
            plugin_info.state = PluginState.STARTING
            plugin_info.last_start = datetime.utcnow()
            
            if plugin_info.type == "external":
                # Запускаем как внешний процесс
                process = await self._start_external_plugin(plugin_info)
                if process:
                    plugin_info.process = process
                    plugin_info.state = PluginState.RUNNING
                    logger.info(f"Started external plugin: {plugin_id}")
                    
                    # Запускаем мониторинг
                    await self._start_monitoring(plugin_id)
                    return True
                else:
                    plugin_info.state = PluginState.ERROR
                    return False
            elif plugin_info.type == "internal":
                # Внутренние плагины управляются другим способом
                plugin_info.state = PluginState.RUNNING
                logger.info(f"Internal plugin {plugin_id} marked as running")
                return True
            else:
                logger.error(f"Unknown plugin type: {plugin_info.type}")
                plugin_info.state = PluginState.ERROR
                return False
                
        except Exception as e:
            logger.error(f"Error starting plugin {plugin_id}: {e}")
            plugin_info.state = PluginState.ERROR
            return False
    
    async def _start_external_plugin(self, plugin_info: PluginInfo) -> Optional[subprocess.Popen]:
        """Запустить внешний плагин как subprocess"""
        try:
            # Проверяем существование файла
            if not os.path.exists(plugin_info.path):
                logger.error(f"Plugin file does not exist: {plugin_info.path}")
                return None
            
            # Подготовка команды запуска
            cmd = [sys.executable, plugin_info.path]
            
            # Подготовка окружения
            env = os.environ.copy()
            env.update(plugin_info.env)
            
            # Установка ограничений ресурсов (насколько возможно в Python)
            # Это базовая реализация - в продакшене нужно использовать cgroups или контейнеры
            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            
            # Проверяем, что процесс запустился
            await asyncio.sleep(0.5)  # Небольшая задержка для запуска
            if process.poll() is not None:
                # Процесс завершился сразу - ошибка
                stdout, stderr = process.communicate()
                logger.error(f"Plugin {plugin_info.id} failed to start: {stderr.decode()}")
                return None
            
            logger.info(f"External plugin process started: {plugin_info.id} (PID: {process.pid})")
            return process
            
        except Exception as e:
            logger.error(f"Failed to start external plugin {plugin_info.id}: {e}")
            return None
    
    async def stop_plugin(self, plugin_id: str) -> bool:
        """Остановить плагин"""
        if plugin_id not in self.plugins:
            logger.error(f"Plugin {plugin_id} not registered")
            return False
        
        plugin_info = self.plugins[plugin_id]
        
        try:
            plugin_info.state = PluginState.STOPPING
            plugin_info.last_stop = datetime.utcnow()
            
            if plugin_info.type == "external" and plugin_info.process:
                # Останавливаем внешний процесс
                await self._stop_external_plugin(plugin_info)
            elif plugin_info.type == "internal":
                # Внутренние плагины управляются другим способом
                pass
            
            plugin_info.state = PluginState.STOPPED
            logger.info(f"Stopped plugin: {plugin_id}")
            
            # Останавливаем мониторинг
            await self._stop_monitoring(plugin_id)
            return True
            
        except Exception as e:
            logger.error(f"Error stopping plugin {plugin_id}: {e}")
            plugin_info.state = PluginState.ERROR
            return False
    
    async def _stop_external_plugin(self, plugin_info: PluginInfo):
        """Остановить внешний плагин"""
        if not plugin_info.process:
            return
        
        try:
            # Пытаемся корректно завершить процесс
            plugin_info.process.send_signal(signal.SIGTERM)
            
            try:
                # Ждем завершения с таймаутом
                stdout, stderr = plugin_info.process.communicate(timeout=5.0)
            except subprocess.TimeoutExpired:
                # Если не завершился, убиваем
                logger.warning(f"Plugin {plugin_info.id} did not respond to SIGTERM, sending SIGKILL")
                plugin_info.process.kill()
                stdout, stderr = plugin_info.process.communicate()
            
            logger.info(f"External plugin process stopped: {plugin_info.id}")
            
        except Exception as e:
            logger.error(f"Error stopping external plugin {plugin_info.id}: {e}")
    
    async def _check_dependencies(self, plugin_id: str) -> bool:
        """Проверить зависимости плагина"""
        plugin_info = self.plugins[plugin_id]
        
        for dep_id in plugin_info.dependencies:
            if dep_id not in self.plugins:
                logger.warning(f"Dependency {dep_id} not found for plugin {plugin_id}")
                continue
            
            dep_info = self.plugins[dep_id]
            if dep_info.state != PluginState.RUNNING:
                logger.warning(f"Dependency {dep_id} not running for plugin {plugin_id}")
                return False
        
        return True
    
    async def _start_monitoring(self, plugin_id: str):
        """Запустить мониторинг плагина"""
        if plugin_id in self._monitor_tasks:
            # Уже запущен
            return
        
        task = asyncio.create_task(self._monitor_plugin(plugin_id))
        self._monitor_tasks[plugin_id] = task
        logger.debug(f"Started monitoring for plugin: {plugin_id}")
    
    async def _stop_monitoring(self, plugin_id: str):
        """Остановить мониторинг плагина"""
        if plugin_id in self._monitor_tasks:
            task = self._monitor_tasks[plugin_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self._monitor_tasks[plugin_id]
            logger.debug(f"Stopped monitoring for plugin: {plugin_id}")
    
    async def _monitor_plugin(self, plugin_id: str):
        """Мониторинг состояния плагина"""
        if plugin_id not in self.plugins:
            return
        
        plugin_info = self.plugins[plugin_id]
        
        while not self._shutdown and plugin_info.state in [PluginState.RUNNING, PluginState.STARTING]:
            try:
                # Проверяем состояние процесса для внешних плагинов
                if plugin_info.type == "external" and plugin_info.process:
                    if plugin_info.process.poll() is not None:
                        # Процесс упал
                        logger.error(f"Plugin {plugin_id} process died unexpectedly")
                        plugin_info.state = PluginState.ERROR
                        
                        # Пытаемся перезапустить
                        await self._handle_plugin_crash(plugin_id)
                        break
                
                # Ждем интервал проверки
                await asyncio.sleep(plugin_info.health_check_interval)
                
            except asyncio.CancelledError:
                logger.debug(f"Monitoring cancelled for plugin: {plugin_id}")
                break
            except Exception as e:
                logger.error(f"Error monitoring plugin {plugin_id}: {e}")
                break
    
    async def _handle_plugin_crash(self, plugin_id: str):
        """Обработать падение плагина"""
        plugin_info = self.plugins[plugin_id]
        
        # Увеличиваем счетчик перезапусков
        plugin_info.restart_count += 1
        restart_time = datetime.utcnow()
        
        # Проверяем, не превышен ли лимит перезапусков
        restarts_in_window = await self._get_recent_restarts(plugin_id, plugin_info.restart_window)
        
        if restarts_in_window >= plugin_info.max_restarts:
            logger.error(f"Plugin {plugin_id} restart limit exceeded, disabling")
            plugin_info.state = PluginState.ERROR
            # Здесь можно добавить уведомление администратору
            return
        
        logger.info(f"Restarting plugin {plugin_id} (attempt {plugin_info.restart_count})")
        
        # Перезапускаем плагин
        await asyncio.sleep(2)  # Небольшая задержка перед перезапуском
        await self.start_plugin(plugin_id)
    
    async def _get_recent_restarts(self, plugin_id: str, window_seconds: int) -> int:
        """Получить количество перезапусков за последнее время"""
        # В реальной реализации это будет более сложная логика с хранением истории
        # Пока возвращаем счетчик перезапусков
        return self.plugins[plugin_id].restart_count
    
    async def get_plugin_status(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        """Получить статус плагина"""
        if plugin_id not in self.plugins:
            return None
        
        plugin_info = self.plugins[plugin_id]
        
        status = {
            'id': plugin_info.id,
            'name': plugin_info.name,
            'version': plugin_info.version,
            'type': plugin_info.type,
            'state': plugin_info.state.value,
            'last_start': plugin_info.last_start.isoformat() if plugin_info.last_start else None,
            'last_stop': plugin_info.last_stop.isoformat() if plugin_info.last_stop else None,
            'restart_count': plugin_info.restart_count,
            'pid': plugin_info.process.pid if plugin_info.process and plugin_info.process.poll() is None else None
        }
        
        return status
    
    async def list_plugins_status(self) -> Dict[str, Dict[str, Any]]:
        """Получить статусы всех плагинов"""
        status = {}
        for plugin_id in self.plugins:
            plugin_status = await self.get_plugin_status(plugin_id)
            if plugin_status:
                status[plugin_id] = plugin_status
        return status
    
    async def cleanup(self):
        """Очистка ресурсов при завершении"""
        self._shutdown = True
        
        # Останавливаем все мониторинги
        for task in list(self._monitor_tasks.values()):
            task.cancel()
        
        # Ждем завершения мониторингов
        if self._monitor_tasks:
            await asyncio.gather(*self._monitor_tasks.values(), return_exceptions=True)
        
        # Останавливаем все плагины
        for plugin_id in list(self.plugins.keys()):
            await self.stop_plugin(plugin_id)


# Global instance
_plugin_lifecycle_manager: Optional[PluginLifecycleManager] = None


def get_plugin_lifecycle_manager() -> PluginLifecycleManager:
    """Получить глобальный экземпляр PluginLifecycleManager"""
    global _plugin_lifecycle_manager
    if _plugin_lifecycle_manager is None:
        raise RuntimeError("PluginLifecycleManager not initialized. Call init_plugin_lifecycle_manager first.")
    return _plugin_lifecycle_manager


def init_plugin_lifecycle_manager() -> PluginLifecycleManager:
    """Инициализировать глобальный экземпляр PluginLifecycleManager"""
    global _plugin_lifecycle_manager
    _plugin_lifecycle_manager = PluginLifecycleManager()
    return _plugin_lifecycle_manager


__all__ = [
    "PluginState",
    "PluginInfo", 
    "PluginLifecycleManager",
    "get_plugin_lifecycle_manager",
    "init_plugin_lifecycle_manager"
]