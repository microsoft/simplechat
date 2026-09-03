// chat-m365-audit.js

export function appendMicrosoft365Audit(container, conversationId) {
    const section = document.createElement('details');
    section.className = 'card mt-3 p-3';
    const summary = document.createElement('summary');
    summary.textContent = 'Microsoft 365 sharing and analysis acknowledgements';
    const body = document.createElement('div');
    body.className = 'mt-2';
    section.append(summary, body);
    container.appendChild(section);
    let loaded = false;
    async function loadPage(continuationToken = '') {
        try {
            const query = continuationToken ? `?continuation_token=${encodeURIComponent(continuationToken)}` : '';
            const response = await fetch(`/api/m365/conversations/${encodeURIComponent(conversationId)}/audit${query}`, {
                credentials: 'same-origin',
            });
            if (!response.ok) {
                throw new Error('Unable to read this conversation Microsoft 365 audit.');
            }
            const page = await response.json();
            for (const item of page.items || []) {
                const row = document.createElement('div');
                row.className = 'border-bottom py-2';
                const source = item.source || Object.keys(item.decisions || {}).join(', ') || 'Microsoft 365';
                const duration = item.effective_grant?.effective_duration || '';
                row.textContent = `${item.created_at} - ${source} - ${item.event_type}${duration ? ` (${duration})` : ''}`;
                if (item.approval_id) {
                    const reference = document.createElement('div');
                    reference.className = 'small text-muted';
                    reference.textContent = `Approval: ${item.approval_id}`;
                    row.appendChild(reference);
                }
                body.appendChild(row);
            }
            if (!body.childElementCount) {
                body.textContent = 'No Microsoft 365 acknowledgements have been recorded for this conversation.';
            }
            if (page.continuation_token) {
                const more = document.createElement('button');
                more.type = 'button';
                more.className = 'btn btn-outline-secondary btn-sm mt-2';
                more.textContent = 'More audit entries';
                more.addEventListener('click', () => {
                    more.remove();
                    void loadPage(page.continuation_token);
                });
                body.appendChild(more);
            }
        } catch (error) {
            body.textContent = error.message;
            body.classList.add('alert', 'alert-warning');
        }
    }
    section.addEventListener('toggle', () => {
        if (section.open && !loaded) {
            loaded = true;
            void loadPage();
        }
    });
}
