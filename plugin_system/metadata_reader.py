"""
Модуль для чтения метаданных плагинов из plugin.json
"""

import json
import logging
from typing import Dict, Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class PluginMetadataReader:
    """Читатель метаданных плагинов"""
    
    REQUIRED_FIELDS = ['id', 'name', 'version']
    
    @staticmethod
    def read_metadata(plugin_json_path: str) -> Optional[Dict[str, Any]]:
        """
        Прочитать метаданные плагина из plugin.json.
        
        Args:
            plugin_json_path: Путь к файлу plugin.json
            
        Returns:
            Dict с метаданными или None если ошибка
        """
        try:
            with open(plugin_json_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            # Проверяем обязательные поля
            for field in PluginMetadataReader.REQUIRED_FIELDS:
                if field not in metadata:
                    logger.warning(f"⚠️ Missing required field '{field}' in {plugin_json_path}")
                    return None
            
            logger.debug(f"✅ Read plugin metadata: {metadata['id']}")
            return metadata
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in {plugin_json_path}: {e}")
            return None
        except FileNotFoundError:
            logger.warning(f"⚠️ Plugin metadata file not found: {plugin_json_path}")
            return None
        except Exception as e:
            logger.error(f"❌ Error reading {plugin_json_path}: {e}", exc_info=True)
            return None
    
    @staticmethod
    def create_default_metadata(base_name: str) -> Dict[str, Any]:
        """
        Создать метаданные по умолчанию на основе имени файла.
        
        Args:
            base_name: Базовое имя (без расширения)
            
        Returns:
            Dict с метаданными по умолчанию
        """
        return {
            "id": base_name,
            "name": base_name.replace('_', ' ').title(),
            "version": "1.0.0",
            "type": "internal"
        }

