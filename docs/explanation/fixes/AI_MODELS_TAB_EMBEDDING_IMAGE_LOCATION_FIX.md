# AI Models Tab Embedding/Image Location Fix (v0.236.014)

## Issue Description
Embeddings and image generation configuration were placed inside the legacy AI model modal, which made them harder to find and inconsistent with the expected AI Models tab layout.

## Root Cause Analysis
The embeddings and image generation cards were moved into the legacy modal during a refactor that consolidated legacy GPT settings into a modal, unintentionally relocating non-legacy sections.

## Version Implemented
Fixed/Implemented in version: **0.236.014**

## Technical Details
### Files Modified
- application/single_app/templates/admin_settings.html
- application/single_app/config.py

### Code Changes Summary
- Moved the embeddings and image generation cards back to the AI Models tab.
- Kept GPT configuration in the legacy modal.
- Incremented the application version.

### Testing Approach
- Added a functional test to assert that the embeddings and image generation sections are outside the legacy modal markup.

### Impact Analysis
- Restores expected layout for administrators.
- Prevents settings from being hidden in the legacy modal.
- Maintains legacy GPT configuration flow without impacting multi-endpoint UI.

## Validation
- Functional test: functional_tests/test_ai_models_tab_embedding_image_location.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.014**.
