// Top Navigation Functionality

/**
 * Navigation-related utilities and event handlers
 * Handles general navigation behavior and interactions
 */

// Initialize top navigation functionality
document.addEventListener('DOMContentLoaded', () => {
  handleResponsiveNavigation();
  setupDropdownBehaviors();
  initializeMobileNavigationDrawer();
});

// Handle responsive navigation behavior
function handleResponsiveNavigation() {
  window.addEventListener('resize', () => {
    if (window.innerWidth > 991) {
      const navbarCollapse = document.querySelector('.navbar-collapse');
      if (navbarCollapse && navbarCollapse.classList.contains('show') && typeof bootstrap !== 'undefined' && bootstrap.Collapse) {
        bootstrap.Collapse.getOrCreateInstance(navbarCollapse).hide();
      }

      const offcanvasElement = document.getElementById('topNavMobileMenu');
      if (offcanvasElement && typeof bootstrap !== 'undefined' && bootstrap.Offcanvas) {
        const offcanvasInstance = bootstrap.Offcanvas.getInstance(offcanvasElement);
        if (offcanvasInstance) {
          offcanvasInstance.hide();
        }
      }
    }
  });
}

function initializeMobileNavigationDrawer() {
  const offcanvasElement = document.getElementById('topNavMobileMenu');
  if (!offcanvasElement || typeof bootstrap === 'undefined' || !bootstrap.Offcanvas) {
    return;
    }

  const offcanvasInstance = bootstrap.Offcanvas.getOrCreateInstance(offcanvasElement);

  offcanvasElement.querySelectorAll('a[href]').forEach((link) => {
    link.addEventListener('click', () => {
      offcanvasInstance.hide();
    });
  });
}

// Set up dropdown behaviors
function setupDropdownBehaviors() {
  document.querySelectorAll('.dropdown-toggle').forEach((dropdown) => {
    dropdown.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        if (typeof bootstrap !== 'undefined' && bootstrap.Dropdown) {
          const dropdownInstance = bootstrap.Dropdown.getOrCreateInstance(this);
          dropdownInstance.toggle();
        }
      }
    });
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('.dropdown')) {
      document.querySelectorAll('.dropdown-menu.show').forEach((menu) => {
        if (typeof bootstrap !== 'undefined' && bootstrap.Dropdown) {
          const dropdownToggle = menu.previousElementSibling;
          if (dropdownToggle) {
            const dropdownInstance = bootstrap.Dropdown.getInstance(dropdownToggle);
            if (dropdownInstance) {
              dropdownInstance.hide();
            }
          }
        }
      });
        }
  });
}

// Utility function to toggle navbar collapse on mobile
function toggleNavbarCollapse() {
  const navbarCollapse = document.querySelector('.navbar-collapse');
  if (navbarCollapse) {
    if (typeof bootstrap !== 'undefined' && bootstrap.Collapse) {
      const collapse = bootstrap.Collapse.getOrCreateInstance(navbarCollapse);
      collapse.toggle();
    } else {
      navbarCollapse.classList.toggle('show');
    }
    }
}

// Export functions for use in other modules if needed
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    handleResponsiveNavigation,
    setupDropdownBehaviors,
    toggleNavbarCollapse
  };
}
*** Add File: c:\Repos\simplechatmsft\application\single_app\static\css\workspace-responsive.css
/* Shared responsive workspace styles */

.workspace-page {
  padding-bottom: 2rem;
}

.workspace-page-header {
  align-items: flex-start;
  display: flex;
  gap: 1rem;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.workspace-page-title {
  margin-bottom: 0;
}

.workspace-page-subtitle {
  color: var(--bs-secondary-color, #6c757d);
  margin-bottom: 0;
}

.workspace-section-switcher {
  display: none;
  flex: 0 0 clamp(13rem, 30vw, 18rem);
  min-width: 13rem;
}

.workspace-section-switcher--persistent {
  display: flex;
}

.workspace-section-switcher .form-label {
  color: var(--bs-secondary-color, #6c757d);
  font-size: 0.82rem;
  font-weight: 600;
  margin-bottom: 0.35rem;
}

.workspace-page .nav-tabs {
  flex-wrap: nowrap;
  gap: 0.35rem;
  margin-bottom: 0;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
}

.workspace-page .nav-tabs .nav-link {
  border-radius: 999px 999px 0 0;
  white-space: nowrap;
}

.workspace-toolbar-actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.workspace-page .filter-buttons-col {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  justify-content: flex-end;
}

.workspace-page .action-dropdown .dropdown-toggle::after {
  display: none;
}

.workspace-page .table-loading-row td {
  color: #6c757d;
  padding: 1.5rem;
  text-align: center;
}

@media (max-width: 991.98px) {
  .workspace-page-header {
    flex-direction: column;
  }

  .workspace-section-switcher {
    display: flex;
    min-width: 0;
    width: 100%;
  }

  .workspace-page .nav-tabs {
    display: none !important;
  }

  .workspace-toolbar-actions {
    display: grid;
    width: 100%;
  }

  .workspace-toolbar-actions .btn {
    width: 100%;
  }

  .workspace-page .filter-buttons-col {
    justify-content: stretch;
    width: 100%;
  }

  .workspace-page .filter-buttons-col .btn {
    flex: 1 1 100%;
  }

  #documents-table,
  #group-documents-table,
  #prompts-table,
  #group-prompts-table,
  #agents-table,
  #group-agents-table,
  #plugins-table,
  #group-plugins-table {
    table-layout: auto !important;
  }

  #documents-table thead,
  #group-documents-table thead,
  #prompts-table thead,
  #group-prompts-table thead,
  #agents-table thead,
  #group-agents-table thead,
  #plugins-table thead,
  #group-plugins-table thead {
    display: none;
  }

  #documents-table,
  #group-documents-table,
  #prompts-table,
  #group-prompts-table,
  #agents-table,
  #group-agents-table,
  #plugins-table,
  #group-plugins-table,
  #documents-table tbody,
  #group-documents-table tbody,
  #prompts-table tbody,
  #group-prompts-table tbody,
  #agents-table tbody,
  #group-agents-table tbody,
  #plugins-table tbody,
  #group-plugins-table tbody {
    display: block;
    width: 100%;
  }

  #documents-table tr.document-row,
  #group-documents-table tr.document-row,
  #prompts-table tbody tr,
  #group-prompts-table tbody tr,
  #agents-table tbody tr,
  #group-agents-table tbody tr,
  #plugins-table tbody tr,
  #group-plugins-table tbody tr {
    background: var(--bs-body-bg, #fff);
    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 0.9rem;
    box-shadow: 0 0.35rem 1rem rgba(15, 23, 42, 0.06);
    display: block;
    margin-bottom: 0.85rem;
    overflow: hidden;
    padding: 0.85rem 0.95rem;
  }

  #documents-table tr.document-row td,
  #group-documents-table tr.document-row td,
  #prompts-table tbody tr td,
  #group-prompts-table tbody tr td,
  #agents-table tbody tr td,
  #group-agents-table tbody tr td,
  #plugins-table tbody tr td,
  #group-plugins-table tbody tr td {
    border: 0;
    display: block;
    max-width: none !important;
    overflow: visible !important;
    padding: 0.2rem 0;
    text-align: left !important;
    white-space: normal !important;
    width: 100% !important;
  }

  #documents-table tr.document-row td::before,
  #group-documents-table tr.document-row td::before,
  #prompts-table tbody tr td::before,
  #group-prompts-table tbody tr td::before,
  #agents-table tbody tr td::before,
  #group-agents-table tbody tr td::before,
  #plugins-table tbody tr td::before,
  #group-plugins-table tbody tr td::before {
    color: var(--bs-secondary-color, #6c757d);
    display: block;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    margin-bottom: 0.15rem;
    text-transform: uppercase;
  }

  #documents-table tr.document-row td:nth-child(1)::before,
  #group-documents-table tr.document-row td:nth-child(1)::before {
    content: "Status";
  }

  #documents-table tr.document-row td:nth-child(2)::before,
  #group-documents-table tr.document-row td:nth-child(2)::before {
    content: "File";
  }

  #documents-table tr.document-row td:nth-child(3)::before,
  #group-documents-table tr.document-row td:nth-child(3)::before {
    content: "Title";
  }

  #documents-table tr.document-row td:nth-child(4)::before,
  #group-documents-table tr.document-row td:nth-child(4)::before {
    content: "Actions";
  }

  #documents-table tr.document-row td:nth-child(4),
  #group-documents-table tr.document-row td:nth-child(4) {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 0.35rem;
    padding-top: 0.55rem;
  }

  #documents-table tr.document-row td:nth-child(4) .btn,
  #group-documents-table tr.document-row td:nth-child(4) .btn {
    flex: 1 1 8rem;
    justify-content: center;
  }

  #documents-table tr.document-row td:nth-child(4) .action-dropdown,
  #group-documents-table tr.document-row td:nth-child(4) .action-dropdown {
    margin-left: auto;
  }

  #documents-table tr.document-details-row,
  #documents-table tr.document-status-row,
  #group-documents-table tr.document-details-row,
  #group-documents-table tr.document-status-row {
    display: block;
    margin-bottom: 0.85rem;
    margin-top: -0.55rem;
  }

  #documents-table tr.document-details-row td,
  #documents-table tr.document-status-row td,
  #group-documents-table tr.document-details-row td,
  #group-documents-table tr.document-status-row td {
    background: color-mix(in srgb, var(--bs-body-bg, #fff) 94%, var(--bs-primary, #0d6efd) 6%);
    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 0 0 0.9rem 0.9rem;
    display: block;
    padding: 0.85rem 0.95rem;
    width: 100%;
  }

  #prompts-table tbody tr td:nth-child(1)::before,
  #group-prompts-table tbody tr td:nth-child(1)::before,
  #agents-table tbody tr td:nth-child(1)::before,
  #group-agents-table tbody tr td:nth-child(1)::before,
  #plugins-table tbody tr td:nth-child(1)::before,
  #group-plugins-table tbody tr td:nth-child(1)::before {
    content: "Name";
  }

  #prompts-table tbody tr td:nth-child(2)::before,
  #group-prompts-table tbody tr td:nth-child(2)::before,
  #agents-table tbody tr td:nth-child(2)::before,
  #group-agents-table tbody tr td:nth-child(2)::before,
  #plugins-table tbody tr td:nth-child(2)::before,
  #group-plugins-table tbody tr td:nth-child(2)::before {
    content: "Details";
  }

  #agents-table tbody tr td:nth-child(3)::before,
  #group-agents-table tbody tr td:nth-child(3)::before,
  #plugins-table tbody tr td:nth-child(3)::before,
  #group-plugins-table tbody tr td:nth-child(3)::before {
    content: "Actions";
  }

  #agents-table tbody tr td:nth-child(3),
  #group-agents-table tbody tr td:nth-child(3),
  #plugins-table tbody tr td:nth-child(3),
  #group-plugins-table tbody tr td:nth-child(3),
  #prompts-table tbody tr td:nth-child(2),
  #group-prompts-table tbody tr td:nth-child(2) {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 0.35rem;
    padding-top: 0.45rem;
  }

  #agents-table tbody tr td:nth-child(3) .btn,
  #group-agents-table tbody tr td:nth-child(3) .btn,
  #plugins-table tbody tr td:nth-child(3) .btn,
  #group-plugins-table tbody tr td:nth-child(3) .btn,
  #prompts-table tbody tr td:nth-child(2) .btn,
  #group-prompts-table tbody tr td:nth-child(2) .btn {
    flex: 1 1 7rem;
    justify-content: center;
  }

  #agents-table-body,
  #group-agents-table-body,
  #plugins-table-body,
  #group-plugins-table-body {
    min-height: 0;
  }
}
*** Add File: c:\Repos\simplechatmsft\application\single_app\static\js\workspace_section_switcher.js
// workspace_section_switcher.js

(function initializeWorkspaceSectionSwitchers() {
  function getTabButtons(tabListSelector) {
    if (!tabListSelector) {
      return [];
    }

    return Array.from(document.querySelectorAll(`${tabListSelector} button[data-bs-toggle="tab"]`));
  }

  function syncSelectWithActiveTab(selectElement, tabButtons) {
    const activeButton = tabButtons.find((button) => button.classList.contains('active'));
    if (activeButton) {
      selectElement.value = activeButton.id;
    }
  }

  function initializeSwitcher(switcherElement) {
    const selectElement = switcherElement.querySelector('[data-workspace-section-select]');
    const tabButtons = getTabButtons(switcherElement.dataset.tabList);
    if (!selectElement || !tabButtons.length) {
      return;
    }

    selectElement.addEventListener('change', (event) => {
      const targetButton = document.getElementById(event.target.value);
      if (!targetButton) {
        return;
      }

      if (typeof bootstrap !== 'undefined' && bootstrap.Tab) {
        bootstrap.Tab.getOrCreateInstance(targetButton).show();
      } else {
        targetButton.click();
      }
    });

    tabButtons.forEach((button) => {
      button.addEventListener('shown.bs.tab', () => {
        syncSelectWithActiveTab(selectElement, tabButtons);
      });
    });

    syncSelectWithActiveTab(selectElement, tabButtons);
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-workspace-switcher]').forEach((switcherElement) => {
      initializeSwitcher(switcherElement);
    });
  });
})();
