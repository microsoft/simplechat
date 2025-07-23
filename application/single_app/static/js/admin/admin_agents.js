// admin_agents.js
// Handles CRUD operations and modal logic for Agents in the admin UI

import { showToast } from "../chat/chat-toast.js";
import * as agentsCommon from '../agents_common.js';

// --- Orchestration Settings Logic ---
const maxRoundsGroup = document.getElementById('max_rounds_per_agent_group');
const maxRoundsInput = document.getElementById('max_rounds_per_agent');
const saveOrchBtn = document.getElementById('save-orchestration-settings-btn');
const orchestrationTypeSelect = document.getElementById('orchestration_type');
const selectedAgentDropdown = document.getElementById('default-agent-select');
const agentModalSaveBtn = document.getElementById('agent-modal-save-btn');
const perUserSKToggle = document.getElementById('toggle-per-user-sk');
const agentsTableBody = document.getElementById('agents-table-body');
const mergeGlobalToggle = document.getElementById('toggle-merge-global-sk');
let orchestrationTypes = [];
let orchestrationSettings = {};
let agents = [];
let selectedAgent = null;

// --- Function Definitions ---

async function loadAllAdminAgentData() {
    try {
        const [typesRes, settingsRes, agentSettingsRes, agentsRes] = await Promise.all([
            fetch('/api/orchestration_types'),
            fetch('/api/orchestration_settings'),
            fetch('/api/admin/agent/settings'),
            fetch('/api/admin/agents'),
        ]);
        if (!typesRes.ok) throw new Error('Failed to load orchestration types');
        if (!settingsRes.ok) throw new Error('Failed to load orchestration settings');
        if (!agentSettingsRes.ok) throw new Error('Failed to load selected agent');
        if (!agentsRes.ok) throw new Error('Failed to load agents');
        orchestrationTypes = await typesRes.json();
        orchestrationSettings = await settingsRes.json();
        const agentSettings = await agentSettingsRes.json();
        let selectedAgentName = null;
        if (agentSettings.global_selected_agent) {
            if (typeof agentSettings.global_selected_agent === 'object') {
                selectedAgentName = agentSettings.global_selected_agent.name;
            } else {
                selectedAgentName = agentSettings.global_selected_agent;
            }
        }
        selectedAgent = selectedAgentName;
        agents = await agentsRes.json();
        renderOrchestrationForm();
        renderAgentsTable();
        renderAdminAgentDropdown(agents, selectedAgentName);
    } catch (err) {
        console.error('Error loading admin agent data:', err);
        orchestrationTypes = [];
        orchestrationSettings = {};
        agents = [];
        selectedAgent = null;
        renderOrchestrationForm();
        renderAgentsTable();
        renderAdminAgentDropdown([], null);
    }
}

function renderAdminAgentDropdown(agentsList, selectedAgentName) {
    const dropdown = document.getElementById('default-agent-select');
    if (!dropdown) return;
    dropdown.innerHTML = '';
    if (!agentsList.length) {
        dropdown.disabled = true;
        return;
    }
    agentsList.forEach(agent => {
        const opt = document.createElement('option');
        opt.value = agent.name;
        opt.textContent = agent.display_name || agent.name;
        if (agent.name === selectedAgentName) opt.selected = true;
        dropdown.appendChild(opt);
    });
    dropdown.disabled = false;
    // Attach change handler only once
    if (!dropdown._handlerAttached) {
        dropdown.addEventListener('change', async function () {
            const newSelectedName = dropdown.value;
            if (!newSelectedName) return;
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
                // Wait a moment to ensure backend update, then reload
                await new Promise(res => setTimeout(res, 150));
                await loadAllAdminAgentData();
                showToast('Selected agent updated!', 'success');
            } catch (err) {
                showToast('Failed to set selected agent.', 'danger');
            }
        });
        dropdown._handlerAttached = true;
    }
}

function ensureAdminAgentEventListeners() {
    // Add Agent button
    const addAgentBtn = document.getElementById('add-agent-btn');
    if (addAgentBtn) {
        addAgentBtn.removeEventListener('click', handleAddAgentClick);
        addAgentBtn.addEventListener('click', handleAddAgentClick);
    }
}

function handleAddAgentClick() {
    openAgentModal();
    window.editingAgentIndex = null;
    window.editingAgentName = null;
}

// DRY modal open logic for add/edit agent (unified with workspace)
async function openAgentModal(agent = null) {
    const modalEl = document.getElementById('agentModal');
    if (!modalEl) return alert('Agent modal not found.');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);

    // Clear error div on modal open
    const errorDiv = document.getElementById('agent-modal-error');
    if (errorDiv) {
        errorDiv.textContent = '';
        errorDiv.style.display = 'none';
    }

    // Populate modal fields using shared helper
    agentsCommon.setAgentModalFields(agent || {}, { context: 'admin' });

    // Setup plugin select
    const pluginSelect = document.getElementById('agent-plugins-to-load');
    let availablePlugins = [];
    try {
        const resp = await fetch('/api/admin/plugins');
        if (resp.ok) {
            availablePlugins = await resp.json();
        }
    } catch (e) {
        availablePlugins = [];
    }
    agentsCommon.populatePluginMultiSelect(pluginSelect, availablePlugins);
    agentsCommon.setSelectedPlugins(pluginSelect, agent?.plugins_to_load || []);

    // Setup toggles using shared helpers
    agentsCommon.setupApimToggle(
        document.getElementById('agent-enable-apim'),
        document.getElementById('agent-apim-fields'),
        document.getElementById('agent-gpt-fields'),
        () => agentsCommon.loadGlobalModelsForModal({
            endpoint: '/api/admin/agent/settings',
            agent,
            globalModelSelect: document.getElementById('agent-global-model-select'),
            isGlobal: true,
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
            endpoint: '/api/admin/agent/settings',
            agent,
            globalModelSelect: document.getElementById('agent-global-model-select'),
            isGlobal: true,
            customConnectionCheck: agentsCommon.shouldEnableCustomConnection,
            deploymentFieldIds: { gpt: 'agent-gpt-deployment', apim: 'agent-apim-deployment' }
        })
    );
    agentsCommon.attachAdvancedToggleHandler(advancedToggle, modalElements);
    modal.show();
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

    // Remove dropdown population from here; handled by renderAdminAgentDropdown after all data loads
}

function toggleMaxRounds() {
    if (!orchestrationTypeSelect) return;
    if (orchestrationTypeSelect.value === 'group_chat') {
        maxRoundsGroup.style.display = '';
    } else {
        maxRoundsGroup.style.display = 'none';
    }
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
        // Use global_selected_agent for badge logic (compare by name)
        const isSelected = selectedAgent && agent.name === selectedAgent;
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
    // Attach event listeners for edit and delete buttons (event delegation)
    agentsTableBody.removeEventListener('click', handleAgentTableClick);
    agentsTableBody.addEventListener('click', handleAgentTableClick);
}

function handleAgentTableClick(e) {
    if (e.target.classList.contains('edit-agent-btn')) {
        const idx = parseInt(e.target.getAttribute('data-index'), 10);
        if (!isNaN(idx) && Array.isArray(agents)) {
            openAgentModal(agents[idx]);
            window.editingAgentIndex = idx;
            window.editingAgentName = agents[idx].name;
        }
    } else if (e.target.classList.contains('delete-agent-btn')) {
        const idx = parseInt(e.target.getAttribute('data-index'), 10);
        if (!isNaN(idx) && Array.isArray(agents)) {
            // Confirm delete
            if (confirm(`Are you sure you want to delete agent '${agents[idx].name}'?`)) {
                deleteAgent(idx);
            }
        } else {
            availablePlugins = [];
        }
        agentsCommon.populatePluginMultiSelect(pluginSelect, availablePlugins);
        if (agent && Array.isArray(agent.plugins_to_load)) {
            agentsCommon.setSelectedPlugins(pluginSelect, agent.plugins_to_load);
        } else {
            agentsCommon.setSelectedPlugins(pluginSelect, []);
        }

        // --- Shared Modal Logic ---
        const customConnectionToggle = document.getElementById('agent-custom-connection');
        const customConnectionFields = document.getElementById('agent-custom-connection-fields');
        const globalModelGroup = document.getElementById('agent-global-model-group');
        const globalModelSelect = document.getElementById('agent-global-model-select');
        const advancedToggle = document.getElementById('agent-advanced-toggle');
        const advancedSection = document.getElementById('agent-advanced-section');
        const modalElements = {
            customFields: customConnectionFields,
            globalModelGroup: globalModelGroup,
            advancedSection: advancedSection
        };
        // Custom Connection Toggle
        let customEnabled = shouldEnableCustomConnection(agent);
        customConnectionToggle.checked = customEnabled;
        toggleCustomConnectionUI(customEnabled, modalElements);
        customConnectionToggle.onchange = function () {
            toggleCustomConnectionUI(this.checked, modalElements);
            if (!this.checked) {
                loadGlobalModels();
            }
        };
        // Advanced Toggle
        let expandAdvanced = shouldExpandAdvanced(agent);
        advancedToggle.checked = expandAdvanced;
        toggleAdvancedUI(expandAdvanced, modalElements);
        advancedToggle.onchange = function () {
            toggleAdvancedUI(this.checked, modalElements);
        };
        // Global Model Dropdown
        async function loadGlobalModels() {
            const endpoint = '/api/admin/agent/settings';
            const { models, selectedModel, apimEnabled } = await fetchAndGetAvailableModels(endpoint, agent);
            populateGlobalModelDropdown(globalModelSelect, models, selectedModel);
            globalModelSelect.onchange = function () {
                const selected = models.find(m => m.deployment === this.value || m.name === this.value || m.id === this.value);
                if (selected) {
                    if (apimEnabled) {
                        document.getElementById('agent-apim-deployment').value = selected.deployment || '';
                        document.getElementById('agent-gpt-endpoint').value = '';
                        document.getElementById('agent-gpt-key').value = '';
                        document.getElementById('agent-gpt-deployment').value = '';
                        document.getElementById('agent-gpt-api-version').value = '';
                    } else {
                        document.getElementById('agent-gpt-endpoint').value = selected.endpoint || '';
                        document.getElementById('agent-gpt-key').value = selected.key || '';
                        document.getElementById('agent-gpt-deployment').value = selected.deployment || selected.name || '';
                        document.getElementById('agent-gpt-api-version').value = selected.api_version || '';
                        document.getElementById('agent-apim-deployment').value = '';
                    }
                }
            };
        }
        // Initial model load if not using custom connection
        if (!customEnabled) {
            loadGlobalModels();
        }
    }
}

async function deleteAgent(idx) {
    const agent = agents[idx];
    try {
        const resp = await fetch(`/api/admin/agents/${encodeURIComponent(agent.name)}`, {
            method: 'DELETE',
        });
        if (!resp.ok) {
            const data = await resp.json();
            showToast(data.error || 'Failed to delete agent.', 'danger');
            return;
        }
        showToast('Agent deleted!', 'success');
        await loadAllAdminAgentData();
    } catch (err) {
        showToast('Failed to delete agent.', 'danger');
    }
}

// Helper to (re)attach change handler to dropdown
function attachSelectedAgentDropdownHandler() {
    const oldDropdown = document.getElementById('default-agent-select');
    if (oldDropdown) {
        // Clone the dropdown to remove all previous listeners
        const newDropdown = oldDropdown.cloneNode(true);
        oldDropdown.parentNode.replaceChild(newDropdown, oldDropdown);
        newDropdown.addEventListener('change', async function () {
            const newSelectedName = newDropdown.value;
            if (!newSelectedName || (selectedAgent && newSelectedName === selectedAgent)) return;
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
                // Wait a moment to ensure backend update, then reload
                await new Promise(res => setTimeout(res, 150));
                await loadAllAdminAgentData();
                showToast('Selected agent updated!', 'success');
            } catch (err) {
                showToast('Failed to set selected agent.', 'danger');
            }
        });
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

// --- Execution Section: Only minimal wiring at the bottom ---
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        loadAllAdminAgentData();
        ensureAdminAgentEventListeners();
    });
} else {
    loadAllAdminAgentData();
    ensureAdminAgentEventListeners();
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

// Save Agent (Add/Edit)
if (agentModalSaveBtn) {
    agentModalSaveBtn.addEventListener('click', async function () {
        console.log('[DEBUG] Save Agent button clicked');
        let agentData;
        try {
            agentData = agentsCommon.getAgentModalFields({ context: 'admin' });
            // Only preserve id if editing; do not generate or strip id on create
            if (typeof editingAgentIndex !== 'undefined' && editingAgentIndex !== null && agents[editingAgentIndex] && agents[editingAgentIndex].id) {
                agentData.id = agents[editingAgentIndex].id;
            }
            // If id is still not present, fetch a GUID from backend
            if (!('id' in agentData) || !agentData.id) {
                try {
                    const guidResp = await fetch('/api/agents/generate_id');
                    if (guidResp.ok) {
                        const guidData = await guidResp.json();
                        agentData.id = guidData.id;
                    } else {
                        agentData.id = '';
                    }
                } catch (guidErr) {
                    agentData.id = '';
                }
            }
            agentData.is_global = true;
        } catch (e) {
            const msg = 'Additional Settings: ' + e.message;
            showAgentModalError(msg);
            showToast(msg, 'danger');
            return;
        }
        try {
            if (!window.validateAgent) {
                window.validateAgent = (await import('/static/js/validateAgent.mjs')).default;
            }
            console.log('[DEBUG] Agent object before validation:', agentData);
            const valid = window.validateAgent(agentData);
            console.log('[DEBUG] Validation result:', valid);
            if (window.validateAgent.errors) {
                console.log('[DEBUG] Ajv validation errors:', window.validateAgent.errors);
            }
            if (!valid) {
                const msg = 'Validation error: Invalid agent data.';
                showAgentModalError(msg);
                showToast(msg, 'danger');
                return;
            }
        } catch (e) {
            const msg = 'Schema validation failed: ' + e.message;
            console.log('[DEBUG] Validation threw error:', e);
            showAgentModalError(msg);
            showToast(msg, 'danger');
            return;
        }
        try {
            let resp, data;
            if (typeof editingAgentIndex === 'undefined' || editingAgentIndex === null) {
                console.log('[DEBUG] About to POST new agent');
                resp = await fetch('/api/admin/agents', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(agentData)
                });
                data = await resp.json();
                console.log('[DEBUG] POST response:', resp.status, data);
                if (!resp.ok) {
                    const msg = data.error || 'Failed to add agent.';
                    showAgentModalError(msg);
                    showToast(msg, 'danger');
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
                    const msg = data.error || 'Failed to update agent.';
                    showAgentModalError(msg);
                    showToast(msg, 'danger');
                    return;
                }
                agents[editingAgentIndex] = agentData;
            }
            const agentModal = bootstrap.Modal.getInstance(document.getElementById('agentModal'));
            if (agentModal) agentModal.hide();
            try {
                await loadAllAdminAgentData();
            } catch (loadErr) {
                const msg = 'Agent saved, but failed to reload agents: ' + (loadErr.message || loadErr);
                console.error('[ERROR] ' + msg, loadErr);
                showAgentModalError(msg);
                showToast(msg, 'danger');
                return;
            }
        } catch (e) {
            const msg = 'Failed to save agent: ' + (e && e.message ? e.message : e);
            console.error('[ERROR] Save agent exception:', e);
            showAgentModalError(msg);
            showToast(msg, 'danger');
        }
    });
}

// --- Explicit: Per-User Semantic Kernel Toggle (Async Save) ---
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

loadOrchestrationSettings();