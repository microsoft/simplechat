# V2 Group Directory

## Overview

Implemented in version: **0.261.150**, tracked in
`application/single_app/config.py`.

The V2 group directory is where you find groups, ask to join them, and create
new ones, without leaving V2. Before this release, V2 only listed the groups you
already belong to, and finding or creating a group meant going to the classic
**Profile** page.

The page reads the directory routes described in
[Group Directory APIs](GROUP_DIRECTORY_APIS.md), and nothing else.

## Getting there

- **Browse all groups**, in the header of **Group workspaces**.
- **Browse the group directory**, on the **Choose a group workspace** screen
  shown when no group is selected.
- `/v2/groups/directory` directly. The path is reserved for the directory, so
  it is never read as a group ID.

**Your groups** returns to the group workspaces.

## The page

Three views, kept in the address with the search and the page number, so the
browser's back and forward buttons and a shared link reopen the same view:

- **All:** every group you can discover;
- **My groups:** the groups you belong to;
- **Discover:** the groups you don't belong to, including those you've asked to
  join.

The search is done on the server, a moment after you stop typing. It matches a
group's name or description, or its exact ID, and a new search starts again at
the first page. A search longer than 200 characters isn't sent: the page keeps
the current list and shows the limit under the search box. There are 20 groups
to a page.

Each group shows:
- its logo, or its initial in the group's colour;
- its name and description;
- its member count and owner's name;
- your membership: your role, such as **Owner**, **Admin**, **Document
  manager** or **Member**, or **Requested** when you've asked to join.

Logos are loaded only for groups you belong to, because only members can see a
group's logo. The owner's email and ID are never shown.

### Actions

Each group offers the one action that fits your membership:

- **Open**, for a group you belong to. It opens the group's workspace, which
  then makes that group your active group, as choosing it in the picker does.
- **Request to join**, for a group you don't belong to. Your request waits for
  the group's owner or an admin to approve it.
- **Cancel request**, for a group you've asked to join.

Each action updates the group's row from the server's answer. When the server
refuses, the page shows its message:

- **Already a member, already requested, or no request to cancel:** someone
  else changed your membership meanwhile. The page reloads to show the current
  state.
- **The group was deleted:** the page says so and reloads.
- **The group kept changing while the request was saved:** the row stays as it
  was, and you can try again.

### Creating a group

**Create group** appears only when the server says you may create one. That
takes into account whether group creation is on, and whether it is limited to
people with the **CreateGroups** role. The page never decides from the setting
alone.

The dialog asks for a name, from 1 to 80 characters, and an optional
description of up to 500. It checks these limits the way the server does,
counting each character, including an emoji, once. A refusal from the server,
such as creation having been turned off meanwhile, is shown in the dialog with
your entries kept. On success, the new group's workspace opens, with you as its
owner.

## Known limitations

- **Approving requests** still happens on the classic manage page, until the
  native Members view arrives.
- **The directory reads every group** on each request, as the classic Find
  Group did; see the API reference.

## Testing and validation

- `ui_tests/test_v2_group_directory.py` (31 cases) drives the production V2
  build against a closed fixture, `ui_tests/fixtures/group_directory.py`, that
  models the server's rules. It covers:
  - the layout in both themes at desktop and mobile sizes, including an
    80-character name and a 500-character description;
  - the route reservation, with no group-context or activation request;
  - views, search and paging through the address, the search limit, and a page
    number out of range;
  - join then cancel from the server's rows;
  - each conflict code reloading, the plain retry, and a deleted group;
  - Open and create opening the group by ID;
  - Create following the server's hint, with the creation setting on and off;
  - the create limits, including an emoji name at the limit and one over it;
  - logos requested only for member rows;
  - the shared role labels;
  - a malformed response being an error rather than an empty list.
- `functional_tests/test_group_directory_fixture_parity.py` (19 cases) runs the
  same requests against the real routes and the fixture, and compares their
  shapes. It covers each view, a search, a later page, a strict-parameter
  refusal, the owner's nested keys, every create, join and cancel outcome, and
  `Cache-Control: no-store` on every route.

On the integrated tree the group section suites, the group shell, the personal
and public document suites and personal authoring pass unchanged. That includes
the mobile layout of group documents, which the first version of the page's
picker link would have squeezed.

## Related

- [Group Directory APIs](GROUP_DIRECTORY_APIS.md)
- [Workspace Notification Links Fix](../fixes/WORKSPACE_NOTIFICATION_LINKS_FIX.md)
