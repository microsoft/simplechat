# V2 Group Document Collaboration

## Overview

Implemented in version: **0.261.131**, tracked in
`application/single_app/config.py`.

The M2C native sharing and approval review surface is integrated into the
shared workspace shell, together with its backend slice. This page describes
the browser experience and the client contract it holds the server to. The
server endpoints are documented in
[Group Document Collaboration APIs](GROUP_DOCUMENT_COLLABORATION_APIS.md).

## Purpose and boundaries

A group that owns a document can share it with other groups, and a group that
receives one can accept it or remove its own access. Separately, a generated
artifact that a member asked to publish into a group waits for an owner-side
decision before it becomes an ordinary group document.

Both flows previously required the legacy group workspace page. M2C brings them
into the same native explorer used for My Workspace and for M2A/M2B group
browsing and management, so a reviewer never leaves the workspace to act on a
notification.

M2C covers inspection of sharing state, sharing to a target group, withdrawing
a share, accepting a received share, removing received access, and approving,
rejecting, or cancelling a pending generated artifact. It does not change what
a document *is*, does not alter screening policy, and does not migrate public
workspaces.

## Explicit operation boundary

Every collaboration call uses the immutable target family
`/api/groups/<group_id>/documents/<document_id>/...`, built in
`application/v2_ui/src/lib/documentCollaboration.ts`:

| Operation | Path suffix |
|---|---|
| `inspect` | `/sharing` |
| target lookup | `/sharing/targets` |
| `share` | `/share` |
| `unshare` | `/share/<target_group_id>` |
| `approve_share` | `/approve-share` |
| `remove_share` | `/received-share` |
| `approve_artifact` | `/artifact/approve` |
| `reject_artifact` | `/artifact/reject` |
| `cancel_artifact` | `/artifact/cancel` |

The group is part of the path, never a query parameter on a legacy route. A
server that does not implement these routes rejects the call rather than
executing it against whatever group the account currently has selected. Both
the group id and the document id are URL-encoded, and the document id is passed
through `requireWorkspaceId` first.

## Capability handshake is a hint, not a grant

The selected-group context advertises supported operations through a
`document_collaboration` block with `schema_version: 1`. Fresh document
projections advertise `document_collaboration_actions`.

`advertisedDocumentCollaboration` returns an empty set for anything that is not
a record with `schema_version: 1`, so a missing or unrecognized capability
leaves the review surface unavailable rather than falling back to personal
sharing. The client then intersects the advertised set with the actions on the
freshly read state, and the server revalidates every request independently.

## What the client refuses to act on

`parseDocumentCollaborationState` rejects a payload unless it identifies the
same group and document the user is looking at, carries an integer
`document_version` of at least 1, a non-empty `etag`, a known `relationship`,
and an `owner_group`. It additionally requires that `relationship === 'owner'`
agrees with `owner_group.id === groupId`. A response that fails any of these
raises a refresh-before-deciding error instead of rendering a decision.

Relationships are `owner`, `not_approved`, `approved`, `removed`, and `denied`.
The last two are repair-only tombstones: `isCollaborationRepair` treats them as
a state in which the only permitted operations are `inspect` and
`remove_share`, so a recipient can finish cleaning up access to a document that
is already gone without that being mistaken for a live grant.

Receipts are validated against the state each mutation is allowed to produce:

| Mutation | Accepted result states |
|---|---|
| `share` | `not_approved`, `approved` |
| `unshare` | `removed` |
| `approve_share` | `approved` |
| `remove_share` | `denied`, `removed` |
| `approve_artifact` | `approved`, `approval_failed` |
| `reject_artifact` | `rejected` |
| `cancel_artifact` | `cancelled` |

A malformed success receipt does not clear the reviewer's draft, so a decision
is never silently lost to an unparseable response.

## Eligibility rules enforced in the interface

These narrow what is offered. They do not replace server authorization.

- A superseded revision, an unavailable screening state, or a generated-artifact
  restriction removes mutations from the surface.
- `share` and `unshare` require the `owner` relationship, and `share`
  additionally requires the current revision.
- `approve_share` and `remove_share` are only for a non-owner relationship.
- Artifact decisions require the `owner` relationship and the matching action on
  the publication block. `approve_artifact` requires the current revision, and
  `cancel_artifact` requires that the actor is the original requester, so a
  requester can withdraw their own request without gaining authority over
  anyone else's.

## Notifications lead to the exact document

A native notification opens the referenced group and document directly in the
review surface, including when the document is not on the current page of the
explorer. A notification whose group or document does not match has no
navigation or activation side effect, and a link to a denied or deleted
document does not fall back to some other document. Switching groups clears a
pending link target.

## Concurrency and interruption

Decisions are bound to the `etag` from the state the reviewer actually saw. A
stale `etag` keeps the entered target and requires an explicit refresh before
the retry, rather than resolving the conflict silently.

Sharing captures the scope at the moment of the decision, so changing the
active group while a share is in flight does not redirect it. From version
**0.261.169**, each collaboration adapter, group and public, keeps one frozen
copy of the scope it was created for. Its request paths, its receipt check and
the public review's workspace name all read that copy, so a caller changing its
own scope object afterwards can't make a confirmed decision look unconfirmed.
A partial share
preserves its notice without replaying notifications, and an owner repairing a
partially applied unshare does not disturb a newly created grant. Losing and
regaining focus pauses decisions without discarding recipient input, and a
busy review never aborts a write already in progress.

## File structure

| File | Role |
|---|---|
| `application/v2_ui/src/lib/documentCollaboration.ts` | Adapter, URL construction, state/receipt validation, eligibility |
| `application/v2_ui/src/components/documents/DocumentCollaborationDialog.tsx` | Review and decision surface |
| `application/v2_ui/src/components/documents/DocumentExplorer.tsx` | Entry points, link targeting, selection behavior |
| `application/v2_ui/src/lib/groupWorkspaceNavigation.ts` | Off-page deep links into a specific document |
| `application/single_app/static/js/notifications.js` | Native notification click-through |

## Testing and validation

`ui_tests/test_v2_group_document_collaboration.py` covers the surface with 33
executable cases, including notification entry and mismatched links, owner
target search paging, `etag` drift, partial share and partial unshare repair,
recipient cleanup versus source deletion, publication approval not releasing
screening, requester-only cancellation, malformed receipts, focus and busy
handling, cross-group document-id collisions, and responsive review layout in
light and dark at 1440x900 and 390x844.

Run the V2 group and personal-scope browser suites together:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\ui_tests;$PWD\ui_tests\fixtures"
python -m pytest .\ui_tests\test_v2_group_document_collaboration.py `
  .\ui_tests\test_v2_group_document_management.py `
  .\ui_tests\test_v2_group_documents.py `
  .\ui_tests\test_v2_group_workspace_shell.py `
  .\ui_tests\test_v2_personal_document_scope.py -q --disable-warnings
```

127 cases pass at the current branch tip, alongside
`application/v2_ui` `npm run build`, which runs `tsc -b` before the production
bundle.

## Known limitations

Public workspace sharing is M3 and is not covered here.

## Related

- [Group Document Collaboration APIs](GROUP_DOCUMENT_COLLABORATION_APIS.md) — the server endpoints
- [V2 Group Document Browsing](V2_GROUP_DOCUMENT_BROWSING.md) — M2A read surface
- [V2 Group Document Management](V2_GROUP_DOCUMENT_MANAGEMENT.md) — M2B operations
- [Group Document Projection Coordination](GROUP_DOCUMENT_PROJECTION_COORDINATION.md) — why a revoked share cannot be republished by an older writer
- [V2 Shared Workspace Context](V2_SHARED_WORKSPACE_CONTEXT.md) — capability handshake
