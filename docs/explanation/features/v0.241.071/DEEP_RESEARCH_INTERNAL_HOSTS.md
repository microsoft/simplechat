# Deep Research Internal Network Hostnames

## Overview
Deep Research now includes an admin-controlled option to review approved internal network hostnames. By default, hostnames that resolve to private/internal IP addresses remain blocked. Admins can enable `Allow internal network hostnames` when Deep Research should inspect internal sites by DNS name.

Implemented in version: **0.241.071**

## Dependencies
- Deep Research source validation in `functions_source_review.py`
- Admin Settings Deep Research controls in `admin_settings.html`
- Admin Settings save handling in `route_frontend_admin_settings.py`
- Optional domain allow/block policy editors

## Technical Specifications
- New setting: `source_review_allow_internal_hosts`
- Default: `False`
- When disabled, DNS hostnames resolving to private/internal addresses are denied before fetch.
- When enabled, DNS hostnames resolving to private/internal addresses are allowed if they also pass domain allow/block rules.
- Literal IP URL hosts remain blocked, including direct private IP, loopback, and metadata-style link-local targets.
- Localhost, known metadata hostnames, link-local addresses, multicast, reserved, and unspecified addresses remain blocked.
- Redirect targets are validated with the same policy before fetch.

## Usage Instructions
1. Open Admin Settings.
2. Go to Search & Extract.
3. Enable Deep Research.
4. Turn on `Allow internal network hostnames` only for environments where the app host should fetch internal DNS names.
5. Use `Allowed Domains` to limit internal access to approved domains or suffixes when possible.
6. Save settings and test with an internal DNS URL, not a literal IP address URL.

## Testing and Validation
- `functional_tests/test_source_review_security.py` validates default denial, opt-in allowance for internal DNS names, and continued blocking for literal IP URL targets.
- `ui_tests/test_admin_source_review_settings.py` validates the Admin Settings switch and setup guide text.

## Known Limitations
- Deep Research validates DNS resolution before fetch, but the HTTP client still resolves the hostname during the request. Use domain allowlists and stable internal DNS records to reduce DNS rebinding risk.
- The feature does not allow direct IP URL targets. Use DNS names for approved internal sites.
