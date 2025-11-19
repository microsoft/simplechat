/**
 * Attaches a shared onchange handler to the custom connection toggle.
 * @param {HTMLInputElement} toggleEl - The custom connection toggle element
 * @param {Object} agent - The agent object (may be null)
 * @param {Object} modalElements - { customFields, globalModelGroup, advancedSection }
 * @param {Function} loadGlobalModelsCb - Callback to load global models (optional)
 */
export function attachCustomConnectionToggleHandler(toggleEl, agent, modalElements, loadGlobalModelsCb) {
	if (!toggleEl) return;
	toggleEl.onchange = function () {
		toggleCustomConnectionUI(this.checked, modalElements);
		if (!this.checked && typeof loadGlobalModelsCb === 'function') {
			loadGlobalModelsCb();
		}
	};
}

/**
 * Attaches a shared onchange handler to the advanced toggle.
 * @param {HTMLInputElement} toggleEl - The advanced toggle element
 * @param {Object} modalElements - { advancedSection }
 */
export function attachAdvancedToggleHandler(toggleEl, modalElements) {
	if (!toggleEl) return;
	toggleEl.onchange = function () {
		toggleAdvancedUI(this.checked, modalElements);
	};
}
/**
 * Populates agent modal fields from an agent object.
 * @param {Object} agent - The agent object (may be empty for new)
 * @param {Object} opts - { modalRoot: HTMLElement (optional, defaults to document), context: 'user'|'admin'|'group' }
 */
export function setAgentModalFields(agent, opts = {}) {
	const root = opts.modalRoot || document;
	root.getElementById('agent-name').value = agent.name || '';
	root.getElementById('agent-display-name').value = agent.display_name || '';
	root.getElementById('agent-description').value = agent.description || '';
	root.getElementById('agent-gpt-endpoint').value = agent.azure_openai_gpt_endpoint || '';
	root.getElementById('agent-gpt-key').value = agent.azure_openai_gpt_key || '';
	root.getElementById('agent-gpt-deployment').value = agent.azure_openai_gpt_deployment || '';
	root.getElementById('agent-gpt-api-version').value = agent.azure_openai_gpt_api_version || '';
	root.getElementById('agent-apim-endpoint').value = agent.azure_agent_apim_gpt_endpoint || '';
	root.getElementById('agent-apim-subscription-key').value = agent.azure_agent_apim_gpt_subscription_key || '';
	root.getElementById('agent-apim-deployment').value = agent.azure_agent_apim_gpt_deployment || '';
	root.getElementById('agent-apim-api-version').value = agent.azure_agent_apim_gpt_api_version || '';
	root.getElementById('agent-enable-apim').checked = !!agent.enable_agent_gpt_apim;
	root.getElementById('agent-instructions').value = agent.instructions || '';
	root.getElementById('agent-additional-settings').value = agent.other_settings ? JSON.stringify(agent.other_settings, null, 2) : '{}';
	root.getElementById('agent-max-completion-tokens').value = agent.max_completion_tokens || '';
	// Actions handled separately
}

/**
 * Extracts agent data from modal fields and returns an agent object.
 * @param {Object} opts - { modalRoot: HTMLElement (optional, defaults to document), context: 'user'|'admin'|'group' }
 * @returns {Object} agent object
 */
export function getAgentModalFields(opts = {}) {
	const root = opts.modalRoot || document;
	let additionalSettings = {};
	try {
		const settingsRaw = root.getElementById('agent-additional-settings').value.trim();
		if (settingsRaw) additionalSettings = JSON.parse(settingsRaw);
	} catch (e) {
		showToast('error', 'Additional Settings must be a valid JSON object.');
		throw e;
	}
	// Actions handled here - support both old multiselect and new stepper action cards
	const actionsSelect = root.getElementById('agent-plugins-to-load');
	let actions_to_load = [];
	
	if (actionsSelect) {
		// Old system - multiselect
		actions_to_load = Array.from(actionsSelect.selectedOptions).map(opt => opt.value).filter(Boolean);
	} else {
		// New system - stepper action cards
		const selectedActionCards = root.querySelectorAll('.action-card.border-primary');
		actions_to_load = Array.from(selectedActionCards).map(card => {
			// Try ID first, then fall back to name
			return card.getAttribute('data-action-id') || card.getAttribute('data-action-name');
		}).filter(Boolean);
	}

	return {
		name: root.getElementById('agent-name').value.trim(),
		display_name: root.getElementById('agent-display-name').value.trim(),
		description: root.getElementById('agent-description').value.trim(),
		azure_openai_gpt_endpoint: root.getElementById('agent-gpt-endpoint').value.trim(),
		azure_openai_gpt_key: root.getElementById('agent-gpt-key').value.trim(),
		azure_openai_gpt_deployment: root.getElementById('agent-gpt-deployment').value.trim(),
		azure_openai_gpt_api_version: root.getElementById('agent-gpt-api-version').value.trim(),
		azure_agent_apim_gpt_endpoint: root.getElementById('agent-apim-endpoint').value.trim(),
		azure_agent_apim_gpt_subscription_key: root.getElementById('agent-apim-subscription-key').value.trim(),
		azure_agent_apim_gpt_deployment: root.getElementById('agent-apim-deployment').value.trim(),
		azure_agent_apim_gpt_api_version: root.getElementById('agent-apim-api-version').value.trim(),
		enable_agent_gpt_apim: root.getElementById('agent-enable-apim').checked,
		instructions: root.getElementById('agent-instructions').value.trim(),
		max_completion_tokens: parseInt(root.getElementById('agent-max-completion-tokens').value.trim()) || null,
		actions_to_load: actions_to_load,
		other_settings: additionalSettings,
		agent_type: (opts.agent && opts.agent.agent_type) || 'local'
	};
}
/**
 * Loads available models for the agent modal, populates the dropdown, and pre-fills deployment if not set.
 * @param {Object} opts
 *   - endpoint: API endpoint to fetch settings (e.g. '/api/admin/agent/settings' or '/api/user/agent/settings')
 *   - agent: The agent object (may be empty for new)
 *   - globalModelSelect: The <select> element for models
 *   - isGlobal: Boolean, true for admin/global context, false for workspace/user
 *   - customConnectionCheck: Function(agent) => boolean, to check if custom connection is enabled
 *   - deploymentFieldIds: { gpt: string, apim: string } - DOM IDs for deployment fields
 */
export async function loadGlobalModelsForModal({
	endpoint,
	agent,
	globalModelSelect,
	isGlobal,
	customConnectionCheck,
	deploymentFieldIds
}) {
	const { models, selectedModel, apimEnabled } = await fetchAndGetAvailableModels(endpoint, agent);
	populateGlobalModelDropdown(globalModelSelect, models, selectedModel);

	// Pre-fill deployment if not set and not using custom connection
	if (!customConnectionCheck(agent)) {
		if (apimEnabled) {
			const apimDeploymentInput = document.getElementById(deploymentFieldIds.apim);
			if (apimDeploymentInput && !apimDeploymentInput.value && models.length > 0 && models[0].deployment) {
				apimDeploymentInput.value = models[0].deployment;
			}
		} else {
			const gptDeploymentInput = document.getElementById(deploymentFieldIds.gpt);
			if (
				gptDeploymentInput &&
				!gptDeploymentInput.value &&
				models.length > 0 &&
				(models[0].deployment || models[0].name)
			) {
				gptDeploymentInput.value = models[0].deployment || models[0].name;
			}
		}
	}

	globalModelSelect.onchange = function () {
		const selected = models.find(
			m => m.deployment === this.value || m.name === this.value || m.id === this.value
		);
		if (selected) {
			// Check if custom connection is enabled for this agent
			const isCustomConnection = customConnectionCheck(agent);
			
			if (isCustomConnection) {
				// Only populate custom fields if custom connection is actually enabled
				if ((isGlobal && apimEnabled) || (!isGlobal && agent && agent.enable_agent_gpt_apim)) {
					const apimDeploymentInput = document.getElementById(deploymentFieldIds.apim);
					if (apimDeploymentInput) apimDeploymentInput.value = selected.deployment || '';
					// Clear GPT fields when using APIM
					['agent-gpt-endpoint', 'agent-gpt-key', 'agent-gpt-deployment', 'agent-gpt-api-version'].forEach(id => {
						const el = document.getElementById(id);
						if (el) el.value = '';
					});
				} else {
					// Populate GPT fields with proper values from the selected model
					const deploymentEl = document.getElementById('agent-gpt-deployment');
					const apiVersionEl = document.getElementById('agent-gpt-api-version');
					const endpointEl = document.getElementById('agent-gpt-endpoint');
					const keyEl = document.getElementById('agent-gpt-key');
					
					if (deploymentEl) deploymentEl.value = selected.deployment || selected.name || '';
					if (apiVersionEl) apiVersionEl.value = selected.api_version || ''; // Use proper API version, not model name
					if (endpointEl) endpointEl.value = selected.endpoint || '';
					if (keyEl) keyEl.value = selected.key || '';
					
					// Clear APIM field
					const apimDeploymentInput = document.getElementById(deploymentFieldIds.apim);
					if (apimDeploymentInput) apimDeploymentInput.value = '';
				}
			} else {
				// Custom connection is OFF - using global connection settings
				// Only populate the deployment field, agent will use global endpoint/key
				const deploymentEl = document.getElementById('agent-gpt-deployment');
				if (deploymentEl) deploymentEl.value = selected.deployment || selected.name || '';
				
				// Do NOT populate custom connection fields when using global settings
				// Clear them to ensure they don't interfere with shouldEnableCustomConnection logic
				const apiVersionEl = document.getElementById('agent-gpt-api-version');
				const endpointEl = document.getElementById('agent-gpt-endpoint');
				const keyEl = document.getElementById('agent-gpt-key');
				
				if (apiVersionEl) apiVersionEl.value = '';
				if (endpointEl) endpointEl.value = '';
				if (keyEl) keyEl.value = '';
			}
		}
	};
}
/**
 * Shared logic to show/hide APIM and GPT fields based on APIM toggle state.
 * @param {HTMLInputElement} apimToggle - The APIM toggle checkbox element
 * @param {HTMLElement} apimFields - The APIM fields container
 * @param {HTMLElement} gptFields - The GPT fields container
 */
export function setupApimToggle(apimToggle, apimFields, gptFields, onToggle) {
	if (!apimToggle || !apimFields || !gptFields) return;
	function updateApimFieldsVisibility() {
		console.log('[DEBUG] updateApimFieldsVisibility fired. apimToggle.checked:', apimToggle.checked);
		if (apimToggle.checked) {
			apimFields.style.display = 'block';
			gptFields.style.display = 'none';
			apimFields.classList.remove('d-none');
			gptFields.classList.add('d-none');
			console.log('[DEBUG] Showing APIM fields, hiding GPT fields.');
		} else {
			apimFields.style.display = 'none';
			gptFields.style.display = 'block';
			gptFields.classList.remove('d-none');
			apimFields.classList.add('d-none');
			console.log('[DEBUG] Hiding APIM fields, showing GPT fields.');
		}
		if (typeof onToggle === 'function') {
			onToggle();
		}
	}
	apimToggle.onchange = updateApimFieldsVisibility;
	updateApimFieldsVisibility();
}
/**
 * Populate a multi-select element with available plugins
 * @param {HTMLElement} selectEl - The select element
 * @param {Array} plugins - Array of plugin objects (must have .name)
 */
export function populatePluginMultiSelect(selectEl, plugins) {
	if (!selectEl) return;
	selectEl.innerHTML = '';
	if (!plugins || !plugins.length) {
		let opt = document.createElement('option');
		opt.value = '';
		opt.textContent = 'No plugins available';
		selectEl.appendChild(opt);
		selectEl.disabled = true;
		return;
	}
	plugins.forEach(plugin => {
		let opt = document.createElement('option');
		opt.value = plugin.name;
		opt.textContent = plugin.display_name || plugin.name;
		selectEl.appendChild(opt);
	});
	selectEl.disabled = false;
}

/**
 * Get selected plugin names from a multi-select
 * @param {HTMLElement} selectEl
 * @returns {Array<string>} Array of selected plugin names
 */
export function getSelectedPlugins(selectEl) {
	if (!selectEl) return [];
	return Array.from(selectEl.selectedOptions).map(opt => opt.value).filter(Boolean);
}

/**
 * Pre-select plugins in a multi-select
 * @param {HTMLElement} selectEl
 * @param {Array<string>} pluginNames
 */
export function setSelectedPlugins(selectEl, pluginNames) {
	if (!selectEl || !Array.isArray(pluginNames)) return;
	Array.from(selectEl.options).forEach(opt => {
		opt.selected = pluginNames.includes(opt.value);
	});
}
/**
 * Set a user setting (e.g., enable_agents)
 * @param {string} key - Setting key
 * @param {any} value - Setting value
 * @returns {Promise<boolean>} Success
 */
export async function setUserSetting(key, value) {
	const resp = await fetch('/api/user/settings', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ settings: { [key]: value } })
	});
	return resp.ok;
}

/**
 * Get a user setting (e.g., enable_agents)
 * @param {string} key - Setting key
 * @returns {Promise<any>} Setting value or null
 */
export async function getUserSetting(key) {
	const resp = await fetch('/api/user/settings');
	if (!resp.ok) return null;
	const data = await resp.json();
	return data.settings ? data.settings[key] : null;
}
// agents_common.js
// Reusable agent logic for chat, workspace, and group modules
/**
 * Returns true if actions_to_load or other_settings are non-empty (not [], {}, null, or undefined)
 * @param {Object} agent
 */
export function shouldExpandAdvanced(agent) {
	if (!agent) return false;
	let actions = agent.actions_to_load;
	let settings = agent.other_settings;
	let hasActions = false;
	let hasSettings = false;
	// Check actions_to_load
	if (Array.isArray(actions)) {
		hasActions = actions.length > 0;
	} else if (typeof actions === 'string') {
		try {
			const arr = JSON.parse(actions);
			hasActions = Array.isArray(arr) && arr.length > 0;
		} catch { hasActions = !!actions.trim(); }
	} else if (actions && actions !== null && actions !== undefined) {
		hasActions = true;
	}
	// Check other_settings
	if (settings && typeof settings === 'object' && !Array.isArray(settings)) {
		hasSettings = Object.keys(settings).length > 0;
	} else if (typeof settings === 'string') {
		try {
			const obj = JSON.parse(settings);
			hasSettings = obj && typeof obj === 'object' && Object.keys(obj).length > 0;
		} catch { hasSettings = !!settings.trim(); }
	} else if (settings && settings !== null && settings !== undefined) {
		hasSettings = true;
	}
	return hasActions || hasSettings;
}

/**
 * Returns true if any custom connection fields are set (non-empty or true)
 * @param {Object} agent
 * @returns {boolean}
 */
export function shouldEnableCustomConnection(agent) {
	if (!agent) return false;
	return Boolean(
		(agent.azure_openai_gpt_endpoint && agent.azure_openai_gpt_endpoint.trim()) ||
		(agent.azure_openai_gpt_key && agent.azure_openai_gpt_key.trim()) ||
		(agent.azure_openai_gpt_api_version && agent.azure_openai_gpt_api_version.trim()) ||
		(agent.azure_agent_apim_gpt_endpoint && agent.azure_agent_apim_gpt_endpoint.trim()) ||
		(agent.azure_agent_apim_gpt_subscription_key && agent.azure_agent_apim_gpt_subscription_key.trim()) ||
		(agent.azure_agent_apim_gpt_api_version && agent.azure_agent_apim_gpt_api_version.trim()) ||
		agent.enable_agent_gpt_apim
	);
}
/**
 * Returns available models and selected model for dropdown, based on APIM toggle and settings
 * @param {Object} opts - { apimEnabled, settings, agent }
 * @returns {Object} { models, selectedModel }
 */
export function getAvailableModels({ apimEnabled, settings, agent }) {
	let models = [];
	let selectedModel = null;
	if (apimEnabled) {
		// azure_apim_gpt_deployment is a string, could be comma separated
		let apimDeployments = (settings && settings.azure_apim_gpt_deployment) || '';
		models = apimDeployments.split(',').map(s => ({ deployment: s.trim(), display_name: s.trim() })).filter(m => m.deployment);
		selectedModel = agent && agent.azure_agent_apim_gpt_deployment ? agent.azure_agent_apim_gpt_deployment : null;
	} else {
		// Otherwise use gpt_model.selected (array)
		let rawModels = (settings && settings.gpt_model && settings.gpt_model.selected) ? settings.gpt_model.selected : [];
		console.log('[DEBUG] Raw models:', rawModels);
		// Normalize: map deploymentName/modelName to deployment/name if present
		models = rawModels.map(m => {
			if (m.deploymentName || m.modelName) {
				return {
					...m,
					deployment: m.deploymentName,
					name: m.modelName
				};
			}
			return m;
		});
		selectedModel = agent && agent.azure_openai_gpt_deployment ? agent.azure_openai_gpt_deployment : null;
		console.log('[DEBUG] Available models:', selectedModel);
	}
	return { models, selectedModel };
}
/**
 * Fetches settings from endpoint and returns available models, selected model, and apimEnabled
 * @param {string} endpoint - API endpoint to fetch settings
 * @param {Object} agent - Current agent object
 * @returns {Promise<{models: Array, selectedModel: string, apimEnabled: boolean}>}
 */
export async function fetchAndGetAvailableModels(endpoint, agent) {
	try {
		const resp = await fetch(endpoint);
		if (!resp.ok) throw new Error('Failed to fetch global models');
		const settings = await resp.json();
		// Check APIM enabled (support both enable_gpt_apim and enable_apim)
		const apimEnabled = settings.enable_gpt_apim || false;
		const { models, selectedModel } = getAvailableModels({ apimEnabled, settings, agent });
		return { models, selectedModel, apimEnabled };
	} catch (e) {
		return { models: [], selectedModel: null, apimEnabled: false };
	}
}

/**
 * Shows/hides custom connection fields and global model dropdown
 * @param {boolean} isEnabled
 * @param {Object} modalElements - { customFields, globalModelGroup }
 */
export function toggleCustomConnectionUI(isEnabled, modalElements) {
	if (!modalElements) return;
	if (modalElements.customFields) {
		modalElements.customFields.style.display = isEnabled ? '' : 'none';
		isEnabled ? modalElements.customFields.classList.remove('d-none') : modalElements.customFields.classList.add('d-none');
	}
	if (modalElements.globalModelGroup) {
		modalElements.globalModelGroup.style.display = isEnabled ? 'none' : '';
		isEnabled ? modalElements.globalModelGroup.classList.add('d-none') : modalElements.globalModelGroup.classList.remove('d-none');
	}
}

/**
 * Shows/hides advanced section
 * @param {boolean} isEnabled
 * @param {Object} modalElements - { advancedSection }
 */
export function toggleAdvancedUI(isEnabled, modalElements) {
	if (!modalElements) return;
	if (modalElements.advancedSection) {
		modalElements.advancedSection.style.display = isEnabled ? '' : 'none';
		isEnabled ? modalElements.advancedSection.classList.remove('d-none') : modalElements.advancedSection.classList.add('d-none');
	}
}

/**
 * Populates the global model dropdown
 * @param {HTMLElement} selectEl
 * @param {Array} models
 * @param {string} selectedModel
 */
export function populateGlobalModelDropdown(selectEl, models, selectedModel) {
	if (!selectEl) return;
	selectEl.innerHTML = '';
	if (!models || !models.length) {
		let opt = document.createElement('option');
		opt.value = '';
		opt.textContent = 'No models available';
		selectEl.appendChild(opt);
		selectEl.disabled = true;
		return;
	}
	models.forEach(model => {
		let opt = document.createElement('option');
		opt.value = model.name || model.deployment || model.id || '';
		opt.textContent = model.display_name || model.name || model.deployment || model.id || '';
		if (selectedModel && (model.name === selectedModel || model.deployment === selectedModel || model.id === selectedModel)) {
			opt.selected = true;
		}
		selectEl.appendChild(opt);
	});
	selectEl.disabled = false;
}

/**
 * Fetch user agents from backend
 * @returns {Promise<Array>} Array of agent objects
 */
export async function fetchUserAgents() {
	const res = await fetch('/api/user/agents');
	if (!res.ok) throw new Error('Failed to fetch user agents');
	return await res.json();
}

export async function fetchGroupAgentsForActiveGroup() {
	if (typeof window === 'undefined' || !window.activeGroupId) {
		return [];
	}
	try {
		const res = await fetch('/api/group/agents');
		if (!res.ok) {
			console.warn('Group agents request failed:', res.status, res.statusText);
			return [];
		}
		const payload = await res.json().catch(() => ({ agents: [] }));
		const agents = Array.isArray(payload.agents) ? payload.agents : [];
		const activeGroupName = (typeof window !== 'undefined' && window.activeGroupName) ? window.activeGroupName : '';
		return agents.map(agent => ({
			...agent,
			is_group: true,
			group_id: agent.group_id || window.activeGroupId,
			group_name: agent.group_name || activeGroupName || null
		}));
	} catch (error) {
		console.error('Failed to fetch group agents:', error);
		return [];
	}
}

/**
 * Fetch selected agent from user settings
 * @returns {Promise<Object|null>} Selected agent object or null
 */
export async function fetchSelectedAgent() {
	const res = await fetch('/api/user/settings');
	if (!res.ok) throw new Error('Failed to fetch user settings');
	const settings = await res.json();
	let selectedAgent = settings.selected_agent;
	if (!selectedAgent && settings.settings && settings.settings.selected_agent) {
		selectedAgent = settings.settings.selected_agent;
	}
	return selectedAgent || null;
}

/**
 * Populate a <select> element with agent options
 * @param {HTMLElement} selectEl - The select element to populate
 * @param {Array} agents - Array of agent objects
 * @param {Object|string} selectedAgentObj - Selected agent (object or name)
 */
export function populateAgentSelect(selectEl, agents, selectedAgentObj) {
	if (!selectEl) return;
	selectEl.innerHTML = '';
	if (!agents || !agents.length) {
		selectEl.disabled = true;
		return;
	}
	
	console.log('DEBUG: populateAgentSelect called with agents:', agents);
	console.log('DEBUG: Number of agents:', agents.length);
	agents.forEach((agent, index) => {
		console.log(`DEBUG: Agent ${index}: name="${agent.name}", is_global=${agent.is_global}, is_group=${agent.is_group}, display_name="${agent.display_name}"`);
	});
	
	const getDisplayLabel = (agent) => (agent.display_name || agent.displayName || agent.name || '').trim();
	const displayLabelCounts = agents.reduce((acc, agent) => {
		const label = getDisplayLabel(agent).toLowerCase();
		if (!label) {
			return acc;
		}
		acc[label] = (acc[label] || 0) + 1;
		return acc;
	}, {});

	let selectedAgentName = typeof selectedAgentObj === 'object' ? selectedAgentObj.name : selectedAgentObj;
	const selectedAgentId = typeof selectedAgentObj === 'object' ? (selectedAgentObj.id || selectedAgentObj.agent_id) : null;
	const selectedAgentIsGlobal = typeof selectedAgentObj === 'object' ? !!selectedAgentObj.is_global : false;
	const selectedAgentIsGroup = typeof selectedAgentObj === 'object' ? !!selectedAgentObj.is_group : false;
	const selectedAgentGroupId = typeof selectedAgentObj === 'object' ? (selectedAgentObj.group_id || selectedAgentObj.groupId || null) : null;
	console.log('DEBUG: Selected agent name:', selectedAgentName);
	
	agents.forEach(agent => {
		let opt = document.createElement('option');
		const agentId = agent.id || agent.agent_id || agent.name;
		const contextPrefix = agent.is_group ? 'group' : (agent.is_global ? 'global' : 'personal');
		opt.value = `${contextPrefix}_${agentId}`;
		const groupName = agent.group_name || agent.groupName || '';
		const displayLabel = getDisplayLabel(agent);
		const labelKey = displayLabel.toLowerCase();
		const hasDuplicateLabel = labelKey && displayLabelCounts[labelKey] > 1;
		let labelSuffix = '';
		if (agent.is_group) {
			if (hasDuplicateLabel) {
				labelSuffix = ` (Group${groupName ? `: ${groupName}` : ''})`;
			}
		} else if (agent.is_global) {
			labelSuffix = ' (Global)';
		}
		opt.textContent = `${displayLabel}${labelSuffix}`;
		opt.dataset.name = agent.name || '';
		opt.dataset.displayName = displayLabel;
		opt.dataset.agentId = agentId || '';
		opt.dataset.isGlobal = agent.is_global ? 'true' : 'false';
		opt.dataset.isGroup = agent.is_group ? 'true' : 'false';
		opt.dataset.groupId = agent.group_id || agent.groupId || '';
		opt.dataset.groupName = groupName || '';
		// For selection matching, prefer ID if available, otherwise fallback to name/context
		if (selectedAgentObj && typeof selectedAgentObj === 'object') {
			const candidateIds = [agentId, agent.id, agent.agent_id].filter(Boolean).map(String);
			const selectedIds = [selectedAgentId].filter(Boolean).map(String);
			const idMatches = selectedIds.length > 0 && selectedIds.some(selId => candidateIds.includes(selId));
			const nameMatches = agent.name === selectedAgentObj.name;
			const contextMatches = (!!agent.is_global === selectedAgentIsGlobal) && (!!agent.is_group === selectedAgentIsGroup);
			const groupMatches = !selectedAgentIsGroup || selectedAgentGroupId === null || String(agent.group_id || agent.groupId || '') === String(selectedAgentGroupId || '');
			if ((idMatches || nameMatches) && contextMatches && groupMatches) {
				opt.selected = true;
			}
		} else if (agent.name === selectedAgentName && !agent.is_global && !agent.is_group) {
			// Default to personal agent if just name is provided
			opt.selected = true;
		}
		selectEl.appendChild(opt);
		console.log(`DEBUG: Added option: value="${opt.value}", text="${opt.textContent}", selected=${opt.selected}`);
	});
	selectEl.disabled = false;
}

/**
 * Set selected agent in user settings
 * @param {Object} agentObj - Agent object with name and is_global
 * @returns {Promise<boolean>} Success
 */
export async function setSelectedAgent(agentObj) {
	const resp = await fetch('/api/user/settings/selected_agent', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ selected_agent: agentObj })
	});
	return resp.ok;
}
