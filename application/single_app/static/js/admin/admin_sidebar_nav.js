// admin_sidebar_nav.js
// Admin Sidebar Navigation
document.addEventListener('DOMContentLoaded', function() {
    // The top-nav group pills exist only in the tab layout, so they are wired
    // independently of the sidebar.
    setupAdminGroupPills();

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
    
    if (adminToggle && !adminToggle.dataset.sidebarMenuKey) {
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
                if (typeof window.setPersistentSidebarMenuExpanded === 'function') {
                    window.setPersistentSidebarMenuExpanded('adminSettings', true);
                } else {
                    adminSection.classList.remove('d-none');
                    adminCaret.style.transform = 'rotate(0deg)';
                }
                
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
    
    // Set up group expand/collapse. Groups are the level above tabs, so a
    // collapsed group hides its tabs without affecting which tab is active.
    setupAdminGroupToggles();

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
    
    // Set the initial active tab - but only if no tab is already active.
    // Latest Features is deliberately excluded so it never opens by default.
    // The landing tab is whichever tab the nav map renders first rather than a
    // hardcoded id, so it stays correct as the information architecture moves.
    const activeTab = document.querySelector('.admin-nav-tab.active, .admin-nav-section.active');
    if (!activeTab) {
        const firstTab = document.querySelector('.admin-nav-tab[data-tab]');
        const firstTabId = firstTab ? firstTab.getAttribute('data-tab') : null;
        if (firstTabId) {
            firstTab.classList.add('active');
            showAdminTab(firstTabId);
        }
    } else {
        console.log('initAdminSidebarNav - Found existing active tab, preserving current state:', activeTab.getAttribute('data-tab'));
        syncAdminGroupSharedRegions(activeTab.getAttribute('data-tab'));
    }

    // Clicking a tab button directly does not go through showAdminTab, so the
    // shared regions are synced from Bootstrap's own event as well.
    document.querySelectorAll('button.nav-link[data-bs-target^="#"]').forEach(button => {
        button.addEventListener('shown.bs.tab', event => {
            const target = event.target.getAttribute('data-bs-target');
            if (target) {
                syncAdminGroupSharedRegions(target.slice(1));
            }
        });
    });
}

function setupAdminGroupToggles() {
    document.querySelectorAll('[data-admin-group-toggle]').forEach(toggle => {
        toggle.addEventListener('click', function (e) {
            e.preventDefault();
            const groupId = this.getAttribute('data-admin-group-toggle');
            setAdminGroupExpanded(groupId, !isAdminGroupExpanded(groupId), true);
        });
    });
}

/**
 * Wire the top-nav group pills, which filter the tab strip to one group.
 * Only relevant in the tab layout; the sidebar layout uses group headers.
 */
function setupAdminGroupPills() {
    const pills = document.querySelectorAll('[data-admin-group-pill]');
    if (!pills.length) {
        return;
    }

    pills.forEach(pill => {
        pill.addEventListener('click', function () {
            showAdminGroupTabs(this.getAttribute('data-admin-group-pill'), true);
        });
    });
}

/**
 * Show one group's tabs in the top strip.
 * @param {string} groupId Group to reveal.
 * @param {boolean} activateFirstTab Whether to open that group's first tab.
 */
function showAdminGroupTabs(groupId, activateFirstTab) {
    document.querySelectorAll('[data-admin-group-pill]').forEach(pill => {
        const selected = pill.getAttribute('data-admin-group-pill') === groupId;
        pill.classList.toggle('active', selected);
        pill.setAttribute('aria-selected', selected ? 'true' : 'false');
    });

    let firstTabButton = null;
    document.querySelectorAll('.admin-tab-item').forEach(item => {
        const inGroup = item.getAttribute('data-admin-group') === groupId;
        item.hidden = !inGroup;
        if (inGroup && !firstTabButton) {
            firstTabButton = item.querySelector('button[data-bs-target]');
        }
    });

    if (activateFirstTab && firstTabButton) {
        const target = firstTabButton.getAttribute('data-bs-target') || '';
        showAdminTab(target.replace('#', ''));
    }
}

/**
 * Reveal the group owning a tab in the top strip, so a deep link or a
 * cross-reference never activates a pane whose tab is filtered out of view.
 * @param {string} tabId Tab pane id.
 */
function revealAdminGroupPillForTab(tabId) {
    const item = document.querySelector(`.admin-tab-item [data-bs-target="#${tabId}"]`);
    const groupItem = item && item.closest('.admin-tab-item');
    if (!groupItem) {
        return;
    }

    const groupId = groupItem.getAttribute('data-admin-group');
    if (groupId && groupItem.hidden) {
        showAdminGroupTabs(groupId, false);
    }
}

function getAdminGroupElements(groupId) {
    return {
        toggle: document.querySelector(`[data-admin-group-toggle="${groupId}"]`),
        list: document.getElementById(`admin-group-${groupId}`),
    };
}

function isAdminGroupExpanded(groupId) {
    const { list } = getAdminGroupElements(groupId);
    return Boolean(list) && !list.classList.contains('d-none');
}

/**
 * Expand or collapse a nav group.
 * @param {string} groupId Group identifier.
 * @param {boolean} expanded Desired state.
 * @param {boolean} persist Whether to remember the state for this user.
 */
function setAdminGroupExpanded(groupId, expanded, persist) {
    const { toggle, list } = getAdminGroupElements(groupId);
    if (!toggle || !list) {
        return;
    }

    list.classList.toggle('d-none', !expanded);
    toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');

    const caret = toggle.querySelector('.admin-nav-group-caret');
    if (caret) {
        caret.classList.toggle('collapsed', !expanded);
    }

    if (persist && typeof window.setPersistentSidebarMenuExpanded === 'function') {
        window.setPersistentSidebarMenuExpanded(`adminGroup:${groupId}`, expanded);
    }
}

/**
 * Open the group that owns a tab, so activating a tab never leaves it hidden.
 * @param {string} tabId Tab pane id.
 */
function revealAdminGroupForTab(tabId) {
    const tabLink = document.querySelector(`.admin-nav-tab[data-tab="${tabId}"]`);
    const groupItem = tabLink && tabLink.closest('[data-admin-group]');
    if (!groupItem) {
        return;
    }

    const groupId = groupItem.getAttribute('data-admin-group');
    if (!isAdminGroupExpanded(groupId)) {
        setAdminGroupExpanded(groupId, true, true);
    }
}

// Tabs that existed before the information architecture rework, mapped to
// where their content now lives. Old bookmarks and links keep working.
const LEGACY_TAB_REDIRECTS = {
    'governance': 'feature-governance',
    'scale': 'redis-caching',
    'general': 'branding',
    'safety': 'access-roles',
    'security': 'secrets',
    'workspaces': 'workspace-types',
    'search-extract': 'web-research',
    'ai-models': 'model-endpoints',
    'data-management': 'backup',
};

function resolveAdminTabId(tabId) {
    return LEGACY_TAB_REDIRECTS[tabId] || tabId;
}

/**
 * Some groups share one set of controls across all of their tabs, such as the
 * single save button that serves every Backup & Recovery tab. Those controls
 * cannot be duplicated into each pane without repeating element ids, and they
 * cannot sit in one pane because the other tabs would lose them, so they live
 * outside the panes and are revealed only while their group is active.
 */
function syncAdminGroupSharedRegions(tabId) {
    const regions = document.querySelectorAll('[data-admin-group-shared]');
    if (!regions.length) {
        return;
    }

    // Only one of the two navigations is rendered at a time, so resolve the
    // owning group from whichever is present. Looking only at the top tab strip
    // would leave the region hidden for good in the sidebar layout.
    const tabButton = document.querySelector(`.admin-tab-item[data-admin-group] button[data-bs-target="#${tabId}"]`);
    let owner = tabButton ? tabButton.closest('[data-admin-group]') : null;
    if (!owner) {
        const sidebarLink = document.querySelector(`.admin-nav-tab[data-tab="${tabId}"]`);
        owner = sidebarLink ? sidebarLink.closest('[data-admin-group]') : null;
    }
    const activeGroup = owner ? owner.getAttribute('data-admin-group') : null;

    regions.forEach(region => {
        const ownerGroup = region.getAttribute('data-admin-group-shared');
        region.hidden = ownerGroup !== activeGroup;
    });
}

function showAdminTab(requestedTabId) {
    const tabId = resolveAdminTabId(requestedTabId);

    // Open the owning group first, in whichever layout is active, so
    // activating a tab never leaves it hidden behind a collapsed group header
    // or filtered out of the top strip.
    revealAdminGroupForTab(tabId);
    revealAdminGroupPillForTab(tabId);

    const bootstrapTabButton = document.querySelector(`button.nav-link[data-bs-target="#${tabId}"]`);
    if (bootstrapTabButton && typeof bootstrap !== 'undefined' && typeof bootstrap.Tab === 'function') {
        const tab = bootstrap.Tab.getOrCreateInstance(bootstrapTabButton);
        tab.show();
    } else {
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
    }
    
    // Update the hash in URL for deep linking
    window.location.hash = tabId;
    syncAdminGroupSharedRegions(tabId);
    if (typeof window.updateAdminSettingsSaveButtonState === 'function') {
        window.updateAdminSettingsSaveButtonState();
    }
}

// Make function globally available
window.showAdminTab = showAdminTab;

function scrollToSection(sectionId) {
    // Resolve a sidebar data-section value to the element it should scroll to.
    const sectionMap = {
        // Only genuine aliases belong here. Any sidebar data-section value
        // that already matches its element id resolves through the
        // `sectionMap[sectionId] || sectionId` fallback below.
        'gpt-config': 'gpt-configuration',
        'embeddings-config': 'embeddings-configuration',
        'image-config': 'image-generation-configuration',
        'agents-config': 'agents-configuration',
        'actions-config': 'actions-configuration',
        'web-search-section': 'web-search-foundry-section',
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
    .admin-nav-group {
        font-weight: 500;
        letter-spacing: 0.01em;
    }
    .admin-nav-group:hover {
        background-color: rgba(0, 0, 0, 0.05);
    }
    .admin-nav-group-caret {
        font-size: 0.75em;
        transition: transform 0.2s ease;
    }
    .admin-nav-group-caret.collapsed {
        transform: rotate(-90deg);
    }
`;
document.head.appendChild(style);

// Admin search functionality
function filterAdminSections(searchTerm) {
    const normalizedSearch = searchTerm.toLowerCase().trim();

    if (!normalizedSearch) {
        showAllAdminSections();
        return;
    }

    let hasVisibleSections = false;

    const groupItems = document.querySelectorAll('.admin-nav-group-item');
    const allTabs = document.querySelectorAll('.admin-nav-tab');
    const allSections = document.querySelectorAll('.admin-nav-section');

    // Start from everything hidden, then reveal what matches.
    groupItems.forEach(group => group.classList.add('admin-search-hidden'));
    document.querySelectorAll('.admin-nav-group').forEach(group => {
        group.classList.remove('admin-search-highlight');
    });

    allTabs.forEach(tab => {
        tab.closest('li').classList.add('admin-search-hidden');
        tab.classList.remove('admin-search-highlight');
        const submenu = document.getElementById(tab.getAttribute('data-tab') + '-submenu');
        if (submenu) {
            submenu.style.display = 'none';
        }
    });

    allSections.forEach(section => {
        section.closest('li').classList.add('admin-search-hidden');
        section.classList.remove('admin-search-highlight');
    });

    /**
     * Reveal the group containing an element and expand its tab list, so a
     * match is never left hidden behind a collapsed group.
     * @param {HTMLElement} element Element inside a group.
     */
    const revealGroupOf = (element) => {
        const groupItem = element.closest('.admin-nav-group-item');
        if (!groupItem) {
            return;
        }
        groupItem.classList.remove('admin-search-hidden');
        const list = groupItem.querySelector('.admin-nav-group-tabs');
        if (list) {
            list.classList.remove('d-none');
        }
    };

    // A group matching by name reveals everything it holds.
    document.querySelectorAll('.admin-nav-group').forEach(group => {
        const label = group.querySelector('.nav-text');
        if (!label || !label.textContent.toLowerCase().includes(normalizedSearch)) {
            return;
        }

        group.classList.add('admin-search-highlight');
        revealGroupOf(group);
        hasVisibleSections = true;

        const groupItem = group.closest('.admin-nav-group-item');
        groupItem.querySelectorAll('.admin-nav-tab').forEach(tab => {
            tab.closest('li').classList.remove('admin-search-hidden');
        });
    });

    allTabs.forEach(tab => {
        const label = tab.querySelector('.nav-text');
        const tabText = label ? label.textContent.toLowerCase() : '';
        const tabId = tab.getAttribute('data-tab');
        let tabHasMatch = false;

        if (tabText.includes(normalizedSearch)) {
            tab.closest('li').classList.remove('admin-search-hidden');
            tab.classList.add('admin-search-highlight');
            revealGroupOf(tab);
            tabHasMatch = true;
            hasVisibleSections = true;

            const submenu = document.getElementById(tabId + '-submenu');
            if (submenu) {
                submenu.style.display = 'block';
                submenu.querySelectorAll('.admin-nav-section').forEach(section => {
                    section.closest('li').classList.remove('admin-search-hidden');
                });
            }
        }

        const sections = document.querySelectorAll(`.admin-nav-section[data-tab="${tabId}"]`);
        let sectionHasMatch = false;

        sections.forEach(section => {
            const sectionLabel = section.querySelector('.nav-text');
            const sectionText = sectionLabel ? sectionLabel.textContent.toLowerCase() : '';

            if (sectionText.includes(normalizedSearch)) {
                section.closest('li').classList.remove('admin-search-hidden');
                section.classList.add('admin-search-highlight');
                sectionHasMatch = true;
                hasVisibleSections = true;

                tab.closest('li').classList.remove('admin-search-hidden');
                revealGroupOf(tab);

                const submenu = document.getElementById(tabId + '-submenu');
                if (submenu) {
                    submenu.style.display = 'block';
                }
            }
        });

        // A tab surfaced only because a section matched is not itself a hit.
        if (sectionHasMatch && !tabHasMatch) {
            tab.classList.remove('admin-search-highlight');
        }
    });

    showSearchResults(hasVisibleSections, normalizedSearch);
}

function showAllAdminSections() {
    // Restore the normal browsing state: nothing hidden, nothing highlighted,
    // submenus closed, and groups back to their persisted expansion.
    document.querySelectorAll('.admin-nav-group-item').forEach(group => {
        group.classList.remove('admin-search-hidden');
    });

    document.querySelectorAll('.admin-nav-tab, .admin-nav-section, .admin-nav-group').forEach(item => {
        const listItem = item.closest('li');
        if (listItem) {
            listItem.classList.remove('admin-search-hidden');
        }
        item.classList.remove('admin-search-highlight');
    });

    document.querySelectorAll('[id$="-submenu"]').forEach(submenu => {
        submenu.style.display = 'none';
    });

    document.querySelectorAll('[data-admin-group-toggle]').forEach(toggle => {
        const groupId = toggle.getAttribute('data-admin-group-toggle');
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        setAdminGroupExpanded(groupId, expanded, false);
    });

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
        const searchIcon = document.createElement('i');
        const message = document.createElement('span');

        noResultsDiv.id = 'admin-search-no-results';
        noResultsDiv.className = 'px-3 py-2 text-muted text-center small';
        searchIcon.className = 'bi bi-search me-1';
        searchIcon.setAttribute('aria-hidden', 'true');
        message.textContent = `No settings found for "${searchTerm}"`;
        noResultsDiv.append(searchIcon, message);
        adminSection.appendChild(noResultsDiv);
    }
}

function hideSearchResults() {
    const noResults = document.getElementById('admin-search-no-results');
    if (noResults) {
        noResults.remove();
    }
}
