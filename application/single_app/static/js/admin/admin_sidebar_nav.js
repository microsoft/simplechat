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
    
    if (adminToggle) {
        adminToggle.addEventListener('click', function() {
            const isCollapsed = adminSection.style.display === 'none';
            adminSection.style.display = isCollapsed ? 'block' : 'none';
            adminCaret.classList.toggle('rotate-180', !isCollapsed);
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
    
    // Set the initial active tab (General)
    const firstTab = document.querySelector('.admin-nav-tab[data-tab="general"]');
    if (firstTab) {
        firstTab.classList.add('active');
        showAdminTab('general');
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
    }
    
    // Update the hash in URL for deep linking
    window.location.hash = tabId;
}

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
        'system-settings-section': 'system-settings-section',
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
`;
document.head.appendChild(style);