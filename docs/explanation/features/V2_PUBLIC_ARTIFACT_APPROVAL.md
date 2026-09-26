# V2 Public Artifact Approval

## Overview

Implemented in version: **0.261.134**, tracked in
`application/single_app/config.py`.

When someone asks to publish a generated artifact into a public workspace, the
request now waits in the native V2 explorer for an owner-side decision, the same
way it already does for group workspaces. Reviewers approve, reject, or withdraw
requests without leaving the workspace.

The endpoint reference is
[Public Document Artifact Approval APIs](PUBLIC_DOCUMENT_ARTIFACT_APPROVAL_APIS.md).

## Purpose and boundaries

This completes the public document experience for everything that happens
inside a single public workspace: browsing (M3A), management (M3B), and now
artifact approval.

Cross-workspace sharing for public workspaces is **not** included. The backend
infrastructure it would need does not exist yet, so the explorer deliberately
offers no share controls for public scope, and attempting a share raises an
explicit error rather than failing quietly.

## One review surface, not two

The review dialog and its adapter are shared with the group review surface
rather than copied. `documentCollaboration.ts` and `DocumentCollaborationDialog.tsx`
became scope-aware, so public and group reviews run through one implementation.
For public scope, only the publication decisions are available.

Because those two files are shared with the shipped group review experience,
the group collaboration browser suite is the check that matters most for this
change. It passes unchanged.

## Decisions are checked for identity

Every receipt is validated against the workspace and document that were asked
for — `public_workspace_id` and `document_id` — and a receipt that does not
match raises rather than rendering as a completed decision. A late or misrouted
response cannot be shown as an approval of the wrong document.

Decisions are bound to the version of the review state the reviewer actually
saw. If the document changed in the meantime, the entered input is kept and the
reviewer is asked to refresh before deciding.

## Per-document gating

A review control appears only when that document's own
`document_collaboration_actions` list includes the action. The workspace
advertising the operation is not enough on its own.

The browser suite pins this with a positive control: a document with an empty
action list shows no review control, while a pending document in the same view
does. Without the second half, a surface that never showed a review control
would also pass.

There is no client-side fallback that enables an action when the list is empty.
That would turn a missing server hint into a silent bypass of the server's
per-document authorization.

## No Shared place

Public workspaces still have no share relationship, so the Shared place never
appears for public scope. This holds in four places together: facet validation
omits the shared count, place visibility suppresses Shared, document operations
treat public documents as having no incoming share, and the document scope check
still requires an exact workspace match. The browser suite now asserts
positively that the Shared place stays absent while a review is in progress.

## Active workspace state stays non-load-bearing

Selecting a public workspace still records it as the active selection, but
nothing on the page depends on that. A test proves a refused activation leaves a
publication decision fully working, because every decision names its workspace
in its own path.

## File structure

| File | Role |
|---|---|
| `application/v2_ui/src/lib/documentCollaboration.ts` | Scope-aware review adapter; public publication state and receipt validation |
| `application/v2_ui/src/components/documents/DocumentCollaborationDialog.tsx` | Shared review dialog |
| `application/v2_ui/src/components/documents/DocumentExplorer.tsx` | Review entry points |
| `application/v2_ui/src/pages/workspace/DocumentsSection.tsx` | Wires the public adapter |
| `application/v2_ui/src/lib/workspaceContext.ts` | Recognizes the `document_collaboration` block |

## Testing and validation

At this milestone, `ui_tests/test_v2_public_documents.py` covered the public
surface with 54 cases, including 11 for artifact approval: a queued approval, confirmation-gated
rejection and cancellation, recovery from `approval_failed`, a stale version
followed by refresh and retry, missing or unknown capability, per-document
gating, a refused activation during a decision, the Shared place staying absent,
and dialog layout in light and dark at 1440x900 and 390x844.

Run the V2 browser suites together, one process at a time:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\ui_tests;$PWD\ui_tests\fixtures"
python -m pytest .\ui_tests\test_v2_public_documents.py `
  .\ui_tests\test_v2_personal_document_scope.py `
  .\ui_tests\test_v2_group_documents.py `
  .\ui_tests\test_v2_group_document_management.py `
  .\ui_tests\test_v2_group_document_collaboration.py `
  .\ui_tests\test_v2_group_workspace_shell.py -q --disable-warnings
```

## Related

- [Public Document Artifact Approval APIs](PUBLIC_DOCUMENT_ARTIFACT_APPROVAL_APIS.md)
- [V2 Public Document Management](V2_PUBLIC_DOCUMENT_MANAGEMENT.md) — M3B
- [V2 Public Document Browsing](V2_PUBLIC_DOCUMENT_BROWSING.md) — M3A
- [V2 Group Document Collaboration](V2_GROUP_DOCUMENT_COLLABORATION.md) — the group equivalent
