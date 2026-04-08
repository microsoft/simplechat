# Chat Model Description Tooltip Fix (v0.236.023)

## Issue Description
Chat model options did not expose model descriptions on hover, making it harder for users to choose between similar models.

## Root Cause Analysis
The model select options did not include a tooltip title derived from the model description.

## Version Implemented
Fixed/Implemented in version: **0.236.023**

## Technical Details
### Files Modified
- application/single_app/templates/chats.html
- application/single_app/config.py

### Code Changes Summary
- Added a title attribute on multi-endpoint model options using the model description (or display name as fallback).
- Incremented the application version.

### Testing Approach
- Added a functional test to verify the tooltip title is present in the chat template.

### Impact Analysis
- Improves model selection clarity with descriptive hover text.

## Validation
- Functional test: functional_tests/test_chat_model_description_tooltip.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.023**.
