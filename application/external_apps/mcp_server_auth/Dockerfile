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

# Set default environment variables to prevent startup errors
# ENV TENANT_ID="7d887458-fb0d-40bf-adb3-084d875f65db" \
#     CLIENT_ID="22961fbc-e723-4a13-bd92-ddd83add0794" \
#     BACKEND_API_URL="https://host.docker.internal:5443/" \
#     API_SCOPES="22961fbc-e723-4a13-bd92-ddd83add0794/.default" \
#     OAUTH_CALLBACK_PORT=8080 \
#     MCP_SERVER_HOST=0.0.0.0 \
#     MCP_SERVER_PORT=8084 \
#     MCP_TRANSPORT_TYPE=http

# 8084 for MCP server (default)
# 8080 for OAuth callback (default)
EXPOSE 8084 8080

CMD ["python", "server.py"]
