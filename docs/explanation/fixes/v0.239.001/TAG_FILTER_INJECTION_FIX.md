<!-- BEGIN TAG_FILTER_INJECTION_FIX.md BLOCK -->

# Tag Filter Injection Fix

## Issue Description

Tag filter inputs from user query parameters (`?tags=...`) and JSON request bodies were passed through `normalize_tag()` which only trims whitespace and lowercases, without validating the character set. While Cosmos DB queries used parameterized values (preventing direct SQL injection), the `build_tags_filter()` function in `functions_search.py` constructed OData filter strings via string interpolation, creating a potential OData injection vector in Azure AI Search.

## Root Cause

The `validate_tags()` function enforces a strict `^[a-z0-9_-]+$` character whitelist when **saving** tags, but this validation was not applied when **filtering** by tags. The filter path only used `normalize_tag()` (strip + lowercase), allowing arbitrary characters to reach query construction code.

## Version

- **Fixed in**: v0.238.025
- **Affected versions**: Prior versions with tag filtering

## Technical Details

### Files Modified

| File | Change |
|------|--------|
| `application/single_app/functions_documents.py` | Added `sanitize_tags_for_filter()` function |
| `application/single_app/route_backend_documents.py` | Replaced `normalize_tag` with `sanitize_tags_for_filter` in tag filter |
| `application/single_app/route_backend_group_documents.py` | Replaced `normalize_tag` with `sanitize_tags_for_filter` in tag filter |
| `application/single_app/route_backend_public_documents.py` | Replaced `normalize_tag` with `sanitize_tags_for_filter` in tag filter |
| `application/single_app/functions_search.py` | Hardened `build_tags_filter()` to validate tags before OData interpolation |
| `application/single_app/config.py` | Version bump to 0.238.025 |

### Code Changes

**New function `sanitize_tags_for_filter()`**: Accepts either a comma-separated string (from query params) or a list of strings (from JSON bodies). Normalizes each tag, validates against `^[a-z0-9_-]+$`, enforces the 50-character limit, deduplicates, and silently drops invalid entries.

**Route file updates**: The inline `normalize_tag()` + split pattern was replaced with a single call to `sanitize_tags_for_filter()`, which handles splitting, normalizing, and validating internally.

**`build_tags_filter()` hardening**: Replaced the single-quote escaping approach with `sanitize_tags_for_filter()` validation. Since validated tags can only contain `[a-z0-9_-]`, no escaping is necessary and OData injection is impossible.

### Defense-in-Depth Layers

1. **Character whitelist**: `^[a-z0-9_-]+$` prevents any injection-significant characters
2. **Parameterized Cosmos DB queries**: Tag values passed as parameters, not interpolated
3. **Tag normalization**: Lowercase + trim before validation
4. **Length limit**: 50-character maximum per tag

## Testing

- **Functional test**: `functional_tests/test_tag_filter_sanitization.py`
- Covers: valid tags, special character rejection, SQL injection attempts, OData injection attempts, edge cases (empty/None/numeric input), length limits, deduplication

## Impact

- No functional behavior change for valid tag filters (tags stored in the system already pass `^[a-z0-9_-]+$` validation)
- Invalid characters in tag filters are silently dropped rather than passed through to queries
- OData filter injection via `build_tags_filter()` is now prevented by input validation

<!-- END TAG_FILTER_INJECTION_FIX.md BLOCK -->
