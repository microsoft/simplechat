# Agent credential authorization and re-entry (0.261.434)

Fixed/Implemented in version: **0.261.428**, recorded in
`application/single_app/config.py`.
Permission-aware chat recovery implemented in version: **0.261.429**, recorded
in the same configuration file.
Recovery button presentation updated in version: **0.261.430**.
Selected guided recovery implemented in version: **0.261.431**.
Shared-response integration validated in version: **0.261.432**.
Signed-catalog base integration recorded in version: **0.261.433**.
Recovery-test review corrections recorded in version: **0.261.434**.

## Issue and root cause

Agent-level credentials did not consistently retain an authorized owner and
connection boundary. Agent identifiers could be reused across user/group
partitions, while credential names were based on the agent identifier alone.
Inactive configuration could bypass save-time validation and later reach an
unscoped Key Vault lookup. A partial custom connection could also inherit an
application credential while retaining a different destination.

The reported MCP connection-test bypass was not reproduced on the reviewed
0.261.427 source: its scope/source checks rejected the tested foreign references
before credential access. This fix addresses the analogous agent runtime
boundaries; it is not evidence that an older deployed build is unaffected.

## Technical changes

`agent_credential_contracts.py` defines the supported GPT/APIM and nested Foundry
secret fields and a credential revision independent of the application version.
New references bind the owner/workspace, agent and credential field, with fresh
names on replacement. Client input cannot set internal readiness metadata.
Bindings also cover the credential's endpoint and, for Foundry service principals,
the token authority, tenant, client and scope. Retargeting a saved connection
cannot silently forward its unchanged credential to a different destination;
the affected credential must be replaced before that connection can run.

The Key Vault helpers and classic/native storage owners validate all fields,
including inactive configuration and deployments with Key Vault storage disabled.
They never copy an old vault value to manufacture a trusted replacement. Cleanup
skips untrusted legacy references; superseded new references are cleaned only
after a successful save.

`semantic_kernel_loader.py` selects an authorized connection before hydrating
its selected credential. Custom connections do not inherit global keys or token
providers. The authoritative stored agent supplies its connection details.
Foundry credential construction refuses unresolved agent secret references.

Classic and V2 agent editors identify affected fields and explain how to recover.
Native editors do not offer **Keep saved value** for a credential requiring
re-entry. The existing user-safe model-configuration error boundary carries
actionable failures to chat and workflow consumers.

`functions_agent_credential_recovery.py` adds a secret-free recovery envelope to
the existing JSON and SSE chat error boundaries. The runtime error carries only
its resource identity, never credentials or internal bindings. The response
adapter rechecks the signed-in viewer's exact personal, group, or global editor
policy and confirms the canonical stored record before advertising an editor
link. Group membership, owner-only policy, status and governance are reused from
the existing group boundary; site Admin is not a group-management bypass.

Classic and native chat render only validated local agent-editor URLs. The
link opens **Model & connection** in a separate tab and does not replay the
request. Non-editors receive group-owner or site-administrator guidance without
resource identifiers in the recovery envelope. Unknown or invalid contexts
never produce a link. Ordinary model-configuration errors retain their existing
response shape. Failed native retries carry their own transient recovery action;
historical persisted error strings do not store viewer-specific permissions.
The collaborative chat bridge retains that envelope only on the requesting
actor's JSON/SSE response. It never writes the editor permission/link into shared
message history or broadcasts it to other conversation participants.

Since **0.261.430**, the recovery action is a real button in both chat interfaces.
Its supporting text sits inside the button: after saving, return to chat and
select **Retry** on the message, or start a new conversation. The button still
opens the validated same-origin agent editor in a separate tab with no opener.
Keyboard activation and non-editor/unsafe-target rejection remain covered.
This presentation-only refinement does not change runtime credential bindings
or storage boundaries.

In **0.261.431**, `AgentCredentialRecoveryNotice.tsx` and the classic DOM renderer
implement the selected guided layout. An ordered two-step sequence separates
the connection update from the deliberate return to chat. The button remains
compact, only receives a validated local editor URL and opens with no opener.
Non-editors get **Request an update** with the server's existing contact
guidance, not a disabled or misleading edit control. Ordinary errors and
Foundry sign-in recovery retain their separate presentation.

The shared comfortable-width helper now keeps messages and the composer in a
720-pixel maximum reading column at the default text size, with matching
16-pixel mobile insets. Explicit **Wide** mode is unchanged. The notice uses
existing neutral and accent theme tokens rather than hard-coded light-only
colors.

The **0.261.432** Development merge combines the shared write-only response
projection with these runtime bindings. Canonical secret discovery retains all
agent slots, both classic configured-secret controls and the separate re-entry
notice render, raw editor responses recompute readiness, and cleaned list rows
retain their authoritative safe readiness metadata. An unchanged legacy inline
credential is preserved, not silently migrated into Key Vault when storage is
enabled. Shared-response regressions now check both bound and legacy records
against the real group cleaning/runtime helpers.

## Upgrade and recovery

Restart the application and scheduler/workflow workers when deploying this
update so already-initialized clients do not retain the old behavior.
Reload open browser pages to load the updated classic/native recovery controls.

Existing embedded agent-level Azure OpenAI keys, APIM subscription keys and
Foundry service-principal client secrets must be re-entered before that
credential can be used. An authorized editor can replace the affected value,
explicitly remove it, or select an approved saved model connection. Group
management and owner-only governance still apply; ordinary consumers should
contact someone permitted to edit the agent.

Saved model-connection credentials, reusable workspace identities, and MCP/action
credentials are not blanket-reset. Managed identity or delegated-user
authentication without an embedded agent secret does not require secret
re-entry. A retained inactive legacy override cannot become usable again simply
by switching authentication modes.

Re-entry does not revoke a provider credential. If incident assessment indicates
exposure, rotate the affected credential at its source and enter the replacement.
Legacy Key Vault cleanup requires a separate ownership assessment; the update
does not mass-delete those secrets.

## Validation and limitations

Regression coverage lives in:

- `functional_tests/test_agent_credential_security.py`
- `functional_tests/test_agent_credential_reentry.py`
- `functional_tests/test_agent_credential_owner_runtime.py`
- `functional_tests/test_agent_credential_recovery_links.py`
- `functional_tests/test_collaboration_group_agent_stream_fix.py`
- `functional_tests/test_group_agent_secret_scope.py`
- `functional_tests/test_group_agent_secret_roundtrip.py`
- `ui_tests/test_agent_credential_reentry.py`
- `ui_tests/test_v2_chat_retry.py`

The tests cover owner/field separation, foreign and inactive references,
Key Vault on/off behavior, untrusted metadata, legacy masks, explicit replacement,
approved defaults, classic/native round trips, SDK-shaped point responses and
visible recovery notices. They use synthetic credentials and external-I/O seams,
not live provider accounts.

Validation results for the combined credential fix and permission-aware recovery
in **0.261.429**:

- Focused backend, credential-owner, group compatibility and MCP route coverage:
  **128 passed**, with **38 passing subtests**. This includes role/status/
  governance denial, disabled workspaces, mismatched records, secret-free
  JSON/SSE envelopes and requester-only collaborative chat recovery.
- Classic/native browser recovery and saved-agent retry coverage: **42 passed**.
  The tests exercise exact-agent editor links, new-tab connection deep links,
  unsafe URL rejection and scope-specific non-editor guidance. Three additional
  production-UI screenshot captures with synthetic data passed.
- `python .\scripts\check_cosmos_response_boundaries.py --run-contracts`:
  **2,040 passed**, with **431 passing subtests**, and **zero review gaps**
  across 1,094 owners and 426 test doubles.
  Thirty chat owners, eleven collaboration owners and two unchanged SDK-default
  doubles were re-reviewed after their module/import fingerprints changed.
- TypeScript checking, production V2 build, classic JavaScript syntax, Python
  compilation, all **28** route-policy checks, all **13** documentation
  coverage/site checks, XSS checks, added-line access-control checks and patch
  whitespace checks passed.

These are not a claim that every legacy functional suite is green. The separate
MCP authorization-context suite retains three previously observed recovery
fixture/expectation failures. The broader workspace suite also has a previously
observed assigned-knowledge fixture failure caused by an incomplete Azure Core
stub; its other 138 cases passed.
Two source-pattern assertions in `test_chat_error_response_sanitization.py`
also fail on unchanged HEAD because their expected legacy error strings are no
longer present. The full-file access-control heuristic likewise reports an
unchanged conversation helper; the added-line scan is clean. None of these
baseline findings was hidden by a suppression or changed as part of this fix.

The **0.261.430** presentation refinement is covered by **42** classic/native
recovery and retry browser cases, plus desktop/mobile PNG captures of the actual
built interface. The cases verify real button semantics, embedded next-step
guidance, keyboard activation, isolated new-tab navigation and unchanged
permission/unsafe-URL rejection. TypeScript, production builds, JavaScript
syntax, XSS, documentation and whitespace checks pass. The storage inventory
remains at zero review gaps; no credential/storage behavior changed.

The selected **0.261.431** guided layout passed **63** browser cases/captures
covering recovery, retries, mobile controls, tables, two-column/stacked steps,
matching message/composer geometry and preservation of explicit Wide mode.
The focused backend/recovery and reading-width contract run passed **42** cases.
TypeScript, both production/harness builds, classic JavaScript syntax, XSS,
documentation and whitespace checks passed. The storage inventory still has
zero review gaps; its previously recorded full runtime gate remains the
credential/storage evidence.

The **0.261.432** shared-response integration passed **198** focused runtime,
projection and editor SDK tests and **65** shared-editor/recovery browser cases.
The renewed full Cosmos gate passed **2,074** tests and **431** subtests, with
zero review gaps across **1,102** owners and **429** doubles. Both V2 builds,
type checking, all route-policy/documentation checks and changed-line editor
XSS checks passed. The full-file editor XSS warning was also confirmed on the
unchanged Development source; it was not suppressed or modified in this merge.

The **0.261.433** base merge retains signed-catalog snapshot pinning around the
background chat worker alongside permission-aware credential recovery. The chat
storage owners themselves are unchanged; their module-level reviews retain
both catalog and credential runtime evidence. The declared catalog dependency
pins and upstream workflow timeout changes are preserved.

The **0.261.433** integration passed **183** focused catalog, task-pinning,
scheduler and credential cases and **59** browser cases. Both V2 builds and
type checking passed, along with **29** route-policy and **13** documentation
checks. The full owner-runtime gate passed **1,601** tests using the declared
pytest 8.4.2 test environment, with **1,104** owners, **430** doubles and zero
review gaps.

The **0.261.434** review corrections keep the SSE terminal-field mutation
outside its assertion so optimized Python cannot discard the normalization.
The UI regression module uses one import style for its shared workspace fixture
module, with explicit bindings preserving the original fixture objects,
constants and localhost-origin monkeypatch. These corrections do not change
the application credential behavior or the selected guided recovery design.
The complete affected functional and UI files pass **39** and **28** cases,
respectively. An actual SSE-branch probe also preserves normalization at Python
optimization levels 0, 1 and 2.

API response redaction and role-appropriate shared configuration projection are
separate, complementary boundaries. Runtime authorization must not be replaced
by UI masking or by authentication decorators alone.
