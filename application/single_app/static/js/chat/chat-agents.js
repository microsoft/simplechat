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

const enableAgentsBtn = document.getElementById("enable-agents-btn");
const agentSelectContainer = document.getElementById("agent-select-container");
const modelSelectContainer = document.getElementById("model-select-container");

export async function initializeAgentInteractions() {
    if (enableAgentsBtn && agentSelectContainer) {
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
    const agentSelect = agentSelectContainer.querySelector('select');
    try {
        const [userAgents, selectedAgent] = await Promise.all([
            fetchUserAgents(),
            fetchSelectedAgent()
        ]);
        const groupAgents = await fetchGroupAgentsForActiveGroup();
        const combinedAgents = [...userAgents, ...groupAgents];
        const personalAgents = combinedAgents.filter(agent => !agent.is_global && !agent.is_group);
        const activeGroupAgents = combinedAgents.filter(agent => agent.is_group);
        const globalAgents = combinedAgents.filter(agent => agent.is_global);
        const orderedAgents = [...personalAgents, ...activeGroupAgents, ...globalAgents];
        populateAgentSelect(agentSelect, orderedAgents, selectedAgent);
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