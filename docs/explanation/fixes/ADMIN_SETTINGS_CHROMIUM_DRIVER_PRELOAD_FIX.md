# Admin Settings Chromium Driver Preload Fix (0.261.465)

Fixed/Implemented in version: **0.261.465** (`application/single_app/config.py`).

## Issue and root cause

The classic Admin Settings page and the V2 settings API both check whether
Source Review can render pages with Chromium. On Azure App Service, that check
could wait indefinitely before returning any settings. The five-second browser
launch timeout did not apply to the earlier Playwright driver handshake.

The affected image contained the expected Chromium and Node binaries. It
started and rendered JavaScript in local Docker under the image's non-root
user. On App Service, the same image started Node but the Playwright driver
sent no handshake over its pipe. The platform had injected the Application
Insights Node agent via `NODE_OPTIONS=--require /agents/nodejs/build/src/Loader.js`.
Keeping that preload reproduced the stall; removing it from just the
diagnostic child process restored driver startup.

## Fix

The Dockerfile points `PLAYWRIGHT_NODEJS_PATH` at a root-owned launcher built
from `docker-customization/simplechat_playwright_node.py`. Before executing the
Node binary bundled with the installed Playwright wheel, the launcher removes
the known Azure preload from the child's `NODE_OPTIONS`.
Other Node flags and preloads still apply. The fix does not change the Flask
process's environment, Application Insights configuration, pinned versions,
browser launch flags, or the option to build without Chromium.

The shared capability check also bounds each caller's wait to 15 seconds and
shares one in-flight check per worker. If the driver remains unavailable, both
settings surfaces can load with an unavailable status, and Source Review can
skip the browser fallback rather than starting another unverified driver.

## Validation

`functional_tests/test_source_review_chromium_startup.py` covers flag
preservation, a stalled handshake, and recovery when the handshake completes.
On the affected App Service instance, a diagnostic child without the preload
reported `js_rendering_available: true` and rendered JavaScript with Chromium
158.0.8127.18.

In local Docker, a synthetic preload at the same path blocked the original
image. The rebuilt image reported `js_rendering_available: true` in under one
second under Gunicorn's `gthread` workers as UID 65532, and Source Review
extracted text inserted by JavaScript from an offline fixture. A different
stalled preload, intentionally preserved, returned the timeout status after
15 seconds. The full local rebuild used a build-only pip mirror because the
direct package download failed TLS; the mirror configuration was not retained
in the runtime.

Existing deployments need a rebuilt image and their normal rollout. The
diagnostic comparison did not change or deploy Azure resources.
