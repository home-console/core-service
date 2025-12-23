"""
Auth Service Integration - интеграция с системой авторизации.
Обеспечивает OAuth интеграцию с Яндексом и безопасный обмен токенами.
"""
import asyncio
import logging
import os
import http.client
import json
from typing import Dict, Any, Optional
from urllib.parse import urljoin, urlencode

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from home_console_sdk.plugin import InternalPluginBase

# Импорты для работы с внутренними устройствами
try:
    from ...db import get_session
    from ...models import Device, PluginBinding, IntentMapping
    from sqlalchemy import select
except ImportError:
    from db import get_session
    from models import Device, PluginBinding, IntentMapping
    from sqlalchemy import select

logger = logging.getLogger(__name__)

# Конфигурация сервиса авторизации
AUTH_SERVICE_BASE = os.getenv('AUTH_SERVICE_BASE', 'http://auth-service:8000')
INTERNAL_TOKEN = os.getenv('INTERNAL_SERVICE_TOKEN', 'internal-service-token')


class AuthServiceClient:
    """Клиент для взаимодействия с сервисом авторизации."""
    
    @staticmethod
    def call_auth_service(endpoint: str, method: str = 'GET', data: Dict[str, Any] = None, 
                         headers: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Вызвать метод сервиса авторизации.
        
        Args:
            endpoint: API endpoint (например, /api/tokens/cloud/yandex)
            method: HTTP метод
            data: Данные для POST/PUT запросов
            headers: Дополнительные заголовки
        
        Returns:
            Ответ от сервиса авторизации
        """
        url = urljoin(AUTH_SERVICE_BASE, endpoint)
        parsed = http.client.urlsplit(url)
        
        conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
        conn = conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)
        
        try:
            req_headers = {"Authorization": f"Bearer {INTERNAL_TOKEN}"}
            if headers:
                req_headers.update(headers)
            
            if data:
                req_headers["Content-Type"] = "application/json"
                body = json.dumps(data).encode('utf-8')
            else:
                body = None
            
            conn.request(method.upper(), parsed.path, body=body, headers=req_headers)
            resp = conn.getresponse()
            response_data = resp.read()
            text = response_data.decode('utf-8') if response_data else ''
            
            if not (200 <= resp.status < 300):
                raise HTTPException(
                    status_code=resp.status, 
                    detail=f'Auth service error: {resp.status} {text}'
                )
            
            return json.loads(text) if text else {}
            
        finally:
            try:
                conn.close()
            except:
                pass


class YandexAuthManager:
    """Менеджер авторизации Яндекса."""

    @staticmethod
    def get_yandex_oauth_url(state: str = None) -> str:
        """
        Получить URL для OAuth авторизации с Яндексом.

        Args:
            state: Состояние для защиты от CSRF

        Returns:
            URL для перенаправления пользователя
        """
        client_id = os.getenv('YANDEX_CLIENT_ID')
        redirect_uri = os.getenv('YANDEX_REDIRECT_URI')
        scope = os.getenv('YANDEX_OAUTH_SCOPE', 'smart_home')

        if not client_id or not redirect_uri:
            raise HTTPException(
                status_code=500,
                detail='YANDEX_CLIENT_ID and YANDEX_REDIRECT_URI must be set'
            )

        params = {
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'scope': scope,
        }
        if state:
            params['state'] = state

        authorize_url = os.getenv('YANDEX_OAUTH_AUTHORIZE', 'https://oauth.yandex.ru/authorize')
        return authorize_url + '?' + urlencode(params)

    @staticmethod
    async def exchange_code_for_token(code: str) -> Dict[str, Any]:
        """
        Обменять код авторизации на токен.

        Args:
            code: Код авторизации от Яндекса

        Returns:
            Информация о токене
        """
        client_id = os.getenv('YANDEX_CLIENT_ID')
        client_secret = os.getenv('YANDEX_CLIENT_SECRET')
        redirect_uri = os.getenv('YANDEX_REDIRECT_URI')

        if not all([client_id, client_secret, redirect_uri]):
            raise HTTPException(
                status_code=500,
                detail='YANDEX_CLIENT_ID, SECRET and REDIRECT_URI must be set'
            )

        # Обмен кода на токен
        token_url = os.getenv('YANDEX_OAUTH_TOKEN', 'https://oauth.yandex.ru/token')
        body = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri
        }

        parsed = http.client.urlsplit(token_url)
        conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
        conn = conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)

        try:
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            conn.request('POST', parsed.path, body=urlencode(body), headers=headers)
            resp = conn.getresponse()
            response_data = resp.read()
            text = response_data.decode('utf-8') if response_data else ''

            if not (200 <= resp.status < 300):
                raise HTTPException(
                    status_code=502,
                    detail=f'Failed exchanging token: {resp.status} {text}'
                )

            token_resp = json.loads(text)
            return token_resp

        finally:
            try:
                conn.close()
            except:
                pass

    @staticmethod
    async def save_yandex_tokens(access_token: str, refresh_token: str = None) -> bool:
        """
        Сохранить токены Яндекса в систему авторизации.

        Args:
            access_token: Access token от Яндекса
            refresh_token: Refresh token от Яндекса (опционально)

        Returns:
            Успешность сохранения
        """
        try:
            # Используем новый модуль аутентификации
            from ...utils.auth_client import store_yandex_token
            return store_yandex_token(access_token, refresh_token)
        except ImportError:
            # Резервный вариант через старый способ
            try:
                data = {
                    "service": 'yandex_smart_home',
                    "token": access_token,
                    "refresh_token": refresh_token
                }

                # Используем AuthServiceClient из старого кода
                url = urljoin(AUTH_SERVICE_BASE, '/api/tokens/cloud/yandex_smart_home')
                parsed = http.client.urlsplit(url)

                conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
                conn = conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)

                try:
                    headers = {"Authorization": f"Bearer {INTERNAL_TOKEN}", "Content-Type": "application/json"}
                    body = json.dumps(data).encode('utf-8')

                    conn.request('POST', parsed.path, body=body, headers=headers)
                    resp = conn.getresponse()
                    response_data = resp.read()
                    text = response_data.decode('utf-8') if response_data else ''

                    if not (200 <= resp.status < 300):
                        raise Exception(f'Auth service returned {resp.status}: {text}')

                    return True

                finally:
                    try:
                        conn.close()
                    except:
                        pass
            except Exception as e:
                logger.error(f"Failed to save Yandex tokens: {e}")
                return False

    @staticmethod
    async def get_yandex_token() -> Optional[str]:
        """
        Получить токен Яндекса из системы авторизации.

        Returns:
            Токен Яндекса или None если не настроен
        """
        try:
            # Используем новый модуль аутентификации
            from ...utils.auth_client import get_yandex_token as get_token
            return get_token()
        except ImportError:
            # Резервный вариант через старый способ
            try:
                # Вызов через HTTP к сервису авторизации
                url = urljoin(AUTH_SERVICE_BASE, '/api/tokens/cloud')
                parsed = http.client.urlsplit(url)

                conn_class = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
                conn = conn_class(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), timeout=10)

                try:
                    headers = {"Authorization": f"Bearer {INTERNAL_TOKEN}"}
                    conn.request('GET', parsed.path, headers=headers)
                    resp = conn.getresponse()
                    response_data = resp.read()
                    text = response_data.decode('utf-8') if response_data else ''

                    if resp.status != 200:
                        raise Exception(f'Failed to fetch tokens: {resp.status} {text}')

                    tokens = json.loads(text) if text else {}
                    ytoken = tokens.get('yandex_smart_home')

                    if not ytoken:
                        return None

                    # Токен может быть строкой или объектом
                    return ytoken if isinstance(ytoken, str) else ytoken.get('token')

                finally:
                    try:
                        conn.close()
                    except:
                        pass
            except Exception as e:
                logger.error(f"Failed to get Yandex token: {e}")
                return None


class YandexSmartHomePlugin(InternalPluginBase):
    """Плагин интеграции с Яндекс Умный Дом с интеграцией авторизации."""

    id = "yandex_smart_home"
    name = "Yandex Smart Home"
    version = "0.3.0"
    description = "Yandex Smart Home adapter - OAuth + device sync + intent mapping + auth integration"

    async def on_load(self):
        """Инициализация плагина."""
        from fastapi import APIRouter
        self.router = APIRouter()

        # Регистрируем endpoints
        self.router.add_api_route("/start_oauth", self.start_oauth, methods=["GET"])
        self.router.add_api_route("/callback", self.oauth_callback, methods=["GET", "POST"])
        self.router.add_api_route("/devices", self.list_devices_proxy, methods=["GET"])
        self.router.add_api_route("/action", self.execute_action, methods=["POST"])

        # Добавляем эндпоинты для синхронизации устройств
        self.router.add_api_route("/sync", self.sync_devices, methods=["POST"])
        self.router.add_api_route("/sync_states", self.sync_device_states, methods=["POST"])
        self.router.add_api_route("/discover", self.auto_discover_new_devices, methods=["POST"])

        # Добавляем эндпоинты для интентов и голосовых команд от Алисы
        self.router.add_api_route("/alice", self.handle_alice_request, methods=["POST"])
        self.router.add_api_route("/intents", self.list_intents, methods=["GET"])
        self.router.add_api_route("/intents", self.create_intent, methods=["POST"])
        self.router.add_api_route("/intents/{intent_name}", self.update_intent, methods=["PUT"])
        self.router.add_api_route("/intents/{intent_name}", self.delete_intent, methods=["DELETE"])

        self.logger.info("✅ Yandex Smart Home plugin with auth integration loaded")

    async def start_oauth(self):
        """Начать OAuth процесс с Яндексом."""
        try:
            url = YandexAuthManager.get_yandex_oauth_url()
            return JSONResponse({"auth_url": url})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def oauth_callback(self, request: Request):
        """Обратный вызов OAuth от Яндекса."""
        params = dict(request.query_params)
        code = params.get('code') or (await request.form()).get('code') if request.method == 'POST' else None
        if not code:
            raise HTTPException(status_code=400, detail='code required')

        # Обменять код на токен
        token_resp = await YandexAuthManager.exchange_code_for_token(code)
        access_token = token_resp.get('access_token') or token_resp.get('token')
        
        if not access_token:
            raise HTTPException(status_code=502, detail='No access_token in token response')

        # Сохранить токены в систему авторизации
        refresh_token = token_resp.get('refresh_token')
        success = await YandexAuthManager.save_yandex_tokens(access_token, refresh_token)
        
        if not success:
            raise HTTPException(status_code=500, detail='Failed to save tokens to auth service')

        return JSONResponse({"status": "ok", "saved": True})

    async def list_devices_proxy(self):
        """Прокси для получения устройств из Яндекса."""
        # Получить токен из системы авторизации
        access_token = await YandexAuthManager.get_yandex_token()
        if not access_token:
            raise HTTPException(status_code=400, detail='Yandex token not configured')

        # Вызвать Яндекс API
        api_base = os.getenv('YANDEX_API_BASE', 'https://api.iot.yandex.net')
        devices_path = os.getenv('YANDEX_DEVICES_PATH', '/v1.0/user/devices')
        parsed_api = http.client.urlsplit(api_base)
        conn_class = http.client.HTTPSConnection if parsed_api.scheme == 'https' else http.client.HTTPConnection
        conn = conn_class(parsed_api.hostname, parsed_api.port or (443 if parsed_api.scheme == 'https' else 80), timeout=10)
        
        try:
            headers = {"Authorization": f"Bearer {access_token}"}
            conn.request('GET', devices_path, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            text = data.decode('utf-8') if data else ''
            
            if resp.status != 200:
                raise HTTPException(status_code=502, detail=f'Yandex API error: {resp.status} {text}')
            
            devices = json.loads(text) if text else []
            # Нормализовать устройства
            normalized = []
            if isinstance(devices, dict) and devices.get('devices'):
                for d in devices.get('devices'):
                    normalized.append({ 
                        'id': d.get('id') or d.get('device_id') or d.get('instance_id'), 
                        'name': d.get('name') or d.get('id'), 
                        'type': d.get('type') or d.get('device_type') 
                    })
            elif isinstance(devices, list):
                for d in devices:
                    if isinstance(d, dict):
                        normalized.append({ 
                            'id': d.get('id') or d.get('device_id'), 
                            'name': d.get('name'), 
                            'type': d.get('type') 
                        })
            else:
                normalized = devices
                
            return JSONResponse({ 'devices': normalized })
            
        finally:
            try:
                conn.close()
            except:
                pass

    async def execute_action(self, payload: dict):
        """Выполнить действие на устройстве Яндекса."""
        # Получить токен из системы авторизации
        access_token = await YandexAuthManager.get_yandex_token()
        if not access_token:
            raise HTTPException(status_code=400, detail='Yandex token not configured')

        device_id = payload.get('device_id')
        if not device_id:
            raise HTTPException(status_code=400, detail='device_id required')

        api_base = os.getenv('YANDEX_API_BASE', 'https://api.iot.yandex.net')
        action_path_template = os.getenv('YANDEX_ACTION_PATH', '/v1.0/devices/{device_id}/actions')
        target_path = action_path_template.replace('{device_id}', str(device_id))
        parsed_api = http.client.urlsplit(api_base)
        conn_class = http.client.HTTPSConnection if parsed_api.scheme == 'https' else http.client.HTTPConnection
        conn = conn_class(parsed_api.hostname, parsed_api.port or (443 if parsed_api.scheme == 'https' else 80), timeout=10)
        
        try:
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            body = json.dumps(payload.get('params') or payload)
            conn.request('POST', target_path, body=body.encode('utf-8'), headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            text = data.decode('utf-8') if data else ''
            
            if not (200 <= resp.status < 300):
                raise HTTPException(status_code=502, detail=f'Yandex action error: {resp.status} {text}')
            
            return JSONResponse({ 'status': 'ok', 'yandex_response': json.loads(text) if text else {} })
            
        finally:
            try:
                conn.close()
            except:
                pass

    # Остальные методы остаются теми же, что и раньше...
    # (sync_devices, sync_device_states, auto_discover_new_devices, и т.д.)
    
    async def sync_devices(self, payload: Dict[str, Any] = None):
        """Синхронизировать устройства между Яндекс и внутренней системой."""
        try:
            # Получаем устройства из Яндекса
            yandex_response = await self.list_devices_proxy()
            yandex_devices = yandex_response.get('content', {}).get('devices', [])
            
            # Получаем существующие связи
            async with self.db_session_maker() as db:
                # Получаем все существующие связи для Яндекса
                existing_bindings_result = await db.execute(
                    select(PluginBinding).where(
                        PluginBinding.plugin_name == 'yandex_smart_home'
                    )
                )
                existing_bindings = existing_bindings_result.scalars().all()
                
                # Создаем маппинг существующих связей
                existing_yandex_ids = {binding.selector for binding in existing_bindings}
                
                # Синхронизируем устройства
                synced_count = 0
                for yandex_dev in yandex_devices:
                    yandex_dev_id = yandex_dev.get('id')
                    yandex_dev_name = yandex_dev.get('name', f"Yandex Device {yandex_dev_id}")
                    yandex_dev_type = yandex_dev.get('type', 'unknown')
                    
                    if yandex_dev_id not in existing_yandex_ids:
                        # Создаем новое внутреннее устройство
                        device = Device(
                            name=yandex_dev_name,
                            type=yandex_dev_type,
                            external_id=yandex_dev_id,
                            external_source='yandex',
                            config={'yandex_device': yandex_dev}
                        )
                        db.add(device)
                        await db.flush()  # Получаем ID нового устройства
                        
                        # Создаем связь между Яндекс-устройством и внутренним устройством
                        binding = PluginBinding(
                            device_id=device.id,
                            plugin_name='yandex_smart_home',
                            selector=yandex_dev_id,
                            enabled=True,
                            config={'yandex_device': yandex_dev}
                        )
                        db.add(binding)
                        synced_count += 1
                    else:
                        # Обновляем существующую связь если нужно
                        for binding in existing_bindings:
                            if binding.selector == yandex_dev_id:
                                # Обновляем конфигурацию
                                binding.config['yandex_device'] = yandex_dev
                                binding.config['last_sync'] = json.dumps({'timestamp': asyncio.get_event_loop().time()})
                                break
                
                await db.commit()
                
            self.logger.info(f"Synced {synced_count} new Yandex devices, total: {len(yandex_devices)}")
            
            return JSONResponse({
                'status': 'ok',
                'synced_new_devices': synced_count,
                'total_yandex_devices': len(yandex_devices),
                'message': f'Synced {synced_count} new Yandex devices, total {len(yandex_devices)} devices'
            })
        except Exception as e:
            self.logger.error(f"Error syncing devices: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def sync_device_states(self):
        """Синхронизировать состояния устройств из Яндекса."""
        try:
            # Получаем устройства из Яндекса (с их состояниями)
            yandex_response = await self.list_devices_proxy()
            yandex_devices = yandex_response.get('content', {}).get('devices', [])

            async with self.db_session_maker() as db:
                # Получаем все связи для Яндекса
                bindings_result = await db.execute(
                    select(PluginBinding).where(
                        PluginBinding.plugin_name == 'yandex_smart_home'
                    )
                )
                bindings = bindings_result.scalars().all()

                updated_count = 0
                for yandex_dev in yandex_devices:
                    yandex_dev_id = yandex_dev.get('id')

                    # Находим связанное внутреннее устройство
                    for binding in bindings:
                        if binding.selector == yandex_dev_id:
                            # Обновляем состояние внутреннего устройства
                            device_result = await db.execute(
                                select(Device).where(Device.id == binding.device_id)
                            )
                            device = device_result.scalar_one_or_none()

                            if device:
                                # Обновляем состояние устройства
                                device.config = device.config or {}
                                device.config['yandex_state'] = yandex_dev.get('state', {})
                                device.config['last_yandex_sync'] = json.dumps({'timestamp': asyncio.get_event_loop().time()})

                                updated_count += 1
                                break

                await db.commit()

            self.logger.info(f"Updated states for {updated_count} Yandex devices")

            return JSONResponse({
                'status': 'ok',
                'updated_states': updated_count,
                'message': f'Updated states for {updated_count} Yandex devices'
            })
        except Exception as e:
            self.logger.error(f"Error syncing device states: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def auto_discover_new_devices(self):
        """Автоматически обнаруживать новые устройства в Яндексе и создавать связи."""
        try:
            # Получаем текущие устройства из Яндекса
            yandex_response = await self.list_devices_proxy()
            yandex_devices = yandex_response.get('content', {}).get('devices', [])

            discovered_count = 0
            for yandex_dev in yandex_devices:
                yandex_dev_id = yandex_dev.get('id')

                # Проверяем, есть ли уже связь для этого устройства
                async with self.db_session_maker() as db:
                    binding_result = await db.execute(
                        select(PluginBinding).where(
                            PluginBinding.plugin_name == 'yandex_smart_home',
                            PluginBinding.selector == yandex_dev_id
                        )
                    )
                    existing_binding = binding_result.scalar_one_or_none()

                    if not existing_binding:
                        # Это новое устройство, создаем связь и внутреннее устройство
                        device = Device(
                            name=yandex_dev.get('name', f"Yandex Device {yandex_dev_id}"),
                            type=yandex_dev.get('type', 'unknown'),
                            external_id=yandex_dev_id,
                            external_source='yandex',
                            config={'yandex_device': yandex_dev, 'auto_created': True}
                        )
                        db.add(device)
                        await db.flush()

                        binding = PluginBinding(
                            device_id=device.id,
                            plugin_name='yandex_smart_home',
                            selector=yandex_dev_id,
                            enabled=True,
                            config={'yandex_device': yandex_dev, 'auto_mapped': True}
                        )
                        db.add(binding)
                        await db.commit()

                        discovered_count += 1

                        # Отправляем событие об обнаружении нового устройства
                        await self.event_bus.emit('device.discovered', {
                            'source': 'yandex',
                            'device_id': device.id,
                            'yandex_device_id': yandex_dev_id,
                            'name': device.name,
                            'type': device.type
                        })

            self.logger.info(f"Auto-discovered {discovered_count} new Yandex devices")

            return JSONResponse({
                'status': 'ok',
                'discovered_devices': discovered_count,
                'message': f'Auto-discovered {discovered_count} new Yandex devices'
            })
        except Exception as e:
            self.logger.error(f"Error auto-discovering devices: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # Заглушки для методов, которые должны быть реализованы
    async def list_bindings(self):
        """Получить список связей между Яндекс-устройствами и внутренними устройствами."""
        return JSONResponse({'bindings': []})

    async def create_binding(self, payload: Dict[str, Any]):
        """Создать связь между Яндекс-устройством и внутренним устройством."""
        return JSONResponse({
            'status': 'created',
            'binding': payload
        })

    async def sync_device_states(self):
        """Синхронизировать состояния устройств из Яндекса."""
        try:
            # Получаем устройства из Яндекса (с их состояниями)
            yandex_response = await self.list_devices_proxy()
            yandex_devices = yandex_response.get('content', {}).get('devices', [])

            async with self.db_session_maker() as db:
                # Получаем все связи для Яндекса
                bindings_result = await db.execute(
                    select(PluginBinding).where(
                        PluginBinding.plugin_name == 'yandex_smart_home'
                    )
                )
                bindings = bindings_result.scalars().all()

                updated_count = 0
                for yandex_dev in yandex_devices:
                    yandex_dev_id = yandex_dev.get('id')

                    # Находим связанное внутреннее устройство
                    for binding in bindings:
                        if binding.selector == yandex_dev_id:
                            # Обновляем состояние внутреннего устройства
                            device_result = await db.execute(
                                select(Device).where(Device.id == binding.device_id)
                            )
                            device = device_result.scalar_one_or_none()

                            if device:
                                # Обновляем состояние устройства
                                device.config = device.config or {}
                                device.config['yandex_state'] = yandex_dev.get('state', {})
                                device.config['last_yandex_sync'] = json.dumps({'timestamp': asyncio.get_event_loop().time()})

                                updated_count += 1
                                break

                await db.commit()

            self.logger.info(f"Updated states for {updated_count} Yandex devices")

            return JSONResponse({
                'status': 'ok',
                'updated_states': updated_count,
                'message': f'Updated states for {updated_count} Yandex devices'
            })
        except Exception as e:
            self.logger.error(f"Error syncing device states: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ========== Функции для интентов и голосовых команд от Алисы ==========
    
    async def handle_alice_request(self, request: Request):
        """Обработать запрос от Яндекс Алисы."""
        try:
            body = await request.json()
            
            # Проверяем тип запроса
            request_type = body.get('request', {}).get('type', 'SimpleUtterance')
            
            if request_type == 'SimpleUtterance':
                # Обработка голосовой команды
                command = body.get('request', {}).get('command', '')
                original_utterance = body.get('request', {}).get('original_utterance', command)
                
                # Обрабатываем команду
                response_text = await self.process_alice_command(original_utterance)
                
                # Формируем ответ для Алисы
                response = {
                    "response": {
                        "text": response_text,
                        "tts": response_text,
                        "end_session": False
                    },
                    "version": "1.0"
                }
                
                return JSONResponse(response)
            elif request_type == 'ButtonPressed':
                # Обработка нажатия кнопки
                payload = body.get('request', {}).get('payload', {})
                return await self.handle_alice_button(payload)
            else:
                return JSONResponse({
                    "response": {
                        "text": "Извините, я не понимаю этот тип запроса",
                        "end_session": False
                    },
                    "version": "1.0"
                })
        except Exception as e:
            self.logger.error(f"Error handling Alice request: {e}")
            return JSONResponse({
                "response": {
                    "text": "Произошла ошибка при обработке запроса",
                    "end_session": False
                },
                "version": "1.0"
            })

    async def process_alice_command(self, command: str) -> str:
        """Обработать голосовую команду от Алисы."""
        try:
            # Пытаемся найти подходящий интент для команды
            intent_name, params = await self.match_intent(command)
            
            if intent_name:
                # Выполняем действие, связанное с интентом
                result = await self.execute_intent_action(intent_name, params)
                return result or f"Выполнил команду: {command}"
            else:
                # Пытаемся найти устройство по команде
                device_action = await self.parse_device_command(command)
                if device_action:
                    # Выполняем действие на устройстве
                    result = await self.execute_device_action(device_action['device_id'], device_action['action'], device_action.get('params', {}))
                    return result or f"Выполнил действие на устройстве: {command}"
                else:
                    return f"Извините, я не понимаю команду: {command}"
        except Exception as e:
            self.logger.error(f"Error processing Alice command '{command}': {e}")
            return "Произошла ошибка при обработке команды"

    async def match_intent(self, command: str) -> tuple[Optional[str], Dict[str, Any]]:
        """Найти подходящий интент для команды."""
        try:
            async with self.db_session_maker() as db:
                # Ищем интенты, которые могут соответствовать команде
                intents_result = await db.execute(
                    select(IntentMapping).where(
                        IntentMapping.plugin_action.like(f'%{command}%')
                    )
                )
                intents = intents_result.scalars().all()
                
                # Проверяем каждый интент на соответствие команде
                for intent in intents:
                    # Простое сопоставление - в реальности может быть сложнее (NLP)
                    if intent.intent_name.lower() in command.lower() or \
                       (intent.selector and intent.selector.lower() in command.lower()):
                        return intent.intent_name, {'command': command}
                
                # Если не нашли подходящий интент, возвращаем None
                return None, {}
        except Exception as e:
            self.logger.error(f"Error matching intent for command '{command}': {e}")
            return None, {}

    async def execute_intent_action(self, intent_name: str, params: Dict[str, Any]) -> Optional[str]:
        """Выполнить действие, связанное с интентом."""
        try:
            async with self.db_session_maker() as db:
                intent_result = await db.execute(
                    select(IntentMapping).where(
                        IntentMapping.intent_name == intent_name
                    )
                )
                intent = intent_result.scalar_one_or_none()
                
                if not intent or not intent.plugin_action:
                    return None
                
                # Выполняем действие через event bus
                await self.event_bus.emit('intent.executed', {
                    'intent_name': intent_name,
                    'action': intent.plugin_action,
                    'params': params,
                    'source': 'alice'
                })
                
                # Возвращаем результат выполнения
                return f"Выполнил интент: {intent_name}"
        except Exception as e:
            self.logger.error(f"Error executing intent '{intent_name}': {e}")
            return None

    async def parse_device_command(self, command: str) -> Optional[Dict[str, Any]]:
        """Разобрать команду устройства из голосовой команды."""
        try:
            # Простой парсер команд устройств - в реальности может быть сложнее
            command_lower = command.lower()
            
            # Пытаемся определить действие
            action = None
            if 'включи' in command_lower or 'включить' in command_lower:
                action = 'turn_on'
            elif 'выключи' in command_lower or 'выключить' in command_lower:
                action = 'turn_off'
            elif 'открой' in command_lower or 'открыть' in command_lower:
                action = 'open'
            elif 'закрой' in command_lower or 'закрыть' in command_lower:
                action = 'close'
            elif 'увеличь' in command_lower or 'повысь' in command_lower:
                action = 'increase'
            elif 'уменьши' in command_lower or 'понизь' in command_lower:
                action = 'decrease'
            
            if not action:
                return None
            
            # Пытаемся определить устройство
            async with self.db_session_maker() as db:
                devices_result = await db.execute(select(Device))
                devices = devices_result.scalars().all()
                
                for device in devices:
                    device_name = device.name.lower()
                    if device_name in command_lower:
                        return {
                            'device_id': device.id,
                            'action': action,
                            'params': {'command': command}
                        }
                
                # Если не нашли конкретное устройство, можем вернуть общий запрос
                return {
                    'device_id': None,
                    'action': action,
                    'params': {'command': command, 'query': command_lower}
                }
                
        except Exception as e:
            self.logger.error(f"Error parsing device command '{command}': {e}")
            return None

    async def execute_device_action(self, device_id: Optional[str], action: str, params: Dict[str, Any]) -> Optional[str]:
        """Выполнить действие на устройстве."""
        try:
            if not device_id:
                # Если нет конкретного устройства, можем выполнить общий запрос
                await self.event_bus.emit('device.action.requested', {
                    'action': action,
                    'params': params,
                    'source': 'alice'
                })
                return f"Выполнил действие: {action}"
            
            # Найти связь между внутренним устройством и Яндекс-устройством
            async with self.db_session_maker() as db:
                binding_result = await db.execute(
                    select(PluginBinding).where(
                        PluginBinding.device_id == device_id,
                        PluginBinding.plugin_name == 'yandex_smart_home'
                    )
                )
                binding = binding_result.scalar_one_or_none()
                
                if binding:
                    # Выполнить команду через Яндекс API
                    yandex_device_id = binding.selector
                    yandex_response = await self.send_command_to_yandex_device(yandex_device_id, action, params)
                    return yandex_response or f"Выполнил действие {action} на устройстве"
                else:
                    # Выполнить действие на внутреннем устройстве
                    await self.event_bus.emit('device.action', {
                        'device_id': device_id,
                        'action': action,
                        'params': params,
                        'source': 'alice'
                    })
                    return f"Выполнил действие {action} на устройстве"
        except Exception as e:
            self.logger.error(f"Error executing device action '{action}' on device {device_id}: {e}")
            return None

    async def send_command_to_yandex_device(self, yandex_device_id: str, action: str, params: Dict[str, Any]) -> Optional[str]:
        """Отправить команду в Яндекс Умный Дом."""
        try:
            # Подготовить команду для Яндекс API
            yandex_payload = {
                'device_id': yandex_device_id,
                'action': action,
                'params': params
            }
            
            # Вызвать выполнение действия через Яндекс API
            result = await self.execute_action(yandex_payload)
            return result.get('status', 'ok') if isinstance(result, dict) else 'ok'
        except Exception as e:
            self.logger.error(f"Error sending command to Yandex device {yandex_device_id}: {e}")
            return None

    async def handle_alice_button(self, payload: Dict[str, Any]) -> JSONResponse:
        """Обработать нажатие кнопки в Алисе."""
        try:
            # Обработка нажатия кнопки
            button_text = payload.get('title', 'Неизвестная кнопка')
            
            # Можем обрабатывать специальные кнопки
            if button_text == 'Список устройств':
                devices_response = await self.list_devices_proxy()
                devices = devices_response.get('content', {}).get('devices', [])
                device_list = ', '.join([d.get('name', d.get('id', 'Unknown')) for d in devices])
                response_text = f"Устройства: {device_list}" if device_list else "Нет доступных устройств"
            else:
                response_text = f"Нажата кнопка: {button_text}"
            
            return JSONResponse({
                "response": {
                    "text": response_text,
                    "tts": response_text,
                    "end_session": False
                },
                "version": "1.0"
            })
        except Exception as e:
            self.logger.error(f"Error handling Alice button: {e}")
            return JSONResponse({
                "response": {
                    "text": "Произошла ошибка при обработке кнопки",
                    "end_session": False
                },
                "version": "1.0"
            })

    # ========== Управление интентами ==========
    
    async def list_intents(self):
        """Получить список интентов."""
        try:
            async with self.db_session_maker() as db:
                intents_result = await db.execute(
                    select(IntentMapping).where(
                        IntentMapping.plugin_name == 'yandex_smart_home'
                    )
                )
                intents = intents_result.scalars().all()
                
                intents_list = []
                for intent in intents:
                    intents_list.append({
                        'id': intent.id,
                        'intent_name': intent.intent_name,
                        'selector': intent.selector,
                        'plugin_action': intent.plugin_action,
                        'description': intent.description,
                        'enabled': intent.enabled
                    })
                
                return JSONResponse({'intents': intents_list})
        except Exception as e:
            self.logger.error(f"Error listing intents: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def create_intent(self, payload: Dict[str, Any]):
        """Создать новый интент."""
        try:
            intent_name = payload.get('intent_name')
            selector = payload.get('selector')
            plugin_action = payload.get('plugin_action')
            description = payload.get('description', '')
            enabled = payload.get('enabled', True)
            
            if not intent_name or not plugin_action:
                raise HTTPException(status_code=400, detail='intent_name and plugin_action are required')
            
            async with self.db_session_maker() as db:
                intent = IntentMapping(
                    intent_name=intent_name,
                    selector=selector,
                    plugin_name='yandex_smart_home',
                    plugin_action=plugin_action,
                    description=description,
                    enabled=enabled
                )
                db.add(intent)
                await db.commit()
                
                return JSONResponse({
                    'status': 'created',
                    'intent': {
                        'id': intent.id,
                        'intent_name': intent.intent_name,
                        'selector': intent.selector,
                        'plugin_action': intent.plugin_action,
                        'description': intent.description,
                        'enabled': intent.enabled
                    }
                })
        except Exception as e:
            self.logger.error(f"Error creating intent: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def update_intent(self, intent_name: str, payload: Dict[str, Any]):
        """Обновить интент."""
        try:
            async with self.db_session_maker() as db:
                intent_result = await db.execute(
                    select(IntentMapping).where(
                        IntentMapping.intent_name == intent_name,
                        IntentMapping.plugin_name == 'yandex_smart_home'
                    )
                )
                intent = intent_result.scalar_one_or_none()
                
                if not intent:
                    raise HTTPException(status_code=404, detail=f'Intent {intent_name} not found')
                
                # Обновляем поля
                if 'selector' in payload:
                    intent.selector = payload['selector']
                if 'plugin_action' in payload:
                    intent.plugin_action = payload['plugin_action']
                if 'description' in payload:
                    intent.description = payload['description']
                if 'enabled' in payload:
                    intent.enabled = payload['enabled']
                
                await db.commit()
                
                return JSONResponse({
                    'status': 'updated',
                    'intent': {
                        'id': intent.id,
                        'intent_name': intent.intent_name,
                        'selector': intent.selector,
                        'plugin_action': intent.plugin_action,
                        'description': intent.description,
                        'enabled': intent.enabled
                    }
                })
        except Exception as e:
            self.logger.error(f"Error updating intent {intent_name}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def delete_intent(self, intent_name: str):
        """Удалить интент."""
        try:
            async with self.db_session_maker() as db:
                intent_result = await db.execute(
                    select(IntentMapping).where(
                        IntentMapping.intent_name == intent_name,
                        IntentMapping.plugin_name == 'yandex_smart_home'
                    )
                )
                intent = intent_result.scalar_one_or_none()
                
                if not intent:
                    raise HTTPException(status_code=404, detail=f'Intent {intent_name} not found')
                
                await db.delete(intent)
                await db.commit()
                
                return JSONResponse({'status': 'deleted', 'intent_name': intent_name})
        except Exception as e:
            self.logger.error(f"Error deleting intent {intent_name}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def on_unload(self):
        """Cleanup при выгрузке."""
        self.logger.info("👋 Yandex Smart Home plugin with auth integration unloaded")