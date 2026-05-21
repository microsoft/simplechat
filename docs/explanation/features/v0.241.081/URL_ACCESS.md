# URL Access

## Overview
URL Access is a shared, admin-governed direct URL review capability for chat and personal workflows. It lets users explicitly opt in to reviewing HTTP(S) URLs they paste into a prompt without turning every pasted link into an automatic fetch. The feature reuses Source Review's URL safety checks and evidence formatting while keeping Deep Research as a separate user-facing research mode.

Implemented in version: **0.241.081**

Config version reference: `application/single_app/config.py` version `0.241.082` after the `UrlAccessUser` governance update.

## Dependencies
- URL safety and evidence extraction in `functions_source_review.py`
- Admin settings defaults and sanitization in `functions_settings.py`
- Chat request handling in `route_backend_chats.py`
- Workflow persistence in `functions_personal_workflows.py`
- Workflow execution in `functions_workflow_runner.py`
- Workflow authoring UI in `workspace.html` and `workspace_workflows.js`

## Technical Specifications
- Admin toggle: `enable_url_access`
- Chat limit: `url_access_max_chat_urls_per_turn`, hard-capped at 100 URLs per chat turn
- Workflow limit: `url_access_max_workflow_urls_per_run`, hard-capped at 500 URLs per workflow run
- Shared domain policy: `url_access_allowed_domains` and `url_access_blocked_domains`
- Legacy aliases: `source_review_allowed_domains` and `source_review_blocked_domains` remain synchronized for existing Deep Research settings
- Workflow opt-in field: `url_access_enabled`
- Optional role gate: `require_member_of_url_access_user` with Entra app role `UrlAccessUser` added in version **0.241.082**
- Runtime context: workflow runs use `URL_ACCESS_CONTEXT_WORKFLOW`

URL Access uses Source Review in `url_access_only=True` mode. That mode reviews only the direct URLs supplied by the user or workflow prompt, does not run Deep Research traversal or web-search query planning, and injects bounded evidence as untrusted source context for the model or agent invocation.

## Usage Instructions
1. Open Admin Settings.
2. Go to Search & Extract.
3. Enable `URL Access for chat and workflows`.
4. Set chat and workflow URL limits.
5. Optionally require the `UrlAccessUser` Enterprise App role.
6. Optionally configure allowed and blocked domain rules.
7. In chat, paste HTTP(S) URLs and select the `URLs` button before sending.
8. In a personal workflow, enable `Allow URL Access for this workflow` before saving the workflow.

## Workflow Behavior
- The workflow prompt is stored as the user-authored message without injected evidence text.
- When the saved workflow has `url_access_enabled: true`, the runner validates the prompt URLs against the workflow limit and admin enablement.
- Scheduled and manual runs share the same server-side validation path.
- Reviewed URL evidence is added only to the execution context and is recorded in workflow metadata and citations for auditability.
- If admins later disable URL Access and a saved workflow still requests it with URLs, the run fails with a clear administrator-disabled error.

## Testing and Validation
- `functional_tests/test_source_review_security.py` validates URL Access defaults, limit clamping, domain aliases, and request validation.
- `functional_tests/test_deep_research_explicit_toggle.py` validates Deep Research remains explicitly selected and can coexist with URL Access.
- `functional_tests/test_workflow_url_access_policy.py` validates workflow storage, UI, JavaScript payload, and runner wiring.
- `ui_tests/test_admin_source_review_settings.py` validates the admin URL Access section.
- `ui_tests/test_workspace_workflow_url_access.py` validates the workflow modal URL Access switch and browser-facing settings.
- `docs/explanation/features/v0.241.082/URL_ACCESS_APP_ROLE.md` documents the `UrlAccessUser` governance option.

## Known Limitations
- URL Access does not bypass Source Review safety controls for localhost, literal IP targets, metadata hosts, credentialed URLs, unsafe redirects, unsupported content types, or oversized pages.
- Domain allow/block rules apply to both chat and workflow URL Access.
- URL Access is explicit. Plain URL presence in a chat message or workflow prompt does not trigger fetching by itself.