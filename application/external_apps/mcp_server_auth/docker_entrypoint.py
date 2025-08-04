#!/usr/bin/env python3
"""
Docker entrypoint script for MCP server.
Provides better error handling and validation for Docker deployments.
"""

import os
import sys

def check_environment():
    """Check if required environment variables are set."""
    required_vars = {
        'TENANT_ID': 'Azure tenant ID',
        'CLIENT_ID': 'Azure application client ID', 
        'BACKEND_API_URL': 'Backend API base URL'
    }
    
    missing_vars = []
    for var, description in required_vars.items():
        value = os.getenv(var, '').strip()
        if not value:
            missing_vars.append(f"  {var}: {description}")
    
    if missing_vars:
        print("❌ Missing required environment variables:")
        print("\n".join(missing_vars))
        print("\nPlease provide these variables through:")
        print("  - Docker run: -e TENANT_ID=your-value")
        print("  - Docker compose: environment section")
        print("  - .env file: --env-file .env")
        print("\nExample .env file:")
        print("TENANT_ID=your-tenant-id")
        print("CLIENT_ID=your-client-id")
        print("CLIENT_SECRET=your-client-secret")
        print("BACKEND_API_URL=https://your-api.com/")
        print("API_SCOPES=api://your-client-id/.default")
        return False
    
    return True

def main():
    """Main entrypoint."""
    print("🐳 Starting MCP Entra Auth Server...")
    
    # Check environment
    if not check_environment():
        sys.exit(1)
    
    print("✅ Environment validation passed")
    
    # Import and run the server
    try:
        from server import main as server_main
        server_main()
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
