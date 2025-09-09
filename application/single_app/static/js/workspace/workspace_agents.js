// workspace_agents.js
// Handles user agent CRUD in the workspace UI

import { showToast } from "../chat/chat-toast.js";
import * as agentsCommon from '../agents_common.js';
import { AgentModalStepper } from '../agent_modal_stepper.js';

// --- DOM Elements & Globals ---
const agentsTbody = document.getElementById('agents-table-body');
const agentsErrorDiv = document.getElementById('workspace-agents-error');
const createAgentBtn = document.getElementById('create-agent-btn');
const agentsSearchInput = document.getElementById('agents-search');
let agents = [];
let filteredAgents = [];


// --- Function Definitions ---
function renderLoading() {
  if (agentsTbody) {
    agentsTbody.innerHTML = `<tr class="table-loading-row"><td colspan="3"><div class="spinner-border spinner-border-sm me-2" role="status"><span class="visually-hidden">Loading...</span></div>Loading agents...</td></tr>`;
  }
  if (agentsErrorDiv) agentsErrorDiv.innerHTML = '';
}

function renderError(msg) {
  if (agentsErrorDiv) {
    agentsErrorDiv.innerHTML = `<div class="alert alert-danger">${msg}</div>`;
  }
  if (agentsTbody) {
    agentsTbody.innerHTML = '';
  }
}

function filterAgents(searchTerm) {
  if (!searchTerm || !searchTerm.trim()) {
    filteredAgents = agents;
  } else {
    const term = searchTerm.toLowerCase().trim();
    filteredAgents = agents.filter(agent => {
      const displayName = (agent.display_name || agent.name || '').toLowerCase();
      const description = (agent.description || '').toLowerCase();
      return displayName.includes(term) || description.includes(term);
    });
  }
  renderAgentsTable(filteredAgents);
}

// --- Helper Functions ---

function truncateDisplayName(displayName, maxLength = 12) {
  if (!displayName || displayName.length <= maxLength) {
    return displayName;
  }
  return displayName.substring(0, maxLength) + '...';
}

function renderAgentsTable(agentsList) {
  if (!agentsTbody) return;
  agentsTbody.innerHTML = '';
  if (!agentsList.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="4" class="text-center text-muted">No agents found.</td>';
    agentsTbody.appendChild(tr);
    return;
  }
  // Fetch selected_agent from user settings (async)
  fetch('/api/user/settings').then(res => {
    if (!res.ok) throw new Error('Failed to load user settings');
    return res.json();
  }).then(settings => {
    let selectedAgentObj = settings.selected_agent;
    if (!selectedAgentObj && settings.settings && settings.settings.selected_agent) {
      selectedAgentObj = settings.settings.selected_agent;
    }
    let selectedAgentName = typeof selectedAgentObj === 'object' ? selectedAgentObj.name : selectedAgentObj;
    agentsTbody.innerHTML = '';
    for (const agent of agentsList) {
      const tr = document.createElement('tr');
      
      // Create action buttons
      let actionButtons = `<button class="btn btn-sm btn-primary chat-agent-btn me-1" data-name="${agent.name}" title="Chat with this agent">
        <i class="bi bi-chat-dots me-1"></i>Chat
      </button>`;
      
      if (!agent.is_global) {
        actionButtons += `
          <button class="btn btn-sm btn-outline-secondary edit-agent-btn me-1" data-name="${agent.name}" title="Edit agent">
            <i class="bi bi-pencil"></i>
          </button>
          <button class="btn btn-sm btn-outline-danger delete-agent-btn" data-name="${agent.name}" title="Delete agent">
            <i class="bi bi-trash"></i>
          </button>
        `;
      }
      
      const truncatedDisplayName = truncateDisplayName(agent.display_name || agent.name || '');
      
      tr.innerHTML = `
        <td>
          <strong>${truncatedDisplayName}</strong>
          ${agent.is_global ? ' <span class="badge bg-info text-dark">Global</span>' : ''}
        </td>
        <td class="text-muted small">${agent.description || 'No description available'}</td>
        <td>${actionButtons}</td>
      `;
      agentsTbody.appendChild(tr);
    }
  }).catch(e => {
    renderError('Could not load agent settings: ' + e.message);
    // Fallback: render table without settings
    agentsTbody.innerHTML = '';
    for (const agent of agentsList) {
      const tr = document.createElement('tr');
      
      // Create action buttons
      let actionButtons = `<button class="btn btn-sm btn-primary chat-agent-btn me-1" data-name="${agent.name}" title="Chat with this agent">
        <i class="bi bi-chat-dots me-1"></i>Chat
      </button>`;
      
      if (!agent.is_global) {
        actionButtons += `
          <button class="btn btn-sm btn-outline-secondary edit-agent-btn me-1" data-name="${agent.name}" title="Edit agent">
            <i class="bi bi-pencil"></i>
          </button>
          <button class="btn btn-sm btn-outline-danger delete-agent-btn" data-name="${agent.name}" title="Delete agent">
            <i class="bi bi-trash"></i>
          </button>
        `;
      }
      
      const truncatedDisplayName = truncateDisplayName(agent.display_name || agent.name || '');
      
      tr.innerHTML = `
        <td>
          <strong>${truncatedDisplayName}</strong>
          ${agent.is_global ? ' <span class="badge bg-info text-dark">Global</span>' : ''}
        </td>
        <td class="text-muted small">${agent.description || 'No description available'}</td>
        <td>${actionButtons}</td>
      `;
      agentsTbody.appendChild(tr);
    }
  });
}

async function fetchAgents() {
  renderLoading();
  try {
    const res = await fetch('/api/user/agents');
    if (!res.ok) throw new Error('Failed to load agents');
    agents = await res.json();
    filteredAgents = agents; // Initialize filtered list
    renderAgentsTable(filteredAgents);
  } catch (e) {
    renderError(e.message);
  }
}

function attachAgentTableEvents() {
  console.log('Attaching agent table events');
  
  if (createAgentBtn) {
    console.log('Setting up create agent button event');
    createAgentBtn.onclick = () => {
      console.log('Create agent button clicked');
      openAgentModal();
    };
  } else {
    console.error('Create agent button not found');
  }
  
  // Search functionality
  if (agentsSearchInput) {
    agentsSearchInput.addEventListener('input', (e) => {
      filterAgents(e.target.value);
    });
  }
  
  agentsTbody.addEventListener('click', function (e) {
    console.log('Agent table clicked, target:', e.target);
    
    // Find the button element (could be the target or a parent)
    const editBtn = e.target.closest('.edit-agent-btn');
    const deleteBtn = e.target.closest('.delete-agent-btn');
    const chatBtn = e.target.closest('.chat-agent-btn');
    
    if (editBtn) {
      console.log('Edit agent button clicked, dataset:', editBtn.dataset);
      const agent = agents.find(a => a.name === editBtn.dataset.name);
      console.log('Found agent:', agent);
      openAgentModal(agent);
    }
    
    if (deleteBtn) {
      const agent = agents.find(a => a.name === deleteBtn.dataset.name);
      if (deleteBtn.disabled) return;
      if (confirm(`Delete agent '${agent.name}'?`)) deleteAgent(agent.name);
    }
    
    if (chatBtn) {
      const agentName = chatBtn.dataset.name;
      chatWithAgent(agentName);
    }
  });
}

async function chatWithAgent(agentName) {
  try {
    console.log('DEBUG: chatWithAgent called with agentName:', agentName);
    console.log('DEBUG: Available agents:', agents);
    
    // Find the agent to get its is_global status
    const agent = agents.find(a => a.name === agentName);
    console.log('DEBUG: Found agent:', agent);
    
    if (!agent) {
      throw new Error('Agent not found');
    }
    
    console.log('DEBUG: Agent is_global flag:', agent.is_global);
    console.log('DEBUG: !!agent.is_global:', !!agent.is_global);
    
    // Set the selected agent with proper is_global flag
    const payloadData = { 
      selected_agent: { 
        name: agentName, 
        is_global: !!agent.is_global 
      } 
    };
    console.log('DEBUG: Sending payload:', payloadData);
    
    const resp = await fetch('/api/user/settings/selected_agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payloadData)
    });
    
    if (!resp.ok) {
      throw new Error('Failed to select agent');
    }
    
    console.log('DEBUG: Agent selection saved successfully');
    
    // Navigate to chat page
    window.location.href = '/chats';
  } catch (err) {
    console.error('Error selecting agent for chat:', err);
    showToast('Error selecting agent for chat. Please try again.', 'error');
  }
}


async function openAgentModal(agent = null, selectedAgentName = null) {
  console.log('openAgentModal called with agent:', agent);

  // Use the stepper to show the modal (instance created once globally)

  // Use the stepper to show the modal
  try {
    console.log('Calling showModal on AgentModalStepper');
    await window.agentModalStepper.showModal(agent);
    console.log('Modal should be visible now');

    // --- Custom Connection Toggle Logic (mirroring admin_agents.js) ---
    // Setup toggles using shared helpers
    agentsCommon.setupApimToggle(
      document.getElementById('agent-enable-apim'),
      document.getElementById('agent-apim-fields'),
      document.getElementById('agent-gpt-fields'),
      () => agentsCommon.loadGlobalModelsForModal({
        endpoint: '/api/user/agent/settings',
        agent,
        globalModelSelect: document.getElementById('agent-global-model-select'),
        isGlobal: false,
        customConnectionCheck: agentsCommon.shouldEnableCustomConnection,
        deploymentFieldIds: { gpt: 'agent-gpt-deployment', apim: 'agent-apim-deployment' }
      })
    );
    agentsCommon.toggleCustomConnectionUI(
      agentsCommon.shouldEnableCustomConnection(agent),
      {
        customFields: document.getElementById('agent-custom-connection-fields'),
        globalModelGroup: document.getElementById('agent-global-model-group'),
        advancedSection: document.getElementById('agent-advanced-section')
      }
    );
    agentsCommon.toggleAdvancedUI(
      agentsCommon.shouldExpandAdvanced(agent),
      {
        customFields: document.getElementById('agent-custom-connection-fields'),
        globalModelGroup: document.getElementById('agent-global-model-group'),
        advancedSection: document.getElementById('agent-advanced-section')
      }
    );
    // Attach shared toggle handlers after shared helpers
    const customConnectionToggle = document.getElementById('agent-custom-connection');
    const advancedToggle = document.getElementById('agent-advanced-toggle');
    const modalElements = {
      customFields: document.getElementById('agent-custom-connection-fields'),
      globalModelGroup: document.getElementById('agent-global-model-group'),
      advancedSection: document.getElementById('agent-advanced-section')
    };
    agentsCommon.attachCustomConnectionToggleHandler(
      customConnectionToggle,
      agent,
      modalElements,
      () => agentsCommon.loadGlobalModelsForModal({
        endpoint: '/api/user/agent/settings',
        agent,
        globalModelSelect: document.getElementById('agent-global-model-select'),
        isGlobal: false,
        customConnectionCheck: agentsCommon.shouldEnableCustomConnection,
        deploymentFieldIds: { gpt: 'agent-gpt-deployment', apim: 'agent-apim-deployment' }
      })
    );
    agentsCommon.attachAdvancedToggleHandler(advancedToggle, modalElements);

    // Clear error div on modal open (optional, if you have an error div)
    const errorDiv = document.getElementById('agent-modal-error');
    if (errorDiv) {
      errorDiv.textContent = '';
      errorDiv.style.display = 'none';
    }

  } catch (error) {
    console.error('Error opening agent modal:', error);
    showToast('Error opening agent modal. Please try again.', 'error');
  }
}

async function deleteAgent(name) {
  // For user agents, just remove from the list and POST the new list
  try {
    const res = await fetch('/api/user/agents');
    if (!res.ok) throw new Error('Failed to load agents');
    let agents = await res.json();
    agents = agents.filter(a => a.name !== name);
    const saveRes = await fetch('/api/user/agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(agents)
    });
    if (!saveRes.ok) throw new Error('Failed to delete agent');
    fetchAgents();
  } catch (e) {
    renderError(e.message);
  }
}


// --- Execution: Event Wiring & Initial Load ---

function initializeWorkspaceAgentUI() {
  window.agentModalStepper = new AgentModalStepper(false);
  attachAgentTableEvents();
  fetchAgents();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeWorkspaceAgentUI);
} else {
  initializeWorkspaceAgentUI();
}

// Expose fetchAgents globally for migration script
window.fetchAgents = fetchAgents;
