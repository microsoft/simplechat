// ui-switch.js
document.addEventListener('click', async (event) => {
    const button = event.target.closest('.ui-switch');
    if (!button || button.disabled) {
        return;
    }
    // Keep the account dropdown open so an unsuccessful save remains visible.
    event.stopPropagation();
    const buttons = document.querySelectorAll('.ui-switch');
    const errors = document.querySelectorAll('.ui-switch-error');
    buttons.forEach((item) => { item.disabled = true; });
    errors.forEach((item) => { item.classList.add('d-none'); });
    try {
        const response = await fetch('/api/user/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ settings: { preferredUiMode: 'modern' } }),
        });
        if (!response.ok || response.redirected) {
            throw new Error('Preference save failed');
        }
        await response.json();
        const target = new URL(button.dataset.modernPath, window.location.origin);
        if (target.origin !== window.location.origin || !/^\/v2(?:\/|$)/.test(target.pathname)) {
            throw new Error('Invalid modern destination');
        }
        // The modern address names its interface the way a classic one does with ui=classic.
        target.searchParams.set('ui', 'modern');
        // The V2 fragment translator maps classic tabs after the interface changes.
        target.hash = window.location.hash;
        window.location.assign(target.href);
    } catch (error) {
        errors.forEach((item) => {
            item.textContent = 'Your interface preference could not be saved. Please try again.';
            item.classList.remove('d-none');
        });
        buttons.forEach((item) => { item.disabled = false; });
    }
}, true);
