// Admin Sidebar Navigation
document.addEventListener('DOMContentLoaded', function() {
    // Only initialize if we're on admin settings page with sidebar nav
    if (!document.getElementById('admin-settings-toggle')) return;
    
    // Initialize admin settings sidebar
    initAdminSidebarNav();
});

function initAdminSidebarNav() {
    // Set up collapsible admin settings section
    const adminToggle = document.getElementById('admin-settings-toggle');
    const adminSection = document.getElementById('admin-settings-section');
    const adminCaret = document.getElementById('admin-settings-caret');
    const adminSearchBtn = document.getElementById('admin-search-btn');
    const adminSearchContainer = document.getElementById('admin-search-container');
    const adminSearchInput = document.getElementById('admin-search-input');
    const adminSearchClear = document.getElementById('admin-search-clear');
    
    if (adminToggle) {
        adminToggle.addEventListener('click', function(e) {
            // Don't toggle if clicking on search button
            if (e.target.closest('#admin-search-btn')) {
                return;
            }
            
            const isCollapsed = adminSection.style.display === 'none';
            adminSection.style.display = isCollapsed ? 'block' : 'none';
            adminCaret.classList.toggle('rotate-180', !isCollapsed);
        });
    }
    
    // Set up admin search functionality
    if (adminSearchBtn) {
        adminSearchBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            const isVisible = adminSearchContainer.style.display !== 'none';
            adminSearchContainer.style.display = isVisible ? 'none' : 'block';
            
            if (!isVisible) {
                // Ensure admin section is expanded when search is opened
                adminSection.style.display = 'block';
                adminCaret.classList.add('rotate-180');
                
                // Focus on search input
                setTimeout(() => adminSearchInput.focus(), 100);
            } else {
                // Clear search when hiding
                clearAdminSearch();
            }
        });
    }
    
    // Set up search input functionality
    if (adminSearchInput) {
        adminSearchInput.addEventListener('input', function() {
            filterAdminSections(this.value);
        });
        
        adminSearchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                clearAdminSearch();
                adminSearchContainer.style.display = 'none';
            }
        });
    }
    
    // Set up clear button
    if (adminSearchClear) {
        adminSearchClear.addEventListener('click', function() {
            clearAdminSearch();
        });
    }
    
    // Set up tab navigation
    document.querySelectorAll('.admin-nav-tab').forEach(tabLink => {
        tabLink.addEventListener('click', function(e) {
            e.preventDefault();
            const tabId = this.getAttribute('data-tab');
            showAdminTab(tabId);
            
            // Update active state for main tabs
            document.querySelectorAll('.admin-nav-tab').forEach(link => {
                link.classList.remove('active');
            });
            this.classList.add('active');
            
            // Clear section active states
            document.querySelectorAll('.admin-nav-section').forEach(link => {
                link.classList.remove('active');
            });
            
            // Toggle submenu if it exists
            const submenu = document.getElementById(tabId + '-submenu');
            if (submenu) {
                const isVisible = submenu.style.display !== 'none';
                
                // Close all other submenus first
                document.querySelectorAll('[id$="-submenu"]').forEach(menu => {
                    if (menu !== submenu) {
                        menu.style.display = 'none';
                    }
                });
                
                // Toggle the current submenu
                submenu.style.display = isVisible ? 'none' : 'block';
            } else {
                // Close all submenus if this tab doesn't have one
                document.querySelectorAll('[id$="-submenu"]').forEach(menu => {
                    menu.style.display = 'none';
                });
            }
        });
    });
    
    // Set up section navigation
    document.querySelectorAll('.admin-nav-section').forEach(sectionLink => {
        sectionLink.addEventListener('click', function(e) {
            e.preventDefault();
            const tabId = this.getAttribute('data-tab');
            const sectionId = this.getAttribute('data-section');
            showAdminTab(tabId);
            scrollToSection(sectionId);
            
            // Update active state
            document.querySelectorAll('.admin-nav-section').forEach(link => {
                link.classList.remove('active');
            });
            this.classList.add('active');
        });
    });
    
    // Set the initial active tab (General) - but only if no tab is already active
    const activeTab = document.querySelector('.admin-nav-tab.active, .admin-nav-section.active');
    if (!activeTab) {
        const firstTab = document.querySelector('.admin-nav-tab[data-tab="general"]');
        if (firstTab) {
            firstTab.classList.add('active');
            showAdminTab('general');
        }
    } else {
        console.log('initAdminSidebarNav - Found existing active tab, preserving current state:', activeTab.getAttribute('data-tab'));
    }
}

function showAdminTab(tabId) {    
    // Hide all tab panes
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.remove('show', 'active');
    });
    
    // Show the selected tab pane
    const targetTab = document.getElementById(tabId);
    if (targetTab) {
        targetTab.classList.add('show', 'active');
    } else {
        console.warn('❌ showAdminTab - Could not find tab pane with ID:', tabId);
    }
    
    // Update the hash in URL for deep linking
    window.location.hash = tabId;
}

// Make function globally available
window.showAdminTab = showAdminTab;

function scrollToSection(sectionId) {
    // Map section IDs to actual element IDs/classes in the admin settings
    const sectionMap = {
        'gpt-config': 'gpt-configuration',
        'embeddings-config': 'embeddings-configuration', 
        'image-config': 'image-generation-configuration',
        'agents-config': 'agents-configuration',
        'actions-config': 'actions-configuration',
        // General tab sections
        'branding-section': 'branding-section',
        'home-page-text-section': 'home-page-text-section',
        'appearance-section': 'appearance-section',
        'classification-banner-section': 'classification-banner-section',
        'external-links-section': 'external-links-section',
        'health-check-section': 'health-check-section',
        'system-settings-section': 'system-settings-section',
        'control-center-admin-section': 'control-center-admin-section',
        // Logging tab sections
        'application-insights-section': 'application-insights-section',
        'debug-logging-section': 'debug-logging-section',
        'file-processing-logs-section': 'file-processing-logs-section',
        // Scale tab sections
        'redis-cache-section': 'redis-cache-section',
        'front-door-section': 'front-door-section',
        // Workspaces tab sections
        'personal-workspaces-section': 'personal-workspaces-section',
        'group-workspaces-section': 'group-workspaces-section',
        'public-workspaces-section': 'public-workspaces-section',
        'file-sharing-section': 'file-sharing-section',
        'metadata-extraction-section': 'metadata-extraction-section',
        'document-classification-section': 'document-classification-section',
        // Citations tab sections
        'standard-citations-section': 'standard-citations-section',
        'enhanced-citations-section': 'enhanced-citations-section',
        // Safety tab sections
        'content-safety-section': 'content-safety-section',
        'user-feedback-section': 'user-feedback-section',
        'permissions-section': 'permissions-section',
        'conversation-archiving-section': 'conversation-archiving-section',
        // Search & Extract tab sections
        'azure-ai-search-section': 'azure-ai-search-section',
        'document-intelligence-section': 'document-intelligence-section',
        'multimedia-support-section': 'multimedia-support-section'
    };
    
    const targetElementId = sectionMap[sectionId] || sectionId;
    const targetElement = document.getElementById(targetElementId) || 
                          document.querySelector(`[class*="${targetElementId}"]`) ||
                          document.querySelector(`h5:contains("${targetElementId.replace('-', ' ')}")`);
    
    if (targetElement) {
        setTimeout(() => {
            targetElement.scrollIntoView({ 
                behavior: 'smooth', 
                block: 'start' 
            });
        }, 100);
    }
}

// Handle initial hash navigation
window.addEventListener('load', function() {
    if (window.location.hash && document.getElementById('admin-settings-toggle')) {
        const tabId = window.location.hash.substring(1);
        showAdminTab(tabId);
        
        // Set active nav link
        const navLink = document.querySelector(`.admin-nav-tab[data-tab="${tabId}"]`);
        if (navLink) {
            document.querySelectorAll('.admin-nav-tab').forEach(link => {
                link.classList.remove('active');
            });
            navLink.classList.add('active');
        }
    }
});

// CSS for rotation animation
const style = document.createElement('style');
style.textContent = `
    .rotate-180 {
        transform: rotate(180deg);
    }
    .admin-nav-tab.active,
    .admin-nav-section.active {
        background-color: rgba(13, 110, 253, 0.1);
        color: #0d6efd;
    }
    .admin-nav-tab:hover,
    .admin-nav-section:hover {
        background-color: rgba(0, 0, 0, 0.05);
    }
    .admin-search-highlight {
        background-color: rgba(255, 193, 7, 0.3) !important;
        font-weight: 500;
    }
    .admin-search-hidden {
        display: none !important;
    }
`;
document.head.appendChild(style);

// Admin search functionality
function filterAdminSections(searchTerm) {
    const normalizedSearch = searchTerm.toLowerCase().trim();
    
    if (!normalizedSearch) {
        // Show all sections if search is empty
        showAllAdminSections();
        return;
    }
    
    let hasVisibleSections = false;
    
    // Get all admin nav items
    const allTabs = document.querySelectorAll('.admin-nav-tab');
    const allSections = document.querySelectorAll('.admin-nav-section');
    
    // Hide all sections and tabs initially
    allTabs.forEach(tab => {
        tab.closest('li').classList.add('admin-search-hidden');
        // Hide submenu
        const submenu = document.getElementById(tab.getAttribute('data-tab') + '-submenu');
        if (submenu) {
            submenu.style.display = 'none';
        }
    });
    
    allSections.forEach(section => {
        section.closest('li').classList.add('admin-search-hidden');
        section.classList.remove('admin-search-highlight');
    });
    
    // Search through tabs and sections
    allTabs.forEach(tab => {
        const tabText = tab.querySelector('.nav-text').textContent.toLowerCase();
        const tabId = tab.getAttribute('data-tab');
        let tabHasMatch = false;
        
        // Check if tab name matches
        if (tabText.includes(normalizedSearch)) {
            tab.closest('li').classList.remove('admin-search-hidden');
            tab.classList.add('admin-search-highlight');
            tabHasMatch = true;
            hasVisibleSections = true;
            
            // Show submenu for matched tab
            const submenu = document.getElementById(tabId + '-submenu');
            if (submenu) {
                submenu.style.display = 'block';
                // Show all sections under this tab
                submenu.querySelectorAll('.admin-nav-section').forEach(section => {
                    section.closest('li').classList.remove('admin-search-hidden');
                });
            }
        }
        
        // Check sections under this tab
        const sections = document.querySelectorAll(`.admin-nav-section[data-tab="${tabId}"]`);
        let sectionHasMatch = false;
        
        sections.forEach(section => {
            const sectionText = section.querySelector('.nav-text').textContent.toLowerCase();
            
            if (sectionText.includes(normalizedSearch)) {
                // Show the section
                section.closest('li').classList.remove('admin-search-hidden');
                section.classList.add('admin-search-highlight');
                sectionHasMatch = true;
                hasVisibleSections = true;
                
                // Show the parent tab
                tab.closest('li').classList.remove('admin-search-hidden');
                
                // Show the submenu
                const submenu = document.getElementById(tabId + '-submenu');
                if (submenu) {
                    submenu.style.display = 'block';
                }
            }
        });
        
        // If tab has matching sections but doesn't match itself, remove tab highlight
        if (sectionHasMatch && !tabHasMatch) {
            tab.classList.remove('admin-search-highlight');
        }
    });
    
    // Show "No results" message if nothing found
    showSearchResults(hasVisibleSections, normalizedSearch);
}

function showAllAdminSections() {
    // Remove all search-related classes and show all items
    document.querySelectorAll('.admin-nav-tab, .admin-nav-section').forEach(item => {
        item.closest('li').classList.remove('admin-search-hidden');
        item.classList.remove('admin-search-highlight');
    });
    
    // Hide all submenus (normal collapsed state)
    document.querySelectorAll('[id$="-submenu"]').forEach(submenu => {
        submenu.style.display = 'none';
    });
    
    // Remove search results message
    hideSearchResults();
}

function clearAdminSearch() {
    const searchInput = document.getElementById('admin-search-input');
    if (searchInput) {
        searchInput.value = '';
        showAllAdminSections();
    }
}

function showSearchResults(hasResults, searchTerm) {
    // Remove existing search results message
    hideSearchResults();
    
    if (!hasResults && searchTerm) {
        const adminSection = document.getElementById('admin-settings-section');
        const noResultsDiv = document.createElement('div');
        noResultsDiv.id = 'admin-search-no-results';
        noResultsDiv.className = 'px-3 py-2 text-muted text-center small';
        noResultsDiv.innerHTML = `
            <i class="bi bi-search me-1"></i>
            No settings found for "${searchTerm}"
        `;
        adminSection.appendChild(noResultsDiv);
    }
}

function hideSearchResults() {
    const noResults = document.getElementById('admin-search-no-results');
    if (noResults) {
        noResults.remove();
    }
}