# Source Review Dynamic Grid Archive Fix

Fixed in version: **0.241.065**

## Issue Description

Source Review could review dynamic archive pages such as `https://www.jpmorganchase.com/ir/news`, but the static HTML extraction saw only the shell/navigation content. In the JPMorgan case this produced only a couple of structured items even though the rendered archive exposes many dated press-release rows and a Load More control.

The same run also showed a skipped source with a `NoneType` date-extraction error, allowing one malformed archive candidate to skip an otherwise usable page.

## Root Cause Analysis

Some AEM dynamic-grid archive pages publish their repeated card rows through a same-origin JSON service advertised by `data-dg-action` attributes. Source Review detected the Load More control but did not consume the JSON endpoint when JavaScript rendering was disabled, so it undercounted client-rendered archives.

Date extraction also assumed every structured candidate had a BeautifulSoup-like container, which was not true for all archive/link candidates.

## Technical Details

### Files Modified

- `application/single_app/functions_source_review.py`
- `functional_tests/test_source_review_security.py`
- `functional_tests/test_document_analysis_lossless_artifacts.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added generic AEM dynamic-grid detection for HTML pages with `data-dg-action` metadata.
- Fetches the advertised same-origin JSON endpoint with existing Source Review URL validation before any request.
- Converts dynamic-grid JSON rows into Source Review `structured_items` with normalized title, URL, date, nearby text, score, and source type.
- Merges dynamic-grid rows into the existing link inventory so Deep Source Review can follow those dated release URLs.
- Added guards so missing date containers return an empty date instead of failing the whole page.
- Updated the application version in `config.py` to `0.241.065`.

### Testing Approach

- Added a Source Review functional regression using a fake dynamic-grid JSON endpoint to verify dated client-rendered archive rows are folded into `structured_items`.
- Added a regression for missing date containers.
- Re-ran Source Review extraction/security tests.

## Validation

### Test Results

- `python -m py_compile application/single_app/functions_source_review.py functional_tests/test_source_review_security.py`
- `python functional_tests/test_source_review_security.py` -> 11/11 tests passed

### Before

Source Review on JPMorgan's IR news archive saw the page title/navigation and detected Load More, but extracted only a very small number of non-release structured items when JavaScript rendering was unavailable or disabled.

### After

Source Review can use the page's own dynamic-grid JSON service to extract the archive rows directly, including dated press-release titles and links. This gives Deep Research enough structured evidence to answer from the official JPMorgan archive instead of relying primarily on third-party search results.

## Related Version Update

- `application/single_app/config.py` was updated to version `0.241.065`.
