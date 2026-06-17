// sidebar.js

// Sidebar Navigation Functionality

/**
 * Nav layout toggle (top nav <-> sidebar nav)
 * - Persists in user settings via /api/user/settings
 * - On page load, fetches user settings to update toggle text
 */

// Utility functions for user settings
const sidebarMenuStateKeys = new Set([
  'workspaces',
  'support',
  'externalLinks',
  'customPages',
  'adminSettings',
  'controlCenter',
  'conversations'
]);

async function getUserSettings() {
  if (window.simplechatUserSettings && typeof window.simplechatUserSettings === 'object') {
    return window.simplechatUserSettings;
  }

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
    const resp = await fetch('/api/user/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: { navLayout } })
    });
    if (resp.ok && window.simplechatUserSettings && typeof window.simplechatUserSettings === 'object') {
      window.simplechatUserSettings.navLayout = navLayout;
    }
    console.log('Nav layout setting saved successfully:', navLayout);
  } catch (e) {
    console.error('Error saving nav layout setting:', e);
  }
}

function normalizeSidebarMenuState(menuState) {
  if (!menuState || typeof menuState !== 'object' || Array.isArray(menuState)) {
    return {};
  }

  return Object.entries(menuState).reduce((normalizedState, [key, value]) => {
    if (!sidebarMenuStateKeys.has(key)) {
      return normalizedState;
    }

    if (typeof value === 'boolean') {
      normalizedState[key] = value;
      return normalizedState;
    }

    if (typeof value === 'string') {
      const normalizedValue = value.trim().toLowerCase();
      if (normalizedValue === 'true' || normalizedValue === 'false') {
        normalizedState[key] = normalizedValue === 'true';
      }
    }

    return normalizedState;
  }, {});
}

function readInitialSidebarMenuState() {
  if (window.simplechatSidebarMenuState && typeof window.simplechatSidebarMenuState === 'object') {
    return normalizeSidebarMenuState(window.simplechatSidebarMenuState);
  }

  const stateElement = document.getElementById('sidebar-menu-state-data');
  if (!stateElement) {
    return {};
  }

  try {
    const parsedState = JSON.parse(stateElement.textContent || '{}');
    return normalizeSidebarMenuState(parsedState);
  } catch (error) {
    console.warn('Unable to parse sidebar menu state:', error);
    return {};
  }
}

function getSidebarMenuStateCache() {
  window.simplechatSidebarMenuState = normalizeSidebarMenuState(
    window.simplechatSidebarMenuState || readInitialSidebarMenuState()
  );

  return window.simplechatSidebarMenuState;
}

async function saveSidebarMenuState(menuKey, isExpanded) {
  if (!menuKey) {
    return false;
  }

  if (!sidebarMenuStateKeys.has(menuKey)) {
    console.warn('Ignoring unsupported sidebar menu state key:', menuKey);
    return false;
  }

  const currentMenuState = getSidebarMenuStateCache();
  const nextMenuState = normalizeSidebarMenuState({
    ...currentMenuState,
    [menuKey]: Boolean(isExpanded)
  });
  window.simplechatSidebarMenuState = nextMenuState;

  try {
    const response = await fetch('/api/user/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ settings: { sidebarMenuState: nextMenuState } })
    });

    if (!response.ok) {
      console.warn('Sidebar menu state was not saved:', response.statusText);
      return false;
    }

    return true;
  } catch (error) {
    console.warn('Error saving sidebar menu state:', error);
    return false;
  }
}

function getSidebarMenuToggle(menuKey) {
  return Array.from(document.querySelectorAll('[data-sidebar-menu-key]'))
    .find((toggle) => toggle.dataset.sidebarMenuKey === menuKey) || null;
}

function setSidebarMenuExpanded(toggle, isExpanded, options = {}) {
  if (!toggle) {
    return false;
  }

  const section = document.getElementById(toggle.dataset.sidebarMenuTarget || '');
  const caret = document.getElementById(toggle.dataset.sidebarMenuCaret || '')
    || toggle.querySelector('.bi-caret-down-fill');

  if (section) {
    section.classList.toggle('d-none', !isExpanded);
    section.setAttribute('aria-hidden', String(!isExpanded));
  }

  toggle.setAttribute('aria-expanded', String(isExpanded));

  if (caret) {
    caret.style.transform = isExpanded ? 'rotate(0deg)' : 'rotate(-90deg)';
  }

  if (options.persist !== false) {
    saveSidebarMenuState(toggle.dataset.sidebarMenuKey, isExpanded);
  }

  return isExpanded;
}

function setPersistentSidebarMenuExpanded(menuKey, isExpanded, options = {}) {
  const toggle = getSidebarMenuToggle(menuKey);
  return setSidebarMenuExpanded(toggle, isExpanded, options);
}

function initializePersistentSidebarMenus() {
  const menuState = getSidebarMenuStateCache();

  document.querySelectorAll('[data-sidebar-menu-key][data-sidebar-menu-target]').forEach((toggle) => {
    if (toggle.dataset.sidebarMenuBound === 'true') {
      return;
    }

    const menuKey = toggle.dataset.sidebarMenuKey;
    const section = document.getElementById(toggle.dataset.sidebarMenuTarget || '');
    const defaultExpanded = toggle.getAttribute('aria-expanded') !== 'false'
      && !(section && section.classList.contains('d-none'));
    const hasSavedState = Object.prototype.hasOwnProperty.call(menuState, menuKey);
    const isExpanded = hasSavedState ? menuState[menuKey] === true : defaultExpanded;

    toggle.dataset.sidebarMenuBound = 'true';
    setSidebarMenuExpanded(toggle, isExpanded, { persist: false });

    toggle.addEventListener('click', (event) => {
      const eventTarget = event.target instanceof Element ? event.target : null;
      if (eventTarget && eventTarget.closest('[data-sidebar-menu-ignore="true"]')) {
        return;
      }

      event.preventDefault();
      const nextExpanded = toggle.getAttribute('aria-expanded') !== 'true';
      setSidebarMenuExpanded(toggle, nextExpanded);
    });

    toggle.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') {
        return;
      }

      event.preventDefault();
      const nextExpanded = toggle.getAttribute('aria-expanded') !== 'true';
      setSidebarMenuExpanded(toggle, nextExpanded);
    });
  });
}

// Update toggle text based on current layout
function updateNavLayoutToggleText(navLayout) {
  // Top nav elements
  const switchToLeftNavText = document.getElementById('switchToLeftNavText');
  const switchToTopNavText = document.getElementById('switchToTopNavText');
  
  // Sidebar nav elements
  const sidebarSwitchToLeftNavText = document.getElementById('sidebarSwitchToLeftNavText');
  const sidebarSwitchToTopNavText = document.getElementById('sidebarSwitchToTopNavText');
  
  if (navLayout === 'top') {
    // Currently in top nav mode, show option to switch to left nav (sidebar)
    if (switchToLeftNavText) switchToLeftNavText.classList.remove('d-none');
    if (switchToTopNavText) switchToTopNavText.classList.add('d-none');
    if (sidebarSwitchToLeftNavText) sidebarSwitchToLeftNavText.classList.remove('d-none');
    if (sidebarSwitchToTopNavText) sidebarSwitchToTopNavText.classList.add('d-none');
  } else {
    // Currently in sidebar mode, show option to switch to top nav
    if (switchToLeftNavText) switchToLeftNavText.classList.add('d-none');
    if (switchToTopNavText) switchToTopNavText.classList.remove('d-none');
    if (sidebarSwitchToLeftNavText) sidebarSwitchToLeftNavText.classList.add('d-none');
    if (sidebarSwitchToTopNavText) sidebarSwitchToTopNavText.classList.remove('d-none');
  }
}

function getSidebarElements() {
  return {
    body: document.body,
    sidebar: document.getElementById('sidebar-nav'),
    toggleButton: document.getElementById('sidebar-toggle-btn'),
    floatingButton: document.getElementById('floating-expand-btn'),
    mainContent: document.getElementById('main-content'),
    allContentElements: document.querySelectorAll('.main-content, .container, .container-fluid, #main-content')
  };
}

function syncSidebarControls(isExpanded, toggleButton, floatingButton) {
  document.querySelectorAll('[data-sidebar-toggle="toggle"]').forEach((control) => {
    control.setAttribute('aria-expanded', String(isExpanded));
  });

  if (floatingButton) {
    floatingButton.classList.toggle('d-none', isExpanded);
    floatingButton.classList.toggle('sidebar-floating-expand-visible', !isExpanded);
    floatingButton.setAttribute('aria-hidden', String(isExpanded));
  }
}

function setSidebarExpandedState(isExpanded) {
  const {
    body,
    sidebar,
    toggleButton,
    floatingButton,
    mainContent,
    allContentElements
  } = getSidebarElements();

  if (!body || !sidebar) {
    return false;
  }

  sidebar.classList.toggle('sidebar-expanded', isExpanded);
  sidebar.classList.toggle('sidebar-collapsed', !isExpanded);
  body.classList.toggle('sidebar-collapsed', !isExpanded);

  allContentElements.forEach((element) => {
    element.style.marginLeft = isExpanded ? '' : '0px';
    element.style.maxWidth = isExpanded ? '' : '100%';
  });

  if (mainContent) {
    mainContent.classList.toggle('sidebar-padding', isExpanded);
  }

  syncSidebarControls(isExpanded, toggleButton, floatingButton);
  return isExpanded;
}

function toggleSidebar(event) {
  if (event) {
    event.preventDefault();
  }

  const { sidebar } = getSidebarElements();
  if (!sidebar) {
    return false;
  }

  const isExpanded = sidebar.classList.contains('sidebar-expanded') && !sidebar.classList.contains('sidebar-collapsed');
  return setSidebarExpandedState(!isExpanded);
}

function initializeSidebarToggleButtons() {
  document.querySelectorAll('[data-sidebar-toggle="toggle"]').forEach((button) => {
    if (button.dataset.sidebarToggleBound === 'true') {
      return;
    }

    button.dataset.sidebarToggleBound = 'true';
    button.addEventListener('click', toggleSidebar);
  });

  const { body, sidebar } = getSidebarElements();
  if (!body || !sidebar) {
    return;
  }

  const isExpanded = !body.classList.contains('sidebar-collapsed') && !sidebar.classList.contains('sidebar-collapsed');
  setSidebarExpandedState(isExpanded);
}

function initializeChatSidebarDrawer() {
  const sidebar = document.querySelector('#sidebar-nav[data-navigation-drawer="chat-rail"]');
  if (!sidebar || typeof bootstrap === 'undefined' || !bootstrap.Offcanvas) {
    return;
  }

  if (sidebar.dataset.chatSidebarDrawerBound === 'true') {
    return;
  }

  sidebar.dataset.chatSidebarDrawerBound = 'true';

  sidebar.addEventListener('click', (event) => {
    if (window.innerWidth > 991) {
      return;
    }

    const dismissTrigger = event.target.closest('a[href], #sidebar-new-chat-btn, .sidebar-conversation-item');
    if (!dismissTrigger || dismissTrigger.matches('a[href^="#"]')) {
      return;
    }

    const offcanvasInstance = bootstrap.Offcanvas.getInstance(sidebar);
    if (offcanvasInstance) {
      offcanvasInstance.hide();
    }
  });
}

if (typeof window !== 'undefined') {
  window.toggleSidebar = toggleSidebar;
  window.setPersistentSidebarMenuExpanded = setPersistentSidebarMenuExpanded;
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
    
    // Debug logging
    console.log('Nav Layout Debug:', {
      userNavLayout,
      adminDefault,
      effectiveLayout,
      settingsObject: settings
    });
    
    updateNavLayoutToggleText(effectiveLayout);
  }).catch(error => {
    console.error('Error loading nav layout settings:', error);
    // Default to top nav if error
    updateNavLayoutToggleText('top');
  });

  initializeSidebarToggleButtons();
  initializePersistentSidebarMenus();
  initializeChatSidebarDrawer();
});

// Export functions for use in other modules if needed
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    getUserSettings,
    setUserNavLayout,
    updateNavLayoutToggleText,
    toggleSidebar,
    setSidebarExpandedState,
    initializePersistentSidebarMenus,
    setPersistentSidebarMenuExpanded
  };
}
