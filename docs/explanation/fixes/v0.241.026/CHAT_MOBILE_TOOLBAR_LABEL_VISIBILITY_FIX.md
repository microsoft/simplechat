# Chat Mobile Toolbar Label Visibility Fix

Fixed/Implemented in version: **0.241.026**

## Issue Description

The mobile chat tools drawer still showed wide buttons with only icons when the buttons were not active.

That left large amounts of dead space in each row and made the drawer feel unfinished even though the layout and close behavior were already working.

## Root Cause Analysis

The toolbar button labels in `application/single_app/templates/chats.html` still included the Bootstrap utility classes `d-none d-md-inline`.

Those classes were originally added for the compact desktop toolbar behavior, but once the same buttons were moved into the mobile drawer they created a markup-level hidden state that conflicted with the mobile-specific CSS rules.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/templates/chats.html`, `functional_tests/test_chat_searchable_selectors.py`

Code changes summary:

- Removed `d-none d-md-inline` from the chat tools button labels so visibility is controlled by the toolbar CSS instead of hardcoded Bootstrap utility classes.
- Added a regression assertion to ensure the hidden desktop utility classes do not return to the shared toolbar labels.
- Bumped the application version to `0.241.026`.

Impact analysis:

- Mobile users now see readable labels for inactive drawer buttons instead of empty horizontal space.
- Desktop still keeps its compact inactive button behavior because that visibility is controlled by the existing toolbar CSS, not the removed Bootstrap utility classes.

## Validation

Test coverage: `functional_tests/test_chat_searchable_selectors.py`

Test results:

- `functional_tests/test_chat_searchable_selectors.py`: passed `9/9` checks after adding the label visibility regression assertion.

Before/after comparison:

- Before: Inactive mobile drawer buttons could render as icon-only rows with large empty space.
- After: Inactive mobile drawer buttons show their labels normally while desktop still hides inactive labels.

Related config.py version update: `VERSION = "0.241.026"`