// chat-m365-connect.js
(() => {
    'use strict';

    let callbackHandled = false;

    function makeElement(tag, className, text) {
        const element = document.createElement(tag);
        element.className = className;
        if (text !== undefined) {
            element.textContent = text;
        }
        return element;
    }

    function authorizationUrl(value) {
        const invalidUrlMessage = 'The server did not return a valid HTTPS Microsoft 365 sign-in URL.';
        if (typeof value !== 'string' || !value.trim()) {
            throw new Error(invalidUrlMessage);
        }
        let target;
        try {
            target = new URL(value);
        } catch {
            throw new Error(invalidUrlMessage);
        }
        // The authenticated API validates the configured authority, including custom clouds.
        if (target.protocol !== 'https:' || !target.hostname || target.username || target.password) {
            throw new Error(invalidUrlMessage);
        }
        return target.href;
    }

    async function requestAction(requestId, action) {
        const api = window.SimpleChatM365Approvals;
        if (!api) {
            throw new Error('Microsoft 365 controls are unavailable. Refresh before trying again.');
        }
        if (typeof requestId !== 'string' || !requestId.trim() || ['.', '..'].includes(requestId)) {
            throw new Error('The saved Microsoft 365 request is unavailable. Open the original conversation and try again.');
        }
        await api.requestJson('/api/m365/preferences');
        return api.requestJson(`/api/m365/requests/${encodeURIComponent(requestId)}/${action}`, {
            method: 'POST',
            body: {}
        });
    }

    function showError(element, error) {
        element.className = 'alert alert-danger mt-2 mb-0';
        element.setAttribute('role', 'alert');
        element.tabIndex = -1;
        element.textContent = error.message || 'The Microsoft 365 request could not be completed.';
        element.focus();
    }

    function renderPrompt(container, payload) {
        const prompt = makeElement('section', 'm365-connect-prompt alert alert-warning mt-2 mb-0');
        prompt.setAttribute('aria-label', 'Microsoft 365 connection required');
        prompt.appendChild(makeElement('h3', 'fs-6', 'Connect Microsoft 365'));
        prompt.appendChild(makeElement('p', 'mb-2',
            payload.message || payload.error || 'Connect your Microsoft account to continue this saved chat request.'));

        const sourceLabels = window.SimpleChatM365Approvals?.sourceLabels || {};
        const sources = Array.isArray(payload.sources) ? payload.sources : Object.keys(payload.sources || {});
        const labels = sources.map(source => Object.prototype.hasOwnProperty.call(sourceLabels, source)
            ? sourceLabels[source] : String(source));
        if (labels.length) {
            prompt.appendChild(makeElement('p', 'small mb-2', `Sources: ${labels.join(', ')}.`));
        }
        prompt.appendChild(makeElement('p', 'small mb-2',
            'Microsoft will show the requested permissions before you consent. Action capability limits, sharing acknowledgements, and workflow Run as approvals still apply. This connects your chat session, not a workflow account.'));
        const button = makeElement('button', 'btn btn-primary', 'Connect Microsoft 365');
        button.type = 'button';
        const status = makeElement('div', 'small mt-2');
        status.setAttribute('role', 'status');
        status.setAttribute('aria-live', 'polite');
        button.addEventListener('click', async () => {
            button.disabled = true;
            status.className = 'small mt-2';
            status.setAttribute('role', 'status');
            status.textContent = 'Preparing Microsoft 365 sign-in…';
            try {
                const result = await requestAction(payload.m365_request_id, 'connect');
                const target = authorizationUrl(result.authorization_url);
                status.textContent = 'Opening Microsoft 365 sign-in…';
                window.location.assign(target);
            } catch (error) {
                showError(status, error);
                button.disabled = false;
            }
        });
        prompt.append(button, status);
        container.appendChild(prompt);
        return prompt;
    }

    async function handleCallback() {
        if (callbackHandled) {
            return;
        }
        const url = new URL(window.location.href);
        const authState = url.searchParams.get('m365_auth');
        const requestId = url.searchParams.get('m365_request_id');
        if (!authState && !requestId) {
            return;
        }
        callbackHandled = true;
        const conversationId = url.searchParams.get('conversationId') || url.searchParams.get('conversation_id');
        url.searchParams.delete('m365_auth');
        url.searchParams.delete('m365_request_id');
        window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);

        const chatbox = document.getElementById('chatbox');
        if (!chatbox) {
            return;
        }
        const panel = makeElement('section', 'm-3');
        panel.id = 'm365-chat-connect-status';
        panel.setAttribute('aria-label', 'Microsoft 365 connection status');
        chatbox.before(panel);
        const status = makeElement('div', 'alert alert-info');
        status.setAttribute('role', 'status');
        status.setAttribute('aria-live', 'polite');
        panel.appendChild(status);
        if (authState !== 'connected' || !requestId || !conversationId) {
            showError(status, new Error('Microsoft 365 sign-in did not complete. Open the original conversation or Approvals to connect again.'));
            return;
        }

        const retry = makeElement('button', 'btn btn-outline-primary d-none', 'Retry resume');
        retry.type = 'button';
        const conversationLink = makeElement('a', 'btn btn-link', 'Open original conversation');
        conversationLink.href = `/chats?${new URLSearchParams({ conversationId })}`;
        panel.append(retry, conversationLink);

        async function resume() {
            retry.disabled = true;
            status.className = 'alert alert-info';
            status.setAttribute('role', 'status');
            status.textContent = 'Microsoft 365 connected. Resuming your saved request…';
            try {
                const result = await requestAction(requestId, 'resume');
                retry.classList.add('d-none');
                if (result.auth_required === true) {
                    status.textContent = 'Microsoft 365 still requires sign-in for this request.';
                    panel.querySelector('.m365-connect-prompt')?.remove();
                    renderPrompt(panel, { ...result, m365_request_id: requestId });
                    return;
                }
                const executionStatus = result.execution_status || result.status;
                if (result.resume_scheduled === true || ['queued', 'running', 'completed'].includes(executionStatus)) {
                    status.textContent = executionStatus === 'completed'
                        ? 'This request has already completed. Loading the original conversation.'
                        : 'Request queued or resuming. Its result will appear in the original conversation.';
                    window.dispatchEvent(new CustomEvent('m365-chat-resumed', {
                        detail: { requestId, conversationId }
                    }));
                } else {
                    status.className = 'alert alert-warning';
                    status.textContent = result.message || 'The request is not queued. Review its remaining approvals or current status in Approvals.';
                    const approvalsLink = makeElement('a', 'btn btn-link', 'Review Approvals');
                    approvalsLink.href = '/approvals';
                    panel.appendChild(approvalsLink);
                }
            } catch (error) {
                showError(status, error);
                retry.classList.remove('d-none');
                retry.disabled = false;
            }
        }
        retry.addEventListener('click', () => { void resume(); });
        await resume();
    }

    window.SimpleChatM365Connect = Object.freeze({ renderPrompt, handleCallback });
})();
