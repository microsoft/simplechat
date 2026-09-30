# Orchestration Web Search and Deep Research Access Fix

Fixed in version: **0.261.205**

Application version reference: `application/single_app/config.py`.
Refs [#1509](https://github.com/microsoft/simplechat/issues/1509).

## Issue

In V2 chat, orchestrated runs that used web search, a linked page or deep research
failed with "A required retained result is unavailable or changed. No preview was
substituted." The same requests worked in classic chat. The message didn't say
which part failed, so it looked like a web search or deep research defect.

## Root cause

Two separate refusals stopped these steps before any search ran. Both were
reported with the same generic `result_unavailable` failure, and the reason wasn't
logged.

1. **A directory lookup on every call.** Each external-source access ran
   `GraphExternalIdentityReader`. It read the user, the app's service principal and
   the user's app-role assignments from Microsoft Graph with an app-only token.
   That needs the **application** permission `Directory.Read.All`, which
   deployments don't grant by default. Graph returned HTTP 403, the reader raised
   `external_identity_access_denied`, and every web search, URL read and deep
   research step failed. Classic chat never makes this call: it trusts the app
   roles in the signed-in session. The per-call lookup also added several Graph
   requests to every step, which doesn't scale to large tenants.
2. **A deep research planner gate.** `is_research_acquisition_profile_supported()`
   refused a research acquisition whenever query planning (with more than one
   query) or LLM link planning was on. Both are on by default in Knowledge
   settings, so every orchestrated deep research step was refused with
   `external_configuration_research_profile_unsupported`.

## Changes

### Signed-in session roles, as classic chat

`SessionExternalIdentityReader` replaces `GraphExternalIdentityReader`.
`build_external_identity_reader` captures the session's app roles and
`preferred_username` while the request context exists, because the run then
continues on a worker thread. Each access still point-reads conversation
ownership and the user's settings, and applies Control Center access
restrictions (with the Admin bypass that `user_required` has) and the
`enable_agents` preference. There are no Graph calls, tokens or MSAL clients,
and roles are never saved on the run.

A scheduler continuation, such as recovery after a restart, has no signed-in
session. Its reads fail closed with the refusal code
`external_identity_session_unavailable`. Saved run roles are never restored.

### Deep research planners admitted

The profile gate is removed from `validate_acquisition` and
`capture_research_planner_configuration`, and the predicate is deleted. The
research engine still captures the planner before query planning and around
every search and page fetch, so each planner request follows a fresh
`preflight_gather_acquisition` and `planner` / `resolved` attestation of the
model client actually constructed. The planner's token and temperature controls
are fixed in code, not read from settings. The planner settings are part of the
captured research policy, so an administrator change during a run stops the next
boundary with `external_configuration_changed` before further searches, page
fetches or planner requests.

### A clear message for background refusals

`OrchestrationInvocationDeniedError` keeps the refusal's stable code in
`authority_reason`, including when a sticky capture failure is raised again. The
new `access_failure()` in `functions_orchestration_schema.py` maps only
`external_identity_session_unavailable` to the new `external_session_required`
failure:

> This step continued in the background, where your sign-in is not available to
> confirm access to web search, web pages, deep research, agents or actions. Send
> the request again to use them.

Every other refusal stays `result_unavailable`. Dependency steps, saved waits,
final-answer verification, content preparation and image steps use this mapping.
Step, saved-wait, finalization and content-preparation failure events log the
code as `sc_authority_reason`. Exception text is never read and the code is
never shown to the user.

### Directory permission work reverted

An earlier, unreleased attempt on this branch granted `Directory.Read.All`, added
it to the deployers, and warned admins when it was missing. That work was
reverted, because orchestration no longer needs the permission. No deployer,
setting or app registration change is needed for this fix.

## Files modified

| File | Change |
| --- | --- |
| `functions_orchestration_external_identity.py` | `SessionExternalIdentityReader` replaces the Graph reader. The safe error types and codes are kept; their messages now say "Current user authorization" instead of "Current directory authorization". |
| `functions_orchestration_bootstrap.py` | Captures session roles inside a request context and builds the session reader. Graph, MSAL and `requests` use is removed. |
| `functions_orchestration_external_configuration.py` | Deletes `is_research_acquisition_profile_supported` and its refusal in `validate_acquisition`. |
| `functions_source_review.py` | `capture_research_planner_configuration` attests the planner without refusing a profile. |
| `functions_orchestration_invocation_capture.py` | `OrchestrationInvocationDeniedError(authority_reason)` keeps the refusal's validated code. |
| `functions_orchestration_result_contracts.py` | Adds `EXTERNAL_SESSION_UNAVAILABLE_REASON`. |
| `functions_orchestration_schema.py` | Adds the `external_session_required` failure and `access_failure()`. |
| `functions_orchestration_executor.py`, `functions_orchestration_composition.py` | Use `access_failure()` and log `authority_reason` on failure events, falling back to a `ResultUnavailableError` code. |
| `functions_orchestration_images.py` | Uses `access_failure()` for refused inputs. |
| `functions_orchestration_external_sources.py` | Documents the session-based identity contract. |
| `config.py` | Version `0.261.205`. |

## Validation

Updated and new functional tests:

- `test_orchestration_external_identity.py`: the real session reader, including
  the missing-session refusal, role bounds, per-call rereads, restrictions and
  fresh normal and optimized imports with networking blocked.
- `test_orchestration_external_bootstrap.py`: the real root captures roles only in
  a request context, keeps them for the worker thread, refuses background,
  anonymous and other-user sessions before any read, and makes no directory calls.
- `test_orchestration_research_pre_effect.py`: the gate is gone, planner profiles
  are admitted, a profile change on either side or after preparation is refused
  with no effects, turning off either planner switch alone on one side is
  refused, and default research settings run both planners.
- `test_orchestration_research_capture.py`: each planner request happens only
  after its attestation, with the attested deployment, and the result is
  retained and recovered.
- `test_orchestration_dependency_runtime.py`,
  `test_orchestration_source_authority_runtime.py`,
  `test_orchestration_external_preflight_adapter.py`: the session refusal reaches
  steps, saved waits, finalization and composition as `external_session_required`,
  while other refusals stay `result_unavailable`, and each failure event logs the
  refusal code as `authority_reason`.
- `test_orchestration_image_references.py`: an image step whose retained input is
  refused for a missing session reports `external_session_required` before any
  image is generated.
- `test_orchestration_external_error_markers.py`: the safe identity service and
  cancellation messages say "Current user authorization".

These nine files pass together: 674 tests and 92 subtests. Each of 31 deliberate
code breaks makes at least one of them fail. The breaks include trusting a
missing session, skipping the role check, reading exception text, and leaving a
planner switch out of the compared settings. The documentation coverage (7/7)
and site quality (6/6) checks also pass.

### Before and after

| Before | After |
| --- | --- |
| Every orchestrated web search, URL read and deep research step made several Microsoft Graph calls and failed without `Directory.Read.All`. | Steps use the signed-in session's app roles, as classic chat does, with no Graph calls. |
| Default Knowledge settings refused every orchestrated deep research step. | Query and link planners run after attestation, within existing limits. |
| All refusals showed "A required retained result is unavailable or changed." with no logged reason. | A missing session asks the user to send the request again, and step, saved-wait, finalization and content-preparation failures log `sc_authority_reason`. |

## Limitations

- A role removed in Entra ID applies until the user's session is refreshed, as
  in classic chat.
- A background continuation can't use web search, linked pages, deep research,
  agents or actions, because it has no signed-in session.
- If `Directory.Read.All` was granted to the app registration only for
  orchestration, it can be revoked.

## Related documentation

- [Retained external source access](../features/ORCHESTRATION_EXTERNAL_SOURCE_ACCESS.md)
- [Checkpoint recovery](../features/ORCHESTRATION_CHECKPOINT_RECOVERY.md)
- [Orchestration settings](../../admin/orchestration.md)
- [Logging tags](../../reference/logging-tags.md)
