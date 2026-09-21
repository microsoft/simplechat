# Development and React V2 workflow integration

Fixed in version: **0.261.122**.

React V2 authoring integration fixed in version: **0.261.124**.

The application version is recorded in
`application/single_app/config.py`. This integration combines Development's
Microsoft 365 authorization, guarded Custom model clients, and authoritative
settings store with the branch's native workflow authoring, durable execution,
AI Connections, and content screening.

## Issue and root cause

Recreating historical merges can lose changes that existed only in a merge
resolution. Independently developed features also need explicit integration:
Microsoft 365 waits cannot be treated as completed durable runs, a native edit
must retain the selected Run as account, and embedding connections must use the
same outbound policy as the current Custom model clients.

The final integration restores the missing merge intent without replacing
Development's newer security and persistence contracts with older implementations.

## React V2 List and Flow authoring

The subsequent React V2 base integration retains M5B visual authoring and M5C
cross-surface Undo/Redo alongside the Microsoft 365 account selector. The original
pre-rebase React V2 snapshot distinguishes new target-side changes from historical
conflicts caused by replayed commits; unchanged target files do not replace the
already integrated Development implementations.

The new history session originally classified `m365_run_as_user_id` as protected
runtime metadata, rejecting Run as changes in structured workflows. Adding it to
the authored-field list in `WorkflowAuthoringHistory.tsx` lets selection, explicit
clearing, Undo, and Redo use the same guarded draft transaction as other fields.
The Flow preview projection in `workflowEditor.ts` also retains this authored
field, keeping its field inventory and definition digest consistent with Save
and the server's `WORKFLOW_DEFINITION_FIELDS` rather than silently omitting it.
`WorkflowEditorDialog.tsx` retains both the account selector and the new authoring
components. History does not change scope, saved revisions, runtime metadata, or
Microsoft 365 consent.

## Microsoft 365 and durable workflows

The selected `m365_run_as_user_id` is part of the authored workflow definition,
revision, and durable snapshot. Material changes to modern workflow fields
invalidate Microsoft 365 approval bindings. Definition saves normalize those
bindings against the freshly read record inside the existing compare-and-swap
save, so stale editor state cannot restore an obsolete approval.

The native workflow editor uses the existing scoped account-list endpoint for
explicit selection and clearing. A loading or access failure does not erase a
stored account. The native runtime and Flow views identify Microsoft 365
authorization waits and do not offer generic approval or resumption for them,
even when an older response contains a stale resume flag. See
[Create a workflow](../../guides/create-a-workflow.md) and
[Trigger and inspect a workflow](../../guides/trigger-a-workflow.md).

Approval and sign-in waits remain nonterminal. They release the durable worker
lease and expose a cancellation-only gate. The workflow's ordinary Resume and
Approve operations cannot authorize Microsoft 365 access. Authorization continues
through the existing Microsoft 365 approval or connection flow.

The Microsoft 365 scheduler requeues the exact waiting run through a dedicated
durable continuation. It checks the run, workflow, original actor, Run as account,
and definition revision before execution. It does not dispatch a durable workflow
through the legacy runner. If another worker owns the run, scheduling reports the
actual pending state rather than marking the handoff failed.

Resumption retains the task attempt and completed results. Structured iteration
uses execution-scoped Microsoft 365 checkpoint and agent-step identities, so a
checkpoint from one iteration cannot skip a later iteration. A conversation
created before sign-in is reused after sign-in. Cancelling the durable run also
cancels its pending Microsoft 365 work.

Key implementation files are `functions_workflow_definitions.py`,
`functions_workflow_definition_store.py`, `functions_m365_workflow_binding.py`,
`functions_workflow_runtime_store.py`, `functions_workflow_execution.py`,
`functions_workflow_structured_execution.py`, `functions_workflow_runtime.py`,
`functions_workflow_runner.py`, `background_tasks.py`, and
`functions_m365_continuations.py` under `application/single_app/`.

## Custom embedding connections

Custom OpenAI and Azure OpenAI embedding connections retain their explicit API,
request model or deployment, operation overrides, URL mode, and version rules.
OAuth2 embedding authentication and other Custom API types remain unsupported.
The retained embedding-only OpenAI-compatible alias continues to require an API
key and keeps its stored connection identity.

`functions_embeddings.py` builds these clients through
`build_custom_openai_client_kwargs`. This preserves Development's DNS-pinned
transport, redirect restrictions, explicit network permissions, TLS trust and
client-certificate handling, authentication header validation, and identity
headers. Pure URL resolution lives in `functions_model_endpoint_urls.py` and is
shared with `model_endpoint_clients.py`; profile resolution does not import the
runtime client module. Custom and embedding-only connection credentials use
strict Key Vault hydration before client construction; unresolved references
cannot be sent as model credentials.

The Classic AI Connections editor matches these restrictions. It offers the
correct embedding API for the selected Custom protocol, explains unsupported
authentication and APIs, and prevents unsupported embedding publication or tests.
Switching authentication preserves model edits and refreshes capability controls.
Unknown models still require explicit embedding metadata; dimensions are not
silently inferred or resized.

## Preserved integration boundaries

Settings writes retain the authoritative store, conditional writes, shared-cache
publication, and embedding/content-screening fences. Existing screened source
checks and publication rollback remain in place. Embedding-only models are not
advertised as image-generation models, and connection tests retain
endpoint-aware capability checks. Empty model selections return the stable
`invalid_model_selection` error before inference. Opening Classic Admin Settings
normalizes connections for display only; persistence remains in the explicit
save and migration paths.

The native Actions settings schema includes Development's retrieval-provider
choice and additional trusted file-download hosts. Host edits reuse the Classic
transport validator and update only the submitted setting, retaining the current
value of its companion setting.

Development's remote-only MCP policy remains authoritative. Retired local STDIO
configurations can be reviewed and migrated, but this integration does not
re-enable their execution.

## Validation

`functional_tests/test_workflow_m365_rebase_integration.py` covers native
definition revisions, fresh-record approval invalidation, both durable runtime
schemas, scheduler dispatch, wait/resume/cancel behavior, exact task attempts,
iteration-scoped checkpoints, crash recovery, and conversation reuse.
`functional_tests/test_m365_continuations.py` covers pending durable handoff
ownership without a false terminal result.
`functional_tests/test_workflow_m365_run_as_client.js` and the native Microsoft
365 browser tests cover authoring and cancellation-only authorization waits.
`functional_tests/test_workflow_authoring_session.js` covers Run as selection and
clearing from absent, empty, and saved values, exact history replay, and the saved
revision boundary. `ui_tests/test_v2_workflow_authoring_history.py` verifies the
same account edits across List and Flow against the real built interface.
`functional_tests/test_workflow_authoring_history.py` compiles real history-produced
payloads and verifies that preview retains the selected account and authored digest.
The Flow authoring browser suite also verifies that switching groups replaces
the eligible Run as account list while discarding the prior group's delayed preview.

`functional_tests/test_ai_connection_embedding_custom_merge.py` covers the
Custom embedding integration. Existing route-policy, settings, provider, content
screening, and documentation checks cover the retained contracts.
`functional_tests/test_m365_admin_settings_rebase_integration.py` and
`ui_tests/test_v2_m365_transport_settings.py` cover the native transport settings,
partial edits, long host names without truncation, and visible validation errors.

`ui_tests/test_ai_connection_custom_embeddings.py` exercises the actual Classic
templates and local JavaScript: supported APIs and authentication, saved-model
tests, unsupported capability states, draft retention, invalid metadata, and
explicit protocol mismatch errors. The shared capacity-editor browser cases
continue to cover the existing admin, personal, and group editors.

Validation uses isolated stores and service boundaries rather than live Microsoft
365, model, or Azure resources. Compiling the merged deployment source with its
pinned Bicep compiler reproduces the checked-in template; no cloud deployment or
deployer version change is required for this final integration.
