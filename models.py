from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean
from sqlalchemy import JSON

# Импортируем Base из db.py для совместимости с async engine
from .db import Base


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
    is_online = Column(Boolean, default=False, nullable=False)  # Устройство онлайн?
    is_on = Column(Boolean, default=False, nullable=False)  # Устройство включено?
    last_seen = Column(DateTime, nullable=True)  # Последнее время онлайна
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PluginBinding(Base):
    __tablename__ = "plugin_bindings"
    id = Column(String(128), primary_key=True)
    device_id = Column(String(128), index=True, nullable=False)
    plugin_name = Column(String(128), nullable=False)
    selector = Column(String(255), nullable=True)  # Внешний идентификатор устройства (например, yandex_device_id)
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


class DeviceLink(Base):
    """
    Связь между двумя устройствами в системе.
    Позволяет связать устройство из одного источника (например, Яндекс) 
    с устройством из другого источника (например, локальное устройство).
    
    Пример: Яндекс-лампа -> Локальное реле
    При команде на Яндекс-устройство, команда перенаправляется на связанное устройство.
    """
    __tablename__ = "device_links"
    id = Column(String(128), primary_key=True)
    source_device_id = Column(String(128), index=True, nullable=False)  # Устройство-источник (например, из Яндекса)
    target_device_id = Column(String(128), index=True, nullable=False)  # Устройство-цель (например, локальное)
    link_type = Column(String(64), nullable=True)  # Тип связи: 'bridge', 'proxy', 'sync', 'mirror'
    direction = Column(String(32), default='bidirectional', nullable=False)  # 'unidirectional' или 'bidirectional'
    enabled = Column(Boolean, default=True, nullable=False)
    config = Column(JSON, nullable=True)  # Дополнительная конфигурация связи
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


class User(Base):
    __tablename__ = "users"
    id = Column(String(128), primary_key=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(128), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="user", nullable=False)  # user, admin, etc.
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)
    last_activity = Column(DateTime, nullable=True)
    # SQLAlchemy reserved attribute name "metadata" -> use column name but safe attribute
    meta = Column("metadata", JSON, nullable=True)


