# Microsoft 365 pending review and draft delivery (v0.261.325)

Fixed/Implemented in version: **0.261.325**

Related version update: `application/single_app/config.py`.

## Issue and root cause

Manual email approval previously sent a saved message snapshot through
`/me/sendMail`, leaving the prepared Outlook draft behind. Its link still pointed
to that draft after sending. Pending emails and invitations also lacked an
owner-authorized, durable editing and AI-assistance contract.

This change concerns new manual-review emails and local invitation preparation.
It does not delete old drafts, migrate historical actions, replay deliveries, or
change delayed/automatic delivery policies.

## Review APIs and authorization

The existing pending-action Blueprint now exposes:

| API | Behavior |
| --- | --- |
| `GET /api/msgraph/pending-actions/{id}/review` | Loads the owner's full saved fields and recent history; refreshes known Outlook draft changes. |
| `PATCH /api/msgraph/pending-actions/{id}/review` | Saves validated fields using `expected_version`, with `origin` and optional `assist_turn_id` attribution. |
| `GET /api/msgraph/pending-actions/{id}/history` | Returns bounded history, using `limit` (1–40) and `cursor` paging. |
| `POST /api/msgraph/pending-actions/{id}/assist` | Proposes field-constrained changes to an unsaved working draft; never saves or sends the proposal. |

Read responses contain `pending_action`, `fields`, `history`, and
`expected_version`. Assistant responses additionally contain the shared editor
assistant's `reply`, `candidate`, `changes`, and `warnings`, plus flat
`candidate_fields` and `assist_turn_id`. Suggestions and successful edits
advance the action version because their history is committed atomically.
All four owner review responses also expose `timezone_aliases`, a bounded copy
of the same fixed Windows-to-IANA mapping used by backend validation. This is
display metadata, not a setting or editable draft field. It lets the browser
display offset-bearing Graph instants in the selected zone while retaining the
original stored datetime strings until an explicit edit.

All routes retain login/user policy and Swagger security. Mutations require the
existing M365 CSRF token. Owner checks and current conversation authorization
precede full-field/history access; shared viewers do not receive them. Only
manual, bound, editable actions can be saved or assisted. Sending, editing,
cancelled and terminal actions cannot be edited.

For verified orchestration origins, authorized owner/shared-viewer projections
also include `producing_user_message_id`, `orchestration_run_id` and `turn_id`.
The capture callback derives these from the exact
owned, conversation-bound run after validating the stored step bridge. Their
fingerprint-bound provenance anchors list discovery before the live creation
frame arrives. Missing or unverifiable historical origins remain unlinked;
browser hints and arbitrary latest-message matching are not used.
New manual email and calendar records carry `review_provenance_version=1`,
included in their material fingerprint. Projection also requires this
creation-time marker; historical records are not relinked merely because their
existing execution binding contains origin fields. Delayed records do not gain
this manual-review provenance strategy.

Email fields are subject, body, content type, and To/Cc/Bcc address lists.
Invitation fields are subject, body, content type, attendees, start/end,
timezone, location and the supported online-meeting option. Unsupported fields,
invalid recipients, nonexistent timezone wall times and end-before-start dates
are rejected. Offset-bearing dates are converted into the chosen timezone.

## Durable changes and AI assistance

`functions_m365_pending_review.py` reuses `functions_editor_assist.py` and its
configured model/limiter adapters. Dedicated email/calendar kinds have closed
field-path allowlists. The model cannot propose owner, identity, delivery-policy,
approval or send operations. Normal model filtering remains in effect; no
additional conditional-send safety-review gate is introduced.
The assist route enforces the existing `is_action_assistant_enabled()` predicate
(`enable_action_ai_assistant` plus Semantic Kernel availability) before resolving
model clients. Direct editing remains available when this existing assistant
setting is off; no new capability setting is introduced.

New manual review Save and approval also reuse configured `chat_output` content
screening/Content Safety checkpoints. They check subject/body and all recipient
or attendee addresses; draft approval checks the current Outlook material even
though the draft-send POST has no JSON snapshot. Existing sharing, selected
source/capability, and audience authorization continue through the restored
context and Graph token checks. Disabled scanners and configured allow-unchecked
decisions keep their existing behavior; this is not an additional AI approval
gate. A blocked decision prevents the patch/send and returns a safe policy error.

The model receives at most the shared assistant's 20 bounded turns from this
action's server-owned thread. Client conversation limits are validated, but a
client thread cannot replace another action's durable context. A result based
on a superseded action version is rejected.
An exact retained submission retry is replayed before rejecting its original
action version: a lost response can be recovered without another model call or
history append. The owner must still have an editable action, and its stored
instruction/field fingerprint must match. Replay returns the current version;
unknown submissions with stale versions and changed submission material conflict.

`functions_m365_review_history.py` stores a separate record in the existing
owner-partitioned pending-action container. An atomic batch updates the action
and history together. History retains at most 40 records and 1,600,000 serialized
bytes; oldest entries expire from that bounded window. Full review fields are
limited to 750,000 serialized bytes, with a 50,000-character body limit.
Revisions retain previous/new fields for restore, direct/AI attribution, and
saved/applied status. Suggestions retain the instruction, reply, exact unsaved
source fields, candidate and warnings so reopened proposal undo has both sides,
without duplicating giant model-result snapshots.

History survives closing/reopening the editor. Send/cancel removes its editable
history without deleting the final delivery receipt. Terminal reads retry
interrupted history cleanup and never expose old edit history. Existing owner
data management already deletes records from this container, including the
separate history record.

## Email save and send lifecycle

New manual email preparation requests `Prefer: IdType="ImmutableId"` and saves
`graph_send_strategy=draft_send_v1`. Editing claims a conditional action lease,
patches the actual draft with its Graph ETag, and atomically saves updated review
material, fingerprint and history. A known external Outlook edit refreshes the
review rather than being blindly overwritten.

A Graph/Cosmos partial failure never reports successful persistence. It leaves
the action non-sendable until a read-only draft refresh reconciles it. If storage
is unavailable even for that failure marker, the edit claim expires after ten
minutes so reopening can reconcile it. Calendar Save writes only local review
material; it never creates an Outlook event or sends invitations.

Approval sends the current email draft via `/me/messages/{id}/send`. The
pre-send read is not an atomic guarantee against concurrent external Outlook
edits and does not introduce another approval pause. A detected change refreshes
the final reviewed projection while the existing claim/version checks still
protect application-side concurrency.

The existing one-claim/no-replay rule remains: uncertain POST outcomes require
Microsoft 365 review and cannot trigger an automatic repeat. Calendar approval
retains the transaction ID and records the created event ID/link.

## Truthful links and compatibility

Graph acceptance is not proof of recipient delivery. After draft-send
acceptance the draft link is cleared. A maximum of five incremental, read-only
immutable-ID lookups can discover the non-draft sent-message link. Each attempt
is claimed in storage before contacting Graph; minimum intervals of 5, 15, 30
and 60 seconds prevent rapid or concurrent refreshes exhausting the retries.
The lookup window ends five minutes after acceptance. Responses expose
`link_status` (`pending`, `available`, `unavailable`), `link_next_lookup_at` and
`link_lookup_deadline_at` so the UI can poll at the next eligible time without
sleeping inside a request or worker. While lookups remain eligible,
`link_pending` is true. Exhaustion or deadline expiry clears pending and
truthfully reports the link unavailable, with guidance to check Outlook Sent
Items; further detail refreshes do not contact Graph or send again. Lookup
failure never reverts accepted status or enables another send.

The client receives `web_link_kind=draft`, `sent`, `retained_draft`, or `event`.
Older retained-draft actions retain their original snapshot behavior and
fingerprints; delayed/automatic email handling is unchanged.

## Validation

`functional_tests/test_m365_pending_review.py` covers full-field reopening,
direct/AI revisions, local calendar saving, owner/CSRF/version enforcement,
history bounds/paging, stale AI results, invalid fields/timezones, Graph ETag
conflicts, concurrent save/send/cancel, partial-save reconciliation, actual
draft send, delayed sent-copy visibility, bounded link lookup and no replay.

`functional_tests/test_m365_pending_action_provenance.py` executes the real
step bridge/capture with SDK-shaped storage, covering owned-run provenance,
authorized shared projection, fingerprint/conversation mismatches and historical
missing identities. It runs alongside the orchestration operation runtime suite.

The focused pending-action/delivery/authorization/editor-assist suites and route
policy tests passed with mocked Graph/model calls and SDK-shaped Cosmos
responses. No live mail or invitation was sent during validation.
