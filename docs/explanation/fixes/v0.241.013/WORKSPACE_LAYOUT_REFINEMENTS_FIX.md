# WORKSPACE LAYOUT REFINEMENTS FIX

Fixed in version: **0.241.013**

## Overview

This refinement tightens several workspace navigation issues introduced during the broader mobile workspace refresh.
Version `0.241.013` in `application/single_app/config.py` is the version associated with these updates.

## Issue Description

- Group workspace placed the section switcher too far above the selected pane, especially on narrow layouts.
- Left-nav workspace menus omitted personal and group endpoint entries even when endpoint tabs were enabled.
- Workspace tabs used a rounded pill-style edge that did not match the established workspace tab look.

## Root Cause Analysis

- The group workspace section switcher was attached to the page header instead of the tab area it controlled.
- Sidebar workspace submenu items were added for documents, prompts, agents, and actions, but endpoint items were never added.
- Shared responsive workspace CSS introduced a custom `border-radius` on nav tabs instead of preserving the flatter style already used in the app.

## Technical Details

### Files Modified

- `application/single_app/templates/_sidebar_nav.html`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/static/css/workspace-responsive.css`
- `application/single_app/config.py`
- `ui_tests/test_workspace_sidebar_endpoint_links.py`

### Code Changes Summary

- Added `Your Endpoints` and `Group Endpoints` entries to the left-nav workspace submenus when the corresponding endpoint tabs are enabled.
- Moved the group workspace section switcher below the shared group controls and immediately above the group tab area.
- Restored square workspace tab corners by removing the pill-style border radius from the shared responsive workspace stylesheet.

## Validation

- Added UI regression coverage in `ui_tests/test_workspace_sidebar_endpoint_links.py` for square tab styling and endpoint sidebar entries.
- Verified the changed CSS file with editor diagnostics.

## Impact Analysis

- Workspace section selection now feels visually connected to the pane it controls.
- Endpoint management is reachable from left-nav layouts again.
- Workspace tabs match the prior visual language instead of appearing as rounded pills.