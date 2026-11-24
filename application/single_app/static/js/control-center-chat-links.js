// control-center-chat-links.js
// Control Center inventory and revocation for active workspace chat links.

let chatLinkRows = [];
let chatLinkContinuation = null;
let chatLinkLoading = false;
let revokeReference = '';

function element(id) {
    return document.getElementById(id);
}

function formatLifetime(days) {
    if (days === null) {
        return 'Never expires';
    }
    return days === 365 ? '1 year' : `${days} days`;
}

function formatDate(value) {
    if (!value) {
        return 'Never';
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? 'Unknown' : parsed.toLocaleString();
}

function documentSelectionLabel(link) {
    if (link.all_documents) {
        return 'All documents';
    }
    const count = Number(link.document_count || 0);
    return `${count} ${count === 1 ? 'document' : 'documents'}`;
}

function reasoningSelectionLabel(link) {
    if (link.routing.kind === 'agent') {
        return 'Agent setting';
    }
    const value = String(link.reasoning_effort || '').trim();
    return value
        ? value.charAt(0).toUpperCase() + value.slice(1)
        : 'Model default';
}

function normalizeChatLinkUrl(path) {
    if (!/^\/l\/[A-Za-z0-9_-]{22}$/.test(path || '')) {
        return '';
    }
    return new URL(path, `${window.location.origin}/`).toString();
}

function setError(message) {
    const container = element('control-center-chat-links-error');
    if (!container) {
        return;
    }
    container.textContent = message || '';
    container.classList.toggle('d-none', !message);
}

async function readError(response, fallback) {
    try {
        const payload = await response.json();
        return payload.message || payload.error || fallback;
    } catch {
        return fallback;
    }
}

function makeActionButton(label, iconClass, onClick, variant = 'outline-secondary') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `btn btn-sm btn-${variant}`;
    button.setAttribute('aria-label', label);
    button.title = label;
    const icon = document.createElement('i');
    icon.className = iconClass;
    icon.setAttribute('aria-hidden', 'true');
    button.appendChild(icon);
    button.addEventListener('click', onClick);
    return button;
}

function renderRows() {
    const body = element('control-center-chat-links-body');
    const empty = element('control-center-chat-links-empty');
    const more = element('control-center-chat-links-more');
    if (!body || !empty || !more) {
        return;
    }
    body.replaceChildren();
    chatLinkRows.forEach(link => {
        const row = document.createElement('tr');
        const creator = document.createElement('td');
        creator.className = 'font-monospace small text-break';
        creator.textContent = link.created_by_user_id || 'Unknown';

        const runner = document.createElement('td');
        const runnerKind = document.createElement('div');
        runnerKind.className = 'text-capitalize';
        runnerKind.textContent = link.routing.kind;
        const runnerKey = document.createElement('div');
        runnerKey.className = 'small text-muted text-break';
        runnerKey.textContent = link.routing.selection_key;
        runner.append(runnerKind, runnerKey);

        const workspace = document.createElement('td');
        workspace.textContent = link.workspace.id
            ? `${link.workspace.kind} · ${link.workspace.id}`
            : link.workspace.kind;
        const documents = document.createElement('td');
        documents.textContent = documentSelectionLabel(link);
        const reasoning = document.createElement('td');
        reasoning.textContent = reasoningSelectionLabel(link);
        const lifetime = document.createElement('td');
        const lifetimeLabel = document.createElement('div');
        lifetimeLabel.textContent = formatLifetime(link.lifetime_days);
        const expiry = document.createElement('div');
        expiry.className = 'small text-muted';
        expiry.textContent = `Expires ${formatDate(link.expires_at)}`;
        lifetime.append(lifetimeLabel, expiry);
        const created = document.createElement('td');
        created.className = 'small text-muted';
        created.textContent = formatDate(link.created_at);
        const actions = document.createElement('td');
        actions.className = 'text-end';
        const actionGroup = document.createElement('div');
        actionGroup.className = 'btn-group btn-group-sm';
        const open = document.createElement('a');
        open.className = 'btn btn-sm btn-outline-secondary';
        open.href = normalizeChatLinkUrl(link.path);
        open.target = '_blank';
        open.rel = 'noreferrer';
        open.setAttribute('aria-label', 'Open chat link');
        open.innerHTML = '<i class="bi bi-box-arrow-up-right" aria-hidden="true"></i>';
        actionGroup.append(
            open,
            makeActionButton('Copy chat link', 'bi bi-copy', async () => {
                try {
                    await navigator.clipboard.writeText(normalizeChatLinkUrl(link.path));
                } catch {
                    setError('Clipboard access is unavailable. Open the link and copy its address manually.');
                }
            }),
            makeActionButton('Revoke chat link', 'bi bi-trash', () => {
                revokeReference = link.reference;
                window.bootstrap?.Modal
                    .getOrCreateInstance(element('control-center-chat-link-revoke-modal'))
                    ?.show();
            }, 'outline-danger'),
        );
        actions.appendChild(actionGroup);
        row.append(creator, runner, workspace, documents, reasoning, lifetime, created, actions);
        body.appendChild(row);
    });
    empty.classList.toggle('d-none', chatLinkRows.length > 0);
    more.classList.toggle('d-none', !chatLinkContinuation);
}

async function loadChatLinks({ append = false } = {}) {
    if (chatLinkLoading) {
        return;
    }
    chatLinkLoading = true;
    setError('');
    const query = new URLSearchParams({ page_size: '25' });
    if (append && chatLinkContinuation) {
        query.set('continuation_token', chatLinkContinuation);
    }
    try {
        const response = await fetch(`/api/v2/control-center/chat-links?${query.toString()}`, {
            credentials: 'same-origin',
            headers: { Accept: 'application/json' },
        });
        if (!response.ok) {
            throw new Error(await readError(response, 'Could not load chat links.'));
        }
        const payload = await response.json();
        chatLinkRows = append ? [...chatLinkRows, ...(payload.links || [])] : (payload.links || []);
        chatLinkContinuation = payload.continuation_token || null;
        renderRows();
    } catch (error) {
        setError(error instanceof Error ? error.message : 'Could not load chat links.');
    } finally {
        chatLinkLoading = false;
    }
}

async function revokeChatLink() {
    if (!revokeReference) {
        return;
    }
    const button = element('control-center-chat-link-revoke-confirm');
    if (button) button.disabled = true;
    try {
        const response = await fetch(
            `/api/v2/control-center/chat-links/${encodeURIComponent(revokeReference)}`,
            {
                method: 'DELETE',
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            },
        );
        if (!response.ok) {
            throw new Error(await readError(response, 'Could not revoke the chat link.'));
        }
        chatLinkRows = chatLinkRows.filter(link => link.reference !== revokeReference);
        revokeReference = '';
        renderRows();
        window.bootstrap?.Modal
            .getOrCreateInstance(element('control-center-chat-link-revoke-modal'))
            ?.hide();
    } catch (error) {
        setError(error instanceof Error ? error.message : 'Could not revoke the chat link.');
    } finally {
        if (button) button.disabled = false;
    }
}

function initializeControlCenterChatLinks() {
    const tab = element('chat-links-tab');
    if (!tab || !element('control-center-chat-links-body')) {
        return;
    }
    tab.addEventListener('shown.bs.tab', () => {
        void loadChatLinks();
    });
    element('control-center-chat-links-refresh')?.addEventListener('click', () => {
        void loadChatLinks();
    });
    element('control-center-chat-links-more')?.addEventListener('click', () => {
        void loadChatLinks({ append: true });
    });
    element('control-center-chat-link-revoke-confirm')?.addEventListener('click', () => {
        void revokeChatLink();
    });
    const existingTabInitializer = window.initializeControlCenterTab;
    window.initializeControlCenterTab = function initializeControlCenterTab(tabId) {
        if (typeof existingTabInitializer === 'function') {
            existingTabInitializer(tabId);
        }
        if (tabId === 'chat-links') {
            void loadChatLinks();
        }
    };
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeControlCenterChatLinks, { once: true });
} else {
    initializeControlCenterChatLinks();
}
