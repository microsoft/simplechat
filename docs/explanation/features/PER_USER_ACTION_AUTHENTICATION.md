# Per-User Action Authentication

Implemented in version: **0.261.107**

Version reference: `application/single_app/config.py`.

## Overview

Per-User Action Authentication lets an administrator share a global action without
sharing the account that authenticates its requests. The action describes which
credential it needs; the person submitting a chat turn supplies an identity from
their personal workspace.

The first adapter is the read-only Yamcs action. This uses the same conceptual
boundary as Microsoft Graph's delegated session authentication, but keeps manually
supplied credentials in Workspace Identities. It does not change Graph's OAuth flow.

## Dependencies and scope

The feature uses existing authenticated chat, action governance, Workspace
Identities, Cosmos DB, and `yamcs-client==2.1.0`. Key Vault remains optional under
the deployment's existing identity storage policy.

The new credential-source choice is available for global Yamcs actions. Personal
and group action definitions keep their existing authentication choices, and their
agents can use permitted global actions through the existing scope/merge policy.
Providing an identity does not require permission to author personal actions.

Both classic and React v2 support credential entry. V2 also provides focused native
global Yamcs authoring and editing for supported personal action identity types.

## Authentication profiles

| Profile | Personal identity type | Request authentication |
| --- | --- | --- |
| Yamcs login | Username/password | Yamcs token exchange using the native client |
| Gateway HTTP Basic | Username/password | HTTP Basic without Yamcs token exchange |
| Bearer token | Bearer token | Bearer authorization header |
| API key | API key | The native Yamcs `x-api-key` header |

One action authenticates to one target: Yamcs itself or a reverse gateway exposing
its API. Gateway Basic and Yamcs login are deliberately different profiles even
though their input fields are the same.

Other connectors must explicitly implement a compatible adapter before advertising
the new source. Arbitrary authentication scripts, custom credential forms, custom
API-key headers, OAuth/MFA adapters, and simultaneous gateway/upstream credentials
are not supported by this initial adapter.

## Action configuration

The optional `credential_requirement` field contains only configuration:

```json
{
    "credential_requirement": {
        "id": "<server-assigned-stable-id>",
        "source": "current_user",
        "identity_name": "Yamcs",
        "profile": "yamcs_login"
    }
}
```

The administrator chooses the profile and identity label. The server owns the
stable requirement ID and derives the native authentication fields. The action
must not also contain an inline credential or a workspace `identity_id` reference.

A label-only edit does not silently rename users' identities or break their
existing bindings. Changing the destination or profile requires a fresh approval
for that recipient. Names help users find identities; they are not authorization
identifiers.

## Private identity resolution

Each binding maps an authenticated user and requirement ID to an identity in that
user's personal partition. Resolution checks the action's current availability,
governance, identity ownership, credential type, and approved destination/profile.
It never falls back to the action creator, agent owner, conversation owner, or a
global credential.

Already approved compatible destinations can reuse a named identity across actions.
An ambiguous match requires selection. An unapproved destination requires explicit
confirmation before any credential is sent there.

Credentials are resolved at invocation time into a short-lived client. They are not
written into shared plugin manifests or process-global kernels. New per-user
connections require HTTPS and certificate validation, and protect the initial
login as well as subsequent calls with timeout and redirect checks.

## Storage and request lifecycle

Secrets stay in the existing personal Workspace Identities storage. With Key Vault
enabled and configured, the identity stores a scoped secret reference; otherwise
the existing Cosmos identity record stores the credential value. Storage failure
is an error, not permission to silently change storage policy.

The `personal_action_auth` container is partitioned by `/user_id` and holds
metadata-only binding and request records. Pending requests expire and use
conditional writes/claims to prevent stale saves and duplicate continuations.
They do not contain credential field values, the original message, or model history.
Portable backup/migration includes bindings, not transient requests.

Chat credential entry uses these authenticated endpoints:

| Endpoint | Purpose |
| --- | --- |
| `POST /api/action-auth/preflight` | Resolve required identities for the selected agent, action, or executable plan |
| `GET /api/action-auth/requests/<request_id>` | Read the current user's sanitized request state |
| `POST /api/action-auth/requests/<request_id>/credentials` | Validate and save or bind that user's identity |
| `POST /api/action-auth/requests/<request_id>/cancel` | Cancel the pending continuation |

Manual identity management continues to use the existing personal identity APIs.
The request ID is not an authorization token: every operation checks the current
user and referenced resources again.

## Chat behavior

Before execution, chat checks the selected agent's assigned protected actions.
When an identity is missing or needs approval, an app-authored **Connect Yamcs**
card collects the registered fields without sending the draft chat message.
After setup, the original request is sent once. Cancel leaves execution stopped.

The card and answers are not messages, plan-elicitation answers, model/tool
arguments, shared events, or browser-persisted state. Secret inputs are cleared
when the form is completed or abandoned.

Authentication rejection can require credential repair. Insufficient service
permission, network failure, and storage failure are separate outcomes. Repair
does not automatically replay a turn whose tools have already started.

## Shared conversations

The participant submitting a turn supplies its authentication identity, including
permitted retries and delegated agent calls. The conversation owner remains the
storage owner where existing collaboration behavior requires that; ownership is
not an authentication override.

The private card is visible only to the submitting participant. A sharing notice
explains that the posted prompt and returned data are visible to everyone who can
read the conversation.

Previously posted results remain shared history. Per-user authentication controls
new external calls; it does not filter old messages according to each reader's
service permissions or retract data after a credential is revoked.

## Code map

| Component | Responsibility |
| --- | --- |
| `functions_action_auth.py` | Requirement/profile contract and current-actor credential resolution |
| `functions_action_auth_state.py` | Owned bindings, private preflight requests, and credential lifecycle |
| `functions_action_auth_execution.py` | Execution gates and private control responses |
| `route_backend_action_auth.py` | Authenticated private credential API |
| `functions_workspace_identities.py` | Existing identity and secret storage |
| `functions_yamcs_client.py` | Shared Yamcs client authentication and connection validation |
| `semantic_kernel_plugins/yamcs_plugin.py` | Read-only Yamcs operations using invocation-local credentials |

## Testing and limitations

Functional coverage exercises actor isolation, request ownership, stale state,
protocol behavior, and execution gates before message persistence/broadcast.
`functional_tests/test_action_auth_execution.py` also covers portable auth-state
filtering. Existing Yamcs, workspace identity, route-policy, and delegation tests
remain regression anchors. UI coverage uses synthetic credentials in classic and
v2 browser workflows.

Live service access still depends on the account's Yamcs permissions and network
configuration. Non-browser jobs need an explicitly authorized actor and a ready
identity; they cannot display an interactive credential card. Partially executed
multi-tool turns are not automatically replayed after repair.

See the [user guide](../../guides/personal-action-authentication.md),
[Workspace Identities](WORKSPACE_IDENTITIES.md), and [Yamcs action](YAMCS_ACTION.md).
