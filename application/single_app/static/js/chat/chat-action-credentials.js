// chat-action-credentials.js
// Bootstrap task UI; credential inputs belong only to this form, never a chat draft.
(() => {
    'use strict';

    const cards = new Map();
    const authTypes = new Set(['username_password', 'api_key', 'bearer_token']);
    let conversationId = null;
    let epoch = 0;
    let sequence = 0;
    let csrfToken = null;
    let continuationConsumer = null;
    let pendingController = null;

    function node(tag, className = '', text = '') {
        const element = document.createElement(tag);
        element.className = className;
        element.textContent = text;
        return element;
    }

    function active(id, capturedEpoch = epoch) {
        return capturedEpoch === epoch && id === conversationId
            && id === window.currentConversationId;
    }

    function clearInputs(card) {
        card.querySelectorAll('input').forEach(input => { input.value = ''; });
    }

    function removeCard(id) {
        const state = cards.get(id);
        if (!state) return;
        clearInputs(state.card);
        state.controller?.abort();
        state.card.remove();
        cards.delete(id);
    }

    function clear() {
        epoch += 1;
        pendingController?.abort();
        pendingController = null;
        Array.from(cards.keys()).forEach(removeCard);
        document.getElementById('chat-action-credentials')?.remove();
        conversationId = null;
        csrfToken = null;
    }

    function safeRequest(value) {
        if (!value || typeof value.id !== 'string' || typeof value.etag !== 'string'
            || typeof value.conversation_id !== 'string' || !Array.isArray(value.requirements)
            || !Array.isArray(value.identities)) return null;
        const requirements = value.requirements.filter(requirement =>
            requirement && ['service', 'proxy'].includes(requirement.slot) && authTypes.has(requirement.auth_type)
            && (requirement.slot !== 'proxy' || requirement.auth_type === 'username_password'));
        if (requirements.length !== value.requirements.length
            || new Set(requirements.map(item => item.slot)).size !== requirements.length) return null;
        return {
            id: value.id,
            etag: value.etag,
            conversation_id: value.conversation_id,
            action_name: typeof value.action_name === 'string' ? value.action_name : 'Action',
            destination_label: typeof value.destination_label === 'string' ? value.destination_label : 'Configured service',
            reason: typeof value.reason === 'string' ? value.reason : 'setup_required',
            status: value.status,
            requirements: requirements.map(item => ({
                slot: item.slot, auth_type: item.auth_type,
                label: typeof item.label === 'string' ? item.label : '',
            })),
            identities: value.identities.filter(identity =>
                identity && typeof identity.id === 'string' && typeof identity.name === 'string' && authTypes.has(identity.auth_type))
                .map(identity => ({
                    id: identity.id, name: identity.name, auth_type: identity.auth_type,
                    etag: typeof identity.etag === 'string' ? identity.etag : null,
                })),
        };
    }

    function safeError(status) {
        if (status === 401 || status === 403) return 'Your session or access has changed. Sign in again or reopen the original conversation.';
        if (status === 409 || status === 410 || status === 412) return 'This request has changed or expired. Refresh the request before continuing.';
        return 'Unable to complete this request. Check your connection and try again.';
    }

    async function request(path, options = {}) {
        const capturedEpoch = epoch;
        const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
        if (csrfToken) headers['X-CSRFToken'] = csrfToken;
        const response = await fetch(path, {
            ...options, headers, credentials: 'same-origin', cache: 'no-store',
            body: options.body ? JSON.stringify(options.body) : undefined,
        });
        if (!response.ok) throw new Error(safeError(response.status));
        const result = await response.json();
        if (capturedEpoch === epoch && typeof result.csrf_token === 'string') csrfToken = result.csrf_token;
        return result;
    }

    function endpoint(id, action = '') {
        return `/api/action-credentials/${encodeURIComponent(id)}${action ? `/${action}` : ''}`;
    }

    function root() {
        const chatbox = document.getElementById('chatbox');
        if (!chatbox) return null;
        let container = document.getElementById('chat-action-credentials');
        if (!container) {
            container = node('section', 'my-3');
            container.id = 'chat-action-credentials';
            container.setAttribute('aria-label', 'Private action credential requests');
            chatbox.appendChild(container);
        }
        return container;
    }

    function field(parent, labelText, type, required = true) {
        const group = node('div', 'mb-3');
        const input = node('input', 'form-control');
        input.id = `action-credential-field-${++sequence}`;
        input.type = type;
        input.required = required;
        input.autocomplete = type === 'password' ? 'new-password' : 'off';
        input.maxLength = type === 'password' ? 8192 : 256;
        const label = node('label', 'form-label', labelText);
        label.htmlFor = input.id;
        group.append(label, input);
        parent.appendChild(group);
        return input;
    }

    function render(value) {
        const dto = safeRequest(value);
        if (!dto || !active(dto.conversation_id)) return;
        if (!['pending', 'ready'].includes(dto.status)) {
            removeCard(dto.id);
            return;
        }
        const previous = cards.get(dto.id);
        if (previous?.dto.etag === dto.etag && previous.card.isConnected) return;
        removeCard(dto.id);
        const container = root();
        if (!container) return;
        const capturedEpoch = epoch;
        const card = node('article', 'card text-break mb-3');
        card.dataset.credentialRequestId = dto.id;
        const body = node('div', 'card-body');
        const title = node('h3', 'h5', `Connect to ${dto.action_name}`);
        title.id = `action-credential-heading-${++sequence}`;
        card.setAttribute('aria-labelledby', title.id);
        const reasonLabels = {
            credentials_rejected: 'Your saved credentials were rejected. Review or replace your personal identity.',
            credentials_expired: 'Your saved credentials have expired. Provide a current personal identity.',
            binding_changed: 'The action connection changed. Confirm credentials for the destination below.',
            identity_removed: 'The previously selected identity is no longer available.',
        };
        const reason = node('p', 'mb-2', reasonLabels[dto.reason] || 'This action needs your personal credentials before it can continue.');
        const destination = node('p', 'fw-semibold mb-2', `Destination: ${dto.destination_label}`);
        const privacy = node('p', 'small text-body-secondary', 'Credentials are saved in your personal identity, not in chat messages or the shared action.');
        const form = node('form');
        form.autocomplete = 'off';
        const sections = [];
        if (dto.status !== 'ready') {
            dto.requirements.forEach(requirement => {
                const section = node('fieldset', 'border-0 p-0 mb-3');
                section.appendChild(node('legend', 'h6', requirement.label || (requirement.slot === 'proxy' ? 'Proxy sign-in' : 'Yamcs sign-in')));
                const select = node('select', 'form-select mb-3');
                select.id = `action-credential-identity-${++sequence}`;
                const selectLabel = node('label', 'form-label', 'Personal identity');
                selectLabel.htmlFor = select.id;
                const createOption = node('option', '', 'Create a new personal identity');
                createOption.value = '';
                select.appendChild(createOption);
                dto.identities.filter(identity => identity.auth_type === requirement.auth_type).forEach(identity => {
                    const option = node('option', '', identity.name);
                    option.value = identity.id;
                    select.appendChild(option);
                });
                const inputs = node('div');
                const name = field(inputs, 'Identity name', 'text');
                const username = requirement.auth_type === 'username_password' ? field(inputs, 'Username', 'text') : null;
                const secret = field(inputs, requirement.auth_type === 'username_password' ? 'Password'
                    : (requirement.auth_type === 'api_key' ? 'API key' : 'Bearer token'), 'password');
                const rotateGroup = node('div', 'form-check mb-3 d-none');
                const rotate = node('input', 'form-check-input');
                rotate.type = 'checkbox';
                rotate.id = `action-credential-rotate-${++sequence}`;
                const rotateLabel = node('label', 'form-check-label', 'Replace credentials in this personal identity');
                rotateLabel.htmlFor = rotate.id;
                rotateGroup.append(rotate, rotateLabel);
                function updateInputs() {
                    clearInputs(inputs);
                    const identity = dto.identities.find(item => item.id === select.value);
                    rotateGroup.classList.toggle('d-none', !identity?.etag);
                    const enteringCredentials = !select.value || rotate.checked;
                    inputs.classList.toggle('d-none', !enteringCredentials);
                    name.parentElement.classList.toggle('d-none', Boolean(select.value));
                    name.required = !select.value;
                    if (username) username.required = enteringCredentials;
                    secret.required = enteringCredentials;
                }
                select.addEventListener('change', () => {
                    rotate.checked = false;
                    updateInputs();
                });
                rotate.addEventListener('change', updateInputs);
                section.append(selectLabel, select, rotateGroup, inputs);
                form.appendChild(section);
                sections.push({ requirement, select, name, username, secret, rotate });
            });
        }
        const status = node('p', 'small mb-2 d-none');
        status.setAttribute('role', 'status');
        status.setAttribute('aria-live', 'polite');
        const error = node('div', 'alert alert-danger d-none');
        error.setAttribute('role', 'alert');
        error.tabIndex = -1;
        const controls = node('div', 'd-flex flex-wrap gap-2');
        const save = node('button', 'btn btn-primary', 'Save and continue');
        save.type = 'submit';
        const cancel = node('button', 'btn btn-outline-secondary', 'Cancel');
        cancel.type = 'button';
        const refresh = node('button', 'btn btn-outline-secondary d-none', 'Refresh request');
        refresh.type = 'button';
        controls.append(save, cancel, refresh);
        form.append(status, error, controls);
        body.append(title, reason, destination, privacy, form);
        card.appendChild(body);
        container.appendChild(card);
        const state = { dto, card, controller: new AbortController() };
        cards.set(dto.id, state);

        function busy(value, message = '') {
            form.querySelectorAll('input, select, button').forEach(input => { input.disabled = value; });
            card.setAttribute('aria-busy', String(value));
            status.textContent = message;
            status.classList.toggle('d-none', !message);
            error.classList.add('d-none');
        }

        function failed(message) {
            if (!active(dto.conversation_id, capturedEpoch) || !card.isConnected) return;
            busy(false);
            clearInputs(card);
            error.textContent = message;
            error.classList.remove('d-none');
            refresh.classList.remove('d-none');
            error.focus();
        }

        refresh.addEventListener('click', () => {
            removeCard(dto.id);
            void fetchRequest(dto.id);
        });
        cancel.addEventListener('click', async () => {
            clearInputs(card);
            busy(true, 'Cancelling…');
            try {
                await request(endpoint(dto.id, 'cancel'), {
                    method: 'POST', body: { expected_etag: state.dto.etag }, signal: state.controller.signal,
                });
                removeCard(dto.id);
            } catch {
                failed('Unable to cancel this request. Refresh the request and try again.');
            }
        });
        form.addEventListener('submit', async event => {
            event.preventDefault();
            if ((state.dto.status !== 'ready' && !form.reportValidity()) || !active(dto.conversation_id, capturedEpoch)) return;
            if (typeof continuationConsumer !== 'function') {
                failed('The chat connection is not ready. Reload the conversation before continuing.');
                return;
            }
            const slots = sections.map(({ requirement, select, name, username, secret, rotate }) => {
                const slot = { slot: requirement.slot };
                if (select.value) {
                    slot.identity_id = select.value;
                    if (!rotate.checked) return slot;
                    slot.expected_identity_etag = dto.identities.find(identity => identity.id === select.value)?.etag;
                } else {
                    slot.name = name.value.trim();
                }
                slot.credentials = username
                    ? { auth_type: requirement.auth_type, username: username.value.trim(), password: secret.value }
                    : { auth_type: requirement.auth_type, secret: secret.value };
                return slot;
            });
            clearInputs(card);
            busy(true, state.dto.status === 'ready' ? 'Continuing…' : 'Saving your personal identity…');
            try {
                if (state.dto.status !== 'ready') {
                    const result = await request(endpoint(dto.id, 'submit'), {
                        method: 'POST', body: { expected_etag: state.dto.etag, slots }, signal: state.controller.signal,
                    });
                    const updated = safeRequest(result.credential_request);
                    if (!updated || updated.id !== dto.id || updated.conversation_id !== dto.conversation_id || updated.status !== 'ready') {
                        throw new Error('Credentials could not be confirmed. Refresh the request before continuing.');
                    }
                    state.dto = updated;
                    form.querySelectorAll('fieldset').forEach(section => {
                        section.classList.add('d-none');
                        section.querySelectorAll('input').forEach(input => { input.required = false; });
                    });
                }
                clearInputs(card);
                slots.length = 0;
                if (!active(dto.conversation_id, capturedEpoch)) return;
                status.textContent = 'Continuing the blocked action…';
                await continuationConsumer(async signal => {
                    const response = await fetch(endpoint(dto.id, 'continue'), {
                        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken || '' },
                        credentials: 'same-origin', cache: 'no-store',
                        body: JSON.stringify({ expected_etag: state.dto.etag }), signal,
                    });
                    if (!response.ok) throw new Error(safeError(response.status));
                    if (!active(dto.conversation_id, capturedEpoch)) {
                        await response.body?.cancel();
                        throw new Error('The active conversation changed.');
                    }
                    return response;
                }, dto.conversation_id);
                if (active(dto.conversation_id, capturedEpoch) && cards.get(dto.id) === state) removeCard(dto.id);
            } catch (failure) {
                failed(failure.message === safeError(409) ? failure.message
                    : 'Unable to save or continue. Refresh the request to check its current status, then try again.');
            } finally {
                clearInputs(card);
                slots.length = 0;
            }
        });
    }

    async function fetchRequest(id) {
        const capturedEpoch = epoch;
        const loading = node('p', 'small', 'Loading private credential request…');
        loading.setAttribute('role', 'status');
        root()?.appendChild(loading);
        try {
            const result = await request(endpoint(id));
            if (capturedEpoch === epoch) render(result.credential_request);
        } catch {
            if (capturedEpoch !== epoch) return;
            const container = root();
            if (container) {
                const error = node('div', 'alert alert-warning', 'Unable to load the private credential request. Reopen this conversation to try again.');
                error.setAttribute('role', 'alert');
                const retry = node('button', 'btn btn-sm btn-outline-secondary ms-2', 'Retry');
                retry.type = 'button';
                retry.addEventListener('click', () => {
                    error.remove();
                    void fetchRequest(id);
                });
                error.appendChild(retry);
                container.appendChild(error);
            }
        } finally {
            loading.remove();
        }
    }

    async function refreshConversation(id) {
        if (id !== window.currentConversationId) return;
        if (conversationId !== id) {
            clear();
            conversationId = id;
        }
        if (!id) return;
        pendingController?.abort();
        pendingController = new AbortController();
        const controller = pendingController;
        const capturedEpoch = epoch;
        try {
            const result = await request(`/api/action-credentials/pending?conversation_id=${encodeURIComponent(id)}`, {
                signal: controller.signal,
            });
            if (!active(id, capturedEpoch)) return;
            const requestIds = new Set((result.requests || []).map(item => item.id));
            Array.from(cards.keys()).filter(requestId => !requestIds.has(requestId)).forEach(removeCard);
            (result.requests || []).forEach(render);
        } catch {
            if (!active(id, capturedEpoch) || controller.signal.aborted) return;
            const warning = node('div', 'alert alert-warning', 'Private action credential requests could not be refreshed.');
            warning.setAttribute('role', 'alert');
            const retry = node('button', 'btn btn-sm btn-outline-secondary ms-2', 'Retry');
            retry.type = 'button';
            retry.addEventListener('click', () => {
                warning.remove();
                void refreshConversation(id);
            });
            warning.appendChild(retry);
            root()?.appendChild(warning);
        }
    }

    function handleEvent(payload) {
        const dto = safeRequest(payload?.credential_request);
        if (!dto || dto.conversation_id !== window.currentConversationId) return false;
        if (conversationId !== dto.conversation_id) {
            clear();
            conversationId = dto.conversation_id;
        }
        // Read again for the session CSRF token and the current ETag, not the SSE revision.
        void fetchRequest(dto.id);
        return true;
    }

    window.SimpleChatActionCredentials = {
        handleEvent, refreshConversation, clear,
        setContinuationConsumer(consumer) { continuationConsumer = consumer; },
    };
    window.addEventListener('chat:conversation-context-changed', clear);
    window.addEventListener('pagehide', clear);
    window.addEventListener('beforeunload', clear);
    window.addEventListener('simplechat:signout', clear);
    document.addEventListener('click', event => {
        const link = event.target.closest?.('a[href]');
        if (link && /logout|signout|sign-out/i.test(link.getAttribute('href'))) clear();
    }, true);
    new MutationObserver(() => {
        cards.forEach((state, id) => {
            if (!state.card.isConnected) removeCard(id);
        });
    }).observe(document.documentElement, { childList: true, subtree: true });
})();
