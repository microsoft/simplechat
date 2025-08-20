FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application code
COPY .env.docker .env
COPY auth.py .
COPY config.py .
COPY server.py .

# Set default environment variables for Container Apps
ENV MCP_SERVER_HOST=0.0.0.0 \
    MCP_SERVER_PORT=8084 \
    OAUTH_CALLBACK_PORT=8080 \
    MCP_TRANSPORT_TYPE=http

# 8084 for MCP server (default)
# 8080 for OAuth callback (default)
EXPOSE 8084 8080

# Create token cache directory
RUN mkdir -p /app/cache

CMD ["python", "server.py"]
