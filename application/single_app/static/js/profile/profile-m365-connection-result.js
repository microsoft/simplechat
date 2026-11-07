// profile-m365-connection-result.js
// Ends a Microsoft 365 sign-in on the page the callback renders.
//
// A sign-in started in a popup reports its outcome to the same-origin window that opened it,
// then closes. The opener (V2 settings, a V2 chat notice, or the classic chat) shows the result,
// so the popup never strands the user on another interface. A full-page sign-in shows the
// outcome here and, after success, continues to the fixed settings page the server chose.

(() => {
    'use strict';

    // Only a same-origin absolute path; never another origin or a script URL.
    const SAFE_PATH_PATTERN = /^\/(?![/\\])[^\s\\]*$/;

    function readResult() {
        const element = document.getElementById('m365-connection-result-data');
        if (!element) {
            return null;
        }
        try {
            const value = JSON.parse(element.textContent || 'null');
            return value && typeof value === 'object' ? value : null;
        } catch {
            return null;
        }
    }

    function hasOpener() {
        try {
            return Boolean(window.opener) && window.opener !== window && !window.opener.closed;
        } catch {
            return false;
        }
    }

    function openerMessage(result) {
        const message = {
            type: typeof result.type === 'string' ? result.type : 'm365-connect-failed',
            kind: result.kind === 'workflow' ? 'workflow' : 'chat',
            outcome: result.outcome === 'connected' ? 'connected' : 'failed',
        };
        if (message.outcome !== 'connected') {
            message.code = typeof result.code === 'string' ? result.code : '';
            message.message = typeof result.message === 'string' ? result.message : '';
        }
        return message;
    }

    function initialize() {
        const result = readResult();
        if (!result) {
            return;
        }
        const closeButton = document.getElementById('m365-connection-result-close');
        const closingHint = document.getElementById('m365-connection-result-closing');
        closeButton?.addEventListener('click', () => window.close());

        const popup = result.completion === 'popup' || (result.completion === 'auto' && hasOpener());
        if (popup) {
            closeButton?.classList.remove('d-none');
            if (hasOpener()) {
                window.opener.postMessage(openerMessage(result), window.location.origin);
                closingHint?.classList.remove('d-none');
                window.close();
            }
            return;
        }

        if (
            result.outcome === 'connected'
            && typeof result.continue_url === 'string'
            && SAFE_PATH_PATTERN.test(result.continue_url)
        ) {
            window.location.replace(result.continue_url);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, { once: true });
    } else {
        initialize();
    }
})();
