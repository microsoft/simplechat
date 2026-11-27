# Per-User Action Authentication: Unified Phased Specification

## 1. Status, baselines, and reading guide

| Item | Value |
| --- | --- |
| Status | **Revision 2 for implementation and release review; not a production sign-off** |
| Specification revision | **2**, superseding Revision 1 |
| Updated | 2026-09-17 |
| Local application baseline | **0.261.027**, `Development` at `b7ee5d1b` |
| Implementation foundation reviewed | Paul's `paullizer-user-bound-action-identities` branch, **0.261.107**, commit `0a0417e4bffd6d53dfa621e8d3d5c1f75168cee2` |
| Implemented in version | Foundation exists in the test branch at **0.261.107**; the complete unified release contract below is **not yet verified complete or production-released** |
| First customer release | Shared **global YAMCS action**, using each submitting user's personal **reverse-proxy HTTP Basic** credentials |
| Delivery | Release Phase 1 independently; later phases must not delay its agreed scope |
| Customer validation | Waiting customer validates its real environment after engineering release gates |

This revision uses Paul's implementation as the foundation and the combined design as
the production-readiness contract. Keep one framework, not two competing implementations.
The different version numbers are comparison baselines, not a proposal to change the
current application version. This documentation-only revision changes no code, storage,
deployment, feature flag, or release status.

Implementation statements refer to the pinned commit above, not an assumed future branch
head. See its [framework documentation](https://github.com/microsoft/simplechat/blob/0a0417e4bffd6d53dfa621e8d3d5c1f75168cee2/docs/explanation/features/PER_USER_ACTION_AUTHENTICATION.md)
and [user guide](https://github.com/microsoft/simplechat/blob/0a0417e4bffd6d53dfa621e8d3d5c1f75168cee2/docs/guides/personal-action-authentication.md).
The prior comparison was source/document review, not full security certification or live
customer validation. Requirements below describe the target, including work still needed.

For review, start with **Phase 1 scope (section 4)**, **consent (section 6)**,
**UI/UX (section 7)**, and **release gates (section 13)**. Sections 5 and 8-12 define the
engineering contract. Section 14 separates later releases.

### What Revision 2 changes

| Revision 1 proposal | Unified decision |
| --- | --- |
| New `credential_requirements` array, binding container, and parallel API prefix | Retain Paul's singular `credential_requirement`, `personal_action_auth`, and `/api/action-auth` request/claim machinery. Extend deliberately where lifecycle operations are missing. |
| Personal, group-owned, and global action definitions in Phase 1 | Global definitions first, conditional on customer fit. Authorized group agents may use permitted global actions; that is not group-owned definition support. |
| Proxy Basic plus an optional fixed upstream YAMCS API key in Phase 1 | One credential target/profile for the pilot. Add two-layer authentication only if the customer actually requires it. |
| Credentials must not be entered "in chat" | A private app-authored card on the chat page is acceptable; credentials must never be conversation messages, model input, or shared events. |
| Explicit retry after all setup | Keep one-time first dispatch after successful preflight setup. Require explicit retry once execution has started. |
| Key Vault mandatory for every deployment using this feature | Keep deployment-policy support; require Key Vault-backed identities for this customer's production pilot. Cosmos-resident credentials elsewhere require an explicit documented policy decision. |
| Disconnect removes the binding | Persist a disconnected state that reuse and stale pending requests cannot undo. Do not delete the reusable identity. |
| New statuses and UI prescribed as a replacement | Preserve existing protocol statuses; add persistent connection/verification presentation without replacing the state machine. |
| Instance/processor defaults included as an implied security boundary | Defaults are not access controls. Either enforce an explicit resource policy or state that downstream authorization governs resource access. |

## 2. Product contract and non-negotiable boundaries

> An action defines what credentials are required. The person submitting the request
> supplies the identity. SimpleChat uses that identity only for an authorized action and
> an approved credential destination.

For a global YAMCS action:

```text
Global action requirement: current_user + http_basic

Alice's private approval/binding -> Alice's personal identity -> proxy authenticates Alice
Bob's private approval/binding   -> Bob's personal identity   -> proxy authenticates Bob
```

The shared action never contains either user's identity ID, username, password, resolved
header, or authenticated client. Adding users does not require duplicating the action.

The framework must:

- Use the **submitting user**, including authorized shared-conversation turns, retries,
  and delegated agent calls. The conversation/action/agent owner is not a substitute.
- Resolve credentials at invocation time, never into shared kernels or process-global
  authenticated plugin instances.
- Recheck action enablement, governance, identity ownership, approved recipient/profile,
  binding state, and relevant revisions before use.
- Fail closed rather than select shared credentials, application identity, another
  personal identity, SSO, or anonymous access.
- Keep credentials outside model context, ordinary messages, tool arguments/results,
  portable action exports, browser-persisted state, and logs.
- Preserve legacy fixed-authentication behavior for definitions without the new
  requirement. A malformed or disabled new-mode definition must not fall back to legacy.

The action owner selects the required source. Choosing an existing personal identity
within that source is allowed; switching to a different source is not.

### Authentication is not a promise of personal data filtering

The proxy/YAMCS authorization policy determines what the authenticated account can read.
If Basic authentication ends at a proxy and YAMCS is unauthenticated, Alice and Bob may
still have identical downstream access. Do not advertise a unique "user perspective"
unless the customer confirms that its authorization layer enforces one.

Likewise, results posted in a shared conversation are visible under conversation access
rules. Per-user authentication does not filter earlier messages for later readers,
retract previously posted data, or make tool output private.

## 3. Foundation to retain and gaps to close

### Retain from the reviewed implementation

- Server-owned requirement IDs and credential-free global action definitions.
- Personal Workspace Identities as the credential store, with metadata-only auth records.
- Current-actor resolution and invocation-local YAMCS clients.
- Preflight before message persistence/broadcast, private pending requests, conditional
  save claims, and one-time execution continuation.
- Separate authentication rejection, service permission denial, connection failure, and
  storage failure results.
- Classic and v2 private credential forms, destination confirmation, secret clearing, and
  shared-conversation warnings.
- Current action/governance checks, identity revision checks, revocation hooks, and
  revalidation after secret retrieval.
- Four registered YAMCS profiles and their existing adapter code; do not rewrite or
  rename these simply to conform to Revision 1.

### Required changes or explicit policy alignment

| Area | Reviewed branch | Unified release target |
| --- | --- | --- |
| Reuse | Can derive a new binding from another approved binding at a compatible destination/profile | Phase 1 requires per-action consent. Broader reuse must be explicit and is deferred by default. |
| Candidate identities | Suggested identity name and compatibility filter the list | Rank matching names first, but allow another compatible identity owned by the caller. |
| Connection management | APIs center on pending authentication requests | Add compact persistent status, test/change, and actual disconnect using the same records and services. |
| Verification | `ready` represents current metadata readiness; explicit save probes credentials | Record when the exact connection versions were tested, without probing upstream on every preflight. |
| Identity versions | Uses identity ETags; cosmetic edits can invalidate a binding | Keep ETags for concurrency. Separate cosmetic changes from credential/security changes; never ignore all edits to avoid reconnection. |
| Transport | Enforces HTTPS/TLS and restricts redirects to approved origin/base path, with a three-redirect cap | Pilot defaults to no redirects. A needed restricted-redirect exception must be explicit and tested. |
| Network policy | Canonical recipient validation does not itself restrict resolved network destinations | Enforce connection-time destination policy, including explicit permitted private ground-segment hosts. |
| Provisioning | `personal_action_auth` is created from `config.py`; absent from reviewed deployment inventories | Provision through supported new-deployment and upgrade paths before feature activation. |
| Unattended contexts | Trusted contexts may use ready bindings | Pilot excludes unattended use without a separately approved run-as grant model. |
| Rollout | Per-action opt-in | Add framework disablement, coordinated rollout, rollback, and documented customer acceptance. |

These gaps are not a request to replace working request, identity, or transport machinery.
Implement the smallest changes that satisfy the security and lifecycle contract.

## 4. Phase 1 customer release boundary

### Included and independently deployable

- Global action definitions of plugin type `yamcs`.
- `credential_requirement.source = "current_user"` and profile `http_basic` for the
  customer's proxy login.
- Personal `username_password` identities with Actions usage.
- Authoring without requiring the administrator to have its own proxy account.
- Choosing, creating, testing, replacing, and disconnecting the caller's personal
  connection in classic and v2.
- Paul's private setup/repair card and a compact persistent **My connection** surface.
- Signed-in interactive chat, authorized collaboration, and delegated calls within that
  active turn. Async work may continue the authorized turn; that is not an unattended grant.
- Existing permitted global-action use by personal/group agents through scope/merge
  settings and governance.
- Concurrent users, shared global kernels, multiple workers, and persistent bindings.
- Existing read-only YAMCS tools, result limits, timeouts, and archive-SQL restrictions.
- Protected storage for the customer, per-action consent, lifecycle/revocation,
  safe diagnostics, provisioning, disablement, rollout, and rollback.

### Customer-fit prerequisite

Before calling this scope customer-ready, confirm:

1. A **global** action is acceptable, including its permitted use from the customer's
   agents/workspaces.
2. The proxy's **HTTP Basic credential alone** is the required credential target.
3. The customer has a canonical HTTPS endpoint, a trusted certificate/CA setup, and
   the expected proxy/YAMCS authorization policy.

If a group-owned definition or simultaneous fixed YAMCS API key is essential, record
and approve that scope change before scheduling release. Do not claim a global action
fully replaces group ownership, or that the single-profile implementation supports two
authentication layers.

### Authentication profiles and compatibility

| Profile/combination | Reviewed implementation | Phase 1 customer contract |
| --- | --- | --- |
| `http_basic` / Gateway HTTP Basic | Username/password sent as Basic without YAMCS token exchange | Required acceptance target; proxy authenticates the user |
| `yamcs_login` | Native username/password exchange for a YAMCS token | Keep implementation; independent qualification before advertising production support |
| `bearer_token` | Personal bearer token | Keep implementation; independent qualification |
| `api_key` | Personal API key sent using `x-api-key` | Keep implementation; independent qualification |
| Proxy Basic plus fixed YAMCS API key | Not supported by the new single-profile mode | Deferred unless customer-fit review makes it essential |
| Proxy Basic plus YAMCS native/bearer authentication | Competing use of `Authorization` in the existing model | Reject; do not add duplicate headers or silently disable one layer |

The branch can retain additional profiles, but the customer pilot exposes/enables only
qualified combinations. Do not remove working legacy fixed-authentication combinations.
Adding a second credential target later requires deliberate schema, UI, and adapter work.

### Excluded initially

- New-mode personal/group-owned action definitions or dynamic executing-group bindings.
- Generalized OAuth/SSO, MFA adapters, arbitrary credential forms/scripts, and new connectors.
- Scheduled workflows, File Sync, service-principal/inbound-MCP invocation, or any other
  unattended channel using this new mode without an explicit run-as grant.
- Automatic destination-wide consent, a connection marketplace, bulk credential import,
  administrative impersonation, or a large connection dashboard.
- YAMCS commands, writes, scripts, or changes to data-link state.
- Public-workspace action identities.

Unsupported modes and actorless contexts fail before credential/client construction.
Never infer authorization merely from the presence of a user ID or a ready binding.

## 5. Contracts and persistence: extend, do not replace

### Action requirement

Retain the branch's singular, schema-defined `credential_requirement`:

```json
{
  "credential_requirement": {
    "id": "966fbe2e-85dc-48bd-a0f4-c8e3e679130f",
    "source": "current_user",
    "identity_name": "Mission proxy account",
    "profile": "http_basic"
  }
}
```

This is an illustrative fragment of the reviewed branch contract; the UUID represents
a server-assigned ID. It is not available merely by adding this document to Development.

- Retain server-owned ID generation and validation. An ID or action reference is not
  an authorization token.
- The server derives destination/profile behavior from the authorized stored action,
  not a credential-submission body or model argument.
- Reject simultaneous inline credentials or fixed `identity_id` references in new mode.
  Do not use a second credential field to bypass single-profile validation.
- Keep legacy `auth` behavior when the requirement is absent; reject malformed presence.
- Add short owner-authored setup instructions through a schema-validated extension.
  This field is **additional work**, not part of the four-field example above. Do not
  smuggle it through unchecked metadata or weaken allowed-field validation.
- Label/instruction-only edits must not rename personal identities or revoke otherwise
  unchanged consent. Security-relevant destination/profile/source changes require review.

Do not introduce Revision 1's `credential_requirements` array,
`personal_action_identity_bindings` container, or replacement API prefix for Phase 1.
Those were proposed implementation preferences, not security requirements.

### Identity, approval, binding, and request

| Concept | Meaning |
| --- | --- |
| Identity | The current user's stored service credential and its usage/security metadata |
| Approval | Permission to use that identity for the specified action, recipient, and authentication profile |
| Binding | Which identity satisfies the user's action requirement |
| Pending request | A private, expiring setup/continuation record; not the identity or durable consent itself |

These are distinct semantics, not a mandate for separate databases or containers.
Use `personal_action_auth`, partitioned by `/user_id`, for the branch's metadata-only
binding and request records. Retain conditional writes and execution claims.

The reviewed container enables TTL with `default_ttl = -1`. Durable binding records do
not expire automatically; transient requests carry their own expiration/TTL policy.
A disconnected record must persist long enough to prevent recreation by stale approvals
or requests. Routine pending-request cleanup must not remove this protection.

Binding validation must relate the caller, action, requirement ID, identity, profile,
and recipient fingerprint. Derive the subject from trusted context; do not accept an
arbitrary user partition from a route body, tool parameter, action owner, or conversation
owner. Requests contain no credential values, original message, or model history.

### Concurrency and lifecycle extensions

- Keep ETags for conditional creation/update, replacement, disconnect, and continuation.
- Disconnect must invalidate old request/claim versions. A delayed credential save,
  request refresh, or compatible-binding lookup cannot reconnect without new user intent.
- Record verification time with the exact binding, credential/security, and
  requirement/destination versions it verified.
- Introduce a credential/security revision, or an equivalently tested distinction, so
  cosmetic identity edits do not require authentication again. ETags still protect
  concurrent writes; do not simply stop validating revisions.
- Password rotation invalidates verification and stale client state. Later invocations
  resolve the current credential or request repair; they never use a cached old password.
- If existing test-branch bindings cannot establish action-specific consent provenance,
  require confirmation. Do not silently convert inferred destination reuse into an
  explicitly approved per-action connection.

### Copy, import, and disaster recovery

Normal copy/import creates fresh action/requirement IDs and no personal connections.
Action exports contain requirement metadata, not personal bindings or resolved credentials.

An intentional disaster-recovery restore is a separate, privileged workflow: private
bindings may be restored only with explicit ownership mapping, validated destination
approval, credential availability, and access controls. Do not confuse this with cloning
an action for reuse. Never restore transient setup requests or consumed execution claims.

## 6. Consent and identity reuse

**Phase 1 defaults to approval for this action only.** The user may select the same
personal identity for another action without re-entering its password, but must confirm
that connection. Reusing a stored credential is not the same as inheriting consent.

Requirements:

1. Show the action, canonical recipient/base path, profile, identity choice, and intended
   use before approval.
2. Rank suggested-name matches first; offer **Choose another compatible identity** from
   the caller's own personal catalog. Name matching is a discovery aid only.
3. Do not automatically create a new action binding solely because another action has an
   active binding with the same recipient/profile.
4. A binding with explicit disconnected/revoked state remains blocked until the user
   deliberately reconnects. Removing it must not revive destination-wide approvals.
5. Changing destination, profile, or consent-relevant policy requires renewed approval.
   Display-only label edits do not.

Retain Paul's compatible-identity lookup and reuse machinery. Gate automatic cross-action
reuse behind an explicit broader grant model rather than discarding the implementation.
Destination-wide consent is a later-phase capability, not silently enabled pilot behavior.

A future broader choice could read:

> Allow this connection for compatible actions using this destination and profile.

That choice needs a defined set of covered actions/recipients, revocation, visibility,
and interaction with per-action disconnect. It is not authorized by a checkbox that only
confirms the destination for the current action.

## 7. UI/UX contract: three compact surfaces

### A. Global action authoring

Build on existing classic/v2 YAMCS authoring:

- Credential source: **Each user's personal identity**.
- Profile: **Gateway HTTP Basic** for the customer.
- Suggested identity name and short, validated setup instructions.
- Canonical destination displayed by the application.
- Explanation that every user supplies a private connection.

The administrator can save a valid requirement without having a personal connection.
Testing is always **as the current authorized caller**, never as another employee.
Authoring permissions do not grant access to private user credentials.

If an existing fixed-auth action is converted, explain removal of its fixed credential
reference from the definition. Do not delete a reusable identity or shared secret that
other actions still use. Do not permit personal-source mode to retain hidden legacy auth.

### B. Private connection card

Keep Paul's app-authored card on the chat page. Its placement does not make it a message.

```text
Connect Mission Telemetry                         Private to you

Destination: https://mission.example.com/yamcs
Authentication: Gateway HTTP Basic
Use the account issued for this ground segment.

Use an existing identity [select]
Suggested matches / Choose another compatible identity / Create personal identity

[ ] Allow this action to use my identity for this destination.

Cancel                                      Connect and continue
```

The endpoint is illustrative, not a customer URL. The privacy and destination text is
application-controlled; administrator setup instructions cannot replace or override it.

- Credential fields submit through the private API, never the ordinary chat send path.
- Keep values only in the active form; no local/session storage, URLs, telemetry,
  transcript persistence, shared events, or model/tool input.
- Do not return stored secrets for display. Clear secret fields on successful submit,
  cancellation, abandonment, or failed verification requiring new entry.
- Permit personal identity setup without requiring personal-action authoring permission
  or group identity-manager privileges. Keep the in-card path usable when the personal
  workspace UI is hidden.
- Implement keyboard/focus behavior, clear busy/error states, duplicate-submit prevention,
  and stale-request handling in both classic and v2.

### First dispatch versus repair

Keep preflight before execution and message persistence/broadcast.

**Connect and continue** (the existing branch says **Save and continue**) performs a
bounded read-only probe, saves/binds the identity and approval, and dispatches the
previously unsent request once after all required connections are ready.

- This is initial dispatch, not replay. Preserve server-side one-time claim protection;
  a disabled button alone does not prevent duplicate execution.
- Failure or cancellation leaves execution stopped. A reload or navigation must not
  send an abandoned draft automatically.
- A mid-turn authentication failure opens repair for the affected action. Repairing a
  credential does not repeat the whole turn or completed tool work.
- After execution started, use **Repair connection / Save connection**, then offer an
  explicit retry. Reauthorize the caller, action, binding, and destination before retrying.
- If the system cannot establish whether execution started, do not automatically retry.

The separate **Test connection** operation is read-only and never continues a pending
turn. Persistent connection management must not unexpectedly dispatch an old request.

### Shared-conversation notice

Retain Paul's warning and acknowledgment:

> Your credentials remain private. Your submitted message and returned data will be
> visible to everyone with access to this conversation.

The card is visible only to the submitting participant. Their turn and any authorized
delegation use their identity; another participant's later turn/retry uses that participant.
Previously posted results remain governed by conversation access, even if a reader has
narrower service permissions. Do not imply retroactive filtering or retraction.

### C. Persistent My connection

Add a compact surface on action details and in relevant agent readiness, reusing existing
identity and request services:

```text
My connection

Connected using: Mission account
Last tested: Today, 10:20
Approved destination: mission.example.com/yamcs
Approval: This action only

Test connection        Change identity        Disconnect
```

This is a persistent management view, not a new credential framework or large dashboard.
It should remain accessible without manufacturing a pending chat turn.

| Control/status | Required effect |
| --- | --- |
| Connect | Create/select an owned compatible identity, approve and verify it |
| Test connection | Probe as the caller; update version-bound verification evidence, not chat execution |
| Change identity | Reapprove replacement; explain effects of rotating an identity used by other actions |
| Disconnect | Block this action binding; leave the reusable identity intact |
| Connected / Configured | Metadata is valid; not a claim that the service was contacted on this page load |
| Last tested / Verified | Show timestamp; evidence applies only to the versions tested, not a promise of current reachability |
| Review required | Destination/profile or security policy changed; reconnect before use |
| Unavailable / Repair required | Explain missing/rejected identity or service failure without exposing secrets |

**Cancel setup**, **Disconnect action**, and **Delete identity** are different operations.
Confirm disconnect with: "Disconnect this action? Your saved identity will remain
available." Administrators do not get a cross-user test/impersonation control.

## 8. API and state-machine contract

Retain the implemented endpoints and private request lifecycle:

| Existing endpoint | Responsibility to preserve |
| --- | --- |
| `POST /api/action-auth/preflight` | Determine the current actor's requirements/readiness for the authorized selection |
| `GET /api/action-auth/requests/<request_id>` | Read the caller's sanitized pending request state |
| `POST /api/action-auth/requests/<request_id>/credentials` | Probe, create/update/select identity, and bind using conditional claims |
| `POST /api/action-auth/requests/<request_id>/cancel` | Cancel pending continuation; not revoke an existing connection |

Extend this namespace/service for persistent self-service connection status, compatible
identity listing, test, change, and disconnect. Exact new routes/fields must be reviewed
with the existing state machine; do not introduce a parallel set of Revision 1 APIs.

Every route must:

- Derive the actor from authenticated server context and reject mismatches with trusted
  execution context.
- Reauthorize the action/reference, requirement, request, binding, and personal identity
  on every sensitive read or write. Request IDs are not authorization tokens.
- Use the repository's Blueprint, Swagger, user-policy, CSRF/origin, no-store, and
  safe-error conventions.
- Return only the caller's needed identity labels/type and connection state, never
  credentials or other users' candidate metadata.
- Enforce bounded request sizes and shared attempt limits; do not conflate the two.
- Distinguish access denial, missing resources, stale claims, credential rejection,
  upstream permission denial, network failure, and storage failure.

Preserve `ready`, `credentials_required`, `execution_started`, and existing stable error
codes where they already express the result. Add lifecycle states as reviewed extensions,
not a rename to the earlier spec's proposed `identity_*` protocol.

### User-visible outcomes

| Condition | UI result | Required server behavior |
| --- | --- | --- |
| No approved connection | Connect account | No authenticated upstream request |
| Disconnected | Reconnect explicitly | No recreation via prior compatible approval or stale setup request |
| Wrong password / proxy 401 | Proxy rejected credentials; repair | No fallback or automatic password retry storm |
| Service 403 | Account lacks permission | Do not encourage changing a correct password as the only remedy |
| Recipient/profile changed | Review new destination/profile | Old approval cannot authorize sending credentials there |
| Identity removed, incompatible, or usage revoked | Select/create a valid identity | Recheck current identity state |
| Stale save or consumed claim | Refresh current request/connection | No overwriting a winner or duplicate dispatch |
| Network/secret store unavailable | Retry after service recovery | No changed credential source/storage policy |
| Action access revoked | Action unavailable | No credential workaround or misleading setup offer |
| Unsupported/unattended context or feature disabled | Explicit unavailable result | No guessed actor or legacy-auth fallback |

Secret write, identity write, binding approval, and continuation are not one distributed
transaction. Report partial failures accurately, preserve committed owned identities,
clean only unreferenced staged secrets, and make retries safe. Never claim ready or
dispatch the turn until the current binding and claim are valid.

## 9. Runtime, lifecycle, and isolation guarantees

At each action invocation:

1. Obtain the authenticated submitting-user context, action reference, conversation
   access, delegation lineage, and invocation identifier.
2. Recheck feature/action enablement, governance, and permitted execution channel.
3. Read the current action requirement and approved recipient/profile; stale kernel
   metadata cannot authorize credential use.
4. Resolve only that user's active, explicitly approved binding and compatible identity.
   Check disconnect/revocation, requirement fingerprint, and credential/security revisions.
5. Resolve secrets from the selected deployment storage policy. Revalidate state around
   secret retrieval so a racing revocation cannot silently authorize the next request.
6. Build a short-lived client that holds only this invocation's credentials, validate the
   outbound recipient/network policy, and perform bounded read-only work.
7. Dispose of clients and credential-bearing references on success, error, timeout,
   cancellation, and abandoned iteration/response paths.

Preserve Paul's invocation-local design. A shared kernel may hold credential-free
metadata and a resolver, not a personal user ID captured at load time, a resolved
identity, or an authenticated global client. Do not mutate a shared manifest to inject
credentials. Clear task/request context and rejection receipts between executions.

Do not add cross-user caches of credentials, authenticated clients, readiness authorization,
or personalized results. Phase 1 should retain fresh use-time binding/identity checks.
Persistent connection records are not worker-local credential caches. Future optimizations
need explicit principal/action/destination/version isolation and tested revocation behavior.

### Rotation and cosmetic edits

- Rotation on the same identity does not require editing the action. Resolve the current
  credential and invalidate old verification/client state; prompt repair when necessary.
- Name/description-only identity edits must not force reconnection just because the
  document ETag changed. Use a tested security-revision distinction, while retaining
  ETag concurrency protection for writes.
- Changes to credential type, Actions usage, approval policy, or identity deletion
  invalidate use. Do not treat them as cosmetic.
- A rejected credential revision must not poison a newer replacement or another user's
  identity. Clearing rejection requires an explicit successful probe of the relevant state.
- Revocation blocks subsequent authorization and inappropriate retries. An HTTP request
  already sent cannot be recalled; disclose that limit rather than promising cancellation
  of completed/in-flight external effects.

### Unattended use is not implied

The reviewed branch can resolve ready bindings from trusted execution contexts. For this
pilot, that must not enable new scheduled, inbound, or actorless execution implicitly.
A trusted actor ID proves identity context, not consent to run later on the user's behalf.
Background work serving the active authorized turn may preserve that turn's context;
independent unattended work requires the later run-as grant model.

## 10. Security policies and their UI consequences

### Credential storage

Retain the existing framework's deployment-policy support:

- With Key Vault enabled, use scoped secret references and fail on secret-store failure.
- Without Key Vault, the existing identity policy may store credential values in Cosmos
  identity records. This must be an explicit documented deployment decision, not an
  automatic fallback when Key Vault fails.
- **This customer's production pilot requires Key Vault-backed identities.** Validate
  actual backing for selected identities; enabling the setting does not prove older
  raw-password identities were migrated. Require explicit migration/recreation where needed.
- Do not force unrelated legacy consumers to change storage policy as a side effect of
  implementing the pilot.

Cosmos encryption at rest and Key Vault secret separation are different controls. Do not
describe Cosmos as an unencrypted service, or imply an application-readable password in
a Cosmos record has the same isolation/lifecycle controls as a secret reference.

Passwords, tokens, Basic headers, and resolved identity payloads must not enter ordinary
chat/history, logs, exports, or browser-persisted state. Stored secret values are not
returned to the connection form. Use existing redaction and protected identity handling,
including safe cleanup of staged secrets and failures.

UI consequence: for the customer policy, unavailable protected storage disables connect
and shows an administrative prerequisite message. Never silently save elsewhere.

### Destination and redirect policy

- Require canonical HTTPS destinations and certificate verification. Use the customer's
  approved private CA mechanism where necessary; do not make verification optional for
  personal credentials to pass an integration test.
- Bind consent to normalized scheme/host/effective port/base path and credential-delivery
  profile. Reject URL userinfo, ambiguous/traversal paths, or conflicting endpoint fields.
- Apply destination policy before resolving secrets and at connection time, including
  resolved addresses. Reject loopback, link-local, metadata-service and other prohibited
  targets. Explicitly permit legitimate private ground-segment networks through the
  deployment policy; do not blanket-ban private networking.
- Verify the policy on every SDK path that can send credentials, including login,
  archive calls, redirects, and any secondary transport used by enabled tools.

**Pilot default: canonical URL with no redirects.** Paul's branch allows a limited number
of same-origin/base-path redirects; that is a real policy difference, not equivalent to
rejecting all redirects. If the customer requires that behavior, record the exception,
retain a bounded count and approved path/origin, and test each hop. Never permit
cross-recipient redirects, credential forwarding outside approval, or TLS downgrade.

UI consequence: the author sees a clear validation error or the approved redirect policy.
The user reviews the actual canonical recipient, not an arbitrary alias or final URL
learned only after sending credentials.

### Resource boundaries

YAMCS instance/processor defaults are not permission boundaries. Retain the current
stale-configuration checks, but do not claim an allowlist exists because defaults are
included in a snapshot or fingerprint.

For the pilot, state honestly that the downstream proxy/YAMCS policy authorizes data
access. If the customer needs SimpleChat resource restrictions, explicitly enforce
allowed instances/processors on every tool override and require renewed approval when
that policy widens. Add this scope before release if required; do not rely on UI hiding.

### Authentication-attempt limits

Add shared limits for credential creation, credential verification, and connection tests,
keyed by subject plus action/destination as appropriate. Enforce across workers using
existing rate-limit infrastructure; button disabling, payload-size bounds, and conditional
claims are complementary but not rate limits.

Define bounded timeouts, concurrency limits, and retry/backoff. A rejected password must
not trigger automated repeated authentication or account-lockout storms. Store neither the
secret nor a secret-derived value in rate-limit keys. Choose and document numeric limits
with the customer's proxy lockout policy before enablement.

UI consequence: show an actionable wait/retry message, preserve non-secret form context,
and require fresh secret entry when appropriate. Do not expose upstream exception bodies.

### Import safety and observability

Preserve pure requirement/profile validation without initializing storage or clients.
Keep runtime dependencies, settings, and invocation context explicitly owned and supplied.
A local or dynamic import alone is not an import-cycle fix. Test real startup wiring,
failure paths and module cleanup using the repository's current instructions.

Record safe action/requirement identifiers, hashed subject where appropriate, relevant
versions, outcome category, duration, and correlation ID. Never log passwords, usernames,
headers, secret references with sensitive content, or full upstream responses.
Reuse existing logging; do not create a parallel telemetry framework.

## 11. Implementation work packages

All references below are repository-relative paths in the reviewed branch unless noted.
They are implementation anchors, not a requirement to recreate existing modules.

| Work package | Foundation to extend | Required completion evidence |
| --- | --- | --- |
| Contract and pilot scope | `functions_action_auth.py`, action schema/normalization, global action authoring | Keep singular requirement/profiles; validate global Basic pilot, mixed-credential rejection and owner-authored instructions |
| Consent and lifecycle | `functions_action_auth_state.py`, `functions_workspace_identities.py`, `personal_action_auth` | Per-action approval, all compatible personal candidates, durable disconnect, revision-safe change/rotation |
| Persistent self-service API | `route_backend_action_auth.py` and existing identity routes | Status/test/change/disconnect without a fabricated pending chat turn; private ownership, CSRF and concurrency tests |
| UI | `static/js/chat/chat-action-auth.js`, v2 `ActionCredentialCard.tsx`, `ActionIdentityCredentialForm.tsx`, `ActionAuthentication.tsx`, `actionAuthController.ts` | Keep private card and one-time continuation; add compact My connection and accurate verification/consent text |
| Runtime | `functions_action_auth_execution.py`, `functions_yamcs_client.py`, YAMCS plugin and execution context | Fresh actor-bound resolution, no shared clients/credentials, channel and destination enforcement |
| Network/attempt policy | Existing outbound validation and rate-limit infrastructure | Canonical recipient plus connection-time policy; distributed credential-attempt bounds |
| Provisioning/upgrade | `config.py`, `deployers/bicep/modules/cosmosDb.bicep`, `deployers/terraform/main.tf`, `deployers/azurecli/deploy-simplechat.ps1`, supported upgrade tooling | Provision metadata container with `/user_id` and correct TTL before activation; no required runtime container creation |
| Operations and release | Existing admin settings/governance, docs and deployment practices | Framework disablement, scoped opt-in, worker draining, recovery/rollback and customer acceptance evidence |

The reviewed container is configured from `config.py` but missing from the deployment
inventories. Close both **fresh-deployment and upgrade** gaps. Do not assume an application
identity has data-plane permission to create Cosmos containers during module import.
Use established infrastructure/provisioning credentials and runtime least privilege.

When implementing, update the appropriate action, identity, admin and chat-control guides,
feature inventory and release notes. Pin browser assets locally and keep API/schema
extensions explicit. No inventory or version change is required merely for this spec.

## 12. Engineering acceptance and regression matrix

Use and extend the branch's tests rather than create a competing test suite:

- `functional_tests/test_action_auth_contract.py`
- `functional_tests/test_action_auth_state.py`
- `functional_tests/test_action_auth_service*.py`
- `functional_tests/test_action_auth_execution.py`
- `functional_tests/test_classic_action_auth.mjs`
- `functional_tests/test_v2_action_auth_execution.mjs`
- `functional_tests/test_v2_action_auth_logic.mjs`
- `ui_tests/test_classic_action_auth_workflow.py`
- `ui_tests/test_v2_action_auth_workflow.py`

Retain relevant YAMCS, scoped identity, governance, delegation, import-boundary and route
policy regressions. Restore all test stubs and execute state-changing calls before
assertions. Compilation and fake-config-only tests do not prove real startup safety.

| ID | Scenario | Required result |
| --- | --- | --- |
| U1 | Alice/Bob use the same global Basic action | Proxy sees each respective principal; no other-user metadata exposure |
| U2 | Shared conversation and authorized nested delegation/retry | Submitting/root-turn actor retained; credential card private, posted results visibly shared |
| U3 | Ordinary group member uses a permitted global action | Personal setup works without group identity-manager or personal-action-authoring permission |
| U4 | Concurrent/interleaved calls through shared kernel and multiple workers | Zero credential/header/client contamination |
| U5 | Preflight missing credentials, cancellation, reload/navigation | No first dispatch before readiness; no abandoned draft sent |
| U6 | Double submit, transport retry, stale claim | At most one initial dispatch; no credential overwrite or duplicate continuation |
| U7 | Authentication repair after execution started or status unknown | No automatic replay of the turn or completed tools |
| U8 | Persistent Test/Change/Disconnect | Test does not dispatch; disconnect affects only this action and survives stale requests/reuse |
| U9 | Another compatible action or differently named personal identity | Reuse requires per-action approval; compatible owned identity remains selectable |
| U10 | Wrong password/401 versus resource403 versus network failure | Distinct safe errors; no fallback or uncontrolled retry |
| U11 | Rotation, cosmetic edits, deletion and Actions-usage revocation | Current security state enforced; cosmetic changes do not force unnecessary reconnection |
| U12 | Destination/profile/policy edits and forged identifiers | Reapproval when needed; no unauthorized recipient or other-user partition lookup |
| U13 | HTTPS/certificate policy, private-host approval, unsafe addresses and redirects | Connection-time enforcement on every used SDK path; default no redirects or reviewed bounded exception |
| U14 | Feature off, action off, membership/governance revoked, unsupported channel | Fail closed before credential use; ready binding does not bypass policy |
| U15 | Key Vault failure or selected Cosmos policy; partial identity/binding writes | Pilot storage policy enforced; no silent downgrade, false success or unsafe cleanup |
| U16 | New deployment and upgrade with restricted runtime identity | Container provisioned outside startup with correct partition/TTL; existing metadata preserved |
| U17 | Copy/import/export and intentional recovery restore | No copied personal connections in ordinary action copies; privileged restore validates ownership/approval |
| U18 | Legacy fixed-auth actions and other YAMCS profiles | Existing behavior unchanged; only qualified profiles advertised/enabled |
| U19 | Read-only tool set, bounds, all error/log/serialization paths | No write capability added; no secret leaks or cross-user result cache |
| U20 | Classic/v2 keyboard/focus, busy/expiry states, reconnect and sharing warning | Complete accessible private workflow and persistent My connection controls |
| U21 | Parallel credential attempts across workers | Shared limits prevent bypass, excessive probes and account-lockout storms |
| U22 | Coordinated rollout, disable/re-enable, rollback | Old workers never execute unsupported active manifests; no identity/credential deletion as rollback |

Concurrency regression floor: at least **100 alternating/concurrent A/B invocations**
through the same action and shared-kernel mode, with zero identity mismatches. This is
a concrete regression floor, not proof of every race or a production throughput SLA.

Exercise both Azure Managed Redis and Azure Cache for Redis configurations where used,
and deployments without Redis. Validate deployed browser/storage/transport behavior,
not only synthetic service calls. Benchmark steady-state resolution and test latency
against the customer's timeout/concurrency target without relaxing isolation.

## 13. Phase 1 release, customer acceptance, and rollback

### Engineering gates before customer enablement

- Customer-fit prerequisite in section 4 is recorded.
- Required tests pass, including negative authorization, concurrent invocation, approval
  provenance, disconnect races and credential storage failure.
- Real-module web/scheduler startup and relevant existing tests pass; inspect CodeQL
  annotations, not just successful analysis job conclusions.
- Provisioning and upgrade run with realistic runtime permissions before feature use.
- An authenticated end-to-end browser test passes on a representative environment.
  A skipped live test is a gap to close, not a pass.
- Pilot storage, private network, certificate, redirect and rate-limit policies are
  configured and verified.
- Operators can disable the feature and roll back safely.
- Documentation, release version, inventory, safe diagnostics and known limits are current.

Customer acceptance supplements these gates. The waiting customer validates the real
proxy and operational fit; it must not be the first test of cross-user credential isolation.

### Controlled enablement

Add a framework-wide disablement mechanism, default off for rollout, plus per-action opt-in.
The exact setting name is an implementation detail to finalize against existing admin
conventions; Revision 1's suggested flag name is not a pre-existing requirement.
Disabling the framework blocks new-mode execution even when bindings already exist.

1. Provision/upgrade `personal_action_auth` and verify permissions/TTL.
2. Deploy all participating web/runtime workers and scheduler consumers with the feature
   off. Drain incompatible old workers before enabling new definitions.
3. Configure Key Vault-backed pilot identities, destination/certificate policy, attempt
   limits and the agreed redirect mode.
4. Enable the qualified global Basic action for named pilot users/groups using existing
   governance. Do not seed a shared proxy credential.
5. Have users connect their own identities and complete the acceptance checklist.
6. Widen access only after customer and release-owner sign-off. Later phases are not
   prerequisites for releasing this complete Phase 1.

### Customer acceptance checklist

Use two customer-approved accounts, an unconfigured third user, read-only test data and
proxy-side evidence of the principal. Proxy logs must not record Basic headers/passwords.

- [ ] Global Gateway HTTP Basic meets the actual topology and ownership needs.
- [ ] Administrator saves the action without a personal connection.
- [ ] Alice/Bob see private setup and authenticate as themselves on the same action.
- [ ] Unconfigured user gets guidance without generating an authenticated upstream call.
- [ ] Shared-conversation and delegated turns retain the submitting actor; users understand
  that prompts/results, unlike credentials, are shared.
- [ ] Parallel requests and worker switches do not change which identity authenticates.
- [ ] A differently named compatible identity can be selected without duplicating its secret.
- [ ] Another action needs fresh per-action approval; no inferred destination-wide grant.
- [ ] Persistent test, change, rotation and disconnect work; disconnect stays disconnected.
- [ ] Authentication rejection, permission denial and temporary outage show distinct safe guidance.
- [ ] Destination change requires review; unsafe destinations and unapproved redirects are blocked.
- [ ] No credentials appear in chat, browser responses, logs, action exports or shared cache.
- [ ] Customer confirms actual proxy/YAMCS data authorization; no unsupported personal-data
  filtering claim is made.
- [ ] Disable/re-enable and rollback behave as documented.
- [ ] Customer and release owner record outcomes, blockers and approval before wider rollout.

The validation record identifies the application build/commit, environment/date, policy
choices, action profile/scope, anonymized account cases, correlation IDs and approvers.
Keep real account names, credentials, tokens and mission data out of public issues.
There is no claim of customer acceptance until this record exists.

### Monitoring and stop conditions

Monitor setup-required and rejected-authentication counts, conflicts, rate limiting,
secret-store/network failures and latency using safe identifiers. Any cross-user
credential use, secret disclosure, ignored disconnect, or fallback to unauthorized
authentication is an immediate stop/disable condition.

### Rollback

- First disable new-mode authentication and affected actions. Fail clearly; do not
  reinterpret requirements as anonymous, fixed, application or shared authentication.
- Drain active new-mode work and prevent older binaries receiving enabled unsupported
  manifests. A new kill switch alone cannot make old code understand the new contract.
- Leave additive auth metadata storage and personal identities intact. Cleanup/revocation
  is explicit; rollback must not delete credentials used elsewhere.
- Preserve legacy action availability where compatible. Re-enable only a tested version,
  with current authorization/approval checks and no automatic replay of prior work.

## 14. Later implementation phases

Phase numbering below supersedes Revision 1. Each phase is separately scoped and released;
do not expose selectable but unsupported modes.

| Phase | Deliverable | Release boundary |
| --- | --- | --- |
| **1: Customer pilot** | Qualified global YAMCS Gateway HTTP Basic with lifecycle and production controls above | Sections 12-13 complete; customer acceptance recorded |
| **2: Scope and YAMCS authentication expansion** | New-mode group/personal definitions, qualification of additional existing YAMCS profiles, and dual-layer auth where needed | Explicit scope permissions and per-combination client/header tests |
| **3: Additional adapters** | OpenAPI, MCP, SQL and other connectors through the same framework | Registered adapter capabilities, destination checks, client/pool isolation and lifecycle tests |
| **4: Executing-group bindings** | Manager-approved shared group connection selected from authorized execution context | Explicit group context, manager/use permissions, membership/revocation and no personal fallback |
| **5: Delegated and unattended execution** | Provider-specific delegated consent and explicit scheduled/noninteractive run-as grants | Audience/scopes, grant lifetime, subject state, reauthorization and reconnect/notification behavior |
| **6: Administration and broader reuse** | Destination-wide grants, connection inventory, lifecycle automation and justified caching | Visible grant scope/revocation, disconnect precedence, ownership-safe administration and cache invalidation |

### Phase 2 details

Support group/personal definitions without relaxing existing fixed-reference scoping.
Differentiate personal credentials used with a group-owned action from a shared group
credential. Requalify all existing profiles before making broader support claims.

Dual-layer proxy Basic plus upstream API key requires explicit independent requirements,
validation and presentation. Basic plus a competing YAMCS bearer `Authorization` header
remains invalid in the existing model; more profiles do not remove that conflict.

### Phase 3 details

Adapters advertise only supported authentication types/transports. Specify credentials
placement, destination binding, cleanup, result sharing and connection pooling per adapter.
Do not infer support from accepting `username_password` in a generic schema.

### Phase 4 details

A global action resolves a manager-approved binding for an explicitly authorized group.
A group-owned action uses its authorized group context. Never guess the group from the
action author, conversation owner or unrelated last-active-group preference.

Identity managers configure shared connections; authorized action users need not see or
edit credentials. Bindings reside in the correct group partition. Missing or ambiguous
context stops execution. Group members needing unique accounts still use personal mode.

### Phase 5 details

Keep signed-in delegated tokens distinct from stored Basic credentials and app-only
tokens. Specify provider audience/scopes, consent, refresh/reauthentication and isolation.

Scheduled/noninteractive use requires an explicit grant with subject, permitted action
and purpose, lifetime, revocation and renewal behavior. Recheck membership, governance,
identity/requirement versions and current subject state on every run. A ready browser
binding or trusted actor ID alone is insufficient. Do not persist copied credentials or
borrow browser sessions as run-as authority.

### Phase 6 details

Broader reuse is an explicit, manageable grant, not retrospective interpretation of
per-action approval. Define recipient/profile/action boundaries and renewal rules.
Per-action disconnect must override applicable broader approvals until deliberate reconnect.
Administrative visibility must not imply access to or execution with users' credentials.

Caching requires a separate evidence-based design with principal/destination/action/
credential-version keys, bounded lifetimes, and tested revocation. No convenience
feature here is a dependency of the customer pilot.

## 15. Implementation review and outstanding customer confirmations

| Confirmation | Required before |
| --- | --- |
| Global action acceptable through the customer's agent/governance setup | Phase 1 scope sign-off |
| Proxy Basic alone versus required upstream fixed API key | Integration scope/fixture |
| Proxy/YAMCS versions, canonical URL/base path, trusted private CA and network targets | Transport test |
| Data authorization at proxy/YAMCS and meaning of instance/processor defaults | Customer security acceptance |
| Key Vault backing for all pilot identities, storage permissions and rotation process | Pilot activation |
| Numeric shared attempt limits and upstream lockout policy | Pilot activation |
| Any necessary restricted same-origin/base-path redirect exception | Transport acceptance |
| Lifecycle API extension, consent migration, security revisions and disconnect persistence | Implementation review |
| Supported upgrade path, worker-draining plan and accountable release/rollback owner | Production deployment |
| Pilot accounts, observation period, concurrency/latency targets and acceptance owner | Customer test |

Retain per-action consent, customer Key Vault backing, no-redirect pilot default and
interactive-only scope unless a deviation is explicitly reviewed and documented.
Record changes in this spec rather than silently broadening runtime behavior.

Updating or approving this document does not certify the test branch, assert that gaps
are closed, or authorize production enablement before its engineering and customer gates.
