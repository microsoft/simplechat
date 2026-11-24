// chat-links.js
// Create, resolve, and revoke compact workspace chat launch links.

import {
    applyChatLinkDocumentSourceSelection,
    buildChatLinkDocumentSourceSelection,
} from './chat-documents.js';
import { selectAgentForChatLink } from './chat-agents.js';
import { selectModelForChatLink } from './chat-model-selector.js';
import { showToast } from './chat-toast.js';

const CHAT_LINK_REFERENCE_PATTERN = /^[A-Za-z0-9_-]{22}$/;
const DEFAULT_LIFETIME_DAYS = 90;

let activeChatLinkBinding = null;
let ownLinksContinuation = null;
let ownLinks = [];

async function prepareNewConversationDraft(options = {}) {
    const conversations = await import('./chat-conversations.js');
    conversations.prepareNewConversationDraft(options);
}

function getElement(id) {
    return document.getElementById(id);
}

function selectedOption(elementId) {
    const select = getElement(elementId);
    return select?.options?.[select.selectedIndex] || null;
}

function activeAgentSelectionKey() {
    const enableAgentsButton = getElement('enable-agents-btn');
    if (!enableAgentsButton?.classList.contains('active')) {
        return '';
    }
    return selectedOption('agent-select')?.dataset.catalogKey || '';
}

function activeModelSelectionKey() {
    const option = selectedOption('model-select');
    return option?.dataset.selectionKey || option?.value || '';
}

function workspaceName(scope) {
    if (scope.kind === 'personal') {
        return 'My workspace';
    }
    const candidates = scope.kind === 'group'
        ? (window.userGroups || [])
        : (window.userVisiblePublicWorkspaces || []);
    return candidates.find(item => String(item.id) === String(scope.id))?.name || scope.id;
}

function currentChatLinkConfiguration() {
    const documentSourceSelection = buildChatLinkDocumentSourceSelection();
    if (
        !documentSourceSelection
        || documentSourceSelection.sources.some(source => source.kind !== 'document')
    ) {
        return null;
    }
    const sourceScope = documentSourceSelection.sources[0]?.scope;
    if (!sourceScope) {
        return null;
    }
    const agentSelection = activeAgentSelectionKey();
    const modelSelection = agentSelection ? '' : activeModelSelectionKey();
    if (!agentSelection && !modelSelection) {
        return null;
    }
    return {
        routing: {
            kind: agentSelection ? 'agent' : 'model',
            selection_key: agentSelection || modelSelection,
        },
        workspace: {
            kind: sourceScope.kind,
            ...(sourceScope.kind === 'personal' ? {} : { id: sourceScope.id }),
        },
        document_source_selection: documentSourceSelection,
        display: {
            workspace: workspaceName(sourceScope),
            documents: documentSourceSelection.sources.length,
            runner: agentSelection ? 'Agent' : 'Model',
        },
    };
}

function errorMessage(payload, fallback) {
    if (payload && typeof payload.message === 'string' && payload.message.trim()) {
        return payload.message;
    }
    if (payload && typeof payload.error === 'string' && payload.error.trim()) {
        return payload.error;
    }
    return fallback;
}

async function readJson(response) {
    const contentType = response.headers.get('content-type') || '';
    return contentType.includes('application/json')
        ? response.json().catch(() => ({}))
        : {};
}

function normalizeChatLinkUrl(path) {
    if (!/^\/l\/[A-Za-z0-9_-]{22}$/.test(path || '')) {
        return '';
    }
    return new URL(path, `${window.location.origin}/`).toString();
}

function setDialogError(message) {
    const element = getElement('chat-link-dialog-error');
    if (!element) {
        return;
    }
    element.textContent = message || '';
    element.classList.toggle('d-none', !message);
}

function setLaunchError(message) {
    const container = getElement('chat-link-launch-error');
    const messageElement = getElement('chat-link-launch-error-message');
    if (!container || !messageElement) {
        return;
    }
    messageElement.textContent = message;
    container.classList.remove('d-none');
}

function formatLifetime(days) {
    if (days === null) {
        return 'Never expires';
    }
    return days === 365 ? '1 year' : `${days} days`;
}

function formatExpiry(value) {
    if (!value) {
        return 'Never';
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? 'Unknown' : parsed.toLocaleString();
}

function renderOwnLinks() {
    const list = getElement('chat-link-own-list');
    const empty = getElement('chat-link-own-empty');
    const loadMore = getElement('chat-link-load-more');
    if (!list || !empty || !loadMore) {
        return;
    }
    list.replaceChildren();
    ownLinks.forEach(link => {
        const item = document.createElement('li');
        item.className = 'list-group-item d-flex align-items-start justify-content-between gap-3';

        const details = document.createElement('div');
        details.className = 'min-w-0';
        const title = document.createElement('div');
        title.className = 'fw-semibold';
        title.textContent = `${link.routing.kind === 'agent' ? 'Agent' : 'Model'} · ${link.document_count} documents`;
        const expiry = document.createElement('div');
        expiry.className = 'small text-muted';
        expiry.textContent = `${formatLifetime(link.lifetime_days)} · Expires ${formatExpiry(link.expires_at)}`;
        const address = document.createElement('a');
        address.className = 'small text-break';
        address.href = normalizeChatLinkUrl(link.path);
        address.textContent = normalizeChatLinkUrl(link.path);
        details.append(title, expiry, address);

        const revokeButton = document.createElement('button');
        revokeButton.type = 'button';
        revokeButton.className = 'btn btn-sm btn-outline-danger';
        revokeButton.dataset.chatLinkReference = link.reference;
        revokeButton.setAttribute('aria-label', 'Revoke this chat link');
        revokeButton.textContent = 'Revoke';
        item.append(details, revokeButton);
        list.appendChild(item);
    });
    empty.classList.toggle('d-none', ownLinks.length > 0);
    loadMore.classList.toggle('d-none', !ownLinksContinuation);
}

async function loadOwnLinks({ append = false } = {}) {
    const query = new URLSearchParams({ page_size: '25' });
    if (append && ownLinksContinuation) {
        query.set('continuation_token', ownLinksContinuation);
    }
    const response = await fetch(`/api/chat-links?${query.toString()}`, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
    });
    const payload = await readJson(response);
    if (!response.ok) {
        throw new Error(errorMessage(payload, 'Could not load your chat links.'));
    }
    ownLinks = append ? [...ownLinks, ...(payload.links || [])] : (payload.links || []);
    ownLinksContinuation = payload.continuation_token || null;
    renderOwnLinks();
}

function updateConfigurationSummary(configuration) {
    const runner = getElement('chat-link-summary-runner');
    const workspace = getElement('chat-link-summary-workspace');
    const documents = getElement('chat-link-summary-documents');
    if (runner) runner.textContent = configuration?.display?.runner || 'Not selected';
    if (workspace) workspace.textContent = configuration?.display?.workspace || 'Not selected';
    if (documents) documents.textContent = String(configuration?.display?.documents || 0);
}

async function openCreateDialog() {
    setDialogError('');
    const resultContainer = getElement('chat-link-result');
    resultContainer?.classList.add('d-none');
    const configuration = currentChatLinkConfiguration();
    updateConfigurationSummary(configuration);
    const createButton = getElement('chat-link-create-btn');
    if (createButton) {
        createButton.disabled = !configuration;
    }
    if (!configuration) {
        setDialogError(
            'Select an available agent or model and explicit documents from one workspace before creating a link.',
        );
    }
    try {
        await loadOwnLinks();
    } catch (error) {
        setDialogError(error instanceof Error ? error.message : 'Could not load your chat links.');
    }
    window.bootstrap?.Modal.getOrCreateInstance(getElement('chat-link-modal'))?.show();
}

async function createChatLink() {
    const configuration = currentChatLinkConfiguration();
    if (!configuration) {
        setDialogError(
            'Select an available agent or model and explicit documents from one workspace before creating a link.',
        );
        return;
    }
    const lifetimeSelect = getElement('chat-link-lifetime');
    const selectedLifetime = lifetimeSelect?.value || String(DEFAULT_LIFETIME_DAYS);
    const lifetimeDays = selectedLifetime === 'never' ? null : Number(selectedLifetime);
    const button = getElement('chat-link-create-btn');
    if (button) button.disabled = true;
    try {
        const response = await fetch('/api/chat-links', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                routing: configuration.routing,
                workspace: configuration.workspace,
                document_source_selection: configuration.document_source_selection,
                lifetime_days: lifetimeDays,
            }),
        });
        const payload = await readJson(response);
        if (!response.ok) {
            throw new Error(errorMessage(payload, 'Could not create the chat link.'));
        }
        const input = getElement('chat-link-created-url');
        if (input) {
            input.value = normalizeChatLinkUrl(payload.path);
            input.select();
        }
        getElement('chat-link-result')?.classList.remove('d-none');
        await loadOwnLinks();
    } catch (error) {
        setDialogError(error instanceof Error ? error.message : 'Could not create the chat link.');
    } finally {
        if (button) button.disabled = false;
    }
}

async function copyCreatedLink() {
    const input = getElement('chat-link-created-url');
    const value = input?.value || '';
    if (!value) {
        return;
    }
    try {
        if (!navigator.clipboard?.writeText) {
            throw new Error('Clipboard unavailable.');
        }
        await navigator.clipboard.writeText(value);
        showToast('Chat link copied.', 'success');
    } catch {
        input?.focus();
        input?.select();
        setDialogError('Clipboard access is unavailable. The link is selected so you can copy it manually.');
    }
}

function openRevokeDialog(reference) {
    const modal = getElement('chat-link-revoke-modal');
    if (!modal || !CHAT_LINK_REFERENCE_PATTERN.test(reference)) {
        return;
    }
    modal.dataset.reference = reference;
    window.bootstrap?.Modal.getOrCreateInstance(modal)?.show();
}

async function revokeOwnedLink() {
    const modal = getElement('chat-link-revoke-modal');
    const reference = modal?.dataset.reference || '';
    if (!CHAT_LINK_REFERENCE_PATTERN.test(reference)) {
        return;
    }
    const button = getElement('chat-link-revoke-confirm-btn');
    if (button) button.disabled = true;
    try {
        const response = await fetch(`/api/chat-links/${encodeURIComponent(reference)}`, {
            method: 'DELETE',
            credentials: 'same-origin',
            headers: { Accept: 'application/json' },
        });
        const payload = response.status === 204 ? {} : await readJson(response);
        if (!response.ok) {
            throw new Error(errorMessage(payload, 'Could not revoke the chat link.'));
        }
        window.bootstrap?.Modal.getOrCreateInstance(modal)?.hide();
        ownLinks = ownLinks.filter(link => link.reference !== reference);
        renderOwnLinks();
        showToast('Chat link revoked.', 'success');
    } catch (error) {
        setDialogError(error instanceof Error ? error.message : 'Could not revoke the chat link.');
    } finally {
        if (button) button.disabled = false;
    }
}

function clearChatLinkParameter() {
    const url = new URL(window.location.href);
    url.searchParams.delete('chat_link');
    window.history.replaceState({}, document.title, `${url.pathname}${url.search}${url.hash}`);
}

function requestRoutingMatches(payload, resolution) {
    if (resolution.routing.kind === 'agent') {
        return payload.agent_info?.catalog_key === resolution.routing.selection_key;
    }
    return (
        payload.model_deployment
        && activeModelSelectionKey() === resolution.routing.selection_key
    );
}

export function getChatLinkReferenceForRequest(payload) {
    if (!activeChatLinkBinding) {
        return null;
    }
    const selectionMatches = JSON.stringify(payload.document_source_selection)
        === JSON.stringify(activeChatLinkBinding.document_source_selection);
    if (!selectionMatches || !requestRoutingMatches(payload, activeChatLinkBinding)) {
        activeChatLinkBinding = null;
        return null;
    }
    return activeChatLinkBinding.reference;
}

export function commitChatLinkReference(reference) {
    if (activeChatLinkBinding?.reference === reference) {
        activeChatLinkBinding = null;
    }
}

export function hasActiveChatLinkBinding() {
    return Boolean(activeChatLinkBinding);
}

export async function launchChatLink(reference) {
    if (!CHAT_LINK_REFERENCE_PATTERN.test(reference || '')) {
        setLaunchError('This chat link reference is invalid.');
        return false;
    }
    const url = new URL(window.location.href);
    const conflictingParams = [
        'conversationId',
        'conversation_id',
        'agent_id',
        'public_workspace_selection',
        'result_workflow_id',
        'result_run_id',
    ].filter(name => url.searchParams.has(name));
    if (conflictingParams.length > 0) {
        setLaunchError('This chat link cannot be combined with another chat launch.');
        return false;
    }

    const response = await fetch(`/api/chat-links/${encodeURIComponent(reference)}`, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
    });
    const resolution = await readJson(response);
    if (!response.ok) {
        setLaunchError(errorMessage(
            resolution,
            "You don't have permission to use this linked configuration.",
        ));
        return false;
    }

    try {
        await prepareNewConversationDraft({ preserveSelections: true });
        await applyChatLinkDocumentSourceSelection(
            resolution.document_source_selection,
        );
        const selected = resolution.routing.kind === 'agent'
            ? await selectAgentForChatLink(resolution.routing.selection_key)
            : await selectModelForChatLink(resolution.routing.selection_key);
        if (!selected) {
            throw new Error('The linked agent or model is no longer available.');
        }
        if (resolution.routing.kind === 'agent') {
            await applyChatLinkDocumentSourceSelection(
                resolution.document_source_selection,
            );
        }
        const current = currentChatLinkConfiguration();
        if (
            !current
            || current.routing.kind !== resolution.routing.kind
            || current.routing.selection_key !== resolution.routing.selection_key
            || JSON.stringify(current.document_source_selection)
                !== JSON.stringify(resolution.document_source_selection)
        ) {
            throw new Error('The linked configuration could not be applied exactly.');
        }
        activeChatLinkBinding = {
            reference,
            routing: resolution.routing,
            document_source_selection: resolution.document_source_selection,
        };
        clearChatLinkParameter();
        getElement('chat-link-launch-error')?.classList.add('d-none');
        document.getElementById('user-input')?.focus();
        return true;
    } catch (error) {
        setLaunchError(error instanceof Error
            ? error.message
            : 'The linked chat configuration could not be opened.');
        return false;
    }
}

export function initializeChatLinkControls() {
    getElement('create-chat-link-btn')?.addEventListener('click', () => {
        void openCreateDialog();
    });
    getElement('chat-link-create-btn')?.addEventListener('click', () => {
        void createChatLink();
    });
    getElement('chat-link-copy-btn')?.addEventListener('click', () => {
        void copyCreatedLink();
    });
    getElement('chat-link-load-more')?.addEventListener('click', () => {
        void loadOwnLinks({ append: true }).catch(error => {
            setDialogError(error instanceof Error ? error.message : 'Could not load more chat links.');
        });
    });
    getElement('chat-link-own-list')?.addEventListener('click', event => {
        const reference = event.target.closest('[data-chat-link-reference]')?.dataset.chatLinkReference;
        if (reference) {
            openRevokeDialog(reference);
        }
    });
    getElement('chat-link-revoke-confirm-btn')?.addEventListener('click', () => {
        void revokeOwnedLink();
    });
    getElement('chat-link-start-normal-btn')?.addEventListener('click', () => {
        clearChatLinkParameter();
        getElement('chat-link-launch-error')?.classList.add('d-none');
        void prepareNewConversationDraft();
    });
}
