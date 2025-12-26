"""Alice (Yandex voice assistant) handlers for Yandex Smart Home plugin."""
import logging
from typing import Dict, Any, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select


logger = logging.getLogger(__name__)


class AliceHandlers:
    """Handlers for Yandex Alice voice assistant requests."""

    def __init__(self, plugin_instance):
        """Initialize handlers with plugin instance reference."""
        self.plugin = plugin_instance
        self.db_session_maker = plugin_instance.db_session_maker if hasattr(plugin_instance, 'db_session_maker') else None
        self.event_bus = plugin_instance.event_bus if hasattr(plugin_instance, 'event_bus') else None
        self.logger = logging.getLogger(__name__)

    async def handle_alice_request(self, request: Request):
        """
        Обработать запрос от Яндекс Алисы.
        """
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
        """
        Обработать голосовую команду от Алисы.
        """
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
        """
        Найти подходящий интент для команды.
        """
        # removed
        # models: IntentMapping
        
        try:
            async with self.plugin.get_session() as db:
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
        """
        Выполнить действие, связанное с интентом.
        """
        # removed
        # models: IntentMapping
        
        try:
            async with self.plugin.get_session() as db:
                intent_result = await db.execute(
                    select(IntentMapping).where(
                        IntentMapping.intent_name == intent_name
                    )
                )
                intent = intent_result.scalar_one_or_none()

                if not intent or not intent.plugin_action:
                    return None

                # Выполняем действие через event bus
                if self.event_bus:
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
        """
        Разобрать команду устройства из голосовой команды.
        """
        # removed
        # models: Device
        
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
            async with self.plugin.get_session() as db:
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
        """
        Выполнить действие на устройстве.
        """
        # removed
        # models: PluginBinding
        
        try:
            if not device_id:
                # Если нет конкретного устройства, можем выполнить общий запрос
                if self.event_bus:
                    await self.event_bus.emit('device.action.requested', {
                        'action': action,
                        'params': params,
                        'source': 'alice'
                    })
                return f"Выполнил действие: {action}"

            # Найти связь между внутренним устройством и Яндекс-устройством
            async with self.plugin.get_session() as db:
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
                    if self.event_bus:
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

    def _convert_action_to_yandex_payload(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Конвертировать внутреннее действие в формат Яндекс API.
        
        Внутренние действия: turn_on, turn_off, open, close, increase, decrease
        Яндекс API использует capabilities и properties в пейлоаде.
        """
        payload = {}
        
        # Конвертируем команду включения/выключения
        if action == 'turn_on':
            payload['on'] = True
        elif action == 'turn_off':
            payload['on'] = False
        elif action == 'toggle':
            # toggle требует информацию о текущем состоянии
            # По умолчанию предполагаем включение
            payload['on'] = params.get('on', True)
        elif action == 'open':
            payload['open'] = True
        elif action == 'close':
            payload['open'] = False
        elif action == 'increase':
            # Увеличение значения (яркость, температура и т.д.)
            current = params.get('current_value', 0)
            payload['brightness'] = min(100, current + 10)  # Увеличиваем на 10
        elif action == 'decrease':
            # Уменьшение значения
            current = params.get('current_value', 100)
            payload['brightness'] = max(0, current - 10)  # Уменьшаем на 10
        else:
            # Неизвестное действие - просто передаём параметры
            payload = params
        
        return payload

    async def send_command_to_yandex_device(self, yandex_device_id: str, action: str, params: Dict[str, Any]) -> Optional[str]:
        """
        Отправить команду в Яндекс Умный Дом.
        """
        try:
            # Конвертируем действие в правильный формат Яндекс API
            action_payload = self._convert_action_to_yandex_payload(action, params)
            
            # Подготовить команду для Яндекс API в правильном формате
            yandex_payload = {
                'device_id': yandex_device_id,
                'params': action_payload  # Передаём правильно отформатированный payload
            }

            self.logger.debug(f"Sending command to Yandex device {yandex_device_id}: action={action}, payload={yandex_payload}")
            
            # Вызвать выполнение действия через route handler
            result = await self.plugin.route_handlers.execute_action(yandex_payload, None)
            return result.get('status', 'ok') if isinstance(result, dict) else 'ok'
        except Exception as e:
            self.logger.error(f"Error sending command to Yandex device {yandex_device_id}: {e}")
            return None

    async def handle_alice_button(self, payload: Dict[str, Any]) -> JSONResponse:
        """
        Обработать нажатие кнопки в Алисе.
        """
        try:
            # Обработка нажатия кнопки
            button_text = payload.get('title', 'Неизвестная кнопка')

            # Можем обрабатывать специальные кнопки
            if button_text == 'Список устройств':
                devices_response = await self.plugin.route_handlers.list_devices_proxy(request=None)
                if hasattr(devices_response, 'body'):
                    import json
                    body = devices_response.body
                    data = json.loads(body.decode('utf-8')) if body else {}
                else:
                    data = devices_response if isinstance(devices_response, dict) else {}
                    
                devices = data.get('devices', [])
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
