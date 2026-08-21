# Multi-Endpoint Vision Test Connection Fix

Fixed/Implemented in version: **0.250.008**

## Issue Description

The Admin Settings **Test Vision Analysis** button failed for vision-capable models that were configured through multi-endpoint model management when those models lived on a different Azure OpenAI or Foundry endpoint than the legacy GPT endpoint.

## Root Cause Analysis

The Vision Model dropdown had been updated to show multi-endpoint models, but the test button still submitted only the selected deployment name and the legacy GPT endpoint settings. As a result, a deployment such as `openai-5.1-test` could be displayed correctly, but the backend test attempted to call that deployment on the legacy Azure OpenAI resource and returned `DeploymentNotFound`.

The backend also contained duplicate `_test_multimodal_vision_connection` definitions, leaving only the second function active at runtime and making the intended behavior harder to maintain.

## Technical Details

Files modified:

*   `application/single_app/static/js/admin/admin_settings.js`
*   `application/single_app/templates/admin_settings.html`
*   `application/single_app/route_backend_settings.py`
*   `application/single_app/config.py`
*   `functional_tests/test_multimodal_vision_multi_endpoint_connection.py`

Code changes summary:

*   Added endpoint and model metadata to multi-endpoint Vision Model options while preserving the deployment name as the saved value.
*   Updated the Vision test payload to include `endpoint_id`, `model_id`, provider, model name, and deployment name when a multi-endpoint model is selected.
*   Updated the backend Vision test connection path to resolve the selected endpoint/model from saved settings and build the correct model endpoint client server-side.
*   Removed the duplicate `_test_multimodal_vision_connection` implementation.
*   Preserved GPT-5 and o-series `max_completion_tokens` handling by using the resolved model name as well as the deployment name.

## Validation

Test results:

*   `python -m py_compile application/single_app/config.py application/single_app/route_backend_settings.py functional_tests/test_multimodal_vision_multi_endpoint_connection.py`
*   `python functional_tests/test_multimodal_vision_multi_endpoint_connection.py`
*   `python scripts/check_swagger_routes.py application/single_app/route_backend_settings.py`
*   `python scripts/check_xss_sinks.py --base-sha upstream/Development --head-sha HEAD application/single_app/route_backend_settings.py application/single_app/static/js/admin/admin_settings.js application/single_app/templates/admin_settings.html`
*   `python scripts/check_broken_access_control.py --base-sha upstream/Development --head-sha HEAD application/single_app/route_backend_settings.py`
*   Route policy coverage tests under `functional_tests/route_tests/`

Before the fix, the Vision test button called multi-endpoint deployments against the legacy GPT endpoint. After the fix, multi-endpoint Vision tests resolve and call the selected model's configured endpoint.