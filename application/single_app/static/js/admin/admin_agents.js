// admin_agents.js
// Handles CRUD operations and modal logic for Agents in the admin UI
// Mirrors the structure and robustness of admin_plugins.js
import { showToast } from "../chat/chat-toast.js";

document.addEventListener('DOMContentLoaded', function () {
    // Elements
    const agentsTableBody = document.getElementById('agents-table-body');
    const addAgentBtn = document.getElementById('add-agent-btn');
    const agentModal = new bootstrap.Modal(document.getElementById('agentModal'));
    const agentModalTitle = document.getElementById('agentModalLabel');
    const agentModalSaveBtn = document.getElementById('agent-modal-save-btn');
    const defaultAgentSelect = document.getElementById('default-agent-select');
    const defaultAgentSelectMsg = document.getElementById('default-agent-select-msg');
    const defaultAgentCheckbox = document.getElementById('agent-default-agent');
    const defaultAgentCheckboxMsg = document.getElementById('default-agent-checkbox-msg');

    // State
    let editingAgentIndex = null;
    let agents = [];
    let editingAgentName = null;

    // Utility: Get agent data from form
    function getAgentFormData() {
        let actionsToLoad = [];
        let additionalSettings = {};
        try {
            const actionsRaw = document.getElementById('agent-actions-to-load').value.trim();
            if (actionsRaw) actionsToLoad = JSON.parse(actionsRaw);
        } catch (e) {
            alert('Actions to Load must be a valid JSON array.');
            throw e;
        }
        try {
            const settingsRaw = document.getElementById('agent-additional-settings').value.trim();
            if (settingsRaw) additionalSettings = JSON.parse(settingsRaw);
        } catch (e) {
            alert('Additional Settings must be a valid JSON object.');
            throw e;
        }
        return {
            name: document.getElementById('agent-name').value.trim(),
            display_name: document.getElementById('agent-display-name').value.trim(),
            description: document.getElementById('agent-description').value.trim(),
            azure_openai_gpt_endpoint: document.getElementById('agent-gpt-endpoint').value.trim(),
            azure_openai_gpt_key: document.getElementById('agent-gpt-key').value.trim(),
            azure_openai_gpt_deployment: document.getElementById('agent-gpt-deployment').value.trim(),
            azure_openai_gpt_api_version: document.getElementById('agent-gpt-api-version').value.trim(),
            azure_agent_apim_gpt_endpoint: document.getElementById('agent-apim-endpoint').value.trim(),
            azure_agent_apim_gpt_subscription_key: document.getElementById('agent-apim-subscription-key').value.trim(),
            azure_agent_apim_gpt_deployment: document.getElementById('agent-apim-deployment').value.trim(),
            azure_agent_apim_gpt_api_version: document.getElementById('agent-apim-api-version').value.trim(),
            enable_agent_gpt_apim: document.getElementById('agent-enable-apim').checked,
            default_agent: document.getElementById('agent-default-agent').checked,
            instructions: document.getElementById('agent-instructions').value.trim(),
            actions_to_load: actionsToLoad,
            other_settings: additionalSettings,
            plugins_to_load: []
        };
    }

    // Utility: Populate form with agent data
    function setAgentFormData(agent) {
        document.getElementById('agent-name').value = agent.name || '';
        document.getElementById('agent-display-name').value = agent.display_name || '';
        document.getElementById('agent-description').value = agent.description || '';
        document.getElementById('agent-gpt-endpoint').value = agent.azure_openai_gpt_endpoint || '';
        document.getElementById('agent-gpt-key').value = agent.azure_openai_gpt_key || '';
        document.getElementById('agent-gpt-deployment').value = agent.azure_openai_gpt_deployment || '';
        document.getElementById('agent-gpt-api-version').value = agent.azure_openai_gpt_api_version || '';
        document.getElementById('agent-apim-endpoint').value = agent.azure_agent_apim_gpt_endpoint || '';
        document.getElementById('agent-apim-subscription-key').value = agent.azure_agent_apim_gpt_subscription_key || '';
        document.getElementById('agent-apim-deployment').value = agent.azure_agent_apim_gpt_deployment || '';
        document.getElementById('agent-apim-api-version').value = agent.azure_agent_apim_gpt_api_version || '';
        document.getElementById('agent-enable-apim').checked = !!agent.enable_agent_gpt_apim;
        // Show/hide APIM fields
        const apimToggle = document.getElementById('agent-enable-apim');
        const gptFields = document.getElementById('agent-gpt-fields');
        const apimFields = document.getElementById('agent-apim-fields');
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
        updateApimVisibility();
        document.getElementById('agent-default-agent').checked = !!agent.default_agent;
        document.getElementById('agent-instructions').value = agent.instructions || '';
        document.getElementById('agent-actions-to-load').value = agent.actions_to_load ? JSON.stringify(agent.actions_to_load, null, 2) : '[]';
        document.getElementById('agent-additional-settings').value = agent.other_settings ? JSON.stringify(agent.other_settings, null, 2) : '{}';

        // Grey out default checkbox if another agent is default (unless editing that agent)
        let defaultAgent = agents.find(a => a.default_agent);
        let isEditingDefault = agent && agent.name && defaultAgent && agent.name === defaultAgent.name;
        if (defaultAgent && !isEditingDefault) {
            defaultAgentCheckbox.disabled = true;
            defaultAgentCheckboxMsg.textContent = `Only one default agent is allowed. '${defaultAgent.display_name || defaultAgent.name}' is currently default.`;
        } else {
            defaultAgentCheckbox.disabled = false;
            defaultAgentCheckboxMsg.textContent = '';
        }
    }
    // Utility: Populate default agent dropdown
    function renderDefaultAgentDropdown() {
        if (!defaultAgentSelect) return;
        defaultAgentSelect.innerHTML = '';
        if (!agents.length) {
            defaultAgentSelect.disabled = true;
            defaultAgentSelectMsg.textContent = 'No agents available.';
            return;
        }
        agents.forEach(agent => {
            let opt = document.createElement('option');
            opt.value = agent.name;
            opt.textContent = agent.display_name || agent.name;
            if (agent.default_agent) opt.selected = true;
            defaultAgentSelect.appendChild(opt);
        });
        defaultAgentSelect.disabled = false;
        defaultAgentSelectMsg.textContent = '';
    }

    // Handle default agent dropdown change
    if (defaultAgentSelect) {
        defaultAgentSelect.addEventListener('change', async function () {
            let selectedName = defaultAgentSelect.value;
            if (!selectedName) return;
            try {
                const resp = await fetch('/api/admin/agents/set-default', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: selectedName })
                });
                const data = await resp.json();
                if (!resp.ok) {
                    alert(data.error || 'Failed to update default agent.');
                    return;
                }
                await loadAgents();
            } catch (err) {
                alert('Failed to update default agent.');
            }
        });
    }


    // Render agents table
    function renderAgentsTable() {
        agentsTableBody.innerHTML = '';
        agents.forEach((agent, idx) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${agent.name}</td>
                <td>${agent.display_name}</td>
                <td>${agent.description || ''}</td>
                <td>${agent.default_agent ? '<span class="badge bg-success">Yes</span>' : ''}</td>
                <td>
                    <button type="button" class="btn btn-sm btn-secondary edit-agent-btn" data-index="${idx}">Edit</button>
                    <button type="button" class="btn btn-sm btn-danger delete-agent-btn" data-index="${idx}">Delete</button>
                </td>
            `;
            agentsTableBody.appendChild(tr);
        });
        renderDefaultAgentDropdown();
    }

    // Add Agent
    addAgentBtn.addEventListener('click', function () {
        editingAgentIndex = null;
        editingAgentName = null;
        agentModalTitle.textContent = 'Add Agent';
        setAgentFormData({}); // Clear all modal fields
        agentModal.show();
    });

    // Edit/Delete via event delegation
    agentsTableBody.addEventListener('click', async function (e) {
        if (e.target.classList.contains('edit-agent-btn')) {
            const idx = parseInt(e.target.getAttribute('data-index'));
            editingAgentIndex = idx;
            editingAgentName = agents[idx].name;
            agentModalTitle.textContent = 'Edit Agent';
            setAgentFormData(agents[idx]);
            agentModal.show();
        } else if (e.target.classList.contains('delete-agent-btn')) {
            const idx = parseInt(e.target.getAttribute('data-index'));
            const agentName = agents[idx].name;
            if (confirm('Are you sure you want to delete this agent?')) {
                try {
                    const resp = await fetch(`/api/admin/agents/${encodeURIComponent(agentName)}`, {
                        method: 'DELETE',
                        headers: { 'Content-Type': 'application/json' }
                    });
                    if (!resp.ok) {
                        const data = await resp.json();
                        alert(data.error || 'Failed to delete agent.');
                        return;
                    }
                    agents.splice(idx, 1);
                    renderAgentsTable();
                } catch (err) {
                    alert('Failed to delete agent.');
                }
            }
        }
    });

    // Save Agent (Add/Edit)
    agentModalSaveBtn.addEventListener('click', async function () {
        const agentData = getAgentFormData();
        // Validate with standalone validator (ES module, draft-07+)
        try {
            if (!window.validateAgent) {
                window.validateAgent = (await import('/static/js/validateAgent.mjs')).default;
            }
            const valid = window.validateAgent(agentData);
            if (!valid) {
                showAgentModalError('Validation error: Invalid agent data.');
                return;
            }
        } catch (e) {
            showAgentModalError('Schema validation failed: ' + e.message);
            return;
        }
        try {
            let resp, data;
            if (editingAgentIndex === null) {
                // Add
                resp = await fetch('/api/admin/agents', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(agentData)
                });
                data = await resp.json();
                if (!resp.ok) {
                    showAgentModalError(data.error || 'Failed to add agent.');
                    return;
                }
                agents.push(agentData);
            } else {
                // Edit
                resp = await fetch(`/api/admin/agents/${encodeURIComponent(editingAgentName)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(agentData)
                });
                data = await resp.json();
                if (!resp.ok) {
                    showAgentModalError(data.error || 'Failed to update agent.');
                    return;
                }
                agents[editingAgentIndex] = agentData;
            }
            renderAgentsTable();
            agentModal.hide();
        } catch (err) {
            showAgentModalError('Failed to save agent.');
        }

    // Utility: Show agent modal error
    function showAgentModalError(msg) {
        const errDiv = document.getElementById('agent-modal-error');
        if (errDiv) {
            errDiv.textContent = msg;
            errDiv.style.display = 'block';
        } else {
            alert(msg);
        }
    }
    });

    // Load initial agents from backend
    async function loadAgents() {
        try {
            const resp = await fetch('/api/admin/agents');
            if (!resp.ok) throw new Error('Failed to load agents');
            agents = await resp.json();
            renderAgentsTable();
            renderDefaultAgentDropdown();
        } catch (err) {
            agents = [];
            renderAgentsTable();
            renderDefaultAgentDropdown();
        }
    }
    loadAgents();

    // --- Orchestration Settings Logic ---
    const orchestrationTypeSelect = document.getElementById('orchestration_type');
    const maxRoundsGroup = document.getElementById('max_rounds_per_agent_group');
    const maxRoundsInput = document.getElementById('max_rounds_per_agent');
    const saveOrchBtn = document.getElementById('save-orchestration-settings-btn');
    const orchStatus = document.getElementById('orchestration-settings-status');

    let orchestrationTypes = [];
    let orchestrationSettings = {};

    async function loadOrchestrationSettings() {
        try {
            const [typesRes, settingsRes] = await Promise.all([
                fetch('/api/orchestration_types'),
                fetch('/api/orchestration_settings'),
            ]);
            orchestrationTypes = await typesRes.json();
            orchestrationSettings = await settingsRes.json();
            renderOrchestrationForm();
        } catch (e) {
            orchStatus.textContent = 'Failed to load orchestration settings.';
            orchStatus.style.color = 'red';
        }
    }

    function renderOrchestrationForm() {
        if (!orchestrationTypeSelect) return;
        // Populate dropdown
        orchestrationTypeSelect.innerHTML = '';
        orchestrationTypes.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.value;
            opt.textContent = t.label;
            orchestrationTypeSelect.appendChild(opt);
        });
        orchestrationTypeSelect.value = orchestrationSettings.orchestration_type || '';
        maxRoundsInput.value = orchestrationSettings.max_rounds_per_agent || 1;
        toggleMaxRounds();
    }

    function toggleMaxRounds() {
        if (!orchestrationTypeSelect) return;
        if (orchestrationTypeSelect.value === 'group_chat') {
            maxRoundsGroup.style.display = '';
        } else {
            maxRoundsGroup.style.display = 'none';
        }
    }

    if (orchestrationTypeSelect) {
        orchestrationTypeSelect.addEventListener('change', toggleMaxRounds);
    }


    if (saveOrchBtn) {
        saveOrchBtn.addEventListener('click', async function () {
            const payload = {
                orchestration_type: orchestrationTypeSelect.value,
                max_rounds_per_agent: parseInt(maxRoundsInput.value, 10),
            };
            if (payload.orchestration_type !== 'group_chat') {
                payload.max_rounds_per_agent = 1;
            }
            try {
                const res = await fetch('/api/orchestration_settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await res.json();
                if (res.ok) {
                    showToast('Orchestration settings saved!', 'success');
                } else {
                    showToast(data.error || 'Failed to save orchestration settings.', 'danger');
                }
            } catch (e) {
                showToast('Failed to save orchestration settings.', 'danger');
            }
        });
    }
    loadOrchestrationSettings();

    // --- Explicit: Per-User Semantic Kernel Toggle (Async Save) ---
    const perUserSKToggle = document.getElementById('toggle-per-user-sk');
    if (perUserSKToggle) {
        perUserSKToggle.addEventListener('change', async function() {
            const checked = perUserSKToggle.checked;
            perUserSKToggle.disabled = true;
            const restartMsg = document.getElementById('per-user-sk-restart-msg');
            if (restartMsg) restartMsg.style.display = 'none';
            try {
                const resp = await fetch('/api/admin/agents/settings/per_user_semantic_kernel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ value: checked })
                });
                const data = await resp.json();
                if (resp.ok) {
                    if (restartMsg) restartMsg.style.display = 'block';
                    showToast('Per-user Semantic Kernel setting updated. Restart required to take effect.', 'success');
                } else {
                    showToast(data.error || 'Failed to update setting.', 'danger');
                    perUserSKToggle.checked = !checked;
                }
            } catch (err) {
                showToast('Error updating setting: ' + err.message, 'danger');
                perUserSKToggle.checked = !checked;
            } finally {
                perUserSKToggle.disabled = false;
            }
        });
    }
});
