// Workspace Sidebar Navigation
document.addEventListener('DOMContentLoaded', function() {
    console.log('Workspace sidebar navigation script loaded');
    // Initialize workspace sidebar navigation for both personal and group workspaces
    initWorkspaceSidebarNav();
    
    // Also initialize after a slight delay to handle any dynamic content loading
    setTimeout(initWorkspaceSidebarNav, 100);
    
    // Add a debug function to inspect workspace navigation
    window.debugWorkspaceNav = function() {
        console.log('=== WORKSPACE NAVIGATION DEBUG ===');
        const personalSubmenu = document.getElementById('personal-workspace-submenu');
        const groupSubmenu = document.getElementById('group-workspace-submenu');
        const personalToggle = document.querySelector('[data-target="personal-workspace-submenu"]');
        const groupToggle = document.querySelector('[data-target="group-workspace-submenu"]');
        
        console.log('Personal submenu:', personalSubmenu);
        if (personalSubmenu) {
            console.log('Personal submenu display:', personalSubmenu.style.display);
            console.log('Personal submenu visibility:', personalSubmenu.style.visibility);
            console.log('Personal submenu computed style:', window.getComputedStyle(personalSubmenu).display);
        }
        
        console.log('Group submenu:', groupSubmenu);
        if (groupSubmenu) {
            console.log('Group submenu display:', groupSubmenu.style.display);
            console.log('Group submenu visibility:', groupSubmenu.style.visibility);
            console.log('Group submenu computed style:', window.getComputedStyle(groupSubmenu).display);
        }
        
        console.log('Personal toggle:', personalToggle);
        console.log('Group toggle:', groupToggle);
        console.log('Current path:', window.location.pathname);
        
        // Try to force show personal submenu
        if (personalSubmenu) {
            personalSubmenu.style.display = 'block';
            personalSubmenu.style.visibility = 'visible';
            personalSubmenu.style.opacity = '1';
            console.log('Forced personal submenu to show');
        }
        
        // Try to force show group submenu
        if (groupSubmenu) {
            groupSubmenu.style.display = 'block';
            groupSubmenu.style.visibility = 'visible';
            groupSubmenu.style.opacity = '1';
            console.log('Forced group submenu to show');
        }
    };
});

function initWorkspaceSidebarNav() {
    console.log('Initializing workspace sidebar navigation');
    
    // Set up workspace sub-menu toggles
    const toggles = document.querySelectorAll('.workspace-nav-toggle');
    console.log('Found workspace toggles:', toggles.length);
    
    // Also check if the submenu elements exist
    const personalSubmenu = document.getElementById('personal-workspace-submenu');
    const groupSubmenu = document.getElementById('group-workspace-submenu');
    console.log('Personal submenu found:', !!personalSubmenu);
    console.log('Group submenu found:', !!groupSubmenu);
    
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
                const isVisible = submenu.style.display !== 'none' && submenu.style.display !== '';
                console.log('Current visibility:', isVisible);
                console.log('Current display style:', submenu.style.display);
                
                // Close all other workspace submenus first
                document.querySelectorAll('[id$="-workspace-submenu"]').forEach(menu => {
                    if (menu !== submenu) {
                        menu.style.display = 'none';
                        menu.style.visibility = 'hidden';
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
                
                // Toggle the clicked submenu with more explicit visibility control
                if (isVisible) {
                    submenu.style.display = 'none';
                    submenu.style.visibility = 'hidden';
                } else {
                    submenu.style.display = 'block';
                    submenu.style.visibility = 'visible';
                    submenu.style.opacity = '1';
                }
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
        
        console.log('Personal submenu element:', personalSubmenu);
        console.log('Personal toggle element:', personalToggle);
        
        if (personalSubmenu && personalToggle) {
            personalSubmenu.style.display = 'block';
            personalSubmenu.style.visibility = 'visible';
            personalSubmenu.style.opacity = '1';
            console.log('Personal submenu expanded');
            
            const caret = personalToggle.querySelector('.workspace-caret');
            if (caret) {
                caret.classList.add('rotate-90');
                console.log('Personal caret rotated');
            }
            
            // Set the first tab as active
            const firstTab = personalSubmenu.querySelector('.workspace-nav-tab');
            if (firstTab) {
                firstTab.classList.add('active');
                console.log('First personal tab set as active');
            }
        } else {
            console.log('Personal submenu or toggle not found!');
        }
    } else if (window.location.pathname.includes('/group_workspaces')) {
        console.log('On group workspace page, auto-expanding group submenu');
        const groupSubmenu = document.getElementById('group-workspace-submenu');
        const groupToggle = document.querySelector('[data-target="group-workspace-submenu"]');
        
        console.log('Group submenu element:', groupSubmenu);
        console.log('Group toggle element:', groupToggle);
        
        if (groupSubmenu && groupToggle) {
            groupSubmenu.style.display = 'block';
            groupSubmenu.style.visibility = 'visible';
            groupSubmenu.style.opacity = '1';
            console.log('Group submenu expanded');
            
            const caret = groupToggle.querySelector('.workspace-caret');
            if (caret) {
                caret.classList.add('rotate-90');
                console.log('Group caret rotated');
            }
            
            // Set the first tab as active
            const firstTab = groupSubmenu.querySelector('.workspace-nav-tab');
            if (firstTab) {
                firstTab.classList.add('active');
                console.log('First group tab set as active');
            }
        } else {
            console.log('Group submenu or toggle not found!');
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
    /* Ensure workspace submenus are properly displayed when visible */
    ul[id$="-workspace-submenu"] {
        position: relative;
        z-index: 10;
        background: inherit;
    }
    ul[id$="-workspace-submenu"] li {
        list-style: none;
    }
    ul[id$="-workspace-submenu"] .nav-link {
        padding: 0.375rem 0.75rem;
        margin-bottom: 0.125rem;
        border-radius: 0.25rem;
        transition: all 0.15s ease-in-out;
    }
    /* Override any potential conflicting display rules */
    ul[id$="-workspace-submenu"][style*="display: block"] {
        display: block !important;
        visibility: visible !important;
        opacity: 1 !important;
    }
`;
document.head.appendChild(workspaceStyle);