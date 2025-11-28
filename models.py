from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean
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


