// toast.js

(function initializeToastNotifications() {
    const preferredToastContainerSelector = '[data-toast-container="preferred"]';
    const pendingToastStorageKey = 'simplechat.pendingToast';
    const supportedVariants = new Set(['danger', 'info', 'success', 'warning']);
    const variantAliases = new Map([['error', 'danger']]);
    const syncedToastContainers = new WeakSet();

    function getToastContainer() {
        return document.querySelector(preferredToastContainerSelector)
            || document.getElementById('toast-container');
    }

    function getToastAnchor(container) {
        const anchorId = container?.dataset.toastAnchor;
        return anchorId ? document.getElementById(anchorId) : null;
    }

    function syncToastContainerPosition(container) {
        if (!container?.dataset.toastAnchor) {
            return;
        }

        const defaultTop = container.dataset.toastDefaultTop || '16px';
        const anchor = getToastAnchor(container);
        if (!anchor || anchor.offsetParent === null || !anchor.classList.contains('is-ready')) {
            container.style.top = defaultTop;
            return;
        }

        const gap = Number.parseInt(container.dataset.toastGap || '12', 10);
        const containerPaddingTop = Number.parseFloat(
            window.getComputedStyle(container).paddingTop || '0'
        );
        const anchorRect = anchor.getBoundingClientRect();
        const anchoredTop = Math.max(16, Math.ceil(anchorRect.bottom + gap - containerPaddingTop));
        container.style.top = `${anchoredTop}px`;
    }

    function ensureToastContainerAnchorSync(container) {
        if (!container?.dataset.toastAnchor || syncedToastContainers.has(container)) {
            return;
        }

        syncedToastContainers.add(container);
        const reposition = () => syncToastContainerPosition(container);
        const anchor = getToastAnchor(container);

        window.addEventListener('resize', reposition);

        if (window.ResizeObserver && anchor) {
            const resizeObserver = new ResizeObserver(reposition);
            resizeObserver.observe(anchor);
        }

        if (window.MutationObserver && anchor) {
            const mutationObserver = new MutationObserver(reposition);
            mutationObserver.observe(anchor, {
                attributes: true,
                attributeFilter: ['class', 'style'],
            });
        }

        reposition();
    }

    function normalizeToastMessage(message) {
        return message instanceof Node
            ? message.textContent || ''
            : String(message ?? '');
    }

    function persistToast(message, variant) {
        try {
            window.sessionStorage.setItem(
                pendingToastStorageKey,
                JSON.stringify({ message, variant })
            );
        } catch (error) {
            console.error('[Toast] Unable to persist notification for the next page.', error);
        }
    }

    function consumePendingToast() {
        try {
            const pendingToastJson = window.sessionStorage.getItem(pendingToastStorageKey);
            if (!pendingToastJson) {
                return null;
            }

            window.sessionStorage.removeItem(pendingToastStorageKey);
            const pendingToast = JSON.parse(pendingToastJson);
            if (!pendingToast || typeof pendingToast.message !== 'string') {
                console.error('[Toast] Ignoring an invalid persisted notification.');
                return null;
            }

            return pendingToast;
        } catch (error) {
            console.error('[Toast] Unable to restore the persisted notification.', error);
            return null;
        }
    }

    function showToast(message, variant = 'info', options = {}) {
        const container = getToastContainer();
        if (!container) {
            console.error('[Toast] Toast container is unavailable.');
            return;
        }

        const requestedVariant = variantAliases.get(variant) || variant;
        const normalizedVariant = supportedVariants.has(requestedVariant) ? requestedVariant : 'info';
        const normalizedMessage = normalizeToastMessage(message);
        const isUrgent = normalizedVariant === 'danger' || normalizedVariant === 'warning';
        if (options.persist === true) {
            persistToast(normalizedMessage, normalizedVariant);
        }

        ensureToastContainerAnchorSync(container);
        syncToastContainerPosition(container);

        const toastEl = document.createElement('div');
        toastEl.className = `toast align-items-center text-bg-${normalizedVariant}`;
        toastEl.setAttribute('role', isUrgent ? 'alert' : 'status');
        toastEl.setAttribute('aria-live', isUrgent ? 'assertive' : 'polite');
        toastEl.setAttribute('aria-atomic', 'true');

        const contentEl = document.createElement('div');
        contentEl.className = 'd-flex';

        const bodyEl = document.createElement('div');
        bodyEl.className = 'toast-body';
        bodyEl.textContent = normalizedMessage;

        const closeButtonEl = document.createElement('button');
        closeButtonEl.type = 'button';
        closeButtonEl.className = 'btn-close btn-close-white me-2 m-auto';
        closeButtonEl.setAttribute('data-bs-dismiss', 'toast');
        closeButtonEl.setAttribute('aria-label', 'Close');

        contentEl.appendChild(bodyEl);
        contentEl.appendChild(closeButtonEl);
        toastEl.appendChild(contentEl);
        container.appendChild(toastEl);

        if (!window.bootstrap?.Toast) {
            console.error('[Toast] Bootstrap Toast is unavailable.');
            toastEl.classList.add('show');
            return;
        }

        toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove(), { once: true });
        const bootstrapToast = new window.bootstrap.Toast(toastEl, { delay: 5000 });
        bootstrapToast.show();
    }

    window.showToast = showToast;

    const pendingToast = consumePendingToast();
    if (pendingToast) {
        showToast(pendingToast.message, pendingToast.variant);
    }
}());
