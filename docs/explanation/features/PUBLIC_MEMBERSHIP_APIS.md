# Public Membership APIs

## Overview

Native routes for managing who manages a public workspace: its Admins and
DocumentManagers, their requests and the owner. Every signed-in user already
reads a public workspace, so membership here means the manager roles, not
access.

Implemented in version **0.261.179**. They sit beside the classic
`/api/public_workspaces/<id>/members`, `/requests` and `/transferOwnership`
routes, which keep working.

## Routes

All paths start `/api/public-workspaces/W/membership`, where `W` is the only
target. Each route checks login, the user, and `enable_public_workspaces`.

| Method and path | Purpose |
| --- | --- |
| `GET .../members` | The members, paged and searched |
| `POST .../members` | Add a member as Admin or DocumentManager |
| `PATCH .../members/U` | Change a member's role |
| `DELETE .../members/U` | Remove a member |
| `GET .../requests` | Pending DocumentManager requests |
| `POST .../requests/U/approve` | Approve a request |
| `POST .../requests/U/reject` | Reject a request |
| `PUT .../owner` | Transfer ownership |

- The list takes `search`, `role`, `page` and `page_size`. It answers
  `{members, page, page_size, total_count, membership_management}`, and each
  member carries `member_actions`.
- Every write goes through the public workspace's conditional write. A
  workspace that keeps changing answers 409 `public_workspace_write_conflict`,
  and a deleted workspace is never recreated.

## Rules

- **Who manages:** the Owner and Admins. The Owner alone transfers ownership.
- **Assignable roles:** Admin and DocumentManager. `User` is every other
  signed-in user and is never stored.
- **Status:** members are added, and roles changed, only while the workspace is
  `active` or `upload_disabled`. Requests can be reviewed, members removed and
  ownership transferred in any status.
- **No leaving:** nobody removes themselves (403 `cannot_leave`), as in classic.
  An Admin or DocumentManager who wants to step down asks the Owner.
- **Ownership transfer** goes only to an existing Admin or DocumentManager. The
  previous owner stays a DocumentManager, with their name and email.
- **Emails:** the Owner and Admins see members' email addresses. A
  DocumentManager sees names and roles only; the server blanks each email
  before the list leaves it. Classic showed every email to every member, so this
  is a deliberate tightening (decision 18).
- **Audit:** adding, changing a role and removing each write an activity record,
  as the group's native membership writes do. Approving, rejecting and
  transferring write none, also as the group's don't. The two existing
  notifications (member added, role changed) are unchanged.

Each hint is a hint, never a grant: every route re-checks role and status on
the fresh copy.

## Errors

Refusals answer `{error, error_code}` with reviewed sentences, for example:
- "Only the workspace's owner or an admin can manage its members."
- "Members can't be changed while this workspace is in its current status."
- "You can't remove yourself from a public workspace." (`cannot_leave`)
- "Transfer ownership before removing the owner."

A malformed request is a 400 `invalid_request`. An unexpected failure is logged
with its error type only, and answers `public_membership_unavailable`.

## Creating a public workspace

The public directory's `public_directory` hint now carries `can_create`, from
the same rule the classic `POST /api/public_workspaces` route enforces:
- public workspaces must be on;
- when `require_member_of_create_public_workspace` is set, the caller needs the
  `CreatePublicWorkspaces` app role.

The V2 directory offers **Create** on that hint and posts to the classic route
unchanged. The classic route's error text can contain exception detail, so the
directory never shows it: a failure shows a safe message, and the hint is
re-read.

## Code

- `functions_public_membership_policy.py`: the roles, operations and per-member
  actions.
- `functions_public_membership_disclosure.py`: the email redaction.
- `functions_public_membership.py` and `route_backend_public_membership.py`:
  the rules and the routes.
- `functions_public_membership_audit.py`: the activity records.
- `functions_public_directory_policy.py`: the creation rule for the directory
  hint.

## Testing

- `test_public_membership_policy.py`, `test_public_membership_apis.py` and
  `test_public_membership_transport.py` (the new URLs can't match the classic
  ones).
- `test_public_membership_fixture_parity.py` holds the browser fixture to the
  routes.
- `test_public_directory_policy.py` covers the creation rule.
- `test_public_context_fixture_parity.py` covers `membership_management` and
  the Members section.

## Related

- [V2 Public Members](V2_PUBLIC_MEMBERS.md)
- [V2 Public Workspace Directory](V2_PUBLIC_DIRECTORY.md)
- [Group Membership APIs](GROUP_MEMBERSHIP_APIS.md)
