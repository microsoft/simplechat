# Admin Settings Pane Variable Scope Fix

Admin Settings raised `jinja2.exceptions.UndefinedError: 'analyze_capability' is
undefined` and returned a 500 for every visit.

Fixed in version: **0.260.019**

## Issue

Loading `/admin/settings` failed outright:

```
File "templates/admin/_panes/actions.html", line 17, in top-level template code
  <input ... name="document_action_analyze_enabled"
         {% if analyze_capability.enabled %}checked{% endif %}>
jinja2.exceptions.UndefinedError: 'analyze_capability' is undefined
```

## Root cause

**Jinja `{% set %}` scope does not cross an `{% include %}` boundary.**

While Admin Settings was a single 14,000-line template this never mattered: a
variable derived near the top of the file was visible everywhere below it. The
information architecture rework split that template into 44 per-tab partials,
and a variable derived in one partial is simply not visible in another.

Three variables were left behind when their consuming card moved to a new tab:

| Variable | Declared in | Used in | Failure |
|---|---|---|---|
| `analyze_capability` | `agents.html` | `actions.html` | 500 error |
| `comparison_capability` | `agents.html` | `actions.html` | 500 error |
| `enable_dai_debug` | `redis-caching.html` | `cosmos.html` | **silent** |

### Two very different failure modes

The distinction matters more than the fix:

- **Attribute access** on a missing name (`analyze_capability.enabled`) raises
  `UndefinedError` and takes the page down. Loud, and found immediately.
- **A boolean test** on a missing name (`{% if enable_dai_debug %}`) silently
  evaluates false, because Jinja's default `Undefined` is falsy. Nothing errors.
  The controls it guards simply never render.

The `enable_dai_debug` case was therefore invisible: the Cosmos tab's debug
controls and shadow-validation diagnostics would never have appeared, no matter
how the setting was configured, and nothing would have reported a problem. It
was found only by auditing for the same pattern that caused the crash.

## Why existing tests did not catch it

Every Admin Settings test inspected the template **as text** — field names, card
ids, tag balance, navigation parity, modal placement. All of them passed.

None of them **executed** the template. A template can satisfy every static
check and still raise the moment Flask renders it.

## Files modified

| File | Change |
|---|---|
| `templates/admin/_panes/actions.html` | Declares `analyze_capability` and `comparison_capability` |
| `templates/admin/_panes/agents.html` | Removed the two now-orphaned declarations |
| `templates/admin/_panes/cosmos.html` | Declares `enable_dai_debug` |
| `templates/admin/_panes/redis-caching.html` | Removed the now-orphaned declaration |

Each declaration is a pure derivation from `settings`, which the route supplies
to every template, so moving it to the consuming pane is safe and self-contained.

## Testing

Two new test files, both verified against a deliberately planted version of the
real bug so they are known to fail when they should.

### `test_admin_settings_renders.py`

Renders the entire page through Jinja with the same undefined handling Flask
uses, so an `UndefinedError` surfaces in the test suite rather than in a browser.
This is the test that would have caught the bug immediately.

It also asserts every navigation tab renders a pane, and that exactly one pane is
active and it is the landing tab.

The render context is derived from the route's own `render_template` call and the
app context processors, so it cannot drift as those change.

### `test_admin_settings_pane_variable_scope.py`

Static scope analysis using `jinja2.meta.find_undeclared_variables`. For every
pane it reports the variables needed from outside, then fails if any of them is
declared only in a **sibling pane**:

```
'analyze_capability' is used in 'actions' but only declared in ['agents']
```

This catches the silent variant that a render cannot, because a boolean test on
an undefined name renders perfectly happily.

Variables declared inside a `{% for %}` loop are correctly treated as local.

## Validation

| Check | Result |
|---|---|
| Page renders | 1,383,741 characters, no error |
| Navigation tabs rendering a pane | 44 / 44 |
| Active panes | exactly 1, and it is the landing tab |
| Cross-pane variable leaks | none |
| Field names vs `Development` | 452 → 452, zero lost, zero added |
| Regression set (75 files) | 32 pre-existing failures, unchanged |

## Before and after

**Before**: every visit to Admin Settings returned a 500, and the Cosmos debug
controls were silently unreachable.

**After**: the page loads, the Cosmos debug controls honour their setting, and
both failure modes are covered by tests that fail when the bug is reintroduced.
