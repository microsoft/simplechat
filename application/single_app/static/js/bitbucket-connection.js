// bitbucket-connection.js
document.addEventListener('DOMContentLoaded', () => {
    const root = document.querySelector('[data-bitbucket-reference]');
    if (!root) return;
    const reference = root.dataset.bitbucketReference;
    const status = document.getElementById('bitbucket-status');
    const connect = document.getElementById('bitbucket-connect');
    const disconnect = document.getElementById('bitbucket-disconnect');
    let csrf = '';
    const show = (message, failed = false) => {
        status.textContent = message;
        status.className = `alert ${failed ? 'alert-danger' : 'alert-info'}`;
    };
    async function command(operation) {
        const response = await fetch(`/api/bitbucket/${operation}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({ action_ref: reference }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Bitbucket request failed.');
        return result;
    }
    async function refresh() {
        try {
            const response = await fetch(`/api/bitbucket/connection?action_ref=${encodeURIComponent(reference)}`);
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Cannot check Bitbucket connection.');
            csrf = result.csrf_token;
            connect.disabled = false;
            disconnect.disabled = !result.connected;
            show(result.connected ? 'Connected. Repository and branch restrictions remain in effect.' : 'Not connected. Sign in through Bitbucket to continue.');
        } catch (error) {
            show(error.message, true);
        }
    }
    connect.addEventListener('click', async () => {
        connect.disabled = true;
        try {
            const result = await command('connect');
            const url = new URL(result.authorization_url);
            if (url.protocol !== 'https:') throw new Error('Bitbucket returned an invalid sign-in address.');
            window.location.assign(url.href);
        } catch (error) {
            show(error.message, true);
            connect.disabled = false;
        }
    });
    disconnect.addEventListener('click', async () => {
        disconnect.disabled = true;
        try {
            await command('disconnect');
            await refresh();
        } catch (error) {
            show(error.message, true);
        }
    });
    document.getElementById('bitbucket-refresh').addEventListener('click', refresh);
    refresh();
});
