# Model catalog profiles and per-step Auto routing

Implemented in version: **0.261.126** (`application/single_app/config.py`).

## Overview and dependencies

The catalog separates reusable model descriptions from authorized callable
deployments. Classic and React V2 share an administrator editor for built-in
profiles, custom profiles, favorites, priority, and connection association.
Only V2 orchestration adds explicit per-step Auto routing. Regular chat remains
manual; existing planner overrides and delegated agents retain their own bindings.
Since **0.261.131**, an Auto request stays on the standard orchestration contract
even when the Gather / Reason / Render preview is admitted, because only that step
executor enforces these bindings. Dependency planning rejects Auto explicitly, and a
dependency plan carrying bindings fails closed before model setup.

Dependencies are the existing settings store, AI Connections authorization,
orchestration planner/executor/checkpoints, local Bootstrap assets, and the V2
React bundle. No additional database container or deployer configuration is needed.

## Catalog contract and evidence

The packaged `static/json/model_capabilities.json` and its strict schema advance
to schema version 4. `selectionProfile` adds bounded summaries, strengths,
limitations, task suitability, HTTPS sources, review dates, and reviewed native
Chat Completions incompatibility. Existing token, image, embedding, and reasoning
evidence remains independently authoritative.

`functions_model_catalog.py` merges packaged records with the tenant's
`model_catalog` settings document. Custom identities are generated server-side.
Technical profile revisions exclude preferences. The service does not treat custom
aliases as automatic matches or fabricate a publisher verification date.

`catalogProfileId` associates a deployment with a descriptive profile;
`catalogModelId` remains the independent audited capacity identity. Effective
capabilities apply profile, endpoint, then model overrides, including the existing
explicit vision flag. Approved routing also fingerprints effective capability and
capacity metadata, so connection changes cannot silently reuse an old binding.

## APIs and persistence

| API | Purpose |
| --- | --- |
| `GET /api/models/catalog` | Authenticated profile choices, excluding archived entries and linked-deployment inventory |
| `GET /api/admin/model-catalog` | Administrator profiles, global linked-model summaries, and settings ETag |
| `POST /api/admin/model-catalog` | Create a custom profile using `{etag, profile}` |
| `PATCH /api/admin/model-catalog/<profile_id>` | Replace a custom profile and/or update `{etag, preferences}` |

`save_model_catalog_change` writes through the fenced application settings store.
Invalid changes return 400, stale ETags 409, and unconfirmed persistence 503.
Settings/cache publication remains owned by that store; the chat bootstrap cache
also includes catalog state in its fingerprint. Profile responses are explicit
safe projections, not raw settings or endpoint credentials.
V2 catalog saves refresh the browser's model availability; a refresh failure reports
that the catalog was saved and asks the administrator to reload.

## Selection and execution

An explicit `model_routing: "auto"` request builds candidates from the current
user's authorized chat catalog. It cannot accompany an explicit request model.
The planner labels each model-backed step with a task category, but cannot choose
credentials or forge a binding: normalization strips model-supplied bindings.

The server ranks eligible candidates by task suitability, priority, favorite,
then stable connection identity. Unknown specialist claims do not qualify.
Responses-only profiles are excluded from this Chat Completions-based path,
including when a custom descriptive link tries to obscure the native identity.
The candidate set is bounded at 200; exceeding it is an explicit configuration
error, not a silent truncation.

`functions_orchestration_model_routing.py` assigns and revalidates step bindings.
The executor installs coherent prompt, model, model-context, and research-client
state for one serial step and restores it afterward. Final responses and completed
step records use the executed binding. Bindings participate in checkpoint plan
fingerprints and are reauthorized before checkpoint reuse. Preferences never
reroute saved work; technical edits require a new plan.

## User workflows

See [Model Catalog](../../admin/model-catalog.md) for shared profile management,
custom-profile bounds, archival, save conflicts, and association.
See [Choose models for orchestration](../../guides/model-catalog-routing.md) for
Auto versus pinned selection, plan review, and recovery.

## Validation and limitations

`functional_tests/test_model_catalog_profiles.py` covers profile validation,
precedence, collisions, archival, preference ordering, group binding context,
API incompatibility, and restoration after execution failure.
`functional_tests/test_orchestration_catalog_auto_execution.py` drives real Flask
planning and execution with offline provider responses, checking model calls,
live and hydrated step attribution, saved answer metadata, changed-capacity/access
rejection, and binding-sensitive checkpoint fingerprints.
`functional_tests/test_model_endpoint_capacity_save_validation.py` covers real-app
imports and classic admin/personal/group editor save/reopen projections under
normal and optimized Python, including association preservation and removal of
temporary routing metadata before persistence.
`ui_tests/test_model_catalog_management.py` drives the shared classic editor and
the real React component through profile creation, preferences, archival,
validation, safe text rendering, and mobile layout. Existing catalog-evidence,
model-selection, executor, route-policy, and documentation checks guard the
surrounding contracts.

The editor loads bounded catalog metadata and uses only local script/style assets.
Publisher-reviewed selection facts are not benchmarks; other profiles explicitly
identify capability-derived suitability. Auto does not predict unknown future
tool/document sizes, bypass token guards, substitute models during a failing
step, synchronize upstream catalogs, or estimate live prices/latency. Offline
fixtures do not establish production credentials, tenant availability, or live
provider inference.
