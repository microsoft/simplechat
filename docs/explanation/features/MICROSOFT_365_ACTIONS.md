# Microsoft 365 actions and conversation evidence (v0.261.129)

Implemented in version: **0.261.029**

Authorization bootstrap and workflow diagnostic handling updated in **0.261.030**.
See the [CodeQL remediation](../fixes/M365_CODEQL_REMEDIATION_FIX.md).

Cosmos SDK compatibility and streamed execution-context lifetime were corrected
in **0.261.031**. See the [agent streaming fix](../fixes/M365_AGENT_STREAMING_FIX.md).

In-chat connection, source permission bundles, and early agent binding were
corrected in **0.261.032**. See the [connection onboarding fix](../fixes/M365_CHAT_CONNECTION_ONBOARDING_FIX.md).

Consent callbacks were corrected in **0.261.033** to accept token responses
containing additional previously granted permissions without widening the
selected action or workflow authorization. See the
[consent scope-response fix](../fixes/M365_CONSENT_SCOPE_RESPONSE_FIX.md).

Profile can explicitly renew interactive Microsoft 365 sign-in in **0.261.034**,
independently of pending requests or workflow setup. See the
[reconnect recovery fix](../fixes/M365_CHAT_RECONNECT_RECOVERY_FIX.md).

Verified model token limits and selected-endpoint budget propagation were added
in **0.261.035**. See the
[model token-budget fix](../fixes/MODEL_CATALOG_TOKEN_BUDGET_FIX.md).

Chat mail/invitation review cards, current-state recovery, and claimed
interactive delivery were added in **0.261.038**. See the
[action-card repair](../fixes/M365_CHAT_ACTION_CARDS_FIX.md).

Mail and calendar history search, and the agent stream context and
interrupted-reply persistence repair, were added in **0.261.129**. See the
[stream context and persistence fix](../fixes/M365_AGENT_STREAM_CONTEXT_PERSISTENCE_FIX.md).

Related version update: `application/single_app/config.py`.
Associated issues: #1493 and #1523. Related future work: #954 and #956.

## Overview

Calendar, Email, OneDrive, and SharePoint Online are separate actions. They
share delegated authentication and transport rather than separate credentials
or application-wide file permissions. File retrieval grounds conversations in
Microsoft 365 content without a File Sync source or a workspace search index.

Existing combined Graph actions remain usable and editable, but cannot be
newly created or recreated after deletion. Their Email, Calendar, and OneDrive
operations also pass through source-sharing checks.

## Dependencies and configuration

- Existing agents/actions, conversation storage, and Microsoft Entra sign-in.
- A member account in the deployment tenant. Guest/mismatched accounts fail
  closed rather than falling back to another cached identity.
- Delegated consent for each selected source's supported operation bundle. Graph file search
  uses `Files.Read.All`; Copilot Retrieval requires both delegated
  `Files.Read.All` and `Sites.Read.All`.
- Configure delegated Microsoft Graph permissions on the existing Entra app
  registration as required by tenant consent policy. Admin consent may be
  required. This feature does not require application file permissions or
  SharePoint `Sites.Selected` grants.
- Existing chat Blob storage for retained evidence and resumable processing.
  This dependency is independent of whether enhanced-citation rendering is on.
- Key Vault for saved workflow connections. Set the server environment variable
  `M365_WORKFLOW_TOKEN_KEY_SECRET_NAME` to a dedicated Key Vault secret holding
  a base64-encoded 32-byte encryption key. Preserve historical key versions
  while rotating active connection caches.
- Register `/api/m365/connections/callback` as a redirect URI for workflow
  connection. This connection is separate from ordinary interactive sign-in.
- Interactive chat reuses the registered `/getAToken` callback with a separate
  state/nonce/PKCE-protected flow and the existing server-side login session.
  It does not require a saved workflow connection or Key Vault.

Admin Settings, **Agents & Actions**, offers `m365_retrieval_provider`
(`auto` or `graph`) and `m365_trusted_download_hosts`. These hosts control
server-side redirects, not what folders an action may search.

Cloud endpoints continue to use `AZURE_ENVIRONMENT`, `CUSTOM_GRAPH_URL_VALUE`,
`CUSTOM_GRAPH_AUTHORITY_URL_VALUE`, and `CUSTOM_IDENTITY_URL_VALUE`.
Custom chat storage uses the deployment's `CUSTOM_BLOB_STORAGE_URL_VALUE`
DNS suffix; Key Vault uses the configured cloud domain.

## Retrieval and cloud behavior

Auto prefers `v1.0/copilot/retrieval` only when the cloud supports it and the
data user's Copilot license can be verified without making a metered probe.
Unknown or unlicensed users use ordinary Graph search and file download.
Pay-as-you-go Retrieval is not enabled or used.

The published Copilot Retrieval API cloud table currently supports global
service, not Government L4/L5. Government uses the Graph path; custom
deployments use their configured endpoints. API or policy failures do not
authorize fallback to another identity or cloud. Permission denial and empty
search results are not reasons to bypass the source's decision.

SharePoint supports document-library files. Site pages, list rows, on-premises
SharePoint, and consumer Microsoft accounts are outside this release.
User instructions can narrow a query to a folder or file; actions have no
independent site/folder allowlist.

## Mail and calendar history

Implemented in version: **0.261.129**

**Read my mail** and **Read my calendar events** read any period the user's
mailbox still holds, not only recent mail or upcoming events. Both tools gained
parameters instead of new capabilities, so existing actions and their saved
capability choices keep working.

- Mail accepts literal `search` words and a `received_from`/`received_to`
  range, and can read `all` folders. Words are extracted from the model's text
  before they reach Microsoft Graph KQL, so operators and field prefixes are
  dropped. KQL dates are whole days in an unstated time zone, so the query is
  widened by a day and the exact bounds are applied to each returned message.
- Calendar always reads `me/calendarView`, which expands recurring meetings.
  Without a range it reads the next 30 days. `query` words are matched by the
  plugin, because a calendar view doesn't support Graph search. `order` and
  `starts_in_range` support reading backward and continuing without repeats.
- Every result carries `coverage` with `complete` and, when more items exist,
  `continue_with`: the arguments for the next call. Continuation uses a
  received or start time cursor plus one look-ahead item, because Graph advises
  against reusing a skip token in a different request. Items that share the
  cursor's time are returned by the next call; a tie group larger than `top` is
  reported in the note rather than silently dropped.

No permission changes: history uses the same delegated `Mail.Read` and
`Calendars.Read` scopes. The limits are Microsoft 365's: the primary mailbox
and default calendar only, no permanently deleted or retention-purged items,
and at most 1,000 results for one mail search. See the
[Email](../../reference/actions/m365-email.md) and
[Calendar](../../reference/actions/m365-calendar.md) references for the
parameter details.

## Sharing and approvals

Sharing preferences belong to the user, separately for Calendar, Email,
OneDrive, and SPO. Action owners can constrain the maximum acknowledgement to
one request, today, or indefinitely. Today means the next local midnight in the
confirmed IANA time zone. A saved Always preference never silently renews a
shorter action-limited approval.

Shared personal and shared group conversations require acknowledgement. A
single-user conversation does not become shared merely because it uses a group
workspace. Sharing previously private history also requires approval before
messages or evidence are exposed.

**Approval publishes retained source evidence as well as the answer.**
Conversation participants may reuse that snapshot without access to the
original file. A new remote read still requires the calling user's delegated
access. Revoking a source permission, sign-out, or disconnect does not recall
already-published evidence; conversation retention and deletion govern copies.

Publishing an owner-private capture validates current action capabilities and
sharing consent without requiring a fresh remote-read capability or source
token. Capture and publication retain separate request IDs and an actual-use
audit reference. Delegating another person's private capture still requires
valid Run as authorization.

One persisted approval is actionable in chat or Approvals and is discoverable
through notifications. Only the subject user can authorize their data use.
Conversation details show the acknowledgement audit. A decision can queue work
or require sign-in; it is not an execution-success result.

## Working memory and larger files

The fast windows are three content downloads, 25 MiB per file, and 12,000
file-context tokens per logical request, additionally constrained by actual
model room. Token estimates are conservative when a provider-specific tokenizer
is unavailable. These windows trigger an analysis choice rather than silently
declaring partial content fully analyzed.

The selected model's budget comes from its model override, endpoint override,
and verified catalog profile, resolved independently for each field. Shared
context, independent maximum input, and maximum output are separate constraints.
An explicitly configured Response Length is the generation allowance reserved
for that request; when no request ceiling is configured, a documented model
output maximum remains the conservative upper bound. A custom model with no
published output maximum needs an explicit total-generation cap.

For an arbitrarily named deployment, set `catalogModelId` to its actual
published model ID and retain the correct `modelVersion`. Capacity overrides
belong in Model Endpoints, not in Microsoft 365 connection settings. Unknown
limits and visible-only output allowances do not trigger reconnect: they produce
a model-budget configuration error instead. Image/audio/video history without a
verified token estimate requires a text-only conversation for file evidence.

Approved deeper analysis uses a separate writable analysis run over immutable
captured evidence. Each call processes a bounded batch, preserving full
captured source ranges, intermediate outputs, and progress checkpoints in chat
storage. Model summaries are compact navigation state, not a replacement for
captured evidence. PDF, Word, PowerPoint, text, and tabular files have extraction
paths; unsupported encryption and image-only content are reported.

Hard parser, model, download, and worker limits still apply. The extraction
implementation bounds text, expanded archives, row/column counts, and
document units. Results report coverage instead of silently treating a hard
limit as exhaustive analysis. Exact tabular calculations must use source rows,
not summaries.

Evidence manifests are paginated and versioned. Private staging is not a
generic downloadable attachment. Published snapshots are immutable, forks
receive independent references, and working files follow conversation retention
and archival. A conversation-level inventory marker is persisted before memory
writes so full cleanup does not depend on message-artifact registration completing.
Tokens never belong in these files.

## Review outgoing email and invitations

Manual Email and Calendar operations save a reviewable action before announcing
that it is ready. Chat receives the card independently of the model's prose,
including while an answer is streaming. Reloading the conversation or opening
**Approvals** recovers the same saved action if a stream or model response failed.
Workflow activity uses the same controls and authoritative record.

Only the data owner can **Send**, **Send now**, or **Cancel**. Other authorized
conversation participants receive a read-only summary without the private body,
recipient lists, or BCC identities. The owner reviews the subject, actual
recipients, and body; invitations also show time, timezone, location, and Teams
status. Bodies longer than 4,000 characters require loading the complete review
before the card exposes Send. Model tool results omit body previews and BCC
identities; executable controls are resolved on the server, not from tool prose.

Send verifies the current subject, tenant, cloud, conversation audience, selected
agent/action, enabled operation, and record revision. Concurrent confirmations
claim the same saved action conditionally; they do not create independent sends.
An expired sign-in returns to the same card after reconnect. Reconnecting or
approving source sharing does not send the action or rerun the original agent.

Email confirmation checks that the Outlook draft is still an unchanged draft,
then sends the immutable content reviewed in SimpleChat through `me/sendMail`.
The original Outlook draft remains so concurrent edits are not overwritten or
deleted. **Do not send that retained draft again.** Graph acceptance does not
prove delivery to every recipient. Cancel stops SimpleChat's pending delivery
locally and also leaves the draft. It cannot recall an already-claimed or sent
message or invitation.

Delayed chat delivery retains the existing short, in-process timer, not a
durable credential cache. The countdown only displays/refreshes state. After a
lost timer or restart, an overdue interactive action requires manual review
rather than a surprise background send. A timeout after a possible Graph write
requires checking Outlook; SimpleChat never blindly repeats an uncertain send.
Legacy actions without a trustworthy binding remain cancellable but must be
prepared again before sending.

Immediate delivery and marking mail as read keep their configured behavior.
Their tool results report completion or failure; they do not produce a second
Send button. Source-sharing, deeper-analysis, and workflow Run as decisions keep
their own approval flows.

## Workflows

Manual and scheduled runs use an explicitly selected, consenting Run as user.
The connection does not grant other workflows access automatically. Material
instructions, agent/action capabilities, inputs, or destinations require new
Run as approval. The full review is retained without truncating task or agent
instructions; reviews over 1.5 MB require splitting the workflow. A personal
workflow uses its owner's account; group Run as accounts must be eligible group
members.

Sharing, extended-analysis, Run as, and OAuth decisions are distinct. Paused
runs remain nonterminal; later schedule ticks do not create duplicate runs.
Task outputs and actual tool history survive approval waits. Committed
operations are not replayed. Uncertain external mutations require recovery
rather than being blindly repeated.

Profile uses one selection per source. Calendar consent includes event reads,
invitations, mailbox timezone, and recipient lookup; Email includes reads, draft
and read-state changes, sending, and recipient lookup. Microsoft displays these
permissions before consent. Existing narrower connections need an explicit
reconnect to acquire additional permissions; no permission is silently added.
Action capabilities and outgoing-delivery reviews still restrict actual use.

Workflow mail and calendar deliveries retain identity and approval references,
not bearer tokens. Scheduled delivery is recovered by the workflow scheduler
and rechecks the Run as connection, current workflow revision, and destination
before calling Graph. Manual outgoing actions notify the Run as user and are
reviewed in workflow activity or Approvals. Other group viewers cannot operate those controls.
Cancellation stops automatic delivery without needing remote permissions; a
previously created Outlook draft remains in the user's mailbox. Unknown delivery
outcomes are not retried automatically.

Connection caches are encrypted in the dedicated `m365_connections` container,
with Key Vault-protected keys and disconnect-generation checks.
`m365_execution_runs` stores request references and continuation state, never
credentials. Live grants, connection material, and deprecated combined Graph
actions are excluded from application backup/restore; reconnect and approve
workflows rather than restoring active authority.

## Implementation surfaces

Source-specific plugin facades use `functions_m365_operations.py`,
`functions_m365_transport.py`, and `functions_m365_retrieval.py`.
`functions_m365_execution.py` and `functions_m365_approvals.py` provide the
shared policy boundary. The web/workflow ownership layer supplies canonical
identity, action, and audience context.

`functions_m365_context.py` holds immutable context and fingerprint primitives
without importing configuration or storage owners. Web and scheduler bootstrap
inject the live Run as validator into the connection service. Missing
authorization wiring fails before credential access; validation still runs
before and after token refresh.

`functions_conversation_memory.py` and `conversation_memory_storage.py` provide
storage and checkpoint primitives. `functions_m365_analysis_jobs.py` separates
capture from analysis; `functions_m365_agent_continuation.py` preserves tool
results through approval waits. Broad migration of other tabular and workflow
features to this foundation is a later delivery phase.

## Validation and limitations

Functional coverage includes source isolation, policy ceilings and midnight
expiry, account binding, encrypted-cache lifecycle, role-specific approvals,
cloud routing, provider failures, extraction, private-history publication,
snapshot reuse, and continuation behavior. Real-module cold imports are run
with external network access blocked. Browser coverage exercises the real local
templates and scripts with deterministic API fixtures.

Live Commercial, Government, custom-cloud, and Key Vault qualification requires
the target tenant and deployment credentials. Offline tests do not establish
that a tenant exposes a particular API or that admin consent has been granted.
