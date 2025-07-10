// admin_agents.js
// Handles CRUD operations and modal logic for Agents in the admin UI
import { showToast } from "../chat/chat-toast.js";

document.addEventListener('DOMContentLoaded', function () {
    // Elements
    const agentsTableBody = document.getElementById('agents-table-body');
    const addAgentBtn = document.getElementById('add-agent-btn');
    const agentModal = new bootstrap.Modal(document.getElementById('agentModal'));
    const agentModalTitle = document.getElementById('agentModalLabel');
    const agentModalSaveBtn = document.getElementById('agent-modal-save-btn');
    const agentModalSetSelectedBtn = document.getElementById('agent-modal-set-selected-btn');
    const mergeGlobalToggle = document.getElementById('toggle-merge-global-sk');

    // State
    let editingAgentIndex = null;
    let agents = [];
    let editingAgentName = null, selectedAgent = null;

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
        let id = '';
        // If editing, preserve the existing id
        if (editingAgentIndex !== null && agents[editingAgentIndex] && agents[editingAgentIndex].id) {
            id = agents[editingAgentIndex].id;
        } else {
            // Generate a UUID for new agents
            id = crypto.randomUUID() || '';
        }
        return {
            id,
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
            instructions: document.getElementById('agent-instructions').value.trim(),
            actions_to_load: actionsToLoad,
            other_settings: additionalSettings,
            plugins_to_load: [],
            is_global: true
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
        document.getElementById('agent-instructions').value = agent.instructions || '';
        document.getElementById('agent-actions-to-load').value = agent.actions_to_load ? JSON.stringify(agent.actions_to_load, null, 2) : '[]';
        document.getElementById('agent-additional-settings').value = agent.other_settings ? JSON.stringify(agent.other_settings, null, 2) : '{}';

        // Show 'Set as Selected Agent' button only in edit mode and if not already selected
        if (agentModalSetSelectedBtn) {
            if (agent.name && selectedAgent && agent.name !== selectedAgent.name) {
                agentModalSetSelectedBtn.classList.remove('d-none');
            } else {
                agentModalSetSelectedBtn.classList.add('d-none');
            }
        }
    }

    // Add Agent
    addAgentBtn.addEventListener('click', function () {
        editingAgentIndex = null;
        editingAgentName = null;
        agentModalTitle.textContent = 'Add Agent';
        setAgentFormData({});
        agentModal.show();
        if (agentModalSetSelectedBtn) agentModalSetSelectedBtn.classList.add('d-none');
    });

    // Edit/Delete via event delegation
    agentsTableBody.addEventListener('click', async function (e) {
        if (e.target.classList.contains('edit-agent-btn')) {
            const idx = parseInt(e.target.getAttribute('data-index'));
            editingAgentIndex = idx;
            editingAgentName = agents[idx].name;
            agentModalTitle.textContent = 'Edit Agent';
            // Ensure selectedAgent is loaded before showing modal
            if (!selectedAgent) {
                await loadAgentsAndSelected();
            }
            setAgentFormData(agents[idx]);
            agentModal.show();
        } else if (e.target.classList.contains('delete-agent-btn')) {
            const idx = parseInt(e.target.getAttribute('data-index'));
            const agentName = agents[idx].name;
            // Prevent deleting selected agent
            if (selectedAgent && agentName === selectedAgent.name) {
                alert('You cannot delete the currently selected agent.');
                return;
            }
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

    // Set as Selected Agent (modal button)
    if (agentModalSetSelectedBtn) {
        agentModalSetSelectedBtn.addEventListener('click', async function () {
            if (editingAgentName && selectedAgent && editingAgentName !== selectedAgent.name) {
                try {
                    const resp = await fetch('/api/admin/agents/selected_agent', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: editingAgentName })
                    });
                    if (!resp.ok) {
                        const data = await resp.json();
                        alert(data.error || 'Failed to set selected agent.');
                        return;
                    }
                    await loadAgentsAndSelected();
                    agentModal.hide();
                    showToast('Selected agent updated!', 'success');
                } catch (err) {
                    alert('Failed to set selected agent.');
                }
            }
        });
    }

    // Save Agent (Add/Edit)
    agentModalSaveBtn.addEventListener('click', async function () {
        console.log('[DEBUG] Save Agent button clicked');
        const agentData = getAgentFormData();
        try {
            if (!window.validateAgent) {
                window.validateAgent = (await import('/static/js/validateAgent.mjs')).default;
            }
            // Log agent object before validation
            console.log('[DEBUG] Agent object before validation:', agentData);
            const valid = window.validateAgent(agentData);
            console.log('[DEBUG] Validation result:', valid);
            // If Ajv exposes errors, log them
            if (window.validateAgent.errors) {
                console.log('[DEBUG] Ajv validation errors:', window.validateAgent.errors);
            }
            if (!valid) {
                showAgentModalError('Validation error: Invalid agent data.');
                return;
            }
        } catch (e) {
            console.log('[DEBUG] Validation threw error:', e);
            showAgentModalError('Schema validation failed: ' + e.message);
            return;
        }
        try {
            let resp, data;
            if (editingAgentIndex === null) {
                console.log('[DEBUG] About to POST new agent');
                resp = await fetch('/api/admin/agents', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(agentData)
                });
                data = await resp.json();
                console.log('[DEBUG] POST response:', resp.status, data);
                if (!resp.ok) {
                    showAgentModalError(data.error || 'Failed to add agent.');
                    return;
                }
                agents.push(agentData);
            } else {
                console.log('[DEBUG] About to PUT update agent');
                resp = await fetch(`/api/admin/agents/${encodeURIComponent(editingAgentName)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(agentData)
                });
                data = await resp.json();
                console.log('[DEBUG] PUT response:', resp.status, data);
                if (!resp.ok) {
                    showAgentModalError(data.error || 'Failed to update agent.');
                    return;
                }
                agents[editingAgentIndex] = agentData;
            }
            await loadAgentsAndSelected();
            agentModal.hide();
        } catch (err) {
            console.log('[DEBUG] Save agent threw error:', err);
            showAgentModalError('Failed to save agent.');
        }
    });

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

    // Load initial agents and selected agent from backend
    // Load selected agent and agents, then render table
    async function loadAgentsAndSelected() {
        let settingsResp, agentsResp, settings;
        try {
            // Use correct endpoint for settings
            settingsResp = await fetch('/api/admin/agent/settings');
            if (settingsResp.ok) {
                settings = await settingsResp.json();
                selectedAgent = settings.global_selected_agent || null;
            } else {
                console.warn('Warning: Failed to load selected agent. Table will still load.');
                selectedAgent = null;
            }
        } catch (err) {
            console.warn('Warning: Error loading selected agent:', err);
            selectedAgent = null;
        }
        try {
            agentsResp = await fetch('/api/admin/agents');
            if (!agentsResp.ok) throw new Error('Failed to load agents');
            agents = await agentsResp.json();
            console.log('Loaded agents:', agents);
            console.log('Loaded selectedAgent:', selectedAgent);
            renderAgentsTable();
            // Only call renderOrchestrationForm if orchestrationTypes are loaded
            if (typeof renderOrchestrationForm === 'function' && orchestrationTypes.length > 0) {
                renderOrchestrationForm();
            }
            // Populate selected agent dropdown directly
            const dropdown = document.getElementById('default-agent-select');
            if (dropdown) {
                dropdown.innerHTML = '';
                agents.forEach(agent => {
                    const opt = document.createElement('option');
                    opt.value = agent.name;
                    opt.textContent = agent.display_name || agent.name;
                    if (selectedAgent && agent.name === selectedAgent.name) {
                        opt.selected = true;
                    }
                    dropdown.appendChild(opt);
                });
                attachSelectedAgentDropdownHandler();
            }
        } catch (err) {
            console.error('Error loading agents:', err);
            agents = [];
            renderAgentsTable();
        }
    }
    // Wait for DOMContentLoaded before loading agents
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadAgentsAndSelected);
    } else {
        loadAgentsAndSelected();
    }

    // --- Orchestration Settings Logic ---
    const maxRoundsGroup = document.getElementById('max_rounds_per_agent_group');
    const maxRoundsInput = document.getElementById('max_rounds_per_agent');
    const saveOrchBtn = document.getElementById('save-orchestration-settings-btn');
    const orchestrationTypeSelect = document.getElementById('orchestration_type');
    // Use the correct dropdown for selected agent
    const selectedAgentDropdown = document.getElementById('default-agent-select');

    let orchestrationTypes = [];
    let orchestrationSettings = {};

    // --- Orchestration Settings Logic ---
    async function loadOrchestrationSettings() {
        try {
            const [typesRes, settingsRes] = await Promise.all([
                fetch('/api/orchestration_types'),
                fetch('/api/orchestration_settings'),
            ]);
            if (!typesRes.ok) throw new Error('Failed to load orchestration types');
            if (!settingsRes.ok) throw new Error('Failed to load orchestration settings');
            orchestrationTypes = await typesRes.json();
            orchestrationSettings = await settingsRes.json();
            // Only call renderOrchestrationForm here
            renderOrchestrationForm();
        } catch (e) {
            if (typeof orchStatus !== 'undefined' && orchStatus) {
                orchStatus.textContent = 'Failed to load orchestration settings.';
                orchStatus.style.color = 'red';
            }
        }
    }

    function renderOrchestrationForm() {
        if (!orchestrationTypeSelect) {
            console.warn('orchestrationTypeSelect not found in DOM');
            return;
        }
        orchestrationTypeSelect.innerHTML = '';
        orchestrationTypes.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.value;
            opt.textContent = t.label;
            orchestrationTypeSelect.appendChild(opt);
        });
        // Set value only if present in settings
        if (orchestrationSettings.orchestration_type) {
            orchestrationTypeSelect.value = orchestrationSettings.orchestration_type;
        } else if (orchestrationTypes.length > 0) {
            orchestrationTypeSelect.value = orchestrationTypes[0].value;
        }
        maxRoundsInput.value = orchestrationSettings.max_rounds_per_agent || 1;
        toggleMaxRounds();

        // Populate selected agent dropdown if present
        const dropdown = document.getElementById('default-agent-select');
        if (dropdown) {
            dropdown.innerHTML = '';
            agents.forEach(agent => {
                const opt = document.createElement('option');
                opt.value = agent.name;
                opt.textContent = agent.display_name || agent.name;
                if (selectedAgent && agent.name === selectedAgent.name) {
                    opt.selected = true;
                }
                dropdown.appendChild(opt);
            });
            attachSelectedAgentDropdownHandler();
        } else {
            console.warn('selectedAgentDropdown element not found in DOM');
        }
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
    // --- Merge Global Agents/Plugins Toggle (Async Save) ---
    
    if (mergeGlobalToggle) {
        mergeGlobalToggle.addEventListener('change', async function() {
            const checked = mergeGlobalToggle.checked;
            mergeGlobalToggle.disabled = true;
            try {
                const resp = await fetch('/api/admin/agents/settings/merge_global_semantic_kernel_with_workspace', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ value: checked })
                });
                const data = await resp.json();
                if (resp.ok) {
                    showToast('Merge Global Agents/Plugins setting updated.', 'success');
                } else {
                    showToast(data.error || 'Failed to update setting.', 'danger');
                    mergeGlobalToggle.checked = !checked;
                }
            } catch (err) {
                showToast('Error updating setting: ' + err.message, 'danger');
                mergeGlobalToggle.checked = !checked;
            } finally {
                mergeGlobalToggle.disabled = false;
            }
        });
    }

    // Render agents table
    function renderAgentsTable() {
        agentsTableBody.innerHTML = '';
        if (!Array.isArray(agents) || agents.length === 0) {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td colspan="5" class="text-center">No agents found.</td>`;
            agentsTableBody.appendChild(tr);
            return;
        }
        agents.forEach((agent, idx) => {
            // Use global_selected_agent for badge logic
            const isSelected = selectedAgent && agent.name === selectedAgent.name;
            console.log('Table row:', agent.name, 'SelectedAgent:', selectedAgent ? selectedAgent.name : null, 'isSelected:', isSelected);
            const tr = document.createElement('tr');
            let selectedBadge = isSelected ? '<span class="badge bg-primary ms-1">Selected</span>' : '';
            tr.innerHTML = `
                <td>${agent.name}</td>
                <td>${agent.display_name}</td>
                <td>${agent.description || ''}</td>
                <td>${selectedBadge}</td>
                <td>
                    <button type="button" class="btn btn-sm btn-secondary edit-agent-btn" data-index="${idx}">Edit</button>
                    <button type="button" class="btn btn-sm btn-danger delete-agent-btn" data-index="${idx}" ${isSelected ? 'disabled' : ''}>Delete</button>
                </td>
            `;
            agentsTableBody.appendChild(tr);
        });
    }

    // Helper to (re)attach change handler to dropdown
    function attachSelectedAgentDropdownHandler() {
        const oldDropdown = document.getElementById('default-agent-select');
        if (oldDropdown) {
            // Clone the dropdown to remove all previous listeners
            const newDropdown = oldDropdown.cloneNode(true);
            oldDropdown.parentNode.replaceChild(newDropdown, oldDropdown);
            newDropdown.addEventListener('change', async function () {
                console.log('Selected agent dropdown changed:', newDropdown.value);
                const newSelectedName = newDropdown.value;
                if (!newSelectedName || (selectedAgent && newSelectedName === selectedAgent.name)) return;
                try {
                    const resp = await fetch('/api/admin/agents/selected_agent', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: newSelectedName })
                    });
                    if (!resp.ok) {
                        const data = await resp.json();
                        showToast(data.error || 'Failed to set selected agent.', 'danger');
                        return;
                    }
                    await loadAgentsAndSelected();
                    showToast('Selected agent updated!', 'success');
                } catch (err) {
                    showToast('Failed to set selected agent.', 'danger');
                }
            });
        }
    }
});
