# Agent Audit Metadata Validation Fix (v0.239.112)

## Issue Description
Saving an existing agent could fail with `Agent validation failed: Additional properties are not allowed ('created_at', 'created_by', 'modified_at', 'modified_by' were unexpected)` when the browser sent back a round-tripped agent object that included server-managed audit metadata.

## Root Cause Analysis
The backend sanitized user-editable agent fields, but it did not strip server-managed audit or Cosmos metadata before schema validation. As a result, valid agent edits could be rejected purely because the payload still contained fields previously added by the backend.

## Version Implemented
Fixed/Implemented in version: **0.239.112**

## Technical Details
### Files Modified
- application/single_app/functions_agent_payload.py
- application/single_app/config.py
- functional_tests/test_agent_audit_metadata_validation_fix.py

### Code Changes Summary
- Strip server-managed agent metadata such as `created_at`, `created_by`, `modified_at`, `modified_by`, `updated_at`, `last_updated`, `user_id`, `group_id`, and Cosmos system fields during payload sanitization.
- Preserve existing save behavior where the backend rehydrates authoritative audit fields before persistence.
- Add a regression test that validates a round-tripped agent payload can still pass schema validation.

### Testing Approach
- Run the functional test `functional_tests/test_agent_audit_metadata_validation_fix.py`.

## Impact Analysis
- Editing and saving existing agents no longer fails when the client includes backend-managed metadata.
- The backend now treats audit metadata as authoritative server state rather than client-provided input.

## Validation
- Functional test: functional_tests/test_agent_audit_metadata_validation_fix.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.239.112**.