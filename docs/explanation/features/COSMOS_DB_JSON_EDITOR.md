# Cosmos DB JSON Editor

Implemented in version: **0.250.048**
Refined in version: **0.250.049**
Save-path fix in version: **0.250.050**
Results scrolling refined in version: **0.250.051**

## Overview and Purpose

The Cosmos DB JSON Editor adds an admin-only Data Management tool for targeted SimpleChat Cosmos DB inspection and repair. It lets administrators choose a known SimpleChat container, run a paged read-only query, select a result, edit the full JSON document, and save it back after explicit danger confirmation.

Related issue:
- microsoft/simplechat#1006

Related config update:
- `application/single_app/config.py` reports version `0.250.051`.

Dependencies:
- `application/single_app/functions_data_management.py`
- `application/single_app/route_backend_data_management.py`
- `application/single_app/templates/_sidebar_nav.html`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_data_management.js`

## Technical Specifications

Architecture overview:
- The UI lives in the existing Admin Settings > Data Management tab.
- The container dropdown is populated from a backend allowlist of SimpleChat Cosmos containers and partition key metadata.
- Empty queries run as `SELECT * FROM c`, respect the selected page size up to the 100-document cap, and do not expose continuation paging.
- Custom queries must start with `SELECT`, are capped to 100 results per request, and use Cosmos continuation tokens for Next Page.
- Query results return lightweight summaries in a modal with an independently scrollable results pane. Selecting a result loads the full document by `id` and partition key in the modal editor pane.
- Saves require the loaded ETag and use `MatchConditions.IfNotModified` to prevent overwriting a document that changed after it was opened.
- Saves replace the loaded document through the SDK-supported item/link target and do not pass unsupported transport kwargs to `replace_item`.
- The backend rejects attempts to change `id` or the selected container partition key value.
- Cosmos editor actions are recorded as Data Management activity records, including query execution, document open, save success, rejected attempts, and failures.

Security controls:
- Every editor endpoint is under `/api/admin/data-management/cosmos-editor/...`.
- Routes require `@swagger_route(security=get_auth_security())`, `@login_required`, and `@admin_required`.
- The browser interface is locked behind a Bootstrap danger modal for each page session.
- Saves require a second Bootstrap confirmation modal and the phrase `I understand this can damage system data`.
- Activity logs store metadata and changed paths, not full document bodies.
- The frontend uses safe DOM APIs and `textContent`; no unsafe HTML injection sinks are used.

## Usage Instructions

How to use:
1. Open Admin Settings.
2. Select Data Management.
3. In Cosmos DB JSON Editor, select Unlock Editor.
4. Read and accept the danger prompt.
5. Choose a container.
6. Leave the query empty to browse up to the selected page size, capped at 100 documents, or enter a targeted `SELECT` query.
7. Run the query to open the results modal.
8. Select a result to load the full JSON document.
9. Edit the JSON.
10. Select Save JSON, review the change summary, type the confirmation phrase, and save.

Paging behavior:
- Empty browse mode intentionally stops after one page and uses the selected page size up to 100 documents.
- Custom SELECT mode returns up to 100 documents per page and enables Next Page when Cosmos returns a continuation token.

## Testing and Validation

Functional coverage:
- `functional_tests/test_data_management_security_patterns.py`

UI coverage:
- `ui_tests/test_admin_data_management_settings_ui.py`

Validation focus:
- admin-only route protection
- SELECT-only query validation
- page-size cap and continuation-token workflow
- danger gate and save confirmation workflow
- immutable `id` and partition key enforcement
- ETag-based optimistic concurrency
- Activity Log audit coverage for editor operations

## Known Limitations

- This tool edits one document at a time and intentionally does not support bulk updates.
- Query parameters are not yet exposed in the UI; administrators should write complete targeted SELECT statements.
- The editor is intended for expert administrative repair and investigation, not routine content management.
