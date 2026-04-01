# Foundry Agent Endpoint Validation Fix (Version 0.236.060)

## Header Information
- Fix Title: Prevent Foundry agent invocation without configured endpoint
- Issue Description: Foundry agents could be invoked without an endpoint resolved, resulting in runtime failures during agent execution.
- Root Cause Analysis: Foundry agents were registered even when endpoint configuration was missing, leaving runtime resolution to fail.
- Version Implemented: 0.236.060
- Fixed/Implemented in version: **0.236.060**
- Config version updated in: application/single_app/config.py

## Technical Details
### Files Modified
- application/single_app/semantic_kernel_loader.py
- application/single_app/config.py

### Code Changes Summary
- Added a helper to resolve Foundry endpoints using agent settings, global settings, and environment fallback.
- Prevented Foundry agent registration when no endpoint is available, falling back to kernel-only mode.

### Testing Approach
- Added functional test covering Foundry endpoint resolution priority and fallback.

### Impact Analysis
- Avoids runtime errors when Foundry agent endpoint configuration is missing.
- Improves clarity by keeping kernel-only mode when configuration is incomplete.

## Validation
- Test Results: Functional test added for endpoint resolution logic.
- Before/After Comparison:
  - Before: Foundry agent invocation failed at runtime with missing endpoint.
  - After: Foundry agent registration is skipped and kernel-only mode is used when endpoint is missing.
- User Experience Improvements:
  - Clearer fallback behavior and fewer runtime errors for misconfigured Foundry agents.

## Related Tests
- functional_tests/test_foundry_endpoint_resolution.py
