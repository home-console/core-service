"""
Модуль для работы с архивами плагинов (ZIP, TAR.GZ)
"""

import os
import zipfile
import tarfile
import logging
import tempfile
import shutil
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ArchiveHandler:
    """Обработчик архивов плагинов"""
    
    def __init__(self, temp_dir: Optional[str] = None):
        """
        Инициализация обработчика архивов.
        
        Args:
            temp_dir: Временная директория для распаковки (если None, создается автоматически)
        """
        self.temp_dir = temp_dir or tempfile.mkdtemp(prefix="plugins_")
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir, exist_ok=True)
    
    def extract_archive(self, archive_path: str, archive_type: str) -> Optional[str]:
        """
        Распаковать архив плагина.
        
        Args:
            archive_path: Путь к архиву
            archive_type: 'zip' или 'tar'
            
        Returns:
            Путь к распакованной директории или None при ошибке
        """
        try:
            # Создаем временную папку для распаковки
            archive_name = os.path.splitext(os.path.basename(archive_path))[0]
            # Убираем расширение .tar если есть
            if archive_name.endswith('.tar'):
                archive_name = archive_name[:-4]
            
            extract_dir = os.path.join(self.temp_dir, archive_name)
            os.makedirs(extract_dir, exist_ok=True)
            
            # Распаковываем архив
            if archive_type == 'zip':
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    zf.extractall(extract_dir)
            elif archive_type == 'tar':
                with tarfile.open(archive_path, 'r:*') as tf:
                    tf.extractall(extract_dir)
            else:
                logger.error(f"❌ Unsupported archive type: {archive_type}")
                return None
            
            logger.debug(f"📦 Extracted archive to: {extract_dir}")
            return extract_dir
            
        except zipfile.BadZipFile as e:
            logger.error(f"❌ Invalid ZIP archive {archive_path}: {e}")
            return None
        except tarfile.TarError as e:
            logger.error(f"❌ Invalid TAR archive {archive_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Error extracting archive {archive_path}: {e}", exc_info=True)
            return None
    
    def cleanup(self):
        """Очистить временные файлы"""
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                logger.debug(f"🧹 Cleaned up temp directory: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to cleanup temp directory: {e}")
    
    def __del__(self):
        """Автоматическая очистка при удалении объекта"""
        self.cleanup()

