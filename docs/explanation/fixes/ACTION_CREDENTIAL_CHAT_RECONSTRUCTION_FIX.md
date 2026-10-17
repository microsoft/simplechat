# Same-conversation action credential reconstruction fix

Fixed/Implemented in version: **0.261.345**.

Related version update: `application/single_app/config.py`.

## Issue and root cause

A personal action identity could save successfully, yet **Save and continue**
failed before the blocked tool executed. Starting another conversation used
the saved identity successfully.

Initial per-user chat and continuation constructed different kernels. The
initial workspace loader omitted Document Search and defaulted Fact Memory to
enabled. Continuation always used the agent-core loader, whose inventory and
defaults differed. The retained execution-signature guard correctly rejected
this application-induced change. A global agent selected in a per-user
workspace still uses the per-user execution profile; storage scope alone
cannot identify the right reconstruction path.

Production telemetry established successful credential submission followed by
an `ActionCredentialError` during ordinary chat continuation. It did not record
the exact error subcode. A local regression reproduced
`credential_execution_changed` through fresh reconstruction.

## Implementation

`semantic_kernel_loader.py` shares the existing core registrations through
explicit per-user, global, and agent-core construction profiles. Each retains
its previous capabilities and defaults. `LoggingChatCompletionAgent` carries
the actual profile as excluded server metadata, not model or browser data.

`agent_delegation_runtime.py` records that profile in new chat continuation
descriptors after any delegation-driven reconstruction. The credential route
rebuilds a fresh invocation-local kernel using that profile, the exact selected
agent, current settings, and the current authenticated execution bridge.
Delegation and orchestration retain their existing agent-core defaults.

The signature comparison, current authorization, destination confirmation,
private identity storage, conditional writes, and single-use continuation
claims remain in force. Credentials are read at the actual tool boundary.
Completed tool results stay in retained history; the original question is not
reposted. Completion still requires the resumed operation and screened
assistant response persistence.

The route now records an allowlisted failure code, static execution stage,
exception type, and hashed request/conversation correlations through the
existing telemetry sanitizer. It does not log credential values, exception
messages, stored history, headers, or provider bodies.

## Scope and usage

For new requests, enter credentials or select a compatible saved personal
identity and choose **Save and continue**. The blocked action runs with that
identity and its response returns in the original conversation, including
conversations that already contain messages.

No settings, routes, browser controls, or deployment migration are added.
Previously failed requests are not repaired, reset, migrated, or replayed.
Requests without profile metadata retain their historical reconstruction path.
Actual configuration/access changes continue to stop execution rather than
being treated as password failures.

## Validation

`functional_tests/test_action_credentials_chat_reconstruction.py` runs cold
real-module application probes with only external I/O doubled. It covers
fresh agents, actual Yamcs protobuf results and Basic authorization,
new/selected/replaced identities, global/personal/group execution, existing
conversation history, streaming, absent/explicit Fact Memory settings, prior
completed tools, duplicate continuation, and normal/optimized Python.

Negative cases retain the change guard for instructions, model, tool inventory,
destination, conversation ownership, and group membership. Authentication
rejection must re-challenge; response-persistence failure cannot report success
or automatically replay the operation. Secret sentinels must remain absent
from SSE, telemetry, model history, and private continuation metadata.

`ui_tests/test_v2_action_credentials_backend.py` drives the real React card
against actual Flask credential/message routes and a scripted provider. It
requires one save, one continuation, no replacement chat request, cleared
credential inputs, and the persisted assistant answer in the original chat.
Existing credential, orchestration, bootstrap, and browser regressions remain
applicable.

The focused backend run passed **154 tests**, including all **16** new
reconstruction scenarios. The React credential suite passed **23 browser
tests**, including the real-backend save-to-answer scenario. Route policy
coverage passed **30 tests**; documentation checks passed **7 coverage** and
**6 site-quality** checks. The Node credential transport checks also passed.
The network-blocked Cosmos gate passed **1,079 tests and 244 subtests**, with
**1,066 reviewed owners, 409 doubles, and zero review gaps**.

The broader plugin run has one unchanged baseline failure:
`test_logged_core_plugins.py` records no thought events for its synthetic
tracker. It fails identically in isolation with unchanged application source.
Nine AST-extraction failures in `test_agent_delegation_entrypoints.py` were
reproduced identically against unchanged baseline source. Those fixtures omit
dependencies referenced by the extracted functions; this fix does not change
them or claim these broader suites are green.

## Before and after

Previously, a successful save could be followed by rejection of the
application's own different reconstruction, despite valid credentials.
Matching construction now lets unchanged, authorized work resume while
preserving rejection of genuine configuration or access changes.

See [personal action credentials](../features/PERSONAL_ACTION_CREDENTIALS.md)
and the [user guide](../../guides/personal-action-credentials.md).
