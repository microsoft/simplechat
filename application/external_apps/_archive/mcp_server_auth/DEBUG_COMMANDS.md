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
