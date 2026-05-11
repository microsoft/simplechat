# Admin Settings Tab Preservation Fix

**Version:** 0.229.058

## Issue Description

When users were working in the admin settings page and clicked the save button from any tab other than "General", the page would redirect back to the "General" tab after saving, rather than preserving the tab they were working in. This was frustrating for users who were making changes in specific sections like "Search & Extract", "Agents", "AI Models", or "Safety" as they would lose their place and have to navigate back to the tab they were working in.

**Note**: This issue affected both the traditional tab-based navigation and the newer sidebar navigation interface.

## Root Cause Analysis

The issue occurred because:

1. **Server-side redirects lose hash fragments**: When the admin settings form is submitted via POST, the Flask backend redirects to `url_for('admin_settings')` which goes to the base URL without any hash fragment (like `#search-extract` or `#safety`).

2. **Hash fragments are not preserved during server redirects**: Unlike query parameters, hash fragments are handled entirely on the client side and are not sent to the server during form submissions.

3. **Tab activation only checked URL hash on page load**: The existing navigation functions only looked at `window.location.hash` but didn't have any mechanism to restore a previously active tab after a redirect.

4. **Dual navigation interfaces**: The admin settings page supports both traditional Bootstrap tab navigation and a newer sidebar navigation, requiring different handling for each mode.

## Technical Solution

### Implementation Details

The fix was implemented entirely on the client-side using JavaScript in `admin_settings.js`:

#### 1. **Active Tab Detection Function**
```javascript
function getCurrentActiveTab() {
    // First check if we're using sidebar navigation
    const sidebarToggle = document.getElementById('admin-settings-toggle');
    if (sidebarToggle) {
        // For sidebar navigation, check for active sidebar nav links
        const activeSidebarTab = document.querySelector('.admin-nav-tab.active');
        if (activeSidebarTab) {
            const tabId = activeSidebarTab.getAttribute('data-tab');
            return tabId ? '#' + tabId : null;
        }
        
        // Fallback: check which tab pane is currently visible for sidebar nav
        const activeTabPane = document.querySelector('.tab-pane.show.active');
        if (activeTabPane) {
            return '#' + activeTabPane.id;
        }
        
        // If no active tab found but we have a hash, use that
        if (window.location.hash) {
            return window.location.hash;
        }
    } else {
        // For tab navigation, check Bootstrap tab buttons
        const activeTabButton = document.querySelector('button.nav-link.active[data-bs-target]');
        if (activeTabButton) {
            return activeTabButton.getAttribute('data-bs-target');
        }
        
        // Fallback: check which tab pane is currently visible for tab nav
        const activeTabPane = document.querySelector('.tab-pane.fade.show.active');
        if (activeTabPane) {
            return '#' + activeTabPane.id;
        }
    }
    
    return null;
}
```

#### 2. **Form Submission Enhancement**
```javascript
adminForm.addEventListener('submit', function(e) {
    try {
        // Capture the current active tab before form submission
        const activeTab = getCurrentActiveTab();
        if (activeTab) {
            // Store the active tab in sessionStorage to restore after redirect
            sessionStorage.setItem('adminSettingsActiveTab', activeTab);
        }
        // ... rest of existing form validation logic
    } catch (err) {
        console.error("Error in form submission validation:", err);
    }
});
```

#### 3. **Tab Restoration Logic**
```javascript
function activateTabFromHash() {
    let hash = window.location.hash;
    
    // If no hash in URL, check sessionStorage for saved tab from form submission
    if (!hash) {
        const savedTab = sessionStorage.getItem('adminSettingsActiveTab');
        if (savedTab) {
            hash = savedTab;
            // Clear the saved tab to prevent it from affecting future navigation
            sessionStorage.removeItem('adminSettingsActiveTab');
            // Update URL with the restored hash
            history.replaceState(null, null, hash);
        }
    }
    
    if (hash) {
        const tabId = hash.startsWith('#') ? hash.substring(1) : hash;
        
        // Check if we're using sidebar navigation
        const sidebarToggle = document.getElementById('admin-settings-toggle');
        if (sidebarToggle) {
            // Use sidebar navigation functions
            if (typeof showAdminTab === 'function') {
                showAdminTab(tabId);
                
                // Set active nav link for sidebar
                const navLink = document.querySelector(`.admin-nav-tab[data-tab="${tabId}"]`);
                if (navLink) {
                    document.querySelectorAll('.admin-nav-tab').forEach(link => {
                        link.classList.remove('active');
                    });
                    navLink.classList.add('active');
                }
            }
        } else {
            // Use Bootstrap tab navigation
            const tabButton = document.querySelector(`button.nav-link[data-bs-target="${hash}"]`);
            if (tabButton) {
                const tab = new bootstrap.Tab(tabButton);
                tab.show();
            }
        }
    }
}
```

### Workflow

1. **User is on a specific tab** (e.g., `#search-extract` via sidebar navigation or `#agents` via tab navigation)
2. **User makes changes and clicks save**
3. **Form submission captures current active tab** using `getCurrentActiveTab()` (works for both navigation types)
4. **Active tab is stored in sessionStorage** as `'adminSettingsActiveTab'`
5. **Form submits normally**, server processes and redirects to base admin settings URL
6. **Page reloads**, `activateTabFromHash()` is called during `DOMContentLoaded`
7. **Function checks sessionStorage** for saved tab since URL has no hash
8. **Saved tab is restored** using the appropriate navigation method (sidebar or Bootstrap tabs)
9. **URL is updated** with the correct hash and sessionStorage is cleared

## Files Modified

### JavaScript
- **File**: `application/single_app/static/js/admin/admin_settings.js`
- **Changes**:
  - Added `getCurrentActiveTab()` function to detect the currently active tab with dual navigation support
  - Enhanced form submission handler to capture and store active tab in sessionStorage
  - Modified `activateTabFromHash()` to check sessionStorage when no URL hash is present
  - Added support for both Bootstrap tab navigation and sidebar navigation systems
  - Implemented priority detection for section-level vs tab-level active states in sidebar navigation
  - Added comprehensive debug logging for troubleshooting tab preservation workflow
  - Added URL hash update using `history.replaceState()` for restored tabs

### Version
- **File**: `application/single_app/config.py`
- **Changes**: Updated `VERSION = "0.229.046"`

## Testing

### Functional Tests

#### General Tab Preservation Test
Created `functional_tests/test_admin_settings_tab_preservation.py` which validates:

1. **JavaScript Implementation**: Verifies all required functions and logic are present
2. **HTML Structure**: Confirms the HTML template has the necessary tab structure
3. **Integration Workflow**: Tests the complete tab preservation workflow

#### Sidebar Navigation Test  
Created `functional_tests/test_sidebar_navigation_tab_preservation.py` which validates:

1. **Sidebar Structure**: Confirms proper sidebar navigation HTML structure with data-tab attributes
2. **JavaScript Support**: Verifies enhanced functions support sidebar navigation detection
3. **Integration**: Tests sidebar navigation system integration with tab preservation
4. **Specific Functionality**: Validates search-extract tab preservation functionality

### Test Results
```
General Tab Preservation Tests: 3/3 passed
Sidebar Navigation Tests: 4/4 passed
📊 Total Results: 7/7 tests passed
✅ All tab preservation tests passed!
💡 The admin settings now preserve the active tab when saving for both navigation systems
```

## User Experience Improvements

### Before the Fix
- User navigates to "Search & Extract" tab (sidebar) or "Agents" tab (Bootstrap tabs)
- User makes configuration changes
- User clicks "Save Settings"
- Page reloads and **always** shows "General" tab regardless of which navigation system is used
- User has to manually navigate back to their working tab
- **Poor user experience**: Loss of context and extra navigation required

### After the Fix
- User navigates to "Search & Extract" tab (sidebar) or "Agents" tab (Bootstrap tabs)
- User makes configuration changes  
- User clicks "Save Settings"
- Page reloads and **automatically** returns to the same tab with proper submenu state
- **Improved user experience**: Seamless workflow with preserved context for both navigation types

## Benefits

1. **Improved User Experience**: Users stay in their working context after saving
2. **Reduced Friction**: No need to re-navigate to the tab they were working in
3. **Better Workflow**: Especially beneficial for users making multiple changes in the same section
4. **Non-Intrusive**: Uses sessionStorage which automatically clears on tab close
5. **Backwards Compatible**: Existing URL hash navigation still works as before

## Edge Cases Handled

1. **No active tab detected**: Falls back gracefully without errors
2. **Invalid tab stored**: Bootstrap Tab API handles invalid selectors gracefully
3. **SessionStorage not available**: Code uses try-catch blocks for error handling
4. **Multiple tab navigation**: SessionStorage is cleared after use to prevent interference
5. **Direct URL access with hash**: Original hash navigation is preserved and takes precedence

## Technical Notes

- **SessionStorage vs LocalStorage**: Used sessionStorage to ensure the saved tab doesn't persist across browser sessions
- **History API**: Used `history.replaceState()` instead of `history.pushState()` to avoid creating extra history entries
- **Event Timing**: Form submission capture happens before the actual submission to ensure the active tab is correctly identified
- **Bootstrap Integration**: Works with Bootstrap 5 tab API and doesn't interfere with existing tab switching logic

This fix ensures that admin users can work efficiently in the settings interface without losing their place when saving changes.