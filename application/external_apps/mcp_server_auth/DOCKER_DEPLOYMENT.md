# Docker Deployment Guide

This guide explains how to build and deploy the MCP Entra Auth Server using Docker.

## Prerequisites

- Docker installed and running
- Docker Compose (optional, for easier management)
- Valid Azure Entra ID app registration

## Quick Start

### 1. Configure Environment

Copy `.env.example` to `.env` and configure your Azure Entra ID settings:

```bash
cp .env.example .env
```

Edit `.env` with your values:
```bash
TENANT_ID=your-tenant-id
CLIENT_ID=your-client-id
CLIENT_SECRET=your-client-secret
API_SCOPES=api://your-client-id/.default
BACKEND_API_URL=https://your-backend-api.com/
```

### 2. Build and Run (Easy Way)

#### Windows:
```cmd
docker-run.bat start
```

#### Linux/Mac:
```bash
chmod +x docker-run.sh
./docker-run.sh start
```

### 3. Manual Docker Commands

#### Build the image:
```bash
docker build -t mcp-entra-auth-server:latest .
```

#### Run the container:
```bash
docker run -d \
  --name mcp-entra-auth-server \
  -p 8084:8084 \
  -p 8080:8080 \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  --restart unless-stopped \
  mcp-entra-auth-server:latest
```

### 4. Using Docker Compose

```bash
docker-compose up -d
```

## Port Configuration

- **8084**: MCP Server HTTP endpoint
- **8080**: OAuth callback endpoint

Make sure these ports are available and accessible.

## Environment Variables

| Variable | Description | Required | Example |
|----------|-------------|----------|---------|
| `TENANT_ID` | Azure tenant ID | Yes | `7d887458-...` |
| `CLIENT_ID` | Azure app client ID | Yes | `22961fbc-...` |
| `CLIENT_SECRET` | Azure app client secret | Yes* | `p0M8Q~...` |
| `API_SCOPES` | Scopes for your API | Yes | `api://client-id/.default` |
| `BACKEND_API_URL` | Your backend API URL | Yes | `https://api.example.com/` |
| `MCP_SERVER_HOST` | Server bind address | No | `0.0.0.0` |
| `MCP_SERVER_PORT` | MCP server port | No | `8084` |
| `OAUTH_CALLBACK_PORT` | OAuth callback port | No | `8080` |

*Required for confidential client apps

## Health Checks

The container includes built-in health checks. Check container health:

```bash
docker ps
```

Or use the status command:
```bash
# Windows
docker-run.bat status

# Linux/Mac
./docker-run.sh status
```

## Logs

View container logs:
```bash
# Windows
docker-run.bat logs

# Linux/Mac
./docker-run.sh logs
```

Or directly:
```bash
docker logs -f mcp-entra-auth-server
```

## Data Persistence

The container uses a volume mount for persistent data:
- `./data:/app/data` - Token cache and other persistent data

## Security Considerations

### For Production:

1. **Use secrets management** instead of environment files
2. **Enable TLS/HTTPS** with proper certificates
3. **Use a reverse proxy** (nginx, traefik) for SSL termination
4. **Limit container resources** and set security contexts
5. **Use non-root user** (already configured)
6. **Regular security updates** of base images

### Example with secrets:
```bash
docker run -d \
  --name mcp-entra-auth-server \
  -p 8084:8084 \
  -p 8080:8080 \
  -e TENANT_ID="$(cat /run/secrets/tenant_id)" \
  -e CLIENT_ID="$(cat /run/secrets/client_id)" \
  -e CLIENT_SECRET="$(cat /run/secrets/client_secret)" \
  # ... other environment variables
  mcp-entra-auth-server:latest
```

## Troubleshooting

### Container won't start:
1. Check logs: `docker logs mcp-entra-auth-server`
2. Verify environment variables in `.env`
3. Ensure ports 8084 and 8080 are available
4. Check Docker daemon is running

### Authentication errors:
1. Verify Azure app registration settings
2. Check redirect URI matches: `http://localhost:8080/auth/callback`
3. Ensure correct scopes are configured
4. Verify client secret (if using confidential client)

### Network issues:
1. Check firewall settings
2. Verify port mapping: `-p 8084:8084 -p 8080:8080`
3. Test connectivity: `curl http://localhost:8084`

## Advanced Configuration

### Custom Network:
```bash
# Create custom network
docker network create mcp-network

# Run with custom network
docker run -d \
  --name mcp-entra-auth-server \
  --network mcp-network \
  -p 8084:8084 \
  -p 8080:8080 \
  --env-file .env \
  mcp-entra-auth-server:latest
```

### Resource Limits:
```bash
docker run -d \
  --name mcp-entra-auth-server \
  --memory="512m" \
  --cpus="0.5" \
  -p 8084:8084 \
  -p 8080:8080 \
  --env-file .env \
  mcp-entra-auth-server:latest
```

### Development Mode:
```bash
# Mount source code for development
docker run -d \
  --name mcp-entra-auth-server-dev \
  -p 8084:8084 \
  -p 8080:8080 \
  --env-file .env \
  -v "$(pwd):/app" \
  -e PYTHONDONTWRITEBYTECODE=0 \
  mcp-entra-auth-server:latest
```

## Management Commands

| Action | Windows | Linux/Mac |
|--------|---------|-----------|
| Build | `docker-run.bat build` | `./docker-run.sh build` |
| Start | `docker-run.bat start` | `./docker-run.sh start` |
| Stop | `docker-run.bat stop` | `./docker-run.sh stop` |
| Logs | `docker-run.bat logs` | `./docker-run.sh logs` |
| Status | `docker-run.bat status` | `./docker-run.sh status` |
| Restart | `docker-run.bat restart` | `./docker-run.sh restart` |
