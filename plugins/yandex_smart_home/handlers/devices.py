"""Device handlers for Yandex Smart Home plugin."""
import logging
import json
import asyncio
from typing import Dict, Any, Optional
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select


logger = logging.getLogger(__name__)


class DeviceHandlers:
    """Handlers for device-related operations."""

    def __init__(self, plugin_instance):
        """Initialize handlers with plugin instance reference."""
        self.plugin = plugin_instance
        self.db_session_maker = plugin_instance.db_session_maker if hasattr(plugin_instance, 'db_session_maker') else None
        self.event_bus = plugin_instance.event_bus if hasattr(plugin_instance, 'event_bus') else None
        self.logger = logging.getLogger(__name__)
    
    def _get_model(self, model_name: str):
        """Get core model via plugin DI."""
        model = self.plugin.get_core_model(model_name)
        if not model:
            raise HTTPException(status_code=500, detail=f"Core model {model_name} not available")
        return model

    async def sync_devices(self, payload: Dict[str, Any] = None, user_id: str = None):
        """
        Синхронизировать устройства между Яндекс и внутренней системой.
        """
        try:
            # Получаем устройства из Яндекса через API
            devices_data = await self.plugin.route_handlers.list_devices_proxy(request=None, user_id=user_id)
            
            # Извлекаем данные из ответа
            if hasattr(devices_data, 'body'):
                try:
                    body = devices_data.body
                    data = json.loads(body.decode('utf-8')) if body else {}
                except Exception:
                    data = {}
            else:
                data = devices_data if isinstance(devices_data, dict) else {}

            yandex_devices = data.get('devices') or []

            # Получаем существующие связи
            async with self.plugin.get_session() as db:
                # Get Device and PluginBinding from core_models
                Device = self._get_model('Device')
                PluginBinding = self._get_model('PluginBinding')
                
                # Получаем все существующие связи для Яндекса
                existing_bindings_result = await db.execute(
                    select(PluginBinding).where(
                        PluginBinding.plugin_name == 'yandex_smart_home'
                    )
                )
                existing_bindings = existing_bindings_result.scalars().all()

                # Создаем маппинг существующих связей
                existing_yandex_ids = {binding.selector for binding in existing_bindings}

                # Создаем маппинг binding -> device для быстрого доступа
                binding_to_device = {}
                for binding in existing_bindings:
                    if binding.device_id:
                        device_result = await db.execute(
                            select(Device).where(Device.id == binding.device_id)
                        )
                        device = device_result.scalar_one_or_none()
                        if device:
                            binding_to_device[binding.selector] = (binding, device)

                # Синхронизируем устройства
                synced_count = 0
                updated_count = 0
                
                for yandex_dev in yandex_devices:
                    yandex_dev_id = yandex_dev.get('id')
                    yandex_dev_name = yandex_dev.get('name', f"Yandex Device {yandex_dev_id}")
                    yandex_dev_type = yandex_dev.get('type', 'unknown')

                    if yandex_dev_id not in existing_yandex_ids:
                        # Создаем новое внутреннее устройство
                        device = Device(
                            id=str(uuid4()),
                            name=yandex_dev_name,
                            type=yandex_dev_type,
                            meta={
                                'yandex_device_id': yandex_dev_id,
                                'yandex_device': yandex_dev,
                                'external_source': 'yandex'
                            }
                        )
                        db.add(device)
                        await db.flush()  # Получаем ID нового устройства

                        # Создаем связь между Яндекс-устройством и внутренним устройством
                        binding = PluginBinding(
                            id=str(uuid4()),
                            device_id=device.id,
                            plugin_name='yandex_smart_home',
                            selector=yandex_dev_id,
                            enabled=True,
                            config={'yandex_device': yandex_dev}
                        )
                        db.add(binding)
                        synced_count += 1
                    else:
                        # Обновляем существующее устройство и связь
                        if yandex_dev_id in binding_to_device:
                            binding, device = binding_to_device[yandex_dev_id]
                            
                            # Обновляем данные устройства
                            device.name = yandex_dev_name
                            device.type = yandex_dev_type
                            if not device.meta:
                                device.meta = {}
                            device.meta['yandex_device_id'] = yandex_dev_id
                            device.meta['yandex_device'] = yandex_dev
                            device.meta['external_source'] = 'yandex'
                            
                            # Обновляем конфигурацию binding
                            if not binding.config:
                                binding.config = {}
                            binding.config['yandex_device'] = yandex_dev
                            binding.config['last_sync'] = json.dumps({'timestamp': asyncio.get_event_loop().time()})
                            
                            updated_count += 1

                await db.commit()

            self.logger.info(f"Synced {synced_count} new Yandex devices, updated {updated_count} existing devices, total: {len(yandex_devices)}")

            return JSONResponse({
                'status': 'ok',
                'synced_new_devices': synced_count,
                'updated_devices': updated_count,
                'total_yandex_devices': len(yandex_devices),
                'message': f'Synced {synced_count} new Yandex devices, updated {updated_count} existing devices, total {len(yandex_devices)} devices'
            })
        except Exception as e:
            self.logger.error(f"Error syncing devices: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def sync_device_states(self, user_id: str = None):
        """
        Синхронизировать состояния устройств из Яндекса.
        """
        try:
            # Получаем устройства из Яндекса (с их состояниями)
            yandex_response = await self.plugin.route_handlers.list_devices_proxy(request=None, user_id=user_id)
            if hasattr(yandex_response, 'body'):
                try:
                    body = yandex_response.body
                    data = json.loads(body.decode('utf-8')) if body else {}
                except Exception:
                    data = {}
            else:
                data = yandex_response if isinstance(yandex_response, dict) else {}

            yandex_devices = data.get('devices') or []
            
            Device = self._get_model('Device')
            PluginBinding = self._get_model('PluginBinding')

            async with self.plugin.get_session() as db:
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
                                if not device.meta:
                                    device.meta = {}
                                device.meta['yandex_state'] = yandex_dev.get('state', {})
                                device.meta['last_yandex_sync'] = json.dumps({'timestamp': asyncio.get_event_loop().time()})

                                updated_count += 1
                                break

                await db.commit()
            
            # Обновляем статус онлайн для всех устройств через StateManager
            if hasattr(self.plugin, 'state_manager') and self.plugin.state_manager:
                for yandex_dev in yandex_devices:
                    yandex_dev_id = yandex_dev.get('id')
                    
                    # Находим device_id для этого Yandex устройства
                    for binding in bindings:
                        if binding.selector == yandex_dev_id:
                            await self.plugin.state_manager.update_device_status(
                                binding.device_id, 
                                yandex_dev
                            )
                            break

            self.logger.info(f"Updated states for {updated_count} Yandex devices")

            # If plugin configured to use authoritative per-device polling, run it
            authoritative_updated = 0
            try:
                use_auth = False
                if hasattr(self.plugin, 'config') and isinstance(self.plugin.config, dict):
                    use_auth = bool(self.plugin.config.get('use_authoritative_state', False))

                if use_auth and hasattr(self.plugin, 'device_manager') and self.plugin.device_manager:
                    authoritative_updated = await self.plugin.device_manager.poll_authoritative_states(user_id=user_id)
            except Exception as e:
                self.logger.warning(f"Authoritative poll failed: {e}")

            return JSONResponse({
                'status': 'ok',
                'updated_states': updated_count,
                'authoritative_updates': authoritative_updated,
                'message': f'Updated states for {updated_count} Yandex devices (authoritative updates: {authoritative_updated})'
            })
        except Exception as e:
            self.logger.error(f"Error syncing device states: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def auto_discover_new_devices(self, user_id: str = None):
        """
        Автоматически обнаруживать новые устройства в Яндексе и создавать связи.
        """
        Device = self._get_model('Device')
        PluginBinding = self._get_model('PluginBinding')
        
        try:
            # Получаем текущие устройства из Яндекса
            yandex_response = await self.plugin.route_handlers.list_devices_proxy(request=None, user_id=user_id)
            if hasattr(yandex_response, 'body'):
                try:
                    body = yandex_response.body
                    data = json.loads(body.decode('utf-8')) if body else {}
                except Exception:
                    data = {}
            else:
                data = yandex_response if isinstance(yandex_response, dict) else {}

            yandex_devices = data.get('devices') or []

            discovered_count = 0
            for yandex_dev in yandex_devices:
                yandex_dev_id = yandex_dev.get('id')

                # Проверяем, есть ли уже связь для этого устройства
                async with self.plugin.get_session() as db:
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
                        if self.event_bus:
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

    async def list_bindings(self):
        """Получить список связей между Яндекс-устройствами и внутренними устройствами."""
        PluginBinding = self._get_model('PluginBinding')
        
        try:
            async with self.plugin.get_session() as db:
                bindings_result = await db.execute(
                    select(PluginBinding).where(
                        PluginBinding.plugin_name == 'yandex_smart_home'
                    )
                )
                bindings = bindings_result.scalars().all()
                
                bindings_list = []
                for binding in bindings:
                    bindings_list.append({
                        'id': binding.id,
                        'device_id': binding.device_id,
                        'yandex_device_id': binding.selector,
                        'enabled': binding.enabled,
                        'config': binding.config
                    })
                
                return JSONResponse({'bindings': bindings_list})
        except Exception as e:
            self.logger.error(f"Error listing bindings: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def create_binding(self, payload: Dict[str, Any]):
        """Создать связь между Яндекс-устройством и внутренним устройством."""
        Device = self._get_model('Device')
        PluginBinding = self._get_model('PluginBinding')
        
        try:
            yandex_device_id = payload.get('yandex_device_id')
            internal_device_id = payload.get('internal_device_id')
            enabled = payload.get('enabled', True)
            config = payload.get('config', {})
            
            if not yandex_device_id or not internal_device_id:
                raise HTTPException(status_code=400, detail='yandex_device_id and internal_device_id required')
            
            async with self.plugin.get_session() as db:
                # Проверяем существование внутреннего устройства
                device_result = await db.execute(
                    select(Device).where(Device.id == internal_device_id)
                )
                device = device_result.scalar_one_or_none()
                if not device:
                    raise HTTPException(status_code=404, detail=f'Device {internal_device_id} not found')
                
                # Создаем связь
                binding = PluginBinding(
                    device_id=internal_device_id,
                    plugin_name='yandex_smart_home',
                    selector=yandex_device_id,  # Яндекс-идентификатор устройства
                    enabled=enabled,
                    config=config
                )
                db.add(binding)
                await db.commit()
                
                return JSONResponse({
                    'status': 'created',
                    'binding': {
                        'id': binding.id,
                        'device_id': binding.device_id,
                        'yandex_device_id': binding.selector,
                        'enabled': binding.enabled
                    }
                })
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error creating binding: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def handle_yandex_command(self, yandex_device_id: str, command: str, params: Dict[str, Any]):
        """
        Обработать команду от Яндекса для внутреннего устройства.
        """
        PluginBinding = self._get_model('PluginBinding')
        
        try:
            async with self.plugin.get_session() as db:
                # Найти связь между Яндекс-устройством и внутренним устройством
                binding_result = await db.execute(
                    select(PluginBinding).where(
                        PluginBinding.plugin_name == 'yandex_smart_home',
                        PluginBinding.selector == yandex_device_id,
                        PluginBinding.enabled == True
                    )
                )
                binding = binding_result.scalar_one_or_none()

                if not binding:
                    raise HTTPException(status_code=404, detail=f'No binding found for Yandex device {yandex_device_id}')

                # Выполнить команду на внутреннем устройстве
                # Это может быть выполнение через event bus или прямой вызов
                if self.event_bus:
                    await self.event_bus.emit('yandex.command', {
                        'yandex_device_id': yandex_device_id,
                        'internal_device_id': binding.device_id,
                        'command': command,
                        'params': params
                    })

                return {'status': 'ok', 'executed': True}

        except Exception as e:
            self.logger.error(f"Error handling Yandex command: {e}")
            raise
