# Deep Research Distroless JavaScript Rendering Runtime

Version implemented: **0.241.067**

Fixed/Implemented in version: **0.241.067**

## Overview

Deep Research JavaScript rendering fallback can now be packaged into the existing SimpleChat Azure Linux distroless application image without changing the final runtime base image. The build installs Playwright and a Chromium browser bundle in the builder stage, copies the browser files and required shared libraries into the final distroless stage, and exposes a runtime capability check in Admin Settings.

## Dependencies

- `application/single_app/config.py` version `0.241.067`
- `application/single_app/requirements.txt` includes `playwright==1.58.0`
- `application/single_app/Dockerfile` keeps `mcr.microsoft.com/azurelinux/distroless/python:3.12` as the final stage
- `application/single_app/functions_source_review.py` provides the cached runtime capability check

## Technical Specifications

- `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` is set in both builder and final stages.
- The builder stage installs Azure Linux packages needed by headless Chromium, downloads Playwright Chromium, and preserves the Chromium sandbox binary permissions.
- The final distroless stage copies `/ms-playwright`, browser shared libraries, and font configuration from the builder stage.
- Source Review uses shared Chromium launch arguments for runtime probing and rendered fetches.
- Admin Settings shows whether Playwright Chromium launch was verified in the current runtime.
- If Playwright is unavailable or Chromium cannot launch, Source Review continues to skip JavaScript rendering gracefully.

## Configuration Options

- `SOURCE_REVIEW_CHROMIUM_NO_SANDBOX=false` by default.
- Set `SOURCE_REVIEW_CHROMIUM_NO_SANDBOX=true` only after a security review if the hosting platform blocks Chromium sandbox startup.
- `SOURCE_REVIEW_JS_RENDER_MAX_CONCURRENCY=2` by default. Values are clamped from 1 to 5 to limit simultaneous Chromium rendered fetches per app process.

## Security Considerations

Installing Chromium increases the app image size and the security patch surface. Chromium parses untrusted web content, so vulnerabilities in Chromium, font/media libraries, or browser dependencies become relevant to the app container. The implementation keeps the app running as the existing non-root user and keeps Source Review URL validation, request routing, private network blocking, redirect validation, page budgets, content limits, and timeout controls in place.

Rendered fetches are limited by a small per-process concurrency semaphore to reduce CPU and memory exhaustion risk when multiple users trigger Deep Research at the same time.

The strongest security posture is to keep Chromium sandboxing enabled. Disabling the sandbox may be necessary in some container platforms, but it materially increases risk because compromised browser code would have fewer process isolation boundaries inside the app container. If sandbox disabling is required, restrict Deep Research to trusted admins/users, prefer allowed domains, keep egress controls tight, and patch/rebuild images quickly when Chromium security updates are published.

## Usage Instructions

1. Build and deploy the standard SimpleChat container image.
2. Open **Admin Settings** > **Search & Extract**.
3. Check the JavaScript rendering runtime status under **Allow JavaScript rendering fallback**.
4. Enable JavaScript rendering only when the runtime status confirms Chromium launch support.
5. Review logs for `js_rendering_dependency_unavailable` or `js_rendering_failed` skipped-source reasons when diagnosing failed rendered fetches.

## Testing and Validation

- `functional_tests/test_source_review_security.py` validates runtime capability reporting.
- `ui_tests/test_admin_source_review_settings.py` validates that the admin page exposes runtime status.
- Docker build validation should confirm package availability in the Azure Linux builder stage and Chromium launch verification in the final distroless image.

## Known Limitations

- The runtime probe verifies launch support, not every possible target page behavior.
- Final distroless image support depends on the copied Azure Linux shared libraries matching Playwright Chromium requirements.
- Some hosting platforms may block Chromium sandbox startup; use `SOURCE_REVIEW_CHROMIUM_NO_SANDBOX=true` only as an explicit risk acceptance.
