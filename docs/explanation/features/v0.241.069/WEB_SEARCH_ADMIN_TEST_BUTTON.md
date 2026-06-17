# Web Search Admin Test Button

Version implemented: **0.241.069**

Fixed/Implemented in version: **0.241.069**

## Overview

Admins can now test Web Search from Admin Settings before relying on it in chat. The test uses the current unsaved Azure AI Foundry agent fields, runs a small Grounding with Bing Search prompt, and returns clear success, warning, or failure feedback in the browser.

## Dependencies

- `application/single_app/config.py` version `0.241.069`
- Azure AI Foundry project endpoint and agent ID
- Managed identity or service principal access to the Foundry project. Commercial Foundry uses the renamed `Foundry User` role for minimum project access; Azure Government and custom clouds may still show the equivalent `Azure AI User` role name.
- Foundry agent with Grounding with Bing Search configured

## Technical Specifications

- The existing `/api/admin/settings/test_connection` admin endpoint now handles `test_type: "web_search"`.
- The backend normalizes the Foundry settings from the current form payload instead of requiring settings to be saved first.
- The test validates required endpoint, API version, agent ID, and authentication fields before making an outbound Foundry call.
- Runtime errors are categorized into configuration, authentication, permission, not found, quota/rate limit, network, tool configuration, or unexpected failures.
- Browser-facing diagnostics redact secret, password, key, and token values before returning error text.
- The Admin Settings UI renders feedback with DOM APIs and `textContent` so response text is not treated as HTML.

## Usage Instructions

1. Open Admin Settings and select the Search & Extract tab.
2. Enable Web Search and accept the Grounding with Bing Search notice.
3. Enter the Foundry project endpoint, API version, agent ID, and authentication fields.
4. Select **Test Web Search**.
5. Review the result panel for response preview, citation count, and recommended next steps.

## Testing and Validation

- `functional_tests/test_web_search_admin_connection_test.py` validates settings normalization, preflight validation, successful fake agent responses, no-citation warnings, permission guidance, and secret redaction.
- `ui_tests/test_admin_source_review_settings.py` validates that the Admin Settings Web Search test button renders and displays a mocked successful response.

## Known Limitations

The test confirms the configured Foundry agent can respond to a small live-search prompt. It cannot guarantee every future user query will return citations, because the final behavior still depends on the agent instructions, Bing grounding availability, quota, and the searched content.