# Stream Timing Diagnostics (0.261.472)

Implemented in version: **0.261.472** for the bundled V2 probe
([config.py](../../../application/single_app/config.py)).

## Overview

Use stream timing to distinguish waits on the model, replay storage, and
delivery to the browser. The server and V2 browser report measurements under
the same diagnostic run ID. The probe records timings, counts, and byte
lengths, not prompts or reply text.

## Enable timing for a test

1. In the target Azure App Service, go to **Settings**, open **Environment
   variables**, and select **App settings**. Add `SIMPLECHAT_STREAM_TIMING`
   with the exact value `1` and apply the change. The flag is off by default.
   Saving restarts the app and can interrupt active chats; no image rebuild
   is needed.
2. Sign in and open a V2 personal chat at `/v2/chat?stream_timing=1`. If the
   URL already has query parameters, append `&stream_timing=1`. Only the
   first request to `/api/chat/stream` on that page load opts in. Reload the
   page before each new measurement. Chats without the query parameter are
   not timed.
3. Open DevTools and send a message that streams. In **Network**, look for
   `X-SimpleChat-Stream-Timing: 1` on the request and
   `X-SimpleChat-Stream-Timing-Id` on the response. The response header
   confirms the server started a timing run.

## Find and interpret the results

In the browser **Console**, include Info messages and look for
`[STREAMING] Timing browser arrival` and `[STREAMING] Timing browser end`.
If Application Insights is configured, match their `diagnostic_run_id` to
`sc_diagnostic_run_id` on the server traces. The producer and consumer measure
overlapping work; do not add their durations.

If there is no request header, reload the opt-in URL before sending.
If the request header is present but the response has no timing ID, verify
the App Service setting is `1`, the restart is complete, and the request
returned a stream rather than an error or sign-in response.

## Turn timing off

Remove the query parameter to stop opting in from a browser. To disable the
probe for the deployment, remove `SIMPLECHAT_STREAM_TIMING` or set it to `0`.
Saving that App Service change restarts the app again.

## Regression coverage

The [browser streaming tests](../../../ui_tests/test_v2_stream_citation_delivery.py)
cover one opt-in per page load, timing markers split across network reads, and
the absence of reply text in the timing logs.
