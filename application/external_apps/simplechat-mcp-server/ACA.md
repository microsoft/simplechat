# ADA.md

## Step 1: Set Azure defaults

az cache purge
az account clear
az cloud set --name AzureCloud
az login

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
--name gregscontainerapp1 `
--resource-group GREGU `
--image gregsacr1.azurecr.io/simplechat-mcp-server:latest `
--target-port 8084 `
--ingress external `
--environment development `
--env-vars `
    "AZURE_CLIENT_ID=22961fbc-e723-4a13-bd92-ddd83add0794" `
    "AZURE_TENANT_ID=7d887458-fb0d-40bf-adb3-084d875f65db" `
    "REDIRECT_URI=https://gregscontainerapp1.grayforest-fd321039.eastus.azurecontainerapps.io/auth/callback" `
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
    --name gregscontainerapp1 `
    --resource-group GREGU `
    --image gregsacr1.azurecr.io/simplechat-mcp-server:latest `
    --set-env-vars `
        "AZURE_CLIENT_ID=22961fbc-e723-4a13-bd92-ddd83add0794" `
        "AZURE_TENANT_ID=7d887458-fb0d-40bf-adb3-084d875f65db" `
        "REDIRECT_URI=https://gregscontainerapp1.grayforest-fd321039.eastus.azurecontainerapps.io/auth/callback" `
        "SERVER_HOST=0.0.0.0" `
        "SERVER_PORT=8084" `
        "BACKEND_API_BASE_URL=https://127.0.0.1:5443/" `
        "CUSTOM_API_SCOPE=22961fbc-e723-4a13-bd92-ddd83add0794/.default" `
        "TOKEN_CACHE_FILE=token_cache.json"

## additional commands

az containerapp list --output table
az containerapp list --resource-group <RESOURCE_GROUP_NAME> --output table

Browse to your container app at: http://gregscontainerapp1.grayforest-fd321039.eastus.azurecontainerapps.io/mcp/

Stream logs for your container with: az containerapp logs show -n gregscontainerapp1 -g GREGU

See full output using: az containerapp show -n gregscontainerapp1 -g GREGU