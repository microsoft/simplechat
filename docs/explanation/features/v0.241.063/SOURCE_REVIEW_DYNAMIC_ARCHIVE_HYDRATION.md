# Source Review Dynamic Archive Hydration - v0.241.063

Fixed/Implemented in version: **0.241.063**

Related version update: `application/single_app/config.py` was incremented to `0.241.063` for this enhancement.

## Overview

Source Review now waits for rendered archive/list pages to hydrate dated source rows before clicking visible Load More controls. This improves Deep Research coverage for official archives where the Load More button appears before the dynamic card list has finished attaching data and event handlers.

The fix is generic and does not add site-specific scraping rules.

## Technical Specifications

- The rendered fetch path waits for network idle, dated link/list/card evidence, and a short content-stability window before Load More clicks begin.
- Post-click content-change waits use bounded time derived from the existing Source Review timeout setting.
- Existing SSRF, domain policy, redirect, content-size, page budget, depth budget, and Load More click caps remain in force.
- Deep Research ledger coverage continues to report Load More click counts and structured item totals.

## Usage Instructions

Admins do not need to change settings. Existing Source Review JavaScript rendering and Load More settings continue to control whether this path runs and how many Load More interactions are allowed.

For multi-year archives, admins may still need a high enough `source_review_js_load_more_clicks` value to reach the requested date range within the hard cap.

## Testing and Validation

- `functional_tests/test_source_review_security.py` validates that Source Review waits for rendered archive hydration before clicking Load More.
- Existing Source Review traversal, Deep Research ledger, and web-search citation seeding tests cover the downstream evidence flow.

## Known Limitations

Source Review remains a bounded source-inspection workflow, not a crawler. It will not bypass authentication, captchas, robots policy settings, unsafe URL validation, or configured page and click limits.