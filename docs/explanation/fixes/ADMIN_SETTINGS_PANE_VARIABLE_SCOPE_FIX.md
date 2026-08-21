# Admin Settings Pane Variable Scope Fix

## Issue

After the Admin Settings information-architecture merge, every request to
`GET /admin/settings` returned **500 Internal Server Error** on the deployed
Azure App Service. The page loaded normally before the merge, and other pages
(`/`, `/api/user/settings`) continued to return 200.

The App Service container log showed nothing but the access-log line:

```
"GET /admin/settings HTTP/1.1" 500 265
```

The real exception was only present in Application Insights:

```
jinja2.exceptions.UndefinedError: 'analyze_capability' is undefined
  while handling: Exception on /admin/settings [GET]
```

**Fixed in version: `0.260.019`**

## Root cause

Admin Settings renders its tabs as sibling `{% include %}` partials under
`templates/admin/_panes/`. Jinja gives each included template its own copy of the
context, so a value assigned with `{% set %}` inside one pane is **not** visible
to the next pane.

The pane split moved the **Document Action Capabilities** card into
`admin/_panes/actions.html` but left the two `{% set %}` statements that feed it
behind in `admin/_panes/agents.html`:

```jinja
{# admin/_panes/agents.html - the card that used these had already moved away #}
{% set analyze_capability = settings.document_action_capabilities.analyze %}
{% set comparison_capability = settings.document_action_capabilities.comparison %}
```

`admin_settings.html` includes them as two separate siblings:

```jinja
{% include "admin/_panes/agents.html" %}
{% include "admin/_panes/actions.html" %}
```

So by the time `actions.html` evaluated `{% if analyze_capability.enabled %}`,
the name was `Undefined`, and attribute access on `Undefined` raises. Neither
name was used anywhere in `agents.html`, so the two statements were pure
leftovers there.

The failure is deterministic and data-independent — it is not Azure-specific.
Any run of the merged code fails; a local instance that appeared healthy was
serving pre-merge templates.

### Why the traceback never reached the container log

`setup_appinsights_logging()` calls `configure_azure_monitor()`, which attaches a
handler to the **root** logger. That has two consequences:

1. `logging.basicConfig(level=logging.DEBUG)` on the following line became a
   no-op, because `basicConfig` returns early when root already has handlers.
2. Flask's `create_logger()` calls `has_level_handler()`, walks up to root, finds
   that handler, and therefore **skips** attaching its own stderr handler.

The result was that `app.logger.exception("Exception on %s [%s]")` was delivered
to Application Insights and nowhere else, leaving the App Service console log
with no indication of why the request failed.

### Why the existing tests did not catch it

`functional_tests/test_support/templates.py::resolve_template_includes` inlines
every `admin/` include into a single flat string before assertions run. Once
flattened, `agents.html`'s `{% set %}` appears ahead of `actions.html`'s markup,
so every composed-template test saw a valid document. Detecting this class of bug
requires reading each pane **in isolation**.

## Files modified

| File | Change |
|------|--------|
| `application/single_app/templates/admin/_panes/agents.html` | Removed the two leftover `{% set %}` statements. |
| `application/single_app/templates/admin/_panes/actions.html` | Added both `{% set %}` statements at the top of the pane that renders the card, with a comment explaining the scoping rule. |
| `application/single_app/templates/admin/_panes/cosmos.html` | Qualified six bare `enable_dai_debug` references as `settings.enable_dai_debug`. |
| `application/single_app/templates/admin_settings.html` | Removed the dead `window.enableDocumentClassification` and `window.enableExternalLinks` bootstrap lines. |
| `application/single_app/static/js/admin/admin_settings.js` | Removed the matching dead `let` declarations. |
| `application/single_app/functions_appinsights.py` | Added `ensure_console_error_logging()`. |
| `application/single_app/app.py` | Called `ensure_console_error_logging(app.logger)` after Application Insights setup. |
| `application/single_app/config.py` | `VERSION` `0.260.018` -> `0.260.019`. |
| `functional_tests/test_admin_settings_pane_variable_scope.py` | New regression test. |
| `functional_tests/test_flask_exception_console_logging.py` | New regression test. |
| `functional_tests/test_admin_settings_template_composition.py` | Exempted tests that read pane partials directly from the compose-before-asserting rule. |
| `ui_tests/test_admin_document_action_capabilities_card.py` | Retargeted from the Agents tab to the Actions tab and extended to assert the rendered capability limits. |

### Related silent defects fixed

A Jinja AST scan of all 44 panes surfaced two more names that always resolved to
`Undefined`. Neither caused a 500, but both were broken:

- **`enable_dai_debug`** (`cosmos.html`, six references). The bare name was never
  passed by the route, so the Document Access Index debug controls, shadow
  validation metrics and reset modal never rendered even when an administrator
  enabled the setting. Now reads `settings.enable_dai_debug`.
- **`enable_document_classification` / `enable_external_links`**
  (`admin_settings.html`). These emitted `""` into `window.*` globals whose only
  consumers were two `let` declarations in `admin_settings.js` that nothing ever
  read. Both the producers and the dead declarations were removed rather than
  repaired: emitting `"{{ settings.enable_external_links }}"` would produce the
  string `"False"`, which is **truthy** in JavaScript and would silently flip
  `window.enableExternalLinks || false` to `true`.

Four further names reported by the scan (`option_value` in `extraction.html`;
`release_card_id`, `release_collapse_id`, `preview_card_id` and
`preview_collapse_id` in `latest-features.html`) are `{% set %}` inside their own
`{% for %}` bodies and resolve correctly. The regression test deliberately does
not flag them.

## Code changes

### `admin/_panes/actions.html`

```jinja
<div class="tab-pane fade{% if admin_landing_tab == 'actions' %} show active{% endif %}" id="actions" role="tabpanel" aria-labelledby="actions-tab">
    {# These live here, not in the Agents pane, because sibling
       {% include %} panes each render in their own scope: a value
       set in one pane is not visible to the next one. #}
    {% set analyze_capability = settings.document_action_capabilities.analyze %}
    {% set comparison_capability = settings.document_action_capabilities.comparison %}
    <div class="card p-3 mb-4" id="document-action-capabilities-card">
```

No route change was required. `admin_settings()` already sets
`settings['document_action_capabilities'] = normalize_document_action_capabilities(settings)`,
and `get_default_document_action_capabilities()` always supplies both `analyze`
and `comparison` with `enabled`, `chat_max_documents` and
`workflow_max_documents`, so no defensive `default()` filter is needed.

### `functions_appinsights.ensure_console_error_logging()`

Attaches a `logging.StreamHandler(sys.stderr)` pinned at `ERROR` to the supplied
logger, tagged with a marker attribute so repeated initialisation and gunicorn
worker reloads cannot stack duplicates. The root logger is deliberately left
untouched and the level is pinned at `ERROR`, so library `DEBUG` output can never
flood the container log. Called from `app.py` immediately after
`setup_appinsights_logging(settings)`.

## Testing

### `functional_tests/test_admin_settings_pane_variable_scope.py`

Five tests, reading each pane **individually** rather than through the composing
helpers:

1. `test_provided_names_are_discoverable` — the allowlist of template context
   names is parsed with `ast` from the `render_template('admin_settings.html', ...)`
   call in `route_frontend_admin_settings.py` and from the `dict(...)` returned by
   `inject_settings` in `app.py`, so it cannot go stale as variables are added or
   removed.
2. `test_every_pane_declares_the_values_it_uses` — `jinja2.meta.find_undeclared_variables`
   per pane, minus the discovered context names, minus any name assigned by a
   `{% set %}` in the same file (which suppresses the loop-scoped false positives).
3. `test_parent_template_declares_the_values_it_uses` — the same rule for the
   uncomposed `admin_settings.html`.
4. `test_document_action_capabilities_resolve_in_the_actions_pane` — targeted
   regression guard asserting `actions.html` both sets and uses the two capability
   values, and that `agents.html` no longer sets them.
5. `test_capability_panes_render_as_the_parent_composes_them` — renders
   `agents.html` and `actions.html` together through a real Jinja
   `FileSystemLoader`, exactly as the parent includes them, and asserts the
   configured limits reach the markup.

### `functional_tests/test_flask_exception_console_logging.py`

Four tests covering the logging guarantee: that a root handler satisfies
`has_level_handler` (the upstream behaviour that caused the suppression), that
tracebacks reach stderr, that the handler is attached exactly once, and that the
root logger is left alone.

### `functional_tests/test_admin_settings_template_composition.py`

That suite enforces that functional tests compose the parent template before
asserting on partial-only markup. Reading panes individually is now an explicit
exemption, because composing the parent inlines every pane into a single scope
and would hide precisely the dependency this fix is about.

### `ui_tests/test_admin_document_action_capabilities_card.py`

Retargeted from the Agents tab to the Actions tab, where the card now lives, and
extended to assert that each capability limit input renders a value. Because an
unresolved capability value takes the whole page down rather than rendering an
empty input, the existing `assert response.ok` in that test is a direct browser
level guard against this 500 returning.

## Validation

The new scope test was run against the pre-fix templates and failed as intended:

```
admin/_panes/actions.html -> analyze_capability, comparison_capability
admin/_panes/cosmos.html  -> enable_dai_debug
admin_settings.html       -> enable_document_classification, enable_external_links
```

After the fix:

```
test_admin_settings_pane_variable_scope.py ......... 5/5 passed
test_flask_exception_console_logging.py ............ 4/4 passed
test_admin_settings_template_composition.py ........ passed
test_admin_document_action_capabilities_location.py  passed
test_admin_settings_field_contract.py .............. passed
test_admin_settings_nav_map.py ..................... passed
test_admin_settings_sidebar_card_parity.py ......... passed
test_admin_settings_dependencies.py ................ passed
test_admin_settings_group_shared_regions.py ........ passed
test_admin_settings_modal_placement.py ............. passed
test_admin_settings_walkthrough_targets.py ......... passed
test_admin_settings_sidebar_and_agent_catalog_guard.py ... passed
route_tests/test_route_blueprint_policy_inventory.py ..... passed
route_tests/test_route_policy_test_coverage.py ........... passed
route_tests/test_route_unauthenticated_policy_contract.py  passed
```

These suites fail identically before and after this change and are unrelated to
it: `test_admin_settings_tab_preservation.py` (2/3),
`test_single_app_template_json_bootstrap_safety.py`,
`test_stored_xss_admin_rendering_fix.py` and
`test_admin_settings_safe_int_fallback_fix.py` (which asserts an exact
`VERSION = "0.240.002"` literal).

## Before and after

| Behaviour | Before | After |
|-----------|--------|-------|
| `GET /admin/settings` | 500 on every request | Renders normally |
| Unhandled exception traceback | Application Insights only | Application Insights **and** stderr / `AppServiceConsoleLogs` |
| DAI debug controls with `enable_dai_debug` on | Never rendered | Render as intended |
| Dead `window.enable*` globals | Emitted empty strings | Removed |
