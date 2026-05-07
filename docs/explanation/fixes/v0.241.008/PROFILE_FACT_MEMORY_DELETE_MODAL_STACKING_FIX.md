# Profile Fact Memory Delete Modal Stacking Fix

Fixed/Implemented in version: **0.241.008**

## Issue Description

The profile page fact-memory manager opens a delete-confirmation modal from inside the larger Manage Fact Memories modal.

That confirm dialog could render behind the manager modal content, which made the destructive action difficult or impossible to click. The same profile template also used `display: none` style toggles for the text-to-speech preview controls instead of Bootstrap's `d-none` class pattern.

## Root Cause Analysis

`requestFactMemoryDelete()` and `openFactMemoryModal()` in `application/single_app/templates/profile.html` both relied on default Bootstrap modal instances without any stacked-modal coordination.

Because `factMemoryDeleteModal` and `factMemoryManagerModal` shared the same default Bootstrap modal z-index behavior, the child confirmation modal could lose the stacking order battle against the already-open manager modal.

Separately, the TTS preview controls in the same profile template hid and showed the stop button through `style.display` assignments, which diverged from the repo's Bootstrap visibility guidance.

## Technical Details

Files modified: `application/single_app/templates/profile.html`, `application/single_app/config.py`, `ui_tests/test_profile_fact_memory_editor.py`

Code changes summary:

- Added explicit stacked-modal classes and lifecycle handlers for the fact-memory delete confirmation modal so it renders above the manager modal while the manager remains visible behind it.
- Switched fact-memory modal initialization to `bootstrap.Modal.getOrCreateInstance(...)`, moved the delete modal to the document body, and restored `modal-open` state when closing the child confirm over an open manager modal.
- Added fail-closed status messaging if the delete confirmation modal is unavailable.
- Replaced the profile TTS preview button visibility toggles with a shared helper that uses Bootstrap's `d-none` class instead of `style.display`.
- Extended the existing profile UI regression to assert stacked z-index behavior, stacked backdrop classes, retained manager-modal visibility after delete, and the hidden TTS stop button class contract.

Impact analysis:

- Users can now reliably confirm fact-memory deletes from the profile modal workflow without the confirm dialog being hidden behind the parent modal.
- The profile page now follows the repo's Bootstrap visibility pattern for the TTS preview controls.

## Validation

Test coverage: `ui_tests/test_profile_fact_memory_editor.py`

Test results:

- Validates that the profile page still supports create, edit, retag, and delete operations for fact memories.
- Validates that the delete confirm dialog is stacked above the manager modal and that the stacked backdrop class is applied.
- Validates that the manager modal remains open after a successful delete and that the page keeps `modal-open` state.
- Validates that the hidden TTS stop button uses Bootstrap's `d-none` class when the TTS section is available in the environment.

Before/after comparison:

- Before: The delete confirmation dialog could appear behind the Manage Fact Memories modal, blocking clicks, and the TTS preview controls used `style.display` toggles.
- After: The delete confirmation dialog explicitly stacks above the manager modal, and the TTS preview controls use Bootstrap `d-none` visibility toggles.

Related config.py version update: `VERSION = "0.241.008"`