import websocket
import threading
import time
import json
import logging

class PikvmWebSocketClient:
    def __init__(self, controller, mongodb_handler):
        self.controller = controller
        self.mongodb_handler = mongodb_handler
        self.ws = None
        self.is_running = False
        self.reconnect_interval = 5  # seconds between reconnection attempts

    def on_message(self, ws, message):
        """
        Callback for when a message is received
        
        :param ws: WebSocket connection
        :param message: Received message
        """
        try:
            # Parse the message
            data = json.loads(message)
            logging.info(f"Received WebSocket message: {data}")
            
            # Save to MongoDB
            self.mongodb_handler.save_websocket_event({
                'source': 'pikvm_websocket',
                'raw_message': data
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
        logging.info(f"Handling status message: {data}")
        # Add your specific status handling logic here

    def on_error(self, ws, error):
        """
        Callback for WebSocket errors
        
        :param ws: WebSocket connection
        :param error: Error details
        """
        logging.error(f"WebSocket error: {error}")
        self.mongodb_handler.save_websocket_event({
            'source': 'pikvm_websocket',
            'event_type': 'error',
            'error_details': str(error)
        })
        self.reconnect()

    def on_close(self, ws, close_status_code, close_msg):
        """
        Callback for WebSocket connection closure
        
        :param ws: WebSocket connection
        :param close_status_code: Status code of closure
        :param close_msg: Closure message
        """
        logging.warning(f"WebSocket connection closed. Code: {close_status_code}, Message: {close_msg}")
        self.mongodb_handler.save_websocket_event({
            'source': 'pikvm_websocket',
            'event_type': 'connection_close',
            'status_code': close_status_code,
            'message': close_msg
        })
        self.reconnect()

    def on_open(self, ws):
        """
        Callback for when WebSocket connection is established
        
        :param ws: WebSocket connection
        """
        logging.info("WebSocket connection established")
        
        # Save connection event to MongoDB
        self.mongodb_handler.save_websocket_event({
            'source': 'pikvm_websocket',
            'event_type': 'connection_open'
        })
        
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