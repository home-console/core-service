# Управление зависимостями плагинов

## Текущая реализация (что уже работает)

### ✅ Установка плагинов из Git

Работает через REST API:
```bash
POST /api/v1/admin/plugins/install
{
  "type": "git",
  "git_url": "https://github.com/user/my-plugin.git"
}
```

**Что происходит:**
1. `git clone --depth 1` репозитория в временную папку
2. Поиск `plugin.json` (в корне или в единственной вложенной папке)
3. Копирование плагина в `PLUGINS_DIR` (env переменная)
4. **✅ НОВОЕ:** Автоматическая установка зависимостей из `requirements.txt` через `pip install -r requirements.txt --user`
5. Загрузка плагина (импорт Python модуля и вызов `on_load()`)
6. Регистрация роутов плагина в FastAPI

**Пример структуры плагина:**
```
my-plugin/
├── plugin.json           # Обязательно: метаданные
├── requirements.txt      # Опционально: зависимости
├── main.py              # Точка входа с классом плагина
└── README.md
```

### ✅ Установка из URL (zip/tar.gz)

```bash
POST /api/v1/admin/plugins/install
{
  "type": "url",
  "url": "https://example.com/my-plugin.zip"
}
```

**Что происходит:**
1. Скачивание архива
2. Распаковка в `PLUGINS_DIR`
3. **✅ НОВОЕ:** Установка зависимостей из `requirements.txt`
4. Загрузка плагина

### ✅ Установка из локальной папки

```bash
POST /api/v1/admin/plugins/install
{
  "type": "local",
  "path": "/path/to/my-plugin"
}
```

## ⚠️ Что НЕ реализовано (проблемы)

### 1. Изоляция зависимостей

**Проблема:** Все зависимости устанавливаются в общее окружение (`--user` flag).

**Риски:**
- Конфликты версий между плагинами (плагин A требует `requests==2.28`, плагин B требует `requests==2.31`)
- Загрязнение глобального окружения
- Невозможность полностью удалить зависимости при удалении плагина

**Решения:**
1. **Виртуальные окружения для каждого плагина** (рекомендуется):
   - Создавать отдельный venv для каждого плагина в `PLUGINS_DIR/my-plugin/.venv`
   - Импортировать модули через `importlib` с подменой `sys.path`
   - Пример: `sys.path.insert(0, f"{plugin_dir}/.venv/lib/python3.x/site-packages")`

2. **Контейнеризация плагинов** (для production):
   - Каждый плагин как отдельный Docker контейнер/sidecar
   - Общение через HTTP API (уже реализовано для external plugins)
   - Полная изоляция зависимостей, ресурсов и безопасности

3. **Tracking зависимостей** (минимальное решение):
   - Сохранять список установленных пакетов для каждого плагина в БД
   - При удалении плагина проверять, используются ли зависимости другими плагинами
   - Удалять только "осиротевшие" пакеты

### 2. Удаление зависимостей при uninstall

**Проблема:** При удалении плагина зависимости остаются установленными.

**Текущее поведение:**
```python
await plugin_loader.uninstall_plugin("my_plugin")
# Удаляет файлы плагина, но НЕ удаляет зависимости
```

**Что нужно добавить:**
```python
# При установке - сохранять список зависимостей
plugin_deps = {
    "my_plugin": ["requests==2.31.0", "pydantic==2.0.0"]
}

# При удалении - проверять и удалять
await plugin_loader.uninstall_plugin("my_plugin", remove_deps=True)
# -> проверить, используются ли deps другими плагинами
# -> удалить неиспользуемые через pip uninstall
```

### 3. Обновление плагинов

**Проблема:** Нет механизма обновления плагина с сохранением/обновлением зависимостей.

**Что нужно:**
- `POST /api/v1/admin/plugins/{plugin_id}/update` endpoint
- Логика сравнения старых/новых зависимостей
- Обновление только измененных пакетов

### 4. Версионирование и конфликты

**Проблема:** Нет проверки совместимости версий между плагинами.

**Что нужно:**
- Dependency resolver (как у Poetry/pip)
- Проверка конфликтов перед установкой
- Предупреждения пользователю о потенциальных проблемах

## 🔧 Рекомендации по реализации

### Короткое решение (для демо/dev)

Добавить tracking в БД:

```python
class PluginDependency(Base):
    __tablename__ = "plugin_dependencies"
    id = Column(String, primary_key=True)
    plugin_id = Column(String, ForeignKey("plugins.id"))
    package_name = Column(String)  # requests
    version = Column(String)       # 2.31.0
    installed_at = Column(DateTime)
```

При установке:
```python
def _install_plugin_dependencies(self, plugin_path, plugin_id):
    # ... existing code ...
    # Parse requirements.txt and save to DB
    with open(requirements_file) as f:
        for line in f:
            # Parse "requests==2.31.0"
            # Save to PluginDependency table
```

При удалении:
```python
async def uninstall_plugin(self, plugin_id, remove_deps=False):
    # ... existing code ...
    if remove_deps:
        deps = await self._get_plugin_dependencies(plugin_id)
        for dep in deps:
            if not await self._is_dependency_used_by_other_plugins(dep):
                # pip uninstall -y {dep.package_name}
```

### Надёжное решение (для production)

**Вариант 1: Виртуальные окружения**

```python
def _create_plugin_venv(self, plugin_path, plugin_id):
    venv_path = os.path.join(plugin_path, '.venv')
    subprocess.run([sys.executable, '-m', 'venv', venv_path])
    pip_path = os.path.join(venv_path, 'bin', 'pip')
    
    requirements = os.path.join(plugin_path, 'requirements.txt')
    subprocess.run([pip_path, 'install', '-r', requirements])
    
    return venv_path

def _load_plugin_from_venv(self, plugin_path, plugin_id, venv_path):
    site_packages = os.path.join(venv_path, 'lib', f'python{sys.version_info.major}.{sys.version_info.minor}', 'site-packages')
    sys.path.insert(0, site_packages)
    
    # Load plugin module
    # ...
    
    sys.path.remove(site_packages)
```

**Вариант 2: Контейнеры (рекомендуется)**

Для плагинов с зависимостями — запускать как external microservice:

```yaml
# docker-compose.yml для плагина
services:
  my-plugin:
    build: ./plugins/my-plugin
    environment:
      - PLUGIN_ID=my_plugin
      - CORE_URL=http://core:11000
    networks:
      - plugins
```

Core регистрирует плагин как external:
```python
from plugin_registry import external_plugin_registry
external_plugin_registry.register_plugin("my_plugin", "http://my-plugin:8000")
```

## 📝 Итого: что работает сейчас

✅ **Работает:**
- Установка плагинов из Git/URL/локальной папки
- Автоматическая установка зависимостей из `requirements.txt`
- Загрузка и регистрация плагинов
- Удаление плагинов (файлов)

❌ **Не работает / требует доработки:**
- Изоляция зависимостей (все в один --user env)
- Удаление зависимостей при uninstall
- Обнаружение конфликтов версий
- Обновление плагинов
- Tracking установленных пакетов

⚠️ **Для production обязательно:**
- Использовать виртуальные окружения или контейнеры
- Добавить проверку конфликтов
- Реализовать полное удаление зависимостей

## 🚀 Быстрый тест

```bash
# 1. Создайте тестовый плагин с зависимостями
mkdir -p /tmp/test-plugin
cat > /tmp/test-plugin/plugin.json << 'EOF'
{
  "id": "test_plugin",
  "name": "Test Plugin",
  "version": "1.0.0",
  "type": "internal"
}
EOF

cat > /tmp/test-plugin/requirements.txt << 'EOF'
httpx>=0.24.0
pydantic>=2.0.0
EOF

cat > /tmp/test-plugin/main.py << 'EOF'
from home_console_sdk.plugin import InternalPluginBase

class TestPlugin(InternalPluginBase):
    id = "test_plugin"
    name = "Test Plugin"
    version = "1.0.0"
    
    async def on_load(self):
        import httpx
        import pydantic
        self.logger.info(f"✅ Loaded with httpx {httpx.__version__}, pydantic {pydantic.__version__}")
EOF

# 2. Установите через API
curl -X POST http://127.0.0.1:11000/api/v1/admin/plugins/install \
  -H "Content-Type: application/json" \
  -d '{"type": "local", "path": "/tmp/test-plugin"}'

# 3. Проверьте логи core - должна быть установка зависимостей
# 4. Проверьте список плагинов
curl http://127.0.0.1:11000/api/v1/admin/plugins | jq .
```
