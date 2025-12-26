"""Authentication models and managers for Yandex Smart Home."""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class YandexUser(Base):
    """Model for storing linked Yandex accounts."""
    __tablename__ = "yandex_users"
    
    id = Column(String(128), primary_key=True)
    user_id = Column(String(128), index=True, nullable=False, unique=True)
    ya_user_id = Column(String(128), nullable=True)
    access_token = Column(String(2048), nullable=False)
    refresh_token = Column(String(2048), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    config = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
