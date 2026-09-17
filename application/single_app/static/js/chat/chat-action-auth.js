// chat-action-auth.js
// Private action authentication is deliberately separate from messages and elicitation answers.
import {
    createIdentityCredentialField,
    getIdentityCredentialFields,
    readIdentityCredentialFields,
    wipeIdentityCredentialFields,
} from '../workspace/identity-credential-fields.js';

export const actionAuthProfiles = Object.freeze({
    yamcs_login: { authType: 'username_password', label: 'Yamcs username/password login', nativeType: 'username_password', method: 'username_password' },
    http_basic: { authType: 'username_password', label: 'Gateway HTTP Basic (not Yamcs login)', nativeType: 'basic', method: 'http_basic' },
    bearer_token: { authType: 'bearer_token', label: 'Bearer token', nativeType: 'key', method: 'bearer_token' },
    api_key: { authType: 'api_key', label: 'API key (x-api-key)', nativeType: 'key', method: 'api_key' },
});

const sharedOutputNotice = 'Your account is used for this request. Your message and returned data will be visible to everyone with access to this conversation. Your saved credentials and credential form are private.';
const authErrorMessages = {
    action_auth_rejected: 'The service rejected these credentials. Check them and try again.',
    action_auth_permission_denied: 'Your account does not have permission for this action. Changing a password may not fix this.',
    action_auth_connection_failed: 'The service could not be reached securely. Check its availability and try again.',
    action_auth_storage_unavailable: 'Your private identity could not be saved. Try again; the request has not been sent.',
    action_authentication_failed: 'The service rejected these credentials. Check them and try again.',
    authentication_failed: 'The service rejected these credentials. Check them and try again.',
    invalid_credentials: 'The service rejected these credentials. Check them and try again.',
    permission_denied: 'Your account does not have permission for this action. Changing a password may not fix this.',
    action_permission_denied: 'Your account does not have permission for this action. Changing a password may not fix this.',
    connection_failed: 'The service could not be reached. Check its availability and try again.',
    action_connection_failed: 'The service could not be reached. Check its availability and try again.',
    storage_failed: 'Your private identity could not be saved. Try again; the request has not been sent.',
    action_auth_storage_failed: 'Your private identity could not be saved. Try again; the request has not been sent.',
};

class ActionAuthRequestError extends Error {}

function selectFields(value, stringFields, booleanFields = []) {
    const result = {};
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return result;
    }
    stringFields.forEach(key => {
        if (typeof value[key] === 'string' && value[key]) {
            result[key] = value[key];
        }
    });
    booleanFields.forEach(key => {
        if (typeof value[key] === 'boolean') {
            result[key] = value[key];
        }
    });
    return result;
}

export function buildActionAuthContext(payload = {}, options = {}) {
    const conversationId = options.conversationId ?? payload.conversation_id ?? null;
    const isShared = options.conversationKind === 'collaboration'
        || payload.conversation_kind === 'collaboration'
        || Boolean(window.chatCollaboration?.isCollaborationConversation?.(conversationId));
    const context = {
        conversation_id: conversationId,
        conversation_kind: isShared ? 'collaboration' : 'personal',
    };
    const agent = selectFields(
        payload.agent_info,
        ['id', 'name', 'display_name', 'scope_type', 'scope_id', 'group_id', 'group_name'],
        ['is_global', 'is_group'],
    );
    if (agent.id || agent.name) {
        context.agent_info = agent;
    }
    if (typeof payload.action_ref === 'string' && payload.action_ref.startsWith('action:v1:')) {
        context.action_ref = payload.action_ref;
    }
    if (typeof payload.run_id === 'string' && payload.run_id) {
        context.run_id = payload.run_id;
    }
    return context;
}

export function getGlobalActionAuthReference(action) {
    if (typeof action?.action_ref === 'string' && action.action_ref.startsWith('action:v1:global:')) {
        return action.action_ref;
    }
    if (!action?.id) return null;
    const encode = value => btoa(String.fromCharCode(...new TextEncoder().encode(value)))
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    return `action:v1:global:${encode('global')}:${encode(String(action.id))}`;
}

export function isActionCredentialsRequired(value) {
    const payload = value?.streamErrorData || value?.auth_response || value;
    return payload?.error_code === 'action_credentials_required'
        || payload?.type === 'action_credentials_required';
}

export async function cancelActionAuthRequest(requestId, fetchImpl = (...args) => fetch(...args)) {
    try {
        const response = await fetchImpl(`/api/action-auth/requests/${encodeURIComponent(requestId)}/cancel`, {
            method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
            headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        if (response.ok || response.status === 404 || response.status === 410) return true;
    } catch {
        // Local cancellation already prevents execution; report an unconfirmed server cancellation.
    }
    console.warn('[ACTION_AUTH] The pending credential request could not be cancelled on the server. It will expire.');
    return false;
}

export function validateActionAuthRequirement(requirement) {
    const profile = actionAuthProfiles[requirement?.profile];
    if (!profile || requirement.auth_type !== profile.authType || !requirement.id) {
        throw new Error('This action requests an unsupported identity profile. Ask an administrator to review the action.');
    }
    const expected = getIdentityCredentialFields(profile.authType);
    const fields = requirement.fields;
    if (!Array.isArray(fields) || fields.length !== expected.length
        || expected.some(field => fields.filter(candidate => candidate.name === field.name
            && candidate.type === field.type && candidate.required === true).length !== 1)) {
        throw new Error('This action requests unsupported credential fields. No credentials will be submitted.');
    }
    let destination;
    try {
        destination = new URL(requirement.destination);
    } catch {
        throw new Error('The action has no valid credential destination.');
    }
    if (destination.protocol !== 'https:' || destination.username || destination.password
        || destination.search || destination.hash) {
        throw new Error('A verified HTTPS credential destination is required.');
    }
    return { profile, fields, destination: destination.href };
}

function safeRequestError(response, data) {
    if (authErrorMessages[data?.error_code]) {
        return authErrorMessages[data.error_code];
    }
    if (response.status === 401) {
        return 'Authentication was rejected. Check your sign-in and service credentials, then try again.';
    }
    if (response.status === 403) {
        return 'You do not have permission to use this action or identity.';
    }
    if (response.status === 409 || response.status === 410) {
        return 'This request changed or expired. Cancel and submit your draft again to check the current action.';
    }
    if (response.status >= 500) {
        return 'The connection or private identity store is unavailable. Nothing has been sent to the conversation.';
    }
    return 'The identity could not be connected. Check the required fields and try again.';
}

export class ActionAuthController {
    constructor({ root = null, fetchImpl = (...args) => fetch(...args), ownerDocument = document } = {}) {
        this.root = root;
        this.fetchImpl = fetchImpl;
        this.document = ownerDocument;
        this.active = null;
        this.onNavigation = () => this.cancel();
        this.onSelectionChange = event => {
            if (this.active && !this.root?.contains(event.target) && !this.isCurrent(this.active)) {
                this.cancel();
            }
        };
        this.onLink = event => {
            const link = event.target?.closest?.('a[href]');
            if (!this.active || !link || link.target === '_blank') {
                return;
            }
            const url = new URL(link.href, window.location.href);
            if (url.pathname !== window.location.pathname || url.search !== window.location.search) {
                this.cancel();
            }
        };
        this.onEscape = event => {
            if (event.key === 'Escape' && this.active) {
                event.preventDefault();
                this.cancel();
            }
        };
        window.addEventListener('pagehide', this.onNavigation);
        window.addEventListener('beforeunload', this.onNavigation);
        window.addEventListener('popstate', this.onNavigation);
        window.addEventListener('chat:conversation-context-changed', this.onNavigation);
        this.document.addEventListener('input', this.onSelectionChange);
        this.document.addEventListener('change', this.onSelectionChange);
        this.document.addEventListener('click', this.onLink, true);
        this.document.addEventListener('keydown', this.onEscape);
    }

    getRoot() {
        if (!this.root) {
            this.root = this.document.getElementById('chat-action-auth-root');
        }
        if (!this.root) {
            this.root = this.document.createElement('div');
            this.root.id = 'chat-action-auth-root';
            this.root.className = 'container p-3 d-none';
            this.document.body.appendChild(this.root);
        }
        return this.root;
    }

    element(tag, className = '', text = '') {
        const element = this.document.createElement(tag);
        element.className = className;
        element.textContent = text;
        return element;
    }

    button(label, className, action) {
        const button = this.element('button', className, label);
        button.type = 'button';
        button.addEventListener('click', action);
        return button;
    }

    isCurrent(active) {
        return this.active === active && active.location === window.location.href
            && (!active.isCurrent || active.isCurrent());
    }

    async authorize(payload, options = {}) {
        const context = buildActionAuthContext(payload, options);
        if (!context.agent_info && !context.action_ref && !context.run_id) {
            return {};
        }
        if (this.active) {
            return null;
        }
        return this.start(context, options);
    }

    start(context, options, control = null) {
        return new Promise(resolve => {
            const active = {
                context, resolve, requestId: control?.request_id || null, state: null,
                isCurrent: options.isCurrent, location: window.location.href,
                repair: Boolean(control), sharingAcknowledged: false, busy: false,
                executionStarted: control?.execution_started !== false,
                abortController: new AbortController(), focus: this.document.activeElement,
            };
            this.active = active;
            this.showLoading(active);
            const load = control?.request_id
                ? this.fetchState(active, `/api/action-auth/requests/${encodeURIComponent(control.request_id)}`)
                : this.fetchState(active, '/api/action-auth/preflight', 'POST', context);
            load.then(state => this.acceptState(active, state)).catch(error => this.showError(active, error.message));
        });
    }

    async fetchState(active, url, method = 'GET', payload = null) {
        let body = payload ? JSON.stringify(payload) : undefined;
        try {
            const response = await this.fetchImpl(url, {
                method, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
                headers: { 'Content-Type': 'application/json' }, body,
                signal: active.abortController.signal,
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok && !isActionCredentialsRequired(data)) {
                throw new ActionAuthRequestError(safeRequestError(response, data));
            }
            return data;
        } catch (error) {
            if (active.abortController.signal.aborted) {
                throw new Error('Connection cancelled.');
            }
            // Never render provider exceptions or a credential-bearing response.
            throw new Error(error instanceof ActionAuthRequestError
                ? error.message : 'The private connection request could not be completed. Check your connection and try again.');
        } finally {
            body = undefined;
            if (payload?.credentials) {
                Object.keys(payload.credentials).forEach(key => { payload.credentials[key] = ''; });
                delete payload.credentials;
            }
        }
    }

    shell(active) {
        const root = this.getRoot();
        wipeIdentityCredentialFields(root);
        root.replaceChildren();
        root.classList.remove('d-none');
        const card = this.element('section', 'card border-primary mb-3');
        card.setAttribute('aria-labelledby', 'action-auth-title');
        const body = this.element('div', 'card-body');
        const heading = this.element('h3', 'h5', 'Connect Yamcs');
        heading.id = 'action-auth-title';
        const badge = this.element('span', 'badge bg-secondary mb-2', 'Private to you');
        const status = this.element('div', 'alert alert-info d-none');
        status.id = 'action-auth-status';
        status.setAttribute('role', 'alert');
        body.append(heading, badge, status);
        if (active.repair) {
            body.appendChild(this.element('p', 'small', active.executionStarted
                ? 'The turn stopped for a private identity check. Connecting will not replay it. Retry explicitly after setup; earlier tool work may already have run.'
                : 'The request needs a private identity check before execution. Connecting will not send it. Retry explicitly after setup.'));
        }
        card.appendChild(body);
        root.appendChild(card);
        active.body = body;
        active.status = status;
        return body;
    }

    showLoading(active) {
        const body = this.shell(active);
        body.appendChild(this.element('p', 'text-muted', 'Checking your personal action identities…'));
        body.appendChild(this.button('Cancel', 'btn btn-outline-secondary', () => this.cancel()));
    }

    showError(active, message) {
        if (this.active !== active) {
            return;
        }
        active.busy = false;
        if (active.submit) {
            active.submit.disabled = false;
        }
        active.status.className = 'alert alert-danger';
        active.status.textContent = message;
        if (!active.state) {
            const retry = this.button('Check again', 'btn btn-outline-primary ms-2', () => this.checkAgain(active));
            active.body.appendChild(retry);
        }
    }

    acceptState(active, state) {
        if (this.active !== active) {
            return;
        }
        if (!this.isCurrent(active)) {
            this.cancel();
            return;
        }
        active.busy = false;
        active.requestId = state.request_id || active.requestId;
        active.state = state;
        if (!['ready', 'credentials_required'].includes(state.status)) {
            this.showError(active, 'This connection request is no longer active. Cancel and submit your draft again.');
            return;
        }
        if (state.status === 'ready') {
            if (active.repair || (state.shared_conversation && state.uses_personal_credentials && !active.sharingAcknowledged)) {
                this.renderReady(active);
            } else {
                this.finish(active, active.requestId ? { action_auth_request_id: active.requestId } : {});
            }
            return;
        }
        if (!active.requestId || !Array.isArray(state.requirements) || !state.requirements.length) {
            this.showError(active, 'No supported credential requirement was returned. Cancel and check again.');
            return;
        }
        this.renderRequirement(active, state.requirements[0]);
    }

    sharingNotice(active, body) {
        if (!active.state.shared_conversation || !active.state.uses_personal_credentials) {
            return null;
        }
        body.appendChild(this.element('div', 'alert alert-warning', active.state.sharing_notice || sharedOutputNotice));
        const check = this.checkbox('action-auth-sharing', 'I understand that my message and returned data will be shared.', true);
        check.input.checked = active.sharingAcknowledged;
        body.appendChild(check.wrapper);
        return check.input;
    }

    checkbox(id, label, required = false) {
        const wrapper = this.element('div', 'form-check mb-3');
        const input = this.element('input', 'form-check-input');
        input.type = 'checkbox';
        input.id = id;
        input.required = required;
        const text = this.element('label', 'form-check-label', label);
        text.htmlFor = id;
        wrapper.append(input, text);
        return { wrapper, input };
    }

    renderReady(active) {
        const body = this.shell(active);
        if (active.repair) {
            body.appendChild(this.element('div', 'alert alert-success', 'Your private identity is ready. Use Retry or submit your draft when you are ready; no turn has been replayed.'));
            body.appendChild(this.button('Done', 'btn btn-primary', () => this.finish(active, null)));
            return;
        }
        const shared = this.sharingNotice(active, body);
        const proceed = this.button('Continue with my account', 'btn btn-primary me-2', () => {
            if (shared && !shared.checked) {
                shared.reportValidity();
                return;
            }
            active.sharingAcknowledged = true;
            this.checkAgain(active);
        });
        body.append(proceed, this.button('Cancel', 'btn btn-outline-secondary', () => this.cancel()));
        proceed.focus();
    }

    renderRequirement(active, requirement) {
        const body = this.shell(active);
        const cancel = this.button('Cancel', 'btn btn-outline-secondary', () => this.cancel());
        let registered;
        try {
            registered = validateActionAuthRequirement(requirement);
        } catch (error) {
            body.appendChild(cancel);
            this.showError(active, error.message);
            return;
        }
        body.append(
            this.element('p', 'mb-1', `Global action: ${requirement.action_name || 'Yamcs'}`),
            this.element('p', 'mb-1', `Required personal identity: ${requirement.identity_name}`),
            this.element('p', 'mb-1', `Authentication: ${registered.profile.label}`),
            this.element('p', 'text-break', `Credential destination: ${registered.destination}`),
        );
        const credentialsRejected = requirement.reason === 'authentication_rejected';
        if (credentialsRejected) {
            const warning = this.element('p', 'alert alert-warning', 'Yamcs rejected the saved credentials for this action. Select an identity and enter replacement credentials, or create a new personal identity.');
            warning.id = 'action-auth-rejection';
            body.appendChild(warning);
        }
        const form = this.element('form');
        form.autocomplete = 'off';
        form.setAttribute('aria-label', 'Private Yamcs credentials');
        const shared = this.sharingNotice(active, form);
        const selectorLabel = this.element('label', 'form-label', 'Your personal identity');
        selectorLabel.htmlFor = 'action-auth-identity';
        const selector = this.element('select', 'form-select mb-3');
        selector.id = 'action-auth-identity';
        selector.required = true;
        if (credentialsRejected) {
            selector.setAttribute('aria-describedby', 'action-auth-rejection');
        }
        const candidates = (requirement.identities || []).filter(identity => identity.id && identity.auth_type === requirement.auth_type);
        const placeholder = this.element('option', '', 'Choose an existing identity or create one');
        placeholder.value = '';
        selector.appendChild(placeholder);
        candidates.forEach(identity => {
            const option = this.element('option', '', identity.name || 'Personal identity');
            option.value = identity.id;
            selector.appendChild(option);
        });
        const newOption = this.element('option', '', `Create “${requirement.identity_name}” for Actions`);
        newOption.value = '__create__';
        selector.appendChild(newOption);
        if (!candidates.length) {
            selector.value = '__create__';
        }
        const replace = this.checkbox('action-auth-replace', 'Replace the selected identity’s credentials');
        replace.input.checked = credentialsRejected;
        replace.input.disabled = credentialsRejected;
        const fields = this.element('div', 'row g-3 mb-3');
        const inputs = {};
        registered.fields.forEach(field => {
            const control = createIdentityCredentialField({
                ...field, id: `action-auth-${field.name}`, ownerDocument: this.document,
            });
            inputs[field.name] = control.input;
            fields.appendChild(control.wrapper);
        });
        const updateMode = () => {
            wipeIdentityCredentialFields(fields);
            const creating = selector.value === '__create__';
            const entering = creating || (Boolean(selector.value) && (credentialsRejected || replace.input.checked));
            replace.wrapper.classList.toggle('d-none', !selector.value || creating);
            fields.classList.toggle('d-none', !entering);
            Object.values(inputs).forEach(input => { input.disabled = !entering; });
        };
        selector.addEventListener('change', updateMode);
        replace.input.addEventListener('change', updateMode);
        updateMode();
        const approval = this.checkbox('action-auth-destination', 'I approve sending this identity’s credentials to the destination shown above.', true);
        form.append(selectorLabel, selector, replace.wrapper, fields, approval.wrapper);
        form.appendChild(this.element('p', 'small text-muted', 'Saved only in your personal Workspace Identities, using the existing secret-storage policy. These fields are never posted to chat.'));
        const submit = this.element('button', 'btn btn-primary', active.repair ? 'Save connection' : 'Save and continue');
        submit.type = 'submit';
        active.submit = submit;
        const checkAgain = this.button('Check again', 'btn btn-outline-primary', () => this.checkAgain(active));
        const actions = this.element('div', 'd-flex flex-wrap gap-2');
        actions.append(submit, checkAgain, cancel);
        form.appendChild(actions);
        form.addEventListener('submit', async event => {
            event.preventDefault();
            event.stopPropagation?.();
            if (active.busy || !this.isCurrent(active) || !form.reportValidity()) {
                return;
            }
            active.busy = true;
            submit.disabled = true;
            checkAgain.disabled = true;
            const payload = { requirement_id: requirement.id, confirm_destination: approval.input.checked };
            if (selector.value !== '__create__') {
                payload.identity_id = selector.value;
            }
            if (selector.value === '__create__' || credentialsRejected || replace.input.checked) {
                payload.credentials = readIdentityCredentialFields(requirement.auth_type, inputs);
            }
            active.sharingAcknowledged = !shared || shared.checked;
            wipeIdentityCredentialFields(fields);
            try {
                const state = await this.fetchState(active, `/api/action-auth/requests/${encodeURIComponent(active.requestId)}/credentials`, 'POST', payload);
                this.acceptState(active, state);
            } catch (error) {
                this.showError(active, error.message);
            } finally {
                checkAgain.disabled = false;
            }
        });
        body.appendChild(form);
        this.manualHelp(body, requirement.identity_name, registered.profile.authType);
        (selector.value === '__create__' ? Object.values(inputs)[0] : selector).focus();
    }

    manualHelp(body, identityName, authType) {
        const help = this.element('details', 'mt-3');
        help.appendChild(this.element('summary', '', 'Manual 1–2–3 setup'));
        const steps = this.element('ol', 'small mt-2');
        const first = this.element('li');
        const setupUrl = this.getRoot().dataset.identitySetupUrl;
        if (setupUrl === '/workspace?tab=identities') {
            const link = this.element('a', '', 'Open Your Workspace → Identities in a new tab');
            link.href = setupUrl;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            first.appendChild(link);
        } else {
            first.textContent = 'Your personal Identities workspace is not available here. Use this private connection form instead.';
        }
        steps.append(
            first,
            this.element('li', '', `Add an identity named “${identityName}” with Actions usage and ${authType === 'username_password' ? 'Username and password' : authType === 'api_key' ? 'API key' : 'Bearer token'} authentication.`),
            this.element('li', '', 'Save it, return here, choose Check again, then approve the destination.'),
        );
        help.appendChild(steps);
        body.appendChild(help);
    }

    async checkAgain(active) {
        if (active.busy || !this.isCurrent(active)) {
            return;
        }
        active.busy = true;
        wipeIdentityCredentialFields(this.root);
        try {
            const state = active.requestId
                ? await this.fetchState(active, `/api/action-auth/requests/${encodeURIComponent(active.requestId)}`)
                : await this.fetchState(active, '/api/action-auth/preflight', 'POST', active.context);
            this.acceptState(active, state);
        } catch (error) {
            this.showError(active, error.message);
        }
    }

    finish(active, receipt) {
        if (this.active !== active) {
            return;
        }
        const current = this.isCurrent(active);
        this.active = null;
        wipeIdentityCredentialFields(this.root);
        this.root?.replaceChildren();
        this.root?.classList.add('d-none');
        if (active.focus?.isConnected) {
            active.focus.focus();
        }
        active.resolve(current ? receipt : null);
    }

    cancel() {
        const active = this.active;
        if (!active) {
            return;
        }
        active.abortController.abort();
        this.finish(active, null);
        if (active.requestId) {
            void cancelActionAuthRequest(active.requestId, this.fetchImpl);
        }
    }

    repair(control, options = {}) {
        this.cancel();
        const context = buildActionAuthContext(options.payload || {}, options);
        if (control.execution_started === true && typeof control.action_ref === 'string'
            && control.action_ref.startsWith('action:v1:')) {
            context.action_ref = control.action_ref;
            delete context.agent_info;
            delete context.run_id;
            control = { ...control, request_id: null };
        }
        return this.start(context, options, control);
    }

    destroy() {
        this.cancel();
        window.removeEventListener('pagehide', this.onNavigation);
        window.removeEventListener('beforeunload', this.onNavigation);
        window.removeEventListener('popstate', this.onNavigation);
        window.removeEventListener('chat:conversation-context-changed', this.onNavigation);
        this.document.removeEventListener('input', this.onSelectionChange);
        this.document.removeEventListener('change', this.onSelectionChange);
        this.document.removeEventListener('click', this.onLink, true);
        this.document.removeEventListener('keydown', this.onEscape);
    }
}

let chatController;

export function getActionAuthController() {
    chatController ||= new ActionAuthController();
    return chatController;
}

export async function prepareActionAuthExecution(payload, options = {}) {
    const receipt = await getActionAuthController().authorize(payload, options);
    if (receipt === null) {
        return false;
    }
    delete payload.action_auth_request_id;
    Object.assign(payload, receipt);
    return true;
}

export function handleActionAuthRequired(value, options = {}) {
    if (!isActionCredentialsRequired(value)) {
        return false;
    }
    if (options.isCurrent && !options.isCurrent()) return true;
    const control = value?.streamErrorData || value?.auth_response || value;
    void getActionAuthController().repair(control, options);
    return true;
}

// Executable plans use the same metadata-only gate; planning/elicitation never receives credentials.
export async function executeWithActionAuth(payload, execute, options = {}) {
    if (!await prepareActionAuthExecution(payload, options)) {
        return false;
    }
    return execute(payload);
}
