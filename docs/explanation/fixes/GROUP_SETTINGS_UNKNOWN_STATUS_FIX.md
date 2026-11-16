# Group Settings Unknown Status Fix (v0.261.157)

## Issue

The native group settings routes let the owner of a group with an unrecognized
status change its name, description, color and logo. An unrecognized status
is one this version doesn't know, an empty status, or null.

Everywhere else an unrecognized status fails closed:
- the selected-group context disables every section, with "This group's status
  is not recognized. Contact an administrator.";
- the native membership routes refuse to add a member.

So the settings read offered the owner edits the rest of the workspace
treated as unavailable.

Fixed in version: **0.261.157**, tracked in `application/single_app/config.py`.

## Root cause

`group_settings_read_only` in `functions_group_settings_policy.py` counted only
`locked` and `inactive` as read-only. Every other value, recognized or not, was
editable.

It turned up while the V2 browser fixture's selected-group context was being pinned
against the real one, work that lands separately. It had also been noted when the
settings routes were built, as a choice to review.

## Technical details

### The change

- **The profile and logo are writable only while the group is `active` or
  `upload_disabled`.** A group with no stored status still reads as `active`,
  as everywhere else.
- **A status refusal names its cause.** The error code is still
  `group_status_unavailable`:
  - a locked or inactive group keeps "This group is locked or inactive, so its
    name, description, color and logo can't be changed.";
  - an unrecognized status gets "This group's status isn't recognized, so its
    name, description, color and logo can't be changed."
- **Nothing else changes.** Downloads, retention, the settings read, the
  activity feed, the statistics and the document count stay allowed in every
  status.
- The V2 workspace doesn't show the Settings section for an unrecognized status
  anyway, so the change applies to the routes themselves.
- `settings_management`, in the settings read and the selected-group context,
  now reports the four edits as unavailable for these groups, because it comes
  from the same decision.

### Files modified

- `functions_group_settings_policy.py`: `group_settings_read_only`, and the new
  `GROUP_SETTINGS_WRITABLE_STATUSES`. `GROUP_SETTINGS_READ_ONLY_STATUSES` is
  kept for existing importers.
- `functions_group_settings.py`: `refusal` and `require_operation` choose the
  status message.

### Tests

- `functional_tests/test_group_settings_policy.py`: only `active`,
  `upload_disabled` and a missing status allow the four edits. `locked`,
  `inactive`, null, empty and unrecognized values refuse them, while the reads
  stay allowed.
- `functional_tests/test_group_settings_apis.py`:
  - an unrecognized status refuses the profile and logo writes before the body
    is read, with nothing stored;
  - each status refusal names its cause;
  - downloads and retention still work in an unrecognized status.
- `functional_tests/test_group_settings_context_seam.py`: the context's
  `settings_management` holds the owner's profile and logo in an unrecognized
  status.

## Validation

- Before: the owner of a group with an unrecognized status could rename it and
  change its logo through the native routes.
- After: those edits are refused with a message that names the reason. The
  reads, downloads and retention work as before.

## Related

- [Group Settings APIs](../features/GROUP_SETTINGS_APIS.md)
- [Group Membership APIs](../features/GROUP_MEMBERSHIP_APIS.md)
