// workspace_agents.js
// Handles user agent CRUD in the workspace UI

// DOM elements
const agentsTbody = document.getElementById('agents-table-body');
const agentsErrorDiv = document.getElementById('workspace-agents-error');
const createAgentBtn = document.getElementById('create-agent-btn');
const defaultAgentSelect = document.getElementById('default-agent-select');
const defaultAgentSelectMsg = document.getElementById('default-agent-select-msg');

function renderLoading() {
  if (agentsTbody) {
    agentsTbody.innerHTML = `<tr class="table-loading-row"><td colspan="4"><div class="spinner-border spinner-border-sm me-2" role="status"><span class="visually-hidden">Loading...</span></div>Loading agents...</td></tr>`;
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

function renderAgentsTable(agents) {
  if (!agentsTbody) return;
  agentsTbody.innerHTML = '';
  if (!agents.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="4" class="text-center text-muted">No agents found.</td>';
    agentsTbody.appendChild(tr);
  } else {
    for (const agent of agents) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${agent.name || ''}</td>
        <td>${agent.display_name || ''}</td>
        <td>${agent.default_agent ? '<span class="badge bg-primary">Default</span>' : ''}</td>
        <td>
          <button class="btn btn-sm btn-primary edit-agent-btn" data-name="${agent.name}">Edit</button>
          <button class="btn btn-sm btn-danger ms-1 delete-agent-btn" data-name="${agent.name}">Delete</button>
        </td>
      `;
      agentsTbody.appendChild(tr);
    }
  }
  renderDefaultAgentDropdown(agents);
}

function renderDefaultAgentDropdown(agents) {
  if (!defaultAgentSelect) return;
  defaultAgentSelect.innerHTML = '';
  if (!agents.length) {
    defaultAgentSelect.disabled = true;
    if (defaultAgentSelectMsg) defaultAgentSelectMsg.textContent = 'No agents available.';
    return;
  }
  let foundDefault = false;
  agents.forEach(agent => {
    let opt = document.createElement('option');
    opt.value = agent.name;
    opt.textContent = agent.display_name || agent.name;
    if (agent.default_agent) {
      opt.selected = true;
      foundDefault = true;
    }
    defaultAgentSelect.appendChild(opt);
  });
  defaultAgentSelect.disabled = false;
  if (!foundDefault && defaultAgentSelectMsg) {
    defaultAgentSelectMsg.textContent = 'No default agent set.';
  } else if (defaultAgentSelectMsg) {
    defaultAgentSelectMsg.textContent = '';
  }
}

async function fetchAgents() {
  renderLoading();
  try {
    const res = await fetch('/api/user/agents');
    if (!res.ok) throw new Error('Failed to load agents');
    const agents = await res.json();
    renderAgentsTable(agents);
    attachAgentTableEvents(agents);
  } catch (e) {
    renderError(e.message);
  }
}

function attachAgentTableEvents(agents) {
  if (createAgentBtn) {
    createAgentBtn.onclick = () => openAgentModal();
  }
  // Default agent dropdown change
  if (defaultAgentSelect) {
    defaultAgentSelect.onchange = async function () {
      const selectedName = defaultAgentSelect.value;
      if (!selectedName) return;
      defaultAgentSelect.disabled = true;
      if (defaultAgentSelectMsg) defaultAgentSelectMsg.textContent = '';
      try {
        const resp = await fetch('/api/user/agents/set-default', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: selectedName })
        });
        const data = await resp.json();
        if (!resp.ok) {
          if (defaultAgentSelectMsg) defaultAgentSelectMsg.textContent = data.error || 'Failed to update default agent.';
          return;
        }
        await fetchAgents();
      } catch (err) {
        if (defaultAgentSelectMsg) defaultAgentSelectMsg.textContent = 'Failed to update default agent.';
      } finally {
        defaultAgentSelect.disabled = false;
      }
    };
  }
  for (const btn of document.querySelectorAll('.edit-agent-btn')) {
    btn.onclick = () => {
      const agent = agents.find(a => a.name === btn.dataset.name);
      openAgentModal(agent);
    };
  }
  for (const btn of document.querySelectorAll('.delete-agent-btn')) {
    btn.onclick = () => {
      const agent = agents.find(a => a.name === btn.dataset.name);
      if (agent.default_agent) {
        alert('You must set another agent as default before deleting this one.');
        return;
      }
      if (confirm(`Delete agent '${agent.name}'?`)) deleteAgent(agent.name);
    };
  }
}

function openAgentModal(agent = null) {
  // Get modal and fields
  const modalEl = document.getElementById('agentModal');
  if (!modalEl) return alert('Agent modal not found.');
  const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  // Fields
  const nameInput = document.getElementById('agent-name');
  const displayNameInput = document.getElementById('agent-display-name');
  const descInput = document.getElementById('agent-description');
  const endpointInput = document.getElementById('agent-gpt-endpoint');
  const keyInput = document.getElementById('agent-gpt-key');
  const deploymentInput = document.getElementById('agent-gpt-deployment');
  const apiVersionInput = document.getElementById('agent-gpt-api-version');
  const apimToggle = document.getElementById('agent-enable-apim');
  const gptFields = document.getElementById('agent-gpt-fields');
  const apimFields = document.getElementById('agent-apim-fields');
  const apimEndpointInput = document.getElementById('agent-apim-endpoint');
  const apimKeyInput = document.getElementById('agent-apim-subscription-key');
  const apimDeploymentInput = document.getElementById('agent-apim-deployment');
  const apimApiVersionInput = document.getElementById('agent-apim-api-version');
  const instructionsInput = document.getElementById('agent-instructions');
  const actionsInput = document.getElementById('agent-actions-to-load');
  const settingsInput = document.getElementById('agent-additional-settings');
  const defaultCheckbox = document.getElementById('agent-default-agent');
  const errorDiv = document.getElementById('agent-modal-error');
  const saveBtn = document.getElementById('agent-modal-save-btn');
  // Reset error
  errorDiv.classList.add('d-none');
  errorDiv.textContent = '';
  // APIM toggle logic
  function updateApimVisibility() {
    if (apimToggle.checked) {
      apimFields.style.display = '';
      gptFields.style.display = 'none';
    } else {
      apimFields.style.display = 'none';
      gptFields.style.display = '';
    }
  }
  apimToggle.onchange = updateApimVisibility;
  // Populate fields
  if (agent) {
    nameInput.value = agent.name || '';
    nameInput.disabled = true;
    displayNameInput.value = agent.display_name || '';
    descInput.value = agent.description || '';
    endpointInput.value = agent.azure_openai_gpt_endpoint || '';
    keyInput.value = agent.azure_openai_gpt_key || '';
    deploymentInput.value = agent.azure_openai_gpt_deployment || '';
    apiVersionInput.value = agent.azure_openai_gpt_api_version || '';
    apimEndpointInput.value = agent.azure_agent_apim_gpt_endpoint || '';
    apimKeyInput.value = agent.azure_agent_apim_gpt_subscription_key || '';
    apimDeploymentInput.value = agent.azure_agent_apim_gpt_deployment || '';
    apimApiVersionInput.value = agent.azure_agent_apim_gpt_api_version || '';
    apimToggle.checked = !!agent.enable_agent_gpt_apim;
    updateApimVisibility();
    instructionsInput.value = agent.instructions || '';
    actionsInput.value = Array.isArray(agent.actions_to_load) ? JSON.stringify(agent.actions_to_load, null, 2) : (agent.actions_to_load || '');
    settingsInput.value = agent.other_settings ? JSON.stringify(agent.other_settings, null, 2) : '';
    defaultCheckbox.checked = !!agent.default_agent;
  } else {
    nameInput.value = '';
    nameInput.disabled = false;
    displayNameInput.value = '';
    descInput.value = '';
    endpointInput.value = '';
    keyInput.value = '';
    deploymentInput.value = '';
    apiVersionInput.value = '';
    apimEndpointInput.value = '';
    apimKeyInput.value = '';
    apimDeploymentInput.value = '';
    apimApiVersionInput.value = '';
    apimToggle.checked = false;
    updateApimVisibility();
    instructionsInput.value = '';
    actionsInput.value = '';
    settingsInput.value = '';
    defaultCheckbox.checked = false;
  }
  // Save handler
  saveBtn.onclick = async () => {
    // Parse JSON fields
    let actionsArr = [];
    let settingsObj = {};
    try {
      actionsArr = actionsInput.value.trim() ? JSON.parse(actionsInput.value) : [];
      if (!Array.isArray(actionsArr)) throw new Error('Actions must be a JSON array');
    } catch (e) {
      errorDiv.textContent = 'Actions to Load: ' + e.message;
      errorDiv.classList.remove('d-none');
      return;
    }
    try {
      settingsObj = settingsInput.value.trim() ? JSON.parse(settingsInput.value) : {};
      if (typeof settingsObj !== 'object' || Array.isArray(settingsObj)) throw new Error('Additional Settings must be a JSON object');
    } catch (e) {
      errorDiv.textContent = 'Additional Settings: ' + e.message;
      errorDiv.classList.remove('d-none');
      return;
    }
    // Build agent object
    const newAgent = {
      id: agent ? agent.id : crypto.randomUUID(),
      name: nameInput.value.trim(),
      display_name: displayNameInput.value.trim(),
      description: descInput.value.trim(),
      azure_openai_gpt_endpoint: endpointInput.value.trim(),
      azure_openai_gpt_key: keyInput.value.trim(),
      azure_openai_gpt_deployment: deploymentInput.value.trim(),
      azure_openai_gpt_api_version: apiVersionInput.value.trim(),
      azure_agent_apim_gpt_endpoint: apimEndpointInput.value.trim(),
      azure_agent_apim_gpt_subscription_key: apimKeyInput.value.trim(),
      azure_agent_apim_gpt_deployment: apimDeploymentInput.value.trim(),
      azure_agent_apim_gpt_api_version: apimApiVersionInput.value.trim(),
      enable_agent_gpt_apim: apimToggle.checked,
      default_agent: defaultCheckbox.checked,
      instructions: instructionsInput.value.trim(),
      actions_to_load: actionsArr,
      other_settings: settingsObj,
      plugins_to_load: []
    };
    // Validate with JSON schema (Ajv)
    try {
      if (!window.validateAgent) {
        window.validateAgent = (await import('/static/js/validateAgent.mjs')).default;
      }
      const valid = window.validateAgent(newAgent);
      if (!valid) {
        errorDiv.textContent = 'Validation error: Invalid agent data.';
        errorDiv.classList.remove('d-none');
        return;
      }
    } catch (e) {
      errorDiv.textContent = 'Schema validation failed: ' + e.message;
      errorDiv.classList.remove('d-none');
      return;
    }
    // Save
    try {
      // Get all agents, update or add
      const res = await fetch('/api/user/agents');
      if (!res.ok) throw new Error('Failed to load agents');
      let agents = await res.json();
      const idx = agents.findIndex(a => a.name === newAgent.name);
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
      fetchAgents();
    } catch (e) {
      errorDiv.textContent = e.message;
      errorDiv.classList.remove('d-none');
    }
  };
  // Show modal
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

// Initial load
fetchAgents();
