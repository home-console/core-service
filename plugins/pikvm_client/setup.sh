#!/bin/bash

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

print_status() {
    echo -e "${GREEN}[✓] $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}[!] $1${NC}"
}

install_rust() {
    if ! command -v rustc &> /dev/null; then
        print_warning "Rust not found. Installing Rust..."
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
        source "$HOME/.cargo/env"
        print_status "Rust installed successfully"
    else
        print_status "Rust is already installed"
    fi
}

create_venvs() {
    cd "$PROJECT_DIR"

    # Install Rust if not present
    install_rust

    # Create virtual environment
    python3 -m venv .venv
    source .venv/bin/activate

    # Upgrade pip and setuptools
    pip install --upgrade pip setuptools wheel

    # Install requirements
    pip install -r requirements.txt

    print_status "Virtual environment created and dependencies installed"
}

generate_grpc_code() {
    source .venv/bin/activate
    python generate_grpc.py
    print_status "gRPC code generated"
}

main() {
    clear
    echo "🚀 Setting up PIKVMClientService Microservice"
    
    create_venvs
    generate_grpc_code
    
    echo -e "\n${GREEN}✨ Setup completed successfully! ✨${NC}"
}

main