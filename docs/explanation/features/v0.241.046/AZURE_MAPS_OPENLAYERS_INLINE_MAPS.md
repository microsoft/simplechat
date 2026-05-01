# Azure Maps OpenLayers Inline Maps

Implemented in version: **0.241.046**

## Overview

SimpleChat now includes a built-in Azure Maps action that prepares inline OpenLayers maps directly inside assistant chat messages. Agents can pass structured court, site, or area coordinates into the action, and the chat UI renders the result as an interactive map card with markers, polygon overlays, and standard citation details.

## Dependencies

- `application/single_app/functions_azure_maps.py`
- `application/single_app/semantic_kernel_plugins/azure_maps_openlayers_plugin.py`
- `application/single_app/route_frontend_conversations.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`
- `application/single_app/static/js/plugin_modal_stepper.js`
- `application/single_app/templates/_plugin_modal.html`
- `application/single_app/static/js/chat/chat-inline-maps.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-citations.js`
- `application/single_app/static/css/chats.css`
- `application/single_app/templates/chats.html`

## Technical Specifications

### Action configuration

- Added a new built-in action type: `azure_maps_openlayers`.
- The workspace action modal now shows a dedicated Azure Maps configuration card instead of the generic endpoint/auth form.
- Only an Azure Maps subscription key is required from the user.
- Runtime defaults force the Azure Maps endpoint to `https://atlas.microsoft.com` and the action auth type to `key`.

### Secure tile delivery

- The browser does not receive the raw Azure Maps subscription key.
- The backend creates a short-lived encrypted tile proxy token from the stored key.
- Chat maps request raster tiles through `GET /api/azure-maps/tile`, which validates the token, sanitizes tile parameters, and proxies the request to Azure Maps.

### Chat rendering

- The Semantic Kernel action returns a structured payload with `render_type = azure_maps_openlayers` and a `map_payload` contract.
- Assistant messages now allocate an inline visualization region ahead of the citation accordion.
- A dedicated chat renderer hydrates Azure Maps artifacts when needed, then initializes OpenLayers with the proxy tile URL, markers, polygon areas, and fit-to-features view settings.
- Standard agent citation buttons remain available for the same tool invocation.

## Usage Instructions

1. Open the workspace `Actions` tab and create a new action.
2. Choose the `Azure Maps (OpenLayers)` action type.
3. Enter the Azure Maps subscription key and save the action.
4. Assign the action to an agent and call `create_map_visualization` with marker and optional area coordinates.
5. Review the assistant response in chat and interact with the rendered map card directly inside the message bubble.

## Testing And Validation

- Added `functional_tests/test_azure_maps_openlayers_plugin.py` to validate secure payload generation, token decoding, view defaults, and missing-feature validation.
- Added `ui_tests/test_workspace_azure_maps_action_modal.py` to validate the workspace modal flow, summary state, and save payload for the new built-in action.
- Added `ui_tests/test_chat_inline_azure_maps_rendering.py` to validate inline artifact hydration and map-card rendering inside assistant chat messages.
- The UI tests require `SIMPLECHAT_UI_BASE_URL` and `SIMPLECHAT_UI_STORAGE_STATE` in an authenticated environment.