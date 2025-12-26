"""
Модуль для установки зависимостей плагинов
"""

import os
import sys
import subprocess
import site
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Константы
DEPENDENCY_INSTALL_TIMEOUT = 300  # 5 минут


class PluginDependencyInstaller:
    """Установщик зависимостей плагинов"""
    
    @staticmethod
    def install_dependencies(plugin_path: str, plugin_id: str) -> Dict[str, Any]:
        """
        Установить зависимости плагина из requirements.txt.
        
        Args:
            plugin_path: Путь к директории плагина
            plugin_id: ID плагина
            
        Returns:
            Dict с результатом установки зависимостей
        """
        requirements_file = os.path.join(plugin_path, 'requirements.txt')
        
        if not os.path.exists(requirements_file):
            logger.debug(f"ℹ️ No requirements.txt found for plugin {plugin_id}")
            return {'status': 'skipped', 'reason': 'no_requirements'}
        
        try:
            logger.info(f"📦 Installing dependencies for plugin {plugin_id}")
            
            # Определяем, нужно ли использовать --user
            use_user_flag = PluginDependencyInstaller._should_use_user_flag()
            
            # Формируем команду pip
            pip_cmd = [
                sys.executable, '-m', 'pip', 'install', '-r', requirements_file,
                '--no-warn-script-location', '--no-cache-dir'
            ]
            if use_user_flag:
                pip_cmd.append('--user')
            
            result = subprocess.run(
                pip_cmd,
                capture_output=True,
                text=True,
                timeout=DEPENDENCY_INSTALL_TIMEOUT
            )
            
            if result.returncode == 0:
                PluginDependencyInstaller._add_to_sys_path(use_user_flag)
                
                if result.stdout:
                    logger.debug(f"📦 Pip output: {result.stdout[:500]}")
                
                logger.info(f"✅ Dependencies installed for plugin {plugin_id}")
                return {'status': 'installed', 'output': result.stdout}
            else:
                logger.error(f"❌ Failed to install dependencies for plugin {plugin_id}: {result.stderr}")
                if result.stdout:
                    logger.debug(f"📦 Pip stdout: {result.stdout[:500]}")
                return {'status': 'failed', 'error': result.stderr}
                
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Dependency installation timeout for plugin {plugin_id}")
            return {'status': 'failed', 'error': 'timeout'}
        except Exception as e:
            logger.error(f"❌ Error installing dependencies for plugin {plugin_id}: {e}", exc_info=True)
            return {'status': 'failed', 'error': str(e)}
    
    @staticmethod
    def _should_use_user_flag() -> bool:
        """
        Определить, нужно ли использовать флаг --user при установке.
        
        Returns:
            True если нужно использовать --user, False иначе
        """
        # В Docker контейнере или при работе от root можно устанавливать в системный site-packages
        if os.path.exists('/.dockerenv') or os.getenv('DOCKER_CONTAINER'):
            logger.debug("🐳 Running in Docker, installing to system site-packages")
            return False
        elif os.geteuid() == 0:
            logger.debug("🔑 Running as root, installing to system site-packages")
            return False
        return True
    
    @staticmethod
    def _add_to_sys_path(use_user_flag: bool):
        """
        Добавить путь к site-packages в sys.path.
        
        Args:
            use_user_flag: Использовался ли флаг --user
        """
        if use_user_flag:
            try:
                user_site = site.getusersitepackages()
                if user_site and os.path.exists(user_site):
                    if user_site not in sys.path:
                        sys.path.insert(0, user_site)
                        logger.debug(f"📦 Added user site-packages to sys.path: {user_site}")
                    
                    site.addsitedir(user_site)
                    logger.debug(f"📦 Initialized user site-packages: {user_site}")
            except Exception as e:
                logger.debug(f"Could not add user site-packages to sys.path: {e}")
        else:
            # При установке в системный site-packages просто перезагружаем site
            try:
                import importlib
                importlib.reload(site)
                logger.debug("📦 Reloaded site module to detect new packages")
            except Exception as e:
                logger.debug(f"Could not reload site module: {e}")

