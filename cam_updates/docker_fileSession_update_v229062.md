# Runtime Session & Permission Changes (Version 0.229.062)

This README explains the recent changes made to `app.py`, `config.py`, and the `Dockerfile` to fix Docker container permission issues and runtime session initialization failures. The goal was to make the application run reliably both **with** code and container Azure App Service Deployments, **without** breaking current session functionality.

## Why The Change Was Needed
When the container was deployed to Azure App Service, it crashed with:
```
PermissionError: [Errno 13] Permission denied: '/app/flask_session'
```
The app ran as a non-root user (`nonroot`), and Flask-Session (filesystem backend) tried to create `/app/flask_session`, which wasn't writable. This required fixing the Docker container's permission structure to properly handle session storage. There were also three duplicated blocks of session initialization logic in `app.py` that caused runtime issues when the container was deployed to App Service.

## Summary of Changes
| File | What Changed | Why |
|------|--------------|-----|
| `config.py` | Added `SESSION_FILE_DIR` (defaults to `/app/flask_session`). | Ensures filesystem session storage uses a properly permissioned directory inside the container; tracks release.
| `app.py` | Created a single `configure_sessions(settings)` helper. Removed three duplicated Redis/filesystem setup blocks. Ensured session directory is created early if using filesystem sessions. | Eliminates duplication, improves reliability, keeps logic in one place, supports Redis or filesystem seamlessly.
| `Dockerfile` | Builder stage runs as `root` to create venv, install deps, and create/permission `/app/flask_session`. Final stage copies the pre-permissioned directory. | Ensures privileged steps (install/build/permission) succeed in builder, while final container follows least-privilege with proper session directory permissions.

## How Session Selection Now Works
1. Admin enables Redis in settings:
   - If `redis_url` present → Redis backend configured (key or managed identity).
   - If enabled but URL missing → falls back to filesystem with a log message.
2. Redis not enabled → filesystem backend using `SESSION_FILE_DIR` (default `/app/flask_session`).
3. Any unexpected Redis error → graceful fallback to filesystem (no startup crash).

## Container Deployment with Azure CLI

To build and deploy the container image to Azure Container Registry:

1. **Navigate to the project directory:**
   ```bash
   cd simplechat/
   ```

2. **Set environment variables:**
   ```bash
   ACR_NAME="<your-azure-container-registry-name>"
   IMAGE_NAME="simplechat"
   IMAGE_TAG="<version-tag>"  # Example: v0229062 (remove dots from version)
   ```

3. **Build and push the image:**
   ```bash
   az acr build --registry $ACR_NAME --image $IMAGE_NAME:$IMAGE_TAG -f application/single_app/Dockerfile .
   ```

**Example with actual values:**
```bash
ACR_NAME="mycompanyregistry"
IMAGE_NAME="simplechat"
IMAGE_TAG="v0229062"
az acr build --registry mycompanyregistry --image simplechat:v0229062 -f application/single_app/Dockerfile .
```

## Environment Overrides (Optional)
You can override the session directory:
```
SESSION_FILE_DIR=/home/site/wwwroot/flask_session
```
(Useful only if persistent storage is enabled and you intentionally want on-disk sessions without Redis.)

## Benefits
- No more permission errors during container deployment and startup.
- Clear, single place to update session handling.
- Works in both development and Azure environments.
- Easy future extension (e.g., adding diagnostics or health checks for Redis).