# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with trusted hosts for SSL issues
RUN pip install --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org --no-cache-dir -r requirements.txt

# Copy application files
COPY simplechat-mcp-server.py .
COPY .env .

# Create non-root user for security
# RUN groupadd -r mcpuser && useradd -r -g mcpuser mcpuser
# RUN chown -R mcpuser:mcpuser /app
# USER mcpuser

# Environment variables with defaults (bearer token should be set at runtime)
# ENV SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL="http://localhost:5000"
# ENV SIMPLECHAT_MCP_LOG_LEVEL="INFO"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; from simplechat_mcp_server import config; sys.exit(0 if config.simplechat_bearer_token else 1)"

# Expose port for health checks
EXPOSE 8080

# Default command runs the MCP server
CMD ["python", "simplechat-mcp-server.py"]