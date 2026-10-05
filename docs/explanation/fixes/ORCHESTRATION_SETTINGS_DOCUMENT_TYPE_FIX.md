# Orchestration Settings Document Type Fix

**Version: 0.261.235**

Fixed in version: **0.261.235**, recorded in
`application/single_app/config.py`.

This affects the React V2 branch (`paullizer-react-v2-ui`) and deployments built
from it.

## Issue

A V2 chat orchestration run could finish every step and still end as
**Partially completed**, with:

> A required retained result is unavailable or changed. No preview was
> substituted.

The Plan panel showed every step as completed, so the failure looked
unrelated to the work that had run. It affected runs whose steps retained
external content: web search, linked pages, deep research, agents, actions and
explicit Fact Memory results. Retrying could succeed or fail again, depending on
timing.

Production telemetry recorded the refusal at finalization:

- `[ORCHESTRATION_EXECUTOR] Retained content could not be reauthorized for finalization.`
- `sc_failure_code=result_unavailable`
- `sc_authority_reason=result_external_context_unavailable`

## Root cause

Orchestration rechecks a retained external result's access each time the result
is used: before the step's acquisition, when the result is admitted, and again
when the final answer reads it. Each check reads the current admin settings and
requires them to be exactly a `dict` (`type(settings) is dict`). This strict check
rejects mapping-like or forged values.

The shared settings store did not always return a `dict`:

- A read served from the shared Redis copy decoded JSON, which is a plain `dict`.
- A read served from Cosmos DB returned the SDK's response object. The
  `azure-cosmos` client returns `CosmosDict`, a `dict` subclass that carries
  response headers, and `copy.deepcopy` keeps that subclass. The orchestration
  check refused it as invalid context.

With Redis enabled, Cosmos serves settings reads whenever another worker's
settings save is in progress, a missing or abandoned shared copy is repaired,
Redis is unreachable, or a caller forces a Cosmos read. With Redis disabled,
Cosmos serves every read, so every such step would fail.

In the reported run, the email step and the summary step both completed. The
Cosmos throughput autoscale background task then saved its status to the
settings, and the final answer's recheck read the settings during that save:

| Time (UTC) | Event |
| --- | --- |
| 16:24:30.275 | Autoscale submitted a throughput update and started its settings save. |
| 16:24:30.433 | Finalization read settings from Cosmos DB, received `CosmosDict`, and refused the email result. |
| 16:24:30.444 | The settings save was published. |

Settings saves happen throughout the day. Background tasks and admin changes
both write settings, so how often a run failed depended on timing.

## Changes

`application/single_app/app_settings_store.py` adds `_plain_document()`. It
copies a Cosmos response into a plain `dict` before the store returns it. Both
Cosmos paths use it:

- `_read_cosmos()`, which serves every Cosmos read, including forced reads,
  reads during another worker's save, cache repair and the Redis fallback.
- `_write()`, which returns the saved document after a write or the creation of
  missing settings.

Every settings read now returns the same type, whichever backend served it. The
orchestration checks are unchanged and still refuse anything that is not exactly
a `dict`.

| File | Change |
| --- | --- |
| `app_settings_store.py` | Cosmos reads and writes return plain `dict` copies. |
| `config.py` | Version `0.261.235`. |
| `functional_tests/test_app_settings_store_plain_dict_reads.py` | New regression tests. |

No setting, deployment or data change is needed.

## Validation

### Tests

`functional_tests/test_app_settings_store_plain_dict_reads.py` uses a Cosmos fake
that returns the real SDK `CosmosDict` type:

- Every store read path returns an independent plain `dict`: Redis disabled, the
  shared copy, a forced Cosmos read, another worker's save in progress, an
  abandoned save, a cache miss, and Redis unavailable.
- Writes and creating missing settings return plain `dict` copies.
- The real `get_settings()` returns a plain `dict` with Redis disabled, during
  another worker's save, and with Redis unavailable.
- For web search, linked pages, deep research, agents and actions, the real
  orchestration provider runs step preflight, admission and the finalization
  recheck while another worker's settings save is in progress. The retained
  result stays readable.
- The orchestration access checks still refuse a `CosmosDict`, so the fix stays in
  the store and the strict check is kept.

On the previous code, 17 of the 21 tests fail. All 21 pass with the fix.

Related suites that pass with the change: `test_app_settings_store_consistency.py`,
`test_app_settings_import_boundaries.py`, `test_app_settings_embedding_write_guard.py`,
`test_embedding_settings_concurrency.py`, `test_admin_multi_endpoint_persistence_guard.py`,
`test_orchestration_external_sources.py`, `test_orchestration_external_identity.py`,
`test_orchestration_external_bootstrap.py` and `test_orchestration_external_pre_effect.py`.

### Before and after

| Before | After |
| --- | --- |
| A step or answer that read settings during a settings save, or with Redis disabled, failed with "A required retained result is unavailable or changed." | Settings have the same type from Redis and from Cosmos DB, and the retained result stays available. |
| Retrying could fail again, depending on when other settings saves happened. | The outcome no longer depends on settings save timing. |

## Related

The same reported run showed a second, unrelated problem: the email step
completed without reading mail, because Microsoft 365 actions could not
authorize inside orchestration. That is addressed separately.

- [Orchestration session identity fix](ORCHESTRATION_SESSION_IDENTITY_FIX.md)
- [Orchestration settings](../../admin/orchestration.md)
