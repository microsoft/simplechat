# Shared Workspace Document Access Copy Fix

## Issue

In the V2 group and public workspaces, a viewer who couldn't upload opened an
empty **Documents** section that said "This group has no visible documents. Use
the classic workspace to manage files." with a **Manage files in classic**
button.
- Classic applies the same role and status rules, so it couldn't help that
  viewer either.
- In a public workspace the sentence still said "This group".

A viewer with no document operations who tried a change, such as dropping a
file, read "Document management is available in the classic group workspace."
in a group. In a public workspace they got the generic per-document message.

## Root cause

Both texts date from the read-only group documents release (M2A), before native
document management existed. The `document_management` hint shipped with the
management APIs, so the V2 app always gets it from the server it talks to. The
texts were never revisited, and the explorer didn't know the workspace's status,
so it couldn't explain a refusal.

Fixed in version: **0.261.167**

## Technical details

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/documentAccessCopy.ts` | New. Complete sentences for each scope (group and public), chosen by the workspace's status and whether the server's hint was recognized |
| `application/v2_ui/src/lib/documentOperations.ts` | The operation adapter reports `advertised`: whether the `document_management` hint was recognized |
| `application/v2_ui/src/components/documents/DocumentExplorer.tsx` | Takes the workspace's status. The empty state has no classic button, and a viewer with no operations gets the scoped refusal. The explorer's `onOpenClassic` prop is gone; the section headers' own classic links are unchanged |
| `application/v2_ui/src/pages/workspace/DocumentsSection.tsx` | The group and public sections pass `context.status` |
| `ui_tests/fixtures/public_workspace.py` | `public_context` carries the `document_management` hint the real public context always sends, equal to the server's policy in all 20 role × status combinations |

The server still decides every operation. Only the Owner, Admin and
DocumentManager roles manage documents, and only an active workspace takes
uploads. These texts only put that decision into words for each scope.
Personal documents and uploaders in every scope are unchanged.

### Empty state, for a viewer who can't upload

In a public workspace, read "This public workspace" for "This group".

| State | Description |
| --- | --- |
| Active | This group's owner, admins and document managers can add documents. |
| Uploads disabled | Document uploads are disabled for this group. |
| Locked | This group is locked (read-only), so documents can't be added. |
| Inactive or unrecognized | Documents can't be added to this group in its current status. |
| Permissions not confirmed | This group's document permissions couldn't be confirmed. Refresh this workspace to check whether you can add documents. |

### Refusal, for a viewer with no document operations

| State | Refusal |
| --- | --- |
| Active or uploads disabled | Only this group's owner, admins and document managers can manage its documents. |
| Locked | This group is locked (read-only), so its documents can't be changed. |
| Inactive or unrecognized | This group's documents can't be changed in its current status. |
| Permissions not confirmed | This group's document permissions couldn't be confirmed. Refresh this workspace before managing documents. |

"Permissions not confirmed" covers a missing or unrecognized hint, which no
current server sends. Inactive and unrecognized statuses can't normally be
reached, because the Documents section is unavailable there.

## Validation

- `functional_tests/test_v2_document_access_copy_logic.mjs` (5 checks) covers
  every scope, status and hint combination. It also checks that no sentence
  mentions classic, repeats the heading or names the other scope, and that 7
  malformed hints aren't recognized.
- `functional_tests/test_document_access_copy_policy_seam.py` (7) holds the
  copy's assumptions to the real group and public policies:
  - only the Owner, Admin and DocumentManager roles get operations;
  - only an active workspace takes uploads;
  - a locked workspace grants no change;
  - the public fixture's hint matches the policy.
- Browser: group documents 29, group document management 39 → 47, public
  documents 54 → 59.
- Mutations: reverting either text, reading an unrecognized hint as recognized,
  dropping the status, changing the role wording, or removing the public
  fixture's hint each fail the pins.

## Related

- [V2 Group Document Management](../features/V2_GROUP_DOCUMENT_MANAGEMENT.md)
- [V2 Public Document Management](../features/V2_PUBLIC_DOCUMENT_MANAGEMENT.md)
