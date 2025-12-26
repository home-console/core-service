#!/usr/bin/env python3
import grpc
import sys
import os

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import generated gRPC modules
import pikvm_service_pb2
import pikvm_service_pb2_grpc

class PikvmGRPCClient:
    def __init__(self, host='localhost', port=50051):
        """
        Initialize gRPC client
        
        :param host: gRPC server host
        :param port: gRPC server port
        """
        # Create channel
        self.channel = grpc.insecure_channel(f'{host}:{port}')
        
        # Create stub
        self.stub = pikvm_service_pb2_grpc.PikvmControlServiceStub(self.channel)

    def power_control(self, action, wait=False):
        """
        Send power control command
        
        :param action: Power action (ON, OFF, OFF_HARD, RESET_HARD)
        :param wait: Wait for operation to complete
        :return: Command response
        """
        request = pikvm_service_pb2.PowerControlRequest(
            action=action,
            wait=wait
        )
        return self.stub.PowerControl(request)

    def button_click(self, button, wait=False):
        """
        Send button click command
        
        :param button: Button type (POWER, POWER_LONG, RESET)
        :param wait: Wait for operation to complete
        :return: Command response
        """
        request = pikvm_service_pb2.ButtonClickRequest(
            button=button,
            wait=wait
        )
        return self.stub.ButtonClick(request)

    def upload_msd_image(self, image_path, image_name=None):
        """
        Upload MSD image
        
        :param image_path: Path to the image file
        :param image_name: Optional custom image name
        :return: Command response
        """
        request = pikvm_service_pb2.MSDUploadRequest(
            image_path=image_path,
            image_name=image_name
        )
        return self.stub.UploadMSDImage(request)

    def switch_gpio(self, channel, state, wait=False):
        """
        Switch GPIO channel
        
        :param channel: GPIO channel
        :param state: GPIO state (0 or 1)
        :param wait: Wait for operation to complete
        :return: Command response
        """
        request = pikvm_service_pb2.GPIOControlRequest(
            channel=channel,
            state=state,
            wait=wait
        )
        return self.stub.SwitchGPIO(request)

    def pulse_gpio(self, channel, pulse_delay=None, wait=False):
        """
        Pulse GPIO channel
        
        :param channel: GPIO channel
        :param pulse_delay: Pulse duration
        :param wait: Wait for operation to complete
        :return: Command response
        """
        request = pikvm_service_pb2.GPIOControlRequest(
            channel=channel,
            pulse_delay=pulse_delay or 0,
            wait=wait
        )
        return self.stub.PulseGPIO(request)

def main():
    """
    Example usage of PiKVM gRPC client
    """
    try:
        # Create client
        client = PikvmGRPCClient()

        # Example: Power on
        power_response = client.power_control(
            action=pikvm_service_pb2.ON, 
            wait=True
        )
        print("Power Control Response:", power_response.success, power_response.message)

        # Example: Button click
        button_response = client.button_click(
            button=pikvm_service_pb2.POWER, 
            wait=False
        )
        print("Button Click Response:", button_response.success, button_response.message)

    except grpc.RpcError as e:
        print(f"gRPC Error: {e}")

if __name__ == '__main__':
    main()
