# V2 Model Catalog Workbench

## Overview

The V2 Model Catalog is now a native React workbench. V2 used to mount the classic
catalog module inside its 768px settings column, where the profile list and the
detail panel wrapped into one long, narrow strip: each list row repeated the summary,
publisher, origin, priority, and strong tasks, and one profile's detail ran several
screens long. Connected global models were listed as plain text.

The workbench keeps the same API, behaviour, and labels, and changes the reading:

- Each profile in the list is one line: name, publisher, and the number of global
  AI Connection models that use it.
- The list and the selected profile scroll separately inside a fixed-height pane.
- The detail splits into **Overview**, **Capabilities**, **Connections**, and
  **Evidence** tabs, with routing preferences in its header.
- A connected model opens its own AI Connection, scrolled to and outlining that model.

The classic page keeps its existing catalog, rendered by the shared module.

## Implemented in version: **0.261.256**

The application version is maintained in `application/single_app/config.py`.

**Dependencies:** the React/TypeScript V2 UI, local `lucide-react` icons, the admin
catalog API in `route_backend_models.py`, and `functions_model_catalog.py`. No new
packages, settings, or browser asset sources are required.

## Technical specifications

### Architecture

| File | Responsibility |
| --- | --- |
| `application/v2_ui/src/lib/modelCatalog.ts` | Types, filters, sorting, labels, safe evidence links, form helpers, API calls, and the shared profile-choice request. |
| `application/v2_ui/src/components/admin/ModelCatalogManager.tsx` | Toolbar, filters, list, saving, conflicts, discard prompts, and the React `CatalogProfilePicker`. |
| `application/v2_ui/src/components/admin/ModelCatalogDetail.tsx` | Detail header and the four tabs. |
| `application/v2_ui/src/components/admin/ModelCatalogEditor.tsx` | The custom profile form. |
| `application/v2_ui/src/stores/modelConnectionsStore.ts` | The connection focus request. |
| `application/v2_ui/src/components/admin/ModelConnectionsManager.tsx` | Answers focus requests and outlines the linked model. |
| `application/single_app/route_backend_models.py` | Adds `connection_id` and `model_id` to each admin `linked_models` entry. |

V2 no longer imports `static/js/admin/model_catalog_ui.js` or `model-catalog.css`, so
the V2 build stage in the Dockerfile no longer copies them and the unused
`model_catalog_ui.d.ts` declaration is removed. Classic still loads both.

### API

`GET /api/admin/model-catalog` (admin only) now returns, for each linked model:

```json
{
  "connection": "Primary connection",
  "connection_id": "endpoint-primary",
  "model": "prod-gpt-5",
  "model_id": "model-0",
  "enabled": true,
  "capabilities": {"processesText": true}
}
```

`connection_id` and `model_id` are additive; `model_id` is empty for a model saved
without an id, and the editor then matches the model by its display name. The user
catalog, `GET /api/models/catalog`, still carries no deployment inventory.

### Behaviour kept from the classic module

- Filtering and sorting match: favorites first, then by name; a task filter keeps
  Strong and Suitable ratings.
- Saves send the catalog `etag`; a 409 or validation error keeps the form as typed.
- Unsaved edits ask before they are discarded, in the page and on unload.
- Controls are disabled while a request runs, and focus returns afterwards.
- A save refreshes model availability and announces `model-catalog-changed`.
- Field labels match, except capability labels, which read as sentences, for example
  **Processes text** instead of **processes Text**.

### Click-through to AI Connections

Selecting **Open in AI Connections** leaves a focus request in
`modelConnectionsStore` and brings the AI Connections section into view, clearing a
search or changing category only when they hide it. The global connection list answers
the request once it has loaded: it opens that connection's editor, scrolls to the model,
and outlines it. Group and personal connection lists ignore the request, and a
connection that no longer exists reports so instead of opening.

### Profile picker

`CatalogProfilePicker` in the connection editor is a React select with the same
**Catalog profile** label and option text. All pickers on the page share one request
for the profile list, which a catalog save invalidates.

## Usage

Open **Admin Settings > AI Models** in V2. Search or filter, then select a profile.
Use **Favorite** and **Priority** in the header to set routing preferences. Select the
connected-model count, or the **Connections** tab, to see the global models using the
profile, and **Open in AI Connections** to review one. See
[Model Catalog](../../admin/model-catalog.md#find-and-inspect-a-profile-in-v2).

## Testing and validation

- `functional_tests/test_v2_model_catalog_logic.ts`, run by
  `test_v2_model_catalog_workbench.py`, executes filtering, sorting, labels, payloads,
  safe links, and the shared request against `modelCatalog.ts`.
- `functional_tests/test_v2_model_catalog_workbench.py` pins the classic/V2 boundary
  and the click-through wiring.
- `functional_tests/test_model_catalog_api.py` checks the new link ids for
  administrators and their absence from the user catalog.
- `ui_tests/test_model_catalog_management.py` runs the profile, preference, archive,
  validation, conflict, and refresh workflows against both the classic module and the
  V2 component.
- `ui_tests/test_v2_admin_model_catalog_workbench.py` drives the built SPA: one-line
  rows, keyboard tabs, the connected-model click-through, the search-reveal path, and
  no overflow at 390px and at 1920px with 200% text.

### Known limitations

- The workbench links global connections only; personal and group connections remain
  in their workspaces.
- Effective capabilities in the Connections tab come from the catalog response and
  update after a reload.

Related: [V2 Admin Settings Layout and Hierarchy](V2_ADMIN_SETTINGS_LAYOUT_AND_HIERARCHY.md),
[Model Catalog Profiles and Auto Routing](MODEL_CATALOG_PROFILES_AND_AUTO_ROUTING.md).
