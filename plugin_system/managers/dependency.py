"""
Plugin Dependency Manager - управление зависимостями между плагинами.
Обеспечивает разрешение зависимостей, проверку совместимости и порядок загрузки плагинов.
"""
import asyncio
import logging
import re
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum


logger = logging.getLogger(__name__)


class DependencyType(Enum):
    """Тип зависимости"""
    REQUIRED = "required"  # обязательная зависимость
    OPTIONAL = "optional"  # опциональная зависимость
    CONFLICTS = "conflicts"  # конфликтующая зависимость
    SUGGESTED = "suggested"  # рекомендуемая зависимость


@dataclass
class PluginDependency:
    """Информация о зависимости плагина"""
    plugin_id: str
    version_spec: str  # спецификация версии (например, ">=1.0.0,<2.0.0")
    dependency_type: DependencyType
    optional: bool = False


@dataclass
class PluginInfo:
    """Информация о плагине"""
    id: str
    version: str
    dependencies: List[PluginDependency] = field(default_factory=list)
    loaded: bool = False
    enabled: bool = True
    load_order: int = 0


class PluginDependencyManager:
    """
    Менеджер зависимостей плагинов.
    
    Отвечает за:
    - Разрешение зависимостей между плагинами
    - Проверку совместимости версий
    - Определение порядка загрузки
    - Обнаружение конфликтов зависимостей
    """
    
    def __init__(self):
        self.plugins: Dict[str, PluginInfo] = {}
        self._dependency_graph: Dict[str, Set[str]] = {}  # graph of dependencies
        self._reverse_graph: Dict[str, Set[str]] = {}    # reverse graph for dependents
        self._lock = asyncio.Lock()
        logger.info("PluginDependencyManager initialized")
    
    async def register_plugin(
        self,
        plugin_id: str,
        version: str,
        dependencies: List[PluginDependency] = None
    ) -> bool:
        """Зарегистрировать плагин и его зависимости"""
        async with self._lock:
            plugin_info = PluginInfo(
                id=plugin_id,
                version=version,
                dependencies=dependencies or []
            )
            self.plugins[plugin_id] = plugin_info
            
            # Построить граф зависимостей
            await self._build_dependency_graph(plugin_info)
            
            logger.info(f"Registered plugin {plugin_id} v{version} with {len(dependencies or [])} dependencies")
            return True
    
    async def _build_dependency_graph(self, plugin_info: PluginInfo):
        """Построить граф зависимостей для плагина"""
        deps = set()
        for dep in plugin_info.dependencies:
            if dep.dependency_type != DependencyType.CONFLICTS:
                deps.add(dep.plugin_id)
        
        self._dependency_graph[plugin_info.id] = deps
        
        # Построить обратный граф (кто зависит от этого плагина)
        for dep_id in deps:
            if dep_id not in self._reverse_graph:
                self._reverse_graph[dep_id] = set()
            self._reverse_graph[dep_id].add(plugin_info.id)
    
    async def check_compatibility(self, plugin_id: str, version: str) -> Tuple[bool, List[str]]:
        """Проверить совместимость плагина с текущими зависимостями"""
        errors = []
        
        # Проверяем, есть ли уже плагин с таким ID
        if plugin_id in self.plugins:
            existing_version = self.plugins[plugin_id].version
            if existing_version != version:
                errors.append(f"Plugin {plugin_id} already exists with version {existing_version}, trying to register {version}")
        
        # Проверяем зависимости
        if plugin_id in self.plugins:
            plugin_info = self.plugins[plugin_id]
            for dep in plugin_info.dependencies:
                if dep.plugin_id in self.plugins:
                    installed_version = self.plugins[dep.plugin_id].version
                    try:
                        if not self._check_version_spec(installed_version, dep.version_spec):
                            errors.append(f"Dependency {dep.plugin_id} version {installed_version} does not satisfy {dep.version_spec}")
                    except Exception as e:
                        errors.append(f"Invalid version spec for dependency {dep.plugin_id}: {e}")
                elif dep.dependency_type == DependencyType.REQUIRED:
                    errors.append(f"Required dependency {dep.plugin_id} not found")
        
        return len(errors) == 0, errors

    def _check_version_spec(self, version: str, spec: str) -> bool:
        """
        Простая проверка спецификации версии.
        Поддерживает форматы: '1.0.0', '>=1.0.0', '<=2.0.0', '>=1.0.0,<2.0.0'
        """
        # Разбиваем спецификацию на части (для составных спецификаций)
        specs = [s.strip() for s in spec.split(',')]

        for single_spec in specs:
            if single_spec.startswith('>='):
                min_version = single_spec[2:]
                if not self._version_gte(version, min_version):
                    return False
            elif single_spec.startswith('<='):
                max_version = single_spec[2:]
                if not self._version_lte(version, max_version):
                    return False
            elif single_spec.startswith('>'):
                min_version = single_spec[1:]
                if not self._version_gt(version, min_version):
                    return False
            elif single_spec.startswith('<'):
                max_version = single_spec[1:]
                if not self._version_lt(version, max_version):
                    return False
            elif single_spec.startswith('==') or single_spec.startswith('='):
                target_version = single_spec[2:] if single_spec.startswith('==') else single_spec[1:]
                if not self._version_eq(version, target_version):
                    return False
            elif single_spec.startswith('!='):
                target_version = single_spec[2:]
                if self._version_eq(version, target_version):
                    return False
            else:
                # Простое совпадение
                if not self._version_eq(version, single_spec):
                    return False

        return True

    def _version_gte(self, v1: str, v2: str) -> bool:
        """Проверить, что v1 >= v2"""
        return self._compare_versions(v1, v2) >= 0

    def _version_lte(self, v1: str, v2: str) -> bool:
        """Проверить, что v1 <= v2"""
        return self._compare_versions(v1, v2) <= 0

    def _version_gt(self, v1: str, v2: str) -> bool:
        """Проверить, что v1 > v2"""
        return self._compare_versions(v1, v2) > 0

    def _version_lt(self, v1: str, v2: str) -> bool:
        """Проверить, что v1 < v2"""
        return self._compare_versions(v1, v2) < 0

    def _version_eq(self, v1: str, v2: str) -> bool:
        """Проверить, что v1 == v2"""
        return self._compare_versions(v1, v2) == 0

    def _compare_versions(self, v1: str, v2: str) -> int:
        """
        Сравнить две версии.
        Возвращает: -1 если v1 < v2, 0 если v1 == v2, 1 если v1 > v2
        """
        # Разбиваем версии на компоненты
        parts1 = [int(x) for x in v1.split('.') if x.isdigit()]
        parts2 = [int(x) for x in v2.split('.') if x.isdigit()]

        # Приводим к одинаковой длине
        max_len = max(len(parts1), len(parts2))
        parts1.extend([0] * (max_len - len(parts1)))
        parts2.extend([0] * (max_len - len(parts2)))

        # Сравниваем по компонентам
        for p1, p2 in zip(parts1, parts2):
            if p1 < p2:
                return -1
            elif p1 > p2:
                return 1

        return 0

    async def resolve_load_order(self) -> List[str]:
        """Решить порядок загрузки плагинов на основе зависимостей"""
        # Используем топологическую сортировку
        visited = set()
        temp = set()
        order = []
        
        def dfs(node: str) -> bool:
            """Depth-first search для топологической сортировки"""
            if node in temp:
                # Обнаружен цикл
                raise ValueError(f"Dependency cycle detected: {node}")
            if node in visited:
                return True
            
            temp.add(node)
            
            # Обходим зависимости
            for dep in self._dependency_graph.get(node, set()):
                if not dfs(dep):
                    return False
            
            temp.remove(node)
            visited.add(node)
            order.append(node)
            return True
        
        try:
            for plugin_id in self.plugins:
                if plugin_id not in visited:
                    dfs(plugin_id)
            
            return order
        except ValueError as e:
            logger.error(f"Dependency resolution failed: {e}")
            return []
    
    async def get_plugin_dependents(self, plugin_id: str) -> List[str]:
        """Получить список плагинов, которые зависят от указанного плагина"""
        if plugin_id in self._reverse_graph:
            return list(self._reverse_graph[plugin_id])
        return []
    
    async def get_plugin_dependencies(self, plugin_id: str) -> List[str]:
        """Получить список зависимостей плагина"""
        if plugin_id in self._dependency_graph:
            return list(self._dependency_graph[plugin_id])
        return []
    
    async def can_load_plugin(self, plugin_id: str) -> Tuple[bool, List[str]]:
        """Проверить, можно ли загрузить плагин с текущими зависимостями"""
        if plugin_id not in self.plugins:
            return False, [f"Plugin {plugin_id} not registered"]
        
        errors = []
        plugin_info = self.plugins[plugin_id]
        
        for dep in plugin_info.dependencies:
            if dep.dependency_type == DependencyType.CONFLICTS:
                # Проверяем, что конфликтующий плагин не загружен
                if dep.plugin_id in self.plugins and self.plugins[dep.plugin_id].loaded:
                    errors.append(f"Plugin {plugin_id} conflicts with loaded plugin {dep.plugin_id}")
            elif dep.dependency_type in [DependencyType.REQUIRED, DependencyType.OPTIONAL]:
                # Проверяем, что зависимость установлена и совместима
                if dep.plugin_id not in self.plugins:
                    if dep.dependency_type == DependencyType.REQUIRED:
                        errors.append(f"Required dependency {dep.plugin_id} not installed")
                else:
                    installed_version = self.plugins[dep.plugin_id].version
                    try:
                        if not SpecifierSet(dep.version_spec).contains(installed_version):
                            errors.append(f"Dependency {dep.plugin_id} version {installed_version} does not satisfy {dep.version_spec}")
                    except Exception as e:
                        errors.append(f"Invalid version spec for dependency {dep.plugin_id}: {e}")
        
        return len(errors) == 0, errors
    
    async def mark_plugin_loaded(self, plugin_id: str, loaded: bool = True) -> bool:
        """Отметить плагин как загруженный или выгруженный"""
        if plugin_id not in self.plugins:
            return False
        
        self.plugins[plugin_id].loaded = loaded
        logger.info(f"Plugin {plugin_id} marked as {'loaded' if loaded else 'unloaded'}")
        return True
    
    async def check_conflicts(self, plugin_id: str) -> List[str]:
        """Проверить конфликты для плагина"""
        conflicts = []
        
        if plugin_id not in self.plugins:
            return conflicts
        
        plugin_info = self.plugins[plugin_id]
        
        # Проверяем зависимости с типом CONFLICTS
        for dep in plugin_info.dependencies:
            if dep.dependency_type == DependencyType.CONFLICTS:
                if dep.plugin_id in self.plugins and self.plugins[dep.plugin_id].loaded:
                    conflicts.append(dep.plugin_id)
        
        # Проверяем, не конфликтуют ли другие плагины с этим
        for other_id, other_info in self.plugins.items():
            if other_id == plugin_id:
                continue
            
            for other_dep in other_info.dependencies:
                if (other_dep.dependency_type == DependencyType.CONFLICTS and 
                    other_dep.plugin_id == plugin_id and 
                    other_info.loaded):
                    conflicts.append(other_id)
        
        return conflicts
    
    async def get_load_plan(self, target_plugins: List[str]) -> Tuple[List[str], List[str]]:
        """Получить план загрузки плагинов с учетом зависимостей"""
        # Сначала определяем все необходимые зависимости
        all_needed = set(target_plugins)
        visited = set()
        
        def collect_deps(plugin_id: str):
            if plugin_id in visited:
                return
            visited.add(plugin_id)
            
            if plugin_id in self.plugins:
                for dep_id in self._dependency_graph.get(plugin_id, set()):
                    all_needed.add(dep_id)
                    collect_deps(dep_id)
        
        for plugin_id in target_plugins:
            collect_deps(plugin_id)
        
        # Получаем порядок загрузки для всех необходимых плагинов
        load_order = await self.resolve_load_order()
        
        # Фильтруем, чтобы остались только нужные плагины
        filtered_order = [pid for pid in load_order if pid in all_needed]
        
        # Проверяем, можно ли загрузить каждый плагин
        can_load = []
        cannot_load = []
        
        for plugin_id in filtered_order:
            can_load_plugin, errors = await self.can_load_plugin(plugin_id)
            if can_load_plugin:
                can_load.append(plugin_id)
            else:
                cannot_load.extend(errors)
        
        return can_load, cannot_load
    
    async def get_dependency_report(self) -> Dict[str, Dict[str, List[str]]]:
        """Получить отчет о зависимостях"""
        report = {
            'plugins': {},
            'cycles': [],
            'conflicts': []
        }
        
        for plugin_id, plugin_info in self.plugins.items():
            report['plugins'][plugin_id] = {
                'version': plugin_info.version,
                'loaded': plugin_info.loaded,
                'dependencies': [
                    {
                        'plugin_id': dep.plugin_id,
                        'version_spec': dep.version_spec,
                        'type': dep.dependency_type.value
                    }
                    for dep in plugin_info.dependencies
                ],
                'dependents': await self.get_plugin_dependents(plugin_id)
            }
        
        # Проверяем циклы
        try:
            await self.resolve_load_order()
        except ValueError as e:
            report['cycles'].append(str(e))
        
        # Проверяем конфликты
        for plugin_id in self.plugins:
            conflicts = await self.check_conflicts(plugin_id)
            if conflicts:
                report['conflicts'].append({
                    'plugin_id': plugin_id,
                    'conflicts_with': conflicts
                })
        
        return report


# Global instance
_plugin_dependency_manager: Optional[PluginDependencyManager] = None


def get_plugin_dependency_manager() -> PluginDependencyManager:
    """Получить глобальный экземпляр PluginDependencyManager"""
    global _plugin_dependency_manager
    if _plugin_dependency_manager is None:
        raise RuntimeError("PluginDependencyManager not initialized. Call init_plugin_dependency_manager first.")
    return _plugin_dependency_manager


def init_plugin_dependency_manager() -> PluginDependencyManager:
    """Инициализировать глобальный экземпляр PluginDependencyManager"""
    global _plugin_dependency_manager
    _plugin_dependency_manager = PluginDependencyManager()
    return _plugin_dependency_manager


__all__ = [
    "DependencyType",
    "PluginDependency", 
    "PluginInfo",
    "PluginDependencyManager",
    "get_plugin_dependency_manager",
    "init_plugin_dependency_manager"
]