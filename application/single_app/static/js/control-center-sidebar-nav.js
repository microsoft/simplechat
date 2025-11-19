// Control Center Sidebar Navigation
document.addEventListener('DOMContentLoaded', function() {
    // Only initialize if we're on control center page with sidebar nav
    if (!document.getElementById('control-center-toggle')) return;
    
    // Initialize control center sidebar
    initControlCenterSidebarNav();
});

function initControlCenterSidebarNav() {
    // Set up collapsible control center section
    const controlCenterToggle = document.getElementById('control-center-toggle');
    const controlCenterSection = document.getElementById('control-center-section');
    const controlCenterCaret = document.getElementById('control-center-caret');
    const controlCenterSearchBtn = document.getElementById('control-center-search-btn');
    const controlCenterSearchContainer = document.getElementById('control-center-search-container');
    const controlCenterSearchInput = document.getElementById('control-center-search-input');
    const controlCenterSearchClear = document.getElementById('control-center-search-clear');
    
    if (controlCenterToggle) {
        controlCenterToggle.addEventListener('click', function(e) {
            // Don't toggle if clicking on search button
            if (e.target.closest('#control-center-search-btn')) {
                return;
            }
            
            const isCollapsed = controlCenterSection.style.display === 'none';
            controlCenterSection.style.display = isCollapsed ? 'block' : 'none';
            controlCenterCaret.classList.toggle('rotate-180', !isCollapsed);
        });
    }
    
    // Set up control center search functionality
    if (controlCenterSearchBtn) {
        controlCenterSearchBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            const isVisible = controlCenterSearchContainer.style.display !== 'none';
            controlCenterSearchContainer.style.display = isVisible ? 'none' : 'block';
            
            if (!isVisible) {
                // Ensure control center section is expanded when search is opened
                controlCenterSection.style.display = 'block';
                controlCenterCaret.classList.add('rotate-180');
                
                // Focus on search input
                setTimeout(() => controlCenterSearchInput.focus(), 100);
            } else {
                // Clear search when hiding
                clearControlCenterSearch();
            }
        });
    }
    
    // Set up search input functionality
    if (controlCenterSearchInput) {
        controlCenterSearchInput.addEventListener('input', function() {
            filterControlCenterSections(this.value);
        });
        
        controlCenterSearchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                clearControlCenterSearch();
                controlCenterSearchContainer.style.display = 'none';
            }
        });
    }
    
    // Set up clear button
    if (controlCenterSearchClear) {
        controlCenterSearchClear.addEventListener('click', function() {
            clearControlCenterSearch();
        });
    }
    
    // Set up tab navigation
    document.querySelectorAll('.control-center-nav-tab').forEach(tabLink => {
        tabLink.addEventListener('click', function(e) {
            e.preventDefault();
            const tabId = this.getAttribute('data-tab');
            showControlCenterTab(tabId);
            
            // Update active state for main tabs
            document.querySelectorAll('.control-center-nav-tab').forEach(link => {
                link.classList.remove('active');
            });
            this.classList.add('active');
            
            // Clear section active states
            document.querySelectorAll('.control-center-nav-section').forEach(link => {
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
    document.querySelectorAll('.control-center-nav-section').forEach(sectionLink => {
        sectionLink.addEventListener('click', function(e) {
            e.preventDefault();
            const tabId = this.getAttribute('data-tab');
            const sectionId = this.getAttribute('data-section');
            showControlCenterTab(tabId);
            scrollToSection(sectionId);
            
            // Update active state
            document.querySelectorAll('.control-center-nav-section').forEach(link => {
                link.classList.remove('active');
            });
            this.classList.add('active');
        });
    });
    
    // Set the initial active tab (Dashboard) - but only if no tab is already active
    const activeTab = document.querySelector('.control-center-nav-tab.active, .control-center-nav-section.active');
    if (!activeTab) {
        const firstTab = document.querySelector('.control-center-nav-tab[data-tab="dashboard"]');
        if (firstTab) {
            firstTab.classList.add('active');
            showControlCenterTab('dashboard');
        }
    } else {
        console.log('initControlCenterSidebarNav - Found existing active tab, preserving current state:', activeTab.getAttribute('data-tab'));
    }
}

function showControlCenterTab(tabId) {    
    // Hide all tab panes
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.remove('show', 'active');
    });
    
    // Show the selected tab pane
    const targetPane = document.getElementById(tabId);
    if (targetPane) {
        targetPane.classList.add('show', 'active');
    }
    
    // Update Bootstrap tab buttons (if using top tabs instead of sidebar)
    const targetTabBtn = document.querySelector(`[data-bs-target="#${tabId}"]`);
    if (targetTabBtn) {
        // Remove active from all tab buttons
        document.querySelectorAll('[data-bs-toggle="tab"]').forEach(btn => {
            btn.classList.remove('active');
            btn.setAttribute('aria-selected', 'false');
        });
        
        // Activate the target tab button
        targetTabBtn.classList.add('active');
        targetTabBtn.setAttribute('aria-selected', 'true');
    }
    
    // Initialize tab-specific functionality if needed
    if (typeof window.initializeControlCenterTab === 'function') {
        window.initializeControlCenterTab(tabId);
    }
}

function scrollToSection(sectionId) {
    setTimeout(() => {
        const element = document.getElementById(sectionId);
        if (element) {
            element.scrollIntoView({ 
                behavior: 'smooth', 
                block: 'start',
                inline: 'nearest'
            });
            
            // Add highlight effect
            element.classList.add('highlight-section');
            setTimeout(() => {
                element.classList.remove('highlight-section');
            }, 2000);
        }
    }, 100);
}

function clearControlCenterSearch() {
    const searchInput = document.getElementById('control-center-search-input');
    if (searchInput) {
        searchInput.value = '';
        filterControlCenterSections('');
    }
}

function filterControlCenterSections(searchTerm) {
    const term = searchTerm.toLowerCase().trim();
    const allNavItems = document.querySelectorAll('#control-center-section .nav-item');
    
    allNavItems.forEach(item => {
        const link = item.querySelector('a');
        if (link) {
            const text = link.textContent.toLowerCase();
            const shouldShow = term === '' || text.includes(term);
            item.style.display = shouldShow ? '' : 'none';
        }
    });
    
    // If searching, expand all submenus to show matches
    if (term) {
        document.querySelectorAll('[id$="-submenu"]').forEach(submenu => {
            const hasVisibleItems = Array.from(submenu.querySelectorAll('.nav-item'))
                .some(item => item.style.display !== 'none');
            
            if (hasVisibleItems) {
                submenu.style.display = 'block';
            }
        });
    }
}

// Add CSS for highlight effect
if (!document.getElementById('control-center-sidebar-styles')) {
    const style = document.createElement('style');
    style.id = 'control-center-sidebar-styles';
    style.textContent = `
        .rotate-180 {
            transform: rotate(180deg);
        }
        
        .highlight-section {
            background-color: rgba(13, 110, 253, 0.1) !important;
            border-left: 4px solid #0d6efd !important;
            transition: all 0.3s ease;
        }
        
        .control-center-nav-tab.active,
        .control-center-nav-section.active {
            background-color: rgba(13, 110, 253, 0.1);
            color: #0d6efd;
            font-weight: 600;
        }
        
        .control-center-nav-tab:hover,
        .control-center-nav-section:hover {
            background-color: rgba(0, 0, 0, 0.05);
        }
    `;
    document.head.appendChild(style);
}