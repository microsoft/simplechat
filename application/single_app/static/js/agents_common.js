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
 * Fetch user agents from backend
 * @returns {Promise<Array>} Array of agent objects
 */
export async function fetchUserAgents() {
	const res = await fetch('/api/user/agents');
	if (!res.ok) throw new Error('Failed to fetch user agents');
	return await res.json();
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
	let selectedAgentName = typeof selectedAgentObj === 'object' ? selectedAgentObj.name : selectedAgentObj;
	agents.forEach(agent => {
		let opt = document.createElement('option');
		opt.value = agent.name;
		opt.textContent = (agent.display_name || agent.name) + (agent.is_global ? ' (Global)' : '');
		if (agent.name === selectedAgentName) opt.selected = true;
		selectEl.appendChild(opt);
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
