"""
Core Service Application - Clean FastAPI structure.

This is a refactored version of admin_app.py with better organization:
- Utilities moved to utils/ module
- Cleaner separation of concerns
- Better code organization
- Easier to maintain and extend

To use this instead of admin_app.py:
1. Update main.py to import from this file
2. Update asgi.py to import from this file
3. Test thoroughly
4. Remove old admin_app.py
"""
import os
import sys
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

# Configure logging early (only if not already configured)
if not logging.root.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
# Explicitly set logging level for all handlers
for handler in logging.root.handlers:
    handler.setLevel(logging.INFO)
# Set level for specific modules to INFO
logging.getLogger("core_service").setLevel(logging.INFO)
logging.getLogger("event_bus").setLevel(logging.INFO)
logging.getLogger("routes").setLevel(logging.INFO)
print("🔵 app.py: Log levels set")

# Подключить коллектор логов для просмотра через API (отложим до конца импортов)
print("🔵 app.py: Importing log_collector module (handler will be added later)...")
sys.stdout.flush()
try:
    from .utils.log_collector import application_log_collector
    print("✅ app.py: log_collector module imported (handler not added yet)")
    sys.stdout.flush()
except Exception as e:
    # Если не удалось импортировать, продолжаем без коллектора
    print(f"⚠️ app.py: Failed to import log_collector: {e}")
    import traceback
    traceback.print_exc()
    application_log_collector = None
    sys.stdout.flush()

print("🔵 app.py: About to import FastAPI...")
sys.stdout.flush()  # Принудительно сбросить буфер вывода
logging.info("🔵 app.py: About to import FastAPI (via logging)")
print("🔵 app.py: Importing FastAPI...")
sys.stdout.flush()
logging.info("🔵 app.py: Importing FastAPI (via logging)")

try:
    from fastapi import FastAPI
    print("✅ app.py: FastAPI imported")
    logging.info("✅ app.py: FastAPI imported (via logging)")
    sys.stdout.flush()
except Exception as e:
    print(f"❌ app.py: Failed to import FastAPI: {e}")
    logging.error(f"❌ app.py: Failed to import FastAPI: {e}", exc_info=True)
    import traceback
    traceback.print_exc()
    sys.stdout.flush()
    raise
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqladmin import Admin, ModelView
import sqlalchemy as sa
from sqlalchemy import text

print("🔵 app.py: Importing core modules...")
# Relative imports - try relative first, then absolute with package prefix
try:
    from .db import engine, get_session, AsyncSessionLocal
    from .models import Base
    from .plugin_loader import PluginLoader
    from .plugin_registry import external_plugin_registry
    from .plugin_mode_manager import init_plugin_mode_manager
    from .plugin_config import init_plugin_config_manager
    from .plugin_lifecycle_manager import init_plugin_lifecycle_manager
    from .plugin_security_manager import init_plugin_security_manager
    from .plugin_dependency_manager import init_plugin_dependency_manager
    from .health_monitor import HealthMonitor
    print("✅ app.py: Core modules imported")
except ImportError as e:
    print(f"❌ app.py: Failed to import core modules: {e}")
    import traceback
    traceback.print_exc()
    raise

# Client, CommandLog, Enrollment models are now in plugins/client_manager/models.py
# Import them conditionally for SQLAdmin views (only if plugin is loaded)
Client = None
CommandLog = None
Enrollment = None

print("🔵 app.py: Trying to import client_manager models...")
try:
    # Try relative import first
    from .plugins.client_manager.models import Client, CommandLog, Enrollment
    print("✅ app.py: client_manager models imported")
except ImportError:
    try:
        # Try absolute import with package prefix
        from core_service.plugins.client_manager.models import Client, CommandLog, Enrollment
        print("✅ app.py: client_manager models imported (absolute)")
    except ImportError:
        # Models not available - plugin may not be loaded yet or path is wrong
        # This is OK - SQLAdmin views will be skipped
        print("⚠️ app.py: client_manager models not available (this is OK)")

# Core models (always defined in core-service/models.py) - import with fallback
Device = None
PluginBinding = None
IntentMapping = None
DeviceLink = None
Plugin = None
PluginVersion = None
PluginInstallJob = None
User = None

print("🔵 app.py: Importing core models...")
try:
    from .models import Device, PluginBinding, IntentMapping, DeviceLink, Plugin, PluginVersion, PluginInstallJob, User
    print("✅ app.py: Core models imported")
except ImportError as e:
    print(f"⚠️ app.py: Failed to import core models: {e}")
    try:
        from core_service.models import Device, PluginBinding, IntentMapping, DeviceLink, Plugin, PluginVersion, PluginInstallJob, User
        print("✅ app.py: Core models imported (absolute)")
    except ImportError:
        # If models can't be imported, leave as None; admin views will be skipped
        print("⚠️ app.py: Core models not available (this is OK)")

logger = logging.getLogger(__name__)

# Global health monitor instance
_health_monitor = None

# Добавить handler к root logger после всех импортов (чтобы избежать проблем с рекурсией)
if application_log_collector is not None:
    try:
        print("🔵 app.py: Adding log collector handler to root logger (after imports)...")
        sys.stdout.flush()
        root_logger = logging.getLogger()
        root_logger.addHandler(application_log_collector)
        print("✅ app.py: Log collector handler added successfully")
        sys.stdout.flush()
        # Не вызываем logging.info здесь, чтобы избежать рекурсии
    except Exception as e:
        print(f"⚠️ app.py: Failed to add log collector handler: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()


# ============= SQLAdmin Model Views =============
# Note: Client, CommandLog, Enrollment models are in client_manager plugin
# These views are only created if models are available

if Client is not None:
    class ClientAdmin(ModelView, model=Client):
        column_list = [Client.id, Client.hostname, Client.ip, Client.port, Client.status, Client.last_heartbeat]
        name_plural = "Clients"
else:
    ClientAdmin = None

if CommandLog is not None:
    class CommandLogAdmin(ModelView, model=CommandLog):
        column_list = [CommandLog.id, CommandLog.client_id, CommandLog.command, CommandLog.status, CommandLog.exit_code, CommandLog.created_at]
        name_plural = "Command Logs"
else:
    CommandLogAdmin = None

if Enrollment is not None:
    class EnrollmentAdmin(ModelView, model=Enrollment):
        column_list = [Enrollment.id, Enrollment.status, Enrollment.created_at]
        name_plural = "Enrollments"
else:
    EnrollmentAdmin = None


# ============= Core Model Admin Views =============
if Device is not None:
    class DeviceAdmin(ModelView, model=Device):
        column_list = [Device.id, Device.name, Device.type, Device.is_online, Device.is_on, Device.last_seen, Device.created_at, Device.updated_at]
        form_excluded_columns = ["meta"]  # Исключаем JSON поле из формы
        name_plural = "Devices"
else:
    DeviceAdmin = None

if PluginBinding is not None:
    class PluginBindingAdmin(ModelView, model=PluginBinding):
        column_list = [PluginBinding.id, PluginBinding.device_id, PluginBinding.plugin_name, PluginBinding.enabled, PluginBinding.created_at]
        form_excluded_columns = ["config"]  # Исключаем JSON поле из формы
        name_plural = "Plugin Bindings"
else:
    PluginBindingAdmin = None

if IntentMapping is not None:
    class IntentMappingAdmin(ModelView, model=IntentMapping):
        column_list = [IntentMapping.id, IntentMapping.intent_name, IntentMapping.selector, IntentMapping.plugin_action, IntentMapping.created_at]
        name_plural = "Intent Mappings"
else:
    IntentMappingAdmin = None

if Plugin is not None:
    class PluginAdmin(ModelView, model=Plugin):
        column_list = [Plugin.id, Plugin.name, Plugin.publisher, Plugin.latest_version, Plugin.created_at]
        name_plural = "Plugins"
else:
    PluginAdmin = None

if PluginVersion is not None:
    class PluginVersionAdmin(ModelView, model=PluginVersion):
        column_list = [PluginVersion.id, PluginVersion.plugin_name, PluginVersion.version, PluginVersion.type, PluginVersion.artifact_url, PluginVersion.created_at]
        name_plural = "Plugin Versions"
else:
    PluginVersionAdmin = None

if PluginInstallJob is not None:
    class PluginInstallJobAdmin(ModelView, model=PluginInstallJob):
        column_list = [PluginInstallJob.id, PluginInstallJob.plugin_name, PluginInstallJob.version, PluginInstallJob.status, PluginInstallJob.created_at, PluginInstallJob.started_at, PluginInstallJob.finished_at]
        name_plural = "Plugin Install Jobs"
else:
    PluginInstallJobAdmin = None

if DeviceLink is not None:
    class DeviceLinkAdmin(ModelView, model=DeviceLink):
        column_list = [DeviceLink.id, DeviceLink.source_device_id, DeviceLink.target_device_id, DeviceLink.link_type, DeviceLink.direction, DeviceLink.enabled, DeviceLink.created_at]
        name_plural = "Device Links"
        column_searchable_list = [DeviceLink.source_device_id, DeviceLink.target_device_id]
else:
    DeviceLinkAdmin = None

if User is not None:
    class UserAdmin(ModelView, model=User):
        column_list = [User.id, User.username, User.email, User.role, User.enabled, User.created_at, User.last_login]
        name_plural = "Users"
        column_searchable_list = [User.username, User.email]
        # Фильтры будут доступны автоматически через интерфейс SQLAdmin
else:
    UserAdmin = None

# Модели из плагинов
YandexAccount = None
try:
    from .plugins.yandex_smart_home.main import YandexAccount
except ImportError:
    try:
        from core_service.plugins.yandex_smart_home.main import YandexAccount
    except ImportError:
        try:
            from .plugins.yandex_smart_home.models import YandexAccount
        except Exception:
            try:
                from core_service.plugins.yandex_smart_home.models import YandexAccount
            except Exception:
                pass

if YandexAccount is not None:
    class YandexAccountAdmin(ModelView, model=YandexAccount):
        # Не включаем токены в column_list для безопасности
        column_list = [YandexAccount.id, YandexAccount.user_id, YandexAccount.ya_user_id, YandexAccount.expires_at, YandexAccount.created_at, YandexAccount.updated_at]
        name_plural = "Yandex Accounts"
        column_searchable_list = [YandexAccount.user_id, YandexAccount.ya_user_id]
        # Токены будут видны только при редактировании отдельной записи, но не в списке
else:
    YandexAccountAdmin = None


# ============= Lifecycle Management =============

def register_external_plugins_from_env() -> list:
    """
    Auto-register external plugins from environment variables.
    
    Variables format:
      PLUGIN_{NAME}_URL=http://service:port
      PLUGIN_{NAME}_AUTH_TYPE=bearer|api_key
      PLUGIN_{NAME}_AUTH_TOKEN=secret
    """
    import re
    registered = []
    pattern = re.compile(r'^PLUGIN_([A-Z0-9_]+)_URL$')
    for k, v in os.environ.items():
        m = pattern.match(k)
        if not m:
            continue
        name = m.group(1)
        plugin_id = name.lower().replace('_', '-')
        base_url = v
        auth_type = os.getenv(f'PLUGIN_{name}_AUTH_TYPE')
        auth_token = os.getenv(f'PLUGIN_{name}_AUTH_TOKEN')
        timeout = float(os.getenv(f'PLUGIN_{name}_TIMEOUT', '30.0'))
        try:
            external_plugin_registry.register(
                plugin_id=plugin_id,
                base_url=base_url,
                auth_type=auth_type,
                auth_token=auth_token,
                timeout=timeout,
            )
            registered.append(plugin_id)
        except Exception as e:
            logger.warning(f"Failed registering external plugin from ENV: {plugin_id}: {e}")
    return registered


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager - startup and shutdown logic."""
    # Startup
    print("🚀 Starting application lifecycle...")
    logger.info("🚀 Starting application lifecycle...")
    
    try:
        # Создаем таблицы асинхронно
        print("📦 Creating database tables...")
        logger.info("📦 Creating database tables...")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

                # Ensure new plugin schema columns exist (for backward compatibility
                # when migrations were not applied to the target DB). We run a
                # synchronous inspector in the sync context and ALTER TABLE if needed.
                def _ensure_plugin_columns(sync_conn):
                    inspector = sa.inspect(sync_conn)
                    if 'plugins' not in inspector.get_table_names():
                        return
                    cols = [c['name'] for c in inspector.get_columns('plugins')]
                    to_alter = []
                    if 'supported_modes' not in cols:
                        to_alter.append('supported_modes')
                    if 'mode_switch_supported' not in cols:
                        to_alter.append('mode_switch_supported')

                    if not to_alter:
                        return

                    dialect = sync_conn.dialect.name
                    # Build and execute ALTER statements appropriate for dialect
                    for col in to_alter:
                        try:
                            if col == 'supported_modes':
                                if dialect == 'postgresql':
                                    sync_conn.execute(text('ALTER TABLE plugins ADD COLUMN supported_modes JSON'))
                                else:
                                    # SQLite and others: declare JSON (stored as TEXT) or generic
                                    sync_conn.execute(text('ALTER TABLE plugins ADD COLUMN supported_modes JSON'))
                            elif col == 'mode_switch_supported':
                                if dialect == 'postgresql':
                                    sync_conn.execute(text('ALTER TABLE plugins ADD COLUMN mode_switch_supported BOOLEAN DEFAULT false'))
                                else:
                                    sync_conn.execute(text('ALTER TABLE plugins ADD COLUMN mode_switch_supported BOOLEAN'))
                        except Exception:
                            # Best-effort: ignore failures and continue starting app
                            pass

                await conn.run_sync(_ensure_plugin_columns)
        except Exception as e:
            logger.error(f"❌ Failed to create database tables: {e}", exc_info=True)
            print(f"❌ Failed to create database tables: {e}")
            raise
    
        logger.info("✅ Database tables ready")
        print("✅ Database tables ready")
        
        # Load internal plugins
        logger.info("🔌 Loading plugins...")
        print("🔌 Loading plugins...")
        try:
            # Import event_bus with fallback
            try:
                from .event_bus import event_bus
            except ImportError:
                from core_service.event_bus import event_bus
            
            import asyncio

            # Make get_current_user available to plugins BEFORE loading them
            from .routes.auth import get_current_user
            app.state.get_current_user = get_current_user

            # Передаём async_sessionmaker (`AsyncSessionLocal`) в PluginLoader —
            # плагины ожидают объект session_maker (async_sessionmaker), а не
            # контекстный менеджер `get_session`.
            plugin_loader = PluginLoader(app, AsyncSessionLocal)
            await plugin_loader.load_all()

            # Save to app state for access from endpoints
            app.state.plugin_loader = plugin_loader
            app.state.event_bus = event_bus

            logger.info(f"✅ Loaded {len(plugin_loader.plugins)} internal plugins")

            # Initialize plugin managers
            try:
                from .plugin_mode_manager import init_plugin_mode_manager
                from .plugin_config import init_plugin_config_manager
                from .plugin_lifecycle_manager import init_plugin_lifecycle_manager
                from .plugin_security_manager import init_plugin_security_manager
                from .plugin_dependency_manager import init_plugin_dependency_manager

                plugin_mode_manager = init_plugin_mode_manager(plugin_loader)
                plugin_config_manager = init_plugin_config_manager()
                plugin_lifecycle_manager = init_plugin_lifecycle_manager()
                plugin_security_manager = init_plugin_security_manager()
                plugin_dependency_manager = init_plugin_dependency_manager()

                # Load all plugin configurations
                await plugin_config_manager.load_all_configs()

                # Save to app state
                app.state.plugin_mode_manager = plugin_mode_manager
                app.state.plugin_config_manager = plugin_config_manager
                app.state.plugin_lifecycle_manager = plugin_lifecycle_manager
                app.state.plugin_security_manager = plugin_security_manager
                app.state.plugin_dependency_manager = plugin_dependency_manager

                logger.info("✅ All plugin managers initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize plugin managers: {e}")
            
            # Force OpenAPI schema regeneration after all plugins are loaded
            # This ensures Swagger UI shows all plugin routes
            if hasattr(app, 'openapi_schema'):
                app.openapi_schema = None
                logger.debug("🔄 Cleared OpenAPI schema after plugin load")
            
            # Auto-register external plugins from ENV
            registered = register_external_plugins_from_env()
            logger.info(f"📦 Auto-registered external plugins from ENV: {registered}")
            
            # Initial health checks
            try:
                res = await external_plugin_registry.health_check_all()
                for pid, ok in res.items():
                    logger.info(f"{'✅' if ok else '❌'} {pid}: {'healthy' if ok else 'unhealthy'}")
            except Exception:
                pass
            
            # Start health monitor if enabled
            global _health_monitor
            if os.getenv('ENABLE_HEALTH_MONITOR', 'false').lower() == 'true':
                interval = int(os.getenv('HEALTH_CHECK_INTERVAL', '60'))
                _health_monitor = HealthMonitor(external_plugin_registry, check_interval=interval)
                await _health_monitor.start()
        except Exception as e:
            logger.error(f"❌ Failed to load internal plugins: {e}", exc_info=True)
            print(f"❌ Failed to load internal plugins: {e}")
            raise
        
        logger.info("✅ Application startup complete")
        print("✅ Application startup complete")
    except Exception as e:
        logger.error(f"❌ CRITICAL: Failed during application startup: {e}", exc_info=True)
        print(f"❌ CRITICAL: Failed during application startup: {e}")
        import traceback
        traceback.print_exc()
        raise  # Перебрасываем ошибку, чтобы приложение не запустилось в нерабочем состоянии
    
    yield
    
    logger.info("🛑 Application shutdown started")
    print("🛑 Application shutdown started")
    
    # Shutdown
    try:
        if _health_monitor is not None:
            await _health_monitor.stop()
    except Exception:
        pass
    try:
        # Cleanup plugin managers
        if hasattr(app.state, 'plugin_mode_manager'):
            await app.state.plugin_mode_manager.cleanup()
    except Exception:
        pass
    try:
        # Cleanup lifecycle manager
        if hasattr(app.state, 'plugin_lifecycle_manager'):
            await app.state.plugin_lifecycle_manager.cleanup()
    except Exception:
        pass
    try:
        # Cleanup dependency manager
        if hasattr(app.state, 'plugin_dependency_manager'):
            # No cleanup needed for dependency manager
            pass
    except Exception:
        pass
    try:
        await external_plugin_registry.aclose()
    except Exception:
        pass
    try:
        # Закрываем HTTP клиент
        from .utils.http_client import _close_http_client
        await _close_http_client()
    except Exception:
        pass
    try:
        # Закрываем async engine
        await engine.dispose()
    except Exception:
        pass


# ============= Application Factory =============

def create_admin_app() -> FastAPI:
    """
    Create and configure the Core Admin FastAPI application.
    
    This is the main application factory. It:
    - Sets up CORS
    - Configures SQLAdmin panel
    - Mounts routes (TODO: when routes are extracted)
    - Configures plugins
    
    Returns:
        Configured FastAPI application
    """
    logger.info("🏗️ Creating FastAPI application...")
    app = FastAPI(
        title="Core Admin Panel",
        version="2.0.0",
        description="Home Console Core Service - Refactored",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json"
    )
    logger.info("✅ FastAPI instance created")
    sys.stdout.flush()
    
    # ============= CORS Configuration =============
    origins_env = os.getenv("CORS_ALLOW_ORIGINS") or os.getenv("ALLOWED_ORIGINS") or "http://localhost:3000,http://localhost:80"
    if origins_env.strip() == "*":
        allow_origins = ["*"]
    else:
        allow_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
    
    allow_credentials = False if (len(allow_origins) == 1 and allow_origins[0] == "*") else True
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"]
    )
    
    # ============= Static Files (for production) =============
    # В production можно отдавать фронтенд из core-service
    # В dev фронтенд работает отдельно на порту 3000
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    if os.path.exists(static_dir) and os.listdir(static_dir):
        from fastapi.staticfiles import StaticFiles
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
    
    # ============= SQLAdmin Panel =============
    admin = Admin(app, engine)
    # Add views only if models are available (from client_manager plugin)
    if ClientAdmin is not None:
        admin.add_view(ClientAdmin)
    if CommandLogAdmin is not None:
        admin.add_view(CommandLogAdmin)
    if EnrollmentAdmin is not None:
        admin.add_view(EnrollmentAdmin)
    # Core model views
    if UserAdmin is not None:
        admin.add_view(UserAdmin)
    if DeviceAdmin is not None:
        admin.add_view(DeviceAdmin)
    if DeviceLinkAdmin is not None:
        admin.add_view(DeviceLinkAdmin)
    if PluginBindingAdmin is not None:
        admin.add_view(PluginBindingAdmin)
    if IntentMappingAdmin is not None:
        admin.add_view(IntentMappingAdmin)
    if PluginAdmin is not None:
        admin.add_view(PluginAdmin)
    if PluginVersionAdmin is not None:
        admin.add_view(PluginVersionAdmin)
    if PluginInstallJobAdmin is not None:
        admin.add_view(PluginInstallJobAdmin)
    # Plugin models
    if YandexAccountAdmin is not None:
        admin.add_view(YandexAccountAdmin)
    
    # ============= Basic Routes =============
    
    @app.get("/")
    async def root():
        """Root endpoint with basic info."""
        return {
            "service": "Core Admin Panel",
            "version": "2.0.0",
            "status": "running",
            "endpoints": {
                "admin_panel": "/admin",
                "api_docs": "/api/docs",
                "health": "/health"
            }
        }
    
    @app.get("/health")
    async def health():
        """Health check endpoint."""
        plugin_count = 0
        if hasattr(app.state, 'plugin_loader'):
            plugin_count = len(app.state.plugin_loader.plugins)
        
        return {
            "status": "healthy",
            "plugins_loaded": plugin_count,
            "external_plugins": len(external_plugin_registry.plugins)
        }
    
    @app.get("/api/health")
    async def api_health():
        """API health check endpoint."""
        plugin_count = 0
        if hasattr(app.state, 'plugin_loader'):
            plugin_count = len(app.state.plugin_loader.plugins)
        
        return {
            "status": "healthy",
            "plugins_loaded": plugin_count,
            "external_plugins": len(external_plugin_registry.plugins)
        }
    
    # ============= Mount Routers =============
    try:
        from .routes import devices, plugins, admin, auth

        # Mount core routes (only device management)
        app.include_router(admin.router, prefix="/api", tags=["admin"])
        app.include_router(devices.router, prefix="/api", tags=["devices"])
        app.include_router(plugins.router, prefix="/api", tags=["plugins"])
        app.include_router(auth.router, prefix="/api", tags=["auth"])

        # Client, files, and enrollments routes are now loaded as plugins
        # (client_manager plugin will mount them automatically)

        logger.info("✅ Core routes mounted successfully")
    except Exception as e:
        logger.error(f"❌ Failed to mount routes: {e}")
        raise
    
    logger.info("✅ FastAPI application created successfully")
    
    return app


# Create app instance at module level for Uvicorn
app = create_admin_app()


# ============= For direct execution =============
if __name__ == "__main__":
    import uvicorn
    app = create_admin_app()
    uvicorn.run(app, host="0.0.0.0", port=11000)
