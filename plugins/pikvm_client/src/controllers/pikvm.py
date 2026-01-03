import logging
import json
import ssl
import requests
import pyotp
import websocket
import urllib3

from settings import PikvmSettings, PikvmDeviceConfig
from typing import Union

# Suppress only the specific InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class PikvmController:
    """
    Controller for interacting with PI-KVM API via HTTP and WebSocket
    """
    def __init__(self, config: Union[PikvmSettings, PikvmDeviceConfig], device_id: str = None):
        """
        Initialize PikvmController with connection settings
        
        :param config: PikvmSettings или PikvmDeviceConfig instance (required)
        :param device_id: Идентификатор устройства (для логирования)
        """
        if config is None:
            raise ValueError("Configuration instance is required")
        
        # Сохраняем исходную конфигурацию
        self.config = config
        self.device_id = device_id or getattr(config, 'device_id', 'default')
        
        # Извлекаем параметры подключения
        if isinstance(config, PikvmDeviceConfig):
            self.host = config.host
            self.username = config.username
            self.password = config.password
            self.secret = config.secret
        elif isinstance(config, PikvmSettings):
            # Обратная совместимость
            self.host = config.host
            self.username = config.username
            self.password = config.password
            self.secret = config.secret
            # Validate settings для старого формата
            if self.host:
                config.validate()
        else:
            raise ValueError("Config must be PikvmSettings or PikvmDeviceConfig")
        
        if not self.host:
            raise ValueError("Host is required")
        
        # Создаем объект settings для совместимости с существующим кодом
        self.settings = type('Settings', (), {
            'host': self.host,
            'username': self.username,
            'password': self.password,
            'secret': self.secret,
            'base_url': f"https://{self.host}",
            'websocket_url': f"wss://{self.host}/api/ws?stream=0",
            'ssl_options': {
                "cert_reqs": ssl.CERT_NONE,
                "check_hostname": False
            }
        })()
        
        # Prepare authentication headers
        self.headers = self._prepare_headers()

    def _prepare_headers(self):
        """
        Prepare authentication headers
        
        :return: Dictionary of authentication headers
        """
        # If TOTP secret is provided, combine password with current TOTP
        if self.secret:
            totp_password = self.password + pyotp.TOTP(self.secret).now()
            return {
                "X-KVMD-User": self.username,
                "X-KVMD-Passwd": totp_password,
            }
        
        # Standard authentication
        return {
            "X-KVMD-User": self.username,
            "X-KVMD-Passwd": self.password,
        }

    def test_http_connect(self):
        """
        Test HTTP connection to PI-KVM API
        
        :return: HTTP status code
        :raises: requests.RequestException on connection error
        """
        try:
            # Create a session to configure request-level settings
            session = requests.Session()
            
            # Disable SSL warnings for this session
            session.verify = False

            response = session.get(
                url=f"{self.settings.base_url}/api/info",
                headers=self.headers,
                timeout=10
            )
            logging.info(f"HTTP Status Code: {response.status_code}")
            return response.status_code
        except requests.RequestException as e:
            logging.error(f"HTTP Connection Error: {e}")
            raise

    def test_websocket_connect(self):
        """
        Test WebSocket connection to PI-KVM
        
        :return: WebSocket response message
        :raises: Exception on connection error
        """
        try:
            # SSL options to ignore certificate verification
            ssl_opt = {
                "cert_reqs": ssl.CERT_NONE,
                "check_hostname": False
            }
            
            # Create WebSocket connection
            ws = websocket.WebSocket(sslopt=ssl_opt)
            ws.connect(
                self.settings.websocket_url, 
                header=self.headers
            )
            
            # Send a test message
            test_message = json.dumps({"action": "get_status"})
            ws.send(test_message)
            
            # Receive response
            response = ws.recv()
            logging.info(f"WebSocket Response: {response}")
            
            # Close the connection
            ws.close()
            
            return response
        except Exception as e:
            logging.error(f"WebSocket connection error: {e}")
            raise

    def get_system_info(self, fields=None):
        """
        Get system information from PiKVM
        
        :param fields: Optional fields to retrieve
        :return: System information dictionary
        """
        params = {'fields': fields} if fields else {}
        response = self._make_request('get', '/api/info', params=params)
        return response.json()

    def get_system_log(self, follow=False, seek=None):
        """
        Retrieve system logs
        
        :param follow: Enable real-time log following
        :param seek: Number of seconds to retrieve logs for
        :return: System log content
        """
        params = {}
        if follow:
            params['follow'] = 1
        if seek:
            params['seek'] = seek
        
        response = self._make_request('get', '/api/log', params=params)
        return response.text

    def get_atx_state(self):
        """
        Get current ATX power state
        
        :return: ATX state dictionary
        """
        response = self._make_request('get', '/api/atx')
        return response.json()

    def power_control(self, action='on', wait=False):
        """
        Control PC power
        
        :param action: Power action (on, off, off_hard, reset_hard)
        :param wait: Wait for operation to complete
        :return: API response
        """
        params = {
            'action': action,
            'wait': 1 if wait else 0
        }
        response = self._make_request('post', '/api/atx/power', params=params)
        return response.json()

    def power_button_click(self, button='power', wait=False):
        """
        Simulate PC case button press
        
        :param button: Button type (power, power_long, reset)
        :param wait: Wait for operation to complete
        :return: API response
        """
        params = {
            'button': button,
            'wait': 1 if wait else 0
        }
        response = self._make_request('post', '/api/atx/click', params=params)
        return response.json()

    def get_msd_state(self):
        """
        Get Mass Storage Drive state
        
        :return: MSD state dictionary
        """
        response = self._make_request('get', '/api/msd')
        return response.json()

    def upload_msd_image(self, image_path, image_name=None):
        """
        Upload an image to Mass Storage Drive
        
        :param image_path: Path to the image file
        :param image_name: Optional custom image name
        :return: Upload response
        """
        with open(image_path, 'rb') as f:
            params = {'image': image_name or image_path.split('/')[-1]}
            response = self._make_request(
                'post', 
                '/api/msd/write', 
                params=params, 
                data=f,
                headers={'Content-Type': 'application/octet-stream'}
            )
        return response.json()

    def upload_msd_remote_image(self, url, image_name=None, timeout=10):
        """
        Download and upload an image from a remote URL
        
        :param url: URL of the image
        :param image_name: Optional custom image name
        :param timeout: Download timeout
        :return: Upload response
        """
        params = {
            'url': url,
            'image': image_name,
            'timeout': timeout
        }
        response = self._make_request('post', '/api/msd/write_remote', params=params)
        return response.json()

    def get_gpio_state(self):
        """
        Get GPIO state
        
        :return: GPIO state dictionary
        """
        response = self._make_request('get', '/api/gpio')
        return response.json()

    def switch_gpio(self, channel, state, wait=False):
        """
        Switch GPIO channel
        
        :param channel: GPIO channel
        :param state: 0 or 1
        :param wait: Wait for operation
        :return: Switch response
        """
        params = {
            'channel': channel,
            'state': state,
            'wait': 1 if wait else 0
        }
        response = self._make_request('post', '/api/gpio/switch', params=params)
        return response.json()

    def pulse_gpio(self, channel, delay=None, wait=False):
        """
        Pulse GPIO channel
        
        :param channel: GPIO channel
        :param delay: Pulse duration
        :param wait: Wait for operation
        :return: Pulse response
        """
        params = {
            'channel': channel,
            'wait': 1 if wait else 0
        }
        if delay is not None:
            params['delay'] = delay
        
        response = self._make_request('post', '/api/gpio/pulse', params=params)
        return response.json()

    def get_prometheus_metrics(self):
        """
        Get Prometheus metrics
        
        :return: Prometheus metrics text
        """
        response = self._make_request('get', '/api/export/prometheus/metrics')
        return response.text

    def _make_request(self, method, endpoint, **kwargs):
        """
        Make a generic request to PiKVM API
        
        :param method: HTTP method (get, post)
        :param endpoint: API endpoint
        :param kwargs: Additional request parameters
        :return: Response from the API
        """
        try:
            # Create a session to configure request-level settings
            session = requests.Session()
            
            # Disable SSL warnings and verification
            session.verify = False
            
            # Construct full URL
            url = f"{self.settings.base_url}{endpoint}"
            
            # Merge headers
            headers = {**self.headers, **kwargs.pop('headers', {})}
            
            # Make the request
            response = session.request(
                method, 
                url, 
                headers=headers, 
                timeout=kwargs.pop('timeout', 10),
                **kwargs
            )
            
            # Raise an exception for HTTP errors
            response.raise_for_status()
            
            return response
        except requests.RequestException as e:
            logging.error(f"PiKVM API Request Error: {e}")
            raise

class PikvmControllerGrpc:
    """
    Controller for interacting with PI-KVM API via gRPC
    """
    def __init__(self):
        """
        Initialize PIKVM controller with settings
        """
        self.host = settings.pikvm_host
        self.username = settings.pikvm_username
        self.password = settings.pikvm_password
        self.base_url = f"https://{self.host}"
        
        # Configure logging
        self.logger = logging.getLogger(__name__)

    def _make_request(self, method, endpoint, **kwargs):
        """
        Make a request to the PIKVM API
        
        :param method: HTTP method (get, post)
        :param endpoint: API endpoint
        :param kwargs: Additional request arguments
        :return: Response JSON
        """
        try:
            url = f"{self.base_url}{endpoint}"
            auth = (self.username, self.password)
            
            # Verify SSL is set to False due to self-signed certificates
            kwargs['verify'] = False
            
            # Add authentication
            kwargs['auth'] = auth
            
            # Make request
            response = requests.request(method, url, **kwargs)
            
            # Raise exception for bad responses
            response.raise_for_status()
            
            return response.json()
        except requests.RequestException as e:
            self.logger.error(f"API Request Error: {e}")
            raise

    def power_control(self, action='off', wait=True):
        """
        Control power state of the device
        
        :param action: Power action (on, off, off_hard, reset_hard)
        :param wait: Wait for operation to complete
        :return: API response
        """
        endpoint = "/api/power"
        
        # Map actions to API parameters
        power_actions = {
            'on': 'on',
            'off': 'off',
            'off_hard': 'off_hard',
            'reset_hard': 'reset_hard'
        }
        
        params = {
            'action': power_actions.get(action, 'off'),
            'wait': str(wait).lower()
        }
        
        return self._make_request('get', endpoint, params=params)

    def power_button_click(self, button='power', wait=True):
        """
        Simulate power button click
        
        :param button: Button type (power, power_long, reset)
        :param wait: Wait for operation to complete
        :return: API response
        """
        endpoint = "/api/power"
        
        # Map buttons to API parameters
        button_types = {
            'power': 'power',
            'power_long': 'power_long',
            'reset': 'reset'
        }
        
        params = {
            'button': button_types.get(button, 'power'),
            'wait': str(wait).lower()
        }
        
        return self._make_request('get', endpoint, params=params)

    def upload_msd_image(self, image_path, image_name):
        """
        Upload Mass Storage Device (MSD) image
        
        :param image_path: Path to the image file
        :param image_name: Name of the image
        :return: API response
        """
        endpoint = "/api/msd/upload"
        
        with open(image_path, 'rb') as image_file:
            files = {'image': (image_name, image_file)}
            
            return self._make_request('post', endpoint, files=files)

    def switch_gpio(self, channel, state, wait=True):
        """
        Switch GPIO state
        
        :param channel: GPIO channel
        :param state: GPIO state (0 or 1)
        :param wait: Wait for operation to complete
        :return: API response
        """
        endpoint = "/api/gpio/switch"
        
        params = {
            'channel': channel,
            'state': int(state),
            'wait': str(wait).lower()
        }
        
        return self._make_request('get', endpoint, params=params)

    def pulse_gpio(self, channel, delay=1, wait=True):
        """
        Pulse GPIO
        
        :param channel: GPIO channel
        :param delay: Pulse duration in seconds
        :param wait: Wait for operation to complete
        :return: API response
        """
        endpoint = "/api/gpio/pulse"
        
        params = {
            'channel': channel,
            'delay': float(delay),
            'wait': str(wait).lower()
        }
        
        return self._make_request('get', endpoint, params=params)