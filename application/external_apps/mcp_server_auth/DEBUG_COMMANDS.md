# Debug Commands

ping
get_server_info
check_auth_status
authenticate_user
check_auth_status
get_session
view_sessionid
get_conversations
send_chat_message("25bf1a4e-b6f8-4bb4-957d-b345d8f43c94", "this is greg and large marge")
logout_user

get_access_token
refresh_token

## activate

cd C:\tempAaronMcp\simplechat\application\external_apps\mcp_server_auth\ && .\.venv\Scripts\activate

## fastmcp

fastmcp run .\server.py --transport streamable-http --port 8084 --host 127.0.0.1

## terminate process

netstat -ano | findstr :8084
taskkill /F /PID 27960

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