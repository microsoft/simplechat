# Group/Public Workspace Expanded Tags Fix

## Fix Title
Group and public workspace expanded list rows now display document tags like the personal workspace.

## Issue Description
When a user expanded a document in list view inside a group workspace or public workspace, the metadata panel omitted the document's tags. Personal workspace already showed tags in the same expanded view, and the backend APIs for group and public workspaces were already returning each document's `tags` array.

## Root Cause Analysis
- The group workspace expanded-details renderer in `group_workspaces.html` never added a `Tags:` row.
- The public workspace expanded-details renderer in `public_workspace.js` had the same omission.
- Both workspaces already loaded workspace tag definitions and document tag arrays for filtering and metadata editing, so the gap was limited to list-view UI rendering rather than missing backend data.

## Version Implemented
Fixed in version: **0.239.113**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/templates/group_workspaces.html` | Added a local tag badge renderer and inserted a `Tags:` row into expanded list-view document details. |
| `application/single_app/static/js/public/public_workspace.js` | Added a local tag badge renderer and inserted a `Tags:` row into expanded list-view document details. |
| `functional_tests/test_group_public_workspace_expanded_tags.py` | Added regression coverage for the group/public expanded tag rows and helper usage. |
| `application/single_app/config.py` | Version bump to `0.239.113`. |

## Code Changes Summary
- Added `renderGroupTagBadges()` in the group workspace page and `renderPublicTagBadges()` in the public workspace script.
- Reused existing workspace tag definitions and color utilities so tags render with configured colors when available.
- Added a neutral fallback badge color for unknown tag definitions and `No tags` text when a document has no tags.
- Inserted the new `Tags:` row between `Keywords:` and `Abstract:` to match the personal workspace expanded-details layout.

## Testing Approach
- Added `functional_tests/test_group_public_workspace_expanded_tags.py`.
- The test validates that:
  - Personal workspace still provides the parity reference for expanded tag rendering.
  - Group workspace defines a local badge helper and renders a `Tags:` row in expanded document details.
  - Public workspace defines a local badge helper and renders a `Tags:` row in expanded document details.
  - The `Tags:` row appears between `Keywords:` and `Abstract:` in both renderers.

## Impact Analysis
- Group workspace users now see document tags immediately when expanding a file in list view.
- Public workspace users now get the same visibility without needing to open metadata editing flows.
- The experience is now consistent across personal, group, and public workspaces while keeping backend contracts unchanged.

## Validation
- Before: group and public expanded list rows showed metadata such as version, authors, keywords, and abstract, but omitted tags.
- After: both workspaces render color-coded tag badges or a `No tags` fallback in the expanded details row.
- Regression test: `functional_tests/test_group_public_workspace_expanded_tags.py`