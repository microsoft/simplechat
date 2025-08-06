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
COPY auth.py .
COPY config.py .
COPY api_client.py .
COPY server.py .

# Set default environment variables for Container Apps
ENV AZURE_CLIENT_ID=22961fbc-e723-4a13-bd92-ddd83add0794 \
    AZURE_TENANT_ID=7d887458-fb0d-40bf-adb3-084d875f65db \
    REDIRECT_URI=https://gregscontainerapp1.grayforest-fd321039.eastus.azurecontainerapps.io/auth/callback \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8084 \
    BACKEND_API_BASE_URL=https://127.0.0.1:5443/ \
    CUSTOM_API_SCOPE=22961fbc-e723-4a13-bd92-ddd83add0794/.default \
    TOKEN_CACHE_FILE=token_cache.json

# 8084 for MCP server (default)
EXPOSE 8084

# Create token cache directory
RUN mkdir -p /app/cache

CMD ["python", "server.py"]
