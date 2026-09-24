# Group Retention Settings Fix (v0.261.154)

## Issue

Saving a group's retention policy on the classic manage page failed or did the
wrong thing in several ways. The page posts both retention periods on every
save, through `POST /api/retention-policy/group/<group_id>`.

- **"Using organization default" couldn't be saved.** The route refused
  `"default"`, although the page offers it and new groups are created with it.
  So a save failed whenever either select showed the organization default, and
  a group that had chosen a period could never go back to the default.
- **Sending one period dropped the other.** The route replaced the whole stored
  policy with the values sent.
- **Some values were stored wrongly or crashed the route.** `true` was stored as
  1 day, and a list, an object or a non-finite number (`Infinity`, `NaN`) gave
  a server error.
- **No feature switch was checked.** The route accepted saves with group
  workspaces or group retention policies turned off.

Fixed in version: **0.261.154**, tracked in `application/single_app/config.py`.

## Root cause

The route accepted only whole days and `"none"`, parsed any other value with
`int()` without checking its type, assigned the parsed values as the new
policy, and carried no feature gate.

## Technical details

### The change

- `"default"` is accepted for either period and stored as the string new groups
  are seeded with.
- The values sent are merged into the stored policy, so the other period is
  kept. A stored policy that isn't an object is replaced.
- `true`, `false`, lists, objects and non-finite numbers get the route's
  existing 400, "Invalid conversation retention value" or "Invalid document
  retention value". Text and finite numbers are parsed as before, and the
  existing bounds messages are unchanged.
- The route needs group workspaces (400 "Enable Group Workspaces is disabled.")
  and group retention policies (403 `group_retention_disabled`, "Retention
  policies aren't turned on for group workspaces."). The switch is checked
  before the group is read or the body parsed, so it answers the same for every
  caller. The native route uses the same check.
- The save goes through the group etag guard, so it no longer overwrites a
  membership change made at the same moment (see
  [Group Settings Write Safety Fix](GROUP_SETTINGS_WRITE_SAFETY_FIX.md)).

`GET /api/retention-policy/defaults/group`, which the page reads for the
organization defaults, is unchanged and stays ungated.

### Files modified

- `route_backend_retention_policy.py`: `update_group_retention_settings`.

### Tests

`functional_tests/test_group_settings_legacy_fixes.py` covers the merge, a
malformed stored policy, saving both organization defaults, `"default"` for
each period, the refused types and literals, the values still accepted, the
unchanged refusals, and both gates, including that they answer before the group
is read.

## Validation

- Before: a group showing the organization default couldn't save its retention
  settings, and saving one period erased the other.
- After: every option on the page saves, only the periods sent change, and the
  route follows the administrator's retention switches.

## Related

- [Group Settings APIs](../features/GROUP_SETTINGS_APIS.md)
- [Group Settings Write Safety Fix](GROUP_SETTINGS_WRITE_SAFETY_FIX.md)
