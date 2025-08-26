// Top Navigation Functionality

/**
 * Navigation-related utilities and event handlers
 * Handles general navigation behavior and interactions
 */

// Initialize top navigation functionality
document.addEventListener('DOMContentLoaded', () => {
  // Set up any top navigation specific event listeners
  console.log('Top navigation initialized');

  // Handle responsive navigation behavior
  handleResponsiveNavigation();

  // Set up dropdown behaviors
  setupDropdownBehaviors();
});

// Handle responsive navigation behavior
function handleResponsiveNavigation() {
  // Handle window resize for responsive navigation
  window.addEventListener('resize', function() {
    // Close any open mobile menus when resizing to larger screens
    if (window.innerWidth > 768) {
      const navbarCollapse = document.querySelector('.navbar-collapse');
      if (navbarCollapse && navbarCollapse.classList.contains('show')) {
        // Use Bootstrap's collapse method if available
        if (typeof bootstrap !== 'undefined' && bootstrap.Collapse) {
          const collapse = bootstrap.Collapse.getInstance(navbarCollapse);
          if (collapse) {
            collapse.hide();
          }
        }
      }
    }
  });
}

// Set up dropdown behaviors
function setupDropdownBehaviors() {
  // Handle dropdown menu accessibility
  document.querySelectorAll('.dropdown-toggle').forEach(dropdown => {
    dropdown.addEventListener('keydown', function(e) {
      // Handle keyboard navigation for dropdowns
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        if (typeof bootstrap !== 'undefined' && bootstrap.Dropdown) {
          const dropdownInstance = bootstrap.Dropdown.getOrCreateInstance(this);
          dropdownInstance.toggle();
        }
      }
    });
  });

  // Close dropdowns when clicking outside
  document.addEventListener('click', function(e) {
    if (!e.target.closest('.dropdown')) {
      document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
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
      // Fallback for manual toggle
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
