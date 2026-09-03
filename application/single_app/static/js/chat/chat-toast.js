// chat-toast.js

/**
 * Show a notification through the global toast utility.
 *
 * Returns the toast's handle, so a caller showing progress with `{ autohide: false }` can
 * dismiss it once the work finishes.
 */
export function showToast(message, variant = 'danger', options = {}) {
    if (typeof window.showToast !== 'function') {
        throw new Error('Global toast utility is unavailable.');
    }

    return window.showToast(message, variant, options);
}