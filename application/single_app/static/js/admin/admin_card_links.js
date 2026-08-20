// admin_card_links.js
// Resolves links that point at an Admin Settings card rather than at a tab.
//
// Cross-tab links used to name a tab button directly, for example
// switchTab(event, 'workspaces-tab'). That couples the link to a tab id, so a
// tab rename or an information-architecture change silently breaks the link:
// the button no longer exists, no pane is activated, and the URL hash is left
// pointing at nothing.
//
// A link declares the card it wants instead:
//
//     <a href="#redis-cache-section" data-admin-link="redis-cache-section">
//
// The owning tab is resolved from the DOM at click time, so card ids are the
// only contract. Cards can move between tabs, and tabs can be renamed or
// regrouped, without touching a single link.

const HIGHLIGHT_CLASS = 'admin-card-link-target';
const HIGHLIGHT_MS = 1600;

/**
 * Find the tab pane that contains a card.
 * @param {string} cardId Element id of the target card.
 * @returns {{card: HTMLElement, paneId: string|null}|null}
 */
export function resolveAdminCard(cardId) {
    const card = document.getElementById(cardId);
    if (!card) {
        return null;
    }

    const pane = card.closest('.tab-pane');
    return { card, paneId: pane ? pane.id : null };
}

/**
 * Activate the tab owning a card, scroll to it, and highlight it briefly.
 * @param {string} cardId Element id of the target card.
 * @returns {boolean} Whether the card was found.
 */
export function openAdminCard(cardId) {
    const resolved = resolveAdminCard(cardId);
    if (!resolved) {
        console.warn(`openAdminCard: no card with id "${cardId}"`);
        return false;
    }

    const { card, paneId } = resolved;

    if (paneId && typeof window.showAdminTab === 'function') {
        window.showAdminTab(paneId);
        syncSidebarActiveState(paneId);
    }

    // Let the pane become visible before measuring scroll position.
    window.setTimeout(() => {
        card.scrollIntoView({ behavior: 'smooth', block: 'start' });
        card.classList.add(HIGHLIGHT_CLASS);
        window.setTimeout(() => card.classList.remove(HIGHLIGHT_CLASS), HIGHLIGHT_MS);
    }, 120);

    return true;
}

/**
 * Mirror the activated tab in the sidebar, when the sidebar layout is in use.
 * @param {string} paneId Tab pane id that was activated.
 */
function syncSidebarActiveState(paneId) {
    const navLink = document.querySelector(`.admin-nav-tab[data-tab="${paneId}"]`);
    if (!navLink) {
        return;
    }

    document.querySelectorAll('.admin-nav-tab, .admin-nav-section').forEach((link) => {
        link.classList.remove('active');
    });
    navLink.classList.add('active');
}

/**
 * Delegate clicks so links added after load keep working.
 */
export function initAdminCardLinks() {
    document.addEventListener('click', (event) => {
        const link = event.target.closest('[data-admin-link]');
        if (!link) {
            return;
        }

        const cardId = link.getAttribute('data-admin-link');
        if (!cardId) {
            return;
        }

        event.preventDefault();
        openAdminCard(cardId);
    });
}

window.openAdminCard = openAdminCard;

document.addEventListener('DOMContentLoaded', initAdminCardLinks);
