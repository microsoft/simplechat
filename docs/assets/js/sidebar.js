// sidebar.js
/**
 * Documentation sidebar behavior for the GitHub Pages site.
 */

(function() {
    "use strict";

    const DESKTOP_BREAKPOINT = 992;

    function isDesktop() {
        return window.innerWidth >= DESKTOP_BREAKPOINT;
    }

    function getElements() {
        return {
            sidebar: document.getElementById("sidebar-nav"),
            openButton: document.getElementById("docs-mobile-menu-toggle"),
            closeButton: document.getElementById("docs-sidebar-close"),
            backdrop: document.getElementById("docs-sidebar-backdrop")
        };
    }

    function setSidebarOpen(isOpen) {
        const { sidebar, openButton, backdrop } = getElements();

        if (!sidebar || !openButton || !backdrop) {
            return;
        }

        sidebar.classList.toggle("is-open", isOpen);
        openButton.setAttribute("aria-expanded", isOpen ? "true" : "false");
        backdrop.classList.toggle("d-none", !isOpen || isDesktop());
        document.body.classList.toggle("docs-nav-open", isOpen && !isDesktop());
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
            if (event.key === "Escape") {
                closeSidebar();
            }
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