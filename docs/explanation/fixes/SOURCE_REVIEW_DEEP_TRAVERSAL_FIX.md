# Source Review Deep Traversal Fix

Fixed in version: **0.241.042**

Further refined in version: **0.241.044**

Further refined in version: **0.241.045**

Further refined in version: **0.241.046**

## Issue Description

Source Review improved answers by reviewing source pages, but Deep Source Review could over-invest remaining page budget in child links from the first reviewed source page. For multi-source research requests, that meant one official archive could contribute several child pages while another archive received less follow-up exploration.

## Root Cause Analysis

The initial traversal queue allowed child links to be queued while seed source pages were still waiting. This made child selection depend too heavily on seed order instead of first reviewing all initial source/archive pages and then spending leftover budget on the best child links across those pages.

## Technical Details

### Files Modified

* `application/single_app/functions_source_review.py`
* `application/single_app/config.py`
* `functional_tests/test_source_review_deep_traversal.py`
* `functional_tests/test_source_review_security.py`
* `docs/explanation/features/v0.241.041/SOURCE_REVIEW.md`

### Code Changes Summary

* Source Review now reviews all seed URLs within the page budget before pulling child-link candidates into the active fetch queue.
* Deep traversal now ranks child candidates across seed pages, so later seed pages can still contribute the best follow-up links.
* Archive-style requests now favor generic release/detail link patterns and penalize common non-evidence navigation paths such as about, careers, awards, privacy, and annual report pages.
* The v0.241.044 refinement scores extracted links before enforcing the per-page link inventory limit, so press-release/detail links are not dropped just because a page emits navigation links first.
* The v0.241.045 refinement passes all Foundry web-search URL citations into Source Review, adds a seed-page budget, and allows bounded second-hop traversal for official archive -> section/year -> detail-page flows.
* The v0.241.046 refinement adds bounded Load More handling to the optional rendered-page path so interactive official archives can expose more dated source links before evidence extraction.
* Source Review audit logs now include Deep Source Review usage, seed and child page counts, planner attempted/used state, planner candidate count, and selected planner URLs for easier diagnosis.
* Malformed link entries are ignored defensively, and unexpected fetch/extraction failures now include traceback logging for diagnosis.
* App version was updated in `application/single_app/config.py` to `0.241.042`.
* App version was updated in `application/single_app/config.py` to `0.241.044` for the link-prioritization and audit refinement.
* App version was updated in `application/single_app/config.py` to `0.241.045` for the citation seeding and second-hop traversal refinement.
* App version was updated in `application/single_app/config.py` to `0.241.046` for the rendered Load More refinement.

### Testing Approach

* Added `functional_tests/test_source_review_deep_traversal.py` to validate source-archive child-link prioritization and cross-seed child selection without company-specific rules.
* Added v0.241.044 regression coverage for relevant links surviving noisy navigation and for generic same-domain navigation being rejected for archive-style requests.
* Added v0.241.045 regression coverage for raw Foundry citations becoming Source Review seeds and for bounded second-hop traversal with reserved seed budget.
* Added v0.241.046 regression coverage for Load More control detection and click-cap clamping.
* Updated `functional_tests/test_source_review_security.py` to the current config version.

## Validation

The targeted Source Review tests validate that Deep Source Review can identify a relevant release/detail page over generic navigation links and choose high-value child links from later seed archives.

## Impact Analysis

Multi-source web research should now make better use of Deep Source Review. The behavior remains bounded by the configured page budget, hard safety ceilings, SSRF controls, and prompt-injection isolation.