// chat-action-recovery.js
// Decisions here apply only before a model or action has run.

let csrfToken = '';
let resumeRequest = null;
let decision = null;
let activeNotice = null;
let restoreController = null;
let contextRevision = 0;
const storageKey = conversationId => `simplechat.action-recovery.${conversationId}`;

function node(tag, className, text) {
    const element = document.createElement(tag);
    element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
}

async function api(path, body, signal) {
    const response = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) {
        throw new Error([404, 409, 410].includes(response.status)
            ? 'Action recovery changed, expired, or is no longer permitted. Recheck this agent.'
            : 'Action recovery could not be confirmed. Retry safely.');
    }
    return response.json();
}

async function initialize(signal) {
    const revision = contextRevision;
    const context = await api('/api/action-recovery/context', undefined, signal);
    if (signal?.aborted || revision !== contextRevision) {
        throw new Error('The selected chat context changed. Recheck before sending.');
    }
    if (typeof context.csrf_token !== 'string' || !context.csrf_token) {
        throw new Error('Action recovery could not be initialized.');
    }
    csrfToken = context.csrf_token;
}

export function actionRecoveryHeaders() {
    return csrfToken ? { 'X-CSRFToken': csrfToken } : {};
}

export function getActionRecoveryRevision() {
    return contextRevision;
}

function safeEditUrl(value) {
    return typeof value === 'string'
        && /^\/v2\/(?:workspace\/actions\/|groups\/[^/\\]+\/actions\/|admin\/actions\/)[^/\\?#]+$/.test(value)
        ? value : null;
}

function content(recovery, body) {
    const root = node('div', 'text-break');
    root.append(node('p', '', recovery.ready
        ? `${recovery.agent_name}: actions are available again. Your message has not been sent.`
        : `${recovery.agent_name}: no model or action has run.`));
    if (recovery.all_actions_unavailable) {
        root.append(node('p', 'fw-semibold', 'All assigned actions are unavailable. Continuing cannot use any of them.'));
    }
    const list = node('ul', 'list-unstyled');
    for (const action of recovery.actions) {
        const row = node('li', 'border-bottom py-3');
        row.append(node('h3', 'h6', action.name), node('p', 'small text-body-secondary', `${action.scope} action`),
            node('p', '', action.reason));
        const capabilities = Array.isArray(action.capabilities)
            ? action.capabilities.filter(value => typeof value === 'string') : ['All configured operations for this action'];
        row.append(node('p', 'small text-body-secondary', `Unavailable: ${capabilities.join(', ')}`));
        const controls = node('div', 'd-flex flex-wrap align-items-center gap-3');
        const link = safeEditUrl(action.edit_url);
        if (link) {
            const open = node('a', '', 'Open action in a new tab');
            open.href = link;
            open.target = '_blank';
            open.rel = 'noopener noreferrer';
            controls.append(open);
        } else {
            row.append(node('p', '', "Contact the action's owner or administrator to review its configuration."));
        }
        if (action.can_report) {
            const report = node('button', 'btn btn-outline-secondary btn-sm', 'Notify owner/admin');
            report.type = 'button';
            const status = node('span', 'small');
            status.setAttribute('role', 'status');
            report.addEventListener('click', async () => {
                report.disabled = true;
                status.textContent = 'Sending report...';
                try {
                    const result = await api(`/api/action-recovery/${encodeURIComponent(recovery.id)}/report`, {
                        action_key: action.key,
                    });
                    if (result.reported !== true) throw new Error('Delivery could not be confirmed.');
                    report.textContent = 'Reported';
                    status.textContent = 'Reported';
                } catch {
                    report.disabled = false;
                    status.textContent = 'Delivery uncertain. Retry safely.';
                }
            });
            controls.append(report, status);
        }
        row.append(controls);
        list.append(row);
    }
    root.append(list);
    const details = node('details', '');
    details.append(node('summary', '', 'Preserved unsent message'), node('p', 'text-break mt-2', body.message || ''));
    root.append(details, node('p', 'small text-body-secondary mt-3',
        'Existing sign-in, credential and approval prompts still apply when an available action is used. This choice never retries a calendar or email operation.'));
    return root;
}

function readRecovery(value) {
    if (value?.type !== 'action_recovery_required') return null;
    if (typeof value.id !== 'string' || typeof value.conversation_id !== 'string'
        || typeof value.agent_name !== 'string' || !Array.isArray(value.actions)
        || (!value.actions.length && value.ready !== true)
        || typeof value.all_actions_unavailable !== 'boolean'
        || value.actions.some(action => typeof action?.key !== 'string' || typeof action.name !== 'string'
            || typeof action.reason !== 'string' || typeof action.scope !== 'string'
            || typeof action.can_report !== 'boolean')) {
        throw new Error('Action availability could not be read. Recheck this agent.');
    }
    return value;
}

export function showActionRecovery(value, body, revision = contextRevision) {
    if (revision !== contextRevision) return true;
    const recovery = readRecovery(value);
    if (!recovery) return false;
    sessionStorage.setItem(storageKey(recovery.conversation_id), recovery.id);
    if (window.currentConversationId !== recovery.conversation_id) return true;
    document.getElementById('action-recovery-notice')?.remove();
    const notice = node('section', 'alert alert-warning my-2');
    notice.id = 'action-recovery-notice';
    notice.setAttribute('aria-label', 'Unavailable actions');
    notice.append(node('h2', 'h6', recovery.ready
        ? 'Your unsent request is ready to recheck' : 'This agent has unavailable actions'), content(recovery, body));
    const recheck = node('button', 'btn btn-outline-secondary mt-2', 'Recheck and send preserved request');
    recheck.type = 'button';
    recheck.addEventListener('click', () => {
        if (window.currentConversationId === recovery.conversation_id && resumeRequest) resumeRequest(body);
    });
    notice.append(recheck);
    document.getElementById('chatbox')?.before(notice);
    activeNotice = notice;
    return true;
}

function showRecoveryError(body) {
    if (window.currentConversationId !== body.conversation_id) return;
    const notice = activeNotice || node('section', 'alert alert-warning my-2');
    notice.id = 'action-recovery-notice';
    const error = node('p', '', 'Action availability could not be confirmed. Your message has not been sent. Recheck before sending.');
    error.setAttribute('role', 'alert');
    notice.querySelector('[role="alert"]')?.remove();
    notice.append(error);
    if (!activeNotice) {
        const message = node('p', 'text-break', body.message || '');
        const recheck = node('button', 'btn btn-outline-secondary', 'Recheck and send preserved request');
        recheck.type = 'button';
        recheck.addEventListener('click', () => {
            if (window.currentConversationId === body.conversation_id) resumeRequest?.(body);
        });
        notice.append(message, recheck);
        document.getElementById('chatbox')?.before(notice);
        activeNotice = notice;
    }
}

function askDecision(recovery, body, signal) {
    return new Promise(resolve => {
        const modal = node('div', 'modal fade');
        modal.tabIndex = -1;
        modal.setAttribute('aria-label', 'This agent has unavailable actions');
        const dialog = node('div', 'modal-dialog modal-dialog-scrollable');
        const panel = node('div', 'modal-content');
        const header = node('div', 'modal-header');
        header.append(node('h2', 'modal-title h5', 'This agent has unavailable actions'));
        const main = node('div', 'modal-body');
        main.append(content(recovery, body));
        const footer = node('div', 'modal-footer');
        for (const [choice, label] of [
            ['cancel', 'Cancel / choose another agent'], ['recheck', 'Recheck'],
            ['continue', 'Continue without these actions'],
        ]) {
            const button = node('button', choice === 'continue' ? 'btn btn-primary' : 'btn btn-outline-secondary', label);
            button.type = 'button';
            button.addEventListener('click', () => finish(choice));
            footer.append(button);
        }
        panel.append(header, main, footer);
        dialog.append(panel);
        modal.append(dialog);
        document.body.append(modal);
        const instance = new bootstrap.Modal(modal);
        const opener = document.activeElement;
        let resolved = false;
        const finish = (choice, hide = true) => {
            if (resolved) return;
            resolved = true;
            signal?.removeEventListener('abort', cancel);
            if (decision === finish) decision = null;
            if (hide) instance.hide();
            resolve(choice);
        };
        const cancel = () => finish('cancel');
        decision = finish;
        modal.addEventListener('hide.bs.modal', () => finish('cancel', false));
        modal.addEventListener('hidden.bs.modal', () => {
            instance.dispose();
            modal.remove();
            if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
        }, { once: true });
        modal.addEventListener('shown.bs.modal', () => {
            if (resolved) instance.hide();
            else footer.querySelector('button')?.focus();
        }, { once: true });
        signal?.addEventListener('abort', cancel, { once: true });
        instance.show();
        if (signal?.aborted) cancel();
    });
}

export async function prepareActionRequest(original, signal) {
    if (!original.agent_info || !original.conversation_id) return original;
    const revision = contextRevision;
    const body = { ...original, action_recovery_nonce: original.action_recovery_nonce || crypto.randomUUID() };
    try {
        await initialize(signal);
    } catch (error) {
        if (!signal?.aborted && revision === contextRevision) showRecoveryError(body);
        throw error;
    }
    if (signal?.aborted || revision !== contextRevision) return null;
    if (body.action_recovery) return body;
    for (;;) {
        let value;
        try {
            value = await api('/api/chat/action-health', { request: body }, signal);
        } catch (error) {
            if (!signal?.aborted && revision === contextRevision) showRecoveryError(body);
            throw error;
        }
        if (signal?.aborted || revision !== contextRevision || window.currentConversationId !== body.conversation_id) return null;
        const recovery = readRecovery(value);
        if (!recovery) {
            if (!['ready', 'not_checked'].includes(value.state)) throw new Error('Action availability could not be confirmed.');
            sessionStorage.removeItem(storageKey(body.conversation_id));
            activeNotice?.remove();
            activeNotice = null;
            return body;
        }
        showActionRecovery(recovery, body);
        const choice = await askDecision(recovery, body, signal);
        if (choice === 'cancel' || signal?.aborted || revision !== contextRevision) return null;
        if (choice === 'continue') {
            activeNotice?.remove();
            activeNotice = null;
            sessionStorage.removeItem(storageKey(body.conversation_id));
            return { ...body, action_recovery: { id: recovery.id, decision: 'continue' } };
        }
    }
}

export function setActionRecoveryResume(callback) {
    resumeRequest = callback;
}

async function restoreConversation() {
    contextRevision += 1;
    decision?.('cancel');
    restoreController?.abort();
    const controller = new AbortController();
    restoreController = controller;
    activeNotice?.remove();
    activeNotice = null;
    const conversationId = window.currentConversationId;
    if (!conversationId) return;
    const id = sessionStorage.getItem(storageKey(conversationId));
    if (!id) return;
    try {
        await initialize(controller.signal);
        const value = await api(`/api/action-recovery/${encodeURIComponent(id)}`, undefined, controller.signal);
        if (!controller.signal.aborted && window.currentConversationId === conversationId) {
            showActionRecovery(value.recovery, value.pending_body);
        }
    } catch {
        if (controller.signal.aborted) return;
        const notice = node('div', 'alert alert-warning', 'Action recovery changed or expired. Recheck your selected agent before sending.');
        notice.setAttribute('role', 'status');
        notice.id = 'action-recovery-notice';
        document.getElementById('action-recovery-notice')?.remove();
        document.getElementById('chatbox')?.before(notice);
    }
}

window.addEventListener('chat:conversation-context-changed', restoreConversation);
document.getElementById('agent-select')?.addEventListener('change', () => {
    contextRevision += 1;
    decision?.('cancel');
    restoreController?.abort();
    activeNotice?.remove();
    activeNotice = null;
});
queueMicrotask(() => { void restoreConversation(); });
