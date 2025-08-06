# ADA.md

## Step 1: Set Azure defaults

az config set defaults.group=GREGU
az config set defaults.location=eastus

## Step 2: Create and configure Azure Container Registry (if not already done)

az acr create --resource-group GREGU --name gregsacr1 --sku Basic
az acr login --name gregsacr1
az acr update -n gregsacr1 --admin-enabled true
az acr credential show --name gregsacr1 --query username --output tsv
az acr credential show --name gregsacr1 --query passwords[0].value --output tsv

## Step 3: Build and push Docker image with proper configuration

docker build -t gregsacr1.azurecr.io/simplechat-mcp-server:latest .
docker push gregsacr1.azurecr.io/simplechat-mcp-server:latest

## Step 4: Deploy to Container Apps with HTTPS and proper port configuration

az containerapp up `
--name gregscontainerapp2 `
--resource-group GREGU `
--image gregsacr1.azurecr.io/simplechat-mcp-server:latest `
--target-port 8084 `
--ingress external `
--environment development `
--env-vars `
    "AZURE_CLIENT_ID=22961fbc-e723-4a13-bd92-ddd83add0794" `
    "AZURE_TENANT_ID=7d887458-fb0d-40bf-adb3-084d875f65db" `
    "REDIRECT_URI=http://0.0.0.0/auth/callback" `
    "SERVER_HOST=0.0.0.0" `
    "SERVER_PORT=8084" `
    "BACKEND_API_BASE_URL=https://127.0.0.1:5443/" `
    "CUSTOM_API_SCOPE=22961fbc-e723-4a13-bd92-ddd83add0794/.default" `
    "TOKEN_CACHE_FILE=token_cache.json" `
--query properties.latestRevisionFqdn

## Step 5: Enable Managed Identity for ACA and then assign ACRPULL IAM to Managed Identity

Enable managed identity and assign iam to ACR from ACA

## Step 6: Configure additional environment variables for Entra ID

az containerapp update `
    --name gregscontainerapp2 `
    --resource-group GREGU `
    --image gregsacr1.azurecr.io/simplechat-mcp-server:latest `
    --set-env-vars `
        "TENANT_ID=7d887458-fb0d-40bf-adb3-084d875f65db" `
        "CLIENT_ID=22961fbc-e723-4a13-bd92-ddd83add0794" `
        "REDIRECT_URI=https://gregscontainerapp2.jollystone-4d8e996b.eastus.azurecontainerapps.io:444/auth/callback" `
        "CLIENT_SECRET=bogus" `
        "API_SCOPES=22961fbc-e723-4a13-bd92-ddd83add0794/.default" `
        "BACKEND_API_URL=https://127.0.0.1:5443/" `
        "TOKEN_CACHE_PATH=/app/token_cache.json" `
        "MCP_SERVER_NAME=SimpleChat MCP Server ACA" `
        "MCP_SERVER_VERSION=1.0.99" `
        "MCP_SERVER_HOST=0.0.0.0" `
        "MCP_SERVER_PORT=8084" `
        "OAUTH_CALLBACK_PORT=8080" `
        "MCP_TRANSPORT_TYPE=http" `
        "APP_TYPE=public"

## additional commands

az containerapp list --output table
az containerapp list --resource-group <RESOURCE_GROUP_NAME> --output table
