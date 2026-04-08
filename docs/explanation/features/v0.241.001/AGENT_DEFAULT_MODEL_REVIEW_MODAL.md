# Agent Default Model Review Modal

Version implemented: **0.240.073**

## Overview

The AI Models section now includes an agent default-model review workflow that scales beyond a short inline list. Admins can review agents in a modal, selectively apply the saved default model to inherited agents, and explicitly override selected agents that already carry custom or non-default model settings.

## Dependencies

- `application/single_app/route_backend_agents.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_model_endpoints.js`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/functions_agent_payload.py`

## Technical Specifications

### Architecture Overview

- The backend preview classifies every global, group, and personal local agent against the saved default model.
- Preview records now distinguish:
  - recommended inherited agents that should adopt the saved default automatically
  - manual-review agents that admins may explicitly override
  - agents already aligned to the saved default
  - agents blocked until a valid default model is saved
- The migration run endpoint accepts explicit `selected_agent_keys` so the UI can apply the saved default only to the rows an admin selected.

### User Experience

- The AI Models tab shows a compact summary card instead of an inline table that can grow unbounded.
- The full review opens in a scrollable Bootstrap modal with:
  - search
  - status filtering
  - recommended selection helpers
  - manual-review override selection helpers
- When agents are disabled, AI Models shows guidance explaining that this workflow becomes available after agents are enabled.
- The Agents tab includes a direct link back to AI Models so admins can discover the review workflow from the place where they manage agents.

## Usage Instructions

1. Enable Agents in the Agents tab if they are currently disabled.
2. Enable multi-endpoint model management and save a valid default model in AI Models.
3. Open the agent review modal from AI Models.
4. Review the recommended selections.
5. Add explicit override candidates only when you intentionally want to replace a custom or non-default binding with the saved default model.
6. Apply the saved default model to the selected agents.

## Testing And Validation

- Functional coverage verifies the modal wiring, explicit selection payload, override support, and cross-links between Agents and AI Models.
- UI coverage verifies that the modal controls are present when the admin settings page loads.
- This workflow is intended to remain useful after future default-model changes so admins can rebalance agent costs or standardize on new model releases.