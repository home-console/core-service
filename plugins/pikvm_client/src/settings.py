import os
import ssl
import logging
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator
from dotenv import load_dotenv

load_dotenv()

class PikvmSettings(BaseModel):
    """
    Configuration settings for PI-KVM connection and MongoDB
    """
    # Connection settings
    host: Optional[str] = Field(
        default=os.getenv('PIKVM_HOST'), 
        description="PI-KVM host address"
    )
    username: str = Field(
        default=os.getenv('PIKVM_USERNAME', 'admin'), 
        description="PI-KVM username"
    )
    password: str = Field(
        default=os.getenv('PIKVM_PASSWORD', 'admin'), 
        description="PI-KVM password"
    )
    secret: Optional[str] = Field(
        default=os.getenv('PIKVM_SECRET'), 
        description="Optional secret key"
    )

    # gRPC settings
    grpc_port: int = Field(
        default=int(os.getenv('GRPC_PORT', '50051')), 
        description="gRPC server port"
    )

    # MongoDB settings
    mongodb_uri: str = Field(
        default=os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'), 
        description="MongoDB connection URI"
    )
    mongodb_database: str = Field(
        default=os.getenv('MONGODB_DATABASE', 'pikvm_data'), 
        description="MongoDB database name"
    )
    mongodb_collection: str = Field(
        default=os.getenv('MONGODB_COLLECTION', 'websocket_events'), 
        description="MongoDB collection name"
    )

    # Logging settings
    debug: bool = Field(
        default=os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes'), 
        description="Enable debug logging"
    )

    # Pydantic configuration
    model_config = ConfigDict(
        env_prefix='PIKVM_',
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )

    # Computed properties
    @property
    def base_url(self) -> str:
        return f"https://{self.host}"

    @property
    def websocket_url(self) -> str:
        return f"wss://{self.host}/api/ws?stream=0"

    @property
    def log_level(self) -> int:
        return logging.DEBUG if self.debug else logging.INFO

    @property
    def ssl_options(self) -> dict:
        """
        SSL options to ignore certificate verification
        """
        return {
            "cert_reqs": ssl.CERT_NONE,
            "check_hostname": False
        }

    @model_validator(mode='after')
    def validate_settings(self):
        """
        Validate required settings during model initialization.
        Валидация выполняется только если все обязательные поля заданы.
        Это позволяет плагину загрузиться даже без настроек (для последующей настройки через UI).
        """
        # Валидация выполняется только если host задан (значит пользователь начал настройку)
        # Если host не задан, просто пропускаем валидацию - плагин загрузится, но не будет работать
        if self.host:
            if not self.username:
                raise ValueError("PIKVM_USERNAME must be set")
            if not self.password:
                raise ValueError("PIKVM_PASSWORD must be set")
            if not self.mongodb_uri:
                raise ValueError("MONGODB_URI must be set")
        
        return self

    def validate(self):
        """
        Custom validate method for backwards compatibility
        """
        self.validate_settings()
        return self

    def configure_logging(self):
        """
        Configure logging based on debug setting
        """
        logging.basicConfig(
            level=self.log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        return self.log_level

# Глобальный экземпляр settings больше не создается при импорте
# Он должен создаваться в плагине через _create_settings() после загрузки конфигурации
