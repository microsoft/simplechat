# Agent Payload Field Lengths Fix (Version v0.237.001)

## Header Information
- **Fix Title:** Agent payload field length validation
- **Issue Description:** Agent payload validation did not enforce length limits, allowing oversized values into storage.
- **Root Cause Analysis:** Length checks existed but were never invoked in `sanitize_agent_payload`, and no limits covered Azure-specific fields.
- **Fixed/Implemented in version:** **0.237.009**
- **Config Version Updated:** `config.py` VERSION set to **0.237.009**

## Technical Details
- **Files Modified:**
  - application/single_app/functions_agent_payload.py
  - application/single_app/config.py
- **Code Changes Summary:**
  - Added max length recommendations for Azure OpenAI and APIM fields.
  - Validated field lengths in `sanitize_agent_payload` and for Foundry settings.
  - Bumped application version in config.py.
- **Testing Approach:**
  - Added a functional test to confirm validation wiring and limits are present.

## Validation
- **Test Results:** functional_tests/test_agent_payload_field_lengths.py
- **Before/After Comparison:**
  - Before: Oversized agent fields could pass validation.
  - After: Oversized fields raise `AgentPayloadError` with a clear message.
- **User Experience Improvements:**
  - Prevents invalid payloads and provides consistent validation feedback.
