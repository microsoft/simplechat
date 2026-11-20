# Stream Replay Batching Fix (v0.261.473)

Fixed in version: **0.261.473**

Investigated in version: **0.261.472**

Related issue: [microsoft/simplechat#1964](https://github.com/microsoft/simplechat/issues/1964).

Related version update: `application/single_app/config.py` changes
`VERSION` from `0.261.472` to `0.261.473`.

## Issue and root cause

Short chat answers could take about 100 seconds to finish appearing even
without agents or tool calls. The model generated content much faster than
SimpleChat delivered it. Application and Azure service telemetry did not
show resource saturation.

The streaming loop synchronously persisted almost every content delta to
Redis, updated stream metadata separately, and repeatedly read cancellation
state before requesting the next model delta. The accumulated sequential
network round trips, rather than Redis resource pressure, dominated latency.

## Technical details

- `application/single_app/route_backend_chats.py` sends ordinary content
  deltas to the active browser immediately and accumulates replay content.
  At eligible flush points, content is combined into a replay event once
  250 ms have elapsed. Pending content is flushed before thought, control,
  error, cancellation, and completion events, and during worker cleanup.
- Cancellation metadata reads are cached for 250 ms. Explicit local
  cancellation updates the cached state immediately; forced reads remain
  available.
- `application/single_app/app_settings_cache.py` appends replay data and
  writes metadata in one Redis transaction. `WATCH` retries protect
  cancellation and reconnect coordination state. Expiry commands use the
  pipeline without separate `EXISTS` round trips.
  Terminal cancellation retains its inactive state, cancellation flag, and
  completion timestamp rather than being overwritten by earlier metadata.
- The existing Cosmos-backed fallback remains available when Redis is
  disabled or fails.

No API, deployment setting, or schema migration is required. Replay content
event counts now describe persisted batches, not individual model deltas.
The batching-completion log records received content events and persisted
batches separately.

## Validation

### Contributor-reported DEV results

These are measurements supplied with the fix, not a local reproduction or
a performance guarantee for other deployments.

| Measurement | Before | After |
| --- | ---: | ---: |
| Total server processing | 107.8 seconds | 10.8 seconds |
| Delay after content yields | 72.1 seconds | 1.35 seconds |
| Content events written to replay | 440 | 11 batches |
| Azure OpenAI time to response | 404 ms | 353 ms |
| Redis errors | 0 | 0 |

Additional reported checks:

- Stop reached the canceled state in 611 ms.
- Refreshing during generation reattached once and completed a
  12,367-character response without visible missing or duplicated text.
- A long response reduced 2,919 content events to 76 replay batches.
- Azure OpenAI, Redis, App Service, and Cosmos DB showed no sustained
  resource pressure.

### Regression coverage

`functional_tests/test_stream_replay_batching.py` exercises immediate live
delivery, the 250 ms replay threshold, ordered control-event flushing,
throttled and forced cancellation reads, disconnect grace cancellation,
Redis transaction conflicts, terminal-state preservation, and Cosmos fallback.
The existing content-streaming and timeout/resilience tests cover compatible
cache doubles, content replacement, and reconnect behavior.

## Limitations and follow-up

Flush checks are event-driven, not a separate periodic timer: content can
remain buffered while the upstream generator is idle until the next event
or worker cleanup.

An abrupt browser refresh did not increment the detach telemetry counter in
the reported DEV test, although reconnect succeeded. Improving that counter
is a separate follow-up.
