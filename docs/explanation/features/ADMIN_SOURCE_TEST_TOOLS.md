# Admin Source Test Tools

Implemented in version: **0.241.094**

## Overview

Admin Source Test Tools add lightweight verification controls to Admin Settings for governed external source features:

- Web Search Foundry Agent smoke testing from the Search & Extract settings tab.
- URL Access allowed and blocked domain policy testing from the same tab.

The application version was updated in `application/single_app/config.py` to `0.241.094` for this feature.

## Technical Specifications

### Architecture

- The Web Search modal calls the existing `/api/admin/settings/test_connection` route with `test_type: web_search` and the current unsaved Foundry form values.
- The URL Policy modal calls the same admin-only route with `test_type: url_access_policy` and the current unsaved URL Access domain rules.
- URL policy evaluation uses Source Review URL normalization and safety validation without fetching remote content.
- Browser-facing result rendering uses static Bootstrap modal shells and JavaScript DOM APIs with `textContent` for returned messages, details, and guidance.

### API Endpoints

- `POST /api/admin/settings/test_connection`
  - `test_type: web_search` runs the configured Foundry agent against a short admin test prompt.
  - `test_type: url_access_policy` evaluates one URL against URL Access policy and SSRF safety validation.

### Configuration Options

- Web Search: `enable_web_search`, `web_search_consent_accepted`, and `web_search_agent.other_settings.azure_ai_foundry` fields.
- URL Access: `enable_url_access`, `url_access_allowed_domains`, `url_access_blocked_domains`, and `source_review_allow_internal_hosts`.

### File Structure

- `application/single_app/functions_url_access_policy_test.py`
- `application/single_app/functions_web_search_test.py`
- `application/single_app/functions_source_review.py`
- `application/single_app/route_backend_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `functional_tests/test_url_access_admin_policy_test.py`
- `functional_tests/test_web_search_admin_connection_test.py`
- `ui_tests/test_admin_source_review_settings.py`

## Usage Instructions

1. Open Admin Settings and select Search & Extract.
2. Enable Web Search and configure the Azure AI Foundry agent settings.
3. Select **Test Web Search** to open the smoke-test modal and run the configured agent.
4. Configure URL Access allowed or blocked domains.
5. Select **Test URL Policy**, enter a URL, and run the policy test to see whether URL Access would allow or block it.

## Testing and Validation

- Functional tests validate Web Search custom prompts and URL Access policy outcomes.
- UI coverage validates modal visibility, test result rendering, and allowed/blocked URL policy states.
- The URL policy test does not fetch remote content; it validates normalization, domain policy, and server-side URL safety gates.