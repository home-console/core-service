#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess

def generate_grpc_code():
    """
    Generate gRPC code from .proto files
    """
    # Determine paths
    current_dir = os.path.dirname(os.path.abspath(__file__))
    proto_dir = os.path.join(current_dir, 'src/protos')
    output_dir = os.path.join(current_dir, 'src/generated')
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Find all .proto files
    proto_files = [f for f in os.listdir(proto_dir) if f.endswith('.proto')]
    
    if not proto_files:
        print("No .proto files found in the protos directory.")
        return
    
    # Generate gRPC code for each .proto file
    for proto_file in proto_files:
        full_proto_path = os.path.join(proto_dir, proto_file)
        
        # Run protoc command
        cmd = [
            'python', '-m', 'grpc_tools.protoc',
            f'-I{proto_dir}',
            f'--python_out={output_dir}',
            f'--grpc_python_out={output_dir}',
            full_proto_path
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"Successfully generated gRPC code for {proto_file}")
        except subprocess.CalledProcessError as e:
            print(f"Error generating gRPC code for {proto_file}:")
            print(e.stderr)
            continue
    
    # Ensure generated files are in the correct location
    for file_name in os.listdir(output_dir):
        if file_name.endswith(('_pb2.py', '_pb2_grpc.py')):
            # Move to src/generated if needed
            generated_dir = os.path.join(current_dir, 'src', 'generated')
            os.makedirs(generated_dir, exist_ok=True)
            
            src_path = os.path.join(output_dir, file_name)
            dst_path = os.path.join(generated_dir, file_name)
            
            try:
                shutil.move(src_path, dst_path)
                print(f"Moved {file_name} to {dst_path}")
            except Exception as e:
                print(f"Error moving {file_name}: {e}")

def main():
    """
    Main entry point for gRPC code generation
    """
    try:
        generate_grpc_code()
    except Exception as e:
        print(f"Unexpected error during gRPC code generation: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
