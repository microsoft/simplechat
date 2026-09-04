# Backup Settings Save Button Fix

**Version:** 0.261.001
**Fixed in version:** **0.261.001**
**Related issue:** [#1353](https://github.com/microsoft/simplechat/issues/1353)

## Issue description

In **Admin Settings → Backup, Migrate & Restore**, toggling **Enable scheduled
backups** did not enable the **Save Settings** button. The button stayed greyed
out and labelled "Saved", leaving an admin with no way to persist the change.

The toggle was the visible symptom of a much wider failure. The entire Backup &
Recovery JavaScript module was inert:

- Saved settings were never loaded from the API, so every control showed its
  static template default rather than the stored configuration.
- The backup inventory and job history lists never populated.
- No button in any of the five tabs was wired up, including Run Full Backup,
  Test Storage, Generate Key, the migration workflow and the Cosmos Editor.

## Root cause

Commit `9bbd7bda` ("Stage D part 6: Backup & Recovery") split the single
`admin/_panes/data-management.html` pane into five sibling panes — `backup`,
`migrate`, `restore`, `cosmos-editor` and `jobs`. The shared save button, status
line and operational warning moved into a `data-admin-group-shared="backup-recovery"`
region outside the panes, because a control living in one pane would disappear
whenever another tab of the group was active.

`admin_data_management.js` was not updated as part of that split. It still
resolved its root container from the id the split removed, and hard-stopped when
it was missing:

```js
// bindElements()
elements.tabPane = elements.dataManagement;   // getElementById("data-management") -> null

// DOMContentLoaded
bindElements();
if (!elements.tabPane) {
    return;                                   // module dies here
}
```

`bindEvents()` therefore never ran. `bindDataManagementChangeTracking()` was
also scoped to `elements.tabPane`, so no `change` or `input` listener was ever
attached. `dataManagementModified` stayed `false`, and
`updateDataManagementSaveButtonState()` kept the button disabled and labelled
"Saved" — exactly the reported behaviour.

Of the 214 element ids `bindElements()` binds, exactly one — `data-management` —
was absent from the composed Admin Settings template.

The same removed id had a second consumer. `admin_settings.js`
`updateSaveButtonState()` hides the *global* Save Settings button while a Backup
& Recovery tab is active, so the group's dedicated button is the only one shown:

```js
const dataManagementPane = document.getElementById('data-management');
const isDataManagementActive = Boolean(dataManagementPane?.classList.contains('active'));
```

That lookup was always `null`, so the global save button appeared on all five
Backup & Recovery tabs alongside the dedicated one — two save buttons, only one
of which applied to backup settings.

## Approach

Re-introducing an `id="data-management"` wrapper around the panes is not
viable. Bootstrap hides inactive panes through `.tab-content > .tab-pane`, a
direct-child selector, so nesting the five panes one level deeper would stop
that rule matching and display every pane at once.

Instead the group membership is declared in the markup and both consumers read
it. Each pane carries `data-admin-group-pane="backup-recovery"`, mirroring the
existing `data-admin-group-shared="backup-recovery"` convention and tying the
panes to the real navigation group id in `admin_settings_nav.py`. This also
gives the functional tests a contract to enforce, so splitting or adding a
Backup & Recovery tab in future cannot silently strand the module again.

## Files modified

| File | Change |
|---|---|
| `application/single_app/templates/admin/_panes/backup.html` | Added `data-admin-group-pane="backup-recovery"` to the tab pane |
| `application/single_app/templates/admin/_panes/migrate.html` | Added `data-admin-group-pane="backup-recovery"` to the tab pane |
| `application/single_app/templates/admin/_panes/restore.html` | Added `data-admin-group-pane="backup-recovery"` to the tab pane |
| `application/single_app/templates/admin/_panes/cosmos-editor.html` | Added `data-admin-group-pane="backup-recovery"` to the tab pane |
| `application/single_app/templates/admin/_panes/jobs.html` | Added `data-admin-group-pane="backup-recovery"` to the tab pane |
| `application/single_app/static/js/admin/admin_data_management.js` | Resolve every declared pane, guard on the collection, bind change tracking across all panes |
| `application/single_app/static/js/admin/admin_settings.js` | Detect the active Backup & Recovery pane through the group attribute |
| `application/single_app/config.py` | `VERSION = "0.261.001"` |
| `functional_tests/test_admin_data_management_pane_binding.py` | New regression test |
| `functional_tests/test_data_management_security_patterns.py` | Updated markup and save button assertions |

## Code changes

`admin_data_management.js` now selects its panes by the declared group:

```js
const dataManagementPaneSelector = "[data-admin-group-pane='backup-recovery']";

function bindElements() {
    // ...
    elements.tabPanes = Array.from(document.querySelectorAll(dataManagementPaneSelector));
}

document.addEventListener("DOMContentLoaded", () => {
    bindElements();
    if (!elements.tabPanes.length) {
        return;
    }
    // ...
});
```

Change tracking iterates every pane, so a control on the Backup tab and a
control on the Migrate tab both arm the save button. The Cosmos Editor opt-out
is preserved, because a direct database editor is not a settings surface:

```js
function bindDataManagementChangeTracking() {
    elements.tabPanes.forEach((pane) => {
        pane.querySelectorAll("input, select, textarea").forEach((element) => {
            if (element.closest("[data-ignore-data-management-change='true']")) {
                return;
            }
            const eventName = element.type === "checkbox" || element.type === "radio" || element.tagName === "SELECT" ? "change" : "input";
            element.addEventListener(eventName, markDataManagementModified);
        });
    });
}
```

`admin_settings.js` hides the global save button using the same contract:

```js
const isBackupRecoveryActive = Boolean(document.querySelector('[data-admin-group-pane="backup-recovery"].active'));
saveButton.classList.toggle('d-none', isBackupRecoveryActive);
```

## Testing

`functional_tests/test_admin_data_management_pane_binding.py` covers:

1. Every element id bound in `bindElements()` resolves to a real element in the
   composed Admin Settings template. This is the general assertion that catches
   this class of bug.
2. Every tab in the `backup-recovery` navigation group has a pane declaring the
   group attribute.
3. No pane outside the group claims it.
4. The module resolves panes from the attribute, guards on the collection, and
   no longer references the removed id.
5. Change tracking iterates every pane and keeps the Cosmos Editor opt-out.
6. Settings controls that `saveDataManagementSettings()` sends, sampled across
   both the Backup and Migrate tabs, sit inside a tracked pane.
7. The global save button defers to the group attribute.
8. `config.py` `VERSION` is at least `0.261.001`.

## Validation

Against the pre-fix state the new test fails 7 of its 8 checks, including the
one that names the reported symptom directly:

```
Test failed: Settings controls that saveDataManagementSettings() sends are outside every
tracked pane, so changing them cannot enable the save button: ['data_management_enabled',
'data_management_retention_value', 'data_management_encryption_enabled']
```

After the fix:

```
Results: 8/8 tests passed
```

The following suites also pass: `test_data_management_security_patterns.py`,
`test_admin_settings_group_shared_regions.py`,
`test_admin_settings_template_composition.py`,
`test_admin_settings_modal_placement.py`,
`test_admin_settings_field_contract.py`, `test_admin_settings_nav_map.py`,
`test_admin_settings_sidebar_card_parity.py`,
`test_admin_settings_pane_variable_scope.py`,
`test_admin_settings_walkthrough_targets.py` and
`test_admin_settings_dependencies.py`.

## Before and after

| Behaviour | Before | After |
|---|---|---|
| Toggling **Enable scheduled backups** | Save button stays disabled, reads "Saved" | Save button enables, reads "Save Settings" |
| Stored backup settings on page load | Never fetched; controls show template defaults | Loaded from `/api/admin/data-management/settings` |
| Backup inventory and job history | Never populate | Populate on load |
| Buttons across the five tabs | Unbound and inert | Wired up |
| Save buttons shown on a Backup & Recovery tab | Two, the global one being inapplicable | One, the group's own |

## Notes

- No settings key, admin tab, action plugin or chat control was added or
  renamed, so `docs/_data/app_surface.yml` does not need regenerating.
- The restore and Cosmos Editor dialogs were moved to document level by the same
  commit that caused this bug. Scoping change tracking to the panes means a
  restore confirmation phrase is no longer treated as a settings edit, which is
  an improvement over the pre-split behaviour.
- `support_menu_config.py` still links to `#data-management`. That keeps working
  through the `LEGACY_TAB_REDIRECTS` map in `admin_sidebar_nav.js`
  (`data-management` → `backup`), which exists for exactly this purpose, so it
  was left unchanged.

## Known related issues, not addressed here

- `functional_tests/test_admin_settings_tab_preservation.py` fails on
  `Missing required HTML elements: ['class="tab-pane fade']`. It reads the raw
  `admin_settings.html` instead of the composed template, so it broke when the
  panes moved into includes. Confirmed pre-existing: it fails identically with
  the changes above stashed.
- Around twenty functional tests assert the exact `config.py` version literal,
  for example `assert_contains(CONFIG_FILE, 'VERSION = "0.239.129"')`. This is
  the pattern the versioning instructions call out, and
  `test_support.versioning.assert_app_version_at_least` exists to replace it.
  They were already failing before this change: the highest literal in the suite
  is `0.260.023` while `config.py` was `0.260.028`. The bump to `0.261.001`
  breaks none of them further, since no test asserts either version, but
  converting them to the shared helper is worthwhile follow-up work.
- A broader probe found roughly 39 `getElementById` literals in
  `admin_settings.js` with no matching id in the composed Admin Settings
  template, for example `workspaces`, `agents-tab` and
  `enable_group_creation_setting`. Some appear to be stale leftovers from the
  same information-architecture rework; others resolve against templates outside
  Admin Settings. Auditing them is separate work.
