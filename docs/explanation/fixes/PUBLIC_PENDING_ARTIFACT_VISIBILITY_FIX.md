# Public Pending Artifact Visibility Fix

## Issue

A generated artifact that someone asks to publish into a public workspace waits
for a manager's approval. Until then it isn't published. But V2 showed it to
everyone who can read the workspace, which is every signed-in user:

- the V2 public document list showed its row, with its title, abstract, tags
  and "Pending approval" status, and counted it in the totals, places, facets
  and tag counts;
- a detail or version read returned it;
- the publication read answered a reader with the requester's ID, name and the
  time of the request;
- a reader's decision request answered differently for a pending artifact than
  for a missing one, which confirmed it existed;
- the V2 chat document picker, which reads the classic
  `/api/public_workspace_documents` and its `/tags`, listed it, and counted its
  tags, for every reader.

## Root cause

The public projector, `_project_public_document`, had no pending branch. The
group projector has had one since 0.261.129: it shows a pending artifact only in
a held form. The public projector was written for public document browsing in
0.261.132, before public generated-artifact approval arrived in 0.261.134, and
the public chat routes predate both.

Fixed in version: **0.261.183**

## Technical details

One predicate decides, `public_document_visible_to_role(document, role)` in
`functions_public_document_policy.py`: a pending artifact is visible only to the
workspace's Owner, Admins and DocumentManagers. Only a manager can request a
public publication (`_authorize_destination`) or decide one, while every
signed-in user reads a public workspace, so even a held row would show the whole
tenant the file name and requester of an unapproved publication. Group
workspaces are unchanged: a group member can request an artifact, and still sees
the held row.

Files modified:
- `functions_public_document_reads.py`: the list, and everything computed from
  it (totals, places, facets and tags), leaves pending artifacts out for a
  reader, filtering again with the role its final revalidation finds. Detail and
  versions answer a reader with the same 404 as a missing document,
  "Document not found or access denied.", and a pending revision in a family the
  reader can see is skipped. A manager sees the group's held form: the file and
  request fields only, the status "Awaiting generated artifact approval", and
  `enhanced_citations: false`, with the review actions unchanged.
- `functions_public_document_collaboration.py` and
  `functions_public_document_publication.py`: a reader's publication read and
  decisions answer as missing (404 `collaboration_unavailable`), before any etag
  check.
- `route_backend_public_documents.py`: `/api/public_workspace_documents` and
  `/api/public_workspace_documents/tags` leave pending artifacts out **for
  every caller**, on both the document access index and the source query path.
  A pending artifact has no chunks until approval starts processing, so nothing
  can chat with it.
- `documentReadAdapter.ts`: a stale comment corrected.

Side effects:
- The chat routes are shared with classic chat and with the classic workspace
  page's tag filter, whose counts now leave pending artifacts out too.
- The tags route counts exactly the listed documents' tags. Before, a family
  whose current revision had no tags could count an older revision's tags.
- A failed tags read answers 500 "Error fetching tags" instead of silently
  giving that workspace no tags. Every caller already handles a failed answer.
- A requester who has lost their manager role can no longer cancel their own
  pending request in V2, since they can no longer see it. Managers can still
  reject it.

Not changed: the classic public list, detail, versions, downloads and
`/fileCount` routes, which classic uses and V2 doesn't. They're recorded as a
follow-up (decision 27).

## Validation

- `functional_tests/test_public_document_fixture_parity.py` (63): the manager's
  held row on list, detail and versions; a reader and an outsider never learn of
  the artifact, with places, counts, facets and tags unchanged; the reader's
  review read and every decision answer as missing, even with the real etag;
  the fixtures' copy of the rule held to the server's predicate; a family
  mixing released and pending revisions; a demotion mid-read.
- `functional_tests/test_public_chat_document_list_pending_artifacts.py` (11):
  the real chat routes over the real document access index and the source path,
  for a reader and a manager, with list and tags equal to the released-only
  answer.
- `functional_tests/test_public_document_publication.py` (63),
  `ui_tests/test_v2_public_documents.py` (62) and
  `ui_tests/test_v2_chat_context_selection.py` (43).
- 27 mutations, each failing a pin.

## Related

- [V2 Public Artifact Approval](../features/V2_PUBLIC_ARTIFACT_APPROVAL.md)
- [Artifact Approval APIs](../features/PUBLIC_DOCUMENT_ARTIFACT_APPROVAL_APIS.md)
