import os
import ssl
import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, model_validator
from dotenv import load_dotenv

load_dotenv()

class PikvmDeviceConfig(BaseModel):
    """
    Конфигурация одного устройства PiKVM
    """
    device_id: str = Field(description="Уникальный идентификатор устройства")
    host: str = Field(description="PI-KVM host address")
    username: str = Field(default='admin', description="PI-KVM username")
    password: str = Field(description="PI-KVM password")
    secret: Optional[str] = Field(default=None, description="Optional TOTP secret key")
    enabled: bool = Field(default=True, description="Включено ли устройство")

class PikvmSettings(BaseModel):
    """
    Configuration settings for PI-KVM connection
    """
    # Connection settings (для обратной совместимости)
    host: Optional[str] = Field(
        default=os.getenv('PIKVM_HOST'), 
        description="PI-KVM host address (deprecated, use devices)"
    )
    username: str = Field(
        default=os.getenv('PIKVM_USERNAME', 'admin'), 
        description="PI-KVM username (deprecated, use devices)"
    )
    password: str = Field(
        default=os.getenv('PIKVM_PASSWORD', 'admin'), 
        description="PI-KVM password (deprecated, use devices)"
    )
    secret: Optional[str] = Field(
        default=os.getenv('PIKVM_SECRET'), 
        description="Optional secret key (deprecated, use devices)"
    )
    
    # Новые настройки для множественных устройств
    devices: List[PikvmDeviceConfig] = Field(
        default_factory=list,
        description="Список устройств PiKVM"
    )

    # gRPC settings
    grpc_port: int = Field(
        default=int(os.getenv('GRPC_PORT', '50051')), 
        description="gRPC server port"
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
        # Если есть устройства в списке, валидируем их
        if self.devices:
            device_ids = [d.device_id for d in self.devices]
            if len(device_ids) != len(set(device_ids)):
                raise ValueError("Device IDs must be unique")
            for device in self.devices:
                if not device.host:
                    raise ValueError(f"Host must be set for device {device.device_id}")
                if not device.password:
                    raise ValueError(f"Password must be set for device {device.device_id}")
        # Для обратной совместимости: валидация старого формата
        elif self.host:
            if not self.username:
                raise ValueError("PIKVM_USERNAME must be set")
            if not self.password:
                raise ValueError("PIKVM_PASSWORD must be set")
        
        return self
    
    def get_device_config(self, device_id: Optional[str] = None) -> Optional[PikvmDeviceConfig]:
        """
        Получить конфигурацию устройства по device_id.
        Если device_id не указан и есть только одно устройство, вернуть его.
        Если device_id не указан и используется старый формат (host), создать временную конфигурацию.
        """
        if self.devices:
            if device_id:
                for device in self.devices:
                    if device.device_id == device_id and device.enabled:
                        return device
                return None
            elif len(self.devices) == 1:
                return self.devices[0] if self.devices[0].enabled else None
            else:
                return None
        # Обратная совместимость: если используется старый формат
        elif self.host:
            return PikvmDeviceConfig(
                device_id=device_id or "default",
                host=self.host,
                username=self.username,
                password=self.password,
                secret=self.secret,
                enabled=True
            )
        return None
    
    def get_all_devices(self) -> List[PikvmDeviceConfig]:
        """Получить список всех включенных устройств"""
        if self.devices:
            return [d for d in self.devices if d.enabled]
        elif self.host:
            return [PikvmDeviceConfig(
                device_id="default",
                host=self.host,
                username=self.username,
                password=self.password,
                secret=self.secret,
                enabled=True
            )]
        return []

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
