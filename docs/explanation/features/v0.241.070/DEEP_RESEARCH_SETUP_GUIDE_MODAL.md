# Deep Research Setup Guide Modal

## Overview
The Admin Settings Deep Research section now includes a Setup Guide modal that explains how to configure Deep Research, assign the optional `DeepResearchUser` Enterprise App role, and tune the source-review controls.

Implemented in version: **0.241.070**

## Dependencies
- Deep Research settings in `functions_source_review.py`
- Admin Settings template `admin_settings.html`
- Modal partial `_deep_research_info.html`
- Optional Entra Enterprise App role `DeepResearchUser`
- Web Search via Foundry Agent for search-backed Deep Research flows

## Technical Specifications
- Adds a Bootstrap `Setup Guide` button to the Deep Research card header in Admin Settings.
- Adds `_deep_research_info.html` as a static modal include, matching existing setup guide patterns such as Web Search and Key Vault.
- Documents role setup steps for `DeepResearchUser`, configuration guidance for every Deep Research setting, safety boundaries, and troubleshooting checks.
- Does not add dynamic JavaScript or render untrusted values in the modal.
- Updates `config.py` version to `0.241.070`.

## Usage Instructions
1. Open Admin Settings.
2. Go to the Search & Extract tab.
3. In the Deep Research card, select `Setup Guide`.
4. Review the recommended setup steps, app-role assignment flow, settings reference, safety boundaries, and troubleshooting checklist.

## Testing and Validation
- `ui_tests/test_admin_source_review_settings.py` validates that the modal opens and contains role setup, settings reference, and browser-runtime guidance.
- The existing Deep Research UI test continues to validate the primary settings controls and removal of the legacy assigned-user UI.

## Known Limitations
- The modal provides setup guidance only. App role assignment still occurs in Microsoft Entra ID through the Enterprise App experience or deployment automation.
