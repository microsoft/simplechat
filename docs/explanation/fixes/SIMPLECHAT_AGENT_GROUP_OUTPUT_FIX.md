# SimpleChat Agent Group Output Fix

Fixed/Implemented in version: **0.261.160**

## Issue

Three SimpleChat agent tools answered the model with the whole stored group
item:

- `make_group_inactive`;
- `add_user_to_group`;
- `create_group`.

That item carries every member's email address, pending join requests,
status history and, when Key Vault storage is off, the group's model endpoint
credentials inline. The model could repeat any of it in a reply, or pass it to
another tool, although none of these tools needs more than the group's
identity.

This is the same class of disclosure as the
[Group Details Payload Disclosure Fix](GROUP_DETAILS_PAYLOAD_DISCLOSURE_FIX.md)
in 0.261.143.

## Root cause

The operations in `functions_simplechat_operations.py` return the stored item,
because the routes that share them need it. The plugin passed that result to
the model unchanged.

## Fix

`simplechat_plugin.py` reduces the group to a summary at the tool boundary:

```json
{"id": "...", "name": "...", "status": "active"}
```

A missing status reads as `active`.

- `create_group` answers `{"group": <summary>}`.
- `add_user_to_group` keeps `success`, `message`, `group_id`, `group_name`,
  `member` and `member_role`. Its `group` becomes the summary.
- `make_group_inactive` keeps `old_status`, `new_status` and `message`. Its
  `group` becomes the summary.

The operations still return the stored item, so the routes that use them are
unchanged.

No SimpleChat action reference page describes these outputs, so no reference
documentation changes.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/semantic_kernel_plugins/simplechat_plugin.py` | `_agent_group_summary` and `_with_agent_group_summary`, applied to the three tools. |

## Testing

`functional_tests/test_simplechat_agent_group_output.py` (8) loads the real
plugin module and pins each tool's output keys. It seeds the stored group with
member emails, a pending request, status history and an inline endpoint key,
and checks that none of them reaches a tool's answer. It also checks that a
missing status reads as `active`.

## Related

- [Group Residual Writers Write Safety Fix](GROUP_RESIDUAL_WRITERS_WRITE_SAFETY_FIX.md),
  which put the inactive marker these tools call on the conditional write.
