# V2 Admin Tabular Preflight Switch Fix

## Issue

V2 Admin Settings showed a switch called **Tabular search shared preflight**
(`enable_tabular_search_shared_preflight`) under Workspaces › Files & Sharing ›
Shared Conversation File Approvals. It had no description and nothing to do with file
approvals. Changing it had no lasting effect: a switch turned off came back on after the
next page load.

Two related flags, `enable_tabular_analyze_durable_preflight` and
`enable_tabular_hierarchical_analysis`, had the same problem. They appeared as raw keys
under **Other capabilities**.

## What these flags do

All three control how SimpleChat handles an exhaustive request against a CSV or XLSX
file, such as "for every row, answer these questions" or "give me a CSV with one line per
row".

| Flag | Effect while on |
| --- | --- |
| `enable_tabular_search_shared_preflight` | A regular chat message (Search) goes through the shared tabular planner. The planner can run the request as a durable background job over every row. |
| `enable_tabular_analyze_durable_preflight` | The Analyze path does the same for a request against a single tabular file. |
| `enable_tabular_hierarchical_analysis` | The durable job accepts exhaustive per-row and per-line requests, including ones that ask for written answers rather than a file export. |

With any of them off, those requests fall back to the older foreground path. That path
answers the first rows that fit in one model turn and then truncates, or keeps retrying
without finishing. This was the customer-reported failure the tabular parity work fixed.
The only reason to turn them off is an incident rollback, which the environment variable
below handles, so they are always on.

## Root cause

The V2 admin page draws a switch for every `enable_*` boolean in the settings document
that `admin_settings_fields.py` does not declare. It places each one under the navigation
section whose id shares the most words with the key (`buildCapabilityIndex` in
`AdminSettingsPage.tsx`). The only word `enable_tabular_search_shared_preflight` shares
with any section id is "shared", in `shared-conversation-file-approvals-section`. That is
where it was drawn.

None of the three flags can be edited:

- `normalize_tabular_parity_durable_preflight_defaults()` in `functions_settings.py` sets
  each one back to `True` on every `get_settings()` read and saves the correction. It
  exists because older deployments stored these flags as `False` before their defaults
  were raised. See [Tabular Parity Stale Settings Migration Fix](TABULAR_PARITY_STALE_SETTINGS_MIGRATION_FIX.md).
- `_apply_tabular_parity_env_kill_switch()` forces them to `False` while the
  `SIMPLECHAT_DISABLE_TABULAR_PARITY_DURABLE_PREFLIGHT` environment variable is set. This is
  the supported emergency rollback.

A switch therefore reverted in either direction. The classic admin page has never had a
control for these flags, and the rollout documentation says there is intentionally no
admin toggle.

## Fixed in version: **0.261.261**

The application version is maintained in `application/single_app/config.py`.

## Technical details

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/admin_settings_fields.py` | Added the three flags to `SUPPRESSED_CAPABILITY_KEYS`, each with the reason it is not an administrator setting. |
| `functional_tests/test_v2_admin_capability_placement.py` | Expects the three suppressions, adds a check that covers every forced flag, and adds Workspaces to the groups that must receive no guessed switches. |
| `application/single_app/config.py` | Version bump. |

### Code changes

- The settings GET already sends `SUPPRESSED_CAPABILITY_KEYS` as `suppressed_capabilities`,
  and `buildCapabilityIndex` skips those keys. Listing the three flags removes their switches
  and needs no frontend change.
- Defaults and runtime behavior are unchanged. The flags stay `True`, and the environment
  variable still turns all of them off.

### Impact

- Shared Conversation File Approvals now shows only its own setting.
- **Other capabilities** no longer lists the two sibling flags.
- Administrators can no longer flip a switch that appears to save but has no lasting effect.

## Validation

`functional_tests/test_v2_admin_capability_placement.py` passes 8/8. To confirm the guards
catch the regression, the suppression for `enable_tabular_search_shared_preflight` was
removed in memory, and three checks then failed:

- `test_described_groups_receive_no_guessed_capabilities` reported the key filed under
  Workspaces › Files & Sharing › `shared-conversation-file-approvals-section`. Workspaces
  is now one of the groups that must receive no guessed switches.
- `test_forced_tabular_parity_flags_are_suppressed` reads
  `TABULAR_PARITY_DURABLE_PREFLIGHT_ACTIVE_DEFAULTS` from `functions_settings.py` and
  requires every `enable_*` key in it to be suppressed with a reason. A flag added to that
  map later is covered without editing the test.
- `test_non_editable_capabilities_are_suppressed_not_declared` reported the missing
  suppression.

Before: an unlabelled switch under Shared Conversation File Approvals and two raw keys
under Other capabilities, all of which reverted after saving. After: no switch for any of
the three, and all three stay on.

Related: [V2 Admin Chat Settings](../features/V2_ADMIN_CHAT_SETTINGS.md),
[Tabular Analyze Search Parity Rollout](../features/TABULAR_ANALYZE_SEARCH_PARITY_ROLLOUT.md).
