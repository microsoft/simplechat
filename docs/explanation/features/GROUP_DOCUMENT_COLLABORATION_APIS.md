# Group Document Collaboration APIs (v0.261.131)

## Overview

The M2C backend adds immutable-target group document sharing and approval
decisions. A selected group is part of each URL, so an older worker cannot
ignore a new scope query parameter and act inside a different active group.

Implemented in version: **0.261.131**, tracked in
`application/single_app/config.py`.

Dependencies are the existing authenticated group-document Blueprint, group and
document containers, Search, source Blob Storage, notifications, and Content
Screening services. There is no new setting, container, or cloud architecture.
The M2A read APIs and M2B management APIs remain available.

This slice does not implement public workspace sharing, group saved views, or
screening-policy configuration.

## Immutable API family

All paths below start with `/api/groups/G/documents/D`. `G` is the acting
group and is the sole target; `D` is the document. No operation reads or
changes `activeGroupOid`.

| Method and suffix | Purpose |
|---|---|
| `GET /sharing` | Current collaboration state for this group and document |
| `GET /sharing/targets` | Eligible destination groups, with `search`, `page`, `page_size` |
| `POST /share` | Share with a target group |
| `DELETE /share/T` | Withdraw the share to target group `T` |
| `POST /approve-share` | Accept a share this group received |
| `DELETE /received-share` | Remove this group's own received access |
| `POST /artifact/approve` | Approve a pending generated artifact |
| `POST /artifact/reject` | Reject a pending generated artifact |
| `POST /artifact/cancel` | Withdraw one's own artifact request |

Every route carries `@swagger_route(security=get_auth_security())`,
`@login_required`, and `@user_required`. The two reads reject any request body.

Legacy `/api/group_documents/...` sharing routes keep their active-group
contracts. They are not aliases for the new routes.

## Collaboration state

`GET /sharing` returns:

```json
{
  "schema_version": 1,
  "group_id": "G",
  "document_id": "D",
  "document_version": 3,
  "etag": "\"0x8D...\"",
  "owner_group": { "id": "...", "name": "..." },
  "relationship": "owner",
  "actions": ["inspect", "share", "unshare"],
  "recipients": [{ "id": "...", "name": "...", "description": "...", "approval_status": "approved" }],
  "publication": null
}
```

`relationship` is one of `owner`, `not_approved`, `approved`, `removed`, or
`denied`. `removed` and `denied` are terminal repair states: they carry no
recipients, and the only operations offered are `inspect` and `remove_share`,
so a recipient can finish cleaning up access to a document that is already gone
without that being mistaken for a live grant.

Recipients are enumerated only for an owning group whose actor holds a document
manager role. `publication` is present only for a pending generated artifact and
reports `status`, `is_requester`, the requester attribution fields, and the
`actions` permitted on it.

`etag` is the document's current `_etag`. Clients must send back the value from
the state they actually read; the server rejects a decision bound to a stale
one rather than resolving the conflict silently.

## Decision receipts

Every mutation returns:

```json
{
  "schema_version": 1,
  "group_id": "G",
  "document_id": "D",
  "action": "share",
  "target_group_id": "T",
  "status": "applied",
  "state": "not_approved",
  "errors": []
}
```

`target_group_id` is present only for `share` and `unshare`. `status` is
`applied`, `unchanged`, `queued`, or `partial`. `state` is the resulting
relationship, constrained per action:

| Action | Permitted result state |
|---|---|
| `share` | `not_approved`, `approved` |
| `unshare` | `removed` |
| `approve_share` | `approved` |
| `remove_share` | `denied`, `removed` |
| `approve_artifact` | `approved`, `approval_failed` |
| `reject_artifact` | `rejected` |
| `cancel_artifact` | `cancelled` |

`errors` entries carry `stage`, `code`, and `message`. A `partial` status with a
populated `errors` list means the decision was recorded but one or more
downstream effects did not complete; the recorded decision stands and the
remaining effects are repaired rather than replayed as a new decision.

## Authorization is re-established per request

The selected-group context advertises a `document_collaboration` block with
`schema_version: 1`, and fresh document projections advertise
`document_collaboration_actions`. Both are interface eligibility hints, never
authorization grants. Each endpoint independently revalidates the actor's role,
group status, source relationship, revision currency, screening state, and
feature policy before acting.

Ordinary `User` membership does not acquire sharing or approval authority.
Artifact cancellation additionally requires that the actor is the original
requester, so a requester can withdraw their own request without gaining
authority over anyone else's.

## Durability and ordering

A share or approval writes a claim record before it applies effects, carrying
`schema_version`, an operation id, a request id, the document version, the
source group, the target group, the acting group and user, the action, the
resulting state, and a per-effect progress map. This is what makes a `partial`
outcome repairable instead of ambiguous.

Ambiguous transport failures are not treated as success or as failure. They
leave the operation recorded and unresolved so it can be reconciled explicitly,
following the same principle as the projection fence.

Collaboration changes coordinate with document projection writes through
`functions_group_document_projection_fence`, which prevents an older writer
from republishing a revoked access list. See
[Group Document Projection Coordination](GROUP_DOCUMENT_PROJECTION_COORDINATION.md).

## Serialization boundary

Collaboration internals are never serialized into a document payload. The
sharing ledger, the collaboration operation marker, the publication receipt id,
and the generated artifact source conversation, message, container, and blob
path are all members of `PRIVATE_DOCUMENT_FIELDS` in
`content_screening/access.py`, so they are redacted by both branches of
`public_document_payload` and therefore by every caller.

Share rosters (`shared_user_ids`, `shared_group_ids`) are deliberately **not**
in that set, because legitimate audiences render share status and counts from
them. Narrowing a roster to an audience is the responsibility of the projection
that knows the audience: `_project_group_document` rewrites `shared_group_ids`
for a non-owner-manager.

## Testing and validation

| Suite | Coverage |
|---|---|
| `functional_tests/test_group_document_collaboration.py` | Sharing state, targets, decisions, authorization, receipts |
| `functional_tests/test_group_document_publication.py` | Artifact approval, rejection, cancellation, cleanup |
| `functional_tests/test_public_document_payload_redaction.py` | Serialization boundary, including the roster exclusions |
| `ui_tests/test_v2_group_document_collaboration.py` | 33 browser cases over the review surface |

At the integration commit, the combined group collaboration, publication, read,
management, redaction, screening access, and read-boundary selection passes
**967 cases with 44 subtests**, the V2 browser suites pass **127**, route policy
passes **8/8, 4/4, 2/2**, and the broken-access-control scanner passes on all
changed backend modules.

## Related

- [V2 Group Document Collaboration](V2_GROUP_DOCUMENT_COLLABORATION.md) — the browser surface
- [Group Document Management APIs](GROUP_DOCUMENT_MANAGEMENT_APIS.md) — M2B
- [Group Document Read APIs](GROUP_DOCUMENT_READ_APIS.md) — M2A
