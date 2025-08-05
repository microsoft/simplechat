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
cls
az config set defaults.group=GREGU2
az config set defaults.location=eastus
az acr create --resource-group GREGU2 --name gregsacr2 --sku Basic
az acr login --name gregsacr2
az acr update -n gregsacr2 --admin-enabled true
az acr credential show --name gregsacr2 --query username --output tsv
az acr credential show --name gregsacr2 --query passwords[0].value --output tsv

docker build -t gregsacr2.azurecr.io/simplechat-mc-server:latest .
docker push gregsacr2.azurecr.io/simplechat-mc-server:latest

az containerapp up `
    --name gregscontainerapp2 `
    --resource-group GREGU2 `
    --image gregsacr2.azurecr.io/simplechat-mc-server:latest `
    --target-port 8000 `
    --ingress external `
    --environment development `
    --query properties.latestRevisionFqdn

#not needed
#az containerapp secret set --name gregscontainerapp2 --resource-group GREGU2 --secrets my-api-key=YOUR_ACTUAL_API_KEY
#az containerapp update --name gregscontainerapp2 --resource-group GREGU2 --set-env-vars "MY_API_KEY=secretref:my-api-key"

#output
Using resource group 'GREGU2'
Creating ContainerAppEnvironment 'development' in resource group GREGU2
No Log Analytics workspace provided.
Generating a Log Analytics workspace with name "workspace-2iXJt"
Creating Containerapp gregscontainerapp2 in resource group GREGU2
Adding registry password as a secret with name "gregsacr2azurecrio-gregsacr2"

Container app created. Access your app at:
https://gregscontainerapp2.jollystone-4d8e996b.eastus.azurecontainerapps.io/
https://gregscontainerapp2.jollystone-4d8e996b.eastus.azurecontainerapps.io/mcp/
https://gregscontainerapp2.jollystone-4d8e996b.eastus.azurecontainerapps.io:8000/mcp/

Your container app gregscontainerapp2 has been created and deployed! Congrats!

Browse to your container app at: http://gregscontainerapp2.jollystone-4d8e996b.eastus.azurecontainerapps.io 

Stream logs for your container with: az containerapp logs show -n gregscontainerapp2 -g GREGU2

See full output using: az containerapp show -n gregscontainerapp2 -g GREGU2
```

## Mcp inspector

npx @modelcontextprotocol/inspector http://127.0.0.1:8084/mcp/

## Docker

docker build -t rudy:1 .
docker run -p 8084:8084 -p 8080:8080 rudy:1
http://localhost:8084/mcp/

### initialize first and get session id
curl -X POST http://127.0.0.1:8084/mcp/ -H "content-type: application/json" -H "accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}},"id":1}'

### call tools
curl -X POST http://127.0.0.1:8084/mcp/ -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}'

$sessionId must have a session id below.

curl -X POST http://localhost:8000/mcp -Method POST -Headers @{'accept'='application/json, text/event-stream'; 'content-type'='application/json'; 'Mcp-Session-Id'=$sessionId} -Body '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"add","arguments":{"a":10,"b":15}},"id":2}'
