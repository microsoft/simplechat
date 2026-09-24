# V2 Group Members (v0.261.155)

## Overview

The group workspace in V2 has a **Members** section. Owners and admins use it to
add and remove members, change roles, review requests to join, import members
from a CSV file, and transfer ownership, without leaving V2. Every other member
sees who belongs to the group and can leave it.

Implemented in version: **0.261.155**, tracked in
`application/single_app/config.py`.

Dependencies:
- the group membership routes from version 0.261.151
  ([Group Membership APIs](GROUP_MEMBERSHIP_APIS.md));
- the directory people search, `/api/userSearch`;
- the selected-group context
  ([V2 Shared Workspace Context](V2_SHARED_WORKSPACE_CONTEXT.md)).

## Where it lives

Members is a section of the group workspace, in a **Manage** group of the
section navigation and the overview, at `/v2/groups/<group_id>/members`. It
shares the header, the group picker, the unsaved-change guard and access
revalidation with every other section, so the workspace keeps one navigation
tree. A personal workspace has no Manage group.

The selected-group context reports it as `sections.members`, in the `manage`
group:
- it's available to every member while the group's status lets them view it:
  `active`, `locked` and `upload_disabled`;
- it's unavailable in an `inactive` group, or one with an unrecognized status,
  with the status as the reason;
- its `can_manage` is for navigation only. The controls come from the member
  list's own hints.

A link to `/members/<anything>` opens the section itself, as for other
sections with no item routes.

## What each role sees

The page offers only what the server's hints allow:
- `membership_management.operations` for the page's controls: **Add member**,
  **Import CSV** and **Requests to join**;
- `member_actions` for each row's controls: the role, **Remove**, **Make
  owner** and **Leave this group**.

With the rules from the membership routes, that gives:

| Role | What they can do |
|---|---|
| Owner | Everything below, and **Make owner** on another member. The owner can't leave or change their own role; they transfer ownership first. |
| Admin | Add and import members, review requests, change roles (including other admins' and their own), remove members, leave |
| DocumentManager, User | See the members, and leave the group |

In a `locked` group, adding and importing are refused, as on the classic page.
Everything else works in every status that shows the section.

## Using it

- **Browse:** search by name or email, filter by role, and page through 20
  members at a time. The search, role and page are in the address, so a link
  keeps them.
- **Add member:** search the directory, pick a person and a role, and add them.
  The row that appears is the one the server stored. If the person isn't in the
  directory, or is already a member, the dialog says so and stays open.
- **Import CSV:** the classic format.
  - A `userId,displayName,email,role` header, and at most 1,000 rows.
  - User IDs must be GUIDs, and roles are `user`, `admin` or
    `document_manager`.
  - Any invalid row refuses the whole file, with the classic messages.
  - Each row is added through the same route as **Add member**, and its
    outcome is shown. **Retry failed rows** tries only the rows that failed.
- **Change a role:** choose it in the row. Choosing the role someone already
  has does nothing. An admin who demotes themselves is asked to confirm first,
  because they lose member management.
- **Remove** and **Leave this group** ask for confirmation. After leaving, V2
  refreshes your groups and returns to the group list.
- **Select several members** to change their role or remove them together. Each
  member's result is shown, and the members that failed stay selected. Your own
  row isn't selectable; use its own controls.
- **Make owner** explains the consequences first: the new owner takes over, and
  you become a member. Afterwards the page reloads the members and your access.
- **Requests to join:** **Approve** or **Reject**. If the request was already
  settled, for example by another admin or by an earlier approval whose
  response was lost, the page says it was already handled and reloads.

## Errors

- A refusal shows the server's message, and the page reloads the members.
- If the group changed while a change was being saved, the page keeps
  everything as it was, so the same action can simply be retried.
- If your own access changed, the page re-reads your access to the group. If
  you're no longer a member, or the group is gone, the workspace says so.
- A response that doesn't have the expected shape is shown as a load error,
  never as an empty list.

## Implementation

| File | Purpose |
|---|---|
| `application/v2_ui/src/pages/workspace/GroupMembersSection.tsx` | The section: list, requests, row and bulk actions, confirmations |
| `application/v2_ui/src/components/membership/AddMemberDialog.tsx` | Directory search and role choice |
| `application/v2_ui/src/components/membership/ImportMembersDialog.tsx` | CSV import with per-row results and retry |
| `application/v2_ui/src/lib/groupMembership.ts` | The membership client, strict response checks, CSV parsing |
| `application/v2_ui/src/pages/workspace/groupManageSections.ts` | The Manage group's sections |
| `application/single_app/functions_workspace_context.py` | `sections.members` in the selected-group context |

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `ui_tests/test_v2_group_members.py` | 36 | The real V2 page: navigation, every role and status, search and paging in the address, add, CSV import, role changes, remove, leave, bulk actions, transfer, requests, every refusal, malformed responses, both themes at both sizes |
| `functional_tests/test_group_membership_fixture_parity.py` | 58 | The browser fixture's responses, statuses, error codes and messages against the real membership routes and `/api/userSearch` |
| `functional_tests/test_v2_group_membership_logic.py` | 1 (10 checks) | The client's response checks and CSV parsing |
| `functional_tests/test_v2_group_workspace_context.py` | 88 | `sections.members` for every role and status, among the context's other contracts |

## Known limitations

- **Inactive groups:** the Members section isn't available in an `inactive`
  group, or one with an unrecognized status, although the membership routes
  and the classic manage page still allow management there. Use **Manage group
  (classic)** for those groups.
- **Adding** is by directory search only; the CSV import covers user IDs.
- **CSV import** adds one row at a time, as the classic page does.
- **Membership changes** don't appear in the group activity feed, as before.
