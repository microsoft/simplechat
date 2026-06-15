---
description: "Use when: auditing SimpleChat Python routes, helpers, or plugins for Broken Access Control, IDOR, BOLA, user_id/object-id misuse, or missing ownership/membership checks."
name: "Broken Access Control Audit"
argument-hint: "Target paths, feature area, endpoint list, or incident class to audit"
agent: "agent"
---

Audit the requested SimpleChat code for Broken Access Control, IDOR, and BOLA-style issues. Focus on places where caller-controlled object identifiers cross into reads, writes, search queries, blob access, plugin calls, or profile/settings lookups without a fresh authorization decision for that exact object.

Use the repository guardrails in [.github/instructions/broken-access-control-prevention.instructions.md](../instructions/broken-access-control-prevention.instructions.md) and the deterministic checker in [scripts/check_broken_access_control.py](../../scripts/check_broken_access_control.py). If the user did not provide target paths, start with changed files and likely surfaces under `application/single_app/route_backend_*.py`, `application/single_app/route_external_*.py`, `application/single_app/functions_*.py`, and `application/single_app/semantic_kernel_plugins/`.

## Audit Workflow

1. Identify entry points: Flask routes, Semantic Kernel `@kernel_function` methods, background task dispatchers that accept request-derived IDs, and helpers called by those surfaces.
2. Trace each object identifier from source to sink. Treat route path parameters, request JSON, query args, form values, active settings, hidden fields, plugin arguments, client state, and datastore-provided owner/participant IDs as untrusted until proven otherwise.
3. For each sensitive sink, verify an authorization decision at or immediately before the sink. Sensitive sinks include Cosmos `read_item`, `query_items`, `upsert_item`, `delete_item`, blob reads/writes, Azure Search operations, Graph calls that reveal identity data, file downloads, profile images, conversation messages, documents, groups, public workspaces, and user settings.
4. Distinguish role checks from object checks. `@login_required`, `@user_required`, `@admin_required`, GUID entropy, Graph search availability, and frontend-only access are not sufficient for object-level authorization.
5. Look for reverse-resolution or oracle behavior: endpoints that turn known opaque IDs into names, emails, profile images, app membership, document ownership, conversation membership, or existence signals.
6. Compare the implementation against approved helper patterns such as `_authorize_personal_conversation_read(...)`, `_authorize_personal_conversation_access(...)`, `_authorize_user_profile_access(...)`, `_read_authorized_user_profile_document(...)`, `get_user_settings(...)`, `assert_group_role(...)`, `require_active_group(...)`, `require_active_public_workspace(...)`, `_resolve_authorized_scope_arguments(...)`, `_resolve_blob_location_with_fallback(...)`, and `_resolve_authorized_fact_memory_call(...)`.
7. Run the checker where useful:

```powershell
python scripts/check_broken_access_control.py --full-file <path1.py> <path2.py>
```

For a repository-wide audit, use the GitHub Actions workflow `Broken Access Control Full Scan` or run the checker over tracked Python files locally.

## Output Format

Return findings first, ordered by severity. For each finding include:

- `Severity`: Critical, Important, Moderate, or Low.
- `Surface`: endpoint/helper/plugin and file path.
- `Source`: the untrusted object ID.
- `Sink`: the protected data or mutation.
- `Missing Check`: the absent ownership, membership, admin, or relationship validation.
- `Impact`: realistic data or operation exposed.
- `Remediation`: the specific helper or object-level guard to add.
- `Regression Test`: the minimum test that should fail before the fix and pass after.

If no issues are found, say that clearly and list any residual blind spots, such as dynamic authorization hidden behind decorators or code paths that need runtime tests.