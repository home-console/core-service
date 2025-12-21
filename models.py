from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean
from sqlalchemy import JSON
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class Client(Base):
    __tablename__ = "clients"
    id = Column(String(128), primary_key=True)
    hostname = Column(String(255), nullable=True)
    ip = Column(String(64), nullable=True)
    port = Column(Integer, nullable=True)
    status = Column(String(32), nullable=True)
    connected_at = Column(DateTime, nullable=True)
    last_heartbeat = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class CommandLog(Base):
    __tablename__ = "command_logs"
    id = Column(String(128), primary_key=True)  # command_id
    client_id = Column(String(128), index=True, nullable=False)
    command = Column(Text, nullable=False)
    status = Column(String(32), nullable=True)  # queued, running, success, error, cancelled, timeout
    stdout = Column(Text, nullable=True)
    stderr = Column(Text, nullable=True)
    exit_code = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)


class Enrollment(Base):
    __tablename__ = "enrollments"
    id = Column(String(128), primary_key=True)  # client_id
    status = Column(String(32), nullable=False, default="pending")  # pending/approved/rejected
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class TerminalAudit(Base):
    __tablename__ = "terminal_audit"
    id = Column(String(128), primary_key=True)
    session_id = Column(String(128), index=True, nullable=False)
    client_id = Column(String(128), index=True, nullable=True)
    initiator_type = Column(String(32), nullable=True)
    initiator_id = Column(String(128), nullable=True)
    record_path = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)
    exit_code = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


