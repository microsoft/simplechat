# Agent Modal Multi-Endpoint & Foundry Notice Fix (Version 0.236.054)

## Overview
Hides custom connection controls in the agent modal when multi-endpoint model management is enabled and adds an advanced settings notice for Azure AI Foundry agents.

## Issue Description
When multi-endpoint model management is enabled, custom connection fields should not be available in the agent modal. Additionally, Azure AI Foundry agents need a clear notice that advanced settings are managed by Foundry.

## Root Cause Analysis
The agent modal always rendered custom connection controls and lacked a Foundry-specific advanced settings notice.

## Fix Summary
- Hide custom connection toggle and fields via Jinja when multi-endpoint model management is enabled.
- Add an advanced settings notice for Foundry agents and toggle visibility in the modal stepper.

## Files Modified
- application/single_app/templates/_agent_modal.html
- application/single_app/static/js/agent_modal_stepper.js
- application/single_app/config.py
- functional_tests/test_agent_modal_multiendpoint_foundry_advanced_notice.py

## Testing
- Added functional test: `test_agent_modal_multiendpoint_foundry_advanced_notice.py`.

## Validation
- Verified the custom connection fields are gated by the multi-endpoint setting.
- Verified the Foundry advanced notice is toggled when selecting Foundry agent type.

## Version
Fixed/Implemented in version: **0.236.054**

## Config Version Reference
`config.py` updated to `VERSION = "0.236.054"`.
