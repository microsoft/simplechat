# Terms of Use revision in Activity Logs

Fixed/Implemented in version: **0.261.051**
Initial hash-display implementation: **0.261.050** (superseded before release).

Tracking: [#1616](https://github.com/microsoft/simplechat/issues/1616).

## Issue and root cause

Terms of Use acceptance and decline records already persist `terms_hash`, the
SHA-256 identifier of the title, normalized message, and recurrence. Both
post-authentication acceptance and pre-authentication acceptance promoted after
sign-in record this identifier.

The Control Center Activity Logs renderer and CSV formatter had no Terms-specific
cases, so the Details column and CSV returned `N/A`. The stored revision was
visible only through raw JSON. Showing the hash fixed that visibility gap but did
not meet the requirement for executive-readable labels such as `v1` and `v2`.

## Changes

- [Activity renderer](../../../application/single_app/static/js/control-center.js):
  show the recorded Terms version as `v1`, `v2`, etc. in row details, the detail modal, and
  the client CSV-details helper, alongside frequency and source.
- [CSV formatter](../../../application/single_app/route_backend_control_center.py):
  include the recorded revision in the existing server-side CSV export.
- [Control Center template](../../../application/single_app/templates/control_center.html):
  add separate acceptance and decline activity filters.
- [Pure configuration helpers](../../../application/single_app/functions_terms_of_use_config.py):
  preserve the existing normalized hash and allocate sequential revision metadata.
  Keeping these helpers independent of Flask, settings, logging, and Azure clients
  avoids a new bootstrap import cycle.
- [Settings owner](../../../application/single_app/functions_settings.py):
  persist the baseline and increment within the existing OCC write transaction.
  Incoming settings cannot supply or overwrite the server-owned counter.
- [Acceptance helpers](../../../application/single_app/functions_terms_of_use.py)
  and [audit writers](../../../application/single_app/functions_activity_logging.py):
  carry the number through both authentication flows and into accepted/declined
  records, keeping `terms_hash` for technical verification.
- [Admin notices pane](../../../application/single_app/templates/admin/_panes/notices.html):
  display the current saved version as a read-only label.
- [Application version](../../../application/single_app/config.py): `0.261.051`.

The renderer reads the historical event's `terms_version`, not the current Terms
configuration. Events without a number display **Legacy**; no historical revision
is invented. Hashes remain in raw JSON rather than dominating the normal UI or
CSV details. HTML-rendered values use the existing escaping helpers.

Current non-empty terms receive a persisted `v1` baseline on upgrade. Changed
normalized title, message, or frequency advances the number, including disabled
edits and later restoration of earlier text. Unchanged saves, toggles, redirects,
and button labels do not advance it. Blank new installations wait for the first
non-empty message. Failed or conflicting writes do not allocate a number;
read-only outage fallback does not expose an uncommitted baseline.

The additional metadata does not change hash-based acceptance, authentication
policy, or recurrence rules. It does not track application versions or retain
historical full Terms text. Old events and pre-auth acceptances lacking a number
are not rewritten. Numbering is local to the installation, not global across
independent environments.

## Validation

- [Terms functional tests](../../../functional_tests/test_terms_of_use.py):
  execute the actual acceptance helpers and log writers with in-memory I/O;
  verify historical numbers and hashes for changed text across all recurrence modes,
  before and after authentication, declined terms, and CSV output.
- [Activity Logs browser tests](../../../ui_tests/test_terms_of_use_activity_logs.py):
  exercise the real JavaScript module with offline APIs, verifying row/modal
  visibility without JSON expansion, filtering, CSV download, legacy events,
  and HTML escaping.
- [Settings-store tests](../../../functional_tests/test_app_settings_store_consistency.py):
  baseline migration, first save, disabled edits, normalization, no-op saves,
  spoofed metadata, concurrent updates/retries, rejected stale forms and outages.
- [Cold-import tests](../../../functional_tests/test_app_settings_import_boundaries.py):
  real-module imports with network and reverse bootstrap imports blocked.
- The original CSV formatter returned `N/A`; numbered events now export readable
  details such as `Terms version: v2, Frequency: once, Source: post_auth`.

## Related investigation: disabled settings (#1615)

[#1615](https://github.com/microsoft/simplechat/issues/1615) reports Terms of Use
edits that do not save while the feature is disabled. The clarified reproduction
starts with the toggle **already disabled**, then edits and saves the settings;
it is not a save that first turns the feature off. The customer confirmed that
the save reports success, but the automatic reload loses the title, message, and
frequency edits. Enabling the toggle allows the same edits to save.
This was not reproduced in the assessed V1 code. The composed admin form includes
the editable fields when
disabled; the actual route's Terms parsing and saved-field mapping retain them.
[Settings-store tests](../../../functional_tests/test_app_settings_store_consistency.py)
cover disabling existing terms and editing already-disabled terms, with and
without shared Redis caching, then reading through another worker.

No speculative production change was made for #1615. The affected customer
deployment is **0.261.027**. The disabled-field POST parsing and underlying
settings store match the branch. The separate #1616 changes add revision metadata;
they are not a claimed fix for lost edits.

An authorized live test on **beta 0.261.048** submitted an edited Terms message
while the feature remained disabled. The save returned its normal redirect and
success notification; the edited message remained after an additional reload.
The original message was restored with another save, followed by a reload that
verified every original Terms field and the disabled toggle. Temporary browser
probe state was removed. Dev's React V2 deployment was not modified.

This beta result does not disprove the customer report. The customer's submitted
Terms fields, persisted settings, and subsequent readback still need comparison
to identify the failing stage. Do not treat #1615 as resolved by this fix.

Local revalidation on 2026-10-04 passed 10 focused checks across the Terms helper,
settings-store, and Terms UI suites. These cover disabled and enabled POST-field
parsing, saves starting with disabled terms with and without shared Redis caching,
cross-worker readback, disabled revision changes, and browser editability while
disabled. Storage uses in-memory service doubles and route parsing uses the actual
Terms statements extracted from the route; this is not a new end-to-end
reproduction against the affected customer's deployment.

A separate local Chromium probe rendered the composed V1 admin form with Terms
already disabled and inspected native `FormData` after editing the title, message,
and frequency. All six Terms configuration fields were included with their edited
values whether the toggle was off or on; only the unchecked checkbox was omitted,
as expected. This probe did not execute the full admin JavaScript or submit to a
live backend, so it does not rule out deployment-specific browser or write/read
behavior. The affected deployment's actual POST must be checked before attributing
the failure to omitted fields, persistence, or readback.

### Release-to-branch commit review

The published release tag is `v0.261.027` (`f5bcae7a`); branch HEAD `87c0891f`
contains 43 additional commits, including merge commits. Pending local changes
are separate from that committed range.

| Commit | Finding | Relationship to #1615 |
| --- | --- | --- |
| [bf2f13f5](https://github.com/microsoft/simplechat/commit/bf2f13f5) | Cross-worker settings consistency and Redis Explorer fix | Already contained in the release; not a later fix explaining the difference. |
| [b9a063ab](https://github.com/microsoft/simplechat/commit/b9a063ab) | Post-configuration replaces a direct Cosmos snapshot upsert with an OCC delta merge, Redis publication, and verified readback | Credible indirect candidate if deployment post-configuration overlapped admin edits or bypassed the shared cache. Not proof of the customer's incident or an explanation specific to the Terms toggle. |
| [bdb668af](https://github.com/microsoft/simplechat/commit/bdb668af) | Cosmos replacement-write corrections for user settings/actions | User settings differ from the admin `app_settings` Terms configuration; does not directly fix lost Terms message edits. |
| [dd430b7a](https://github.com/microsoft/simplechat/commit/dd430b7a), [87c0891f](https://github.com/microsoft/simplechat/commit/87c0891f) | Model validation, capacity and routing changes | No Terms message persistence fix identified. |

The existing deployment regression
`test_save_publishes_shared_cache_and_preserves_concurrent_edit` passes. The
post-configuration fix is in the deployment scripts, not just the web image:
updating an image alone does not update a customer's old deployment runner.
Confirm their deployment method and whether post-configuration ran during the
failed save before attributing #1615 to this candidate. Do not rerun
post-configuration against customer settings merely to test this hypothesis.
