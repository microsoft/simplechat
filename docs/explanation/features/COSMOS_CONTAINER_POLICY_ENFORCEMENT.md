# Cosmos Container Policy Enforcement

Implemented in version: **0.241.153**

## Overview

Cosmos container policy enforcement lets admins apply one global SimpleChat throughput automation policy to every dedicated-throughput Cosmos container. The policy also applies automatically to containers discovered later, so admins do not need to configure each new container manually.

Dependencies:

- Cosmos throughput monitoring and scaling controls in Admin Settings.
- Azure Resource Manager throughput read/write permissions for the app identity.
- Azure Monitor metrics read permissions for RU utilization data.

## Technical Specifications

Architecture overview:

- The setting `cosmos_throughput_enforce_container_defaults` is persisted with the Admin Settings Cosmos throughput configuration.
- When enabled, `get_container_policy()` resolves each container policy from the global automation thresholds, intervals, step sizes, and guardrails.
- Existing per-container cooldown timestamps are preserved so a recently scaled container does not immediately scale again after enforcement is enabled.
- New containers inherit the same enforced policy when they are discovered by Refresh or the background autoscale loop.

Configuration options:

- Enable Cosmos throughput automation.
- Configure the global scale-up/down thresholds, intervals, RU step sizes, and min/max guardrails.
- Enable Enforce global policy for all containers.
- Use Apply Global Policy in the Containers modal to stage the current global policy onto currently discovered containers.

File structure:

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `functional_tests/test_cosmos_throughput_autoscale_logic.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`

## Usage Instructions

1. Open Admin Settings and go to the Scale tab.
2. Enable Cosmos throughput automation.
3. Configure the global thresholds, intervals, RU step sizes, and guardrails.
4. Enable Enforce global policy for all containers.
5. Save Admin Settings.

When enabled, all dedicated-throughput containers use the same SimpleChat automation policy. Containers using shared database throughput remain visible but are not individually scalable until they have dedicated throughput.

## Testing and Validation

Test coverage:

- Functional test verifies enforced policy overrides saved per-container settings while preserving cooldown timestamps.
- Functional test verifies future containers with no saved row policy inherit the global policy.
- UI test verifies the enforcement switch and Apply Global Policy action are present.

Known limitations:

- This feature applies SimpleChat background scaling policy consistently. It does not convert Cosmos manual throughput resources into Cosmos autoscale throughput resources.