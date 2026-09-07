---
layout: showcase-page
title: "Running Simple Chat Locally"
permalink: /explanation/running_simplechat_locally/
menubar: docs_menu
accent: blue
eyebrow: "Explanation"
description: "Use the repo-local Python 3.12 environment and the Flask debug loop for everyday development, then move to Linux-compatible runtimes only when Gunicorn validation matters."
hero_icons: ["bi-laptop", "bi-terminal", "bi-code-square"]
hero_pills: ["Python 3.12 local venv", "Flask debug loop first", "Gunicorn validation only when needed"]
hero_links: [{ label: "Explanation index", url: "/explanation/", style: "primary" }, { label: "Azure production runtime", url: "/explanation/running_simplechat_azure_production/", style: "secondary" }]
order: 140
category: Explanation
---

Local development is intentionally simpler than Azure production. The goal is fast editing and debugging, not pretending every laptop is a production host.

<section class="latest-release-card-grid">
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-box"></i></div>
		<h2>Use a repo-local virtual environment</h2>
		<p>Create a Python 3.12 `.venv` in the repo and point VS Code at it before you install dependencies or run the app.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-bug"></i></div>
		<h2>Prefer `python app.py` for normal work</h2>
		<p>The Flask debug loop is the default developer path because it keeps iteration fast and avoids unnecessary production-runtime complexity.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-windows"></i></div>
		<h2>Windows is supported for development</h2>
		<p>On Windows, keep using the local Python flow for day-to-day work and move to Docker or WSL2 only when Linux-specific runtime behavior needs testing.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-diagram-2"></i></div>
		<h2>Test Gunicorn separately</h2>
		<p>Use a Linux-compatible environment when you specifically need worker, thread, timeout, or streaming behavior that mirrors production more closely.</p>
	</article>
</section>

<div class="latest-release-note-panel">
	<h2>Do not overfit local startup to production</h2>
	<p>The repo deliberately separates the everyday developer loop from the production hosting model. That keeps local work straightforward and makes production-specific validation more explicit.</p>
</div>

This guide explains the recommended local developer workflow for Simple Chat.

Current documentation version: 0.241.009

## VS Code Python 3.12 Setup

If you are developing in VS Code, use a local `.venv` created with Python 3.12.

From the repo root on Windows:

```powershell
py -3.12 -m venv .venv
```

Activate it in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

If you prefer Command Prompt:

```bat
.venv\Scripts\activate.bat
```

Install dependencies after activation:

```powershell
pip install --upgrade pip
pip install -r application/single_app/requirements.txt
```

In VS Code:

- install the Microsoft Python extension if it is not already installed
- open the Command Palette and run `Python: Select Interpreter`
- choose the interpreter from `.venv`
- confirm the selected interpreter is Python 3.12

Recommended verification commands:

```powershell
python --version
python -c "import sys; print(sys.executable)"
```

Expected results:

- `python --version` should report Python 3.12.x
- `sys.executable` should point to the repo-local `.venv`

If VS Code does not detect the environment automatically, reload the window after creating `.venv`, then select the interpreter again.

## Recommended Local Startup

After the `.venv` interpreter is selected in VS Code, start the app directly with Python for normal development:

```bash
python app.py
```

Set:

```bash
FLASK_DEBUG=1
```

This keeps Simple Chat on the Flask development server, enables local HTTPS behavior, and avoids unnecessary production-runtime complexity while you are editing and debugging the application.

## Windows Developer Workflow

Windows developers should use the repo-local `.venv` with the direct Python startup path.

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
- VS Code terminals inherit the selected `.venv` interpreter when activated in the workspace terminal.

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

## Logout Behavior Across Environments

Logout takes one of two paths, chosen per request. Knowing which one you are on explains
most unexpected logout behavior.

- **Local logout** clears the Flask session and redirects to the app home page.
- **Easy Auth logout** first redirects through the App Service platform endpoint
  `/.auth/logout` so the platform sign-in session is cleared too, then returns to the
  SimpleChat login page.

SimpleChat picks Easy Auth logout only when the request carries the
`X-MS-CLIENT-PRINCIPAL` headers that App Service Easy Auth injects into requests it
intercepts. That gives the following behavior:

| Where you are running | Easy Auth headers present | Logout path |
| --- | --- | --- |
| Local machine (`python app.py`) | No | Local logout |
| App Service with Easy Auth enabled | Yes | Easy Auth logout |
| App Service without Easy Auth enabled | No | Local logout |

Running locally, you always get local logout, because `WEBSITE_HOSTNAME` is not set and no
platform headers exist. There is nothing to configure for local development.

### Troubleshooting a 404 on logout

If logout lands on a 404 at `/.auth/logout`, the app believed Easy Auth was serving that
host but the endpoint was not reachable. Work through the following:

1. Run with `FLASK_DEBUG=1` and sign out again. The logout path decision is written to the
   debug log, including the reason when local logout is chosen.
2. Confirm whether Easy Auth is actually enabled for the App Service. Setting only the
   `WEBSITE_AUTH_AAD_ALLOWED_TENANTS` application setting does not enable it.
3. If Easy Auth is enabled, confirm that `/.auth/*` is routed through to the App Service
   origin. A custom domain, gateway or front door that does not forward those paths will
   return a 404 even though Easy Auth is running.

If Easy Auth must stay enabled and `/.auth/*` cannot be routed, keep logout on the local
path with:

```bash
DISABLE_APP_SERVICE_EASY_AUTH_LOGOUT=true
```

Use that only when the routing issue cannot be fixed. While it is set, signing out no
longer clears the App Service platform session, so the next sign-in can complete without
prompting for credentials.

## Practical Guidance

- Create `.venv` with Python 3.12 and select it in VS Code before installing dependencies.
- Use `python app.py` for normal development.
- Keep `FLASK_DEBUG=1` on local developer machines.
- Treat Gunicorn as a production-runtime validation tool, not the default local developer startup path.
- On Windows, move to Docker or WSL2 when testing Gunicorn workers and threads matters.