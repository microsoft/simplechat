#!/bin/bash
# Docker build and run script for MCP Entra Auth Server

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🐳 MCP Entra Auth Server - Docker Build & Run Script${NC}"
echo "================================================"

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ Error: .env file not found${NC}"
    echo "Please create a .env file based on .env.example"
    exit 1
fi

# Create data directory if it doesn't exist
mkdir -p data

# Function to build the Docker image
build_image() {
    echo -e "${YELLOW}🔨 Building Docker image...${NC}"
    docker build -t mcp-entra-auth-server:latest .
    echo -e "${GREEN}✅ Docker image built successfully${NC}"
}

# Function to run the container
run_container() {
    echo -e "${YELLOW}🚀 Starting MCP server container...${NC}"
    
    # Stop and remove existing container if it exists
    docker stop mcp-entra-auth-server 2>/dev/null || true
    docker rm mcp-entra-auth-server 2>/dev/null || true
    
    # Run the container
    docker run -d \
        --name mcp-entra-auth-server \
        -p 8084:8084 \
        -p 8080:8080 \
        --env-file .env \
        -v "$(pwd)/data:/app/data" \
        --restart unless-stopped \
        mcp-entra-auth-server:latest
    
    echo -e "${GREEN}✅ Container started successfully${NC}"
    echo "MCP Server URL: http://localhost:8084/mcp/"
    echo "OAuth Callback URL: http://localhost:8080/auth/callback"
}

# Function to show logs
show_logs() {
    echo -e "${YELLOW}📋 Container logs:${NC}"
    docker logs -f mcp-entra-auth-server
}

# Function to stop the container
stop_container() {
    echo -e "${YELLOW}🛑 Stopping container...${NC}"
    docker stop mcp-entra-auth-server
    docker rm mcp-entra-auth-server
    echo -e "${GREEN}✅ Container stopped${NC}"
}

# Function to show container status
show_status() {
    echo -e "${YELLOW}📊 Container status:${NC}"
    docker ps -a --filter "name=mcp-entra-auth-server"
    
    echo -e "\n${YELLOW}🔍 Health check:${NC}"
    if docker ps --filter "name=mcp-entra-auth-server" --filter "status=running" | grep -q mcp-entra-auth-server; then
        # Test if server is responding
        if curl -s http://localhost:8084 > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Server is healthy and responding${NC}"
        else
            echo -e "${RED}❌ Server is running but not responding${NC}"
        fi
    else
        echo -e "${RED}❌ Container is not running${NC}"
    fi
}

# Main script logic
case "${1:-build}" in
    "build")
        build_image
        ;;
    "run")
        run_container
        ;;
    "start")
        build_image
        run_container
        ;;
    "logs")
        show_logs
        ;;
    "stop")
        stop_container
        ;;
    "status")
        show_status
        ;;
    "restart")
        stop_container
        build_image
        run_container
        ;;
    *)
        echo "Usage: $0 {build|run|start|logs|stop|status|restart}"
        echo ""
        echo "Commands:"
        echo "  build   - Build the Docker image"
        echo "  run     - Run the container (assumes image exists)"
        echo "  start   - Build image and run container"
        echo "  logs    - Show container logs"
        echo "  stop    - Stop and remove container"
        echo "  status  - Show container status and health"
        echo "  restart - Stop, rebuild, and restart container"
        exit 1
        ;;
esac
