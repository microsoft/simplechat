# DLP Local Stack Smoke Runbook

## Purpose

Use this runbook to render the DLP admin settings UI against a disposable local Cosmos DB emulator without using Azure-hosted Cosmos.

## Ports

- Cosmos gateway: `9081`
- Cosmos health: `9082`
- Cosmos explorer: `1235`
- SimpleChat Flask dev server: `5000`

Port `8081` is intentionally avoided because local proxy tools may already bind it.

## Start Cosmos

```bash
docker run --detach --name simplechat-cosmos-dlp --publish 9081:8081 --publish 9082:8080 --publish 1235:1234 mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-latest --gateway-endpoint localhost:9081
```

## Verify Cosmos

```bash
curl.exe -sS http://localhost:9082/status
```

The health endpoint should show PostgreSQL and Explorer as healthy. When
`--gateway-endpoint localhost:9081` is used, the container-internal gateway
probe can report unhealthy because it checks the host-advertised port from
inside the container. Use the SDK smoke test below as the authoritative check.

## SDK Smoke Test

Run this from the repository root after the Python environment is created:

```bash
.venv\Scripts\python.exe -c "from azure.cosmos import CosmosClient, PartitionKey; key='<cosmos-emulator-key>'; c=CosmosClient('http://localhost:9081/', credential=key); db=c.create_database_if_not_exists('SimpleChatSmoke'); con=db.create_container_if_not_exists(id='smoke', partition_key=PartitionKey(path='/id')); con.upsert_item({'id':'ok','value':1}); print(con.read_item('ok', partition_key='ok')['value'])"
```

Expected output:

```text
1
```

## Python Environment

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r application\single_app\requirements.txt
```

## Start SimpleChat

Set these environment variables before launch:

```dotenv
AZURE_COSMOS_ENDPOINT=http://localhost:9081/
AZURE_COSMOS_KEY=<cosmos-emulator-key>
AZURE_COSMOS_AUTHENTICATION_TYPE=key
NO_PROXY=localhost,127.0.0.1,::1
no_proxy=localhost,127.0.0.1,::1
FLASK_DEBUG=1
SIMPLECHAT_USE_GUNICORN=0
SIMPLECHAT_RUN_BACKGROUND_TASKS=0
DISABLE_FLASK_INSTRUMENTATION=1
CLIENT_ID=local-dev-client
TENANT_ID=local-dev-tenant
MICROSOFT_PROVIDER_AUTHENTICATION_SECRET=replace-me
```

Then run:

```bash
cd application\single_app
..\..\.venv\Scripts\python.exe app.py
```

Open:

```text
https://localhost:5000
```

## Capture The DLP Admin Card

After authenticating as an admin user, save the rendered admin settings page:

```bash
curl.exe -k -sS -H "Cookie: session=<admin-session-cookie>" https://localhost:5000/admin/settings -o .codex-local/admin-settings.html
```

Then extract the DLP section for a focused visual review:

```bash
python tools/local_dev/render_dlp_admin_preview.py .codex-local/admin-settings.html .codex-local
```

The script writes:

- `.codex-local/admin-dlp-preview.html`
- `.codex-local/admin-dlp-preview-expanded.html`

## Known Local Caveats

- Browser automation may be blocked by Windows group policy.
- If Docker Desktop stops, the Flask process can keep serving cached pages while Cosmos requests fail.
- If another tool owns port `8081`, use `9081` and pass `--gateway-endpoint localhost:9081`.
- Keep `.codex-local/` untracked; it is for local smoke artifacts only.

## Optional Presidio Analyzer Smoke

SimpleChat can test the external `presidio_endpoint` engine against the stock local Presidio Analyzer container without adding Presidio dependencies to the SimpleChat app image.

Run a local Presidio Analyzer container:

```bash
docker run --rm -p 5002:3000 mcr.microsoft.com/presidio-analyzer:latest
```

Configure DLP Admin Settings:

- Default Engine: External Presidio Analyzer endpoint
- Analyzer Endpoint: `http://localhost:5002/analyze`
- Auth Header: `X-DLP-API-Key`
- Secret Env Var: `PRESIDIO_DLP_API_KEY`
- Score Threshold: `0.5`
- Entities: `CREDIT_CARD, EMAIL_ADDRESS, PHONE_NUMBER, US_SSN`

The stock local container does not require an API key. Production deployments should require a private network path plus an API key header at a proxy, wrapper, gateway, or service boundary. The API key value should live in App Service settings or a Key Vault reference; SimpleChat admin settings store only the environment variable name, such as `PRESIDIO_DLP_API_KEY`.

Then test a web-search or upload input containing harmless synthetic content such as `a@example.com`. In redact mode, SimpleChat should use the Presidio Analyzer returned spans and replace the value before egress or indexing. Do not enable raw text logging for SimpleChat, proxies, or analyzer containers while testing.
