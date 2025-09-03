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
            const selectedValue = agentSelect.value;
            console.log('DEBUG: Agent dropdown changed to:', selectedValue);
            console.log('DEBUG: Available agents:', agents);
            
            // Parse the selected value to extract name and global status
            let selectedAgentObj = null;
            if (selectedValue.startsWith('global_')) {
                const agentName = selectedValue.substring(7); // Remove 'global_' prefix
                selectedAgentObj = agents.find(a => a.name === agentName && a.is_global === true);
            } else if (selectedValue.startsWith('personal_')) {
                const agentName = selectedValue.substring(9); // Remove 'personal_' prefix
                selectedAgentObj = agents.find(a => a.name === agentName && a.is_global === false);
            } else {
                // Fallback for agents without prefix (backwards compatibility)
                selectedAgentObj = agents.find(a => a.name === selectedValue);
            }
            
            console.log('DEBUG: Found agent object:', selectedAgentObj);
            
            if (selectedAgentObj) {
                const payload = { name: selectedAgentObj.name, is_global: !!selectedAgentObj.is_global };
                console.log('DEBUG: Setting selected agent payload:', payload);
                console.log('DEBUG: Agent is_global flag:', selectedAgentObj.is_global);
                console.log('DEBUG: !!selectedAgentObj.is_global:', !!selectedAgentObj.is_global);
                
                await setSelectedAgent(payload);
                console.log('DEBUG: Agent selection saved successfully');
            } else {
                console.log('DEBUG: No agent found with value:', selectedValue);
            }
        };
    } catch (e) {
        console.error('Error loading agents:', e);
    }
}

// Call initializeAgentInteractions on load
initializeAgentInteractions();