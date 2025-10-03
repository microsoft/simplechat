/**
 * Sidebar Functionality
 * Handles sidebar interactions, collapsing, and responsive behavior
 */

(function() {
  'use strict';

  // Sidebar state management
  let sidebarState = {
    expanded: true,
    mobile: false
  };

  // Check if we're on mobile
  function isMobile() {
    return window.innerWidth <= 768;
  }

  // Update sidebar state
  function updateSidebarState() {
    sidebarState.mobile = isMobile();
    
    if (sidebarState.mobile) {
      // On mobile, sidebar should be collapsed by default
      const sidebar = document.getElementById('sidebar-nav');
      if (sidebar && !sidebar.classList.contains('sidebar-collapsed')) {
        sidebarState.expanded = false;
      }
    }
  }

  // Toggle collapsible sections
  function initCollapsibleSections() {
    // Sections toggle
    const sectionsToggle = document.getElementById('sections-toggle');
    const sectionsList = document.getElementById('sections-list');
    const sectionsCaret = document.getElementById('sections-caret');
    
    if (sectionsToggle && sectionsList && sectionsCaret) {
      let sectionsCollapsed = false;
      sectionsToggle.addEventListener('click', function() {
        sectionsCollapsed = !sectionsCollapsed;
        sectionsList.style.display = sectionsCollapsed ? 'none' : '';
        sectionsCaret.style.transform = sectionsCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
      });
    }

    // External links toggle
    const externalLinksToggle = document.getElementById('external-links-toggle');
    const externalLinksSection = document.getElementById('external-links-section');
    const externalLinksCaret = document.getElementById('external-links-caret');
    
    if (externalLinksToggle && externalLinksSection && externalLinksCaret) {
      let externalLinksCollapsed = false;
      externalLinksToggle.addEventListener('click', function() {
        externalLinksCollapsed = !externalLinksCollapsed;
        externalLinksSection.style.display = externalLinksCollapsed ? 'none' : '';
        externalLinksCaret.style.transform = externalLinksCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
      });
    }

    // Section submenus
    const sectionToggles = document.querySelectorAll('.section-nav-toggle');
    sectionToggles.forEach(function(toggle) {
      toggle.addEventListener('click', function(e) {
        e.preventDefault();
        const targetId = toggle.getAttribute('data-target');
        const submenu = document.getElementById(targetId);
        const caret = toggle.querySelector('.section-caret');
        
        if (submenu && caret) {
          const isHidden = submenu.style.display === 'none' || submenu.style.display === '';
          submenu.style.display = isHidden ? 'block' : 'none';
          caret.style.transform = isHidden ? 'rotate(90deg)' : 'rotate(0deg)';
        }
      });
    });
  }

  // Handle responsive behavior
  function handleResize() {
    updateSidebarState();
    
    const sidebar = document.getElementById('sidebar-nav');
    const mainContent = document.getElementById('main-content');
    
    if (!sidebar || !mainContent) return;

    if (isMobile()) {
      // On mobile, always collapse sidebar and remove padding
      sidebar.classList.add('sidebar-collapsed');
      sidebar.classList.remove('sidebar-expanded');
      mainContent.classList.remove('sidebar-padding');
      document.body.classList.add('sidebar-collapsed');
    } else if (sidebarState.expanded) {
      // On desktop, restore expanded state if it was expanded
      sidebar.classList.remove('sidebar-collapsed');
      sidebar.classList.add('sidebar-expanded');
      mainContent.classList.add('sidebar-padding');
      document.body.classList.remove('sidebar-collapsed');
    }
  }

  // Auto-expand current section
  function autoExpandCurrentSection() {
    // Find the current page in the sidebar and expand its parent section
    const currentLinks = document.querySelectorAll('#sidebar-nav .nav-link.active, #sidebar-nav .dropdown-item.active');
    
    currentLinks.forEach(function(link) {
      let parentSubmenu = link.closest('ul[id$="-submenu"]');
      if (parentSubmenu) {
        const submenuId = parentSubmenu.id;
        const toggleElement = document.querySelector(`[data-target="${submenuId}"]`);
        const caret = toggleElement ? toggleElement.querySelector('.section-caret') : null;
        
        if (toggleElement && caret) {
          parentSubmenu.style.display = 'block';
          caret.style.transform = 'rotate(90deg)';
        }
      }
    });
  }

  // Initialize sidebar functionality
  function initSidebar() {
    updateSidebarState();
    initCollapsibleSections();
    autoExpandCurrentSection();
    
    // Handle window resize
    let resizeTimer;
    window.addEventListener('resize', function() {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(handleResize, 250);
    });
    
    // Initial responsive setup
    handleResize();
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSidebar);
  } else {
    initSidebar();
  }

  // Expose utilities globally
  window.SimpleChat = window.SimpleChat || {};
  window.SimpleChat.Sidebar = {
    getSidebarState: () => ({ ...sidebarState }),
    updateSidebarState,
    isMobile
  };

})();