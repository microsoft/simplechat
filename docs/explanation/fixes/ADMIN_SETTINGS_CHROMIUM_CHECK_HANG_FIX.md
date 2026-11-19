# Admin settings no longer wait on the Chromium launch check

Fixed in version: **0.261.464**

## Issue

On the container built from 0.261.463, Admin Settings did not load. In V2 the page stayed on
its loading placeholders; `GET /api/v2/admin/settings` never answered (no response after 45
seconds, and no access-log line for it). The server-rendered `/admin/settings` page hung the
same way. Every other admin request answered normally, including
`/api/v2/admin/update-status`, which is requested at the same moment.

## Root cause

Both settings pages call `get_source_review_runtime_capabilities()`, which reports whether
this runtime can launch Playwright Chromium for Source Review JavaScript rendering. It
launched a browser on the request's own thread. The launch call has a 5 second timeout, but
starting the Playwright driver (`sync_playwright()`) has none: a driver that never answers
raises nothing, so the request waited forever. The result is cached only after it finishes,
so every visit started the check again and held another worker thread.

The two pages share nothing else that the answering endpoints lack, which is how the check
was identified. **Why the driver does not answer in this image was not established.** The
merge from Development that preceded this build changed the container's base images and
package installation and moved Playwright from 1.58.0 to 1.65.1; that is the likely area,
not a confirmed cause.

## Change

`application/single_app/functions_source_review.py`

- The launch runs on its own daemon thread (`_run_source_review_runtime_probe`). A caller
  waits at most `SOURCE_REVIEW_RUNTIME_PROBE_SECONDS` (15) from the moment the check started.
- If it has not finished, the caller gets `js_rendering_available: False` with a message
  saying the check did not finish, and a warning is logged:
  `[SOURCE_REVIEW] Chromium launch check did not finish in time.`
- That answer is not cached. A check that finishes later is what the next caller reads.
- While a check is alive no second one starts, and later callers do not wait again.

Nothing changes when the launch succeeds or fails with an error: the same result is cached
as before.

A Source Review page fetch (`_try_rendered_page_fetch`) started the same driver with no
limit, gated only by the saved setting. It now asks the runtime check first and skips
rendering with `js_rendering_runtime_unavailable` when the runtime is not verified, so a run
cannot hang there for the same reason.

## Files modified

- `application/single_app/functions_source_review.py`
- `functional_tests/test_source_review_security.py`
- `application/single_app/config.py`

## Validation

- `test_source_review_runtime_check_cannot_hold_a_caller`: with a launch that never
  returns, the first caller is answered within the limit, later callers are answered at once
  and start no second launch, and a launch that completes late becomes the cached result.
- The existing runtime capability tests pass.

## Not verified

- Not run in the container. That the settings pages load on the deployed site is to be
  confirmed after the next deployment.
- Source Review JavaScript rendering is expected to be unavailable on this image until the
  driver problem is found. Pages are still fetched without rendering.
- Worker threads already held by earlier visits are released only when the container
  restarts, which a deployment does.
