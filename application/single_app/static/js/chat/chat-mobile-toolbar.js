// chat-mobile-toolbar.js

function isMobileToolbarViewport() {
    return window.matchMedia('(max-width: 991.98px)').matches;
}

function getMobileToolsOffcanvas(panelElement) {
    if (!panelElement || typeof bootstrap === 'undefined' || !bootstrap.Offcanvas) {
        return null;
    }

    return bootstrap.Offcanvas.getOrCreateInstance(panelElement, { toggle: false });
}

function hideMobileSelectorDropdown(dropdownButtonId) {
    if (!dropdownButtonId || typeof bootstrap === 'undefined' || !bootstrap.Dropdown) {
        return;
    }

    const dropdownButton = document.getElementById(dropdownButtonId);
    if (!dropdownButton) {
        return;
    }

    bootstrap.Dropdown.getInstance(dropdownButton)?.hide();
}

function closeOpenMobileSelectorDropdowns() {
    hideMobileSelectorDropdown('model-dropdown-button');
    hideMobileSelectorDropdown('prompt-dropdown-button');
    hideMobileSelectorDropdown('agent-dropdown-button');
}

function revealSelectorInMobileDrawer({ selectorId, dropdownButtonId }) {
    if (!isMobileToolbarViewport() || !selectorId) {
        return;
    }

    const selectorElement = document.getElementById(selectorId);
    if (!selectorElement || window.getComputedStyle(selectorElement).display === 'none') {
        return;
    }

    selectorElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    if (!dropdownButtonId || typeof bootstrap === 'undefined' || !bootstrap.Dropdown) {
        return;
    }

    const dropdownButton = document.getElementById(dropdownButtonId);
    if (!dropdownButton) {
        return;
    }

    window.setTimeout(() => {
        dropdownButton.focus({ preventScroll: true });
        bootstrap.Dropdown.getOrCreateInstance(dropdownButton, {
            autoClose: 'outside',
        }).show();
    }, 140);
}

function moveSurfaceToSlot(surfaceElement, slotElement) {
    if (!surfaceElement || !slotElement || surfaceElement.parentElement === slotElement) {
        return;
    }

    slotElement.appendChild(surfaceElement);
}

function hideMobileToolsPanel(panelElement) {
    if (!isMobileToolbarViewport()) {
        return;
    }

    getMobileToolsOffcanvas(panelElement)?.hide();
}

function initializeChatMobileToolbar() {
    const mobileToolsToggle = document.getElementById('chat-mobile-tools-toggle');
    const mobileToolsClose = document.getElementById('chat-mobile-tools-close');
    const mobileToolsPanel = document.getElementById('chat-mobile-tools-panel');
    const primarySurface = document.getElementById('chat-toolbar-primary-surface');
    const toolsSurface = document.getElementById('chat-toolbar-tools-surface');
    const selectorsSurface = document.getElementById('chat-toolbar-selectors-surface');
    const desktopPrimarySlot = document.getElementById('chat-toolbar-desktop-primary-slot');
    const desktopToolsSlot = document.getElementById('chat-toolbar-desktop-tools-slot');
    const desktopSelectorsSlot = document.getElementById('chat-toolbar-desktop-selectors-slot');
    const mobileToolsSlot = document.getElementById('chat-toolbar-mobile-tools-slot');
    const mobilePrimarySlot = document.getElementById('chat-toolbar-mobile-primary-slot');
    const mobileSelectorsSlot = document.getElementById('chat-toolbar-mobile-selectors-slot');

    if (!mobileToolsToggle || !mobileToolsPanel || !primarySurface || !toolsSurface || !selectorsSurface) {
        return;
    }

    const dismissButtonIds = [
        'image-generate-btn',
        'search-documents-btn',
        'choose-file-btn',
        'search-web-btn',
        'reasoning-toggle-btn',
        'tts-autoplay-toggle-btn',
    ];

    const syncToolbarLayout = () => {
        if (isMobileToolbarViewport()) {
            moveSurfaceToSlot(primarySurface, mobilePrimarySlot);
            moveSurfaceToSlot(toolsSurface, mobileToolsSlot);
            moveSurfaceToSlot(selectorsSurface, mobileSelectorsSlot);
            return;
        }

        closeOpenMobileSelectorDropdowns();
        moveSurfaceToSlot(primarySurface, desktopPrimarySlot);
        moveSurfaceToSlot(toolsSurface, desktopToolsSlot);
        moveSurfaceToSlot(selectorsSurface, desktopSelectorsSlot);

        mobileToolsToggle.classList.remove('is-expanded');
        mobileToolsToggle.setAttribute('aria-expanded', 'false');
        getMobileToolsOffcanvas(mobileToolsPanel)?.hide();
    };

    mobileToolsPanel.addEventListener('shown.bs.offcanvas', () => {
        mobileToolsToggle.classList.add('is-expanded');
        mobileToolsToggle.setAttribute('aria-expanded', 'true');
    });

    mobileToolsPanel.addEventListener('hidden.bs.offcanvas', () => {
        closeOpenMobileSelectorDropdowns();
        mobileToolsToggle.classList.remove('is-expanded');
        mobileToolsToggle.setAttribute('aria-expanded', 'false');
    });

    mobileToolsClose?.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        closeOpenMobileSelectorDropdowns();
        hideMobileToolsPanel(mobileToolsPanel);
    });

    window.addEventListener('chat:toolbar-selector-activated', (event) => {
        revealSelectorInMobileDrawer(event.detail || {});
    });

    dismissButtonIds.forEach((buttonId) => {
        const button = document.getElementById(buttonId);
        if (!button) {
            return;
        }

        button.addEventListener('click', () => {
            window.setTimeout(() => {
                hideMobileToolsPanel(mobileToolsPanel);
            }, 0);
        });
    });

    window.addEventListener('resize', syncToolbarLayout);
    syncToolbarLayout();
}

initializeChatMobileToolbar();