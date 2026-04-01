# NEW_FOUNDRY_VERSION_METADATA_FIX.md

# New Foundry Version Metadata Fix

Fixed in version: **0.239.177**

## Issue

New Foundry application fetches were succeeding, but the returned list was not always surfacing the published version number in the agent selector. That forced the user to infer version metadata manually. The agent modal also exposed a manual version field even though the live Responses invocation path uses the application name and endpoint-level OpenAI API version instead.

## Root Cause

- The REST normalization logic did not read nested version shapes such as `versions.latest.version`.
- The agent modal treated application version as a user-entered value instead of fetched metadata.
- The agent modal still used a hardcoded default for the Responses API version instead of inheriting it from the selected endpoint configuration.

## Files Modified

- `application/single_app/foundry_agent_runtime.py`
- `application/single_app/static/js/agent_modal_stepper.js`
- `application/single_app/templates/_agent_modal.html`
- `application/single_app/templates/_multiendpoint_modal.html`
- `functional_tests/test_new_foundry_fetch_support.py`
- `functional_tests/test_new_foundry_version_metadata.py`
- `application/single_app/config.py`

## Validation

- Functional coverage verifies nested New Foundry version metadata is read from the fetched payload.
- Functional coverage verifies the version field is no longer presented as a manual entry field in the agent modal.
- Functional coverage verifies the current app version and selector-version formatting are present.

## Impact

Users can fetch New Foundry applications and see the published version in the selector while continuing to configure the runtime by application name. The Responses API version is now inherited from endpoint configuration rather than hardcoded in the agent modal.