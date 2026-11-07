# Public Member CSV Roles Fix

## Issue

The V2 public workspace **Members** section imports members from a CSV file,
as the group section does. Its dialog said "Roles are user, admin or
document_manager.", and a row with the role `user` passed the file check. The
server then refused that row with "The role must be Admin or DocumentManager.",
because a public workspace assigns only Admins and DocumentManagers. Every
other signed-in user is already a reader, so there's nothing to add them as.

## Root cause

Version 0.261.179 moved the group Members section into a shared
`MembersSection`, which the public workspace also uses. The import dialog and
its CSV parser weren't part of the section's scope: both hardcoded the group's
three roles. The single **Add member** dialog already took the scope's roles.

Fixed in version: **0.261.180**

## Technical details

Files modified:
- `application/v2_ui/src/lib/groupMembership.ts`: `parseMemberCsv(text, roles)`
  accepts only the role tokens of the roles it's given, in the classic file's
  order (`user`, `admin`, `document_manager`), and its row error lists them.
  `describeMemberCsvRoles(roles)` gives the dialog's wording. Called without
  roles, both keep all three tokens.
- `application/v2_ui/src/components/membership/ImportMembersDialog.tsx`: takes
  the section's `roles`, parses with them and describes them.
- `application/v2_ui/src/pages/workspace/MembersSection.tsx`: passes the
  scope's assignable roles.

In a public workspace the dialog now says "Roles are admin or
document_manager.", and a `user` row is refused when the file is read, with
"Row N: Invalid role 'user'. Must be: admin or document_manager". Nothing is
sent for a file with a refused row, as before for any other invalid row. No
server behaviour changed.

The group import is unchanged: the same three roles, the same dialog text
("Roles are user, admin or document_manager.") and the same row error
("Must be: user, admin, or document_manager").

## Validation

- `functional_tests/test_v2_public_membership_logic.mjs`: the public parse
  refuses `user` and `owner` and accepts `admin` and `document_manager`. A
  mutation that ignores the roles fails it.
- `ui_tests/test_v2_public_members.py`: the dialog text, a `user` row refused
  before any request, and the per-row import results with public roles only.
- `ui_tests/test_v2_group_members.py`, `ui_tests/test_v2_group_journeys.py` and
  `functional_tests/test_v2_group_membership_logic.mjs` pass unchanged, which
  holds the group text byte for byte.

## Related

- [V2 Public Members](../features/V2_PUBLIC_MEMBERS.md)
- [V2 Group Members](../features/V2_GROUP_MEMBERS.md)
