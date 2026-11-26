# Streaming replay round trips (0.261.472)

Fixed in version: **0.261.467** (`application/single_app/config.py`).

## Issue and fix

Long chat replies made separate cache requests for progress, replay, and Stop
for every text chunk. A slower network path multiplied those waits. This change
does not buffer chunks or change model routing.

- Redis: after the first visible content event, an eligible direct-model delta
  is checked and persisted in one server-side call. It preserves the submission
  guard, updates both metadata records and the replay list, and observes Stop
  before appending. The attached consumer still checks for safety replacement
  separately. Periodic durable Stop reads, detached/reconnecting streams, and
  control and terminal frames keep their existing paths.
- Cosmos: a conditional Patch appends one event without a separate read or
  uploading the existing history. The Patch response keeps worker-local
  replay current for read outages. A sequence watermark per writing thread
  prevents duplicate appends after lost replies without adding a marker per
  chunk. A missing or pre-upgrade document is handled separately. Metadata
  writes are unchanged for successful streams.

## Compatibility and limits

The Redis optimization needs scripting and a non-clustered endpoint, or keys
on the same shard. If Redis rejects the script before execution because it is
unsupported or not permitted, Simple Chat uses the existing separate operations.
After a lost script reply, Simple Chat checks the publication marker in Redis
instead of replaying the write on a different backend. If a direct content
append cannot be confirmed, it ends the stream with a reload instruction,
not a differently truncated saved response. The error is available to
reconnecting clients without appending to the failed replay list. Previous
releases still read the event list. The Cosmos item size limit still applies.

## Validation

The regression tests exercise immediate replay, cross-worker visibility,
unconfirmed writes, Stop and safety replacement, and the single conditional
Patch request through the installed Cosmos SDK. Operators can compare a long
reply with the timing probe enabled: `redis_publish` is reported separately
from SDK pulls and queue waits. Check Stop and refresh/reconnect with both
Redis selected and Redis off.

### Opt-in stream timing

See [Stream Timing Diagnostics](../features/STREAM_TIMING_DIAGNOSTICS.md) for
the App Service setting, browser opt-in, and server trace correlation. The
SSE consumer and token-usage handling are unchanged when the probe is off.

## Cosmos discovery pointer

Implemented in version: **0.261.468** (`application/single_app/config.py`).

With Cosmos selected, conversation discovery stores the submission ID instead
of a second copy of its status. Text chunks still append to replay and write
attempt metadata immediately. Discovery is renewed periodically while the
attempt is active, including on keepalives, and refreshed at completion for the
existing recovery window. Cosmos conditionally renews only the currently
referenced attempt, so a stale worker cannot renew a newer attempt's pointer.

Lookups with a submission ID still address their attempt directly; lookups
without an ID read shared discovery rather than relying on an older worker's
conversation alias. A reconnect that depends on discovery confirms renewal
before attaching; a lookup or renewal that cannot be confirmed returns 503
rather than reporting the stream absent. Initialization retries before any
chunks are sent; if both writes fail, the attempt is interrupted and its
lease is released. Background renewal retries transient errors sooner without
recreating a missing pointer or overwriting a replacement. Legacy sessions
without submission IDs retain conversation metadata. Redis is unchanged.

The streaming and Cosmos regressions verify that ordinary chunks write attempt
metadata without updating discovery, that explicit submissions skip discovery,
and that pointer renewal uses one conditional Patch. They also cover a lost
initial write, transient discovery errors, and renewal before reconnect.
Compare `metadata_write` time per event with the previous MAG1 run at the
same Cosmos throughput.

## Single-write Cosmos content

Implemented in version: **0.261.469** (`application/single_app/config.py`).

After the first visible content and its stream state are confirmed, each
ordinary direct-model chunk appends to Cosmos replay and advances progress
in the same conditional Patch. The operation still completes before the
chunk is delivered, so there is no batching or unsaved tail. A lost Patch
response cannot double-count progress because the append and counters share
the existing retry watermark.

First content, Stop, reattach, safety, and completion still use the attempt's
control metadata. During long streams, a separate conditional renewal
extends the control record's expiry without overwriting its state. Status
combines control and replay progress; terminal metadata retains the final
totals. Progress stays readable for the life of the attempt metadata even
after replay text expires. Missing progress is not saved as a final total.
Indexing, Cosmos throughput, Redis, and legacy streams are unchanged.

The stream tests check immediate replay, Stop and safety behavior, cross-worker
progress, and lease renewal. The SDK wire test checks that the content and
counters use one Patch. In MAG1 compare `metadata_write_count`, RU per event,
and 429s at the same autoscale cap; `cosmos_metadata_renew` counts the occasional
lease Patch separately. A lower request count is not proof of lower RUs.

## Request-scoped settings read

Implemented in version: **0.261.471** (`application/single_app/config.py`).

The background SSE publisher reuses the settings loaded by the chat route
for the same turn instead of fetching the application configuration again.
That snapshot continues to control output screening for the turn. Other
stream entry points still load their own settings, and live source access
and durable attempt checks are unchanged. The background stream regression
verifies that no second read runs and provisional output is still withheld
when screening requires it.

### Replay-only index experiment

An Azure Government test in `SimpleChat/settings` compared one-event PATCHes
on synthetic replay items of the same size and shape. Only the test array
in the excluded arm was omitted from indexing. At 64, 640, and 1,152 existing
events, average indexed/excluded charges were 18.02/17.83, 75.34/51.43, and
148.64/106.33 RU per PATCH, respectively. The 36 matched pairs used 27.4%
fewer RUs with the exclusion. This isolates write charge, not streaming
latency or throttling under real chat traffic.

The temporary test path was removed, the synthetic items were deleted, and
the original index policy was verified. No live replay format or Cosmos
throughput was changed.
