from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean
from sqlalchemy import JSON

# Импортируем Base из db.py для совместимости с async engine
try:
    from .db import Base
except ImportError:
    from db import Base


# ============= CORE MODELS - Only Device Management =============
# Models for client management (Client, CommandLog, Enrollment, TerminalAudit)
# are now in plugins/client_manager/models.py


class Device(Base):
    __tablename__ = "devices"
    id = Column(String(128), primary_key=True)
    name = Column(String(255), nullable=False)
    type = Column(String(64), nullable=True)
    # `metadata` is reserved by SQLAlchemy Declarative API, use attribute name `meta`
    # but keep the DB column name as `metadata` for compatibility.
    meta = Column('metadata', JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PluginBinding(Base):
    __tablename__ = "plugin_bindings"
    id = Column(String(128), primary_key=True)
    device_id = Column(String(128), index=True, nullable=False)
    plugin_name = Column(String(128), nullable=False)
    config = Column(JSON, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class IntentMapping(Base):
    __tablename__ = "intent_mappings"
    id = Column(String(128), primary_key=True)
    intent_name = Column(String(128), index=True, nullable=False)
    selector = Column(String(255), nullable=True)  # simple selector like alias=name
    plugin_action = Column(String(255), nullable=False)  # canonical action e.g. plugin.action
    payload_template = Column(Text, nullable=True)  # JSON template or jinja
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Plugin(Base):
    __tablename__ = "plugins"
    id = Column(String(128), primary_key=True)
    name = Column(String(128), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    publisher = Column(String(128), nullable=True)
    latest_version = Column(String(64), nullable=True)
    # enabled — разрешен ли к автозагрузке (persisted)
    enabled = Column(Boolean, nullable=False, default=True)
    # loaded — факт загрузки в рантайме (обновляется при load/unload)
    loaded = Column(Boolean, default=False, nullable=False)
    # runtime_mode маппится на plugin_type в SDK: "in_process" | "microservice" | "hybrid"
    runtime_mode = Column(String(32), nullable=True)
    # supported_modes — список поддерживаемых режимов (например ["in_process", "microservice"])
    supported_modes = Column(JSON, nullable=True)
    # mode_switch_supported — можно ли переключать режим на лету
    mode_switch_supported = Column(Boolean, default=False, nullable=True)
    # произвольная конфигурация плагина (опционально)
    config = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PluginVersion(Base):
    __tablename__ = "plugin_versions"
    id = Column(String(128), primary_key=True)
    plugin_name = Column(String(128), index=True, nullable=False)
    version = Column(String(64), nullable=False)
    manifest = Column(JSON, nullable=True)
    type = Column(String(64), nullable=True)
    artifact_url = Column(String(1024), nullable=True)
    signature = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PluginInstallJob(Base):
    __tablename__ = "plugin_install_jobs"
    id = Column(String(128), primary_key=True)
    plugin_name = Column(String(128), index=True, nullable=False)
    version = Column(String(64), nullable=False)
    target_agent = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="pending")  # pending, sent, running, success, failed
    logs = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


