# Public Workspace Manage Script Syntax Fix

Fixed/Implemented in version: **0.241.009**

## Issue Description

The public workspace management page could fail to load with a browser syntax error:

```text
Uncaught SyntaxError: Unexpected token '&' (at manage_public_workspace.js:310:27)
```

The reported `&bull;` line was valid JavaScript, but the parser reached it after an earlier malformed template-literal fragment in the document-ready event binding block.

## Root Cause Analysis

The `$(document).ready(...)` block in `application/single_app/static/js/public/manage_public_workspace.js` contained duplicated user-search event bindings and spliced fragments from the user-search result template.

Those fragments left raw template markup and HTML table cells inside executable JavaScript, so Chromium and Node reported a syntax error before the rest of the public workspace page scripts could initialize.

## Technical Details

Files modified:

- `application/single_app/static/js/public/manage_public_workspace.js`
- `application/single_app/config.py`
- `functional_tests/test_public_workspace_manage_script_syntax_fix.py`
- `ui_tests/test_public_workspace_manage_script_parse.py`
- `docs/explanation/fixes/v0.241.009/PUBLIC_WORKSPACE_MANAGE_SCRIPT_SYNTAX_FIX.md`
- `docs/explanation/release_notes.md`

Code changes summary:

- Removed the stray template-literal and HTML fragments from the document-ready handler block.
- Preserved the delegated `.select-user-btn` click handler added for safe member search selection.
- Restored the delegated approve and reject request handlers for `#pendingRequestsTable`.
- Kept the CSV bulk upload handlers immediately after the restored request handlers.
- Aligned regression artifacts with `VERSION = "0.241.009"` in `application/single_app/config.py`.

Testing approach:

- Added a functional regression that runs `node --check` when Node.js is available and verifies the document-ready block no longer contains the known spliced fragments.
- Added a Playwright regression that compiles the script with Chromium's JavaScript parser.

Impact analysis:

- Public workspace management pages can initialize again instead of stopping at the first syntax error.
- Member search selection, pending request approval/rejection, and CSV bulk member upload event wiring remain available.

## Validation

Before the fix, `manage_public_workspace.js` failed to parse and the public workspace page could not load its management scripts. After the fix, both Node.js and Chromium parser checks validate the script, and the restored event handlers are covered by targeted regression tests.

Related config.py version update: `VERSION = "0.241.009"`

Related tests:

- `functional_tests/test_public_workspace_manage_script_syntax_fix.py`
- `ui_tests/test_public_workspace_manage_script_parse.py`