import websocket
import threading
import time
import json
import logging
import asyncio
from typing import Optional, Callable, Any

class PikvmWebSocketClient:
    def __init__(self, controller, device_id: str = None, event_emitter: Optional[Callable] = None, main_event_loop=None):
        """
        Args:
            controller: PikvmController instance
            device_id: Идентификатор устройства
            event_emitter: Async функция для публикации событий (event_name, data)
            main_event_loop: Event loop из основного потока (для run_coroutine_threadsafe)
        """
        self.controller = controller
        self.device_id = device_id or getattr(controller, 'device_id', 'unknown')
        self.event_emitter = event_emitter
        self.main_event_loop = main_event_loop
        self.ws = None
        self.is_running = False
        self.reconnect_interval = 5  # seconds between reconnection attempts
    
    def _emit_event(self, event_name: str, data: dict):
        """
        Публиковать событие через event_emitter (если доступен) или просто логировать.
        Работает автономно - если event_emitter не задан, просто логирует.
        """
        event_data = {
            "device_id": self.device_id,
            **data
        }
        
        # Логируем всегда (автономная работа)
        logging.info(f"[{self.device_id}] Event: {event_name}, data: {event_data}")
        
        # Публикуем в event bus, если доступен
        if self.event_emitter and self.main_event_loop:
            try:
                # Используем run_coroutine_threadsafe для безопасной публикации из потока
                future = asyncio.run_coroutine_threadsafe(
                    self.event_emitter(event_name, event_data),
                    self.main_event_loop
                )
                # Не ждем результата, чтобы не блокировать WebSocket поток
                # Если нужно, можно добавить обработку исключений через future.exception()
            except Exception as e:
                logging.warning(f"Failed to emit event '{event_name}': {e}. Continuing with logging only.")

    def on_message(self, ws, message):
        """
        Callback for when a message is received
        
        :param ws: WebSocket connection
        :param message: Received message
        """
        try:
            # Parse the message
            data = json.loads(message)
            
            # Публикуем событие о получении сообщения
            self._emit_event("websocket.message", {
                "message": data,
                "raw": message
            })
            
            # Add your custom message handling logic here
            if data.get('action') == 'status':
                self.handle_status_message(data)
        except json.JSONDecodeError:
            logging.error(f"Failed to parse message: {message}")
        except Exception as e:
            logging.error(f"Error processing message: {e}")

    def handle_status_message(self, data):
        """
        Example method to handle specific types of messages
        
        :param data: Parsed message data
        """
        # Публикуем событие о статусе
        self._emit_event("websocket.status", {
            "status": data
        })

    def on_error(self, ws, error):
        """
        Callback for WebSocket errors
        
        :param ws: WebSocket connection
        :param error: Error details
        """
        # Публикуем событие об ошибке
        self._emit_event("websocket.error", {
            "error": str(error),
            "error_type": type(error).__name__
        })
        self.reconnect()

    def on_close(self, ws, close_status_code, close_msg):
        """
        Callback for WebSocket connection closure
        
        :param ws: WebSocket connection
        :param close_status_code: Status code of closure
        :param close_msg: Closure message
        """
        # Публикуем событие о закрытии соединения
        self._emit_event("websocket.closed", {
            "status_code": close_status_code,
            "message": close_msg
        })
        self.reconnect()

    def on_open(self, ws):
        """
        Callback for when WebSocket connection is established
        
        :param ws: WebSocket connection
        """
        # Публикуем событие об установке соединения
        self._emit_event("websocket.connected", {})
        
        # Send initial connection message or status request
        try:
            initial_message = json.dumps({"action": "get_status"})
            ws.send(initial_message)
        except Exception as e:
            logging.error(f"Failed to send initial message: {e}")

    def connect(self):
        """
        Establish WebSocket connection
        """
        try:
            # SSL options to ignore certificate verification
            ssl_opt = self.controller.settings.ssl_options
            
            # Create WebSocket connection
            self.ws = websocket.WebSocketApp(
                self.controller.settings.websocket_url,
                header=self.controller.headers,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            
            # Run the WebSocket in a separate thread
            self.is_running = True
            wst = threading.Thread(target=self.ws.run_forever, kwargs={'sslopt': ssl_opt})
            wst.daemon = True
            wst.start()
            
            return wst
        except Exception as e:
            logging.error(f"Failed to establish WebSocket connection: {e}")
            return None

    def reconnect(self):
        """
        Attempt to reconnect if connection is lost
        """
        if not self.is_running:
            return
        
        logging.info("Attempting to reconnect...")
        
        # Close existing connection if it exists
        if self.ws:
            self.ws.close()
        
        # Wait before reconnecting
        time.sleep(self.reconnect_interval)
        
        # Attempt to reconnect
        self.connect()

    def stop(self):
        """
        Stop the WebSocket connection
        """
        self.is_running = False
        if self.ws:
            self.ws.close()
        logging.info("WebSocket connection stopped")