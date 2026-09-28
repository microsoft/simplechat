# Group Prompt Write Access Fix

## Issue

Any member of a group, including an ordinary `User`, could create, edit, and
delete the group's shared prompts by calling the legacy `/api/group_prompts`
routes directly.

The classic group workspace never offered ordinary members those actions. Its
`canManageGroupPrompts()` check limits management to the manager roles. The
server, however, did not enforce the same rule.

Fixed in version: **0.261.136**

## Root cause

`route_backend_group_prompts.py` used one helper for all five routes, and that
helper admitted all four roles:

```python
def _get_active_group_or_error(user_id):
    try:
        return require_active_group(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
        ), None
```

Because the write routes shared the read routes' helper, they inherited the
read policy. The interface hid the buttons, so the gap went unnoticed.

Public prompts did not have this problem: `route_backend_public_prompts.py`
already narrows its create, update, and delete routes to the manager roles.

## Fix

The helper now takes the allowed roles as an argument, defaulting to the
original four so the reads are unchanged. The three write routes pass the
manager roles:

```python
GROUP_PROMPT_WRITE_ROLES = ("Owner", "Admin", "DocumentManager")
```

| Route | Before | After |
|---|---|---|
| `GET /api/group_prompts` | all four roles | unchanged |
| `GET /api/group_prompts/<id>` | all four roles | unchanged |
| `POST /api/group_prompts` | all four roles | Owner, Admin, DocumentManager |
| `PATCH /api/group_prompts/<id>` | all four roles | Owner, Admin, DocumentManager |
| `DELETE /api/group_prompts/<id>` | all four roles | Owner, Admin, DocumentManager |

An ordinary member's write now gets 403, "Only group owners, admins, and
document managers can change group prompts". The routes keep their paths and
active-group targeting.

### A message this fix had to correct

Narrowing the writes made a 403 reachable by members for the first time. The
helper mapped every `PermissionError` to one message, "You are not a member of
the active group". That was accurate while only non-members could reach it, but
once members could be refused it would tell a member they were not a member,
sending them to look for a membership problem that does not exist.

`assert_group_role` raises two different errors — not a member, and a member
without the role — and the helper collapsed them. It now tells them apart by
checking membership directly, not by matching the error's wording, which would
break silently if that wording changed. Non-members still get the original
message, so the new wording never reaches someone outside the group.

The rule was decided by the product owner: ordinary members may use a prompt,
and reword it in chat for a single message, but may not save changes to the
group's prompts.

### The `PromptManager` role

`canManageGroupPrompts()` also lists a `PromptManager` role. It appears nowhere
else in the application, no code assigns it, and no server role list recognizes
it, so it grants nothing. It was deliberately not added to the server policy.

### Files modified

| File | Change |
|---|---|
| `application/single_app/route_backend_group_prompts.py` | Role argument on the helper; manager roles on the three write routes |

The immutable-target routes added in the same release enforce the same rule,
and also require the group to be `active`, matching `canManageGroupPrompts()`.
See [Group Prompt APIs](../features/GROUP_PROMPT_APIS.md).

## Compatibility

No supported flow changes. The classic interface never showed ordinary members
these actions, so only direct API calls by ordinary members are affected.
Integrations or scripts that create group prompts must use a manager account.

## Validation

`functional_tests/test_group_prompt_legacy_policy.py` pins both halves: the
three write routes refuse `User`, the two read routes still admit it, and no
server role list contains `PromptManager`. Pinning the preserved reads alongside
the refusal stops a later change from either widening writes again or locking
members out of reading.

It also pins the message: a refused member is told it is a role problem, a
non-member is still told they are not a member, and a non-member read keeps the
original message. With the old single message reinstated, the member case fails
while the two non-member cases still pass, so the test isolates exactly the
behaviour this fix introduced.

The broken-access-control scanner passes on `route_backend_group_prompts.py`.
