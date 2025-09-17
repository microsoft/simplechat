// Workspace Sidebar Navigation
document.addEventListener('DOMContentLoaded', function() {
    console.log('Workspace sidebar navigation script loaded');
    // Initialize workspace sidebar navigation for both personal and group workspaces
    initWorkspaceSidebarNav();
});

function initWorkspaceSidebarNav() {
    console.log('Initializing workspace sidebar navigation');
    
    // Set up workspace sub-menu toggles
    const toggles = document.querySelectorAll('.workspace-nav-toggle');
    console.log('Found workspace toggles:', toggles.length);
    
    toggles.forEach(toggle => {
        console.log('Setting up toggle for:', toggle.getAttribute('data-target'));
        toggle.addEventListener('click', function(e) {
            e.preventDefault();
            console.log('Toggle clicked:', this.getAttribute('data-target'));
            
            const targetId = this.getAttribute('data-target');
            const submenu = document.getElementById(targetId);
            const caret = this.querySelector('.workspace-caret');
            
            console.log('Submenu found:', !!submenu);
            
            if (submenu) {
                const isVisible = submenu.style.display !== 'none';
                console.log('Current visibility:', isVisible);
                
                // Close all other workspace submenus first
                document.querySelectorAll('[id$="-workspace-submenu"]').forEach(menu => {
                    if (menu !== submenu) {
                        menu.style.display = 'none';
                        // Reset carets for other menus
                        const otherToggle = document.querySelector(`[data-target="${menu.id}"]`);
                        if (otherToggle) {
                            const otherCaret = otherToggle.querySelector('.workspace-caret');
                            if (otherCaret) {
                                otherCaret.classList.remove('rotate-90');
                            }
                        }
                    }
                });
                
                // Toggle the clicked submenu
                submenu.style.display = isVisible ? 'none' : 'block';
                console.log('New visibility:', submenu.style.display);
                
                if (caret) {
                    caret.classList.toggle('rotate-90', !isVisible);
                }
            }
        });
    });
    
    // Set up tab navigation for workspace tabs
    const workspaceTabs = document.querySelectorAll('.workspace-nav-tab');
    console.log('Found workspace tabs:', workspaceTabs.length);
    
    workspaceTabs.forEach(tabLink => {
        tabLink.addEventListener('click', function(e) {
            e.preventDefault();
            const tabId = this.getAttribute('data-tab');
            console.log('Tab clicked:', tabId);
            showWorkspaceTab(tabId);
            
            // Update active state within the same submenu
            const parentSubmenu = this.closest('[id$="-workspace-submenu"]');
            if (parentSubmenu) {
                parentSubmenu.querySelectorAll('.workspace-nav-tab').forEach(link => {
                    link.classList.remove('active');
                });
            }
            this.classList.add('active');
        });
    });
    
    // Auto-expand the relevant workspace submenu if we're on a workspace page
    if (window.location.pathname.includes('/workspace')) {
        console.log('On workspace page, auto-expanding personal submenu');
        const personalSubmenu = document.getElementById('personal-workspace-submenu');
        const personalToggle = document.querySelector('[data-target="personal-workspace-submenu"]');
        
        if (personalSubmenu && personalToggle) {
            personalSubmenu.style.display = 'block';
            const caret = personalToggle.querySelector('.workspace-caret');
            if (caret) {
                caret.classList.add('rotate-90');
            }
            
            // Set the first tab as active
            const firstTab = personalSubmenu.querySelector('.workspace-nav-tab');
            if (firstTab) {
                firstTab.classList.add('active');
            }
        }
    } else if (window.location.pathname.includes('/group_workspaces')) {
        console.log('On group workspace page, auto-expanding group submenu');
        const groupSubmenu = document.getElementById('group-workspace-submenu');
        const groupToggle = document.querySelector('[data-target="group-workspace-submenu"]');
        
        if (groupSubmenu && groupToggle) {
            groupSubmenu.style.display = 'block';
            const caret = groupToggle.querySelector('.workspace-caret');
            if (caret) {
                caret.classList.add('rotate-90');
            }
            
            // Set the first tab as active
            const firstTab = groupSubmenu.querySelector('.workspace-nav-tab');
            if (firstTab) {
                firstTab.classList.add('active');
            }
        }
    }
}

function showWorkspaceTab(tabId) {
    // Find the corresponding Bootstrap tab button
    const topTabBtn = document.getElementById(tabId + '-btn');
    
    if (topTabBtn) {
        // Trigger the Bootstrap tab functionality by simulating a click
        // This will handle all the existing event listeners and content loading
        topTabBtn.click();
    } else {
        // Fallback: manually handle tab switching if button not found
        // Hide all tab panes
        const tabPanes = document.querySelectorAll('.tab-pane');
        tabPanes.forEach(pane => {
            pane.classList.remove('show', 'active');
        });
        
        // Show the selected tab pane
        const targetPane = document.getElementById(tabId);
        if (targetPane) {
            targetPane.classList.add('show', 'active');
        }
    }
}

// Add CSS for workspace navigation styling
const workspaceStyle = document.createElement('style');
workspaceStyle.textContent = `
    .workspace-nav-tab.active {
        background-color: rgba(13, 110, 253, 0.1);
        color: #0d6efd;
    }
    .workspace-nav-tab:hover {
        background-color: rgba(0, 0, 0, 0.05);
    }
    .workspace-nav-toggle:hover {
        background-color: rgba(0, 0, 0, 0.05);
    }
    .rotate-90 {
        transform: rotate(90deg);
    }
    .workspace-caret {
        transition: transform 0.2s ease;
    }
`;
document.head.appendChild(workspaceStyle);