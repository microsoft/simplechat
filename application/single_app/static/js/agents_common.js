// agents_common.js

import { showToast } from './chat/chat-toast.js';

const AGENT_ICON_FALLBACK_CLASSES = Object.freeze([
	'bi-robot',
	'bi-stars',
	'bi-lightbulb',
	'bi-search',
	'bi-graph-up',
	'bi-shield-check',
	'bi-code-square',
	'bi-database',
	'bi-envelope',
	'bi-calendar-check',
	'bi-file-earmark-text',
	'bi-bar-chart',
	'bi-diagram-3',
	'bi-globe',
	'bi-gear',
	'bi-person-workspace'
]);
const AGENT_ICON_IMAGE_MAX_SIZE = 128;
const AGENT_ICON_IMAGE_MAX_DATA_URL_LENGTH = 350000;
const AGENT_ICON_CLASS_PATTERN = /^bi-[a-z0-9][a-z0-9-]{0,80}$/;
const DEFAULT_ICON_CONTROL_SELECTORS = Object.freeze({
	editor: '.agent-icon-editor',
	mode: '#agent-icon-mode',
	classInput: '#agent-icon-class',
	imageData: '#agent-icon-image-data',
	preview: '#agent-icon-preview',
	typeBootstrap: '#agent-icon-type-bootstrap',
	typeImage: '#agent-icon-type-image',
	bootstrapControls: '#agent-bootstrap-icon-controls',
	imageControls: '#agent-image-icon-controls',
	pickerButton: '#agent-icon-picker-button',
	pickerLabel: '#agent-icon-picker-label',
	pickerSearch: '#agent-icon-picker-search',
	pickerList: '#agent-icon-picker-list',
	imageFile: '#agent-icon-image-file',
	imageClear: '#agent-icon-image-clear',
	defaultBootstrapIcon: 'bi-robot'
});
let bootstrapIconClassesPromise = null;

function getIconControlConfig(options = {}) {
	return { ...DEFAULT_ICON_CONTROL_SELECTORS, ...(options || {}) };
}

function getScopedElement(root, selector) {
	if (!root || !selector) return null;
	const normalizedSelector = /^[#.\[]/.test(selector) ? selector : `#${selector}`;
	return root.querySelector(normalizedSelector);
}

function normalizeBootstrapIconClass(value, fallbackIcon = 'bi-robot') {
	const normalizedFallback = AGENT_ICON_CLASS_PATTERN.test(fallbackIcon) ? fallbackIcon : 'bi-robot';
	const iconClass = String(value || '').replace(/^bi\s+/, '').trim();
	return AGENT_ICON_CLASS_PATTERN.test(iconClass) ? iconClass : normalizedFallback;
}

async function loadBootstrapIconClasses() {
	if (!bootstrapIconClassesPromise) {
		bootstrapIconClassesPromise = fetch('/static/css/bootstrap-icons.css')
			.then(response => response.ok ? response.text() : '')
			.then(cssText => {
				const matches = new Set();
				const iconPattern = /\.bi-([a-z0-9][a-z0-9-]*)::before/g;
				let match = iconPattern.exec(cssText);
				while (match) {
					matches.add(`bi-${match[1]}`);
					match = iconPattern.exec(cssText);
				}
				return Array.from(matches).sort((left, right) => left.localeCompare(right));
			})
			.catch(() => []);
	}

	const iconClasses = await bootstrapIconClassesPromise;
	return iconClasses.length ? iconClasses : Array.from(AGENT_ICON_FALLBACK_CLASSES);
}

function setIconPreview(root, options = {}) {
	const config = getIconControlConfig(options);
	const mode = getScopedElement(root, config.mode)?.value || 'bootstrap';
	const preview = getScopedElement(root, config.preview);
	if (!preview) return;
	preview.textContent = '';

	if (mode === 'image') {
		const imageData = getScopedElement(root, config.imageData)?.value || '';
		if (/^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(imageData)) {
			const image = document.createElement('img');
			image.src = imageData;
			image.alt = '';
			preview.appendChild(image);
			return;
		}
	}

	const iconElement = document.createElement('i');
	iconElement.className = `bi ${normalizeBootstrapIconClass(getScopedElement(root, config.classInput)?.value, config.defaultBootstrapIcon)}`;
	iconElement.setAttribute('aria-hidden', 'true');
	preview.appendChild(iconElement);
}

function setBootstrapIcon(root, iconClass, options = {}) {
	const config = getIconControlConfig(options);
	const normalizedIcon = normalizeBootstrapIconClass(iconClass, config.defaultBootstrapIcon);
	const classInput = getScopedElement(root, config.classInput);
	const pickerLabel = getScopedElement(root, config.pickerLabel);
	const pickerButtonIcon = getScopedElement(root, config.pickerButton)?.querySelector('i');
	if (classInput) classInput.value = normalizedIcon;
	if (pickerLabel) pickerLabel.textContent = normalizedIcon;
	if (pickerButtonIcon) pickerButtonIcon.className = `bi ${normalizedIcon} me-1`;
	setIconPreview(root, config);
}

function setIconMode(root, mode, options = {}) {
	const config = getIconControlConfig(options);
	const normalizedMode = mode === 'image' ? 'image' : 'bootstrap';
	const modeInput = getScopedElement(root, config.mode);
	const bootstrapRadio = getScopedElement(root, config.typeBootstrap);
	const imageRadio = getScopedElement(root, config.typeImage);
	const bootstrapControls = getScopedElement(root, config.bootstrapControls);
	const imageControls = getScopedElement(root, config.imageControls);
	if (modeInput) modeInput.value = normalizedMode;
	if (bootstrapRadio) bootstrapRadio.checked = normalizedMode === 'bootstrap';
	if (imageRadio) imageRadio.checked = normalizedMode === 'image';
	bootstrapControls?.classList.toggle('d-none', normalizedMode !== 'bootstrap');
	imageControls?.classList.toggle('d-none', normalizedMode !== 'image');
	setIconPreview(root, config);
}

function createImageFromUrl(imageUrl) {
	return new Promise((resolve, reject) => {
		const image = new Image();
		image.onload = () => resolve(image);
		image.onerror = () => reject(new Error('Unable to load image.'));
		image.src = imageUrl;
	});
}

async function resizeIconFileToDataUrl(file) {
	if (!file || !['image/png', 'image/jpeg'].includes(file.type)) {
		throw new Error('Choose a PNG or JPEG image.');
	}

	const objectUrl = URL.createObjectURL(file);
	try {
		const image = await createImageFromUrl(objectUrl);
		const scale = Math.min(1, AGENT_ICON_IMAGE_MAX_SIZE / Math.max(image.width, image.height));
		const width = Math.max(1, Math.round(image.width * scale));
		const height = Math.max(1, Math.round(image.height * scale));
		const canvas = document.createElement('canvas');
		canvas.width = width;
		canvas.height = height;
		const context = canvas.getContext('2d');
		context.drawImage(image, 0, 0, width, height);
		const dataUrl = canvas.toDataURL('image/png');
		if (dataUrl.length > AGENT_ICON_IMAGE_MAX_DATA_URL_LENGTH) {
			throw new Error('The icon image is too large after resizing.');
		}
		return dataUrl;
	} finally {
		URL.revokeObjectURL(objectUrl);
	}
}

async function renderIconPickerOptions(root, filterText = '', options = {}) {
	const config = getIconControlConfig(options);
	const list = getScopedElement(root, config.pickerList);
	if (!list) return;
	list.textContent = '';
	const normalizedFilter = String(filterText || '').trim().toLowerCase();
	const iconClasses = await loadBootstrapIconClasses();
	const filteredIcons = iconClasses.filter(iconClass => !normalizedFilter || iconClass.includes(normalizedFilter));

	if (!filteredIcons.length) {
		const empty = document.createElement('div');
		empty.className = 'text-muted small px-2 py-1';
		empty.textContent = 'No matching icons';
		list.appendChild(empty);
		return;
	}

	const fragment = document.createDocumentFragment();
	filteredIcons.forEach(iconClass => {
		const option = document.createElement('button');
		option.type = 'button';
		option.className = 'dropdown-item agent-icon-picker-option';
		option.dataset.iconClass = iconClass;
		option.setAttribute('role', 'option');

		const icon = document.createElement('i');
		icon.className = `bi ${iconClass}`;
		icon.setAttribute('aria-hidden', 'true');
		const label = document.createElement('span');
		label.textContent = iconClass;
		option.appendChild(icon);
		option.appendChild(label);
		fragment.appendChild(option);
	});
	list.appendChild(fragment);
}

export function initializeIconControls(root = document, options = {}) {
	const config = getIconControlConfig(options);
	const editor = getScopedElement(root, config.preview)?.closest(config.editor);
	if (!editor || editor.dataset.iconControlsBound === 'true') {
		return;
	}
	editor.dataset.iconControlsBound = 'true';

	getScopedElement(root, config.typeBootstrap)?.addEventListener('change', () => setIconMode(root, 'bootstrap', config));
	getScopedElement(root, config.typeImage)?.addEventListener('change', () => setIconMode(root, 'image', config));
	getScopedElement(root, config.pickerSearch)?.addEventListener('input', event => {
		renderIconPickerOptions(root, event.target.value, config);
	});
	getScopedElement(root, config.pickerList)?.addEventListener('click', event => {
		const option = event.target.closest('.agent-icon-picker-option[data-icon-class]');
		if (!option) return;
		setBootstrapIcon(root, option.dataset.iconClass, config);
		window.bootstrap?.Dropdown?.getInstance(getScopedElement(root, config.pickerButton))?.hide();
	});
	getScopedElement(root, config.imageFile)?.addEventListener('change', async event => {
		const file = event.target.files?.[0];
		if (!file) return;
		try {
			const dataUrl = await resizeIconFileToDataUrl(file);
			const imageDataInput = getScopedElement(root, config.imageData);
			if (imageDataInput) imageDataInput.value = dataUrl;
			setIconMode(root, 'image', config);
		} catch (error) {
			showToast(error.message || 'Unable to load icon image.', 'warning');
			event.target.value = '';
		}
	});
	getScopedElement(root, config.imageClear)?.addEventListener('click', () => {
		const imageDataInput = getScopedElement(root, config.imageData);
		const fileInput = getScopedElement(root, config.imageFile);
		if (imageDataInput) imageDataInput.value = '';
		if (fileInput) fileInput.value = '';
		setIconMode(root, 'bootstrap', config);
	});

	renderIconPickerOptions(root, '', config);
}

export function setIconPayload(root, iconPayload, options = {}) {
	const config = getIconControlConfig(options);
	initializeIconControls(root, config);
	if (iconPayload && iconPayload.kind === 'image' && iconPayload.value) {
		const imageDataInput = getScopedElement(root, config.imageData);
		if (imageDataInput) imageDataInput.value = iconPayload.value;
		setIconMode(root, 'image', config);
		return;
	}
	setBootstrapIcon(root, iconPayload && iconPayload.kind === 'bootstrap' ? iconPayload.value : config.defaultBootstrapIcon, config);
	setIconMode(root, 'bootstrap', config);
}

function setAgentIconPayload(root, iconPayload) {
	setIconPayload(root, iconPayload);
}

export function getIconPayload(root, options = {}) {
	const config = getIconControlConfig(options);
	const mode = getScopedElement(root, config.mode)?.value || 'bootstrap';
	if (mode === 'image') {
		const imageData = getScopedElement(root, config.imageData)?.value || '';
		if (/^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(imageData)) {
			const mimeType = imageData.startsWith('data:image/jpeg') ? 'image/jpeg' : 'image/png';
			return { kind: 'image', value: imageData, mime_type: mimeType };
		}
	}
	const iconClass = getScopedElement(root, config.classInput)?.value || '';
	return { kind: 'bootstrap', value: normalizeBootstrapIconClass(iconClass, config.defaultBootstrapIcon) };
}

export function getAgentIconPayload(root) {
	return getIconPayload(root);
}

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
	const setValue = (id, value) => {
		const el = root.getElementById(id);
		if (el) {
			el.value = value ?? '';
		}
	};
	const setChecked = (id, value) => {
		const el = root.getElementById(id);
		if (el) {
			el.checked = !!value;
		}
	};

	setValue('agent-name', agent.name || '');
	setValue('agent-display-name', agent.display_name || '');
	setValue('agent-description', agent.description || '');
	setValue('agent-tags', Array.isArray(agent.tags) ? agent.tags.join(', ') : '');
	setAgentIconPayload(root, agent.icon || {});
	setValue('agent-gpt-endpoint', agent.azure_openai_gpt_endpoint || '');
	setValue('agent-gpt-key', agent.azure_openai_gpt_key || '');
	setValue('agent-gpt-deployment', agent.azure_openai_gpt_deployment || '');
	setValue('agent-gpt-api-version', agent.azure_openai_gpt_api_version || '');
	setValue('agent-apim-endpoint', agent.azure_agent_apim_gpt_endpoint || '');
	setValue('agent-apim-subscription-key', agent.azure_agent_apim_gpt_subscription_key || '');
	setValue('agent-apim-deployment', agent.azure_agent_apim_gpt_deployment || '');
	setValue('agent-apim-api-version', agent.azure_agent_apim_gpt_api_version || '');
	setChecked('agent-enable-apim', agent.enable_agent_gpt_apim);
	setValue('agent-model-endpoint-id', agent.model_endpoint_id || '');
	setValue('agent-model-id', agent.model_id || '');
	setValue('agent-model-provider', agent.model_provider || '');
	setValue('agent-instructions', agent.instructions || '');
	setValue(
		'agent-additional-settings',
		agent.other_settings ? JSON.stringify(agent.other_settings, null, 2) : '{}'
	);
	setValue('agent-max-completion-tokens', agent.max_completion_tokens || '');
	
	// Set reasoning effort if available
	const reasoningEffortSelect = root.getElementById('agent-reasoning-effort');
	if (reasoningEffortSelect) {
		reasoningEffortSelect.value = agent.reasoning_effort || '';
	}
	// Actions handled separately
}

/**
 * Extracts agent data from modal fields and returns an agent object.
 * @param {Object} opts - { modalRoot: HTMLElement (optional, defaults to document), context: 'user'|'admin'|'group' }
 * @returns {Object} agent object
 */
export function getAgentModalFields(opts = {}) {
	const root = opts.modalRoot || document;
	const getValue = (id) => {
		const el = root.getElementById(id);
		return el ? el.value.trim() : '';
	};
	const getChecked = (id) => {
		const el = root.getElementById(id);
		return el ? el.checked : false;
	};
	let additionalSettings = {};
	try {
		const settingsRaw = getValue('agent-additional-settings');
		if (settingsRaw) additionalSettings = JSON.parse(settingsRaw);
	} catch (e) {
		showToast('Additional Settings must be a valid JSON object.', 'error');
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
		name: getValue('agent-name'),
		display_name: getValue('agent-display-name'),
		description: getValue('agent-description'),
		tags: getValue('agent-tags')
			.split(',')
			.map(tag => tag.trim())
			.filter(Boolean),
		icon: getAgentIconPayload(root),
		azure_openai_gpt_endpoint: getValue('agent-gpt-endpoint'),
		azure_openai_gpt_key: getValue('agent-gpt-key'),
		azure_openai_gpt_deployment: getValue('agent-gpt-deployment'),
		azure_openai_gpt_api_version: getValue('agent-gpt-api-version'),
		azure_agent_apim_gpt_endpoint: getValue('agent-apim-endpoint'),
		azure_agent_apim_gpt_subscription_key: getValue('agent-apim-subscription-key'),
		azure_agent_apim_gpt_deployment: getValue('agent-apim-deployment'),
		azure_agent_apim_gpt_api_version: getValue('agent-apim-api-version'),
		model_endpoint_id: getValue('agent-model-endpoint-id'),
		model_id: getValue('agent-model-id'),
		model_provider: getValue('agent-model-provider'),
		enable_agent_gpt_apim: getChecked('agent-enable-apim'),
		instructions: getValue('agent-instructions'),
		max_completion_tokens: parseInt(getValue('agent-max-completion-tokens')) || null,
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
		console.log('updateApimFieldsVisibility fired. apimToggle.checked:', apimToggle.checked);
		if (apimToggle.checked) {
			apimFields.style.display = 'block';
			gptFields.style.display = 'none';
			apimFields.classList.remove('d-none');
			gptFields.classList.add('d-none');
			console.log('Showing APIM fields, hiding GPT fields.');
		} else {
			apimFields.style.display = 'none';
			gptFields.style.display = 'block';
			gptFields.classList.remove('d-none');
			apimFields.classList.add('d-none');
			console.log('Hiding APIM fields, showing GPT fields.');
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
	const endpoints = Array.isArray(settings?.model_endpoints) ? settings.model_endpoints : [];
	const multiEndpointEnabled = (settings && settings.enable_multi_model_endpoints) || endpoints.length > 0;
	if (multiEndpointEnabled && endpoints.length) {
		const agentType = (agent && agent.agent_type) ? agent.agent_type : 'local';
		endpoints.forEach(endpoint => {
			if (!endpoint || endpoint.enabled === false) return;
			const provider = (endpoint.provider || 'aoai').toLowerCase();
			if (agentType === 'aifoundry' && provider !== 'aifoundry') {
				return;
			}
			if (agentType === 'new_foundry' && provider !== 'new_foundry') {
				return;
			}
			if (agentType === 'foundry_workflow' && !['foundry_workflow', 'new_foundry', 'aifoundry'].includes(provider)) {
				return;
			}
			const endpointId = endpoint.id || '';
			const endpointModels = endpoint.models || [];
			endpointModels.forEach(model => {
				if (!model || model.enabled === false) return;
				const modelId = model.id || model.deploymentName || model.deployment || model.modelName || model.name || '';
				const deploymentName = model.deploymentName || model.deployment || '';
				const modelName = model.modelName || model.name || '';
				const displayName = model.displayName || deploymentName || modelName || modelId;
				if (!displayName) return;
				models.push({
					id: modelId,
					deployment: deploymentName,
					name: modelName,
					display_name: displayName,
					endpoint_id: endpointId,
					provider
				});
			});
		});
		selectedModel = agent && (agent.model_id || agent.azure_openai_gpt_deployment) ? (agent.model_id || agent.azure_openai_gpt_deployment) : null;
		return { models, selectedModel };
	}
	if (apimEnabled) {
		// azure_apim_gpt_deployment is a string, could be comma separated
		let apimDeployments = (settings && settings.azure_apim_gpt_deployment) || '';
		models = apimDeployments.split(',').map(s => ({ deployment: s.trim(), display_name: s.trim() })).filter(m => m.deployment);
		selectedModel = agent && agent.azure_agent_apim_gpt_deployment ? agent.azure_agent_apim_gpt_deployment : null;
	} else {
		// Otherwise use gpt_model.selected (array)
		let rawModels = (settings && settings.gpt_model && settings.gpt_model.selected) ? settings.gpt_model.selected : [];
		console.log('Raw models:', rawModels);
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
		console.log('Available models:', selectedModel);
	}
	return { models, selectedModel };
}
/**
 * Fetches settings from endpoint and returns available models, selected model, and apimEnabled
 * @param {string} endpoint - API endpoint to fetch settings
 * @param {Object} agent - Current agent object
 * @returns {Promise<{models: Array, selectedModel: string, apimEnabled: boolean, enableMultiModelEndpoints: boolean}>}
 */
export async function fetchAndGetAvailableModels(endpoint, agent) {
	try {
		const resp = await fetch(endpoint);
		if (!resp.ok) throw new Error('Failed to fetch global models');
		const settings = await resp.json();
		// Check APIM enabled (support both enable_gpt_apim and enable_apim)
		const apimEnabled = settings.enable_gpt_apim || false;
		const endpoints = Array.isArray(settings.model_endpoints) ? settings.model_endpoints : [];
		const enableMultiModelEndpoints = (settings.enable_multi_model_endpoints || false) || endpoints.length > 0;
		const { models, selectedModel } = getAvailableModels({ apimEnabled, settings, agent });
		return { models, selectedModel, apimEnabled, enableMultiModelEndpoints };
	} catch (e) {
		return { models: [], selectedModel: null, apimEnabled: false, enableMultiModelEndpoints: false };
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
		opt.value = model.id || model.name || model.deployment || '';
		opt.textContent = model.display_name || model.name || model.deployment || model.id || '';
		if (model.endpoint_id) {
			opt.dataset.endpointId = model.endpoint_id;
		}
		if (model.provider) {
			opt.dataset.provider = model.provider;
		}
		if (model.deployment) {
			opt.dataset.deploymentName = model.deployment;
		}
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

export async function fetchGroupAgentsForActiveGroup(activeGroupId = null, activeGroupName = null) {
	const resolvedGroupId = activeGroupId || (typeof window !== 'undefined' ? window.activeGroupId : null);
	if (!resolvedGroupId) {
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
		const resolvedGroupName = activeGroupName || ((typeof window !== 'undefined' && window.activeGroupName) ? window.activeGroupName : '');
		return agents.map(agent => ({
			...agent,
			is_group: true,
			group_id: agent.group_id || resolvedGroupId,
			group_name: agent.group_name || resolvedGroupName || null
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
