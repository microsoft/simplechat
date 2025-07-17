// chat-agents.js
import { fetchUserAgents, fetchSelectedAgent, populateAgentSelect, setSelectedAgent, getUserSetting, setUserSetting } from '../agents_common.js';

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
        const agents = await fetchUserAgents();
        const selectedAgent = await fetchSelectedAgent();
        populateAgentSelect(agentSelect, agents, selectedAgent);
        agentSelect.onchange = async function() {
            const selectedName = agentSelect.value;
            const selectedAgentObj = agents.find(a => a.name === selectedName);
            if (selectedAgentObj) {
                await setSelectedAgent({ name: selectedAgentObj.name, is_global: !!selectedAgentObj.is_global });
            }
        };
    } catch (e) {
        console.error('Error loading agents:', e);
    }
}

// Call initializeAgentInteractions on load
initializeAgentInteractions();