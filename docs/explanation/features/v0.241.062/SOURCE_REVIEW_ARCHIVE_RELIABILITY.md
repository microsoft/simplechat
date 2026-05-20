# Source Review Archive Reliability - v0.241.062

Fixed/Implemented in version: **0.241.062**

Related version update: `application/single_app/config.py` was incremented to `0.241.062` for this enhancement.

## Overview

Source Review now preserves structured archive and listing rows from generic page markup, improving reliability for official news, press-release, investor-relations, RSS, Atom, sitemap, and search-result pages that expose many dated cards behind repeated Load More interactions.

Source Review remains the internal bounded source-inspection layer used by Deep Research. This enhancement does not add site-specific scraping rules or unbounded crawling.

## Dependencies

- `aiohttp` for bounded HTTP retrieval.
- `beautifulsoup4` for HTML/XML parsing.
- Optional Playwright browser support when admins enable JavaScript rendering.

## Technical Specifications

### Architecture

- HTML extraction now emits `structured_items` for repeated archive/list/result patterns.
- Each structured item preserves a title, URL, nearby text, same-domain signal, and normalized published date when available.
- XML feed extraction emits the same structured item shape for RSS, Atom, and sitemap entries.
- Deep Source Review can use structured items as bounded child-page candidates, so generic "Learn more" links still retain their surrounding card title and date.
- Rendered Load More handling first targets controls by accessible role/text, then falls back to a wider bounded scan across interactive controls.
- Rendered pages now wait for observable content changes after each click before deciding whether pagination stalled.

### Configuration

- Existing Source Review and Deep Research settings continue to apply.
- Structured items are capped by the hard internal `max_structured_items_per_page` limit.
- Load More clicks remain capped by `source_review_js_load_more_clicks` and the hard maximum.

### File Structure

- `application/single_app/functions_source_review.py`: extraction, evidence packaging, traversal candidates, rendered Load More behavior, coverage metadata.
- `functional_tests/test_source_review_security.py`: structured archive-card extraction regression coverage.
- `functional_tests/test_source_review_deep_traversal.py`: structured item traversal candidate regression coverage.

## Usage Instructions

Admins do not need a new setting. When Source Review is enabled, and JavaScript rendering is enabled for dynamic pages, Deep Research can inspect official listing pages and preserve dated rows from repeated card/list markup more consistently.

## Testing and Validation

- Functional tests validate generic card extraction with non-descriptive "Learn more" links.
- Functional tests validate that structured archive items can feed bounded child traversal.
- Existing SSRF, URL validation, page budget, depth budget, redirect, content-size, and prompt-injection isolation controls remain in place.

## Known Limitations

Source Review is still intentionally bounded. It does not bypass authentication, captchas, robots policy settings, domain policy, page budgets, or unsafe URL validation. Pages that require opaque client APIs without visible rendered output may still report partial coverage.