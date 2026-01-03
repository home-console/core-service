"""
Константы для всего приложения.
Централизованное хранение всех магических чисел и строк.
"""

# ============= Device Limits =============
MAX_DEVICE_LINK_DEPTH = 5  # Максимальная глубина связей между устройствами
DEFAULT_DEVICE_CACHE_TTL = 30  # TTL кэша для списка устройств (секунды)

# ============= Plugin Limits =============
PLUGIN_DEBOUNCE_MS = 100  # Время debounce для событий плагинов (миллисекунды)
PLUGIN_BATCH_SIZE = 10  # Размер батча для обработки событий плагинов
PLUGIN_INSTALL_TIMEOUT = 300  # Таймаут установки плагина (секунды)
PLUGIN_LOAD_TIMEOUT = 60  # Таймаут загрузки плагина (секунды)

# ============= HTTP Client Limits =============
HTTP_MAX_CONNECTIONS = 100  # Максимум одновременных HTTP соединений
HTTP_MAX_KEEPALIVE = 20  # Максимум keep-alive соединений
HTTP_KEEPALIVE_EXPIRY = 30.0  # Время жизни keep-alive соединения (секунды)
HTTP_DEFAULT_TIMEOUT = 30.0  # Таймаут HTTP запросов по умолчанию (секунды)
HTTP_CONNECT_TIMEOUT = 10.0  # Таймаут установки соединения (секунды)

# ============= Cache TTLs =============
CACHE_DEVICES_TTL = 30  # TTL кэша для устройств (секунды)
CACHE_PLUGINS_TTL = 60  # TTL кэша для плагинов (секунды)
CACHE_USER_TTL = 300  # TTL кэша для пользователей (секунды)
CACHE_DEFAULT_TTL = 300  # TTL кэша по умолчанию (секунды)

# ============= EventBus =============
EVENT_BUS_DEBOUNCE_MS = 100  # Время debounce для EventBus (миллисекунды)
EVENT_BUS_BATCH_SIZE = 10  # Размер батча для EventBus
EVENT_BUS_MAX_LOG_SIZE = 1000  # Максимальный размер лога событий

# ============= Database =============
DB_POOL_SIZE = 20  # Размер пула соединений БД
DB_MAX_OVERFLOW = 10  # Максимум дополнительных соединений при перегрузке
DB_POOL_RECYCLE = 3600  # Время переиспользования соединений (секунды)
DB_POOL_PRE_PING = True  # Проверка соединений перед использованием

# ============= Yandex Sync =============
YANDEX_SYNC_CONCURRENCY = 20  # Параллелизм при синхронизации устройств Яндекса
YANDEX_SYNC_DELAY_BETWEEN = 0.01  # Задержка между запросами (секунды)

# ============= Device Actions =============
DEVICE_ACTION_ON = "on"
DEVICE_ACTION_OFF = "off"
DEVICE_ACTION_TOGGLE = "toggle"
DEVICE_ACTION_SET = "set"
DEVICE_ACTION_EXECUTE = "execute"

ALLOWED_DEVICE_ACTIONS = [
    DEVICE_ACTION_ON,
    DEVICE_ACTION_OFF,
    DEVICE_ACTION_TOGGLE,
    DEVICE_ACTION_SET,
    DEVICE_ACTION_EXECUTE,
]

# ============= Plugin Types =============
PLUGIN_TYPE_INTERNAL = "internal"
PLUGIN_TYPE_EXTERNAL = "external"
PLUGIN_TYPE_INFRASTRUCTURE = "infrastructure"

# ============= Plugin Runtime Modes =============
PLUGIN_MODE_IN_PROCESS = "in_process"
PLUGIN_MODE_MICROSERVICE = "microservice"
PLUGIN_MODE_HYBRID = "hybrid"
PLUGIN_MODE_EMBEDDED = "embedded"

ALLOWED_PLUGIN_MODES = [
    PLUGIN_MODE_IN_PROCESS,
    PLUGIN_MODE_MICROSERVICE,
    PLUGIN_MODE_HYBRID,
    PLUGIN_MODE_EMBEDDED,
]

# ============= Plugin Install Types =============
PLUGIN_INSTALL_TYPE_URL = "url"
PLUGIN_INSTALL_TYPE_GIT = "git"
PLUGIN_INSTALL_TYPE_LOCAL = "local"

ALLOWED_PLUGIN_INSTALL_TYPES = [
    PLUGIN_INSTALL_TYPE_URL,
    PLUGIN_INSTALL_TYPE_GIT,
    PLUGIN_INSTALL_TYPE_LOCAL,
]

# ============= Device Link Types =============
DEVICE_LINK_TYPE_BRIDGE = "bridge"
DEVICE_LINK_TYPE_PROXY = "proxy"
DEVICE_LINK_TYPE_SYNC = "sync"
DEVICE_LINK_TYPE_MIRROR = "mirror"

ALLOWED_DEVICE_LINK_TYPES = [
    DEVICE_LINK_TYPE_BRIDGE,
    DEVICE_LINK_TYPE_PROXY,
    DEVICE_LINK_TYPE_SYNC,
    DEVICE_LINK_TYPE_MIRROR,
]

# ============= Device Link Directions =============
DEVICE_LINK_DIRECTION_BIDIRECTIONAL = "bidirectional"
DEVICE_LINK_DIRECTION_UNIDIRECTIONAL = "unidirectional"

ALLOWED_DEVICE_LINK_DIRECTIONS = [
    DEVICE_LINK_DIRECTION_BIDIRECTIONAL,
    DEVICE_LINK_DIRECTION_UNIDIRECTIONAL,
]

# ============= User Roles =============
USER_ROLE_USER = "user"
USER_ROLE_ADMIN = "admin"

ALLOWED_USER_ROLES = [
    USER_ROLE_USER,
    USER_ROLE_ADMIN,
]

# ============= Plugin Install Job Status =============
PLUGIN_JOB_STATUS_PENDING = "pending"
PLUGIN_JOB_STATUS_SENT = "sent"
PLUGIN_JOB_STATUS_RUNNING = "running"
PLUGIN_JOB_STATUS_SUCCESS = "success"
PLUGIN_JOB_STATUS_FAILED = "failed"

ALLOWED_PLUGIN_JOB_STATUSES = [
    PLUGIN_JOB_STATUS_PENDING,
    PLUGIN_JOB_STATUS_SENT,
    PLUGIN_JOB_STATUS_RUNNING,
    PLUGIN_JOB_STATUS_SUCCESS,
    PLUGIN_JOB_STATUS_FAILED,
]




