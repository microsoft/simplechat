# External Link Ordering Fix

## Header information

- **Issue:** Administrators could add, edit, delete, and save external links, but could not rearrange saved links.
- **Root cause:** The admin table did not expose controls that changed the order of the existing `external_links` array.
- **Fixed in version:** **0.250.102**
- **Tracking:** GitHub issue #793

## Technical details

### Files modified

- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/config.py`
- `functional_tests/test_external_link_ordering.py`
- `ui_tests/test_admin_external_link_ordering.py`

### Code changes

Saved external-link rows now include keyboard-accessible Move Up and Move Down buttons. The first row cannot move up, and the last row cannot move down. Activating a control swaps adjacent entries in the existing client-side array, rerenders the rows, updates the hidden `external_links_json` field, and marks the admin form as modified.

The affected row rendering now uses DOM element creation and text assignment. Dynamic link destinations are normalized to HTTP or HTTPS URLs before being assigned to an anchor.

### Testing approach

- Functional checks verify that both ordering controls are wired to the shared move handler and existing JSON synchronization flow.
- Azure Playwright coverage verifies boundary states, icon-button interaction, visible row order, and submitted JSON order.

### Impact analysis

No database migration or settings-schema change is required. The admin settings route already stores `external_links` in submitted list order, and navigation templates already render that list in order.

## Validation

### Before

Saved external links displayed in their original order with only Edit and Delete actions.

### After

Admins can move saved links one position up or down and save the resulting order through the existing Admin Settings workflow.

### User experience improvement

Administrators can control navigation ordering without deleting and recreating links.
