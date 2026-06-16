# Tableau Action

Implemented in version: **0.241.210**

Related config.py version update: `application/single_app/config.py` is **0.241.210** for this implementation.

## Overview

The Tableau action lets users connect SimpleChat agents to Tableau Server or Tableau Cloud through a first-class, read-only action. It uses Tableau's supported Python REST client, `tableauserverclient`, and exposes content discovery tools for projects, workbooks, views, datasources, and workbook details.

The action has its own configuration workflow in the Add/Edit Action modal. It does not reuse OpenAPI, Databricks, or generic action forms.

Fixed/Implemented in version: **0.241.210**

## Dependencies

- Python package: `tableauserverclient==0.40`
- Tableau Server or Tableau Cloud HTTPS base URL
- Tableau personal access token, username/password credentials, or a reusable workspace identity
- Existing SimpleChat action storage, Key Vault secret handling, and Semantic Kernel plugin loading

## Technical Specifications

- Plugin type: `tableau`
- Runtime plugin: `semantic_kernel_plugins.tableau_plugin.TableauPlugin`
- Factory: `semantic_kernel_plugins.tableau_plugin_factory.TableauPluginFactory`
- Shared defaults and normalization: `functions_tableau_operations.py`
- Additional settings schema: `application/single_app/static/json/schemas/tableau_plugin.additional_settings.schema.json`
- Allowed auth definition: `application/single_app/static/json/schemas/tableau.definition.json`

Supported Semantic Kernel functions are read-only:

- `search_tableau_content`
- `list_projects`
- `list_workbooks`
- `list_views`
- `list_datasources`
- `get_workbook_details`

The initial implementation intentionally excludes publish, update, delete, refresh, and administrative operations.

## Configuration Options

- `server_url`: Tableau Server or Tableau Cloud base URL.
- `site_content_url`: optional Tableau site content URL; blank uses the default Tableau Server site.
- `auth_method`: `personal_access_token` or `username_password`.
- `pat_name`: Tableau PAT name for PAT authentication.
- `page_size`: REST API page size, bounded from 1 to 1000.
- `max_results`: per-call item limit, bounded from 1 to 1000.
- `timeout`: HTTP timeout in seconds, bounded from 1 to 300.
- `use_server_version`: enables Tableau Server Client version negotiation.

## Usage Instructions

Create a new action from a personal, group, or admin action surface and choose **Tableau**. Enter the Tableau Server URL and optional site content URL. Choose either personal access token or username/password authentication.

For PAT authentication, provide both the PAT name and PAT secret. For reusable identities, select an action-capable identity from the Tableau identity selector. API key reusable identities provide the PAT secret, while the Tableau form still requires the PAT name. Username/password reusable identities provide the Tableau username and password.

After saving the action, assign it to agents that need Tableau content discovery. Agents can list and search Tableau content that the configured Tableau credentials can access.

## Testing and Validation

- Functional coverage: `functional_tests/test_tableau_action_plugin.py`
- UI coverage: `ui_tests/test_tableau_action_modal_workflow.py`
- JavaScript syntax checks: `plugin_modal_stepper.js` and `workspace/view-utils.js`
- Python compile checks cover the Tableau helper, plugin, factory, loader, route, and identity updates.

## Known Limitations

- The action is read-only in version 0.241.210.
- Tableau permissions are enforced by Tableau for the configured credentials.
- Live connectivity is validated only when credentials and a reachable Tableau site are configured in the running app.