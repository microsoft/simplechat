# Cosmos replay-only index exclusion (0.261.472)

Implemented in version: **0.261.472** (`application/single_app/config.py`).

## Purpose

On installations without Redis, Cosmos stores chat chunks so disconnected
clients can resume. Indexing the replay text adds write cost even though
reconnect reads it by document ID. This opt-in setting omits only that text
from the index. It adds no container, buffering, or throughput requirement.

## How it works

The admin-only `GET /api/admin/settings/cosmos-replay-indexing` previews the
settings container's policy. `POST` applies and verifies the exclusion,
verifies a manual change, or disables use of the new format. Automatic
application needs Azure management-plane container permission. It checks
the management target against the Cosmos container the app uses and requests
a conditional update. The app independently verifies the policy before
enabling the setting or creating an excluded replay document.

Only new submission-scoped chat streams using Cosmos use `stream_replay_events` when the exclusion
`/stream_replay_events/[]/?` is verified. Replay readers accept the old
`payload` array as well. Counters, timestamps, and retry markers stay indexed.
Timeout recovery and cross-worker writers reconcile the existing format
instead of creating a second copy of the text.

## Operator workflow

Upgrade every worker that shares the container before turning on
[Optimize Cosmos replay when Redis is off](../../admin/scale.md#optimize-cosmos-replay-when-redis-is-off).
The control is off by default and inactive with Redis enabled. If automatic
application cannot be confirmed, copy the merged policy or the exclusion
entry shown and verify the policy after saving in Azure.

Disabling the setting changes only new streams. Wait for affected streams
and their replay windows to end before rolling back to a version that
cannot read the new format. The exclusion can stay unused.

## Validation and limits

Tests cover policy merge, permission denial, manual verification, and replay
across workers using both formats. The synthetic MAG1 experiment reduced
write charges by 27.4% across 36 paired PATCHes; that is not a guarantee of
lower end-to-end latency or no throttling in every workload.
