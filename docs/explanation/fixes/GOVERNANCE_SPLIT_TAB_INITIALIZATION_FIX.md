# Governance Split Tab Initialization Fix

**Version:** 0.261.002
**Fixed in version:** **0.261.002**
**Related issue:** [#1362](https://github.com/microsoft/simplechat/issues/1362)

## Issue description

In **Admin Settings -> Governance -> Policies**, the **New Policy** button in
the Delegated Item Policies card did not open the delegated item policy editor
modal.

## Root cause

The governance admin JavaScript still used the retired aggregate
`id="governance"` pane as its initialization guard:

```js
if (!document.getElementById('governance')) {
    return;
}
```

The current Admin Settings navigation renders Governance as three split tabs:

- `feature-governance`
- `governance-policies`
- `mcp-governance`

Because the old pane no longer exists, `admin_governance.js` returned before
`wireGovernanceHandlers()` could attach the **New Policy** click handler.

## Approach

The fix makes governance initialization detect the current split governance
panes and updates governance quick links to target the correct tab:

- Feature governance links open `#feature-governance`.
- Delegated resource quick-create links open `#governance-policies`.
- Inbound MCP quick-create links open `#mcp-governance`.

## Files modified

| File | Change |
|---|---|
| `application/single_app/static/js/admin/admin_governance.js` | Detect split governance panes and route quick links to the correct tab ids |
| `application/single_app/config.py` | Bumped `VERSION` to `0.261.002` |
| `functional_tests/test_governance_route_and_wiring_coverage.py` | Added regression markers for split-tab initialization and stale `#governance` references |
| `ui_tests/test_admin_governance_tab.py` | Updated the UI workflow to navigate the split governance tabs before using **New Policy** |
| `docs/explanation/release_notes.md` | Added a bug-fix release note |

## Validation

### Test results

- `node --check application\single_app\static\js\admin\admin_governance.js`
- `python -m py_compile application\single_app\config.py functional_tests\test_governance_route_and_wiring_coverage.py ui_tests\test_admin_governance_tab.py`
- `python functional_tests\test_governance_route_and_wiring_coverage.py`
- `python scripts\check_xss_sinks.py --full-file application\single_app\static\js\admin\admin_governance.js`
- `git --no-pager diff --check`

The targeted Playwright UI test was invoked with
`python -m pytest ui_tests\test_admin_governance_tab.py -q`, but skipped locally
because the local authenticated Playwright storage state was not configured.

### Before / after

- Before: the governance module exited during initialization and never wired the
  delegated item **New Policy** button.
- After: the module initializes when any split governance pane is present, and
  the **New Policy** button opens the delegated item policy editor modal.

### User experience improvements

- Admins can create delegated item policies directly from the Policies tab.
- Governance quick-create links from related admin surfaces land on the intended
  split governance tab.
