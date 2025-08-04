# Use Python 3.12 slim image as base
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY auth.py .
COPY config.py .
COPY server.py .
COPY docker_entrypoint.py .
COPY .env.example .

# Create directories for runtime data
RUN mkdir -p /app/data

# Set default environment variables to prevent startup errors
ENV TENANT_ID="7d887458-fb0d-40bf-adb3-084d875f65db" \
    CLIENT_ID="22961fbc-e723-4a13-bd92-ddd83add0794" \
    BACKEND_API_URL="https://127.0.0.1:5443/" \
    API_SCOPES="22961fbc-e723-4a13-bd92-ddd83add0794/.default" \
    OAUTH_CALLBACK_PORT=8080 \
    MCP_SERVER_HOST=0.0.0.0 \
    MCP_SERVER_PORT=8084 \
    MCP_TRANSPORT_TYPE=http

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash mcpuser && \
    chown -R mcpuser:mcpuser /app
USER mcpuser

# Expose the ports
# 8084 for MCP server (default)
# 8080 for OAuth callback (default)
EXPOSE 8084 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import socket; sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); sock.settimeout(5); result = sock.connect_ex(('localhost', 8084)); sock.close(); exit(0 if result == 0 else 1)"

# Default command
CMD ["python", "docker_entrypoint.py"]

# Docker commands for building and running the container
# Build the Docker image
# docker build -t mcp-entra-auth-server:latest .
#
# Stop and remove the existing container
# docker stop mcp-entra-auth-server
# docker rm mcp-entra-auth-server
#
# Run the container
# docker run -d --name mcp-entra-auth-server -p 8084:8084 -p 8080:8080 --env-file .env -v "%cd%\data:/app/data" --restart unless-stopped mcp-entra-auth-server:latest
