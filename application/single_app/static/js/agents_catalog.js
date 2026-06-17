// agents_catalog.js

import { showToast } from './chat/chat-toast.js';
import { openViewModal } from './workspace/view-utils.js';

const directory = document.querySelector('.agents-directory');
const catalogSearch = document.getElementById('agents-catalog-search');
const agentTabs = Array.from(document.querySelectorAll('.agents-tab[data-agent-tab]'));
const tagFilters = document.getElementById('agents-tag-filters');
const listModeInput = document.getElementById('agents-catalog-list-mode');
const cardModeInput = document.getElementById('agents-catalog-card-mode');
const listView = document.getElementById('agents-list-view');
const cardView = document.getElementById('agents-card-view');
const resultsTitle = document.getElementById('agents-results-title');
const alertBox = document.getElementById('agents-catalog-alert');
const newAgentLink = document.getElementById('agents-new-agent-link');
const searchForm = document.getElementById('agents-catalog-search-form');
const disclaimerMarkdownScript = document.getElementById('agents-page-disclaimer-markdown');
const disclaimerContainer = document.getElementById('agents-page-disclaimer');
const popularWindowToggle = document.getElementById('agents-popular-window-toggle');
const popularWindowButtons = Array.from(document.querySelectorAll('[data-agent-usage-window]'));

const VIEW_STORAGE_KEY = 'simplechat-agents-catalog-view';
const TAB_LABELS = Object.freeze({
    popular: 'Popular',
    search: 'Search Results',
    personal: 'Personal',
    group: 'Group',
    enterprise: 'Enterprise',
});
const ALLOWED_BADGE_VARIANTS = new Set(['primary', 'secondary', 'success', 'info', 'light']);

let allAgents = [];
let activeTab = 'popular';
let activeTags = new Set();
let popularUsageWindow = 'all_time';
let currentViewMode = localStorage.getItem(VIEW_STORAGE_KEY) === 'card' ? 'card' : 'list';

function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function clearElement(element) {
    if (element) {
        element.textContent = '';
    }
}

function getAgentDisplayName(agent) {
    return normalizeText(agent?.display_name || agent?.displayName || agent?.name || 'Unnamed Agent') || 'Unnamed Agent';
}

function getScopeType(agent) {
    if (agent?.is_group || agent?.scope_type === 'group') {
        return 'group';
    }
    if (agent?.is_global || agent?.scope_type === 'global') {
        return 'enterprise';
    }
    return 'personal';
}

function getScopeLabel(agent) {
    const scopeType = getScopeType(agent);
    if (scopeType === 'group') {
        return normalizeText(agent?.group_name || agent?.scope_name || 'Group');
    }
    if (scopeType === 'enterprise') {
        return 'Enterprise';
    }
    return 'Personal';
}

function getScopeBadgeVariant(agent) {
    const scopeType = getScopeType(agent);
    if (scopeType === 'enterprise') {
        return 'info';
    }
    if (scopeType === 'group') {
        return 'primary';
    }
    return 'secondary';
}

function getPromotedPopularBadgeLabel(agent) {
    if (!agent?.is_promoted_popular || agent?.promoted_popular_tag_enabled === false) {
        return '';
    }
    const label = normalizeText(agent?.promoted_popular_tag_label || 'Promoted');
    return label.slice(0, 40) || 'Promoted';
}

function normalizePopularPromotionWindow(value) {
    const normalizedValue = normalizeText(value).toLowerCase().replace(/-/g, '_');
    if (normalizedValue === 'all' || normalizedValue === 'alltime') {
        return 'all_time';
    }
    if (normalizedValue === '30' || normalizedValue === 'last30' || normalizedValue === 'last_30_days') {
        return '30_days';
    }
    return ['all_time', '30_days', 'both'].includes(normalizedValue) ? normalizedValue : 'both';
}

function isPromotedPopularForWindow(agent, usageWindow = popularUsageWindow) {
    if (!agent?.is_promoted_popular) {
        return false;
    }
    const promotionWindow = normalizePopularPromotionWindow(agent.promoted_popular_window);
    const selectedWindow = usageWindow === '30_days' ? '30_days' : 'all_time';
    return promotionWindow === 'both' || promotionWindow === selectedWindow;
}

function getPromotedPopularRank(agent) {
    const rank = Number(agent?.promoted_popular_rank);
    return Number.isFinite(rank) ? rank : 1000000;
}

function getPromotedPopularOrder(agent) {
    const order = normalizeText(agent?.promoted_popular_order).toLowerCase();
    return ['before', 'after', 'mixed'].includes(order) ? order : 'before';
}

function dedupeAgentsByCatalogKey(agents) {
    const seenKeys = new Set();
    const dedupedAgents = [];
    agents.forEach(agent => {
        const catalogKey = normalizeText(agent?.catalog_key || agent?.id || getAgentDisplayName(agent));
        if (seenKeys.has(catalogKey)) {
            return;
        }
        seenKeys.add(catalogKey);
        dedupedAgents.push(agent);
    });
    return dedupedAgents;
}

function normalizeIconPayload(iconPayload) {
    if (!iconPayload || typeof iconPayload !== 'object' || Array.isArray(iconPayload)) {
        return null;
    }

    const kind = normalizeText(iconPayload.kind).toLowerCase();
    const value = normalizeText(iconPayload.value);
    if (kind === 'bootstrap' && /^bi-[a-z0-9][a-z0-9-]{0,80}$/.test(value)) {
        return { kind, value };
    }
    if (kind === 'image' && /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(value) && value.length <= 350000) {
        return { kind, value };
    }
    return null;
}

function appendAgentIcon(container, agent, className = 'agent-icon') {
    clearElement(container);
    container.className = className;
    const icon = normalizeIconPayload(agent?.icon);
    if (icon?.kind === 'image') {
        const image = document.createElement('img');
        image.src = icon.value;
        image.alt = '';
        container.appendChild(image);
        return;
    }

    const iconElement = document.createElement('i');
    iconElement.className = `bi ${icon?.kind === 'bootstrap' ? icon.value : 'bi-robot'}`;
    iconElement.setAttribute('aria-hidden', 'true');
    container.appendChild(iconElement);
}

function createBadge(label, variant = 'secondary') {
    const badge = document.createElement('span');
    const safeVariant = ALLOWED_BADGE_VARIANTS.has(variant) ? variant : 'secondary';
    badge.className = `badge text-bg-${safeVariant}`;
    if (safeVariant === 'light') {
        badge.classList.add('text-dark', 'border');
    }
    badge.textContent = label;
    return badge;
}

function appendTagBadges(container, tags) {
    clearElement(container);
    const safeTags = Array.isArray(tags) ? tags.map(normalizeText).filter(Boolean) : [];
    if (!safeTags.length) {
        return;
    }

    safeTags.forEach(tag => {
        const badge = createBadge(tag, 'light');
        badge.classList.add('me-1', 'mb-1');
        container.appendChild(badge);
    });
}

function createActionButton(iconClass, label, buttonClass, clickHandler) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `btn btn-sm ${buttonClass}`;

    const icon = document.createElement('i');
    icon.className = `bi ${iconClass} me-1`;
    icon.setAttribute('aria-hidden', 'true');
    button.appendChild(icon);
    button.appendChild(document.createTextNode(label));
    button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        clickHandler();
    });

    return button;
}

function createDetailsButton(agent) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-sm btn-outline-secondary agent-details-btn agent-info-icon-btn';
    button.title = 'View details';
    button.setAttribute('aria-label', `View details for ${getAgentDisplayName(agent)}`);
    const icon = document.createElement('i');
    icon.className = 'bi bi-info-circle';
    icon.setAttribute('aria-hidden', 'true');
    button.appendChild(icon);
    button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        openAgentDetails(agent);
    });
    return button;
}

function appendAgentSummary(container, agent) {
    const titleRow = document.createElement('div');
    titleRow.className = 'd-flex align-items-center flex-wrap gap-2 mb-1';

    const title = document.createElement('h3');
    title.className = 'h6 mb-0 text-truncate';
    title.textContent = getAgentDisplayName(agent);
    titleRow.appendChild(title);
    titleRow.appendChild(createBadge(getScopeLabel(agent), getScopeBadgeVariant(agent)));
    const promotedBadgeLabel = getPromotedPopularBadgeLabel(agent);
    if (promotedBadgeLabel) {
        titleRow.appendChild(createBadge(promotedBadgeLabel, 'success'));
    }

    const description = document.createElement('div');
    description.className = 'agent-description text-muted small mb-2';
    description.textContent = normalizeText(agent?.description) || 'No description available.';

    const meta = document.createElement('div');
    meta.className = 'small text-muted mb-2';
    meta.textContent = normalizeText(agent?.model_label || agent?.model_id) || 'Default model';

    const tags = document.createElement('div');
    tags.className = 'agent-tag-list d-flex flex-wrap gap-1';
    appendTagBadges(tags, agent?.tags);

    container.appendChild(titleRow);
    container.appendChild(description);
    container.appendChild(meta);
    container.appendChild(tags);
}

function createAgentActions(agent, className) {
    const actions = document.createElement('div');
    actions.className = className;
    actions.appendChild(createActionButton('bi-chat-dots-fill', 'Chat', 'btn-primary', () => chatWithAgent(agent)));
    actions.appendChild(createDetailsButton(agent));
    return actions;
}

function attachOpenDetailsInteraction(element, agent) {
    element.tabIndex = 0;
    element.setAttribute('role', 'button');
    element.setAttribute('aria-label', `View details for ${getAgentDisplayName(agent)}`);
    element.addEventListener('click', () => openAgentDetails(agent));
    element.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            openAgentDetails(agent);
        }
    });
}

function createAgentRow(agent, index = null) {
    const row = document.createElement('article');
    row.className = 'agent-row';
    row.classList.toggle('agent-row-unranked', index === null);

    if (index !== null) {
        const rank = document.createElement('div');
        rank.className = 'agent-rank';
        rank.textContent = String(index + 1);
        row.appendChild(rank);
    }

    const icon = document.createElement('div');
    appendAgentIcon(icon, agent);

    const content = document.createElement('div');
    content.className = 'min-w-0';
    appendAgentSummary(content, agent);

    row.appendChild(icon);
    row.appendChild(content);
    row.appendChild(createAgentActions(agent, 'agent-row-actions'));
    attachOpenDetailsInteraction(row, agent);
    return row;
}

function createAgentCard(agent, index = null) {
    const column = document.createElement('div');
    column.className = 'col-12 col-md-6 col-xl-4';

    const card = document.createElement('article');
    card.className = 'card agent-card';

    const body = document.createElement('div');
    body.className = 'card-body';

    const topRow = document.createElement('div');
    topRow.className = 'agent-card-media-row d-flex align-items-center gap-3 mb-2';
    if (index !== null) {
        const rank = document.createElement('div');
        rank.className = 'agent-rank';
        rank.textContent = String(index + 1);
        topRow.appendChild(rank);
    }

    const icon = document.createElement('div');
    appendAgentIcon(icon, agent);
    topRow.appendChild(icon);

    const content = document.createElement('div');
    content.className = 'flex-grow-1 min-w-0';
    appendAgentSummary(content, agent);

    body.appendChild(topRow);
    body.appendChild(content);
    body.appendChild(createAgentActions(agent, 'agent-card-actions mt-3'));
    card.appendChild(body);
    attachOpenDetailsInteraction(card, agent);
    column.appendChild(card);
    return column;
}

function getSearchableText(agent) {
    return [
        getAgentDisplayName(agent),
        agent?.name,
        agent?.description,
        getScopeLabel(agent),
        agent?.model_label,
        ...(Array.isArray(agent?.tags) ? agent.tags : []),
    ].map(normalizeText).join(' ').toLowerCase();
}

function getAgentUsageCount(agent, usageWindow = popularUsageWindow) {
    const usageProperty = usageWindow === '30_days' ? 'usage_count_30_days' : 'usage_count_all_time';
    const count = Number(agent?.[usageProperty] ?? agent?.usage_count ?? 0);
    return Number.isFinite(count) ? count : 0;
}

function getPopularAgents() {
    const promotedAgents = allAgents
        .filter(agent => isPromotedPopularForWindow(agent))
        .sort((left, right) => {
            const rankDelta = getPromotedPopularRank(left) - getPromotedPopularRank(right);
            if (rankDelta !== 0) {
                return rankDelta;
            }
            return getAgentDisplayName(left).localeCompare(getAgentDisplayName(right), undefined, { sensitivity: 'base' });
        });
    const promotedKeys = new Set(promotedAgents.map(agent => normalizeText(agent?.catalog_key)));
    const usageRankedAgents = allAgents
        .filter(agent => getAgentUsageCount(agent) > 0 && !promotedKeys.has(normalizeText(agent?.catalog_key)))
        .sort((left, right) => {
            const usageDelta = getAgentUsageCount(right) - getAgentUsageCount(left);
            if (usageDelta !== 0) {
                return usageDelta;
            }
            return getAgentDisplayName(left).localeCompare(getAgentDisplayName(right), undefined, { sensitivity: 'base' });
        })
        .slice(0, 12);
    const promotionOrder = promotedAgents.length ? getPromotedPopularOrder(promotedAgents[0]) : 'mixed';
    if (promotionOrder === 'before') {
        return dedupeAgentsByCatalogKey([...promotedAgents, ...usageRankedAgents]);
    }
    if (promotionOrder === 'after') {
        return dedupeAgentsByCatalogKey([...usageRankedAgents, ...promotedAgents]);
    }
    return dedupeAgentsByCatalogKey([...usageRankedAgents, ...promotedAgents]).sort((left, right) => {
        const usageDelta = getAgentUsageCount(right) - getAgentUsageCount(left);
        if (usageDelta !== 0) {
            return usageDelta;
        }
        const rankDelta = getPromotedPopularRank(left) - getPromotedPopularRank(right);
        if (rankDelta !== 0) {
            return rankDelta;
        }
        return getAgentDisplayName(left).localeCompare(getAgentDisplayName(right), undefined, { sensitivity: 'base' });
    });
}

function getVisibleAgents() {
    const searchTerm = normalizeText(catalogSearch?.value).toLowerCase();
    const baseAgents = searchTerm
        ? allAgents
        : activeTab === 'popular'
        ? getPopularAgents()
        : allAgents.filter(agent => getScopeType(agent) === activeTab);

    return baseAgents
        .filter(agent => {
            if (activeTags.size > 0) {
                const tagSet = new Set((agent.tags || []).map(tag => normalizeText(tag).toLowerCase()));
                if (![...activeTags].every(tag => tagSet.has(tag))) {
                    return false;
                }
            }
            return !searchTerm || getSearchableText(agent).includes(searchTerm);
        })
        .sort((left, right) => {
            if (!searchTerm && activeTab === 'popular') {
                return 0;
            }
            return getAgentDisplayName(left).localeCompare(getAgentDisplayName(right), undefined, { sensitivity: 'base' });
        });
}

function renderTagFilters(visibleAgents) {
    clearElement(tagFilters);
    const tags = Array.from(new Set(visibleAgents.flatMap(agent => Array.isArray(agent.tags) ? agent.tags : [])))
        .map(normalizeText)
        .filter(Boolean)
        .sort((left, right) => left.localeCompare(right, undefined, { sensitivity: 'base' }));

    tagFilters?.classList.toggle('d-none', tags.length === 0);
    tags.forEach(tag => {
        const tagKey = tag.toLowerCase();
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-outline-secondary btn-sm';
        button.classList.toggle('active', activeTags.has(tagKey));
        button.textContent = tag;
        button.addEventListener('click', () => {
            if (activeTags.has(tagKey)) {
                activeTags.delete(tagKey);
            } else {
                activeTags.add(tagKey);
            }
            renderCatalog();
        });
        tagFilters.appendChild(button);
    });
}

function syncTabsForSearch() {
    const hasSearch = Boolean(normalizeText(catalogSearch?.value));
    agentTabs.forEach(tab => {
        const tabName = tab.dataset.agentTab || '';
        tab.classList.toggle('d-none', tabName === 'search' && !hasSearch);
        tab.classList.toggle('active', hasSearch ? tabName === 'search' : tabName === activeTab);
    });
}

function syncPopularWindowToggle() {
    const hasSearch = Boolean(normalizeText(catalogSearch?.value));
    const isPopularView = !hasSearch && activeTab === 'popular';
    popularWindowToggle?.classList.toggle('d-none', !isPopularView);
    popularWindowButtons.forEach(button => {
        const isActive = button.dataset.agentUsageWindow === popularUsageWindow;
        button.classList.toggle('active', isActive);
        button.setAttribute('aria-pressed', String(isActive));
    });
}

function applyViewMode() {
    if (listModeInput) {
        listModeInput.checked = currentViewMode === 'list';
    }
    if (cardModeInput) {
        cardModeInput.checked = currentViewMode === 'card';
    }
    listView?.classList.toggle('d-none', currentViewMode !== 'list');
    cardView?.classList.toggle('d-none', currentViewMode !== 'card');
}

function syncNewAgentLink() {
    if (!newAgentLink) {
        return;
    }

    const hasSearch = Boolean(normalizeText(catalogSearch?.value));
    const allowPersonalCreate = directory?.dataset.allowPersonalCreate === 'true';
    const allowGroupCreate = directory?.dataset.allowGroupCreate === 'true';
    let href = '';
    let visible = false;

    if (!hasSearch && activeTab === 'personal' && allowPersonalCreate) {
        href = '/workspace?tab=agents&new_agent=1';
        visible = true;
    } else if (!hasSearch && activeTab === 'group' && allowGroupCreate) {
        href = '/group_workspaces?tab=group-agents';
        visible = true;
    }

    if (href) {
        newAgentLink.href = href;
    }
    newAgentLink.classList.toggle('d-none', !visible);
}

function updateResultsCopy() {
    const searchTerm = normalizeText(catalogSearch?.value);
    const title = searchTerm ? TAB_LABELS.search : TAB_LABELS[activeTab] || 'Agents';
    if (resultsTitle) {
        resultsTitle.textContent = title;
    }
}

function renderCatalog() {
    const visibleAgents = getVisibleAgents();
    syncTabsForSearch();
    syncPopularWindowToggle();
    renderTagFilters(visibleAgents);
    clearElement(listView);
    clearElement(cardView);

    visibleAgents.forEach((agent, index) => {
        const rankIndex = activeTab === 'popular' && !normalizeText(catalogSearch?.value) ? index : null;
        listView.appendChild(createAgentRow(agent, rankIndex));
        cardView.appendChild(createAgentCard(agent, rankIndex));
    });

    if (!visibleAgents.length) {
        const empty = document.createElement('div');
        empty.className = 'text-center text-muted border rounded p-4';
        empty.textContent = allAgents.length ? 'No agents match the current view.' : 'No agents are available.';
        listView.appendChild(empty.cloneNode(true));
        cardView.appendChild(empty);
    }

    updateResultsCopy();
    syncNewAgentLink();
    applyViewMode();
}

function showAlert(message, type = 'danger') {
    if (!alertBox) {
        return;
    }
    alertBox.className = `alert alert-${type}`;
    alertBox.textContent = message;
}

function hideAlert() {
    if (!alertBox) {
        return;
    }
    alertBox.className = 'alert d-none';
    alertBox.textContent = '';
}

function shouldShowInstructionsInDetails() {
    return directory?.dataset.showInstructionsInDetails !== 'false';
}

function renderAgentsPageDisclaimer() {
    if (!disclaimerContainer || !disclaimerMarkdownScript) {
        return;
    }

    let markdownText = '';
    try {
        markdownText = JSON.parse(disclaimerMarkdownScript.textContent || '""');
    } catch (error) {
        markdownText = '';
    }

    markdownText = String(markdownText || '').trim();
    disclaimerContainer.textContent = '';
    disclaimerContainer.classList.toggle('d-none', !markdownText);
    if (!markdownText) {
        return;
    }

    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
        disclaimerContainer.textContent = markdownText;
        return;
    }

    const sanitizedHtml = DOMPurify.sanitize(marked.parse(markdownText));
    const parsedDocument = new DOMParser().parseFromString(sanitizedHtml, 'text/html');
    disclaimerContainer.replaceChildren(...Array.from(parsedDocument.body.childNodes));
}

function openAgentDetails(agent) {
    const detailAgent = {
        ...agent,
        scope_type: getScopeType(agent),
        scope_label: getScopeLabel(agent),
    };
    openViewModal(detailAgent, 'agent', {
        onChat: () => chatWithAgent(agent),
        showInstructions: shouldShowInstructionsInDetails(),
    });
}

async function chatWithAgent(agent) {
    try {
        const response = await fetch('/api/user/settings/selected_agent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                selected_agent: {
                    id: agent.id || null,
                    name: agent.name || '',
                    display_name: getAgentDisplayName(agent),
                    is_global: Boolean(agent.is_global),
                    is_group: Boolean(agent.is_group),
                    group_id: agent.group_id || null,
                    group_name: agent.group_name || null,
                    icon: agent.icon || {},
                    tags: Array.isArray(agent.tags) ? agent.tags : [],
                    catalog_key: agent.catalog_key || null,
                },
            }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.error || 'Failed to select agent.');
        }
        window.location.href = '/chats';
    } catch (error) {
        showToast(error.message || 'Failed to select agent.', 'error');
    }
}

async function loadCatalog() {
    hideAlert();
    try {
        const response = await fetch('/api/agents/catalog?include_usage=true');
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.error || 'Failed to load agents.');
        }
        allAgents = Array.isArray(payload.agents) ? payload.agents : [];
        renderCatalog();
    } catch (error) {
        allAgents = [];
        showAlert(error.message || 'Failed to load agents.');
        renderCatalog();
    }
}

function setActiveTab(tabName) {
    activeTab = TAB_LABELS[tabName] ? tabName : 'popular';
    activeTags = new Set();
    agentTabs.forEach(tab => {
        tab.classList.toggle('active', tab.dataset.agentTab === activeTab);
    });
    renderCatalog();
}

function initialize() {
    renderAgentsPageDisclaimer();
    searchForm?.addEventListener('submit', event => {
        event.preventDefault();
        renderCatalog();
    });
    catalogSearch?.addEventListener('input', renderCatalog);
    agentTabs.forEach(tab => {
        tab.addEventListener('click', () => setActiveTab(tab.dataset.agentTab || 'popular'));
    });
    popularWindowButtons.forEach(button => {
        button.addEventListener('click', () => {
            popularUsageWindow = button.dataset.agentUsageWindow === '30_days' ? '30_days' : 'all_time';
            renderCatalog();
        });
    });
    listModeInput?.addEventListener('change', () => {
        if (listModeInput.checked) {
            currentViewMode = 'list';
            localStorage.setItem(VIEW_STORAGE_KEY, currentViewMode);
            applyViewMode();
        }
    });
    cardModeInput?.addEventListener('change', () => {
        if (cardModeInput.checked) {
            currentViewMode = 'card';
            localStorage.setItem(VIEW_STORAGE_KEY, currentViewMode);
            applyViewMode();
        }
    });
    applyViewMode();
    loadCatalog();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
} else {
    initialize();
}
