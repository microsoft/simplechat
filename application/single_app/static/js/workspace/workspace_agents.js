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
      
      tr.innerHTML = `
        <td>
          <strong>${agent.display_name || agent.name || ''}</strong>
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
      
      tr.innerHTML = `
        <td>
          <strong>${agent.display_name || agent.name || ''}</strong>
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
  if (createAgentBtn) {
    createAgentBtn.onclick = () => openAgentModal();
  }
  
  // Search functionality
  if (agentsSearchInput) {
    agentsSearchInput.addEventListener('input', (e) => {
      filterAgents(e.target.value);
    });
  }
  
  agentsTbody.addEventListener('click', function (e) {
    if (e.target.classList.contains('edit-agent-btn')) {
      const agent = agents.find(a => a.name === e.target.dataset.name);
      openAgentModal(agent);
    }
    if (e.target.classList.contains('delete-agent-btn')) {
      const agent = agents.find(a => a.name === e.target.dataset.name);
      if (e.target.disabled) return;
      if (confirm(`Delete agent '${agent.name}'?`)) deleteAgent(agent.name);
    }
    if (e.target.classList.contains('chat-agent-btn')) {
      const agentName = e.target.dataset.name;
      chatWithAgent(agentName);
    }
  });
}

async function chatWithAgent(agentName) {
  try {
    // Set the selected agent
    const resp = await fetch('/api/user/settings/selected_agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selected_agent: { name: agentName } })
    });
    
    if (!resp.ok) {
      throw new Error('Failed to select agent');
    }
    
    // Navigate to chat page
    window.location.href = '/chats';
  } catch (err) {
    console.error('Error selecting agent for chat:', err);
    showToast('Error selecting agent for chat. Please try again.', 'error');
  }
}


async function openAgentModal(agent = null, selectedAgentName = null) {
  // Minimal, DRY modal logic using shared helpers
  const modalEl = document.getElementById('agentModal');
  if (!modalEl) return alert('Agent modal not found.');
  const modal = bootstrap.Modal.getOrCreateInstance(modalEl);

  // Initialize stepper
  if (!window.agentModalStepper) {
    window.agentModalStepper = new AgentModalStepper();
  }
  
  // Store agent data for use in stepper
  window.agentModalStepper.currentAgent = agent;
  
  window.agentModalStepper.showModal(agent);

  // Clear error div on modal open
  const errorDiv = document.getElementById('agent-modal-error');
  if (errorDiv) {
    errorDiv.textContent = '';
    errorDiv.classList.add('d-none');
  }

  // Populate modal fields using shared helper
  agentsCommon.setAgentModalFields(agent || {}, { context: 'user' });

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

  // Save handler
  const saveBtn = document.getElementById('agent-modal-save-btn');
  saveBtn.onclick = async () => {
    let newAgent;
    try {
      newAgent = agentsCommon.getAgentModalFields({ context: 'user' });
      // Only preserve id if editing; do not generate or strip id on create
      if (agent && agent.id) newAgent.id = agent.id;
      // If id is still not present, fetch a GUID from backend
      if (!('id' in newAgent) || !newAgent.id) {
        try {
          const guidResp = await fetch('/api/agents/generate_id');
          if (guidResp.ok) {
            const guidData = await guidResp.json();
            newAgent.id = guidData.id;
          } else {
            newAgent.id = '';
          }
        } catch (guidErr) {
          newAgent.id = '';
        }
      }
      newAgent.actions_to_load = window.agentModalStepper ? window.agentModalStepper.getSelectedActionIds() : [];
      newAgent.is_global = false;
    } catch (e) {
      const msg = 'Additional Settings: ' + e.message;
      errorDiv.textContent = msg;
      errorDiv.classList.remove('d-none');
      showToast(msg, 'danger');
      return;
    }
    // Validate with JSON schema (Ajv)
    try {
      if (!window.validateAgent) {
        window.validateAgent = (await import('/static/js/validateAgent.mjs')).default;
      }
      const valid = window.validateAgent(newAgent);
      if (!valid) {
        let errorMsg = 'Validation error: Invalid agent data.';
        if (window.validateAgent.errors && window.validateAgent.errors.length) {
          errorMsg += '\n' + window.validateAgent.errors.map(e => `${e.instancePath} ${e.message}`).join('\n');
        }
        errorDiv.textContent = errorMsg;
        errorDiv.classList.remove('d-none');
        showToast(errorMsg, 'danger');
        return;
      }
    } catch (e) {
      const msg = 'Schema validation failed: ' + e.message;
      errorDiv.textContent = msg;
      errorDiv.classList.remove('d-none');
      showToast(msg, 'danger');
      return;
    }
    try {
      // Save agent (POST or PUT depending on context, here always POST for user agents)
      const res = await fetch('/api/user/agents');
      let agents = [];
      if (res.ok) {
        agents = await res.json();
      }
      // If editing, replace; else, add
      const idx = agent ? agents.findIndex(a => a.id === agent.id) : -1;
      if (idx >= 0) {
        agents[idx] = newAgent;
      } else {
        agents.push(newAgent);
      }
      const saveRes = await fetch('/api/user/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agents)
      });
      if (!saveRes.ok) throw new Error('Failed to save agent');
      modal.hide();
      // After saving, re-fetch user settings and set dropdown to selected agent
      await fetchAgents();
      try {
        const settingsRes = await fetch('/api/user/settings');
        if (settingsRes.ok) {
          const settings = await settingsRes.json();
          let selectedAgentObj = settings.selected_agent;
          if (!selectedAgentObj && settings.settings && settings.settings.selected_agent) {
            selectedAgentObj = settings.settings.selected_agent;
          }
          // Note: selectedAgentName is available for future use if needed
        }
      } catch (e) {
        // Ignore errors, fallback to default behavior
      }
    } catch (e) {
      errorDiv.textContent = e.message;
      errorDiv.classList.remove('d-none');
      showToast(e.message, 'danger');
    }
  };
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
  modal.show();
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
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    attachAgentTableEvents();
    fetchAgents();
  });
} else {
  attachAgentTableEvents();
  fetchAgents();
}

// Expose fetchAgents globally for migration script
window.fetchAgents = fetchAgents;
