// Sidebar Navigation Functionality

/**
 * Nav layout toggle (top nav <-> sidebar nav)
 * - Persists in user settings via /api/user/settings
 * - On page load, fetches user settings to update toggle text
 */

// Utility functions for user settings
async function getUserSettings() {
  try {
    const resp = await fetch('/api/user/settings');
    if (!resp.ok) return {};
    const data = await resp.json();
    return data.settings || {};
  } catch (e) {
    console.error('Error fetching user settings:', e);
    return {};
  }
}

async function setUserNavLayout(navLayout) {
  try {
    await fetch('/api/user/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: { navLayout } })
    });
    console.log('Nav layout setting saved successfully:', navLayout);
  } catch (e) {
    console.error('Error saving nav layout setting:', e);
  }
}

// Update toggle text based on current layout
function updateNavLayoutToggleText(navLayout) {
  document.querySelectorAll('.nav-layout-toggle').forEach(btn => {
    const icon = '<i class="bi bi-window-sidebar me-2"></i>';
    if (navLayout === 'sidebar') {
      btn.innerHTML = icon + 'Top Nav';
    } else {
      btn.innerHTML = icon + 'Left Nav';
    }
  });
}

// Initialize sidebar navigation functionality
document.addEventListener('DOMContentLoaded', () => {
  // On click, toggle nav layout in user settings and reload
  document.querySelectorAll('.nav-layout-toggle').forEach(btn => {
    btn.addEventListener('click', async function(e) {
      e.preventDefault();
      const settings = await getUserSettings();
      
      // Determine current effective layout (same logic as server-side)
      const userNavLayout = settings.navLayout;
      const adminDefault = window.simplechatAdminNavDefault || false;
      const currentEffectiveLayout = userNavLayout === 'sidebar' || (!userNavLayout && adminDefault) ? 'sidebar' : 'top';
      
      // Toggle to the opposite layout
      const next = currentEffectiveLayout === 'sidebar' ? 'top' : 'sidebar';
      await setUserNavLayout(next);
      window.location.reload();
    });
  });

  // On load, update toggle text based on user settings and admin defaults
  getUserSettings().then(settings => {
    // Determine the effective nav layout considering admin defaults (same logic as server-side in base.html)
    const userNavLayout = settings.navLayout;
    
    // Get admin default from the global variable set in base.html
    const adminDefault = window.simplechatAdminNavDefault || false;
    
    // Apply same logic as server-side: use sidebar if user chose it OR if no user choice and admin default is true
    const effectiveLayout = userNavLayout === 'sidebar' || (!userNavLayout && adminDefault) ? 'sidebar' : 'top';
    updateNavLayoutToggleText(effectiveLayout);
  });
});

// Export functions for use in other modules if needed
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    getUserSettings,
    setUserNavLayout,
    updateNavLayoutToggleText
  };
}
