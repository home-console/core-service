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
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqladmin import Admin, ModelView

# Relative imports
try:
    from .db import engine, get_session
    from .models import Base, Client, CommandLog, Enrollment
    from .plugin_loader import PluginLoader
    from .plugin_registry import external_plugin_registry
    from .health_monitor import HealthMonitor
except ImportError:
    from db import engine, get_session
    from models import Base, Client, CommandLog, Enrollment
    from plugin_loader import PluginLoader
    from plugin_registry import external_plugin_registry
    from health_monitor import HealthMonitor

logger = logging.getLogger(__name__)

# Global health monitor instance
_health_monitor = None


# ============= SQLAdmin Model Views =============

class ClientAdmin(ModelView, model=Client):
    column_list = [Client.id, Client.hostname, Client.ip, Client.port, Client.status, Client.last_heartbeat]
    name_plural = "Clients"


class CommandLogAdmin(ModelView, model=CommandLog):
    column_list = [CommandLog.id, CommandLog.client_id, CommandLog.command, CommandLog.status, CommandLog.exit_code, CommandLog.created_at]
    name_plural = "Command Logs"


class EnrollmentAdmin(ModelView, model=Enrollment):
    column_list = [Enrollment.id, Enrollment.status, Enrollment.created_at]
    name_plural = "Enrollments"


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
    Base.metadata.create_all(bind=engine)
    
    # Load internal plugins
    try:
        from event_bus import event_bus
        import asyncio
        
        plugin_loader = PluginLoader(app, get_session)
        await plugin_loader.load_all()
        
        # Save to app state for access from endpoints
        app.state.plugin_loader = plugin_loader
        app.state.event_bus = event_bus
        
        logger.info(f"✅ Loaded {len(plugin_loader.plugins)} internal plugins")
        
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
        logger.warning(f"⚠️ Failed to load internal plugins: {e}")
    
    yield
    
    # Shutdown
    try:
        if _health_monitor is not None:
            await _health_monitor.stop()
    except Exception:
        pass
    try:
        await external_plugin_registry.aclose()
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
    app = FastAPI(
        title="Core Admin Panel",
        version="2.0.0",
        description="Home Console Core Service - Refactored",
        lifespan=lifespan
    )
    
    # ============= CORS Configuration =============
    origins_env = os.getenv("CORS_ALLOW_ORIGINS") or os.getenv("ALLOWED_ORIGINS") or "http://localhost:3000"
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
    
    # ============= SQLAdmin Panel =============
    admin = Admin(app, engine)
    admin.add_view(ClientAdmin)
    admin.add_view(CommandLogAdmin)
    admin.add_view(EnrollmentAdmin)
    
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
                "api_docs": "/docs",
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
    
    # ============= TODO: Mount Routers =============
    # Once we extract routes to separate files:
    # from .routes import clients, plugins, files, enrollments
    # app.include_router(clients.router, prefix="/api")
    # app.include_router(plugins.router, prefix="/api")
    # app.include_router(files.router, prefix="/api")
    # app.include_router(enrollments.router, prefix="/api")
    
    # ============= TEMPORARY: Keep old routes =============
    # Import all the old endpoint functions from admin_app
    # This is a temporary bridge until routes are fully extracted
    try:
        from . import admin_app
        # Copy over all the route handlers
        # (This is hacky but maintains compatibility during transition)
    except Exception as e:
        logger.warning(f"Could not import old admin_app routes: {e}")
    
    return app


# ============= For direct execution =============
if __name__ == "__main__":
    import uvicorn
    app = create_admin_app()
    uvicorn.run(app, host="0.0.0.0", port=11000)
