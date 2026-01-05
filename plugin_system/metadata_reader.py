"""
Модуль для чтения метаданных плагинов из plugin.json
"""

import json
import logging
from typing import Dict, Optional, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class PluginMetadataReader:
    """Читатель метаданных плагинов.

    Поддерживает `plugin.json` / `manifest.json` (приоритет) и YAML-манифесты
    (`plugin.yaml`, `manifest.yaml`, `plugin.yml`, `manifest.yml`).
    """

    REQUIRED_FIELDS = ['id', 'name', 'version']

    @staticmethod
    def _try_load_json(path: Path) -> Optional[Dict[str, Any]]:
        try:
            with path.open('r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in {path}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Error reading JSON {path}: {e}", exc_info=True)
            return None

    @staticmethod
    def _try_load_yaml(path: Path) -> Optional[Dict[str, Any]]:
        try:
            import yaml  # pyyaml
        except Exception:
            logger.warning("⚠️ PyYAML not installed, cannot read YAML manifests")
            return None
        try:
            with path.open('r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else None
        except Exception as e:
            logger.error(f"❌ Error reading YAML {path}: {e}", exc_info=True)
            return None

    @staticmethod
    def _validate_required(metadata: Dict[str, Any], source: Path) -> bool:
        for field in PluginMetadataReader.REQUIRED_FIELDS:
            if field not in metadata:
                logger.warning(f"⚠️ Missing required field '{field}' in {source}")
                return False
        return True

    @staticmethod
    def read_metadata(plugin_meta_path: str) -> Optional[Dict[str, Any]]:
        """
        Прочитать метаданные плагина. Если переданный путь отсутствует,
        будет выполнён поиск альтернативных файлов (JSON затем YAML).

        Args:
            plugin_meta_path: Путь к ожидаемому файлу (например plugin.json или manifest.json)

        Returns:
            Dict с метаданными или None если ошибка
        """
        try:
            candidate = Path(plugin_meta_path) if plugin_meta_path else None
            candidates: List[Path] = []

            if candidate and candidate.exists():
                candidates.append(candidate)
            else:
                # Если явно указанный файл не найден, ищем по набору возможных имён
                base_dir = Path(plugin_meta_path).parent if plugin_meta_path else Path('.')
                names_priority = [
                    'plugin.json', 'manifest.json',
                    'plugin.yaml', 'plugin.yml', 'manifest.yaml', 'manifest.yml'
                ]
                for name in names_priority:
                    p = base_dir / name
                    if p.exists():
                        candidates.append(p)

            for p in candidates:
                if p.suffix.lower() in ('.json',):
                    metadata = PluginMetadataReader._try_load_json(p)
                elif p.suffix.lower() in ('.yaml', '.yml'):
                    metadata = PluginMetadataReader._try_load_yaml(p)
                else:
                    # Попробуем определить по содержимому: сначала JSON, затем YAML
                    metadata = PluginMetadataReader._try_load_json(p) or PluginMetadataReader._try_load_yaml(p)

                if not metadata:
                    continue

                if not PluginMetadataReader._validate_required(metadata, p):
                    continue

                logger.debug(f"✅ Read plugin metadata from {p}: {metadata.get('id')}")
                return metadata

            logger.warning(f"⚠️ No valid plugin metadata found near: {plugin_meta_path}")
            return None

        except Exception as e:
            logger.error(f"❌ Error reading metadata {plugin_meta_path}: {e}", exc_info=True)
            return None

    @staticmethod
    def create_default_metadata(base_name: str) -> Dict[str, Any]:
        return {
            "id": base_name,
            "name": base_name.replace('_', ' ').title(),
            "version": "1.0.0",
            "type": "internal"
        }

