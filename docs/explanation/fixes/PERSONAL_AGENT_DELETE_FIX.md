# Personal Agent Delete Returned An Error After Succeeding

## Issue

`DELETE /api/user/agents/<agent_name>` deleted the agent and then answered `400`. The agent
was gone, but the caller was told the operation had failed.

The classic workspace never hit this, because it does not use the route. `deleteAgent` in
`workspace_agents.js` fetches the whole agent list, removes one entry and POSTs the
remainder back — a read-modify-write around a delete endpoint that already existed. That
workaround is itself lossy: two browser tabs open on the workspace overwrite each other, and
any agent the client did not know about is deleted.

A second, separate defect: the route performed no governance check. The collection save
calls `ensure_governance_access('governance_user_agents', ...)`, and so does
`save_personal_agent`, but neither the delete route nor `delete_personal_agent` did. A user
governance had denied could still delete their agents.

**Fixed in version:** 0.261.041

## Root cause

The route deleted the agent first and validated afterwards:

```python
delete_personal_agent(user_id, agent_name)
log_agent_deletion(...)

remaining_agents = get_personal_agents(user_id)
if len(remaining_agents) > 0:
    found = any(a.get('name') == global_selected_name for a in remaining_agents)
    if not found:
        return jsonify({'error': 'There must be at least one agent matching the global_selected_agent.'}), 400
```

`global_selected_name` comes from `settings.get('global_selected_agent', {}).get('name')`.
When no global agent is configured — the default — it is `None`. Nothing in the remaining
list equals `None`, so `found` is `False` and the route returns `400`, *after* the delete has
already been committed.

The condition therefore fired on every delete that left at least one agent behind, in any
deployment without a global agent configured. It also compared a *personal* agent list
against a *global* selection, which are not the same set of agents; the equivalent check on
the collection save is correctly conditioned on `per_user_semantic_kernel` being off.

## Changes

### `application/single_app/route_backend_agents.py`

The guard now runs before anything is deleted, so a refusal means nothing was removed:

```python
settings = get_settings()
global_selected_agent = settings.get('global_selected_agent', {}) or {}
global_selected_name = global_selected_agent.get('name')
if global_selected_name and agent_name == global_selected_name:
    return jsonify({'error': 'Cannot delete the agent set as global_selected_agent. ...'}), 400

if not delete_personal_agent(user_id, agent_to_delete.get('id') or agent_name):
    return jsonify({'error': 'Agent not found.'}), 404
```

The post-delete block is removed entirely. The pre-delete guard is kept — refusing to delete
the agent a global selection points at is legitimate — but it is now conditioned on a global
name actually being configured.

Governance is enforced before the delete:

```python
try:
    ensure_governance_access('governance_user_agents', user_id)
except PermissionError as exc:
    return jsonify({'error': str(exc)}), 403
```

The route parameter changed from `<agent_name>` to `<agent_id>` and resolves by id first,
falling back to name. `delete_personal_agent` already accepted either, so no storage change
was needed. Name-keyed addressing was fragile: `GET /api/user/agents` can merge personal and
global agents, which permits duplicate names, and a name is editable.

### Related

`GET` and `PATCH` on `/api/user/agents/<agent_id>` were added alongside the fix, so a client
no longer has to replace the whole collection to change one agent. The same was done for
personal actions and personal model endpoints. See
`docs/explanation/features/V2_MY_WORKSPACE.md`.

## Impact

- Deleting a personal agent through the API now reports success when it succeeds.
- A user denied by governance can no longer delete personal agents.
- The V2 interface deletes and edits one agent at a time, so two open tabs no longer
  overwrite each other.
- The classic interface is unaffected. Its whole-collection POST still works, and its
  read-modify-write delete still functions; it is simply no longer necessary.

## Validation

`functional_tests/test_personal_resource_per_item_rest.py` covers both defects
structurally, rather than by asserting on the text of the fix:

- `test_agent_delete_checks_before_it_deletes` locates the guard and the delete call within
  the route body and asserts the guard comes first, then asserts no `400` is returned after
  the delete at all.
- `test_agent_delete_enforces_governance` asserts `ensure_governance_access` is present and
  precedes the delete.

Both fail against the previous implementation. Also re-run:

```powershell
python .\functional_tests\route_tests\test_route_blueprint_policy_inventory.py
python .\functional_tests\test_route_authentication_audit_findings_fix.py
```
