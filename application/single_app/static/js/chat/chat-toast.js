// chat-toast.js

export function showToast(message, variant = 'danger', options = {}) {
    if (typeof window.showToast !== 'function') {
        throw new Error('Global toast utility is unavailable.');
    }

    window.showToast(message, variant, options);
}