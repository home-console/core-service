#!/usr/bin/env python3
import grpc
from concurrent import futures
import logging
import sys
import os

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import generated modules
from generated import pikvm_service_pb2, pikvm_service_pb2_grpc

# Import the PIKVM controller
from controllers.pikvm import PikvmController

class PikvmControlService(pikvm_service_pb2_grpc.PikvmControlServiceServicer):
    def __init__(self):
        """
        Initialize the gRPC service with a PIKVM controller
        """
        self.controller = PikvmController()

    def PowerControl(self, request, context):
        """
        Handle power control gRPC request
        """
        try:
            # Map protobuf enum to controller method
            action_map = {
                pikvm_service_pb2.PowerControlRequest.ON: 'on',
                pikvm_service_pb2.PowerControlRequest.OFF: 'off',
                pikvm_service_pb2.PowerControlRequest.OFF_HARD: 'off_hard',
                pikvm_service_pb2.PowerControlRequest.RESET_HARD: 'reset_hard'
            }
            
            # Call power control
            response = self.controller.power_control(
                action=action_map[request.action], 
                wait=request.wait
            )
            
            return pikvm_service_pb2.CommandResponse(
                success=True, 
                message=str(response)
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pikvm_service_pb2.CommandResponse(
                success=False, 
                message=str(e)
            )

    def ButtonClick(self, request, context):
        """
        Handle button click gRPC request
        """
        try:
            # Map protobuf enum to controller method
            button_map = {
                pikvm_service_pb2.ButtonClickRequest.POWER: 'power',
                pikvm_service_pb2.ButtonClickRequest.POWER_LONG: 'power_long',
                pikvm_service_pb2.ButtonClickRequest.RESET: 'reset'
            }
            
            # Call button click
            response = self.controller.power_button_click(
                button=button_map[request.button], 
                wait=request.wait
            )
            
            return pikvm_service_pb2.CommandResponse(
                success=True, 
                message=str(response)
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pikvm_service_pb2.CommandResponse(
                success=False, 
                message=str(e)
            )

    def UploadMSDImage(self, request, context):
        """
        Handle MSD image upload gRPC request
        """
        try:
            # Call MSD image upload
            response = self.controller.upload_msd_image(
                image_path=request.image_path, 
                image_name=request.image_name
            )
            
            return pikvm_service_pb2.CommandResponse(
                success=True, 
                message=str(response)
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pikvm_service_pb2.CommandResponse(
                success=False, 
                message=str(e)
            )

    def SwitchGPIO(self, request, context):
        """
        Handle GPIO switch gRPC request
        """
        try:
            # Call GPIO switch
            response = self.controller.switch_gpio(
                channel=request.channel, 
                state=request.state, 
                wait=request.wait
            )
            
            return pikvm_service_pb2.CommandResponse(
                success=True, 
                message=str(response)
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pikvm_service_pb2.CommandResponse(
                success=False, 
                message=str(e)
            )

    def PulseGPIO(self, request, context):
        """
        Handle GPIO pulse gRPC request
        """
        try:
            # Call GPIO pulse
            response = self.controller.pulse_gpio(
                channel=request.channel, 
                delay=request.pulse_delay if request.pulse_delay > 0 else None, 
                wait=request.wait
            )
            
            return pikvm_service_pb2.CommandResponse(
                success=True, 
                message=str(response)
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pikvm_service_pb2.CommandResponse(
                success=False, 
                message=str(e)
            )

def serve(port=50051):
    """
    Start the gRPC server
    
    :param port: Port to run the gRPC server on
    """
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)

    # Create gRPC server
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    
    # Add service to server
    pikvm_service_pb2_grpc.add_PikvmControlServiceServicer_to_server(
        PikvmControlService(), server
    )
    
    # Add insecure port
    server.add_insecure_port(f'[::]:{port}')
    
    # Start server
    logger.info(f"Starting gRPC server on port {port}")
    server.start()
    
    # Keep server running
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Server stopped")
        server.stop(0)
    except Exception as e:
        logger.error(f"gRPC server error: {e}")
        server.stop(0)

if __name__ == '__main__':
    serve()
