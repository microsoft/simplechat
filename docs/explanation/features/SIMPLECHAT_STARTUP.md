# SimpleChat Startup and Scheduler (v0.239.129)

## Overview
This document explains how SimpleChat should be started in local development, Azure App Service native Python deployments, and container-based runtimes. It also explains how background scheduler work is separated from the Gunicorn web process so administrators can use more than one web worker without duplicating scheduler threads.

**Version Implemented:** 0.239.129

## Dependencies
- Flask application bootstrap in `application/single_app/app.py`
- Gunicorn runtime config in `application/single_app/gunicorn.conf.py`
- Shared scheduler loops in `application/single_app/background_tasks.py`
- Dedicated scheduler entrypoint in `application/single_app/simplechat_scheduler.py`
- Container startup in `application/single_app/Dockerfile`

## Implemented in version: **0.239.129**

## Technical Specifications

### Web Process Modes
- **Local debug mode:** `FLASK_DEBUG=1` and `python app.py`
- **Direct Gunicorn mode:** Gunicorn launched by App Service or by an operator command
- **Optional handoff mode:** `python app.py` with `SIMPLECHAT_USE_GUNICORN=1`

The web process now supports two production-safe approaches:

1. Launch Gunicorn directly.
2. Launch `python app.py` and let the process exec into Gunicorn when `SIMPLECHAT_USE_GUNICORN=1` is set.

If Gunicorn is already the startup command, `SIMPLECHAT_USE_GUNICORN` is not needed.

### Background Scheduler Separation
Scheduler-style loops are defined in `background_tasks.py` and can be started either:

- inside a single-process web runtime for local development or legacy deployments
- in a separate dedicated scheduler process by running `simplechat_scheduler.py`

Background loops now start unless `SIMPLECHAT_RUN_BACKGROUND_TASKS` is explicitly set to a false-like value such as `0`, `false`, `no`, or `off`.

Approval expiry and retention policy execution also use Cosmos-backed distributed lease documents in the shared settings container so only one worker or instance should perform those jobs at a time.

### Environment Variables

#### Web Process
- `FLASK_DEBUG=1`
  Uses the Flask development server with HTTPS and local-friendly behavior.
- `SIMPLECHAT_USE_GUNICORN=1`
  Only matters when the process starts as `python app.py` in non-debug mode.
- `SIMPLECHAT_RUN_BACKGROUND_TASKS`
  Background loops are enabled when this setting is unset. Set it to `0`, `false`, `no`, or `off` to disable background loops in the current process.

#### Gunicorn Tuning
- `GUNICORN_BIND`
- `GUNICORN_WORKERS`
- `GUNICORN_THREADS`
- `GUNICORN_TIMEOUT`
- `GUNICORN_GRACEFUL_TIMEOUT`
- `GUNICORN_KEEPALIVE`
- `GUNICORN_MAX_REQUESTS`
- `GUNICORN_MAX_REQUESTS_JITTER`

## Native Python App Service

### Recommended Web Startup
Use Gunicorn directly in the App Service Startup command when deploying the native Python runtime.

If App Service starts in `application/single_app`:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```

If App Service starts at the repo root:

```bash
python -m gunicorn -c application/single_app/gunicorn.conf.py --chdir application/single_app app:app
```

An explicit full command is also valid:

```bash
gunicorn --bind=0.0.0.0:$PORT --worker-class gthread --workers 2 --threads 8 --timeout 900 --graceful-timeout 60 --keep-alive 75 --max-requests 500 --max-requests-jitter 50 app:app
```

### Recommended Scheduler Process
Run scheduler work in a separate job/process instead of inside the web workers.

Recommended command:

```bash
python simplechat_scheduler.py
```

Operational options include:
- a separate App Service or worker instance dedicated to the scheduler command
- a WebJob or automation step that runs the scheduler command
- a scheduled container/job platform that launches the same codebase with the scheduler command

### Admin Guidance
- Keep Gunicorn as the web Startup command.
- Leave `SIMPLECHAT_USE_GUNICORN` unset unless you intentionally want `python app.py` to hand off to Gunicorn.
- Set `SIMPLECHAT_RUN_BACKGROUND_TASKS=0` in multi-worker Gunicorn web deployments if the scheduler runs elsewhere.
- Use `workers=2` for the web process only after moving scheduler work out to the dedicated scheduler process.

## Container Runtime

### Default Web Container Behavior
The container image now starts the web process with Gunicorn by default through the Docker entrypoint.

Web container entrypoint:

```text
python3 -m gunicorn -c /app/gunicorn.conf.py app:app
```

### Dedicated Scheduler Container or Job
Use the same image with an overridden command to run scheduler work separately.

Scheduler command:

```bash
python3 /app/simplechat_scheduler.py
```

This allows a deployment topology such as:
- one web container with `workers=2`
- one scheduler container or job running `simplechat_scheduler.py`

## Local Development

### Default Local Workflow
For everyday development, use:

```bash
FLASK_DEBUG=1
python app.py
```

This keeps the normal Flask development flow and starts background loops in the local process.

If multiple workers or instances are active, the approval expiry and retention policy jobs now coordinate through distributed locks. Logging timer work still runs per process.

### Production-Like Local Workflow
For concurrency, timeout, and streaming validation, run Gunicorn locally:

```bash
gunicorn --bind=0.0.0.0:5000 --worker-class gthread --workers 2 --threads 8 --timeout 900 --graceful-timeout 60 --keep-alive 75 --max-requests 500 --max-requests-jitter 50 app:app
```

To test the scheduler separately at the same time:

```bash
python simplechat_scheduler.py
```

## Usage Instructions

### Native Python App Service
1. Set the App Service Startup command to Gunicorn.
2. Set `SIMPLECHAT_RUN_BACKGROUND_TASKS=0` in the web app configuration when scheduler work is running in a separate process/job.
3. Run scheduler work with `python simplechat_scheduler.py` in a separate process/job.

### Container Deployments
1. Keep the default Gunicorn web entrypoint.
2. Launch a second container/job using the same image.
3. Override its command to `python3 /app/simplechat_scheduler.py`.

## Testing and Validation
- Functional test: `functional_tests/test_gunicorn_startup_support.py`
- Functional test: `functional_tests/test_startup_scheduler_support.py`

These tests verify:
- Gunicorn-aware startup helpers and config defaults
- shared background task module extraction
- dedicated scheduler entrypoint presence
- deployment guidance documentation presence

## Known Limitations
- Leaving `SIMPLECHAT_RUN_BACKGROUND_TASKS` unset enables the loops in every Gunicorn worker process.
- Approval expiry and retention policy now coordinate with distributed locks, but logging timer work still runs in every enabled process.
- Set `SIMPLECHAT_RUN_BACKGROUND_TASKS=0` in web workers if you want the separate scheduler process to be the only scheduler runtime.
- The scheduler separation prepares the app for multi-worker web runtimes, but the actual Azure job/container orchestration still needs to be configured per environment.