# V2 Public Members

## Overview

A public workspace's Owner and Admins can now manage its Admins and
DocumentManagers in V2, in a **Members** section under **Manage**, as group
managers do. Before this, public membership was managed only on the classic
page.

Implemented in version **0.261.179**. The routes are described in
[Public Membership APIs](PUBLIC_MEMBERSHIP_APIS.md). An inactive,
unrecognized-status or locked workspace's Owner and Admins keep the section:
**0.261.445**.

## Who sees what

- The Members section is listed for everyone who can view the workspace. Only
  the Owner and Admins can manage members, and that's what the context's
  `membership_management` hint and each member's `member_actions` say. The
  section never decides on a client role check.
- From version **0.261.445** the Owner and Admins also keep it in an `inactive`
  workspace, or one whose status isn't recognized, as the classic manage page
  keeps the member list for them. Everyone else, a DocumentManager included, is
  told the section isn't available, with the status as the reason, as before.
- The Owner and Admins see members' email addresses. A DocumentManager sees
  names and roles only.

## What the section offers

It's the group Members section, driven by the public workspace's client and
wording:
- the member list, with search, a role filter and paging kept in the address;
- **Add member** from the directory, as an Admin or DocumentManager;
- **Import members** from a CSV, with the roles a public workspace assigns
  (`admin` and `document_manager`; from version 0.261.180);
- changing roles and removing members, one at a time or in bulk, with a result
  per member;
- pending DocumentManager requests, to approve or reject;
- **Transfer ownership**, for the Owner, to an existing Admin or
  DocumentManager.

Public differences from groups:
- **Nobody can leave.** There's no Leave, and nobody can remove or demote
  themselves; ask the Owner (decision 17).
- The assignable roles are Admin and DocumentManager.
- The text never says "group", and a workspace whose status stops member
  changes says so.

## Locked, inactive and unrecognized-status workspaces

Version **0.261.445**. Adding a member and changing a role need an `active` or
`upload_disabled` workspace, and the server's membership policy withholds both
in a `locked`, `inactive` or unrecognized-status one. Removing a member,
reviewing requests to join and, for the Owner, transferring ownership are
allowed in every status, as the classic page allows. So in those statuses the
Owner and Admins get the member list, the requests, **Remove** and, for the
Owner, **Make owner**, but not **Add member**, **Import CSV** or the role
selects, and a note says why. A member's role shows as a label rather than a
select, and bulk selection offers **Remove selected** but no **Change role**.

The note reads, for a locked workspace, "This workspace is locked, so members
can't be added or imported and roles can't be changed. Removing members,
reviewing requests to join and, for the owner, transferring ownership still
work." An inactive workspace says "inactive" and one with an unrecognized status
says "This workspace's status isn't recognized". It appears only when the
server's own hint withholds adding, so it explains a missing control rather than
deciding one. It follows the status in the workspace context, so after a
workspace changes status while the page is open, the controls go as soon as the
server refuses one and the note joins them when the page next refreshes its
access, for example when you return to the tab.

After the Owner transfers an inactive workspace to someone else, the former
Owner is a DocumentManager, who doesn't keep Members there: the page re-reads
its access and says the section isn't available, with the status as the reason.

The classic public manage page lets the Owner and Admins add members and change
roles in these statuses, because it checks no status. V2 doesn't, because the
V2 membership routes refuse both there. (The policy module explains the rule by
saying the classic page hides those controls; the classic group page hides
adding in a locked or inactive group, but the classic public page hides
nothing.) To add or promote someone, make the workspace active again in Control
Center.

## How it's built

- `pages/workspace/MembersSection.tsx` is the one scope-driven section.
  `GroupMembersSection` and `PublicMembersSection` are thin wrappers around it.
  The group wrapper's props, markup and behaviour are unchanged, and the group
  Members suite passes with no edits.
- From version **0.261.445** `PublicMembersSection` takes the workspace's status
  from the context and passes the note for it to the section. The section
  offers a role select, and a bulk role change, only when the member list's own
  `change_role` operation is present as well as the row's action, because the
  server withholds the operation, but not each row's action, where a status
  closes role changes. For a group the operation is always present for a
  manager, so nothing changes there.
- `lib/groupMembership.ts` has `createPublicMembershipClient` beside
  `createGroupMembershipClient`, sharing the response readers.
- The public context lists `members` in its **Manage** group; from version
  **0.261.445** it keeps it open for the Owner and Admins in every status.

## Create a public workspace

The V2 directory offers **Create** when the server's directory hint allows it:
public workspaces are on and, when creation is restricted, the caller has the
`CreatePublicWorkspaces` app role. It uses the classic create route unchanged,
and the creator becomes the Owner.

## Testing and validation

- `ui_tests/test_v2_public_members.py`: the section for each role and status,
  add, import, role changes, removal, requests, transfer, and the absence of
  Leave. From version **0.261.445** it also covers a locked, an
  upload-disabled, an inactive and an unrecognized-status workspace: the note
  in place of the add controls and the role selects, removal and the requests
  working there, the hand-over that closes the section for the former Owner, a
  document manager and a reader finding the section closed with the status's
  reason, and the note at both breakpoints in both themes.
- `ui_tests/test_v2_public_directory.py`: the Create affordance, including a
  refused create that shows a safe message.
- The group Members suite (43 cases) passes with no edits, which shows the
  shared section's group behaviour is unchanged.
- `functional_tests/test_v2_public_membership_logic.mjs` and
  `test_v2_public_workspace_context_logic.mjs` run the public client and
  context readers.
- `test_public_membership_fixture_parity.py` holds the browser fixture to the
  routes.
- `functional_tests/test_public_membership_apis.py` runs the real routes for a
  locked, an inactive and an unrecognized-status workspace: the list and the
  requests are read, a member is removed, a request is approved or rejected and
  ownership is transferred, while adding a member and changing a role are
  refused with `public_status_unavailable` and the member list's hint withholds
  exactly those two.
- `functional_tests/test_public_context_fixture_parity.py` holds the Members
  section for every role and status, an unrecognized status included, to the
  browser fixture.

## Known limitations

- From version **0.261.184**, people ask from the V2 directory; see
  [V2 Public Directory](V2_PUBLIC_DIRECTORY.md). Until then, asking happened on
  the classic page.
- In a locked, inactive or unrecognized-status workspace V2 doesn't add members,
  import them or change roles, though the classic public page does; see
  *Locked, inactive and unrecognized-status workspaces* above.
- A DocumentManager doesn't keep the member list in an inactive or
  unrecognized-status workspace, though the classic page shows it to them
  read-only. Their Statistics section stays open; see
  [V2 Public Settings](V2_PUBLIC_SETTINGS.md).

## Related

- [Public Membership APIs](PUBLIC_MEMBERSHIP_APIS.md)
- [V2 Group Members](V2_GROUP_MEMBERS.md)
- [V2 Public Workspace Directory](V2_PUBLIC_DIRECTORY.md)
