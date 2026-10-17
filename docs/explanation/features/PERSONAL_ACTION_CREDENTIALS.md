# Personal action credentials

Fixed/Implemented in version: **0.261.333**.

Current application version: **0.261.345**.

Related version update: `application/single_app/config.py`.

## Overview

An authorized user can invoke an administrator's global action or a team's
group action with their own private identity, without modifying the action or
creating a personal copy. A credential-specific interaction pauses missing or
rejected authentication and provides a chat card for **Save and continue**.
Yamcs is the first connector adapter; the contract separates acquisition and
binding from plugin-specific authentication.

The action is usable directly through orchestration or through an assigned
agent. An agent is not required just to collect credentials.

## Dependencies and storage

The framework uses existing action governance, authenticated execution
identities, workspace identities, and execution continuation. Personal identity
secrets use the existing Key Vault storage when configured and enabled, or the
existing Cosmos identity storage otherwise. No new global capability toggle
is required: the administrator explicitly opts an action's slot into personal
credentials.

Credential setup for an authorized shared action does not depend on enabling
personal action/agent authoring. It does not grant those authoring permissions.

## Architecture

### Action requirements and independent slots

`credential_requirements` is action metadata, not a stored credential:

```json
{
    "credential_requirements": {
        "version": 1,
        "slots": {
            "proxy": {
                "source": "personal",
                "auth_type": "username_password"
            }
        }
    }
}
```

An omitted slot keeps its existing configured-action or workspace-identity
behavior. Switching a slot to personal explicitly removes competing shared
secrets and references. Existing `identity_id` references still resolve in the
workspace that owns the action; they are not reinterpreted as personal
references on global or group actions.

Yamcs supports `service` and `proxy`. Service credentials can be
`username_password`, `api_key`, or `bearer_token`; proxy credentials must be
`username_password`. Proxy Basic uses `Authorization`, so it can coexist only
with Yamcs No Authentication or API Key, not Yamcs username/password or bearer
authentication. Personal sources do not relax this transport restriction.

### Private binding and execution

The authenticated invoking actor supplies the identity, not the action owner,
a model argument, or a caller-selected user ID. Private bindings associate that
actor with the authorized action and slot. Credential resolution occurs when
the selected action is used; browsing a catalog or attaching an unused action
does not prompt for it.

Requests contain safe metadata and compatible identity choices, never entered
secrets. Action access, conversation ownership, current group membership,
destination/authentication state, and request revision are rechecked before
saving or continuing.

Web and scheduler bootstrap supply the existing authorization, identity, and
source-access owners through `functions_action_credential_runtime.py`. The
credential resolver and continuation journal never import those owners back;
an uninitialized runtime fails closed. See the
[import-boundary fix](../fixes/ACTION_CREDENTIAL_IMPORT_BOUNDARIES_FIX.md).

Private bindings, credential requests, and continuation checkpoints are excluded
from backup/restore and migration. Restoring an identity does not restore consent
to use it for a shared action: the user must explicitly select or supply an
identity again. Conversation deletion removes its outstanding requests and
checkpoints. The private-state owner also supports purging a user's entire
partition; SimpleChat does not currently expose a full user-account deletion
endpoint.

### Dedicated credential interaction

The SSE event is `action_credentials_required`, with a safe
`credential_request`. Both chat interfaces recover pending requests for the
owned conversation.

The credential form is distinct from ordinary elicitation. Its inputs are
ephemeral and submitted only to the credential API. They do not enter generic
prompt drafts, tool/model arguments, chat transcripts, exports, telemetry,
browser storage, or collaboration views. Input elements are cleared on
submission, cancellation, unmount, and conversation/account changes. This is a
data-flow boundary, not a promise that JavaScript can zero all browser memory.

### Continuation

Credential collection releases the stream rather than keeping a worker
waiting while the user types. Saving and continuing resumes the blocked work
under a server-owned, revision-fenced continuation. Completed operations are
retained, not replayed by retrying the whole question. A credential request is
not an approval for side effects.

Fresh chat reconstruction was fixed in **0.261.345**. New requests retain the
server-owned construction profile of the agent that actually paused. A global
agent selected in a per-user workspace therefore resumes with the workspace
tool inventory and defaults, not the different agent-core inventory. The
continuation constructs a fresh agent under the current actor and rechecks
configuration, model, tools, action access, and destination before executing.
It does not weaken the execution-signature guard or add Document Search to
workspace chat.

**Save and continue** resolves the saved identity at the blocked tool boundary
and persists the assistant's answer in the original conversation. A successful
save alone is not a completed action. Existing failed requests are not migrated
or replayed. See the
[chat reconstruction fix](../fixes/ACTION_CREDENTIAL_CHAT_RECONSTRUCTION_FIX.md).

Yamcs is read-only. Future write-capable adapters must handle operation
journaling and uncertain effects before acquiring equivalent continuation
support.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/action-credentials/pending?conversation_id=...` | Recover safe outstanding requests for an owned conversation. |
| `GET /api/action-credentials/<id>` | Read an authorized request's safe current state. |
| `POST /api/action-credentials/<id>/submit` | Select compatible personal identities or save new credentials for the requested slots. |
| `POST /api/action-credentials/<id>/continue` | Resume the server-owned blocked work, using only the expected request revision. |
| `POST /api/action-credentials/<id>/cancel` | Cancel the outstanding request with revision fencing. |

Mutation requests carry `expected_etag`. Submit carries slot-specific
`identity_id` selections or new `credentials`; continue does not carry a new
question, credentials, an alternate destination, or a caller-selected actor.
Both GET endpoints also return a session-bound `csrf_token`; mutations send it
as `X-CSRFToken`. Replacing a selected personal identity additionally requires
`expected_identity_etag`, separate from the credential request's revision.

## Authoring and use

In a Yamcs action's Authentication section, select **Each user's personal
identity** for the Yamcs credential, proxy credential, or both supported slots.
Choose the service auth method and enable proxy authentication when needed.
The action editor no longer asks for a shared secret for a personal slot.
Configured credentials and existing workspace identities remain available.

Save the action, optionally attach it to a shared agent, and publish through the
existing governance controls. Draft connection testing is not a substitute for
the invoking user's identity: use the saved action in chat to configure and
check that identity.

See [the user guide](../../guides/personal-action-credentials.md) for first use,
recovery, cancellation, and replacement.

## Failure handling

Missing/deleted identities and confirmed authentication rejection can trigger
credential interaction. A permission denial is not evidence that a password
expired. Timeouts, TLS/network errors, dependency failures, and secret-storage
outages are infrastructure/configuration errors, not credential-renewal loops.
An ambiguous service-versus-proxy rejection must not silently choose the wrong
identity to replace.

Shared credential failures belong to the action administrator; users are not
asked to overwrite an administrator's workspace identity.

## Testing and limitations

React coverage in `functional_tests/test_v2_action_personal_credentials.mjs`
executes real authoring, explicit shared-secret clearing, safe request
projection, transport, and stream-wait behavior.
`ui_tests/test_v2_action_credentials.py` drives the real React card, proving that
credentials stay out of stores/browser storage and continuation does not
submit another chat question.

Existing Yamcs authentication and workspace identity scoping regressions remain
relevant. `functional_tests/test_action_personal_credentials.py` covers the
credential contract, actor-private bindings, storage, and request lifecycle.
`functional_tests/test_action_credentials_sk_continuation.py` exercises actual
Semantic Kernel suspension and continuation, including nested agent execution.
`ui_tests/test_classic_action_credentials.py` covers the classic action editor
and private chat cards.

`functional_tests/test_action_credentials_chat_reconstruction.py` uses real
application loaders, authorization, identity storage, credential routes,
journals, and message persistence with offline Cosmos, model, and provider
transport. Unlike same-instance journal tests, it constructs a fresh agent for
continuation. `ui_tests/test_v2_action_credentials_backend.py` additionally
drives the bundled React card through real Flask routes and checks that the
provider result becomes the same conversation's assistant response.

Local validation for **0.261.333** passed 44 dedicated backend tests and 36
credential browser cases, plus the React type check and production build.
That initial broader Cosmos contract run was non-green: five existing cold-import
probes exceeded their 180-second limit on this Windows host. At **0.261.336**,
the complete network-blocked contract run passed **837 tests and 231 subtests**,
and the expanded credential slice passed **49 tests**. No test limits or
assertions were relaxed.

After integrating the updated V2 base at **0.261.337**, the credential slice
again passed **49 tests**, both credential interfaces passed **36 browser cases**,
and the complete network-blocked Cosmos gate passed **843 tests and 231 subtests**.
The merged inventory retains both credential and workflow boundary reviews:
**1057 owners, 400 doubles, and zero review gaps**.

This release exposes personal sources only for Yamcs. SQL/OpenAPI/MCP and other
compatible static-secret connectors are staged follow-on adapters. Provider
OAuth/OBO requires correctly scoped server-side token acquisition; SimpleChat
cookies must not become generic action credentials. Managed identity remains
the application's identity. Scheduled/background interactive prompting is
outside the first release.

Existing workspace identities do not expose Key Vault secret-expiration or
per-secret reminder options; this feature does not add them. An externally
enforced vault write denial is reported as a storage failure, not silently
bypassed or treated as a rejected service password.
