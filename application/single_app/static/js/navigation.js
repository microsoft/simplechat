// navigation.js

/**
 * Navigation-related utilities and event handlers.
 * Handles responsive drawer behavior, dropdown accessibility, and overlay coordination.
 */

document.addEventListener('DOMContentLoaded', () => {
    handleResponsiveNavigation();
    setupDropdownBehaviors();
    initializeMobileNavigationDrawers();
    initializeNavigationOverlayCoordination();
});

function isChatRailNavigationDrawer(offcanvasElement) {
    return offcanvasElement?.dataset?.navigationDrawer === 'chat-rail';
}

function getNavigationOffcanvasElements() {
    if (typeof bootstrap === 'undefined' || !bootstrap.Offcanvas) {
        return [];
    }

    return Array.from(document.querySelectorAll('[data-navigation-drawer]'));
}

function hideOffcanvasElement(offcanvasElement) {
    if (!offcanvasElement || typeof bootstrap === 'undefined' || !bootstrap.Offcanvas) {
        return;
    }

    const offcanvasInstance = bootstrap.Offcanvas.getInstance(offcanvasElement);
    if (offcanvasInstance) {
        offcanvasInstance.hide();
    }
}

function closeOpenDropdowns() {
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

function handleResponsiveNavigation() {
    window.addEventListener('resize', () => {
        if (window.innerWidth > 991) {
            const navbarCollapse = document.querySelector('.navbar-collapse');
            if (navbarCollapse && navbarCollapse.classList.contains('show') && typeof bootstrap !== 'undefined' && bootstrap.Collapse) {
                bootstrap.Collapse.getOrCreateInstance(navbarCollapse).hide();
            }

            getNavigationOffcanvasElements().forEach((offcanvasElement) => {
                hideOffcanvasElement(offcanvasElement);
            });
        }
    });
}

function initializeMobileNavigationDrawers() {
    getNavigationOffcanvasElements().forEach((offcanvasElement) => {
        if (isChatRailNavigationDrawer(offcanvasElement)) {
            return;
        }

        const offcanvasInstance = bootstrap.Offcanvas.getOrCreateInstance(offcanvasElement);

        offcanvasElement.querySelectorAll('a[href]').forEach((link) => {
            link.addEventListener('click', () => {
                if (window.innerWidth < 992) {
                    offcanvasInstance.hide();
                }
            });
        });
    });
}

function initializeNavigationOverlayCoordination() {
    const topNavUserDropdown = document.getElementById('userDropdown');
    const topNavDropdownContainer = topNavUserDropdown ? topNavUserDropdown.closest('.dropdown') : null;

    if (topNavDropdownContainer && typeof bootstrap !== 'undefined' && bootstrap.Dropdown) {
        topNavDropdownContainer.addEventListener('show.bs.dropdown', () => {
            getNavigationOffcanvasElements().forEach((offcanvasElement) => {
                hideOffcanvasElement(offcanvasElement);
            });
        });
    }

    getNavigationOffcanvasElements().forEach((offcanvasElement) => {
        offcanvasElement.addEventListener('show.bs.offcanvas', () => {
            closeOpenDropdowns();
        });
    });
}

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
            closeOpenDropdowns();
        }
    });
}

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

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        handleResponsiveNavigation,
        setupDropdownBehaviors,
        toggleNavbarCollapse
    };
}