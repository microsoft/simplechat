// admin_settings_dependencies.js
// Announces and enforces Admin Settings options that require another option.
//
// Some settings only work when a different setting is enabled, and those two
// settings often live in different tabs. Previously that was communicated in
// prose, or in a tooltip, or only by a flash message after saving, so an admin
// could turn something on and have nothing happen with no visible reason.
//
// A dependent card declares what it needs:
//
//     <div class="card" id="file-sync-section"
//          data-requires="enable_redis_cache"
//          data-requires-label="Redis Cache"
//          data-requires-target="redis-cache-section"
//          data-requires-mode="warn">
//
// When the prerequisite is off, a notice is inserted at the top of the card
// containing a mirror of the prerequisite control and a link to its card, so
// the admin can satisfy it inline or jump to the full configuration.
//
// Modes:
//   block (default) disables the dependent inputs until the prerequisite is on
//   warn            leaves inputs usable, for prerequisites the backend already
//                   accepts as intent and reconciles later
//
// This is a usability layer only. The backend remains authoritative and still
// refuses or flashes on unmet prerequisites.

const NOTICE_CLASS = 'admin-dependency-notice';
const DISABLED_FLAG = 'data-dependency-disabled';

/**
 * Read every dependency declared in the document.
 * @returns {Array<object>} Parsed dependency descriptors.
 */
function collectDependencies() {
    return Array.from(document.querySelectorAll('[data-requires]')).map((card) => ({
        card,
        prerequisiteId: card.getAttribute('data-requires'),
        label: card.getAttribute('data-requires-label') || 'another setting',
        targetCardId: card.getAttribute('data-requires-target') || '',
        mode: card.getAttribute('data-requires-mode') === 'warn' ? 'warn' : 'block',
        description: card.getAttribute('data-requires-description') || '',
        // Optional selector limiting which controls the dependency guards, for
        // cards that hold a mix of dependent and independent settings.
        scope: card.getAttribute('data-requires-scope') || '',
    }));
}

/**
 * Whether a prerequisite control is currently satisfied.
 * @param {HTMLElement|null} control Prerequisite input.
 * @returns {boolean}
 */
function isSatisfied(control) {
    if (!control) {
        return true;
    }
    if (control.type === 'checkbox' || control.type === 'radio') {
        return control.checked;
    }
    return Boolean(control.value);
}

/**
 * Build the notice shown when a prerequisite is unmet.
 * @param {object} dependency Dependency descriptor.
 * @param {HTMLElement} prerequisite Prerequisite control.
 * @returns {HTMLElement}
 */
function buildNotice(dependency, prerequisite) {
    const notice = document.createElement('div');
    notice.className = `alert ${dependency.mode === 'warn' ? 'alert-warning' : 'alert-info'} ${NOTICE_CLASS}`;
    notice.setAttribute('role', 'note');

    const heading = document.createElement('div');
    heading.className = 'fw-semibold mb-1';
    const icon = document.createElement('i');
    icon.className = 'bi bi-info-circle me-2';
    icon.setAttribute('aria-hidden', 'true');
    heading.append(icon, document.createTextNode(`This needs ${dependency.label}`));
    notice.appendChild(heading);

    const body = document.createElement('p');
    body.className = 'mb-2';
    body.textContent = dependency.description
        || (dependency.mode === 'warn'
            ? `These settings are saved, but stay inactive until ${dependency.label} is enabled and configured.`
            : `These settings are unavailable until ${dependency.label} is enabled.`);
    notice.appendChild(body);

    const actions = document.createElement('div');
    actions.className = 'd-flex flex-wrap align-items-center gap-3';

    // Inline mirror: satisfy the prerequisite without leaving this tab. It
    // carries no name attribute, so only the canonical input is submitted.
    if (prerequisite && prerequisite.type === 'checkbox') {
        const wrapper = document.createElement('div');
        wrapper.className = 'form-check form-switch mb-0';

        const proxy = document.createElement('input');
        proxy.type = 'checkbox';
        proxy.className = 'form-check-input';
        proxy.id = `${dependency.card.id}-requires-proxy`;
        proxy.checked = prerequisite.checked;
        proxy.setAttribute('data-dependency-proxy-for', prerequisite.id);
        proxy.setAttribute('data-ignore-settings-change', 'true');

        proxy.addEventListener('change', () => {
            prerequisite.checked = proxy.checked;
            prerequisite.dispatchEvent(new Event('change', { bubbles: true }));
        });

        const proxyLabel = document.createElement('label');
        proxyLabel.className = 'form-check-label ms-2';
        proxyLabel.setAttribute('for', proxy.id);
        proxyLabel.textContent = `Enable ${dependency.label}`;

        wrapper.append(proxy, proxyLabel);
        actions.appendChild(wrapper);
    }

    if (dependency.targetCardId) {
        const link = document.createElement('a');
        link.href = `#${dependency.targetCardId}`;
        link.setAttribute('data-admin-link', dependency.targetCardId);
        link.className = 'small';
        link.textContent = `Go to ${dependency.label}`;
        actions.appendChild(link);
    }

    notice.appendChild(actions);
    return notice;
}

/**
 * Enable or disable the controls a dependency guards.
 * @param {object} dependency Dependency descriptor.
 * @param {boolean} satisfied Whether the prerequisite is met.
 */
function setControlsDisabled(dependency, satisfied) {
    if (dependency.mode === 'warn') {
        return;
    }

    const selector = dependency.scope || 'input, select, textarea, button';
    dependency.card.querySelectorAll(selector).forEach((control) => {
        if (control.closest(`.${NOTICE_CLASS}`)) {
            return;
        }

        if (!satisfied) {
            // Remember controls that were already disabled for other
            // reasons so re-enabling does not override them.
            if (!control.disabled) {
                control.setAttribute(DISABLED_FLAG, 'true');
                control.disabled = true;
            }
        } else if (control.getAttribute(DISABLED_FLAG) === 'true') {
            control.removeAttribute(DISABLED_FLAG);
            control.disabled = false;
        }
    });
}

/**
 * Apply the current state of one dependency.
 * @param {object} dependency Dependency descriptor.
 */
function applyDependency(dependency) {
    const prerequisite = document.getElementById(dependency.prerequisiteId);
    const satisfied = isSatisfied(prerequisite);

    const existing = dependency.card.querySelector(`:scope > .${NOTICE_CLASS}`);
    if (existing) {
        existing.remove();
    }

    setControlsDisabled(dependency, satisfied);

    if (satisfied) {
        return;
    }

    const notice = buildNotice(dependency, prerequisite);
    const heading = dependency.card.querySelector('h4, h5, h6');
    if (heading && heading.parentElement === dependency.card) {
        heading.insertAdjacentElement('afterend', notice);
    } else {
        dependency.card.prepend(notice);
    }
}

/**
 * Wire up every declared dependency and keep it live.
 */
export function initAdminSettingsDependencies() {
    const dependencies = collectDependencies();
    if (!dependencies.length) {
        return;
    }

    dependencies.forEach((dependency) => {
        applyDependency(dependency);

        const prerequisite = document.getElementById(dependency.prerequisiteId);
        if (!prerequisite) {
            console.warn(
                `admin dependencies: "${dependency.card.id}" requires missing control `
                + `"${dependency.prerequisiteId}"`,
            );
            return;
        }

        prerequisite.addEventListener('change', () => applyDependency(dependency));
        prerequisite.addEventListener('input', () => applyDependency(dependency));
    });
}

document.addEventListener('DOMContentLoaded', initAdminSettingsDependencies);
