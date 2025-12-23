"""
Plugin Security Manager - система безопасности для плагинов.
Обеспечивает аутентификацию, авторизацию и изоляцию плагинов.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
from enum import Enum

import jwt
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class PluginPermission(Enum):
    """Разрешения для плагинов"""
    READ_DEVICES = "read_devices"
    WRITE_DEVICES = "write_devices"
    READ_FILES = "read_files"
    WRITE_FILES = "write_files"
    EXECUTE_COMMANDS = "execute_commands"
    READ_PLUGINS = "read_plugins"
    MANAGE_PLUGINS = "manage_plugins"
    READ_EVENTS = "read_events"
    PUBLISH_EVENTS = "publish_events"


@dataclass
class PluginSecurityContext:
    """Контекст безопасности плагина"""
    plugin_id: str
    permissions: List[PluginPermission]
    allowed_resources: List[str]  # список разрешенных ресурсов
    created_at: datetime
    expires_at: Optional[datetime] = None
    token: Optional[str] = None
    secret_key: Optional[str] = None


class PluginSecurityManager:
    """
    Менеджер безопасности плагинов.
    
    Отвечает за:
    - Аутентификацию плагинов
    - Авторизацию запросов
    - Управление разрешениями
    - Изоляцию плагинов
    """
    
    def __init__(self):
        self.plugin_contexts: Dict[str, PluginSecurityContext] = {}
        self._default_permissions: List[PluginPermission] = [
            PluginPermission.READ_DEVICES,
            PluginPermission.READ_EVENTS
        ]
        self._secret_key = os.getenv('PLUGIN_SECURITY_SECRET', secrets.token_urlsafe(32))
        self._fernet = Fernet(Fernet.generate_key())  # В реальности использовать реальный ключ
        logger.info("PluginSecurityManager initialized")
    
    async def register_plugin(
        self,
        plugin_id: str,
        permissions: List[PluginPermission] = None,
        allowed_resources: List[str] = None,
        token_ttl: int = 3600  # 1 hour default
    ) -> PluginSecurityContext:
        """Зарегистрировать плагин и выдать ему контекст безопасности"""
        # Генерируем токен для плагина
        token = await self._generate_plugin_token(plugin_id, token_ttl)
        secret_key = secrets.token_urlsafe(32)
        
        context = PluginSecurityContext(
            plugin_id=plugin_id,
            permissions=permissions or self._default_permissions.copy(),
            allowed_resources=allowed_resources or [],
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=token_ttl),
            token=token,
            secret_key=secret_key
        )
        
        self.plugin_contexts[plugin_id] = context
        logger.info(f"Registered security context for plugin: {plugin_id}")
        
        return context
    
    async def _generate_plugin_token(self, plugin_id: str, ttl: int) -> str:
        """Сгенерировать JWT токен для плагина"""
        payload = {
            'plugin_id': plugin_id,
            'exp': datetime.utcnow() + timedelta(seconds=ttl),
            'iat': datetime.utcnow(),
            'nbf': datetime.utcnow()
        }
        
        token = jwt.encode(payload, self._secret_key, algorithm='HS256')
        return token
    
    async def authenticate_plugin(self, plugin_id: str, token: str) -> bool:
        """Аутентифицировать плагин по токену"""
        if plugin_id not in self.plugin_contexts:
            logger.warning(f"Plugin {plugin_id} not registered")
            return False
        
        context = self.plugin_contexts[plugin_id]
        
        if not context.token:
            logger.error(f"No token for plugin {plugin_id}")
            return False
        
        if context.token != token:
            logger.warning(f"Invalid token for plugin {plugin_id}")
            return False
        
        # Проверяем срок действия
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=['HS256'])
            if payload.get('plugin_id') != plugin_id:
                logger.warning(f"Token plugin_id mismatch for {plugin_id}")
                return False
        except jwt.ExpiredSignatureError:
            logger.warning(f"Token expired for plugin {plugin_id}")
            return False
        except jwt.InvalidTokenError:
            logger.warning(f"Invalid token for plugin {plugin_id}")
            return False
        
        return True
    
    async def authorize_request(
        self,
        plugin_id: str,
        permission: PluginPermission,
        resource: Optional[str] = None
    ) -> bool:
        """Авторизовать запрос плагина"""
        if plugin_id not in self.plugin_contexts:
            logger.warning(f"Plugin {plugin_id} not registered for authorization")
            return False
        
        context = self.plugin_contexts[plugin_id]
        
        # Проверяем разрешение
        if permission not in context.permissions:
            logger.warning(f"Plugin {plugin_id} lacks permission {permission.value}")
            return False
        
        # Проверяем доступ к ресурсу
        if resource and context.allowed_resources:
            # Если есть список разрешенных ресурсов, проверяем вхождение
            is_allowed = any(
                resource.startswith(allowed) or allowed.startswith(resource)
                for allowed in context.allowed_resources
            )
            if not is_allowed:
                logger.warning(f"Plugin {plugin_id} not authorized for resource {resource}")
                return False
        
        return True
    
    async def get_plugin_permissions(self, plugin_id: str) -> Optional[List[PluginPermission]]:
        """Получить разрешения плагина"""
        if plugin_id not in self.plugin_contexts:
            return None
        
        return self.plugin_contexts[plugin_id].permissions.copy()
    
    async def add_permission(self, plugin_id: str, permission: PluginPermission) -> bool:
        """Добавить разрешение плагину"""
        if plugin_id not in self.plugin_contexts:
            return False
        
        context = self.plugin_contexts[plugin_id]
        if permission not in context.permissions:
            context.permissions.append(permission)
            logger.info(f"Added permission {permission.value} to plugin {plugin_id}")
            return True
        
        return False
    
    async def remove_permission(self, plugin_id: str, permission: PluginPermission) -> bool:
        """Удалить разрешение у плагина"""
        if plugin_id not in self.plugin_contexts:
            return False
        
        context = self.plugin_contexts[plugin_id]
        if permission in context.permissions:
            context.permissions.remove(permission)
            logger.info(f"Removed permission {permission.value} from plugin {plugin_id}")
            return True
        
        return False
    
    async def add_allowed_resource(self, plugin_id: str, resource: str) -> bool:
        """Добавить разрешенный ресурс для плагина"""
        if plugin_id not in self.plugin_contexts:
            return False
        
        context = self.plugin_contexts[plugin_id]
        if resource not in context.allowed_resources:
            context.allowed_resources.append(resource)
            logger.info(f"Added allowed resource {resource} for plugin {plugin_id}")
            return True
        
        return False
    
    async def remove_allowed_resource(self, plugin_id: str, resource: str) -> bool:
        """Удалить разрешенный ресурс у плагина"""
        if plugin_id not in self.plugin_contexts:
            return False
        
        context = self.plugin_contexts[plugin_id]
        if resource in context.allowed_resources:
            context.allowed_resources.remove(resource)
            logger.info(f"Removed allowed resource {resource} for plugin {plugin_id}")
            return True
        
        return False
    
    async def validate_plugin_signature(self, plugin_id: str, data: bytes, signature: str) -> bool:
        """Проверить подпись данных плагином"""
        if plugin_id not in self.plugin_contexts:
            return False
        
        context = self.plugin_contexts[plugin_id]
        if not context.secret_key:
            return False
        
        # Создаем ожидаемую подпись
        expected_signature = hmac.new(
            context.secret_key.encode(),
            data,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)
    
    async def sign_data(self, plugin_id: str, data: bytes) -> Optional[str]:
        """Подписать данные плагином"""
        if plugin_id not in self.plugin_contexts:
            return None
        
        context = self.plugin_contexts[plugin_id]
        if not context.secret_key:
            return None
        
        signature = hmac.new(
            context.secret_key.encode(),
            data,
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    async def cleanup_expired_contexts(self):
        """Очистить просроченные контексты безопасности"""
        now = datetime.utcnow()
        expired_plugins = []
        
        for plugin_id, context in self.plugin_contexts.items():
            if context.expires_at and context.expires_at < now:
                expired_plugins.append(plugin_id)
        
        for plugin_id in expired_plugins:
            del self.plugin_contexts[plugin_id]
            logger.info(f"Removed expired security context for plugin: {plugin_id}")
    
    async def get_security_report(self) -> Dict[str, Any]:
        """Получить отчет по безопасности"""
        report = {
            'total_plugins': len(self.plugin_contexts),
            'contexts': {}
        }
        
        for plugin_id, context in self.plugin_contexts.items():
            report['contexts'][plugin_id] = {
                'permissions': [p.value for p in context.permissions],
                'allowed_resources': context.allowed_resources,
                'created_at': context.created_at.isoformat(),
                'expires_at': context.expires_at.isoformat() if context.expires_at else None,
                'has_token': context.token is not None,
                'has_secret': context.secret_key is not None
            }
        
        return report


# Global instance
_plugin_security_manager: Optional[PluginSecurityManager] = None


def get_plugin_security_manager() -> PluginSecurityManager:
    """Получить глобальный экземпляр PluginSecurityManager"""
    global _plugin_security_manager
    if _plugin_security_manager is None:
        raise RuntimeError("PluginSecurityManager not initialized. Call init_plugin_security_manager first.")
    return _plugin_security_manager


def init_plugin_security_manager() -> PluginSecurityManager:
    """Инициализировать глобальный экземпляр PluginSecurityManager"""
    global _plugin_security_manager
    _plugin_security_manager = PluginSecurityManager()
    return _plugin_security_manager


__all__ = [
    "PluginPermission",
    "PluginSecurityContext", 
    "PluginSecurityManager",
    "get_plugin_security_manager",
    "init_plugin_security_manager"
]