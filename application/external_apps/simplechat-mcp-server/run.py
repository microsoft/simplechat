#!/usr/bin/env python3
"""
Startup script for FastMCP OAuth Server
"""

import os
import sys
from pathlib import Path

def load_env_file():
    """Load environment variables from .env file"""
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    os.environ[key] = value
        print("Loaded environment variables from .env file")
    else:
        print("No .env file found. Using environment variables or defaults.")

def check_configuration():
    """Check if required configuration is present"""
    required_vars = ["AZURE_CLIENT_ID", "AZURE_TENANT_ID"]
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set these in your .env file or environment variables.")
        print("See .env.example for reference.")
        return False
    
    return True

def main():
    """Main startup function"""
    print("Starting FastMCP OAuth Server...")
    
    # Load environment variables
    load_env_file()
    
    # Check configuration
    if not check_configuration():
        sys.exit(1)
    
    # Import and run server
    try:
        from server import main as server_main
        server_main()
    except ImportError as e:
        print(f"Error importing server: {e}")
        print("Make sure all dependencies are installed: pip install -r requirements.txt")
        sys.exit(1)

if __name__ == "__main__":
    main()
