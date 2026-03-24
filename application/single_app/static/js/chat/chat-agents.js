// chat-agents.js
import {
    fetchUserAgents,
    fetchGroupAgentsForActiveGroup,
    fetchSelectedAgent,
    populateAgentSelect,
    setSelectedAgent,
    getUserSetting,
    setUserSetting
} from '../agents_common.js';
import { createSearchableSingleSelect } from './chat-searchable-select.js';

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

let agentSelectorController = null;

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
    });

    return agentSelectorController;
}

function sanitizeGroupId(groupId) {
    if (!groupId && groupId !== 0) return null;
    const normalized = String(groupId).trim();
    if (!normalized) return null;
    const lower = normalized.toLowerCase();
    if (lower === 'none' || lower === 'null' || lower === 'undefined') return null;
    return normalized;
}

function getActiveConversationContext() {
    const activeItem = document.querySelector('.conversation-item.active');
    const chatType = activeItem?.getAttribute('data-chat-type') || '';
    const chatState = activeItem?.getAttribute('data-chat-state') || '';
    const itemGroupId = sanitizeGroupId(activeItem?.getAttribute('data-group-id'));

    return {
        chatType,
        chatState,
        groupId: itemGroupId
    };
}

function getActiveConversationScope() {
    const activeItem = document.querySelector('.conversation-item.active');
    const chatType = activeItem?.getAttribute('data-chat-type') || '';
    const chatState = activeItem?.getAttribute('data-chat-state') || '';
    if (chatType === 'new') {
        return null;
    }
    if (chatState === 'new') {
        return null;
    }
    if (!chatType) {
        return 'personal';
    }
    if (chatType.startsWith('group')) {
        return 'group';
    }
    return 'personal';
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
    if (enableAgentsBtn && agentSelectContainer) {
        initializeAgentSelector();

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
            } else {
                agentSelectContainer.style.display = "none";
                if (modelSelectContainer) modelSelectContainer.style.display = "block";
            }
        });
    } else {
        if (!enableAgentsBtn) console.error("Agent Init Error: enable-agents-btn not found.");
        if (!agentSelectContainer) console.error("Agent Init Error: agent-select-container not found.");
    }
}

export async function populateAgentDropdown() {
    initializeAgentSelector();

    try {
        const conversationScope = getActiveConversationScope();
        const { chatType, chatState, groupId: conversationGroupId } = getActiveConversationContext();
        const activeConversation = document.querySelector('.conversation-item.active');
        const userActiveGroupId = sanitizeGroupId(await getUserSetting('activeGroupOid'));
        const workspaceGroupId = sanitizeGroupId(window.groupWorkspaceContext?.activeGroupId || window.activeGroupId);

        // Only allow group agents when a group context exists or no conversation is selected.
        const allowGroupAgents = !activeConversation
            || conversationScope === 'group'
            || !!conversationGroupId
            || chatState === 'new'
            || chatType === 'new';

        const activeGroupId = allowGroupAgents
            ? (conversationGroupId || userActiveGroupId || workspaceGroupId || null)
            : null;
        const [userAgents, selectedAgent] = await Promise.all([
            fetchUserAgents(),
            fetchSelectedAgent()
        ]);
        const groupAgents = activeGroupId ? await fetchGroupAgentsForActiveGroup(activeGroupId) : [];
        const personalAgents = userAgents.filter(agent => !agent.is_global && !agent.is_group);
        const globalAgents = userAgents.filter(agent => agent.is_global);
        let orderedAgents = [];
        const includeGroupAgents = allowGroupAgents && groupAgents.length > 0;

        if (!conversationScope) {
            orderedAgents = includeGroupAgents
                ? [...personalAgents, ...groupAgents, ...globalAgents]
                : [...personalAgents, ...globalAgents];
        } else if (conversationScope === 'group') {
            orderedAgents = includeGroupAgents
                ? [...groupAgents, ...globalAgents]
                : [...globalAgents];
        } else {
            // Personal scope: show personal first; only add group agents when explicitly allowed
            orderedAgents = includeGroupAgents
                ? [...personalAgents, ...groupAgents, ...globalAgents]
                : [...personalAgents, ...globalAgents];
        }
        populateAgentSelect(agentSelect, orderedAgents, selectedAgent);
        agentSelectorController?.refresh();
        agentSelect.onchange = async function () {
            const selectedOption = agentSelect.options[agentSelect.selectedIndex];
            if (!selectedOption) {
                return;
            }
            const payload = {
                name: selectedOption.dataset.name || '',
                display_name: selectedOption.dataset.displayName || selectedOption.textContent || '',
                id: selectedOption.dataset.agentId || null,
                is_global: selectedOption.dataset.isGlobal === 'true',
                is_group: selectedOption.dataset.isGroup === 'true',
                group_id: selectedOption.dataset.groupId || null,
                group_name: selectedOption.dataset.groupName || (window.activeGroupName || null)
            };
            console.log('DEBUG: Agent dropdown changed with payload:', payload);
            if (!payload.name) {
                console.warn('Selected agent is missing a name, skipping settings update.');
                return;
            }
            await setSelectedAgent(payload);
            console.log('DEBUG: Agent selection saved successfully');
        };
    } catch (e) {
        console.error('Error loading agents:', e);
    }
}

// Call initializeAgentInteractions on load
initializeAgentInteractions();