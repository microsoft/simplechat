# Personal Retention Default Value Fix

**Fixed in version: 0.261.278**

## Issue

On the Profile page, choosing **Using organization default** for personal conversation
or document retention and saving returned HTTP 400 with
`Invalid conversation retention value`, or the document equivalent. Once a user had chosen
their own period, they could not switch back to following the organization default.

## Root cause

`POST /api/retention-policy/user` in `route_backend_retention_policy.py` accepted only
`'none'` or a whole number of days. The select sends `'default'`, which reached `int()` and
was rejected. The group and public workspace routes already accepted `'default'`, and the
retention run already handles it: `resolve_retention_value` maps it to the organization
default.

## Technical details

### Files modified

- `application/single_app/route_backend_retention_policy.py`:
  `update_user_retention_settings` stores `'default'` for either field, before the integer
  check, matching the group route.

### Testing

- `functional_tests/test_v2_user_settings_audio_voice_retention.py`
  (`test_personal_retention_route_accepts_default`) checks that both fields handle
  `'default'` before converting the value to a number.

### Impact

This fixes the classic Profile page and the new V2 **Retention** card, since both save
through this route.

## Validation

- Before: saving **Organization default** failed with a 400, and the previous period stayed
  in force.
- After: the choice is saved, and the next retention run uses the organization's default.
