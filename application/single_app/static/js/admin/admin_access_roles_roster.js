// admin_access_roles_roster.js
//
// Access & Roles shows every "require an Entra app role" switch in one place.
//
// The switches themselves stay on the tabs that own them, because that is where
// they make sense in context. Duplicating the real inputs here would submit
// each setting twice, so this builds a roster of mirrors instead: each row
// carries no name attribute and simply drives the canonical input.
//
// The roster is built from the page rather than from a hand-written list, so a
// new role requirement anywhere in Admin Settings appears here on its own and
// this list cannot fall out of step with reality.
//
// Roster links carry data-admin-link, which admin_card_links.js already handles
// through a delegated listener, so no wiring is needed here.

const ROLE_INPUT_SELECTOR = 'input[type="checkbox"][name^="require_member_of_"]';
const LIST_ID = 'app-role-requirements-list';
const EMPTY_ID = 'app-role-requirements-empty';
const ROSTER_CARD_ID = 'app-role-requirements-section';

/**
 * Read the visible label for a control, falling back to its field name.
 * @param {HTMLInputElement} input Canonical role checkbox.
 * @returns {string} Human readable label.
 */
function labelFor(input) {
    const explicit = input.id ? document.querySelector(`label[for="${input.id}"]`) : null;
    if (explicit && explicit.textContent.trim()) {
        return explicit.textContent.trim();
    }

    const wrapping = input.closest('label');
    if (wrapping && wrapping.textContent.trim()) {
        return wrapping.textContent.trim();
    }

    return input.name;
}

/**
 * Find the card a control belongs to, so the roster can link back to it.
 * @param {HTMLInputElement} input Canonical role checkbox.
 * @returns {HTMLElement|null} The owning card, when it has an id.
 */
function owningCard(input) {
    let card = input.closest('.card[id]');
    while (card && card.id === ROSTER_CARD_ID) {
        card = card.parentElement ? card.parentElement.closest('.card[id]') : null;
    }
    return card;
}

/**
 * Read the heading of a card, used as the "where does this live" hint.
 * @param {HTMLElement} card Owning card.
 * @returns {string} Card title, or an empty string when it has none.
 */
function cardTitle(card) {
    const heading = card ? card.querySelector('h5, h4, h6, .card-title') : null;
    return heading ? heading.textContent.trim() : '';
}

/**
 * Build one roster row: a mirror switch, its label, and a link to the setting.
 * @param {HTMLInputElement} input Canonical role checkbox.
 * @returns {HTMLElement} The row element.
 */
function buildRow(input) {
    const row = document.createElement('div');
    row.className = 'd-flex flex-wrap align-items-center gap-2';
    row.setAttribute('data-role-requirement-row', input.name);

    const wrapper = document.createElement('div');
    wrapper.className = 'form-check form-switch mb-0 flex-grow-1';

    // No name attribute: only the canonical input is submitted with the form.
    const mirror = document.createElement('input');
    mirror.type = 'checkbox';
    mirror.className = 'form-check-input';
    mirror.id = `${input.name}-roster-mirror`;
    mirror.checked = input.checked;
    mirror.disabled = input.disabled;
    mirror.setAttribute('data-role-mirror-for', input.id || input.name);
    mirror.setAttribute('data-ignore-settings-change', 'true');

    const label = document.createElement('label');
    label.className = 'form-check-label ms-2';
    label.setAttribute('for', mirror.id);
    label.textContent = labelFor(input);

    wrapper.append(mirror, label);
    row.appendChild(wrapper);

    const card = owningCard(input);
    if (card) {
        const title = cardTitle(card);
        const link = document.createElement('a');
        link.href = `#${card.id}`;
        link.className = 'small text-nowrap';
        link.setAttribute('data-admin-link', card.id);
        link.textContent = title ? `In ${title}` : 'Go to setting';
        row.appendChild(link);
    }

    // Two-way: the mirror drives the real input, and the real input keeps the
    // mirror honest when it is changed on its own tab.
    mirror.addEventListener('change', () => {
        if (input.checked === mirror.checked) {
            return;
        }
        input.checked = mirror.checked;
        input.dispatchEvent(new Event('change', { bubbles: true }));
    });

    input.addEventListener('change', () => {
        mirror.checked = input.checked;
        mirror.disabled = input.disabled;
    });

    return row;
}

/**
 * Populate the Access & Roles roster from the role switches on the page.
 */
export function initAdminAccessRolesRoster() {
    const list = document.getElementById(LIST_ID);
    if (!list) {
        return;
    }

    const empty = document.getElementById(EMPTY_ID);
    const inputs = Array.from(document.querySelectorAll(ROLE_INPUT_SELECTOR))
        .filter(input => !list.contains(input));

    list.replaceChildren();
    inputs
        .map(input => ({ input, label: labelFor(input) }))
        .sort((a, b) => a.label.localeCompare(b.label))
        .forEach(({ input }) => list.appendChild(buildRow(input)));

    if (empty) {
        empty.classList.toggle('d-none', inputs.length > 0);
    }
}

document.addEventListener('DOMContentLoaded', initAdminAccessRolesRoster);
