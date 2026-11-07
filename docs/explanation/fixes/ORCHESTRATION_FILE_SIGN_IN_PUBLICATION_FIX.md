# Orchestration Files From External Results Failing Without a Reason Fix

**Version: 0.261.303**

Fixed in version: **0.261.303**, recorded in
`application/single_app/config.py`.

This affects the React V2 branch (`paullizer-react-v2-ui`) and deployments built
from it since **0.261.209**.

## Issue

A request to create a Word report from a "Use an action" step's results gathered
its data and wrote the report, then replied:

> Files: issued_refunds_shell_company_linked_entities_bank_analysis.docx: could not be created.
>
> The request was only partially completed. This operation could not complete.

The file card showed **Failed** and "This file could not be created." Nothing
said why, the card offered no **Retry file**, and the recovery card offered no
**Retry from failed step**, only "Review each file separately".

Production telemetry showed that the file rendered in 11 seconds and was refused
when it was published:

- `[ORCHESTRATION_EXTERNAL_SOURCES] A step's source was refused.` for the
  `action_invoke` step, with `sc_stage=external_source_read` and
  `sc_authority_reason=external_identity_session_unavailable`.
- `[ORCHESTRATION_EXECUTOR] A file render attempt finished.` with
  `sc_status=failed`, `sc_output_code=output_access_denied` and
  `sc_error_cause_type=ResultUnavailableError`.

## Root cause

### Publication checked the file's sources without the user's sign-in

Since **0.261.209**, retained external results (web search, linked pages, deep
research, agents and actions) are rechecked with the app roles from the user's
signed-in session. `build_external_identity_reader` captures those roles while
the request context exists, because the run continues on a worker thread.

A render step's own service has those roles: it is built on the request thread
when the run starts. Publishing the file, however, goes through
`upload_generated_file_artifact_stream_for_user`, which authorizes the file's
lineage again through `load_orchestration_artifact_binding`. That function asked
the registered artifact factory for a **new** `build_orchestration_services(...)`
on the worker thread. With no request context there, its identity reader had no
roles, and the recheck of the action result failed closed with
`external_identity_session_unavailable`. Every file whose content came from an
external result was refused this way.

### The failure lost its reason

`_source_visibility_code` mapped the refusal to `output_access_denied`, which is
not retryable, so the file offered no **Retry file**. The saved file projection
says "This file could not be created." for every failure except a time limit, and
the render step reported the generic `step_failed`.

### The chat hid the only retry that could work

React V2 offers **Retry from failed step** only for attempts without files. A
file retry runs in the background scheduler, which never has a signed-in session,
so even a retryable file would have failed the same way.

## Fix

### The rendering service authorizes its own publication

`OrchestrationRenderingService.render_attempt` runs inside the new
`render_attempt_scope(self)` from `functions_orchestration_artifacts.py`. While
the attempt runs, `_bound_service` uses that service for a publication check of
the same user and conversation instead of the factory. A run started from the
chat therefore publishes its files under the sign-in it started with.

The scope is a `ContextVar`, so it never crosses into another thread or request.
A service for another conversation or user is never used, and outside a render
attempt nothing changes.

### A file that needs a sign-in says so

- A refusal caused only by the missing session is classified as the new output
  code `output_sign_in_required`, wherever it surfaces:
  `_source_visibility_code`, `output_failure`, and
  `load_orchestration_artifact_binding`. It is not retried automatically or file
  by file, because both run in the background.
- A failed file's saved projection now explains why it could not be created for
  the common causes: a missing sign-in, unconfirmed access to its conversation or
  results, a missing or changed result, a source under review, or file creation
  being off.
- The render step reports the new failure `file_sign_in_required`, which asks the
  user to select **Retry from failed step**.

### Retry from failed step is offered for such a file

React V2 now offers **Retry from failed step** for an attempt with files when a
failed file can't be retried on its own and no file is still being prepared. The
recovery card explains that the retry creates the plan's files again without
repeating completed plan steps. The retry runs from the signed-in chat, so it
can check and publish the file.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_orchestration_artifacts.py` | `render_attempt_scope`, `signed_in_session_required`, and `_bound_service` using the rendering attempt's service. |
| `application/single_app/functions_orchestration_rendering.py` | Scoped render attempts, `output_sign_in_required` classification and `render_failure_code`. |
| `application/single_app/functions_orchestration_output_store.py` | Failure and unavailable messages for the new code and common failures. |
| `application/single_app/functions_orchestration_continuation.py` | Scheduler reconciliation reports the same step failure. |
| `application/single_app/functions_orchestration_schema.py` | `file_sign_in_required` failure message. |
| `application/v2_ui/src/components/chat/OrchestrationRecoveryNotice.tsx` | **Retry from failed step** for a file that can't be retried alone. |
| `application/single_app/config.py` | Version 0.261.303. |

## Testing

- `functional_tests/test_orchestration_file_sign_in_publication.py` runs the
  real upload and publication modules. A file publishes when the factory's service
  has no sign-in, a foreign conversation's service is never used, and a refused
  file fails as `output_sign_in_required` with its reason and no file-only retry.
  Its step reports `file_sign_in_required`.
- `functional_tests/test_orchestration_output_lifecycle.py` now expects the saved
  reason for an access refusal.
- `ui_tests/test_v2_orchestration_recovery.py` checks that a file that can't be
  retried alone offers **Retry from failed step**, and that a retryable file still
  offers only **Retry file**.

Without the scope, the publication test fails exactly as production did: the file
ends `failed` and unavailable.

## Impact

| Before | After |
| --- | --- |
| A file built from web, deep research, agent or action results failed at publication in every orchestrated run. | It publishes with the sign-in the run started with. |
| The file card said only "This file could not be created." | It says why, for example that its results can only be checked with the user's sign-in. |
| No retry was offered. | **Retry from failed step** creates the files again from the chat, reusing completed steps. |

## Known limitations

A file rendered in the background, such as after a run waited for a long
computation, still can't check web, deep research, agent or action results. It
now fails with that reason, and **Retry from failed step** creates it from the
chat.
