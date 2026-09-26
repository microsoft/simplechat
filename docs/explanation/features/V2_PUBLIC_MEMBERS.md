# V2 Public Members

## Overview

A public workspace's Owner and Admins can now manage its Admins and
DocumentManagers in V2, in a **Members** section under **Manage**, as group
managers do. Before this, public membership was managed only on the classic
page.

Implemented in version **0.261.179**. The routes are described in
[Public Membership APIs](PUBLIC_MEMBERSHIP_APIS.md).

## Who sees what

- The Members section is listed for everyone who can view the workspace. Only
  the Owner and Admins can manage members, and that's what the context's
  `membership_management` hint and each member's `member_actions` say. The
  section never decides on a client role check.
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

## How it's built

- `pages/workspace/MembersSection.tsx` is the one scope-driven section.
  `GroupMembersSection` and `PublicMembersSection` are thin wrappers around it.
  The group wrapper's props, markup and behaviour are unchanged, and the group
  Members suite passes with no edits.
- `lib/groupMembership.ts` has `createPublicMembershipClient` beside
  `createGroupMembershipClient`, sharing the response readers.
- The public context lists `members` in its **Manage** group.

## Create a public workspace

The V2 directory offers **Create** when the server's directory hint allows it:
public workspaces are on and, when creation is restricted, the caller has the
`CreatePublicWorkspaces` app role. It uses the classic create route unchanged,
and the creator becomes the Owner.

## Testing and validation

- `ui_tests/test_v2_public_members.py`: the section for each role and status,
  add, import, role changes, removal, requests, transfer, and the absence of
  Leave.
- `ui_tests/test_v2_public_directory.py`: the Create affordance, including a
  refused create that shows a safe message.
- The group Members (36), journeys (46) and workspace shell suites pass
  unchanged.
- `functional_tests/test_v2_public_membership_logic.mjs` and
  `test_v2_public_workspace_context_logic.mjs` run the public client and
  context readers.
- `test_public_membership_fixture_parity.py` holds the browser fixture to the
  routes.

## Known limitations

- Asking to become a DocumentManager still happens on the classic page. V2
  shows and decides the requests.

## Related

- [Public Membership APIs](PUBLIC_MEMBERSHIP_APIS.md)
- [V2 Group Members](V2_GROUP_MEMBERS.md)
- [V2 Public Workspace Directory](V2_PUBLIC_DIRECTORY.md)
