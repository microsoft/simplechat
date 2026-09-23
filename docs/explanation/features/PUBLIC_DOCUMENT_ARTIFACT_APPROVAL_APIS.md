# Public Document Artifact Approval APIs (v0.261.134)

## Overview

The M3C backend adds generated-artifact approval for public workspaces on the
immutable-target route family, generalizes the document projection fence so one
implementation serves both group and public scopes, and computes each document's
action hints from current policy.

Implemented in version: **0.261.134**, tracked in
`application/single_app/config.py`.

Dependencies are the existing public workspace and public document containers,
the shared `decide_artifact_publication` in `functions_artifact_publication.py`,
the screening bootstrap consume-latch, notifications, and Content Screening. No
new setting, container, or cloud architecture is required.

## Scope, and why it changed

M3C was originally planned to include cross-workspace **sharing** for public
workspaces. At kickoff it was established that the infrastructure for that does
not exist at any layer: document retrieval is scoped to the owning workspace
only, the deployed public Azure AI Search index has no shared-access field, the
document access index has no shared-in path, and there is no public reviewer
concept. A document shared into a public workspace could never be retrieved by
the recipient.

Public sharing therefore needs an index schema change and a migration decision,
and is tracked separately. This milestone ships generated-artifact approval,
which is an owner-side decision about a document already in the workspace and
needs no share relationship.

## Immutable API family

All paths begin `/api/public-workspaces/W/documents/D`. `W` is the sole target;
the routes never read `activePublicWorkspaceOid`.

| Method and suffix | Purpose |
|---|---|
| `GET /publication` | Pending artifact review state for this document |
| `POST /artifact/approve` | Approve a pending generated artifact |
| `POST /artifact/reject` | Reject a pending generated artifact |
| `POST /artifact/cancel` | Withdraw one's own artifact request |

Every route carries `@swagger_route(security=get_auth_security())`,
`@login_required`, `@user_required`, and
`@enabled_required("enable_public_workspaces")`. The read rejects a request body.

## Review state and receipts

`GET /publication` returns `schema_version`, `public_workspace_id`,
`document_id`, `document_version`, `etag`, and a `publication` block with
`status`, `is_requester`, the requester attribution fields, and the permitted
`actions`.

Decision receipts use `status` of `applied`, `unchanged`, `queued`, or
`partial`, with the resulting `state` constrained per action:

| Action | Permitted result state |
|---|---|
| `approve_artifact` | `approved`, `approval_failed` |
| `reject_artifact` | `rejected` |
| `cancel_artifact` | `cancelled` |

Decisions are bound to the `etag` from the state the reviewer actually read. A
stale `etag` keeps the entered input and requires an explicit refresh rather than
resolving the conflict silently.

Cancellation requires that the actor is the original requester, so a requester
can withdraw their own request without gaining authority over anyone else's.

## Screening bootstrap is reused, not reimplemented

`decide_artifact_publication` is shared by the group and public paths. The
screening bootstrap consume-latch introduced for group workspaces therefore
already governs public artifact approval, and this slice reuses it unchanged.

Public-path coverage proves the latch's rules hold here too: a reserved
`scan_id` is reservation identity rather than evidence that a scan ran; absence
of a scan row cannot distinguish "never started" from "started, errored, row
removed", so admission requires recorded proof; the latch stores the consuming
operation identity rather than a boolean; and cancellation, rejection, and
errors all retain it.

## Scope-aware projection fence

`functions_group_document_projection_fence.py` now serves both scopes through a
`_ProjectionScope` with `_GROUP_SCOPE` and `_PUBLIC_SCOPE`, rather than gaining a
public twin. A second copy would have been a third place for one rule to drift,
which this programme has already paid for twice.

The source guard previously rejected any public document outright, which was
how a group fence was kept away from public data. It now matches the **exact
scope identity**:

```python
or document.get(scope.id_field) != scope_id
or document.get(scope.other_id_field)
```

The first clause matters most. Matching only the *kind* of scope would pass a
group-versus-public test while still letting one public workspace's hold act on
a different public workspace's document. Exact identity closes that.

Every existing property is preserved: no automatic expiry; ambiguous transport
failures leave the state `uncertain` and block other writers until explicit
reconciliation; known service refusals release the claim; only the exact
executing collaboration bypasses an ordinary claim through its execution-token
context variable; `GroupDocumentProjectionConflict.status_code` remains 409; and
ordering stays migration fence, then embedding preparation, then the projection
claim.

The two historical module-level context variables, `_collaboration_context` and
`_writer_context`, are kept as aliases of the group scope's own variables. They
are the same objects, not copies, so existing group callers and tests that read
them continue to observe the group context, and setting the public context does
not affect them.

## Action hints are computed from policy

The public read projector now computes both `document_actions` and
`document_collaboration_actions` fresh per document from current authorization,
matching the group projector.

This fixes a defect shipped in the public management release. The projector had
returned a fixed empty `document_actions` list left over from the read-only
browsing slice. Because the explorer gates every per-document operation on that
list, public delete, download, metadata editing, extraction, reprocessing, and
bulk tagging were all disabled against a real backend. The failure denied
rather than permitted, so no data was exposed and every endpoint still
reauthorized server-side, but the management surface could not act.

It went unnoticed because each half was tested against its own assumption: the
backend pinned the empty list while the browser fixtures mocked a populated one.
`functional_tests/test_document_action_hint_seam.py` now pins the seam itself.
It failed three of eight cases against the defect and passes all eight against
the fix, with the group projector as a control proving it discriminates.

Collaboration actions stay off the list path's critical cost. The publication
adapter is consulted only for documents that actually carry a generated-artifact
publication, decided by `public_document_has_publication`, so ordinary documents
incur no extra read. That predicate has a single definition in
`functions_public_document_policy.py`; the publication and collaboration modules
both import it rather than keeping their own copies.

## Context

`build_public_workspace_context` now emits `document_collaboration`,
`{schema_version: 1, operations: [...]}`, containing only the artifact
operations: `inspect`, `approve_artifact`, `reject_artifact`, `cancel_artifact`.
No share operations are advertised. `native_delegation` remains absent.

## Serialization

`public_document_projection_writer` and `public_document_collaboration_operation`
are in `PRIVATE_DOCUMENT_FIELDS`, alongside their group equivalents, and nowhere
else. No projection keeps a local redaction list. The drift guard in
`functional_tests/test_public_document_payload_redaction.py` covers both the
group and public reads modules.

## Testing and validation

| Suite | Coverage |
|---|---|
| `functional_tests/test_public_document_publication.py` | Approve, reject, cancel; authorization; requester-only cancellation; receipts; `etag` conflicts; cleanup; the screening bootstrap on the public path |
| `functional_tests/test_group_document_projection_fence.py` | Scope isolation in both directions, including a different workspace of the same kind |
| `functional_tests/test_public_document_publication_predicate_single_source.py` | One definition of the publication predicate |
| `functional_tests/test_document_action_hint_seam.py` | Action hints computed from policy on both projectors |
| `functional_tests/test_public_document_payload_redaction.py` | Private fields, including the drift guard across both reads modules |

At the closeout commit the M3C public suites and fence pass **188 cases**, the
public read and management regression passes **301**, the group publication and
collaboration regression passes **517**, route policy passes **8/8, 4/4, 2/2**,
and the broken-access-control scanner passes on all nine changed backend
modules.

## Related

- [V2 Public Artifact Approval](V2_PUBLIC_ARTIFACT_APPROVAL.md) — the browser surface
- [Public Document Management APIs](PUBLIC_DOCUMENT_MANAGEMENT_APIS.md)
- [Group Document Collaboration APIs](GROUP_DOCUMENT_COLLABORATION_APIS.md) — the group equivalent
- [Group Document Projection Coordination](GROUP_DOCUMENT_PROJECTION_COORDINATION.md)
