# Model catalog profiles and per-step Auto routing

Implemented in version: **0.261.126** (`application/single_app/config.py`).
Updated in version: **0.261.134** (Gather / Reason / Render plans and the general-answering fallback).
Updated in version: **0.261.139** (Gather / Reason / Render is the only orchestration contract).

## Overview and dependencies

The catalog separates reusable model descriptions from authorized callable
deployments. Classic and React V2 share an administrator editor for built-in
profiles, custom profiles, favorites, priority, and connection association.
Only V2 orchestration adds explicit per-step Auto routing. Regular chat remains
manual; existing planner overrides and delegated agents retain their own bindings.
Between **0.261.131** and **0.261.133**, an Auto request stayed on the earlier
orchestration contract, because only its step executor enforced these bindings.
Since **0.261.134**, the Gather / Reason / Render executor enforces them: each step
runs inside its binding's model scope, and an Auto plan with a missing or stale
binding is refused before any model setup. Since **0.261.139**, Gather / Reason /
Render is the only orchestration contract, so every Auto plan is bound this way.

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
then stable connection identity. An unknown rating never outranks a model rated
for the task. When no connected, capable model is rated for a step's task, the
step uses the model best rated for general answering instead of failing the whole
plan, and its reason reads "General answering, because no connected model is rated
for ...". This matters because few profiles rate specialist tasks: only one
built-in profile rates structured data analysis, and many rate no reasoning. The
fallback never uses a model rated Unsuitable for the task, an archived profile, or
a model missing a required capability such as tool calling for actions.
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

The planner prompt also lists which steps are
model-backed (`compose`, `tabular_analyze`, `document_analyze`, `document_compare`,
`deep_research`, `action_invoke`). The chat answer is credited to the model bound
to the step that `final_response` names. When the reply reuses an earlier turn's
result, or the plan only delivers files, no step writes it, so the default
selection is kept rather than crediting another step's model. The external-source
check that runs before an action or deep research result is admitted or reused
rebuilds the step's model from its approved binding, because the run's own
selection is empty under Auto.

## User workflows

See [Model Catalog](../../admin/model-catalog.md) for shared profile management,
custom-profile bounds, archival, save conflicts, and association.
See [Choose models for orchestration](../../guides/model-catalog-routing.md) for
Auto versus pinned selection, plan review, and recovery.

## Validation and limitations

`functional_tests/test_model_catalog_profiles.py` covers profile validation,
precedence, collisions, archival, preference ordering, the general-answering
fallback and what it never bypasses, group binding context, API incompatibility,
and restoration after execution failure.
`functional_tests/test_orchestration_external_metadata.py` covers rebuilding bound
Auto action and deep research steps from their bindings, and refusing a missing or
malformed binding.
`functional_tests/test_orchestration_single_contract_parity.py` covers Auto planning
and execution on Gather / Reason / Render plans, answer credit, and the planner's
model-backed step list.
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
