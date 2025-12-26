"""
Переиспользует InternalPluginBase из SDK.

Для совместимости и удобства при разработке плагинов в core-service.
"""

from home_console_sdk.plugin import InternalPluginBase

__all__ = ["InternalPluginBase"]

# NOTE: Класс больше не определен здесь, используется из SDK
# Это решает проблему: разработчикам плагинов не нужно клонировать core-service

