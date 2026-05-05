---
applyTo: '**/*.py'
---

# Security: Broken Access Control Prevention

## Critical Requirement

**NEVER treat caller-supplied ids or stored active-scope settings as authorization decisions after login.**

Treat all of the following as untrusted authorization inputs unless the code proves otherwise:

- `conversation_id`, `message_id`, `document_id`, `file_id`, `approval_id`, `group_id`, and `public_workspace_id`
- `activeGroupOid` and `activePublicWorkspaceOid` values loaded from user settings
- Plugin or tool-call arguments such as `user_id`, `conversation_id`, `group_id`, `public_workspace_id`, `scope_id`, and `scope_type`

## Preferred Safe Patterns

Use these patterns by default:

- Revalidate personal conversation ownership with `_authorize_personal_conversation_read(...)`, `_authorize_personal_conversation_access(...)`, or an explicit owner check before reading dependent data.
- Route `activeGroupOid` writes through `update_active_group_for_user(...)`.
- Route `activePublicWorkspaceOid` writes through `update_active_public_workspace_for_user(...)`.
- Resolve active group scope through `require_active_group(...)` instead of raw settings reads in backend and plugin code.
- Resolve active public workspace scope through `require_active_public_workspace(...)` instead of raw settings reads in backend and plugin code.
- In Semantic Kernel plugins, normalize tool-call scope ids through `_resolve_authorized_scope_arguments(...)`, `_resolve_blob_location_with_fallback(...)`, or `_resolve_authorized_fact_memory_call(...)` before storage, blob, or Cosmos access.
- Prefer request-scoped authorization context such as `g.authorized_chat_context` over raw tool arguments.

## Disallowed Patterns For New Code

Do not add new code that does any of the following without a reviewed exception:

- Call `update_user_settings(...)` with a literal `{"activeGroupOid": ...}` payload outside `update_active_group_for_user(...)`
- Call `update_user_settings(...)` with a literal `{"activePublicWorkspaceOid": ...}` payload outside `update_active_public_workspace_for_user(...)`
- Read `activeGroupOid` or `activePublicWorkspaceOid` directly from raw settings in backend routes or plugins when a shared validator exists
- Expose `user_id`, `conversation_id`, `group_id`, `public_workspace_id`, `scope_id`, or `scope_type` in a `@kernel_function` surface without immediately rebinding those values to the authorized request context
- Read a personal conversation by request-derived `conversation_id` and continue to message, blob, or feedback work without an explicit ownership boundary

## Safe Examples

```python
conversation_item = _authorize_personal_conversation_read(user_id, conversation_id)
messages = list(
    cosmos_messages_container.query_items(
        query=query,
        partition_key=conversation_item['id'],
    )
)
```

```python
update_active_group_for_user(requested_active_group, user_id=user_id)
active_group_id = require_active_group(user_id)
```

```python
authorized_scope = self._resolve_authorized_fact_memory_call(
    scope_type=scope_type,
    scope_id=scope_id,
    conversation_id=conversation_id,
)
```

## Unsafe Examples

```python
update_user_settings(user_id, {'activeGroupOid': group_id})
```

```python
active_group_id = settings.get('settings', {}).get('activeGroupOid')
```

```python
@kernel_function(name='unsafe_tool')
def unsafe_tool(self, user_id: str, conversation_id: str, group_id: str = ''):
    return self.store.lookup(user_id=user_id, conversation_id=conversation_id, group_id=group_id)
```

```python
conversation_item = cosmos_conversations_container.read_item(
    item=conversation_id,
    partition_key=conversation_id,
)
```

## PR Review Checklist

For any Python change that reads or mutates user, group, workspace, conversation, or plugin-scoped data:

1. Identify every caller-controlled id that crosses into a data read or mutation.
2. Revalidate ownership or membership at the sensitive operation boundary, not just at route entry.
3. Use the dedicated active-scope validators instead of raw settings reads and writes.
4. Rebind plugin scope parameters to the authorized request context before storage, blob, or Cosmos access.
5. Add or update a regression test when the change touches an authorization boundary.

## Workflow Guardrail

This repository includes a Development PR check in `.github/workflows/broken-access-control-check.yml` backed by `scripts/check_broken_access_control.py`.

If a reviewed exception is unavoidable, add the suppression token below near the specific line and include a justification comment:

```text
bac-check: ignore
```

Use that escape hatch rarely. It is for reviewed legacy exceptions, not normal route or plugin code.