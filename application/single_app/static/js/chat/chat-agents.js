// chat-agents.js
import {
    fetchSelectedAgent,
    setSelectedAgent,
    getUserSetting,
    setUserSetting
} from '../agents_common.js';
import { createFloatingSearchableSelectDropdownConfig, createSearchableSingleSelect } from './chat-searchable-select.js';
import {
    applyAssignedKnowledgeLock,
    clearAssignedKnowledgeLock,
    getEffectiveScopes,
    isScopeLocked,
    setEffectiveScopes
} from './chat-documents.js';
import { getConversationFilteringContext } from './chat-conversation-scope.js';

const enableAgentsBtn = document.getElementById("enable-agents-btn");
const agentSelectContainer = document.getElementById("agent-select-container");
const modelSelectContainer = document.getElementById("model-select-container");
const agentSelect = document.getElementById('agent-select');
const agentDropdown = document.getElementById('agent-dropdown');
const agentDropdownButton = document.getElementById('agent-dropdown-button');
const agentDropdownMenu = document.getElementById('agent-dropdown-menu');
const agentDropdownText = agentDropdownButton
    ? agentDropdownButton.querySelector('.chat-searchable-select-text')
    : null;
const agentSearchInput = document.getElementById('agent-search-input');
const agentDropdownItems = document.getElementById('agent-dropdown-items');

const FLOATING_SELECTOR_DROPDOWN_CONFIG = createFloatingSearchableSelectDropdownConfig();

let agentSelectorController = null;
let scopeChangeListenerInitialized = false;
let pendingScopeNarrowingAgent = null;
let scopeClearActionInitialized = false;
let dropdownHideListenerInitialized = false;

function hasAgentInteractionControls() {
    return Boolean(enableAgentsBtn && agentSelectContainer && agentSelect);
}

function notifyMobileSelectorActivated(selectorId, dropdownButtonId) {
    window.dispatchEvent(new CustomEvent('chat:toolbar-selector-activated', {
        detail: {
            selectorId,
            dropdownButtonId,
        },
    }));
}

function initializeAgentSelector() {
    if (agentSelectorController || !agentSelect) {
        return agentSelectorController;
    }

    agentSelectorController = createSearchableSingleSelect({
        selectEl: agentSelect,
        dropdownEl: agentDropdown,
        buttonEl: agentDropdownButton,
        buttonTextEl: agentDropdownText,
        menuEl: agentDropdownMenu,
        searchInputEl: agentSearchInput,
        itemsContainerEl: agentDropdownItems,
        placeholderText: 'Select an Agent',
        emptyMessage: 'No agents available',
        emptySearchMessage: 'No matching agents found',
        renderOptionContent: renderAgentOptionContent,
        dropdownConfig: FLOATING_SELECTOR_DROPDOWN_CONFIG,
    });

    return agentSelectorController;
}

function compareByName(leftValue, rightValue) {
    return String(leftValue || '').localeCompare(String(rightValue || ''), undefined, {
        sensitivity: 'base',
    });
}

function getBroadScopes() {
    return {
        personal: true,
        groupIds: getKnownGroupIds(),
        publicWorkspaceIds: getKnownPublicWorkspaceIds(),
    };
}

function getSortedGroups() {
    return (window.userGroups || []).slice().sort((leftGroup, rightGroup) => {
        return compareByName(leftGroup?.name, rightGroup?.name);
    });
}

function getAgentDisplayName(agent) {
    return (agent.display_name || agent.displayName || agent.name || 'Unnamed Agent').trim() || 'Unnamed Agent';
}

function getAgentSearchText(agent, sectionLabel) {
    return [
        getAgentDisplayName(agent),
        agent.name || '',
        sectionLabel,
    ].join(' ').trim();
}

function getSectionDuplicateCounts(agents) {
    return agents.reduce((counts, agent) => {
        const key = getAgentDisplayName(agent).toLowerCase();
        counts[key] = (counts[key] || 0) + 1;
        return counts;
    }, {});
}

function getAgentOptionLabel(agent, duplicateCounts) {
    const displayName = getAgentDisplayName(agent);
    const duplicateCount = duplicateCounts[displayName.toLowerCase()] || 0;
    if (duplicateCount <= 1) {
        return displayName;
    }

    return `${displayName} (${agent.name || agent.id || 'agent'})`;
}

function normalizeIconPayload(iconPayload) {
    if (!iconPayload || typeof iconPayload !== 'object' || Array.isArray(iconPayload)) {
        return null;
    }
    const kind = String(iconPayload.kind || '').trim().toLowerCase();
    const value = String(iconPayload.value || '').trim();
    if (kind === 'bootstrap' && /^bi-[a-z0-9][a-z0-9-]{0,80}$/.test(value)) {
        return { kind, value };
    }
    if (kind === 'image' && /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(value) && value.length <= 350000) {
        return { kind, value };
    }
    return null;
}

function createOptionIconElement(iconPayload) {
    const icon = normalizeIconPayload(iconPayload);
    if (!icon) {
        return null;
    }
    if (icon.kind === 'image') {
        const image = document.createElement('img');
        image.src = icon.value;
        image.alt = '';
        image.className = 'chat-searchable-select-item-icon';
        return image;
    }
    const iconWrapper = document.createElement('span');
    iconWrapper.className = 'chat-searchable-select-item-icon';
    const iconElement = document.createElement('i');
    iconElement.className = `bi ${icon.value}`;
    iconElement.setAttribute('aria-hidden', 'true');
    iconWrapper.appendChild(iconElement);
    return iconWrapper;
}

function renderAgentOptionContent(option, optionLabel) {
    const wrapper = document.createElement('span');
    wrapper.className = 'd-flex align-items-center gap-2 min-w-0';
    const iconElement = createOptionIconElement(parseJsonObject(option.dataset.agentIcon || ''));
    if (iconElement) {
        wrapper.appendChild(iconElement);
    }
    const textEl = document.createElement('span');
    textEl.className = 'chat-searchable-select-item-text text-truncate';
    textEl.textContent = optionLabel;
    wrapper.appendChild(textEl);
    return wrapper;
}

function shouldUseConversationScopeGuard(filteringContext) {
    return !filteringContext.isNewConversation && isScopeLocked() !== false;
}

function isAgentEnabledForContext(agent, scopes, filteringContext) {
    if (shouldUseConversationScopeGuard(filteringContext) && filteringContext.conversationScope === 'group') {
        return agent.is_global || String(agent.group_id || '') === String(filteringContext.groupId || '');
    }

    if (shouldUseConversationScopeGuard(filteringContext) && filteringContext.conversationScope === 'public') {
        return agent.is_global;
    }

    if (shouldUseConversationScopeGuard(filteringContext) && filteringContext.conversationScope === 'personal') {
        return !agent.is_group;
    }

    if (agent.is_global) {
        return true;
    }

    if (agent.is_group) {
        return normalizeStringArray(scopes.groupIds || []).includes(String(agent.group_id || ''));
    }

    return scopes.personal === true;
}

function buildAgentSections(agentOptions, scopes, filteringContext) {
    const sections = [];

    const globalAgents = agentOptions
        .filter(agent => agent.is_global)
        .slice()
        .sort((leftAgent, rightAgent) => compareByName(getAgentDisplayName(leftAgent), getAgentDisplayName(rightAgent)));
    if (globalAgents.length > 0) {
        sections.push({
            label: 'Global',
            agents: globalAgents,
        });
    }

    const personalAgents = agentOptions
        .filter(agent => !agent.is_global && !agent.is_group)
        .slice()
        .sort((leftAgent, rightAgent) => compareByName(getAgentDisplayName(leftAgent), getAgentDisplayName(rightAgent)));
    if (personalAgents.length > 0) {
        sections.push({
            label: 'Personal',
            agents: personalAgents,
        });
    }

    getSortedGroups().forEach(group => {
        const sectionAgents = agentOptions
            .filter(agent => agent.is_group && String(agent.group_id || '') === String(group.id))
            .slice()
            .sort((leftAgent, rightAgent) => compareByName(getAgentDisplayName(leftAgent), getAgentDisplayName(rightAgent)));

        if (sectionAgents.length > 0) {
            sections.push({
                label: `[Group] ${group.name || 'Unnamed Group'}`,
                agents: sectionAgents,
            });
        }
    });

    return sections.map(section => {
        const duplicateCounts = getSectionDuplicateCounts(section.agents);
        return {
            label: section.label,
            agents: section.agents.map(agent => ({
                ...agent,
                optionLabel: getAgentOptionLabel(agent, duplicateCounts),
                searchText: getAgentSearchText(agent, section.label),
                disabled: !isAgentEnabledForContext(agent, scopes, filteringContext),
            })),
        };
    });
}

function doesAgentMatchSelection(agent, selectedAgentObj) {
    if (!selectedAgentObj) {
        return false;
    }

    const selectedAgentId = selectedAgentObj.id || selectedAgentObj.agent_id || null;
    const selectedAgentIsGlobal = !!selectedAgentObj.is_global;
    const selectedAgentIsGroup = !!selectedAgentObj.is_group;
    const selectedAgentGroupId = selectedAgentObj.group_id || selectedAgentObj.groupId || null;
    const agentId = agent.id || agent.agent_id || agent.name;

    const idMatches = selectedAgentId && String(agentId || '') === String(selectedAgentId);
    const nameMatches = String(agent.name || '') === String(selectedAgentObj.name || '');
    const contextMatches = !!agent.is_global === selectedAgentIsGlobal && !!agent.is_group === selectedAgentIsGroup;
    const groupMatches = !selectedAgentIsGroup || String(agent.group_id || '') === String(selectedAgentGroupId || '');

    return (idMatches || nameMatches) && contextMatches && groupMatches;
}

function rebuildAgentOptions(sections, selectedAgentObj, filteringContext) {
    if (!agentSelect) {
        return;
    }

    agentSelect.innerHTML = '';

    const hideUnavailableOptions = shouldUseConversationScopeGuard(filteringContext);
    const renderedSections = sections
        .map(section => ({
            ...section,
            agents: hideUnavailableOptions
                ? section.agents.filter(agent => !agent.disabled)
                : section.agents,
        }))
        .filter(section => section.agents.length > 0);

    const flattenedAgents = renderedSections.flatMap(section => section.agents);
    if (!flattenedAgents.length) {
        agentSelect.disabled = true;
        return;
    }

    const selectedAgent = flattenedAgents.find(agent => !agent.disabled && doesAgentMatchSelection(agent, selectedAgentObj));
    const fallbackAgent = flattenedAgents.find(agent => !agent.disabled) || null;
    const selectedKey = selectedAgent
        ? String(selectedAgent.id || selectedAgent.agent_id || selectedAgent.name || '')
        : String(fallbackAgent?.id || fallbackAgent?.agent_id || fallbackAgent?.name || '');

    renderedSections.forEach(section => {
        const optGroup = document.createElement('optgroup');
        optGroup.label = section.label;

        section.agents.forEach(agent => {
            const option = document.createElement('option');
            const agentId = agent.id || agent.agent_id || agent.name;
            const contextPrefix = agent.is_group ? 'group' : (agent.is_global ? 'global' : 'personal');
            const optionKey = String(agentId || '');

            option.value = `${contextPrefix}_${agentId}`;
            option.textContent = agent.optionLabel;
            option.dataset.name = agent.name || '';
            option.dataset.displayName = getAgentDisplayName(agent);
            option.dataset.searchText = agent.searchText;
            option.dataset.agentId = agentId || '';
            option.dataset.isGlobal = agent.is_global ? 'true' : 'false';
            option.dataset.isGroup = agent.is_group ? 'true' : 'false';
            option.dataset.groupId = agent.group_id || '';
            option.dataset.groupName = agent.group_name || '';
            option.dataset.assignedKnowledge = JSON.stringify(agent.assigned_knowledge || { enabled: false });
            option.dataset.agentIcon = JSON.stringify(agent.icon || {});
            option.dataset.agentTags = JSON.stringify(Array.isArray(agent.tags) ? agent.tags : []);
            option.dataset.catalogKey = agent.catalog_key || '';
            option.disabled = agent.disabled;
            option.selected = !agent.disabled && optionKey === selectedKey;

            optGroup.appendChild(option);
        });

        agentSelect.appendChild(optGroup);
    });

    agentSelect.disabled = !flattenedAgents.some(agent => !agent.disabled);
}

function ensureScopeClearAction() {
    if (scopeClearActionInitialized || !agentDropdownMenu || !agentDropdownItems) {
        return;
    }

    const actionContainer = document.createElement('div');
    actionContainer.classList.add('d-none');
    actionContainer.setAttribute('data-agent-scope-action-container', 'true');

    const divider = document.createElement('div');
    divider.classList.add('dropdown-divider');

    const actionButton = document.createElement('button');
    actionButton.type = 'button';
    actionButton.classList.add('dropdown-item', 'text-muted', 'small');
    actionButton.textContent = 'Use all available workspaces';
    actionButton.addEventListener('click', async event => {
        event.preventDefault();
        event.stopPropagation();

        await setEffectiveScopes(getBroadScopes(), {
            source: 'agent-clear',
        });
    });

    actionContainer.appendChild(divider);
    actionContainer.appendChild(actionButton);
    agentDropdownItems.before(actionContainer);
    scopeClearActionInitialized = true;
}

function updateScopeClearAction(scopes, filteringContext) {
    ensureScopeClearAction();

    const actionContainer = agentDropdownMenu?.querySelector('[data-agent-scope-action-container="true"]');
    if (!actionContainer) {
        return;
    }

    const shouldShowAction = filteringContext.isNewConversation && !areScopesBroad(scopes);
    actionContainer.classList.toggle('d-none', !shouldShowAction);
}

function getKnownGroupIds() {
    return (window.userGroups || [])
        .map(group => group?.id)
        .filter(Boolean)
        .map(String);
}

function getKnownPublicWorkspaceIds() {
    return (window.userVisiblePublicWorkspaces || [])
        .map(workspace => workspace?.id)
        .filter(Boolean)
        .map(String);
}

function normalizeStringArray(values = []) {
    return Array.from(new Set(values.filter(Boolean).map(String)));
}

function areScopesBroad(scopes) {
    const knownGroupIds = normalizeStringArray(getKnownGroupIds());
    const selectedGroupIds = normalizeStringArray(scopes.groupIds || []);
    const knownPublicWorkspaceIds = normalizeStringArray(getKnownPublicWorkspaceIds());
    const selectedPublicWorkspaceIds = normalizeStringArray(scopes.publicWorkspaceIds || []);

    return scopes.personal === true
        && knownGroupIds.length === selectedGroupIds.length
        && knownGroupIds.every(groupId => selectedGroupIds.includes(groupId))
        && knownPublicWorkspaceIds.length === selectedPublicWorkspaceIds.length
        && knownPublicWorkspaceIds.every(workspaceId => selectedPublicWorkspaceIds.includes(workspaceId));
}

function getPreloadedAgentOptions() {
    return Array.isArray(window.chatAgentOptions) ? window.chatAgentOptions : [];
}

function parseAssignedKnowledge(rawValue) {
    if (!rawValue) {
        return { enabled: false };
    }
    try {
        const parsed = JSON.parse(rawValue);
        return parsed && typeof parsed === 'object' ? parsed : { enabled: false };
    } catch (error) {
        console.warn('Unable to parse assigned knowledge metadata for agent option:', error);
        return { enabled: false };
    }
}

function parseJsonObject(rawValue) {
    if (!rawValue) {
        return {};
    }
    try {
        const parsed = JSON.parse(rawValue);
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (error) {
        return {};
    }
}

function parseJsonArray(rawValue) {
    if (!rawValue) {
        return [];
    }
    try {
        const parsed = JSON.parse(rawValue);
        return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
        return [];
    }
}

function buildAgentPayloadFromOption(selectedOption) {
    if (!selectedOption) {
        return null;
    }
    return {
        name: selectedOption.dataset.name || '',
        display_name: selectedOption.dataset.displayName || selectedOption.textContent || '',
        id: selectedOption.dataset.agentId || null,
        is_global: selectedOption.dataset.isGlobal === 'true',
        is_group: selectedOption.dataset.isGroup === 'true',
        group_id: selectedOption.dataset.groupId || null,
        group_name: selectedOption.dataset.groupName || (window.activeGroupName || null),
        assigned_knowledge: parseAssignedKnowledge(selectedOption.dataset.assignedKnowledge || ''),
        icon: parseJsonObject(selectedOption.dataset.agentIcon || ''),
        tags: parseJsonArray(selectedOption.dataset.agentTags || '[]'),
        catalog_key: selectedOption.dataset.catalogKey || null
    };
}

async function syncAssignedKnowledgeForPayload(payload) {
    if (payload?.assigned_knowledge?.enabled) {
        await applyAssignedKnowledgeLock(payload);
        return true;
    }
    clearAssignedKnowledgeLock();
    return false;
}

async function maybeNarrowScopeForSelectedAgent(payload) {
    const filteringContext = getConversationFilteringContext();
    if (!filteringContext.isNewConversation) {
        return;
    }

    if (payload.is_group && payload.group_id) {
        await setEffectiveScopes(
            {
                personal: false,
                groupIds: [payload.group_id],
                publicWorkspaceIds: [],
            },
            {
                source: 'agent',
            }
        );
        return;
    }

    if (!payload.is_global) {
        await setEffectiveScopes(
            {
                personal: true,
                groupIds: [],
                publicWorkspaceIds: [],
            },
            {
                source: 'agent',
            }
        );
    }
}

function initializeDropdownHideListener() {
    if (dropdownHideListenerInitialized || !agentDropdown) {
        return;
    }

    agentDropdown.addEventListener('hidden.bs.dropdown', async () => {
        if (!pendingScopeNarrowingAgent) {
            return;
        }

        const pendingPayload = pendingScopeNarrowingAgent;
        pendingScopeNarrowingAgent = null;
        await maybeNarrowScopeForSelectedAgent(pendingPayload);
    });

    dropdownHideListenerInitialized = true;
}

function initializeScopeChangeListener() {
    if (scopeChangeListenerInitialized) {
        return;
    }

    window.addEventListener('chat:scope-changed', async (event) => {
        if (event?.detail?.source === 'assigned-knowledge') {
            return;
        }
        if (!areAgentsEnabled()) {
            return;
        }

        await populateAgentDropdown();
    });

    scopeChangeListenerInitialized = true;
}

/**
 * Check if agents are currently enabled
 * @returns {boolean} True if agents are active
 */
export function areAgentsEnabled() {
    const enableAgentsBtn = document.getElementById("enable-agents-btn");
    return enableAgentsBtn && enableAgentsBtn.classList.contains('active');
}

export async function initializeAgentInteractions() {
    if (!hasAgentInteractionControls()) {
        return;
    }

    initializeAgentSelector();
    initializeScopeChangeListener();
    initializeDropdownHideListener();
    ensureScopeClearAction();

    // On load, sync UI with enable_agents setting
    const enableAgents = await getUserSetting('enable_agents');
    if (enableAgents) {
        enableAgentsBtn.classList.add('active');
        agentSelectContainer.style.display = "block";
        if (modelSelectContainer) modelSelectContainer.style.display = "none";
        await populateAgentDropdown();
    } else {
        enableAgentsBtn.classList.remove('active');
        agentSelectContainer.style.display = "none";
        if (modelSelectContainer) modelSelectContainer.style.display = "block";
        clearAssignedKnowledgeLock();
    }

    // Button click handler
    enableAgentsBtn.addEventListener("click", async function() {
        const isActive = this.classList.toggle("active");
        await setUserSetting('enable_agents', isActive);
        if (isActive) {
            agentSelectContainer.style.display = "block";
            if (modelSelectContainer) modelSelectContainer.style.display = "none";
            // Populate agent dropdown
            await populateAgentDropdown();
            notifyMobileSelectorActivated('agent-select-container', 'agent-dropdown-button');
        } else {
            agentSelectContainer.style.display = "none";
            if (modelSelectContainer) modelSelectContainer.style.display = "block";
            clearAssignedKnowledgeLock();
        }
    });
}

export async function populateAgentDropdown() {
    if (!hasAgentInteractionControls()) {
        return;
    }

    initializeAgentSelector();
    initializeDropdownHideListener();
    ensureScopeClearAction();

    try {
        const selectedAgent = await fetchSelectedAgent();
        const scopes = getEffectiveScopes();
        const filteringContext = getConversationFilteringContext();
        const sections = buildAgentSections(getPreloadedAgentOptions(), scopes, filteringContext);

        rebuildAgentOptions(sections, selectedAgent, filteringContext);
        updateScopeClearAction(scopes, filteringContext);
        agentSelectorController?.refresh();
        await syncAssignedKnowledgeForPayload(buildAgentPayloadFromOption(agentSelect.options[agentSelect.selectedIndex]));
        agentSelect.onchange = async function () {
            const selectedOption = agentSelect.options[agentSelect.selectedIndex];
            if (!selectedOption) {
                return;
            }
            const payload = buildAgentPayloadFromOption(selectedOption);
            console.log('DEBUG: Agent dropdown changed with payload:', payload);
            if (!payload.name) {
                console.warn('Selected agent is missing a name, skipping settings update.');
                return;
            }
            await setSelectedAgent(payload);
            const assignedKnowledgeApplied = await syncAssignedKnowledgeForPayload(payload);
            pendingScopeNarrowingAgent = assignedKnowledgeApplied ? null : payload;
            console.log('DEBUG: Agent selection saved successfully');
        };
    } catch (e) {
        console.error('Error loading agents:', e);
    }
}

// Call initializeAgentInteractions on load
initializeAgentInteractions();