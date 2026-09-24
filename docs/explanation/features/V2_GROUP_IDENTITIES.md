# V2 Group Identities

## Overview

Implemented in version: **0.261.139**, tracked in
`application/single_app/config.py`.

Group workspace identities are reusable credentials that group File Sync sources
and group actions bind to. They can now be listed, created, edited, and deleted
from the native V2 group workspace. Previously the group Identities section was
marked Classic.

The endpoint reference is [Group Identity APIs](GROUP_IDENTITY_APIS.md).

## Who can do what

| | Owner, Admin, DocumentManager | Ordinary member |
|---|---|---|
| See the Identities section and list identities | yes | no |
| Create, edit, delete | yes, in an `active` group | no |

These are the rules the classic group workspace applies. Identities are
available when Semantic Kernel is on for your organization, or File Sync is
enabled for the group.

## The Identities section

The group page renders the native Identities section when the workspace context
offers it (`sections.identities.enabled`).

- **Create** is offered only when the group's `identity_management` hint, in the
  workspace context, includes `create`.
- **Edit and delete** are offered for an identity only when its own
  `identity_actions` include them.
- There is no fallback: a missing or empty hint hides the operation.

The editor offers the same capabilities, uses and authentication types as the
classic workspace, and sends only the fields the server accepts. Stored secrets
are never shown. A stored password or secret appears as kept, and a new value
replaces it.

When a save is refused:

- **Invalid details:** the server's message is shown as returned, and the draft
  stays open.
- **Changed elsewhere:** if another manager changed the identity since you
  opened it, the draft stays open, so you can reload and reapply your change.
- **Still in use:** a delete refused because a File Sync source or action still
  uses the identity lists what uses it, so you can rebind those first.

My Workspace's personal Identities section is unchanged.

## Choosing an identity for a group action

The group action editor can now bind a reusable **group** identity. It lists the
group's identities whose uses include actions, as reported by the server,
and does not interpret defaults or aliases itself.

- **The list loaded, but the bound identity is not in it:** the identity was
  removed or can no longer be used for actions, so the editor calls it
  unavailable.
- **You can't list the group's identities,** for example as an ordinary member:
  the editor shows no error, and keeps an existing binding with neutral wording
  ("Uses a group identity; kept as is").
- **The list failed to load for another reason:** the editor shows the load
  error and keeps the neutral wording.

It never calls a binding unavailable without having seen the list. Personal
actions are unchanged.

## Testing and validation

`ui_tests/test_v2_group_identities.py` drives the production V2 build against a
closed fixture that enforces the server's rules, with 21 cases:

- the section and its reads use the group's own routes, and every row is checked
  against the page's group;
- manager create, edit, and delete, with the exact write fields and
  `expected_etag`;
- a conflicting save keeps the draft;
- an in-use delete lists its references;
- the server's reviewed validation messages are shown;
- a member gets no native section and no identity read;
- the group action editor lists only the group's action identities;
- a member's unresolvable list stays silent;
- a malformed list is treated as a load error rather than an empty one;
- personal identities are unchanged.

On the integrated tree these pass unchanged:

- group actions (25), including the updated identity-copy test;
- group agents (29), group prompts (17), and the group shell (21);
- personal authoring (93), draft navigation (3), and delegation (4);
- the document and public suites;
- the composers;
- the 27 workspace authoring logic checks.

The fixtures record any request for personal data from a group page as
unexpected, and none was made.

## Related

- [Group Identity APIs](GROUP_IDENTITY_APIS.md)
- [V2 Group Actions](V2_GROUP_ACTIONS.md)
