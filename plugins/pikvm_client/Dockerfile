# Use official Python runtime as base image
FROM python:3.11-slim-bullseye

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=/app

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the entire project
COPY src .

# Generate gRPC code
RUN python -m grpc_tools.protoc \
    -I. \
    --python_out=. \
    --grpc_python_out=. \
    protos/pikvm_service.proto

# Create __init__.py files to make directories packages
RUN touch __init__.py pikvm_service_pb2.py pikvm_service_pb2_grpc.py

# Expose gRPC port
EXPOSE 50051

# Default command to run the application
CMD ["python", "main.py"]