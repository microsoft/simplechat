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
