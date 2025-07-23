# SimpleChat MCP Server - Docker & Azure Container Apps Deployment

This guide covers deploying the SimpleChat MCP Server using Docker and Azure Container Apps for production testing and usage.

## 🚀 Quick Start

### Prerequisites

- **Docker**: Install [Docker Desktop](https://www.docker.com/products/docker-desktop)
- **Azure CLI**: Install [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
- **Azure Container Registry** (recommended) or other container registry
- **SimpleChat instance** with valid bearer token

### 1. Environment Setup

```bash
# Copy and configure environment variables
cp .env.example .env

# Edit .env with your SimpleChat details
SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL=https://your-simplechat-instance.com
SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN=your-bearer-token-here
SIMPLECHAT_MCP_LOG_LEVEL=INFO
```

### 2. Local Docker Testing

```bash
# Build and test locally
docker-compose up --build

# Or use the build script
./build-docker.sh test
```

### 3. Azure Container Registry Setup

```bash
# Create Azure Container Registry
az acr create --resource-group myResourceGroup --name myregistry --sku Basic

# Login to registry
az acr login --name myregistry
```

### 4. Build and Deploy

```bash
# Set registry details
export DOCKER_REGISTRY=myregistry.azurecr.io
export SIMPLECHAT_BASE_URL=https://your-simplechat-instance.com
export SIMPLECHAT_BEARER_TOKEN=your-bearer-token

# Build and push image
./build-docker.sh

# Deploy to Azure Container Apps
./deploy-azure.sh
```

## 📦 Docker Configuration

### Dockerfile Features

- **Base Image**: Python 3.11 slim for optimal size
- **Security**: Runs as non-root user
- **Health Checks**: Built-in liveness and readiness probes
- **Environment**: Configurable via environment variables
- **Port**: Exposes port 8080 for health checks

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL` | SimpleChat API base URL | `http://localhost:5000` | Yes |
| `SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN` | Bearer token for authentication | - | Yes |
| `SIMPLECHAT_MCP_LOG_LEVEL` | Logging level | `INFO` | No |
| `SIMPLECHAT_MCP_HEALTH_PORT` | Health check port | `8080` | No |

### Health Endpoints

- **`/health`**: Liveness probe - checks if server is running
- **`/ready`**: Readiness probe - checks if server is ready to accept requests

## ☁️ Azure Container Apps Deployment

### Architecture

```
┌─────────────────────────────────────┐
│ Azure Container Apps Environment    │
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ SimpleChat MCP Server           │ │
│ │ - FastMCP 2.0                   │ │
│ │ - Health endpoints              │ │
│ │ - Auto-scaling                  │ │
│ │ - Log Analytics integration     │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

### Resource Configuration

- **CPU**: 0.25 cores
- **Memory**: 0.5 GB
- **Scaling**: 1-3 replicas based on CPU utilization (70% threshold)
- **Networking**: Internal ingress (not externally accessible)
- **Logging**: Integrated with Azure Log Analytics

### Deployment Templates

Two deployment options are provided:

1. **Bicep Template** (`azure-container-app.bicep`) - Modern Azure Resource Manager
2. **ARM Template** (`azure-container-app.json`) - Traditional JSON template

### Deployment Script Features

The `deploy-azure.sh` script provides:

- ✅ **Prerequisites checking** (Azure CLI, login status, environment variables)
- ✅ **Resource group creation**
- ✅ **Automatic template selection** (Bicep preferred, ARM fallback)
- ✅ **Deployment status monitoring**
- ✅ **FQDN and endpoint discovery**
- ✅ **Log viewing capabilities**

## 🛠️ Manual Deployment Steps

### 1. Create Resource Group

```bash
az group create --name simplechat-mcp-rg --location eastus
```

### 2. Build and Push Image

```bash
# Build image
docker build -t myregistry.azurecr.io/simplechat-mcp-server:latest .

# Push to registry
docker push myregistry.azurecr.io/simplechat-mcp-server:latest
```

### 3. Deploy with Bicep

```bash
az deployment group create \
  --resource-group simplechat-mcp-rg \
  --template-file azure-container-app.bicep \
  --parameters \
    containerImage=myregistry.azurecr.io/simplechat-mcp-server:latest \
    simpleChatBaseUrl=https://your-instance.com \
    simpleChatBearerToken=your-token
```

### 4. Deploy with ARM Template

```bash
az deployment group create \
  --resource-group simplechat-mcp-rg \
  --template-file azure-container-app.json \
  --parameters \
    containerImage=myregistry.azurecr.io/simplechat-mcp-server:latest \
    simpleChatBaseUrl=https://your-instance.com \
    simpleChatBearerToken=your-token
```

## 🔍 Monitoring and Troubleshooting

### View Logs

```bash
# Using deployment script
./deploy-azure.sh show-logs

# Using Azure CLI directly
az containerapp logs show \
  --name simplechat-mcp-server \
  --resource-group simplechat-mcp-rg \
  --follow
```

### Check Health Status

```bash
# Get container app FQDN
FQDN=$(az containerapp show \
  --name simplechat-mcp-server \
  --resource-group simplechat-mcp-rg \
  --query "properties.latestRevisionFqdn" \
  --output tsv)

# Test health endpoints
curl https://$FQDN/health
curl https://$FQDN/ready
```

### Common Issues

| Issue | Solution |
|-------|----------|
| Container fails to start | Check bearer token is valid and environment variables are set |
| Health checks failing | Verify SimpleChat base URL is accessible from container |
| Authentication errors | Ensure bearer token has `ExternalApi` role |
| Image pull errors | Verify container registry permissions and image exists |

## 🧪 Testing Deployment

### 1. MCP Client Configuration

Create an MCP client configuration pointing to your deployed server:

```json
{
  "mcpServers": {
    "simplechat-azure": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--env", "SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL=https://your-instance.com",
        "--env", "SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN=your-token",
        "myregistry.azurecr.io/simplechat-mcp-server:latest"
      ]
    }
  }
}
```

### 2. Test Container Locally

```bash
# Run container with your environment
docker run -it --rm \
  --env SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL=https://your-instance.com \
  --env SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN=your-token \
  -p 8080:8080 \
  myregistry.azurecr.io/simplechat-mcp-server:latest
```

### 3. Validate Tools

Test individual MCP tools:

```bash
# Test token validation
echo '{"tool": "test_token", "arguments": {}}' | docker run -i --rm \
  --env SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL=https://your-instance.com \
  --env SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN=your-token \
  myregistry.azurecr.io/simplechat-mcp-server:latest
```

## 🔐 Security Considerations

### Container Security

- ✅ **Non-root user**: Container runs as `mcpuser`
- ✅ **Minimal base image**: Python 3.11 slim reduces attack surface
- ✅ **No shell access**: Container doesn't include unnecessary packages
- ✅ **Secret management**: Bearer tokens stored as Azure Container Apps secrets

### Network Security

- ✅ **Internal networking**: Container Apps use internal networking by default
- ✅ **HTTPS**: All communication with SimpleChat uses HTTPS
- ✅ **No external exposure**: MCP server not exposed to internet

### Access Control

- ✅ **Bearer token authentication**: All API calls require valid token
- ✅ **Role-based access**: Token must have `ExternalApi` role
- ✅ **Environment isolation**: Each deployment has isolated configuration

## 📈 Performance and Scaling

### Auto-scaling Configuration

- **Minimum replicas**: 1 (always available)
- **Maximum replicas**: 3 (handles increased load)
- **Scaling trigger**: CPU utilization > 70%
- **Scale-down delay**: Gradual scale-down to handle load fluctuations

### Resource Optimization

- **CPU**: 0.25 cores sufficient for typical MCP workloads
- **Memory**: 0.5 GB accommodates FastMCP and HTTP client
- **Startup time**: ~10-15 seconds with health check validation

### Monitoring Metrics

Available through Azure Monitor:

- **Request count**: Number of MCP tool invocations
- **Response time**: Tool execution latency
- **Error rate**: Failed tool executions
- **Resource utilization**: CPU and memory usage

## 🎯 Production Deployment Checklist

- [ ] **Environment variables configured** in production
- [ ] **Container registry access** configured
- [ ] **Resource group and naming** follow organizational standards
- [ ] **Monitoring and alerting** set up in Azure Monitor
- [ ] **Backup and disaster recovery** plan defined
- [ ] **Security review** completed
- [ ] **Load testing** performed
- [ ] **Documentation** updated with production specifics

## 🔄 CI/CD Integration

### GitHub Actions Example

```yaml
name: Deploy SimpleChat MCP Server

on:
  push:
    branches: [main]
    paths: ['application/mcp_server/**']

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Login to Azure
        uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}
      
      - name: Build and deploy
        run: |
          cd application/mcp_server
          export DOCKER_REGISTRY=${{ secrets.REGISTRY_NAME }}.azurecr.io
          export SIMPLECHAT_BASE_URL=${{ secrets.SIMPLECHAT_BASE_URL }}
          export SIMPLECHAT_BEARER_TOKEN=${{ secrets.SIMPLECHAT_BEARER_TOKEN }}
          ./build-docker.sh
          ./deploy-azure.sh
```

## 📞 Support and Troubleshooting

For deployment issues:

1. **Check logs**: Use `./deploy-azure.sh show-logs` or Azure Portal
2. **Verify configuration**: Ensure all environment variables are correct
3. **Test connectivity**: Verify network access to SimpleChat instance
4. **Resource limits**: Check if resource quotas are exceeded
5. **Authentication**: Validate bearer token and permissions

The deployment provides a complete, production-ready MCP server environment with comprehensive monitoring, security, and scalability features.