// workspace_agents.js
// Handles user agent CRUD in the workspace UI

import { showToast } from "../chat/chat-toast.js";
import * as agentsCommon from '../agents_common.js';
import { AgentModalStepper } from '../agent_modal_stepper.js';
import {
    humanizeName, truncateDescription, escapeHtml,
    setupViewToggle, switchViewContainers,
    openViewModal, createAgentCard
} from './view-utils.js';

// --- DOM Elements & Globals ---
const agentsTbody = document.getElementById('agents-table-body');
const agentsErrorDiv = document.getElementById('workspace-agents-error');
const createAgentBtn = document.getElementById('create-agent-btn');
const agentsSearchInput = document.getElementById('agents-search');
const agentsListView = document.getElementById('agents-list-view');
const agentsGridView = document.getElementById('agents-grid-view');
let agents = [];
let filteredAgents = [];
let currentViewMode = 'list';


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
  renderAgentsGrid(filteredAgents);
}

// Open the view modal for an agent with Chat/Edit/Delete actions in the footer
function openAgentViewModal(agent) {
  const callbacks = {
    onChat: (a) => chatWithAgent(a.name),
    onDelete: !agent.is_global ? (a) => { if (confirm(`Delete agent '${a.name}'?`)) deleteAgent(a.name); } : null
  };
  if (!agent.is_global) {
    callbacks.onEdit = (a) => openAgentModal(a);
  }
  openViewModal(agent, 'agent', callbacks);
}

// --- Rendering Functions ---
function renderAgentsTable(agentsList) {
  if (!agentsTbody) return;
  agentsTbody.innerHTML = '';
  if (!agentsList.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="3" class="text-center text-muted">No agents found.</td>';
    agentsTbody.appendChild(tr);
    return;
  }

  for (const agent of agentsList) {
    const tr = document.createElement('tr');
    const displayName = humanizeName(agent.display_name || agent.name || '');
    const description = agent.description || 'No description available';
    const truncatedDesc = truncateDescription(description, 90);
    const isGlobal = agent.is_global;

    // Action buttons — Chat + View always, Edit/Delete for non-global
    let actionButtons = `<button class="btn btn-sm btn-primary chat-agent-btn me-1" data-name="${escapeHtml(agent.name)}" title="Chat with this agent">
        <i class="bi bi-chat-dots me-1"></i>Chat
      </button>
      <button class="btn btn-sm btn-outline-info view-agent-btn me-1" data-name="${escapeHtml(agent.name)}" title="View details">
        <i class="bi bi-eye"></i>
      </button>`;

    if (!isGlobal) {
      actionButtons += `
        <button class="btn btn-sm btn-outline-secondary edit-agent-btn me-1" data-name="${escapeHtml(agent.name)}" title="Edit agent">
          <i class="bi bi-pencil"></i>
        </button>
        <button class="btn btn-sm btn-outline-danger delete-agent-btn" data-name="${escapeHtml(agent.name)}" title="Delete agent">
          <i class="bi bi-trash"></i>
        </button>`;
    }

    tr.innerHTML = `
      <td>
        <strong title="${escapeHtml(agent.display_name || agent.name || '')}">${escapeHtml(displayName)}</strong>
        ${isGlobal ? ' <span class="badge bg-info text-dark">Global</span>' : ''}
      </td>
      <td class="text-muted small" title="${escapeHtml(description)}">${escapeHtml(truncatedDesc)}</td>
      <td>${actionButtons}</td>
    `;
    agentsTbody.appendChild(tr);
  }
}

function renderAgentsGrid(agentsList) {
  if (!agentsGridView) return;
  agentsGridView.innerHTML = '';
  if (!agentsList.length) {
    agentsGridView.innerHTML = '<div class="col-12 text-center text-muted p-4">No agents found.</div>';
    return;
  }

  for (const agent of agentsList) {
    const card = createAgentCard(agent, {
      onChat: (a) => chatWithAgent(a.name),
      onView: (a) => openAgentViewModal(a),
      onEdit: (a) => openAgentModal(a),
      onDelete: (a) => { if (confirm(`Delete agent '${a.name}'?`)) deleteAgent(a.name); },
      canManage: !agent.is_global
    });
    agentsGridView.appendChild(card);
  }
}

async function fetchAgents() {
  renderLoading();
  try {
    const res = await fetch('/api/user/agents');
    if (!res.ok) throw new Error('Failed to load agents');
    agents = await res.json();
    filteredAgents = agents; // Initialize filtered list
    renderAgentsTable(filteredAgents);
    renderAgentsGrid(filteredAgents);
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
    // Find the button element (could be the target or a parent)
    const editBtn = e.target.closest('.edit-agent-btn');
    const deleteBtn = e.target.closest('.delete-agent-btn');
    const chatBtn = e.target.closest('.chat-agent-btn');
    const viewBtn = e.target.closest('.view-agent-btn');
    
    if (editBtn) {
      const agent = agents.find(a => a.name === editBtn.dataset.name);
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

    if (viewBtn) {
      const agent = agents.find(a => a.name === viewBtn.dataset.name);
      if (agent) openAgentViewModal(agent);
    }
  });
}

async function chatWithAgent(agentName) {
  try {
    const agent = agents.find(a => a.name === agentName);
    if (!agent) {
      throw new Error('Agent not found');
    }
    
    const payloadData = { 
      selected_agent: { 
        name: agentName, 
        is_global: !!agent.is_global 
      } 
    };
    
    const resp = await fetch('/api/user/settings/selected_agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payloadData)
    });
    
    if (!resp.ok) {
      throw new Error('Failed to select agent');
    }
    
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

  // Set up view toggle
  setupViewToggle('agents', 'agentsViewPreference', (mode) => {
    currentViewMode = mode;
    switchViewContainers(mode, agentsListView, agentsGridView);
    // Re-render grid if switching to grid and we have data
    if (mode === 'grid' && filteredAgents.length) {
      renderAgentsGrid(filteredAgents);
    }
  });

  fetchAgents();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeWorkspaceAgentUI);
} else {
  initializeWorkspaceAgentUI();
}

// Expose fetchAgents globally for migration script
window.fetchAgents = fetchAgents;
