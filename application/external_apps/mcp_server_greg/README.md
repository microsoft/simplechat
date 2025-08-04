# SimpleChat MCP Server - by Greg

## Debug commands

npx @modelcontextprotocol/inspector

fastmcp run .\simplechat-mcp-server.py

fastmcp run .\simplechat-mcp-server.py --transport streamable-http --port 8080 --host 127.0.0.1

fastmcp run .\simplechat-mcp-server.py --transport http --port 8080 --host 127.0.0.1

cd C:\tempAaronMcp\simplechat\application\external_apps\mcp_server_greg
fastmcp run .\simplechat-mcp-server.py --transport http --port 8080 --host 127.0.0.1

npx @modelcontextprotocol/inspector http://127.0.0.1:8080/mcp/

## Deploy to Azure ACA

``` cli
az acr create --resource-group <your-resource-group> --name <your-acr-name> --sku Basic
az acr login --name <your-acr-name>

docker build -t <your-acr-name>.azurecr.io/fastmcp-server:latest .
docker push <your-acr-name>.azurecr.io/fastmcp-server:latest

az containerapp up \
    --name <your-container-app-name> \
    --resource-group <your-resource-group> \
    --image <your-acr-name>.azurecr.io/fastmcp-server:latest \
    --target-port 8000 \
    --ingress external \
    --environment <your-aca-environment-name> \
    --query properties.latestRevisionFqdn

az containerapp secret set --name <your-container-app-name> --resource-group <your-resource-group> --secrets my-api-key=YOUR_ACTUAL_API_KEY
az containerapp update --name <your-container-app-name> --resource-group <your-resource-group> --set-env-vars "MY_API_KEY=secretref:my-api-key"
```
