# explanation/running_simplechat_azure_production.md
---
layout: libdoc/page
title: Running Simple Chat in Azure Production
order: 150
category: Explanation
---

This guide explains the supported production startup patterns for Simple Chat in Azure.

Current documentation version: 0.239.136

## Default Azure Production Model in This Repo

The repo-provided Azure deployment paths are container-based App Service deployments.

That includes the deployers documented in this repository for:

- `azd`
- Bicep
- Terraform
- Azure CLI

In those deployment models:

- Azure App Service runs the published container image
- the container entrypoint already starts Gunicorn
- you do not need to set an App Service Stack Settings Startup command

The web container entrypoint is:

```text
python3 -m gunicorn -c /app/gunicorn.conf.py app:app
```

## Native Python App Service Option

If you intentionally deploy Simple Chat as a native Python App Service instead of using the repo container image, set the web startup command explicitly.

If App Service starts in `application/single_app`:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```

If App Service starts from the repo root:

```bash
python -m gunicorn -c application/single_app/gunicorn.conf.py --chdir application/single_app app:app
```

## Background Scheduler Guidance

For production, keep scheduler-style work separate from multi-worker web processes when possible.

Recommended web-process setting when scheduler work runs elsewhere:

```bash
SIMPLECHAT_RUN_BACKGROUND_TASKS=0
```

Recommended scheduler command:

```bash
python simplechat_scheduler.py
```

Operationally, that scheduler can run as:

- a separate App Service or worker process
- a scheduled container or job
- another automation path that launches the same codebase with the scheduler command

## Gunicorn Guidance for Azure

Gunicorn is the production web server for Simple Chat in Azure-oriented deployments.

The shared runtime config supports these tuning variables:

- `GUNICORN_BIND`
- `GUNICORN_WORKERS`
- `GUNICORN_THREADS`
- `GUNICORN_TIMEOUT`
- `GUNICORN_GRACEFUL_TIMEOUT`
- `GUNICORN_KEEPALIVE`
- `GUNICORN_MAX_REQUESTS`
- `GUNICORN_MAX_REQUESTS_JITTER`

Use multiple workers only after you have decided how scheduler work is isolated.

## Recommended Azure Production Pattern

For most production environments in this repository:

1. Deploy the container image through the repo-supported deployer.
2. Let the container entrypoint launch Gunicorn.
3. Do not configure an extra App Service Startup command.
4. Move scheduler work into a separate runtime if you want clean multi-worker web behavior.

## What Not to Do

- Do not configure a second Gunicorn startup layer on top of the container deployer.
- Do not treat Windows local development startup as proof of Gunicorn production behavior.
- Do not leave scheduler decisions implicit if you plan to scale out workers or instances.

## Summary

- Repo deployers: container-based, Gunicorn already handled.
- Native Python App Service: set the Gunicorn startup command explicitly.
- Multi-worker production: separate scheduler work deliberately.
- Local developer startup and Azure production startup should be treated as different runtime concerns.