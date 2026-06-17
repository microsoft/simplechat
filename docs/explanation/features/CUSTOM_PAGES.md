# Custom Pages

Current version: **0.242.040**

Implemented in version: **0.242.023**

Example pages added in version: **0.242.024**

Restart acknowledgement implemented in version: **0.242.025**

File list editor implemented in version: **0.242.026**

Admin access and `.html` alias implemented in version: **0.242.027**

Single-source developer guide modal implemented in version: **0.242.028**

In-app canonical guide source implemented in version: **0.242.029**

Large menu handling implemented in version: **0.242.030**

Drawer menu threshold implemented in version: **0.242.031**

Drawer trigger handoff implemented in version: **0.242.032**

Static asset video example implemented in version: **0.242.033**

Literal role enforcement implemented in version: **0.242.034**

Admin-as-User role hierarchy implemented in version: **0.242.035**

Request Access example and access levels implemented in version: **0.242.036**

Request Access guidance modal and duplicate slug checks implemented in version: **0.242.037**

Authenticated custom page navigation fix implemented in version: **0.242.040**

## Overview

Custom Pages let app teams that deploy SimpleChat add trusted, deployment-time pages under the `/custom` namespace without changing the core application route code. The feature is controlled by the Admin Settings toggle `enable_custom_pages` and fails closed when disabled.

## Dependencies

- Flask host routes in `application/single_app/route_custom_pages.py`
- Cosmos DB metadata container `custom_pages`, configured in `application/single_app/config.py`
- Static file folders under `application/single_app/custom_pages/`: `assets`, `css`, `html`, `js`, `json`, and `python`
- Admin Settings metadata designer in `application/single_app/templates/admin_settings.html`

## Technical Specifications

Custom Pages uses always-registered host routes and request-time dispatch. Static page metadata is stored in Cosmos DB so simple page definitions persist across container lifecycle events. Python-backed pages are trusted code shipped with the deployed artifact and discovered from `custom_pages/python` using `CustomPageExtension` subclasses or the `@custom_page` decorator.

The host routes are:

- `/custom/<slug>` for page rendering
- `/custom/<slug>.html` as a familiar static-page alias for page rendering
- `/custom/assets/<slug>/<folder>/<path:filename>` for declared static assets
- `/api/custom/<slug>/<path:operation>` for Python-backed custom page operations
- `/api/admin/custom-pages` for Admin Settings metadata management

Static pages are rendered through `custom_page_shell.html` after the host route applies `@login_required` and `@user_required`. Static HTML content is treated as trusted deployment-time app-team content and is not end-user supplied.

## Configuration Options

- `enable_custom_pages`: Enables or disables all `/custom` page and asset routes.
- `custom_pages_menu_name`: Controls the navigation label when pages are grouped.
- `custom_pages_force_menu`: Forces custom pages to display as a menu even when only one or two pages exist.

The feature version was updated in `application/single_app/config.py` from `0.242.022` to `0.242.023`.

The example page set was added with version `0.242.024`.

Version `0.242.025` added a restart acknowledgement modal for first-time enablement and records the acknowledgement to `activity_logs` as `custom_pages_enabled_acknowledged`.

Version `0.242.026` replaced comma-separated CSS, JavaScript, asset, and JSON text fields with explicit add/remove file list editors.

Version `0.242.027` added `/custom/<slug>.html` as a compatibility alias and improved modal spacing for deployed files and publishing toggles.

Version `0.242.028` added a single-source developer guide modal.

Version `0.242.029` moved the canonical guide source into `application/single_app/docs/how-to/custom_pages.md` so non-container deployments and ACR-built containers receive the guide with the app artifact. The docs how-to page now links to that in-app source instead of duplicating the guide.

Version `0.242.030` clarified forced menu behavior with page count badges and bounded scrolling in sidebar, top navigation, and mobile navigation menus.

Version `0.242.031` changed large custom page sets to use a dedicated drawer when more than five pages are available. One or two pages can stay inline unless the menu is forced, three to five pages use a compact grouped menu, and six or more pages open the drawer with its own scroll area.

Version `0.242.032` added a shared drawer trigger handler so mobile navigation closes before the Custom Pages drawer opens.

Version `0.242.033` added `cat.mp4` as a declared asset in the static example page and renders it with an HTML video viewer.

Version `0.242.034` removed the admin bypass from custom page authorization. When a page has Allowed Roles configured, every user must have at least one exact matching role in the current session.

Version `0.242.035` treats `Admin` as satisfying the base `User` role while still requiring exact matches for all other page-specific roles.

Version `0.242.036` added access levels, a repo-shipped Request Access static page, a one-click Admin Settings action to create its metadata, and an access-denied home-page button for signed-in users without app roles. The earlier learning examples were moved out of live custom pages into `application/single_app/docs/how-to/custom_pages_examples/`.

Version `0.242.037` added post-create guidance for editing the Request Access email address, disables the one-click Request Access helper once `request-access` exists, and prevents duplicate slugs in both the Admin Settings modal and create API.

Version `0.242.040` changed navigation rendering so Custom Pages appears for any signed-in user only when `custom_pages_nav` contains at least one enabled, visible, authorized page. This allows `access_level=authenticated` pages such as Request Access to render for signed-in users without `User` or `Admin`, while hiding the pane when no custom page is available.

## Usage Instructions

Admins can open Admin Settings > Custom Pages to enable the feature and create metadata for simple static pages. Metadata references files already deployed under `application/single_app/custom_pages/html`, `css`, `js`, `assets`, and `json`.

For CSS, JavaScript, asset, and JSON references, admins add one file at a time using the Add button in the metadata designer. The backend still persists those values as arrays in the `custom_pages` Cosmos container.

When Allowed Roles is blank, any signed-in app user can access the custom page. When Allowed Roles has values, users must have at least one matching role in the current session. `Admin` satisfies `User`, but `Admin` does not satisfy arbitrary custom roles. Unknown role names do not grant access.

Access Level controls the base gate before page-specific roles are checked. `App users only` requires `User` or `Admin`. `Any signed-in user` requires login but does not require the base app role, and is intended for bootstrap pages such as Request Access.

When enabled, authorized pages appear in top and left navigation between Chat and the Support/External Links area. When disabled, `/custom` routes return Not Found before metadata lookup, file access, or Python extension dispatch.

When Custom Pages is enabled but no custom page metadata or Python-backed pages are available, the navigation still shows the Custom Pages section with a `No custom pages registered` empty state.

When an admin enables Custom Pages from a disabled state, the Admin Settings UI displays a restart acknowledgement modal. The setting is only accepted after acknowledgement, and the successful save writes an activity log record because App Service restart is required before newly deployed custom page files and Python-backed pages are fully active.

## Example Pages

The repository includes three deployment-time examples:

- `example-simple.html`: A minimal HTML fragment that only needs metadata in the Admin Settings designer.
- `example-static.html`, `example-static.css`, and `example-static.js`: A static page with page-specific CSS and JavaScript.
- `example_python_dashboard.py`: A Python-backed page that renders `example-python-dashboard.html` as a Jinja template and exposes `/api/custom/example-python-dashboard/status` through the host dispatcher.

The Python-backed example is discovered from code, so it should not be created in the metadata designer. Static examples are stored in Cosmos through the designer.

## Testing and Validation

Functional coverage was added in `functional_tests/test_custom_pages_wiring.py`. It validates version/configuration wiring, protected route registration, Admin Settings UI wiring, navigation integration, and the trusted HTML rendering boundary without requiring live Cosmos DB connectivity.

Known limitations:

- The Admin Settings designer manages metadata only; app teams still deploy the referenced files as part of the application artifact.
- Python-backed pages are trusted deployment-time extensions, not arbitrary runtime code uploaded by users.