@echo off
REM Docker build and run script for MCP Entra Auth Server (Windows)

setlocal EnableDelayedExpansion

echo 🐳 MCP Entra Auth Server - Docker Build ^& Run Script
echo ================================================

REM Check if .env file exists
if not exist ".env" (
    echo ❌ Error: .env file not found
    echo Please create a .env file based on .env.example
    exit /b 1
)

REM Create data directory if it doesn't exist
if not exist "data" mkdir data

REM Parse command line argument
set "COMMAND=%~1"
if "%COMMAND%"=="" set "COMMAND=build"

if "%COMMAND%"=="build" goto :build
if "%COMMAND%"=="run" goto :run
if "%COMMAND%"=="start" goto :start
if "%COMMAND%"=="logs" goto :logs
if "%COMMAND%"=="stop" goto :stop
if "%COMMAND%"=="status" goto :status
if "%COMMAND%"=="restart" goto :restart
goto :usage

:build
echo 🔨 Building Docker image...
docker build -t mcp-entra-auth-server:latest .
if %ERRORLEVEL% neq 0 (
    echo ❌ Failed to build Docker image
    exit /b 1
)
echo ✅ Docker image built successfully
goto :end

:run
echo 🚀 Starting MCP server container...

REM Stop and remove existing container if it exists
docker stop mcp-entra-auth-server >nul 2>&1
docker rm mcp-entra-auth-server >nul 2>&1

REM Run the container
docker run -d ^
    --name mcp-entra-auth-server ^
    -p 8084:8084 ^
    -p 8080:8080 ^
    --env-file .env ^
    -v "%cd%\data:/app/data" ^
    --restart unless-stopped ^
    mcp-entra-auth-server:latest

if %ERRORLEVEL% neq 0 (
    echo ❌ Failed to start container
    exit /b 1
)

echo ✅ Container started successfully
echo MCP Server URL: http://127.0.0.1:8084/mcp/
echo OAuth Callback URL: http://127.0.0.1:8080/auth/callback
goto :end

:start
call :build
if %ERRORLEVEL% neq 0 exit /b 1
call :run
goto :end

:logs
echo 📋 Container logs:
docker logs -f mcp-entra-auth-server
goto :end

:stop
echo 🛑 Stopping container...
docker stop mcp-entra-auth-server
docker rm mcp-entra-auth-server
echo ✅ Container stopped
goto :end

:status
echo 📊 Container status:
docker ps -a --filter "name=mcp-entra-auth-server"

echo.
echo 🔍 Health check:
docker ps --filter "name=mcp-entra-auth-server" --filter "status=running" | findstr mcp-entra-auth-server >nul
if %ERRORLEVEL% equ 0 (
    REM Test if server is responding
    curl -s http://127.0.0.1:8084 >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        echo ✅ Server is healthy and responding
    ) else (
        echo ❌ Server is running but not responding
    )
) else (
    echo ❌ Container is not running
)
goto :end

:restart
call :stop
call :build
if %ERRORLEVEL% neq 0 exit /b 1
call :run
goto :end

:usage
echo Usage: %0 {build^|run^|start^|logs^|stop^|status^|restart}
echo.
echo Commands:
echo   build   - Build the Docker image
echo   run     - Run the container (assumes image exists)
echo   start   - Build image and run container
echo   logs    - Show container logs
echo   stop    - Stop and remove container
echo   status  - Show container status and health
echo   restart - Stop, rebuild, and restart container
exit /b 1

:end
endlocal
