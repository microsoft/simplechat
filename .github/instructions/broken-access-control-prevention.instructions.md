---
applyTo: '**/*.py'
---

# Security: Broken Access Control Prevention

## Critical Requirement

**NEVER treat caller-supplied ids or stored active-scope settings as authorization decisions after login.**

Treat all of the following as untrusted authorization inputs unless the code proves otherwise:

- `conversation_id`, `message_id`, `document_id`, `file_id`, `approval_id`, `group_id`, and `public_workspace_id`
- `user_id`, Entra object IDs, owner IDs, participant IDs, shared user IDs, and any other identity value supplied by a route path, request body, query string, plugin argument, client-side state, or datastore field
- `activeGroupOid` and `activePublicWorkspaceOid` values loaded from user settings
- Plugin or tool-call arguments such as `user_id`, `conversation_id`, `group_id`, `public_workspace_id`, `scope_id`, and `scope_type`

## Preferred Safe Patterns

Use these patterns by default:

- Revalidate personal conversation ownership with `_authorize_personal_conversation_read(...)`, `_authorize_personal_conversation_access(...)`, or an explicit owner check before reading dependent data.
- Revalidate user-profile and user-settings reads with an object-level helper such as `_authorize_user_profile_access(...)`, `_read_authorized_user_profile_document(...)`, or `get_user_settings(...)` instead of reading arbitrary user documents by request-derived `user_id`.
- For cross-user profile display, prove a legitimate app relationship at the read boundary: self, Admin, shared group membership with view allowed, shared document relationship, or shared collaboration conversation participation.
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
- Call `cosmos_user_settings_container.read_item(...)` from frontend/API routes with a route, query, or body `user_id` unless an object-level user-profile authorization helper has already allowed that exact target.
- Treat `@login_required`, `@user_required`, `@admin_required`, Graph lookup availability, GUID opacity, or frontend-only UI reachability as sufficient authorization for another user's profile, settings, photo, membership, or ownership metadata.
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

```python
user_doc = cosmos_user_settings_container.read_item(
    item=user_id,
    partition_key=user_id,
)
```

## PR Review Checklist

For any Python change that reads or mutates user, group, workspace, conversation, or plugin-scoped data:

1. Identify every caller-controlled id that crosses into a data read or mutation.
2. For every object id, answer: "Why can this caller read or mutate this exact target object?" Do not rely on login, role-only decorators, hidden UI, GUID entropy, or prior lookup flows.
3. Revalidate ownership, membership, or another explicit relationship at the sensitive operation boundary, not just at route entry.
4. For reverse lookups from opaque IDs to identity metadata, verify that the endpoint does not become a user-enumeration or app-membership oracle.
5. Use the dedicated active-scope validators instead of raw settings reads and writes.
6. Rebind plugin scope parameters to the authorized request context before storage, blob, or Cosmos access.
7. Add or update a regression test when the change touches an authorization boundary.

## Workflow Guardrail

This repository includes a Development PR check in `.github/workflows/broken-access-control-check.yml` backed by `scripts/check_broken_access_control.py`.

For full-code audits, run the manual GitHub Actions workflow `.github/workflows/broken-access-control-full-scan.yml`. It scans tracked Python files under the selected target paths, uploads a report artifact, and defaults to advisory mode because legacy findings may exist. Set `fail_on_findings=true` only when the current baseline is clean enough for a blocking run.

For an agent-assisted review, run the workspace prompt `.github/prompts/broken-access-control-audit.prompt.md` and provide the feature area, target paths, or incident class you want reviewed.

If a reviewed exception is unavoidable, add the suppression token below near the specific line and include a justification comment:

```text
bac-check: ignore
```

Use that escape hatch rarely. It is for reviewed legacy exceptions, not normal route or plugin code.