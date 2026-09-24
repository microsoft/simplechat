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

### A group that keeps changing (0.261.161)

Since 0.261.160, adding a member and marking a group inactive write through the
conditional group write, which can give up when the group keeps changing. The
tools treated that as an unexpected failure: the model got a generic error, and
the application log recorded an error with a traceback.

From version **0.261.161**, those tools answer:

```json
{"success": false,
 "error": "The group changed while your request was being saved. Try again.",
 "error_type": "conflict",
 "error_code": "group_write_conflict"}
```

The sentence and code are the ones every group route uses, so the model can
relay them. Nothing was saved, so the request can be repeated. The log entry is
a warning that names the operation only, with no group data, no exception text
and no traceback. Every other failure is answered as before.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/semantic_kernel_plugins/simplechat_plugin.py` | `_agent_group_summary` and `_with_agent_group_summary`, applied to the three tools; from 0.261.161, a dedicated answer for a group write conflict. |

## Testing

`functional_tests/test_simplechat_agent_group_output.py` (12) loads the real
plugin module and pins each tool's output keys. It seeds the stored group with
member emails, a pending request, status history and an inline endpoint key,
and checks that none of them reaches a tool's answer. It also checks that a
missing status reads as `active`.

From 0.261.161 it also pins the conflict answer for `add_user_to_group` and
`make_group_inactive`: the exact answer and log call, and that a group ID, an
email and a description in the exception's text reach neither. A plain
`RuntimeError`, the conflict's base class, still gets the unexpected answer.
`test_group_write_conflict_text.py` checks the plugin imports the shared
sentence and code.

## Related

- [Group Residual Writers Write Safety Fix](GROUP_RESIDUAL_WRITERS_WRITE_SAFETY_FIX.md),
  which put the inactive marker these tools call on the conditional write.
