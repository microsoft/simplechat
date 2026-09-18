// m365-requests.js
(function initializeMicrosoft365Requests() {
    'use strict';
    const panel = document.getElementById('m365-waiting-requests');
    if (!panel || !window.SimpleChatM365Approvals) {
        return;
    }
    const api = window.SimpleChatM365Approvals;
    async function load(continuationToken = '') {
        try {
            const suffix = continuationToken ? `?continuation_token=${encodeURIComponent(continuationToken)}` : '';
            const payload = await api.requestJson(`/api/m365/requests${suffix}`);
            if (!continuationToken) {
                panel.replaceChildren();
            }
            for (const item of payload.items || []) {
                const row = document.createElement('div');
                row.className = 'border-bottom py-3';
                const label = document.createElement('p');
                label.textContent = `${item.workflow_id ? 'Workflow' : 'Conversation'}: ${item.conversation_id} - ${item.status.replaceAll('_', ' ')}`;
                row.appendChild(label);
                if (item.workflow_id) {
                    const link = document.createElement('a');
                    link.href = '/profile?tab=settings';
                    link.className = 'btn btn-outline-primary btn-sm';
                    link.textContent = 'Review Microsoft 365 connection';
                    row.appendChild(link);
                } else if (item.status !== 'recovery_required') {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'btn btn-outline-primary btn-sm';
                    button.textContent = 'Resume request';
                    button.addEventListener('click', async () => {
                        button.disabled = true;
                        try {
                            const result = await api.requestJson(
                                `/api/m365/requests/${encodeURIComponent(item.id)}/resume`,
                                { method: 'POST', body: {} },
                            );
                            if (result.auth_required) {
                                const signInUrl = result.auth_url || result.consent_url;
                                if (!signInUrl) {
                                    label.textContent = result.message || 'Sign in to SimpleChat again, then resume this request.';
                                    label.className = 'alert alert-warning';
                                    return;
                                }
                                const link = document.createElement('a');
                                const authUrl = new URL(signInUrl);
                                if (authUrl.protocol !== 'https:') {
                                    throw new Error('The sign-in link is invalid.');
                                }
                                link.href = authUrl.href;
                                link.className = 'btn btn-primary btn-sm ms-2';
                                link.textContent = 'Sign in to Microsoft 365';
                                row.appendChild(link);
                            } else {
                                label.textContent = 'Request queued. Its result will appear in the original conversation.';
                                label.className = 'alert alert-info';
                            }
                        } catch (error) {
                            label.textContent = error.message;
                            label.className = 'alert alert-warning';
                        } finally {
                            button.disabled = false;
                        }
                    });
                    row.appendChild(button);
                }
                panel.appendChild(row);
            }
            if (!payload.items?.length && !continuationToken) {
                panel.textContent = 'No Microsoft 365 requests are waiting.';
            }
            if (payload.continuation_token) {
                const more = document.createElement('button');
                more.type = 'button';
                more.className = 'btn btn-outline-secondary btn-sm mt-2';
                more.textContent = 'More waiting requests';
                more.addEventListener('click', () => {
                    more.remove();
                    void load(payload.continuation_token);
                });
                panel.appendChild(more);
            }
        } catch (error) {
            panel.textContent = error.message;
            panel.classList.add('alert', 'alert-warning');
        }
    }
    window.addEventListener('m365-approval-updated', () => { void load(); });
    void load();
})();
