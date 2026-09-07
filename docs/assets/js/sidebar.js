// sidebar.js
/**
 * Documentation sidebar behavior for the GitHub Pages site.
 */

(function() {
    "use strict";

    const FALLBACK_DESKTOP_BREAKPOINT = 992;
    const FOCUSABLE_SELECTOR = [
        "a[href]",
        "button:not([disabled])",
        "input:not([disabled])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        "[tabindex]:not([tabindex='-1'])"
    ].join(",");

    let lastFocusedElement = null;

    function getDesktopBreakpoint() {
        const rawBreakpoint = getComputedStyle(document.documentElement)
            .getPropertyValue("--docs-breakpoint-lg")
            .trim();
        const parsedBreakpoint = Number.parseFloat(rawBreakpoint);

        if (Number.isFinite(parsedBreakpoint) && parsedBreakpoint > 0) {
            return parsedBreakpoint;
        }

        return FALLBACK_DESKTOP_BREAKPOINT;
    }

    function isDesktop() {
        return window.innerWidth >= getDesktopBreakpoint();
    }

    function getElements() {
        return {
            sidebar: document.getElementById("sidebar-nav"),
            openButton: document.getElementById("docs-mobile-menu-toggle"),
            closeButton: document.getElementById("docs-sidebar-close"),
            backdrop: document.getElementById("docs-sidebar-backdrop")
        };
    }

    function getFocusableElements(container) {
        if (!container) {
            return [];
        }

        return Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR)).filter(function(element) {
            return element.getClientRects().length > 0 || element === document.activeElement;
        });
    }

    function focusSidebar() {
        const { sidebar, closeButton } = getElements();

        if (!sidebar || isDesktop()) {
            return;
        }

        window.requestAnimationFrame(function() {
            const focusableElements = getFocusableElements(sidebar);
            const target = closeButton || focusableElements[0] || sidebar;

            if (!target.hasAttribute("tabindex") && target === sidebar) {
                target.setAttribute("tabindex", "-1");
            }

            target.focus({ preventScroll: true });
        });
    }

    function restoreSidebarFocus() {
        const { openButton } = getElements();
        const focusTarget = openButton || lastFocusedElement;

        if (focusTarget && typeof focusTarget.focus === "function") {
            focusTarget.focus({ preventScroll: true });
        }

        lastFocusedElement = null;
    }

    function isMobileSidebarOpen() {
        const { sidebar } = getElements();

        return Boolean(sidebar && sidebar.classList.contains("is-open") && !isDesktop());
    }

    function trapSidebarFocus(event) {
        if (event.key !== "Tab" || !isMobileSidebarOpen()) {
            return;
        }

        const { sidebar } = getElements();
        const focusableElements = getFocusableElements(sidebar);

        if (focusableElements.length === 0) {
            event.preventDefault();
            sidebar.focus({ preventScroll: true });
            return;
        }

        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (event.shiftKey && document.activeElement === firstElement) {
            event.preventDefault();
            lastElement.focus({ preventScroll: true });
        } else if (!event.shiftKey && document.activeElement === lastElement) {
            event.preventDefault();
            firstElement.focus({ preventScroll: true });
        }
    }

    function setSidebarOpen(isOpen) {
        const { sidebar, openButton, backdrop } = getElements();

        if (!sidebar || !openButton || !backdrop) {
            return;
        }

        const wasOpen = sidebar.classList.contains("is-open");

        if (isOpen && !wasOpen) {
            lastFocusedElement = document.activeElement;
        }

        sidebar.classList.toggle("is-open", isOpen);
        openButton.setAttribute("aria-expanded", isOpen ? "true" : "false");
        backdrop.classList.toggle("d-none", !isOpen || isDesktop());
        document.body.classList.toggle("docs-nav-open", isOpen && !isDesktop());

        if (isOpen) {
            focusSidebar();
        } else if (wasOpen && !isDesktop()) {
            restoreSidebarFocus();
        }
    }

    function closeSidebar() {
        setSidebarOpen(false);
    }

    function openSidebar() {
        setSidebarOpen(true);
    }

    function syncSidebarForViewport() {
        const { backdrop } = getElements();

        if (isDesktop()) {
            document.body.classList.remove("docs-nav-open");
            if (backdrop) {
                backdrop.classList.add("d-none");
            }
        }
    }

    function initSectionToggles() {
        const toggles = document.querySelectorAll(".docs-sidebar-section-toggle");

        toggles.forEach(function(toggle) {
            const targetId = toggle.getAttribute("aria-controls");
            const target = targetId ? document.getElementById(targetId) : null;

            if (!target) {
                return;
            }

            toggle.addEventListener("click", function() {
                const isExpanded = toggle.getAttribute("aria-expanded") === "true";
                toggle.setAttribute("aria-expanded", isExpanded ? "false" : "true");
                toggle.classList.toggle("is-collapsed", isExpanded);
                target.classList.toggle("d-none", isExpanded);
            });
        });
    }

    function expandActiveSection() {
        const activeLink = document.querySelector(".docs-sidebar-link.active");

        if (!activeLink) {
            return;
        }

        const list = activeLink.closest(".docs-sidebar-list");
        if (!list) {
            return;
        }

        const toggle = document.querySelector(`[aria-controls="${list.id}"]`);
        list.classList.remove("d-none");

        if (toggle) {
            toggle.setAttribute("aria-expanded", "true");
            toggle.classList.remove("is-collapsed");
        }
    }

    function initSidebar() {
        const { openButton, closeButton, backdrop } = getElements();

        if (openButton) {
            openButton.addEventListener("click", function() {
                openSidebar();
            });
        }

        if (closeButton) {
            closeButton.addEventListener("click", closeSidebar);
        }

        if (backdrop) {
            backdrop.addEventListener("click", closeSidebar);
        }

        document.addEventListener("keydown", function(event) {
            if (event.key === "Escape" && isMobileSidebarOpen()) {
                closeSidebar();
            }

            trapSidebarFocus(event);
        });

        window.addEventListener("resize", syncSidebarForViewport);

        initSectionToggles();
        expandActiveSection();
        syncSidebarForViewport();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initSidebar);
    } else {
        initSidebar();
    }

    window.SimpleChat = window.SimpleChat || {};
    window.SimpleChat.Sidebar = {
        closeSidebar,
        openSidebar,
        setSidebarOpen,
        isDesktop
    };
})();