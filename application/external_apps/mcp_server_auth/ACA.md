# ADA.md

## Step 1: Set Azure defaults

az config set defaults.group=GREGU2
az config set defaults.location=eastus

## Step 2: Create and configure Azure Container Registry (if not already done)

az acr create --resource-group GREGU2 --name gregsacr2 --sku Basic
az acr login --name gregsacr2
az acr update -n gregsacr2 --admin-enabled true
az acr credential show --name gregsacr2 --query username --output tsv
az acr credential show --name gregsacr2 --query passwords[0].value --output tsv

## Step 3: Build and push Docker image with proper configuration

docker build -t gregsacr2.azurecr.io/simplechat-mcp-server:latest .
docker push gregsacr2.azurecr.io/simplechat-mcp-server:latest

## Step 4: Deploy to Container Apps with HTTPS and proper port configuration

az containerapp up `
    --name gregscontainerapp2 `
    --resource-group GREGU2 `
    --image gregsacr2.azurecr.io/simplechat-mcp-server:latest `
    --target-port 8084 `
    --ingress external `
    --environment development `
    --env-vars `
        "MCP_SERVER_HOST=0.0.0.0" `
        "MCP_SERVER_PORT=8084" `
        "OAUTH_CALLBACK_PORT=8080" `
        "MCP_TRANSPORT_TYPE=http" `
        "REDIRECT_URI=https://gregscontainerapp2.jollystone-4d8e996b.eastus.azurecontainerapps.io/auth/callback" `
    --query properties.latestRevisionFqdn

## Step 5: Enable Managed Identity for ACA and then assign ACRPULL IAM to Managed Identity

Enable managed identity and assign iam to ACR from ACA

## Step 6: Configure additional environment variables for Entra ID

az containerapp update `
    --name gregscontainerapp2 `
    --resource-group GREGU2 `
    --set-env-vars `
        "TENANT_ID=your-tenant-id" `
        "CLIENT_ID=your-client-id" `
        "CLIENT_SECRET=your-client-secret" `
        "BACKEND_API_URL=your-backend-api-url" `
        "API_SCOPES=your-api-scopes" `
        "APP_TYPE=confidential" `
        "MCP_SERVER_NAME=SimpleChat MCP Server" `
        "MCP_SERVER_VERSION=1.0.0" `
        "TOKEN_CACHE_PATH=/app/token_cache.json"
