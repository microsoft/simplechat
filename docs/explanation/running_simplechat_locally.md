# explanation/running_simplechat_locally.md
---
layout: libdoc/page
title: Running Simple Chat Locally
order: 140
category: Explanation
---

This guide explains the recommended local developer workflow for Simple Chat.

Current documentation version: 0.239.136

## Recommended Local Startup

For normal development, start the app directly with Python:

```bash
python app.py
```

Set:

```bash
FLASK_DEBUG=1
```

This keeps Simple Chat on the Flask development server, enables local HTTPS behavior, and avoids unnecessary production-runtime complexity while you are editing and debugging the application.

## Windows Developer Workflow

Windows developers should use the direct Python startup path.

Recommended local settings:

```dotenv
FLASK_DEBUG="1"
SIMPLECHAT_USE_GUNICORN="1"
SIMPLECHAT_RUN_BACKGROUND_TASKS="1"
```

Why this still works:

- When `FLASK_DEBUG="1"`, `python app.py` stays on the Flask development server.
- `SIMPLECHAT_USE_GUNICORN` is ignored while debug mode is enabled.
- Background tasks continue to run in the single local process unless explicitly disabled.

## Linux and macOS Developer Workflow

Linux and macOS developers can use the same default local workflow:

```bash
FLASK_DEBUG=1 python app.py
```

That remains the recommended path for everyday development even on systems that can run Gunicorn.

## When You Need Gunicorn-Specific Validation

Use a Linux-compatible runtime only when you specifically need to validate:

- multi-worker behavior
- Gunicorn thread settings
- keepalive and timeout behavior
- production-like streaming behavior

Example Gunicorn command:

```bash
gunicorn --bind=0.0.0.0:5000 --worker-class gthread --workers 2 --threads 8 --timeout 900 --graceful-timeout 60 --keep-alive 75 --max-requests 500 --max-requests-jitter 50 app:app
```

On Windows, use one of these options for that kind of validation:

- Docker Desktop running the repo container image
- WSL2 with a Linux shell
- another Linux environment

Native Windows Python should not be used to run Gunicorn directly.

## Scheduler Behavior in Local Development

By default, background loops remain enabled in local development.

Use this variable only if you want to disable them in the current process:

```bash
SIMPLECHAT_RUN_BACKGROUND_TASKS=0
```

If you want to test the scheduler separately, run:

```bash
python simplechat_scheduler.py
```

## Practical Guidance

- Use `python app.py` for normal development.
- Keep `FLASK_DEBUG=1` on local developer machines.
- Treat Gunicorn as a production-runtime validation tool, not the default local developer startup path.
- On Windows, move to Docker or WSL2 when testing Gunicorn workers and threads matters.