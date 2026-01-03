# Developer Experience & Maintainability Guide

## 🎯 Цель

Максимальный комфорт для разработки и поддержки плагинов, упрощение работы с кодом.

---

## 📋 Содержание

1. [Инструменты разработчика](#инструменты-разработчика)
2. [Улучшенное логирование](#улучшенное-логирование)
3. [Hot Reload для плагинов](#hot-reload-для-плагинов)
4. [Валидация и проверки](#валидация-и-проверки)
5. [Шаблоны и генераторы](#шаблоны-и-генераторы)
6. [Отладка и диагностика](#отладка-и-диагностика)
7. [Тестирование плагинов](#тестирование-плагинов)
8. [Документация в коде](#документация-в-коде)
9. [Инструменты мониторинга](#инструменты-мониторинга)

---

## 🛠️ Инструменты разработчика

### 1. CLI для управления плагинами

Создать `core-service/tools/plugin_cli.py`:

```python
#!/usr/bin/env python3
"""
CLI инструмент для управления плагинами.
"""
import click
import asyncio
import httpx
from pathlib import Path

@click.group()
def cli():
    """Home Console Plugin CLI"""
    pass

@cli.command()
@click.argument('plugin_id')
def reload(plugin_id):
    """Перезагрузить плагин"""
    asyncio.run(_reload_plugin(plugin_id))

@cli.command()
def list():
    """Список всех плагинов"""
    asyncio.run(_list_plugins())

@cli.command()
@click.argument('plugin_id')
def status(plugin_id):
    """Статус плагина"""
    asyncio.run(_plugin_status(plugin_id))

@cli.command()
@click.argument('plugin_id')
def logs(plugin_id):
    """Логи плагина"""
    asyncio.run(_plugin_logs(plugin_id))

async def _reload_plugin(plugin_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"http://localhost:11000/api/plugins/{plugin_id}/reload")
        click.echo(resp.json())

async def _list_plugins():
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:11000/api/plugins")
        plugins = resp.json()
        for p in plugins:
            status = "✅" if p.get('loaded') else "❌"
            click.echo(f"{status} {p['id']} - {p.get('name', 'N/A')}")

if __name__ == '__main__':
    cli()
```

**Использование:**
```bash
python tools/plugin_cli.py list
python tools/plugin_cli.py reload pikvm_client
python tools/plugin_cli.py status pikvm_client
python tools/plugin_cli.py logs pikvm_client
```

---

### 2. Скрипт для создания нового плагина

Создать `core-service/tools/create_plugin.py`:

```python
#!/usr/bin/env python3
"""
Генератор шаблона нового плагина.
"""
import click
from pathlib import Path
import json

@click.command()
@click.argument('plugin_id')
@click.option('--name', prompt='Plugin name')
@click.option('--description', prompt='Description', default='')
def create(plugin_id, name, description):
    """Создать новый плагин из шаблона"""
    plugin_dir = Path(f"plugins/{plugin_id}")
    plugin_dir.mkdir(parents=True, exist_ok=True)
    
    # Создаем структуру
    (plugin_dir / "src").mkdir(exist_ok=True)
    (plugin_dir / "tests").mkdir(exist_ok=True)
    
    # manifest.json
    manifest = {
        "id": plugin_id,
        "name": name,
        "version": "1.0.0",
        "description": description,
        "author": "Your Name",
        "entry_point": "main.py"
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    
    # main.py
    main_py = f'''"""
{name} Plugin
{description}
"""
from home_console_sdk.plugin import InternalPluginBase
from fastapi import APIRouter
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)


class {name.replace(' ', '')}Plugin(InternalPluginBase):
    """{name} Plugin"""
    
    id = "{plugin_id}"
    name = "{name}"
    version = "1.0.0"
    description = "{description}"
    
    async def on_load(self):
        """Инициализация плагина"""
        self.router = APIRouter()
        self._register_routes()
        logger.info(f"✅ {{self.name}} plugin loaded")
    
    def _register_routes(self):
        """Регистрация API endpoints"""
        self.router.add_api_route(
            "/health",
            self.health_check,
            methods=["GET"]
        )
    
    async def health_check(self):
        """Health check endpoint"""
        return JSONResponse({{
            "status": "healthy",
            "plugin_id": self.id,
            "version": self.version
        }})
    
    async def on_unload(self):
        """Очистка при выгрузке"""
        logger.info(f"👋 {{self.name}} plugin unloaded")
'''
    (plugin_dir / "main.py").write_text(main_py)
    
    # README.md
    readme = f'''# {name}

{description}

## Установка

Плагин автоматически загружается из `plugins/{plugin_id}/`

## Конфигурация

Добавьте в переменные окружения или конфигурацию плагина:

```bash
PLUGIN_{plugin_id.upper()}_CONFIG_KEY=value
```

## API Endpoints

- `GET /api/plugins/{plugin_id}/health` - Health check

## Разработка

```bash
# Запустить с hot reload
CORE_RELOAD=1 python main.py

# Проверить плагин
curl http://localhost:11000/api/plugins/{plugin_id}/health
```
'''
    (plugin_dir / "README.md").write_text(readme)
    
    # requirements.txt
    (plugin_dir / "requirements.txt").write_text("# Plugin dependencies\n")
    
    # .gitignore
    gitignore = '''__pycache__/
*.pyc
*.pyo
*.pyd
.Python
*.so
*.egg
*.egg-info/
dist/
build/
.env
.venv
'''
    (plugin_dir / ".gitignore").write_text(gitignore)
    
    click.echo(f"✅ Plugin '{plugin_id}' created in {plugin_dir}")
    click.echo(f"📝 Edit {plugin_dir}/main.py to implement your plugin")

if __name__ == '__main__':
    create()
```

**Использование:**
```bash
python tools/create_plugin.py my_plugin --name "My Plugin" --description "Does something cool"
```

---

## 📝 Улучшенное логирование

### 1. Структурированное логирование для плагинов

Создать `core-service/utils/plugin_logger.py`:

```python
"""
Улучшенное логирование для плагинов с контекстом.
"""
import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional

class PluginLogger:
    """Логгер с контекстом плагина"""
    
    def __init__(self, plugin_id: str, plugin_name: str):
        self.plugin_id = plugin_id
        self.plugin_name = plugin_name
        self.logger = logging.getLogger(f"plugin.{plugin_id}")
        self._context: Dict[str, Any] = {}
    
    def set_context(self, **kwargs):
        """Установить контекст для всех последующих логов"""
        self._context.update(kwargs)
    
    def clear_context(self):
        """Очистить контекст"""
        self._context.clear()
    
    def _format_message(self, message: str, extra: Optional[Dict] = None) -> str:
        """Форматировать сообщение с контекстом"""
        context = {**self._context, **(extra or {})}
        if context:
            return f"[{self.plugin_id}] {message} | {json.dumps(context)}"
        return f"[{self.plugin_id}] {message}"
    
    def debug(self, message: str, **kwargs):
        self.logger.debug(self._format_message(message, kwargs))
    
    def info(self, message: str, **kwargs):
        self.logger.info(self._format_message(message, kwargs))
    
    def warning(self, message: str, **kwargs):
        self.logger.warning(self._format_message(message, kwargs))
    
    def error(self, message: str, exc_info=False, **kwargs):
        self.logger.error(self._format_message(message, kwargs), exc_info=exc_info)
    
    def critical(self, message: str, **kwargs):
        self.logger.critical(self._format_message(message, kwargs))
    
    def log_event(self, event_type: str, data: Dict[str, Any]):
        """Логировать событие плагина"""
        self.info(f"Event: {event_type}", event_type=event_type, **data)
    
    def log_performance(self, operation: str, duration: float, **kwargs):
        """Логировать производительность операции"""
        self.debug(
            f"Performance: {operation}",
            operation=operation,
            duration_ms=duration * 1000,
            **kwargs
        )
```

**Использование в плагине:**
```python
from core_service.utils.plugin_logger import PluginLogger

class MyPlugin(InternalPluginBase):
    async def on_load(self):
        self.logger = PluginLogger(self.id, self.name)
        self.logger.set_context(version=self.version)
        
        # Обычное логирование
        self.logger.info("Plugin loaded")
        
        # С контекстом
        self.logger.info("Processing request", request_id="123", user_id="456")
        
        # События
        self.logger.log_event("device.updated", {"device_id": "dev1", "state": "on"})
        
        # Производительность
        import time
        start = time.time()
        # ... операция ...
        self.logger.log_performance("fetch_devices", time.time() - start, count=10)
```

---

### 2. Централизованный сбор логов плагинов

Создать `core-service/utils/log_collector.py` (расширить существующий):

```python
"""
Сбор и фильтрация логов плагинов.
"""
from collections import deque
from typing import List, Dict, Optional
import logging
import re

class PluginLogCollector(logging.Handler):
    """Сборщик логов для плагинов"""
    
    def __init__(self, max_size: int = 1000):
        super().__init__()
        self.logs: deque = deque(maxlen=max_size)
        self.filters: Dict[str, List[str]] = {}  # plugin_id -> [patterns]
    
    def emit(self, record: logging.LogRecord):
        """Сохранить лог"""
        # Извлекаем plugin_id из имени логгера
        plugin_id = None
        if record.name.startswith("plugin."):
            plugin_id = record.name.split(".", 1)[1]
        
        log_entry = {
            "timestamp": record.created,
            "level": record.levelname,
            "plugin_id": plugin_id,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Добавляем exception info если есть
        if record.exc_info:
            log_entry["exception"] = self.format(record)
        
        self.logs.append(log_entry)
    
    def get_logs(
        self,
        plugin_id: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Получить логи с фильтрацией"""
        logs = list(self.logs)
        
        if plugin_id:
            logs = [l for l in logs if l.get("plugin_id") == plugin_id]
        
        if level:
            logs = [l for l in logs if l.get("level") == level.upper()]
        
        return logs[-limit:]
    
    def clear_logs(self, plugin_id: Optional[str] = None):
        """Очистить логи"""
        if plugin_id:
            self.logs = deque(
                [l for l in self.logs if l.get("plugin_id") != plugin_id],
                maxlen=self.logs.maxlen
            )
        else:
            self.logs.clear()
```

---

## 🔄 Hot Reload для плагинов

### Реализация hot reload

Создать `core-service/plugin_system/hot_reload.py`:

```python
"""
Hot reload для плагинов без перезапуска core-service.
"""
import importlib
import asyncio
import logging
from typing import Dict, Optional
from pathlib import Path
import sys

logger = logging.getLogger(__name__)

class PluginHotReloader:
    """Hot reload для плагинов"""
    
    def __init__(self, plugin_loader):
        self.plugin_loader = plugin_loader
        self._reload_lock = asyncio.Lock()
    
    async def reload_plugin(self, plugin_id: str) -> Dict[str, Any]:
        """Перезагрузить плагин"""
        async with self._reload_lock:
            if plugin_id not in self.plugin_loader.plugins:
                return {"error": f"Plugin '{plugin_id}' not found"}
            
            plugin = self.plugin_loader.plugins[plugin_id]
            
            try:
                # 1. Вызываем on_unload
                if hasattr(plugin, 'on_unload'):
                    await plugin.on_unload()
                
                # 2. Отмонтируем router
                if hasattr(plugin, 'unmount_router'):
                    await plugin.unmount_router()
                
                # 3. Перезагружаем модуль
                module_name = plugin.__class__.__module__
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
                
                # 4. Пересоздаем экземпляр плагина
                plugin_class = plugin.__class__
                new_plugin = plugin_class()
                
                # 5. Инициализируем новый экземпляр
                new_plugin.app = self.plugin_loader.app
                new_plugin.db_session_maker = self.plugin_loader.db_session_maker
                new_plugin.event_bus = self.plugin_loader.event_bus
                
                # 6. Загружаем плагин
                await new_plugin.on_load()
                
                # 7. Монтируем router
                if hasattr(new_plugin, 'mount_router'):
                    await new_plugin.mount_router()
                
                # 8. Заменяем в словаре
                self.plugin_loader.plugins[plugin_id] = new_plugin
                
                logger.info(f"✅ Plugin '{plugin_id}' reloaded successfully")
                return {
                    "status": "success",
                    "plugin_id": plugin_id,
                    "version": getattr(new_plugin, 'version', 'unknown')
                }
            
            except Exception as e:
                logger.error(f"❌ Failed to reload plugin '{plugin_id}': {e}", exc_info=True)
                return {
                    "status": "error",
                    "plugin_id": plugin_id,
                    "error": str(e)
                }
```

**Добавить endpoint в `routes/plugins.py`:**

```python
@router.post("/plugins/{plugin_id}/reload")
async def reload_plugin(plugin_id: str, request: Request):
    """Hot reload плагина"""
    if not hasattr(request.app.state, 'plugin_loader'):
        raise HTTPException(500, "Plugin loader not available")
    
    from core_service.plugin_system.hot_reload import PluginHotReloader
    reloader = PluginHotReloader(request.app.state.plugin_loader)
    result = await reloader.reload_plugin(plugin_id)
    
    if result.get("status") == "error":
        raise HTTPException(500, detail=result.get("error"))
    
    return JSONResponse(result)
```

---

## ✅ Валидация и проверки

### 1. Валидатор структуры плагина

Создать `core-service/tools/validate_plugin.py`:

```python
#!/usr/bin/env python3
"""
Валидатор структуры плагина.
"""
import json
import sys
from pathlib import Path
from typing import List, Dict

def validate_plugin(plugin_dir: Path) -> List[str]:
    """Валидировать структуру плагина"""
    errors = []
    
    # Проверка manifest.json
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        errors.append("❌ manifest.json not found")
        return errors
    
    try:
        manifest = json.loads(manifest_path.read_text())
        required_fields = ["id", "name", "version"]
        for field in required_fields:
            if field not in manifest:
                errors.append(f"❌ manifest.json missing field: {field}")
    except json.JSONDecodeError as e:
        errors.append(f"❌ manifest.json is invalid JSON: {e}")
    
    # Проверка main.py
    main_py = plugin_dir / "main.py"
    if not main_py.exists():
        errors.append("❌ main.py not found")
    else:
        # Проверка что есть класс плагина
        content = main_py.read_text()
        if "InternalPluginBase" not in content:
            errors.append("❌ main.py doesn't inherit from InternalPluginBase")
        if "class" not in content:
            errors.append("❌ main.py doesn't contain plugin class")
    
    # Проверка README
    readme = plugin_dir / "README.md"
    if not readme.exists():
        errors.append("⚠️ README.md not found (recommended)")
    
    return errors

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: validate_plugin.py <plugin_dir>")
        sys.exit(1)
    
    plugin_dir = Path(sys.argv[1])
    errors = validate_plugin(plugin_dir)
    
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    else:
        print("✅ Plugin structure is valid")
```

---

### 2. Проверка зависимостей

Создать `core-service/tools/check_dependencies.py`:

```python
#!/usr/bin/env python3
"""
Проверка зависимостей плагина.
"""
import subprocess
import sys
from pathlib import Path

def check_plugin_dependencies(plugin_dir: Path) -> bool:
    """Проверить что все зависимости установлены"""
    requirements = plugin_dir / "requirements.txt"
    if not requirements.exists():
        return True  # Нет зависимостей
    
    deps = requirements.read_text().strip().split("\n")
    deps = [d.strip() for d in deps if d.strip() and not d.startswith("#")]
    
    missing = []
    for dep in deps:
        # Извлекаем имя пакета (до == или >=)
        pkg_name = dep.split("==")[0].split(">=")[0].split("<=")[0].strip()
        try:
            __import__(pkg_name.replace("-", "_"))
        except ImportError:
            missing.append(pkg_name)
    
    if missing:
        print(f"❌ Missing dependencies: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)}")
        return False
    
    print("✅ All dependencies installed")
    return True

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: check_dependencies.py <plugin_dir>")
        sys.exit(1)
    
    plugin_dir = Path(sys.argv[1])
    if not check_plugin_dependencies(plugin_dir):
        sys.exit(1)
```

---

## 📚 Шаблоны и генераторы

### Шаблон плагина с полной структурой

Создать `core-service/templates/plugin_template/`:

```
plugin_template/
├── manifest.json
├── main.py
├── README.md
├── requirements.txt
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── config.py
│   └── handlers.py
└── tests/
    ├── __init__.py
    └── test_plugin.py
```

---

## 🐛 Отладка и диагностика

### 1. Debug режим для плагинов

Добавить в `InternalPluginBase`:

```python
@property
def is_debug(self) -> bool:
    """Проверить включен ли debug режим"""
    return os.getenv(f"PLUGIN_{self.id.upper()}_DEBUG", "false").lower() == "true"

async def on_load(self):
    if self.is_debug:
        self.logger.setLevel(logging.DEBUG)
        self.logger.debug("🐛 Debug mode enabled")
```

---

### 2. Health check endpoint для всех плагинов

Добавить автоматический health check:

```python
# В InternalPluginBase
async def health_check(self) -> Dict[str, Any]:
    """Автоматический health check"""
    health = {
        "status": "healthy",
        "plugin_id": self.id,
        "version": self.version,
        "loaded": self.is_loaded,
        "router_mounted": self.is_router_mounted
    }
    
    # Плагин может переопределить для дополнительных проверок
    if hasattr(self, '_health_check'):
        custom_health = await self._health_check()
        health.update(custom_health)
    
    return health
```

---

## 🧪 Тестирование плагинов

### Шаблон тестов для плагина

Создать `core-service/templates/plugin_template/tests/test_plugin.py`:

```python
"""
Тесты для плагина.
"""
import pytest
from unittest.mock import Mock, AsyncMock
from your_plugin.main import YourPlugin

@pytest.fixture
def plugin():
    """Создать экземпляр плагина для тестов"""
    plugin = YourPlugin()
    plugin.app = Mock()
    plugin.db_session_maker = Mock()
    plugin.event_bus = Mock()
    return plugin

@pytest.mark.asyncio
async def test_plugin_load(plugin):
    """Тест загрузки плагина"""
    await plugin.on_load()
    assert plugin.is_loaded
    assert plugin.router is not None

@pytest.mark.asyncio
async def test_health_check(plugin):
    """Тест health check"""
    await plugin.on_load()
    health = await plugin.health_check()
    assert health["status"] == "healthy"
    assert health["plugin_id"] == plugin.id
```

---

## 📖 Документация в коде

### Стандарт документации плагинов

```python
"""
Название плагина.

Описание что делает плагин.

## Конфигурация

Переменные окружения:
- PLUGIN_ID_CONFIG_KEY: Описание

## API Endpoints

- GET /api/plugins/plugin_id/endpoint: Описание

## События

Публикует:
- plugin_id.event_name: Описание

Подписывается:
- other_plugin.*: Описание

## Примеры

```python
# Пример использования
```

## Разработка

```bash
# Команды для разработки
```
"""
```

---

## 📊 Инструменты мониторинга

### Dashboard для разработчиков

Создать `core-service/routes/dev_dashboard.py`:

```python
"""
Dashboard для разработчиков плагинов.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/dev", tags=["developer"])

@router.get("/dashboard")
async def dev_dashboard(request: Request):
    """Dashboard для разработчиков"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Plugin Developer Dashboard</title>
        <style>
            body { font-family: monospace; padding: 20px; }
            .plugin { border: 1px solid #ccc; padding: 10px; margin: 10px 0; }
            .status { font-weight: bold; }
            .status.healthy { color: green; }
            .status.error { color: red; }
        </style>
    </head>
    <body>
        <h1>Plugin Developer Dashboard</h1>
        <div id="plugins"></div>
        <script>
            async function loadPlugins() {
                const res = await fetch('/api/plugins');
                const plugins = await res.json();
                const container = document.getElementById('plugins');
                container.innerHTML = plugins.map(p => `
                    <div class="plugin">
                        <h3>${p.id}</h3>
                        <p class="status ${p.loaded ? 'healthy' : 'error'}">
                            ${p.loaded ? '✅ Loaded' : '❌ Not Loaded'}
                        </p>
                        <button onclick="reloadPlugin('${p.id}')">Reload</button>
                        <button onclick="viewLogs('${p.id}')">View Logs</button>
                    </div>
                `).join('');
            }
            async function reloadPlugin(id) {
                await fetch(`/api/plugins/${id}/reload`, {method: 'POST'});
                loadPlugins();
            }
            loadPlugins();
            setInterval(loadPlugins, 5000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(html)
```

---

## 🎯 Чеклист для разработчика плагина

- [ ] Создан через `create_plugin.py`
- [ ] Валидирован через `validate_plugin.py`
- [ ] Зависимости проверены через `check_dependencies.py`
- [ ] Написан README с примерами
- [ ] Добавлены тесты
- [ ] Настроено логирование с контекстом
- [ ] Реализован health check
- [ ] Документированы API endpoints
- [ ] Описаны события (публикуемые/подписываемые)
- [ ] Протестирован hot reload

---

## 🚀 Быстрый старт

```bash
# 1. Создать плагин
python tools/create_plugin.py my_plugin

# 2. Валидировать структуру
python tools/validate_plugin.py plugins/my_plugin

# 3. Проверить зависимости
python tools/check_dependencies.py plugins/my_plugin

# 4. Запустить с hot reload
CORE_RELOAD=1 python main.py

# 5. Перезагрузить плагин
curl -X POST http://localhost:11000/api/plugins/my_plugin/reload

# 6. Посмотреть логи
python tools/plugin_cli.py logs my_plugin

# 7. Открыть dashboard
open http://localhost:11000/dev/dashboard
```

---

## 📝 Резюме

Эти инструменты обеспечивают:

✅ **Быстрое создание** плагинов через шаблоны  
✅ **Удобную отладку** через улучшенное логирование  
✅ **Hot reload** без перезапуска  
✅ **Валидацию** структуры и зависимостей  
✅ **Мониторинг** через dashboard  
✅ **Тестирование** через шаблоны тестов  
✅ **Документацию** через стандарты  

Это значительно упрощает разработку и поддержку плагинов! 🎉

