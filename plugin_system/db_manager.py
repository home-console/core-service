"""
Модуль для работы с базой данных плагинов
"""

import logging
from typing import Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from ..core.database import Plugin, PluginVersion, get_session
except ImportError:
    from core_service.core.database import Plugin, PluginVersion, get_session

logger = logging.getLogger(__name__)


class PluginDBManager:
    """Менеджер работы с БД для плагинов"""
    
    @staticmethod
    async def is_plugin_enabled(plugin_id: str) -> bool:
        """
        Проверить, включен ли плагин (enabled=True в БД).
        
        Args:
            plugin_id: ID плагина
            
        Returns:
            True если плагин включен, False если отключен или не найден
        """
        try:
            async with get_session() as db:
                existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
                existing = existing_q.scalar_one_or_none()
                
                if existing:
                    # Если плагин есть в БД, проверяем флаг enabled (если нет - используем loaded)
                    if hasattr(existing, 'enabled'):
                        return bool(getattr(existing, 'enabled', True))
                    return getattr(existing, 'loaded', True)
                else:
                    # Если плагина нет в БД, считаем его включенным (первая загрузка)
                    return True
        except Exception as e:
            logger.warning(f"⚠️ Failed to check plugin {plugin_id} status: {e}")
            # В случае ошибки считаем плагин включенным
            return True
    
    @staticmethod
    async def update_loaded_status(plugin_id: str, loaded: bool):
        """
        Обновить статус загрузки плагина в БД.
        
        Args:
            plugin_id: ID плагина
            loaded: True если загружен, False если выгружен
        """
        try:
            async with get_session() as db:
                existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin_id))
                existing = existing_q.scalar_one_or_none()
                
                if existing:
                    existing.loaded = loaded
                    await db.flush()
                    logger.debug(f"💾 Updated plugin {plugin_id} loaded status to {loaded}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to update plugin {plugin_id} loaded status: {e}")
    
    @staticmethod
    def _to_serializable(obj: Any) -> Any:
        """
        Преобразовать объект в JSON-сериализуемую структуру.
        
        Args:
            obj: Объект для преобразования
            
        Returns:
            JSON-сериализуемый объект
        """
        import json
        
        if obj is None:
            return None
        # Простые типы оставляем как есть
        if isinstance(obj, (dict, list, str, int, float, bool)):
            return obj
        # Попробуем pydantic-like to_dict
        if hasattr(obj, 'dict') and callable(getattr(obj, 'dict')):
            try:
                return obj.dict()
            except Exception:
                pass
        # Если это обёртка PluginConfig — возьмём plugin_id и кеш
        if hasattr(obj, 'plugin_id'):
            result = {'plugin_id': getattr(obj, 'plugin_id')}
            if hasattr(obj, '_config_cache'):
                try:
                    result['cache'] = dict(getattr(obj, '_config_cache') or {})
                except Exception:
                    result['cache'] = str(getattr(obj, '_config_cache'))
            return result
        # Если есть __dict__, возьмём его (фильтруя приватные и несериализуемые значения)
        if hasattr(obj, '__dict__'):
            out = {}
            for k, v in vars(obj).items():
                if k.startswith('__'):
                    continue
                try:
                    json.dumps(v)
                    out[k] = v
                except Exception:
                    out[k] = str(v)
            return out
        # Фоллбек — str()
        return str(obj)
    
    @staticmethod
    async def save_plugin(
        plugin_instance,
        manifest: Optional[Dict[str, Any]] = None,
        plugin_type: Optional[str] = None
    ):
        """
        Сохранить информацию о плагине в базу данных.
        
        Args:
            plugin_instance: Экземпляр загруженного плагина
            manifest: Метаданные плагина (manifest)
            plugin_type: Тип плагина (internal/external)
        """
        try:
            async with get_session() as db:
                # Проверяем, существует ли плагин в БД
                existing_q = await db.execute(select(Plugin).where(Plugin.id == plugin_instance.id))
                existing = existing_q.scalar_one_or_none()
                
                # Получаем manifest если есть
                if not manifest:
                    manifest = getattr(plugin_instance, 'manifest', None) or getattr(plugin_instance, '_manifest', None)
                
                # Получаем type если есть
                if not plugin_type:
                    plugin_type = getattr(plugin_instance, 'type', None) or getattr(plugin_instance, '_type', None)
                
                # Определяем режим работы плагина из manifest или типа
                runtime_mode = None
                supported_modes = None
                mode_switch_supported = False
                
                if manifest:
                    runtime_mode = manifest.get('runtime_mode')
                    supported_modes = manifest.get('supported_modes')
                    mode_switch_supported = manifest.get('mode_switch_supported', False)
                
                if not runtime_mode:
                    # Определяем по типу плагина
                    if plugin_type == 'external':
                        runtime_mode = 'microservice'
                    elif plugin_type == 'internal':
                        runtime_mode = 'in_process'
                    else:
                        runtime_mode = 'in_process'  # По умолчанию
                
                # Если supported_modes не указан, определяем по типу
                if not supported_modes:
                    if plugin_type == 'external':
                        supported_modes = ['microservice']
                    elif plugin_type == 'internal':
                        supported_modes = ['in_process']
                    else:
                        supported_modes = [runtime_mode]
                
                # Конфигурация плагина если есть
                plugin_config = getattr(plugin_instance, 'config', None)
                plugin_config_serializable = PluginDBManager._to_serializable(plugin_config)
                
                # Создаем или обновляем запись Plugin
                if not existing:
                    plugin_obj = Plugin(
                        id=plugin_instance.id,
                        name=plugin_instance.name or plugin_instance.id,
                        description=getattr(plugin_instance, 'description', None),
                        publisher=None,
                        latest_version=getattr(plugin_instance, 'version', None),
                        enabled=True,  # при первой загрузке считаем разрешенным
                        loaded=True,   # Плагин только что загружен
                        runtime_mode=runtime_mode,
                        supported_modes=supported_modes,
                        mode_switch_supported=mode_switch_supported,
                        config=plugin_config_serializable
                    )
                    db.add(plugin_obj)
                    await db.flush()
                    logger.debug(f"💾 Created Plugin record in DB: {plugin_instance.id} (mode: {runtime_mode}, supported: {supported_modes})")
                else:
                    # Обновляем существующую запись
                    if plugin_instance.name:
                        existing.name = plugin_instance.name
                    if hasattr(plugin_instance, 'description') and plugin_instance.description:
                        existing.description = plugin_instance.description
                    if hasattr(plugin_instance, 'version') and plugin_instance.version:
                        existing.latest_version = plugin_instance.version
                    # Разрешаем к загрузке при успешной загрузке
                    if hasattr(existing, 'enabled'):
                        existing.enabled = True
                    existing.loaded = True  # Плагин загружен
                    if runtime_mode:
                        existing.runtime_mode = runtime_mode
                    if supported_modes:
                        existing.supported_modes = supported_modes
                    existing.mode_switch_supported = mode_switch_supported
                    if plugin_config is not None:
                        existing.config = plugin_config_serializable
                    await db.flush()
                    logger.debug(f"💾 Updated Plugin record in DB: {plugin_instance.id} (mode: {runtime_mode}, supported: {supported_modes})")
                
                # Создаем или обновляем запись PluginVersion
                version = getattr(plugin_instance, 'version', None) or 'unknown'
                pv_id = f"{plugin_instance.id}:{version}"
                
                pv = PluginVersion(
                    id=pv_id,
                    plugin_name=plugin_instance.id,
                    version=version,
                    manifest=manifest,
                    artifact_url=None,
                    type=plugin_type
                )
                await db.merge(pv)
                await db.flush()
                logger.debug(f"💾 Saved PluginVersion record in DB: {pv_id}")
                
        except Exception as e:
            # Не прерываем загрузку плагина, если не удалось сохранить в БД
            logger.warning(f"⚠️ Failed to save plugin {plugin_instance.id} to DB: {e}", exc_info=True)

