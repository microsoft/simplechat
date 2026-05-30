// admin_governance.js

const GOVERNANCE_FEATURE_LABELS = {
    governance_user_endpoints: 'User Endpoints',
    governance_group_endpoints: 'Group Endpoints',
    governance_global_endpoints: 'Global Endpoints',
    governance_user_agents: 'User Agents',
    governance_group_agents: 'Group Agents',
    governance_global_agents_usage: 'Global Agent Usage',
    governance_user_actions: 'User Actions',
    governance_group_actions: 'Group Actions',
    governance_global_actions_usage: 'Global Action Usage',
};

const GOVERNANCE_ITEM_ENTITY_LABELS = {
    endpoint: 'Endpoint',
    global_agent: 'Global Agent',
    global_action: 'Global Action',
};

const GOVERNANCE_ITEM_LOOKUP_HINTS = {
    endpoint: 'Select an endpoint configured in Admin Settings.',
    global_agent: 'Select a global agent available for delegation.',
    global_action: 'Select a global action available for delegation.',
};

const GOVERNANCE_ALLOWLIST_PAGE_SIZE_DEFAULT = 50;
const GOVERNANCE_ALLOWLIST_PAGE_SIZES = [10, 25, 50, 100];
const GOVERNANCE_ALLOWLIST_TRUNCATE_ID_LENGTH = 35;

const GOVERNANCE_ITEM_REVIEW_DEFAULT_PAGE_SIZE = 25;

const governanceItemReviewState = {
    search: '',
    entityType: '',
    page: 1,
    perPage: GOVERNANCE_ITEM_REVIEW_DEFAULT_PAGE_SIZE,
};

let governanceItemReviewModal = null;
let governanceAllowListEditorModal = null;
let governanceAllowListEditorContext = null;
let governanceItemPolicyDeleteModal = null;
let governanceItemPolicyDeleteContext = null;
const governanceItemLookupState = {
    endpoint: [],
    global_agent: [],
    global_action: [],
};

const governanceAllowListSelectionViewState = {
    users: {
        search: '',
        page: 1,
        pageSize: GOVERNANCE_ALLOWLIST_PAGE_SIZE_DEFAULT,
    },
    groups: {
        search: '',
        page: 1,
        pageSize: GOVERNANCE_ALLOWLIST_PAGE_SIZE_DEFAULT,
    },
};

const governanceAllowListDisplayNameCache = {
    users: {},
    groups: {},
};

const governanceAllowListHydrationState = {
    users: new Set(),
    groups: new Set(),
};

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function splitPrincipalList(value) {
    if (!value) {
        return [];
    }

    return String(value)
        .split(',')
        .map((item) => item.trim())
        .filter((item) => item.length > 0);
}

function joinPrincipalList(values) {
    if (!Array.isArray(values) || values.length === 0) {
        return '';
    }

    return values.join(', ');
}

function parseCsvPrincipalLines(csvText) {
    if (!csvText) {
        return [];
    }

    return String(csvText)
        .split(/\r?\n/)
        .flatMap((line) => line.split(','))
        .map((value) => value.trim())
        .filter((value) => value.length > 0);
}

function uniquePrincipalList(values) {
    return Array.from(new Set((Array.isArray(values) ? values : []).map((value) => String(value || '').trim()).filter((value) => value)));
}

function buildAllowListSummary(users, groups) {
    const usersCount = Array.isArray(users) ? users.length : 0;
    const groupsCount = Array.isArray(groups) ? groups.length : 0;
    if (usersCount === 0 && groupsCount === 0) {
        return 'No explicit users or groups configured';
    }
    return `${usersCount} user${usersCount === 1 ? '' : 's'}, ${groupsCount} group${groupsCount === 1 ? '' : 's'}`;
}

function getGovernanceUsersInputForFeatureRow(row) {
    return row?.querySelector('.governance-allowed-users') || null;
}

function getGovernanceGroupsInputForFeatureRow(row) {
    return row?.querySelector('.governance-allowed-groups') || null;
}

function getGovernanceFeatureAllowAllInput(row) {
    return row?.querySelector('.governance-allow-all') || null;
}

function getItemAllowAllInput() {
    return document.getElementById('governance-item-allow-all');
}

function getItemUsersInput() {
    return document.getElementById('governance-item-users');
}

function getItemGroupsInput() {
    return document.getElementById('governance-item-groups');
}

function getItemEntityTypeInput() {
    return document.getElementById('governance-item-entity-type');
}

function getItemIdInput() {
    return document.getElementById('governance-item-id');
}

function setGovernanceItemLookupStatus(message, level = 'muted') {
    const status = document.getElementById('governance-item-id-status');
    if (!status) {
        return;
    }

    status.classList.remove('text-muted', 'text-success', 'text-warning', 'text-danger');
    const className = {
        muted: 'text-muted',
        success: 'text-success',
        warning: 'text-warning',
        danger: 'text-danger',
    }[level] || 'text-muted';
    status.classList.add(className);
    status.textContent = message || '';
}

function normalizeGovernanceLookupOption(option, fallbackLabelPrefix) {
    const value = String(option?.value || option?.id || '').trim();
    if (!value) {
        return null;
    }

    const label = String(option?.label || option?.name || option?.display_name || `${fallbackLabelPrefix} ${value}`).trim();
    const subtitle = String(option?.subtitle || option?.description || '').trim();
    return {
        value,
        label,
        subtitle,
    };
}

function buildGovernanceItemLookupOption(option) {
    const label = option.subtitle ? `${option.label} (${option.subtitle})` : option.label;
    const element = document.createElement('option');
    element.value = option.value;
    element.textContent = label;
    return element;
}

function getAdminEndpointLookupOptionsFromWindow() {
    const fromWindow = Array.isArray(window.modelEndpoints) ? window.modelEndpoints : [];
    const fromHiddenInputRaw = document.getElementById('model_endpoints_json')?.value || '[]';

    let fromHiddenInput = [];
    try {
        const parsed = JSON.parse(fromHiddenInputRaw);
        fromHiddenInput = Array.isArray(parsed) ? parsed : [];
    } catch (error) {
        fromHiddenInput = [];
    }

    const merged = [...fromWindow, ...fromHiddenInput];
    return merged
        .map((endpoint) => normalizeGovernanceLookupOption({
            value: endpoint?.id,
            label: endpoint?.name || endpoint?.id,
            subtitle: endpoint?.connection?.endpoint || endpoint?.endpoint || '',
        }, 'Endpoint'))
        .filter((endpoint) => endpoint !== null)
        .filter((endpoint, index, arr) => arr.findIndex((candidate) => candidate.value === endpoint.value) === index);
}

async function fetchAdminGlobalAgentLookupOptions() {
    const response = await fetch('/api/admin/agents', {
        method: 'GET',
        headers: {
            Accept: 'application/json',
        },
    });

    if (!response.ok) {
        throw new Error('Unable to load global agents lookup.');
    }

    const payload = await response.json();
    return (Array.isArray(payload) ? payload : [])
        .map((agent) => normalizeGovernanceLookupOption({
            value: agent?.id,
            label: agent?.display_name || agent?.name || agent?.id,
            subtitle: agent?.name && agent?.display_name && agent?.display_name !== agent?.name ? agent?.name : '',
        }, 'Agent'))
        .filter((option) => option !== null);
}

async function fetchAdminGlobalActionLookupOptions() {
    const response = await fetch('/api/admin/plugins', {
        method: 'GET',
        headers: {
            Accept: 'application/json',
        },
    });

    if (!response.ok) {
        throw new Error('Unable to load global actions lookup.');
    }

    const payload = await response.json();
    return (Array.isArray(payload) ? payload : [])
        .map((action) => normalizeGovernanceLookupOption({
            value: action?.id,
            label: action?.name || action?.id,
            subtitle: action?.type || '',
        }, 'Action'))
        .filter((option) => option !== null);
}

async function loadGovernanceItemLookup(entityType, forceReload = false) {
    const normalizedEntityType = String(entityType || '').trim();
    if (!normalizedEntityType) {
        return [];
    }

    if (!forceReload && Array.isArray(governanceItemLookupState[normalizedEntityType]) && governanceItemLookupState[normalizedEntityType].length > 0) {
        return governanceItemLookupState[normalizedEntityType];
    }

    if (normalizedEntityType === 'endpoint') {
        governanceItemLookupState.endpoint = getAdminEndpointLookupOptionsFromWindow();
        return governanceItemLookupState.endpoint;
    }
    if (normalizedEntityType === 'global_agent') {
        governanceItemLookupState.global_agent = await fetchAdminGlobalAgentLookupOptions();
        return governanceItemLookupState.global_agent;
    }
    if (normalizedEntityType === 'global_action') {
        governanceItemLookupState.global_action = await fetchAdminGlobalActionLookupOptions();
        return governanceItemLookupState.global_action;
    }

    return [];
}

function renderGovernanceItemLookupOptions(entityType, preferredValue = '') {
    const itemIdInput = getItemIdInput();
    if (!itemIdInput) {
        return;
    }

    const options = Array.isArray(governanceItemLookupState[entityType]) ? governanceItemLookupState[entityType] : [];
    const currentValue = String(preferredValue || '').trim();

    itemIdInput.innerHTML = '';

    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = options.length > 0 ? 'Select an item' : 'No items available';
    itemIdInput.appendChild(placeholder);

    options.forEach((option) => {
        itemIdInput.appendChild(buildGovernanceItemLookupOption(option));
    });

    if (currentValue && options.some((option) => option.value === currentValue)) {
        itemIdInput.value = currentValue;
    } else {
        itemIdInput.value = '';
    }

    const hint = GOVERNANCE_ITEM_LOOKUP_HINTS[entityType] || 'Select a delegated item.';
    if (options.length > 0) {
        setGovernanceItemLookupStatus(`${hint} Loaded ${options.length} item${options.length === 1 ? '' : 's'}.`, 'muted');
    } else {
        setGovernanceItemLookupStatus(`${hint} No items found for this type.`, 'warning');
    }
}

async function refreshGovernanceItemLookup(entityType, forceReload = false, preferredValue = '') {
    const refreshButton = document.getElementById('governance-item-id-refresh-btn');
    if (refreshButton) {
        refreshButton.disabled = true;
    }

    try {
        await loadGovernanceItemLookup(entityType, forceReload);
        renderGovernanceItemLookupOptions(entityType, preferredValue);
    } catch (error) {
        renderGovernanceItemLookupOptions(entityType, '');
        setGovernanceItemLookupStatus(error.message || 'Failed to load delegated item lookup.', 'danger');
    } finally {
        if (refreshButton) {
            refreshButton.disabled = false;
        }
    }
}

function updateFeatureAllowListSummary(row) {
    const usersInput = getGovernanceUsersInputForFeatureRow(row);
    const groupsInput = getGovernanceGroupsInputForFeatureRow(row);
    const summaryEl = row?.querySelector('.governance-allowlist-summary');
    if (!usersInput || !groupsInput || !summaryEl) {
        return;
    }

    const users = splitPrincipalList(usersInput.value);
    const groups = splitPrincipalList(groupsInput.value);
    summaryEl.textContent = buildAllowListSummary(users, groups);
}

function updateItemAllowListSummary() {
    const usersInput = getItemUsersInput();
    const groupsInput = getItemGroupsInput();
    const summaryInput = document.getElementById('governance-item-allowlist-summary');
    if (!usersInput || !groupsInput || !summaryInput) {
        return;
    }

    summaryInput.value = buildAllowListSummary(splitPrincipalList(usersInput.value), splitPrincipalList(groupsInput.value));
}

function applyFeatureAllowAllUiState(row) {
    const allowAllInput = getGovernanceFeatureAllowAllInput(row);
    const editButton = row?.querySelector('.governance-edit-feature-allowlist-btn');
    const usersInput = getGovernanceUsersInputForFeatureRow(row);
    const groupsInput = getGovernanceGroupsInputForFeatureRow(row);
    if (!allowAllInput || !usersInput || !groupsInput) {
        return;
    }

    if (allowAllInput.checked) {
        usersInput.value = '';
        groupsInput.value = '';
    }

    if (editButton) {
        editButton.disabled = allowAllInput.checked;
    }

    updateFeatureAllowListSummary(row);
}

function applyItemAllowAllUiState() {
    const allowAllInput = getItemAllowAllInput();
    const editButton = document.getElementById('governance-edit-item-allowlist-btn');
    const allowedPrincipalsControls = document.getElementById('governance-item-allowed-principals-controls');
    const usersInput = getItemUsersInput();
    const groupsInput = getItemGroupsInput();
    if (!allowAllInput || !usersInput || !groupsInput) {
        return;
    }

    if (allowAllInput.checked) {
        usersInput.value = '';
        groupsInput.value = '';
    }

    if (editButton) {
        editButton.disabled = allowAllInput.checked;
    }

    if (allowedPrincipalsControls) {
        allowedPrincipalsControls.classList.toggle('d-none', allowAllInput.checked);
    }

    updateItemAllowListSummary();
}

async function governanceLookupUsers(query) {
    const response = await fetch(`/api/userSearch?query=${encodeURIComponent(String(query || '').trim())}`, {
        method: 'GET',
        headers: {
            Accept: 'application/json',
        },
    });

    if (!response.ok) {
        throw new Error('User lookup failed.');
    }

    const payload = await response.json();
    return Array.isArray(payload) ? payload : [];
}

async function governanceLookupGroups(query) {
    const response = await fetch(`/api/groups/discover?search=${encodeURIComponent(String(query || '').trim())}&showAll=true`, {
        method: 'GET',
        headers: {
            Accept: 'application/json',
        },
    });

    if (!response.ok) {
        throw new Error('Group lookup failed.');
    }

    const payload = await response.json();
    return Array.isArray(payload) ? payload : [];
}

// Prep hook for chat/workspace follow-up to reuse the same normalized lookup behavior.
window.governancePrincipalLookup = {
    searchUsers: governanceLookupUsers,
    searchGroups: governanceLookupGroups,
};

function buildItemPolicyEntityLabel(entityType) {
    return GOVERNANCE_ITEM_ENTITY_LABELS[entityType] || entityType || '';
}

function mapGovernanceLevelToToastVariant(level = 'info') {
    const normalized = String(level || 'info').toLowerCase();
    if (normalized === 'error') {
        return 'danger';
    }
    if (normalized === 'warn') {
        return 'warning';
    }
    return normalized;
}

function setGovernanceInlineStatusFallback(message, level = 'info') {
    const status = document.getElementById('governance-status');
    if (!status) {
        return;
    }

    const alertLevel = mapGovernanceLevelToToastVariant(level);
    status.className = `alert alert-${alertLevel}`;
    status.classList.remove('d-none');
    status.textContent = String(message || '');
}

function setGovernanceStatus(message, level = 'info') {
    if (!message) {
        return;
    }
    showGovernanceToast(message, mapGovernanceLevelToToastVariant(level));
}

function clearGovernanceStatus() {
    const status = document.getElementById('governance-status');
    if (!status) {
        return;
    }

    status.className = 'alert d-none';
    status.textContent = '';
}

function showGovernanceToast(message, variant = 'success') {
    const normalizedVariant = mapGovernanceLevelToToastVariant(variant);
    const container = document.getElementById('toast-container');
    if (!container || typeof bootstrap?.Toast !== 'function') {
        setGovernanceInlineStatusFallback(message, normalizedVariant === 'danger' ? 'danger' : normalizedVariant);
        return;
    }

    const toastEl = document.createElement('div');
    toastEl.className = `toast align-items-center text-bg-${normalizedVariant}`;
    toastEl.setAttribute('role', 'alert');
    toastEl.setAttribute('aria-live', 'assertive');
    toastEl.setAttribute('aria-atomic', 'true');

    const contentEl = document.createElement('div');
    contentEl.className = 'd-flex';

    const bodyEl = document.createElement('div');
    bodyEl.className = 'toast-body';
    bodyEl.textContent = String(message || '');

    const closeButtonEl = document.createElement('button');
    closeButtonEl.type = 'button';
    closeButtonEl.className = 'btn-close btn-close-white me-2 m-auto';
    closeButtonEl.setAttribute('data-bs-dismiss', 'toast');
    closeButtonEl.setAttribute('aria-label', 'Close');

    contentEl.appendChild(bodyEl);
    contentEl.appendChild(closeButtonEl);
    toastEl.appendChild(contentEl);
    container.appendChild(toastEl);

    const bsToast = new bootstrap.Toast(toastEl, { delay: 5000 });
    bsToast.show();

    toastEl.addEventListener('hidden.bs.toast', () => {
        toastEl.remove();
    });
}

function getGovernanceFeatureToggle(featureKey) {
    const toggle = document.getElementById(featureKey);
    return toggle instanceof HTMLInputElement ? toggle : null;
}

function syncGovernanceFeaturePolicyRowVisibility(row) {
    const featureKey = String(row?.dataset?.featureKey || '').trim();
    if (!row || !featureKey) {
        return;
    }

    const featureToggle = getGovernanceFeatureToggle(featureKey);
    const shouldShow = !featureToggle || featureToggle.checked;
    row.classList.toggle('d-none', !shouldShow);
}

function syncGovernanceFeaturePolicyVisibility() {
    Array.from(document.querySelectorAll('#governance-feature-policies-body tr')).forEach((row) => {
        syncGovernanceFeaturePolicyRowVisibility(row);
    });
}

function buildFeaturePolicyRow(policy) {
    const row = document.createElement('tr');
    row.dataset.featureKey = policy.feature_key;

    const featureCell = document.createElement('td');
    featureCell.textContent = GOVERNANCE_FEATURE_LABELS[policy.feature_key] || policy.feature_key;

    const allowAllCell = document.createElement('td');
    const allowAll = document.createElement('input');
    allowAll.type = 'checkbox';
    allowAll.className = 'form-check-input governance-allow-all';
    allowAll.checked = Boolean(policy.allow_all);
    allowAllCell.appendChild(allowAll);

    const usersCell = document.createElement('td');
    const usersInput = document.createElement('input');
    usersInput.type = 'text';
    usersInput.className = 'form-control form-control-sm governance-allowed-users d-none';
    usersInput.value = joinPrincipalList(policy.allowed_users);
    usersCell.appendChild(usersInput);

    const usersSummary = document.createElement('div');
    usersSummary.className = 'small text-body-secondary governance-allowlist-summary';
    usersSummary.textContent = buildAllowListSummary(policy.allowed_users, policy.allowed_groups);
    usersCell.appendChild(usersSummary);

    const usersEditButton = document.createElement('button');
    usersEditButton.type = 'button';
    usersEditButton.className = 'btn btn-sm btn-outline-primary mt-1 governance-edit-feature-allowlist-btn';
    usersEditButton.textContent = 'Edit Allow List';
    usersCell.appendChild(usersEditButton);

    const groupsCell = document.createElement('td');
    const groupsInput = document.createElement('input');
    groupsInput.type = 'text';
    groupsInput.className = 'form-control form-control-sm governance-allowed-groups d-none';
    groupsInput.value = joinPrincipalList(policy.allowed_groups);
    groupsCell.appendChild(groupsInput);

    const groupsSummary = document.createElement('div');
    groupsSummary.className = 'small text-body-secondary';
    groupsSummary.textContent = 'Includes group IDs added in the editor.';
    groupsCell.appendChild(groupsSummary);

    row.appendChild(featureCell);
    row.appendChild(allowAllCell);
    row.appendChild(usersCell);
    row.appendChild(groupsCell);

    applyFeatureAllowAllUiState(row);
    syncGovernanceFeaturePolicyRowVisibility(row);

    return row;
}

async function loadFeaturePolicies() {
    const tbody = document.getElementById('governance-feature-policies-body');
    if (!tbody) {
        return;
    }

    const response = await fetch('/api/admin/governance/policies', {
        method: 'GET',
        headers: {
            Accept: 'application/json',
        },
    });

    if (!response.ok) {
        throw new Error('Unable to load governance feature policies.');
    }

    const payload = await response.json();
    const featurePolicies = Array.isArray(payload.features) ? payload.features : [];

    tbody.innerHTML = '';
    featurePolicies.forEach((policy) => {
        tbody.appendChild(buildFeaturePolicyRow(policy));
    });
    syncGovernanceFeaturePolicyVisibility();
}

async function saveFeaturePolicies() {
    const rows = Array.from(document.querySelectorAll('#governance-feature-policies-body tr'));
    if (rows.length === 0) {
        setGovernanceStatus('No feature policies are available to save.', 'warning');
        return;
    }

    for (const row of rows) {
        const featureKey = row.dataset.featureKey;
        const allowAllInput = row.querySelector('.governance-allow-all');
        const usersInput = row.querySelector('.governance-allowed-users');
        const groupsInput = row.querySelector('.governance-allowed-groups');

        if (!featureKey || !allowAllInput || !usersInput || !groupsInput) {
            continue;
        }

        const body = {
            allow_all: allowAllInput.checked,
            allowed_users: splitPrincipalList(usersInput.value),
            allowed_groups: splitPrincipalList(groupsInput.value),
        };

        const response = await fetch(`/api/admin/governance/policies/${encodeURIComponent(featureKey)}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                Accept: 'application/json',
            },
            body: JSON.stringify(body),
        });

        if (!response.ok) {
            throw new Error(`Failed to save policy for ${featureKey}.`);
        }
    }

    clearGovernanceStatus();
    showGovernanceToast('Governance feature policies saved successfully.', 'success');
}

function buildItemPolicyRow(policy) {
    const row = document.createElement('tr');

    const entityTypeCell = document.createElement('td');
    const entityType = String(policy.entity_type || '');
    const itemId = String(policy.item_id || '');
    const allowAll = Boolean(policy.allow_all);
    const allowedUsers = Array.isArray(policy.allowed_users) ? policy.allowed_users : [];
    const allowedGroups = Array.isArray(policy.allowed_groups) ? policy.allowed_groups : [];

    entityTypeCell.textContent = buildItemPolicyEntityLabel(entityType);

    const itemIdCell = document.createElement('td');
    itemIdCell.textContent = itemId;

    const allowAllCell = document.createElement('td');
    allowAllCell.textContent = allowAll ? 'Yes' : 'No';

    const usersCell = document.createElement('td');
    renderGovernancePrincipalReviewCell(usersCell, 'users', allowedUsers);

    const groupsCell = document.createElement('td');
    renderGovernancePrincipalReviewCell(groupsCell, 'groups', allowedGroups);

    const actionsCell = document.createElement('td');
    actionsCell.className = 'text-nowrap';
    const editButton = document.createElement('button');
    editButton.type = 'button';
    editButton.className = 'btn btn-sm btn-outline-primary governance-edit-item-policy-btn';
    editButton.textContent = 'Edit';
    editButton.dataset.entityType = entityType;
    editButton.dataset.itemId = itemId;
    editButton.dataset.allowAll = allowAll ? 'true' : 'false';
    editButton.dataset.allowedUsers = JSON.stringify(allowedUsers);
    editButton.dataset.allowedGroups = JSON.stringify(allowedGroups);
    actionsCell.appendChild(editButton);

    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'btn btn-sm btn-outline-danger ms-2 governance-delete-item-policy-btn';
    deleteButton.textContent = 'Delete';
    deleteButton.dataset.entityType = entityType;
    deleteButton.dataset.itemId = itemId;
    actionsCell.appendChild(deleteButton);

    row.appendChild(entityTypeCell);
    row.appendChild(itemIdCell);
    row.appendChild(allowAllCell);
    row.appendChild(usersCell);
    row.appendChild(groupsCell);
    row.appendChild(actionsCell);

    return row;
}

function renderGovernancePrincipalReviewCell(cell, listType, ids, hydrateMissing = true) {
    if (!cell) {
        return;
    }

    const normalizedIds = uniquePrincipalList(ids);
    cell.textContent = '';
    cell.className = 'small';

    if (normalizedIds.length === 0) {
        cell.className = 'small text-muted';
        cell.textContent = 'None';
        return;
    }

    const missingIds = [];
    normalizedIds.forEach((idValue) => {
        const displayName = getGovernanceDisplayName(listType, idValue);
        const truncatedId = truncateGovernanceId(idValue);
        const wrapper = document.createElement('div');
        wrapper.className = 'mb-1';

        const primary = document.createElement('div');
        primary.textContent = displayName || truncatedId;
        primary.title = displayName || idValue;
        wrapper.appendChild(primary);

        if (displayName) {
            const secondary = document.createElement('div');
            secondary.className = 'text-muted';
            secondary.textContent = truncatedId;
            secondary.title = idValue;
            wrapper.appendChild(secondary);
        } else {
            missingIds.push(idValue);
        }

        cell.appendChild(wrapper);
    });

    if (hydrateMissing && missingIds.length > 0) {
        void hydrateGovernanceDisplayNames(listType, missingIds).then(() => {
            renderGovernancePrincipalReviewCell(cell, listType, normalizedIds, false);
        }).catch(() => {
            renderGovernancePrincipalReviewCell(cell, listType, normalizedIds, false);
        });
    }
}

function parseGovernancePrincipalDataset(value) {
    try {
        const parsed = JSON.parse(value || '[]');
        return uniquePrincipalList(Array.isArray(parsed) ? parsed : []);
    } catch (error) {
        return [];
    }
}

function ensureGovernanceItemIdOption(itemIdInput, itemId) {
    const normalizedItemId = String(itemId || '').trim();
    if (!itemIdInput || !normalizedItemId) {
        return;
    }

    const hasOption = Array.from(itemIdInput.options || []).some((option) => option.value === normalizedItemId);
    if (!hasOption) {
        const option = document.createElement('option');
        option.value = normalizedItemId;
        option.textContent = normalizedItemId;
        itemIdInput.appendChild(option);
    }
    itemIdInput.value = normalizedItemId;
}

async function loadGovernanceItemPolicyIntoEditor(policy) {
    const entityTypeInput = document.getElementById('governance-item-entity-type');
    const itemIdInput = document.getElementById('governance-item-id');
    const allowAllInput = document.getElementById('governance-item-allow-all');
    const usersInput = getItemUsersInput();
    const groupsInput = getItemGroupsInput();

    if (!entityTypeInput || !itemIdInput || !allowAllInput || !usersInput || !groupsInput) {
        return;
    }

    const entityType = String(policy?.entity_type || '').trim();
    const itemId = String(policy?.item_id || '').trim();
    if (!entityType || !itemId) {
        return;
    }

    entityTypeInput.value = entityType;
    await refreshGovernanceItemLookup(entityType, false, itemId);
    ensureGovernanceItemIdOption(itemIdInput, itemId);

    allowAllInput.checked = Boolean(policy.allow_all);
    usersInput.value = joinPrincipalList(policy.allowed_users || []);
    groupsInput.value = joinPrincipalList(policy.allowed_groups || []);

    updateItemAllowListSummary();
    applyItemAllowAllUiState();
    document.getElementById('governance-item-policy-form')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    itemIdInput.focus();
}

function openCurrentDelegatedItemAllowListEditor() {
    const usersInput = getItemUsersInput();
    const groupsInput = getItemGroupsInput();
    const entityTypeInput = document.getElementById('governance-item-entity-type');
    const itemIdInput = document.getElementById('governance-item-id');

    if (!usersInput || !groupsInput) {
        return;
    }

    const entityType = String(entityTypeInput?.value || '').trim();
    const itemId = String(itemIdInput?.value || '').trim();
    const contextSuffix = entityType && itemId
        ? ` (${GOVERNANCE_ITEM_ENTITY_LABELS[entityType] || entityType}: ${itemId})`
        : '';

    openGovernanceAllowListEditor({
        title: `Edit Delegated Item Allow List${contextSuffix}`,
        description: 'Manage explicitly allowed users and groups for this delegated item policy.',
        getUsers: () => splitPrincipalList(usersInput.value),
        getGroups: () => splitPrincipalList(groupsInput.value),
        setValues: (users, groups) => {
            usersInput.value = joinPrincipalList(users);
            groupsInput.value = joinPrincipalList(groups);
            const allowAllInput = getItemAllowAllInput();
            if (allowAllInput) {
                allowAllInput.checked = false;
            }
            applyItemAllowAllUiState();
        },
    });
}

function openCurrentDelegatedItemAllowListEditorAfterReviewModalCloses() {
    const reviewModalElement = document.getElementById('governance-item-policies-review-modal');
    if (!reviewModalElement?.classList.contains('show')) {
        openCurrentDelegatedItemAllowListEditor();
        return;
    }

    reviewModalElement.addEventListener('hidden.bs.modal', () => {
        openCurrentDelegatedItemAllowListEditor();
    }, { once: true });
    governanceItemReviewModal?.hide();
}

function ensureGovernanceItemPolicyDeleteModal() {
    let modalElement = document.getElementById('governance-item-policy-delete-confirm-modal');
    if (!modalElement) {
        const modalMarkup = `
            <div class="modal fade" id="governance-item-policy-delete-confirm-modal" tabindex="-1" aria-hidden="true">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Delete Delegated Item Policy</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <p class="mb-2">Delete this delegated item policy?</p>
                            <div class="alert alert-warning mb-0" id="governance-item-policy-delete-summary"></div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-danger" id="governance-item-policy-delete-confirm-btn">Delete Policy</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const wrapper = document.createElement('div');
        wrapper.innerHTML = modalMarkup.trim();
        modalElement = wrapper.firstElementChild;
        document.body.appendChild(modalElement);
    }

    if (!governanceItemPolicyDeleteModal) {
        governanceItemPolicyDeleteModal = bootstrap.Modal.getOrCreateInstance(modalElement);
    }

    if (!modalElement.dataset.wired) {
        modalElement.dataset.wired = 'true';
        const confirmButton = document.getElementById('governance-item-policy-delete-confirm-btn');
        if (confirmButton) {
            confirmButton.addEventListener('click', async () => {
                try {
                    await deleteGovernanceItemPolicyFromContext();
                } catch (error) {
                    setGovernanceStatus(error.message || 'Failed to delete item governance policy.', 'danger');
                }
            });
        }
    }

    return modalElement;
}

function openGovernanceItemPolicyDeleteModal(entityType, itemId) {
    const normalizedEntityType = String(entityType || '').trim();
    const normalizedItemId = String(itemId || '').trim();
    if (!normalizedEntityType || !normalizedItemId) {
        return;
    }

    governanceItemPolicyDeleteContext = {
        entityType: normalizedEntityType,
        itemId: normalizedItemId,
    };

    ensureGovernanceItemPolicyDeleteModal();
    const summary = document.getElementById('governance-item-policy-delete-summary');
    if (summary) {
        summary.textContent = `${buildItemPolicyEntityLabel(normalizedEntityType)}: ${normalizedItemId}`;
    }
    governanceItemPolicyDeleteModal?.show();
}

async function deleteGovernanceItemPolicyFromContext() {
    if (!governanceItemPolicyDeleteContext) {
        return;
    }

    const { entityType, itemId } = governanceItemPolicyDeleteContext;
    const response = await fetch(
        `/api/admin/governance/item-policies/${encodeURIComponent(entityType)}/${encodeURIComponent(itemId)}`,
        {
            method: 'DELETE',
            headers: {
                Accept: 'application/json',
            },
        }
    );

    if (!response.ok) {
        throw new Error('Unable to delete item governance policy.');
    }

    governanceItemPolicyDeleteModal?.hide();
    governanceItemPolicyDeleteContext = null;

    const entityTypeInput = document.getElementById('governance-item-entity-type');
    const itemIdInput = document.getElementById('governance-item-id');
    if (entityTypeInput?.value === entityType && itemIdInput?.value === itemId) {
        const allowAllInput = getItemAllowAllInput();
        const usersInput = getItemUsersInput();
        const groupsInput = getItemGroupsInput();
        if (allowAllInput) {
            allowAllInput.checked = true;
        }
        if (usersInput) {
            usersInput.value = '';
        }
        if (groupsInput) {
            groupsInput.value = '';
        }
        applyItemAllowAllUiState();
    }

    await loadItemPolicies();
    await loadGovernanceItemPolicyReview();
    showGovernanceToast('Delegated item policy deleted.', 'success');
}

function ensureGovernanceItemReviewModal() {
    const existingModal = document.getElementById('governance-item-policies-review-modal');
    if (existingModal) {
        wireGovernanceItemReviewHandlers(existingModal);
        return existingModal;
    }

    const modalMarkup = `
        <div class="modal fade" id="governance-item-policies-review-modal" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog modal-xl modal-dialog-scrollable">
                <div class="modal-content">
                    <div class="modal-header">
                        <div>
                            <h5 class="modal-title mb-1">Configured Delegated Items</h5>
                            <div class="text-muted small">Search and page through the configured item policies.</div>
                        </div>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row g-2 align-items-end mb-3">
                            <div class="col-md-5">
                                <label class="form-label" for="governance-item-review-search">Search</label>
                                <input type="search" class="form-control" id="governance-item-review-search" placeholder="Search users, groups, endpoint IDs, or item IDs">
                            </div>
                            <div class="col-md-3">
                                <label class="form-label" for="governance-item-review-entity-type">Entity Type</label>
                                <select class="form-select" id="governance-item-review-entity-type">
                                    <option value="">All</option>
                                    <option value="endpoint">Endpoint</option>
                                    <option value="global_agent">Global Agent</option>
                                    <option value="global_action">Global Action</option>
                                </select>
                            </div>
                            <div class="col-md-2">
                                <label class="form-label" for="governance-item-review-page-size">Page Size</label>
                                <select class="form-select" id="governance-item-review-page-size">
                                    <option value="10">10</option>
                                    <option value="25" selected>25</option>
                                    <option value="50">50</option>
                                </select>
                            </div>
                            <div class="col-md-2 d-grid gap-2">
                                <button type="button" class="btn btn-primary" id="governance-item-review-search-btn">Search</button>
                                <button type="button" class="btn btn-outline-secondary" id="governance-item-review-reset-btn">Reset</button>
                            </div>
                        </div>

                        <div class="table-responsive">
                            <table class="table table-sm table-striped align-middle">
                                <thead>
                                    <tr>
                                        <th>Entity Type</th>
                                        <th>Item ID</th>
                                        <th>Allow All</th>
                                        <th>Allowed Users</th>
                                        <th>Allowed Groups</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody id="governance-item-policies-review-body"></tbody>
                            </table>
                        </div>

                        <div class="d-flex align-items-center justify-content-between gap-2 mt-3">
                            <div class="text-muted small" id="governance-item-review-summary"></div>
                            <div class="btn-group" role="group" aria-label="Delegated item policy pagination">
                                <button type="button" class="btn btn-outline-secondary btn-sm" id="governance-item-review-prev-btn">Previous</button>
                                <button type="button" class="btn btn-outline-secondary btn-sm" id="governance-item-review-next-btn">Next</button>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    const wrapper = document.createElement('div');
    wrapper.innerHTML = modalMarkup.trim();
    const modalElement = wrapper.firstElementChild;
    document.body.appendChild(modalElement);
    wireGovernanceItemReviewHandlers(modalElement);
    return modalElement;
}

function wireGovernanceItemReviewHandlers(modalElement) {
    if (!modalElement || modalElement.dataset.reviewWired) {
        return;
    }

    const itemPolicyReviewBody = modalElement.querySelector('#governance-item-policies-review-body');
    if (!itemPolicyReviewBody) {
        return;
    }

    modalElement.dataset.reviewWired = 'true';
    itemPolicyReviewBody.addEventListener('click', async (event) => {
        const target = event.target;
        const editButton = target instanceof HTMLElement ? target.closest('.governance-edit-item-policy-btn') : null;
        const deleteButton = target instanceof HTMLElement ? target.closest('.governance-delete-item-policy-btn') : null;

        if (deleteButton) {
            openGovernanceItemPolicyDeleteModal(deleteButton.dataset.entityType, deleteButton.dataset.itemId);
            return;
        }

        if (!editButton) {
            return;
        }

        const policy = {
            entity_type: editButton.dataset.entityType || '',
            item_id: editButton.dataset.itemId || '',
            allow_all: editButton.dataset.allowAll === 'true',
            allowed_users: parseGovernancePrincipalDataset(editButton.dataset.allowedUsers),
            allowed_groups: parseGovernancePrincipalDataset(editButton.dataset.allowedGroups),
        };

        await loadGovernanceItemPolicyIntoEditor(policy);
        openCurrentDelegatedItemAllowListEditorAfterReviewModalCloses();
    });
}

function syncGovernanceItemReviewControls() {
    const searchInput = document.getElementById('governance-item-review-search');
    const entityTypeSelect = document.getElementById('governance-item-review-entity-type');
    const pageSizeSelect = document.getElementById('governance-item-review-page-size');

    if (searchInput) {
        searchInput.value = governanceItemReviewState.search;
    }
    if (entityTypeSelect) {
        entityTypeSelect.value = governanceItemReviewState.entityType;
    }
    if (pageSizeSelect) {
        pageSizeSelect.value = String(governanceItemReviewState.perPage);
    }
}

function renderGovernanceItemReviewRows(itemPolicies) {
    const tbody = document.getElementById('governance-item-policies-review-body');
    if (!tbody) {
        return;
    }

    tbody.innerHTML = '';
    if (!Array.isArray(itemPolicies) || itemPolicies.length === 0) {
        const emptyRow = document.createElement('tr');
        const emptyCell = document.createElement('td');
        emptyCell.colSpan = 6;
        emptyCell.className = 'text-center text-muted';
        emptyCell.textContent = 'No delegated item policies found.';
        emptyRow.appendChild(emptyCell);
        tbody.appendChild(emptyRow);
        return;
    }

    itemPolicies.forEach((policy) => {
        tbody.appendChild(buildItemPolicyRow(policy));
    });
}

function updateGovernanceItemReviewSummary(pagination, totalVisible) {
    const summary = document.getElementById('governance-item-review-summary');
    if (!summary) {
        return;
    }

    if (!pagination) {
        summary.textContent = '';
        return;
    }

    const currentStart = pagination.total_items === 0 ? 0 : ((pagination.page - 1) * pagination.per_page) + 1;
    const currentEnd = pagination.total_items === 0 ? 0 : Math.min(pagination.page * pagination.per_page, pagination.total_items);
    summary.textContent = `Showing ${currentStart}-${currentEnd} of ${pagination.total_items} configured item policy${pagination.total_items === 1 ? '' : 'ies'} (${totalVisible} on page ${pagination.page} of ${pagination.total_pages}).`;
}

function updateGovernanceItemReviewPagination(pagination) {
    const prevButton = document.getElementById('governance-item-review-prev-btn');
    const nextButton = document.getElementById('governance-item-review-next-btn');

    if (prevButton) {
        prevButton.disabled = !pagination || !pagination.has_prev;
    }
    if (nextButton) {
        nextButton.disabled = !pagination || !pagination.has_next;
    }
}

async function loadGovernanceItemPolicyReview(page = governanceItemReviewState.page) {
    const tbody = document.getElementById('governance-item-policies-review-body');
    if (!tbody) {
        return;
    }

    governanceItemReviewState.page = Math.max(1, Number(page) || 1);

    const params = new URLSearchParams();
    if (governanceItemReviewState.search) {
        params.set('search', governanceItemReviewState.search);
    }
    if (governanceItemReviewState.entityType) {
        params.set('entity_type', governanceItemReviewState.entityType);
    }
    params.set('page', String(governanceItemReviewState.page));
    params.set('per_page', String(governanceItemReviewState.perPage));

    const response = await fetch(`/api/admin/governance/item-policies/review?${params.toString()}`, {
        method: 'GET',
        headers: {
            Accept: 'application/json',
        },
    });

    if (!response.ok) {
        throw new Error('Unable to load delegated item policy review data.');
    }

    const payload = await response.json();
    const itemPolicies = Array.isArray(payload.item_policies) ? payload.item_policies : [];
    renderGovernanceItemReviewRows(itemPolicies);
    updateGovernanceItemReviewSummary(payload.pagination, itemPolicies.length);
    updateGovernanceItemReviewPagination(payload.pagination);
}

function openGovernanceItemReviewModal() {
    const modalElement = ensureGovernanceItemReviewModal();
    if (!modalElement) {
        return;
    }

    if (!governanceItemReviewModal) {
        governanceItemReviewModal = bootstrap.Modal.getOrCreateInstance(modalElement);
    }

    governanceItemReviewState.page = 1;
    syncGovernanceItemReviewControls();
    governanceItemReviewModal.show();
    loadGovernanceItemPolicyReview().catch((error) => {
        setGovernanceStatus(error.message || 'Failed to load delegated item policy review.', 'danger');
    });
}

function ensureGovernanceAllowListEditorModal() {
    let modalElement = document.getElementById('governanceAllowListEditorModal');
    if (!modalElement) {
        const modalMarkup = `
            <div class="modal fade" id="governanceAllowListEditorModal" tabindex="-1" aria-hidden="true">
                <div class="modal-dialog modal-xl modal-dialog-scrollable">
                    <div class="modal-content">
                        <div class="modal-header">
                            <div>
                                <h5 class="modal-title mb-1" id="governance-allowlist-editor-title">Edit Allow List</h5>
                                <div class="small text-muted">Use lookup and CSV import to manage users/groups. Saving updates the underlying policy fields.</div>
                            </div>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <div class="alert alert-info py-2 small mb-3" id="governance-allowlist-editor-context"></div>

                            <div class="row g-3">
                                <div class="col-lg-6">
                                    <h6 class="mb-2">User Lookup</h6>
                                    <div class="input-group mb-2">
                                        <input type="search" class="form-control" id="governance-allowlist-user-search" placeholder="Search users by name or email">
                                        <button type="button" class="btn btn-outline-primary" id="governance-allowlist-user-search-btn">Search</button>
                                    </div>
                                    <div class="table-responsive border rounded">
                                        <table class="table table-sm align-middle mb-0">
                                            <thead>
                                                <tr>
                                                    <th style="width: 40px;"><input type="checkbox" id="governance-allowlist-select-all-user-results"></th>
                                                    <th>User</th>
                                                    <th>Email</th>
                                                </tr>
                                            </thead>
                                            <tbody id="governance-allowlist-user-results"></tbody>
                                        </table>
                                    </div>
                                    <div class="d-flex justify-content-end mt-2">
                                        <button type="button" class="btn btn-sm btn-primary" id="governance-allowlist-add-selected-users-btn">Add Selected Users</button>
                                    </div>
                                </div>

                                <div class="col-lg-6">
                                    <h6 class="mb-2">Group Lookup</h6>
                                    <div class="input-group mb-2">
                                        <input type="search" class="form-control" id="governance-allowlist-group-search" placeholder="Search groups by name">
                                        <button type="button" class="btn btn-outline-primary" id="governance-allowlist-group-search-btn">Search</button>
                                    </div>
                                    <div class="table-responsive border rounded">
                                        <table class="table table-sm align-middle mb-0">
                                            <thead>
                                                <tr>
                                                    <th style="width: 40px;"><input type="checkbox" id="governance-allowlist-select-all-group-results"></th>
                                                    <th>Group</th>
                                                    <th>Group ID</th>
                                                </tr>
                                            </thead>
                                            <tbody id="governance-allowlist-group-results"></tbody>
                                        </table>
                                    </div>
                                    <div class="d-flex justify-content-end mt-2">
                                        <button type="button" class="btn btn-sm btn-primary" id="governance-allowlist-add-selected-groups-btn">Add Selected Groups</button>
                                    </div>
                                </div>
                            </div>

                            <hr>

                            <div class="row g-3">
                                <div class="col-lg-6">
                                    <h6 class="mb-2">Selected Users</h6>
                                    <div class="row g-2 align-items-end mb-2">
                                        <div class="col-8">
                                            <label class="form-label small mb-1" for="governance-allowlist-selected-user-search">Find in Selected Users</label>
                                            <input type="search" class="form-control form-control-sm" id="governance-allowlist-selected-user-search" placeholder="Filter by user ID">
                                        </div>
                                        <div class="col-4">
                                            <label class="form-label small mb-1" for="governance-allowlist-selected-user-page-size">Page Size</label>
                                            <select class="form-select form-select-sm" id="governance-allowlist-selected-user-page-size">
                                                <option value="10">10</option>
                                                <option value="25">25</option>
                                                <option value="50" selected>50</option>
                                                <option value="100">100</option>
                                            </select>
                                        </div>
                                    </div>
                                    <div class="table-responsive border rounded" style="max-height: 260px; overflow-y: auto;">
                                        <table class="table table-sm align-middle mb-0">
                                            <thead>
                                                <tr>
                                                    <th style="width: 40px;"><input type="checkbox" id="governance-allowlist-select-all-selected-users"></th>
                                                    <th>User</th>
                                                    <th style="width: 40px;"></th>
                                                </tr>
                                            </thead>
                                            <tbody id="governance-allowlist-selected-users"></tbody>
                                        </table>
                                    </div>
                                    <div class="d-flex align-items-center justify-content-between mt-2">
                                        <div class="small text-muted" id="governance-allowlist-selected-users-summary"></div>
                                        <div class="btn-group btn-group-sm" role="group" aria-label="Selected users pagination">
                                            <button type="button" class="btn btn-outline-secondary" id="governance-allowlist-selected-users-prev-btn">Previous</button>
                                            <button type="button" class="btn btn-outline-secondary" id="governance-allowlist-selected-users-next-btn">Next</button>
                                        </div>
                                    </div>
                                    <div class="d-flex justify-content-end mt-2 gap-2">
                                        <button type="button" class="btn btn-sm btn-outline-danger" id="governance-allowlist-remove-selected-users-btn">Remove Selected</button>
                                        <button type="button" class="btn btn-sm btn-outline-secondary" id="governance-allowlist-clear-users-btn">Clear Users</button>
                                    </div>
                                </div>

                                <div class="col-lg-6">
                                    <h6 class="mb-2">Selected Groups</h6>
                                    <div class="row g-2 align-items-end mb-2">
                                        <div class="col-8">
                                            <label class="form-label small mb-1" for="governance-allowlist-selected-group-search">Find in Selected Groups</label>
                                            <input type="search" class="form-control form-control-sm" id="governance-allowlist-selected-group-search" placeholder="Filter by group ID">
                                        </div>
                                        <div class="col-4">
                                            <label class="form-label small mb-1" for="governance-allowlist-selected-group-page-size">Page Size</label>
                                            <select class="form-select form-select-sm" id="governance-allowlist-selected-group-page-size">
                                                <option value="10">10</option>
                                                <option value="25">25</option>
                                                <option value="50" selected>50</option>
                                                <option value="100">100</option>
                                            </select>
                                        </div>
                                    </div>
                                    <div class="table-responsive border rounded" style="max-height: 260px; overflow-y: auto;">
                                        <table class="table table-sm align-middle mb-0">
                                            <thead>
                                                <tr>
                                                    <th style="width: 40px;"><input type="checkbox" id="governance-allowlist-select-all-selected-groups"></th>
                                                    <th>Group</th>
                                                    <th style="width: 40px;"></th>
                                                </tr>
                                            </thead>
                                            <tbody id="governance-allowlist-selected-groups"></tbody>
                                        </table>
                                    </div>
                                    <div class="d-flex align-items-center justify-content-between mt-2">
                                        <div class="small text-muted" id="governance-allowlist-selected-groups-summary"></div>
                                        <div class="btn-group btn-group-sm" role="group" aria-label="Selected groups pagination">
                                            <button type="button" class="btn btn-outline-secondary" id="governance-allowlist-selected-groups-prev-btn">Previous</button>
                                            <button type="button" class="btn btn-outline-secondary" id="governance-allowlist-selected-groups-next-btn">Next</button>
                                        </div>
                                    </div>
                                    <div class="d-flex justify-content-end mt-2 gap-2">
                                        <button type="button" class="btn btn-sm btn-outline-danger" id="governance-allowlist-remove-selected-groups-btn">Remove Selected</button>
                                        <button type="button" class="btn btn-sm btn-outline-secondary" id="governance-allowlist-clear-groups-btn">Clear Groups</button>
                                    </div>
                                </div>
                            </div>

                            <hr>

                            <div>
                                <h6 class="mb-2">CSV Import</h6>
                                <div class="row g-2 align-items-end">
                                    <div class="col-md-3">
                                        <label class="form-label" for="governance-allowlist-csv-target">Target</label>
                                        <select class="form-select" id="governance-allowlist-csv-target">
                                            <option value="users">Users</option>
                                            <option value="groups">Groups</option>
                                        </select>
                                    </div>
                                    <div class="col-md-3">
                                        <label class="form-label" for="governance-allowlist-csv-mode">Mode</label>
                                        <select class="form-select" id="governance-allowlist-csv-mode">
                                            <option value="merge">Merge</option>
                                            <option value="replace">Replace</option>
                                        </select>
                                    </div>
                                    <div class="col-md-6 d-grid">
                                        <button type="button" class="btn btn-outline-primary" id="governance-allowlist-csv-apply-btn">Apply CSV</button>
                                    </div>
                                </div>
                                <textarea class="form-control mt-2" id="governance-allowlist-csv-input" rows="4" placeholder="Paste one ID per line or comma-separated IDs"></textarea>
                                <div class="form-text">Use this for quick bulk updates when IDs are already known.</div>
                            </div>

                            <div class="small text-muted mt-3" id="governance-allowlist-editor-status"></div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-primary" id="governance-allowlist-save-btn">Apply to Policy</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const wrapper = document.createElement('div');
        wrapper.innerHTML = modalMarkup.trim();
        modalElement = wrapper.firstElementChild;
        document.body.appendChild(modalElement);
    }

    if (!governanceAllowListEditorModal) {
        governanceAllowListEditorModal = bootstrap.Modal.getOrCreateInstance(modalElement);
    }

    if (!modalElement.dataset.wired) {
        modalElement.dataset.wired = 'true';
        wireGovernanceAllowListEditorHandlers();
    }

    return modalElement;
}

function setGovernanceAllowListEditorStatus(message) {
    const normalizedMessage = String(message || '').trim();
    if (!normalizedMessage) {
        return;
    }

    let variant = 'info';
    if (/failed|error|unable/i.test(normalizedMessage)) {
        variant = 'danger';
    } else if (/no\s+csv|enter\s+a\s+user\s+search/i.test(normalizedMessage)) {
        variant = 'warning';
    } else if (/added|removed|cleared|completed|updated/i.test(normalizedMessage)) {
        variant = 'success';
    }

    showGovernanceToast(normalizedMessage, variant);
}

function normalizeGovernanceAllowListPageSize(value) {
    const parsed = Number(value) || GOVERNANCE_ALLOWLIST_PAGE_SIZE_DEFAULT;
    return GOVERNANCE_ALLOWLIST_PAGE_SIZES.includes(parsed) ? parsed : GOVERNANCE_ALLOWLIST_PAGE_SIZE_DEFAULT;
}

function resetGovernanceAllowListSelectionViewState() {
    governanceAllowListSelectionViewState.users.search = '';
    governanceAllowListSelectionViewState.users.page = 1;
    governanceAllowListSelectionViewState.users.pageSize = GOVERNANCE_ALLOWLIST_PAGE_SIZE_DEFAULT;

    governanceAllowListSelectionViewState.groups.search = '';
    governanceAllowListSelectionViewState.groups.page = 1;
    governanceAllowListSelectionViewState.groups.pageSize = GOVERNANCE_ALLOWLIST_PAGE_SIZE_DEFAULT;
}

function syncGovernanceAllowListSelectionControls() {
    const userSearchInput = document.getElementById('governance-allowlist-selected-user-search');
    const userPageSizeSelect = document.getElementById('governance-allowlist-selected-user-page-size');
    const groupSearchInput = document.getElementById('governance-allowlist-selected-group-search');
    const groupPageSizeSelect = document.getElementById('governance-allowlist-selected-group-page-size');

    if (userSearchInput) {
        userSearchInput.value = governanceAllowListSelectionViewState.users.search;
    }
    if (userPageSizeSelect) {
        userPageSizeSelect.value = String(governanceAllowListSelectionViewState.users.pageSize);
    }
    if (groupSearchInput) {
        groupSearchInput.value = governanceAllowListSelectionViewState.groups.search;
    }
    if (groupPageSizeSelect) {
        groupPageSizeSelect.value = String(governanceAllowListSelectionViewState.groups.pageSize);
    }
}

function getGovernanceSelectedIdsByType(listType) {
    if (!governanceAllowListEditorContext) {
        return [];
    }
    if (listType === 'groups') {
        return Array.isArray(governanceAllowListEditorContext.workingGroups) ? governanceAllowListEditorContext.workingGroups : [];
    }
    return Array.isArray(governanceAllowListEditorContext.workingUsers) ? governanceAllowListEditorContext.workingUsers : [];
}

function getFilteredGovernanceSelectedIds(listType) {
    const allIds = getGovernanceSelectedIdsByType(listType);
    const state = governanceAllowListSelectionViewState[listType];
    const searchValue = String(state?.search || '').trim().toLowerCase();
    if (!searchValue) {
        return allIds;
    }
    return allIds.filter((value) => {
        const idText = String(value || '').toLowerCase();
        const displayName = String(getGovernanceDisplayName(listType, value) || '').toLowerCase();
        return idText.includes(searchValue) || displayName.includes(searchValue);
    });
}

function truncateGovernanceId(idValue, maxLength = GOVERNANCE_ALLOWLIST_TRUNCATE_ID_LENGTH) {
    const str = String(idValue || '');
    if (str.length <= maxLength) {
        return str;
    }
    return str.substring(0, maxLength - 1) + '…';
}

function getGovernanceDisplayName(listType, idValue) {
    const cache = governanceAllowListDisplayNameCache[listType] || {};
    return cache[idValue] || null;
}

function setGovernanceDisplayName(listType, idValue, displayName) {
    if (!governanceAllowListDisplayNameCache[listType]) {
        governanceAllowListDisplayNameCache[listType] = {};
    }
    governanceAllowListDisplayNameCache[listType][idValue] = String(displayName || '').trim();
}

function buildGovernanceUserLabel(user) {
    const upn = String(user?.userPrincipalName || user?.mail || user?.email || '').trim();
    const displayName = String(user?.displayName || user?.display_name || upn || '(no name)').trim();
    if (upn && upn.toLowerCase() !== displayName.toLowerCase()) {
        return `${displayName} (${upn})`;
    }
    return displayName;
}

async function resolveGovernanceUserLabelById(userId) {
    try {
        const users = await governanceLookupUsers(userId);
        const matchedUser = (Array.isArray(users) ? users : []).find((user) => String(user?.id || '').trim() === userId);
        if (matchedUser) {
            return buildGovernanceUserLabel(matchedUser);
        }
    } catch {
        // Fall back to local user info below.
    }

    try {
        const response = await fetch(`/api/user/info/${encodeURIComponent(userId)}`, {
            method: 'GET',
            headers: { Accept: 'application/json' },
        });
        if (!response.ok) {
            return '';
        }
        const payload = await response.json();
        return buildGovernanceUserLabel(payload || {});
    } catch {
        return '';
    }
}

async function resolveGovernanceGroupLabelById(groupId) {
    try {
        const groups = await governanceLookupGroups(groupId);
        const matchedGroup = (Array.isArray(groups) ? groups : []).find((group) => String(group?.id || '').trim() === groupId);
        if (!matchedGroup) {
            return '';
        }
        return String(matchedGroup.name || 'Unnamed Group').trim();
    } catch {
        return '';
    }
}

async function hydrateGovernanceDisplayNames(listType, ids) {
    const normalizedIds = uniquePrincipalList(ids);
    if (normalizedIds.length === 0) {
        return;
    }

    const inFlight = governanceAllowListHydrationState[listType] || new Set();
    const missingIds = normalizedIds.filter((idValue) => {
        return idValue && !getGovernanceDisplayName(listType, idValue) && !inFlight.has(idValue);
    });

    if (missingIds.length === 0) {
        return;
    }

    missingIds.forEach((idValue) => inFlight.add(idValue));
    governanceAllowListHydrationState[listType] = inFlight;

    let hasUpdates = false;
    await Promise.all(missingIds.map(async (idValue) => {
        try {
            const resolvedLabel = listType === 'users'
                ? await resolveGovernanceUserLabelById(idValue)
                : await resolveGovernanceGroupLabelById(idValue);

            if (resolvedLabel) {
                setGovernanceDisplayName(listType, idValue, resolvedLabel);
                hasUpdates = true;
            }
        } finally {
            inFlight.delete(idValue);
        }
    }));

    if (hasUpdates && governanceAllowListEditorContext) {
        renderGovernanceAllowListEditorSelections();
    }
}

function renderGovernanceSelectedList(options) {
    const {
        listType,
        containerId,
        checkboxClass,
        emptyMessage,
        summaryId,
        prevButtonId,
        nextButtonId,
    } = options;

    const tbody = document.getElementById(containerId);
    const summary = document.getElementById(summaryId);
    const prevButton = document.getElementById(prevButtonId);
    const nextButton = document.getElementById(nextButtonId);
    const state = governanceAllowListSelectionViewState[listType];

    if (!tbody || !state) {
        return;
    }

    const filteredIds = getFilteredGovernanceSelectedIds(listType);
    const pageSize = normalizeGovernanceAllowListPageSize(state.pageSize);
    state.pageSize = pageSize;
    const totalItems = filteredIds.length;
    const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
    state.page = Math.min(Math.max(1, state.page), totalPages);
    const startIndex = (state.page - 1) * pageSize;
    const visibleIds = filteredIds.slice(startIndex, startIndex + pageSize);

    tbody.innerHTML = '';
    if (visibleIds.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 3;
        cell.className = 'text-center text-muted';
        cell.textContent = emptyMessage;
        row.appendChild(cell);
        tbody.appendChild(row);
    } else {
        visibleIds.forEach((idValue) => {
            const row = document.createElement('tr');

            const checkCell = document.createElement('td');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = checkboxClass;
            checkbox.value = idValue;
            checkCell.appendChild(checkbox);

            const displayName = getGovernanceDisplayName(listType, idValue);
            const truncatedId = truncateGovernanceId(idValue);
            const displayText = displayName ? `${displayName} (${truncatedId})` : truncatedId;

            const infoCell = document.createElement('td');
            infoCell.className = 'small';
            infoCell.textContent = displayText;
            infoCell.title = idValue;

            const copyCell = document.createElement('td');
            copyCell.className = 'text-center';
            const copyButton = document.createElement('button');
            copyButton.type = 'button';
            copyButton.className = 'btn btn-sm btn-link p-0';
            copyButton.innerHTML = '<i class="bi bi-clipboard"></i>';
            copyButton.title = 'Copy ID';
            copyButton.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const originalHtml = copyButton.innerHTML;
                navigator.clipboard.writeText(idValue).then(() => {
                    copyButton.innerHTML = '<i class="bi bi-check"></i>';
                    setTimeout(() => {
                        copyButton.innerHTML = originalHtml;
                    }, 1500);
                }).catch(() => {
                    copyButton.innerHTML = '<i class="bi bi-x"></i>';
                    setTimeout(() => {
                        copyButton.innerHTML = originalHtml;
                    }, 1500);
                });
            });
            copyCell.appendChild(copyButton);

            row.appendChild(checkCell);
            row.appendChild(infoCell);
            row.appendChild(copyCell);
            tbody.appendChild(row);
        });
    }

    if (summary) {
        const viewStart = totalItems === 0 ? 0 : startIndex + 1;
        const viewEnd = totalItems === 0 ? 0 : Math.min(startIndex + visibleIds.length, totalItems);
        summary.textContent = `Showing ${viewStart}-${viewEnd} of ${totalItems} selected (${state.page}/${totalPages}).`;
    }

    if (prevButton) {
        prevButton.disabled = state.page <= 1 || totalItems === 0;
    }
    if (nextButton) {
        nextButton.disabled = state.page >= totalPages || totalItems === 0;
    }
}

function renderPrincipalIdRows(containerId, ids, checkboxClass, emptyMessage) {
    const tbody = document.getElementById(containerId);
    if (!tbody) {
        return;
    }

    tbody.innerHTML = '';
    if (!Array.isArray(ids) || ids.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 2;
        cell.className = 'text-center text-muted';
        cell.textContent = emptyMessage;
        row.appendChild(cell);
        tbody.appendChild(row);
        return;
    }

    ids.forEach((idValue) => {
        const row = document.createElement('tr');

        const checkCell = document.createElement('td');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = checkboxClass;
        checkbox.value = idValue;
        checkCell.appendChild(checkbox);

        const idCell = document.createElement('td');
        idCell.textContent = idValue;

        row.appendChild(checkCell);
        row.appendChild(idCell);
        tbody.appendChild(row);
    });
}

function renderGovernanceAllowListEditorSelections() {
    if (!governanceAllowListEditorContext) {
        return;
    }

    const users = uniquePrincipalList(governanceAllowListEditorContext.workingUsers);
    const groups = uniquePrincipalList(governanceAllowListEditorContext.workingGroups);

    void hydrateGovernanceDisplayNames('users', users);
    void hydrateGovernanceDisplayNames('groups', groups);

    renderGovernanceSelectedList({
        listType: 'users',
        containerId: 'governance-allowlist-selected-users',
        checkboxClass: 'governance-selected-user-checkbox',
        emptyMessage: 'No users selected.',
        summaryId: 'governance-allowlist-selected-users-summary',
        prevButtonId: 'governance-allowlist-selected-users-prev-btn',
        nextButtonId: 'governance-allowlist-selected-users-next-btn',
    });
    renderGovernanceSelectedList({
        listType: 'groups',
        containerId: 'governance-allowlist-selected-groups',
        checkboxClass: 'governance-selected-group-checkbox',
        emptyMessage: 'No groups selected.',
        summaryId: 'governance-allowlist-selected-groups-summary',
        prevButtonId: 'governance-allowlist-selected-groups-prev-btn',
        nextButtonId: 'governance-allowlist-selected-groups-next-btn',
    });
}

function renderGovernanceAllowListUserResults(users) {
    const tbody = document.getElementById('governance-allowlist-user-results');
    if (!tbody) {
        return;
    }

    tbody.innerHTML = '';
    if (!Array.isArray(users) || users.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 3;
        cell.className = 'text-center text-muted';
        cell.textContent = 'No users found.';
        row.appendChild(cell);
        tbody.appendChild(row);
        return;
    }

    users.forEach((user) => {
        const userId = String(user.id || '').trim();
        const upn = String(user.userPrincipalName || user.mail || user.email || '').trim();
        const displayName = String(user.displayName || upn || '(no name)').trim();
        const userLabel = buildGovernanceUserLabel(user);

        if (userId && userLabel) {
            setGovernanceDisplayName('users', userId, userLabel);
        }

        const row = document.createElement('tr');

        const selectCell = document.createElement('td');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'governance-user-result-checkbox';
        checkbox.value = userId;
        checkbox.dataset.displayLabel = userLabel;
        selectCell.appendChild(checkbox);

        const userCell = document.createElement('td');
        userCell.textContent = displayName;

        const emailCell = document.createElement('td');
        emailCell.textContent = upn;

        row.appendChild(selectCell);
        row.appendChild(userCell);
        row.appendChild(emailCell);
        tbody.appendChild(row);
    });
}

function renderGovernanceAllowListGroupResults(groups) {
    const tbody = document.getElementById('governance-allowlist-group-results');
    if (!tbody) {
        return;
    }

    tbody.innerHTML = '';
    if (!Array.isArray(groups) || groups.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 3;
        cell.className = 'text-center text-muted';
        cell.textContent = 'No groups found.';
        row.appendChild(cell);
        tbody.appendChild(row);
        return;
    }

    groups.forEach((group) => {
        const groupId = String(group.id || '').trim();
        const groupName = String(group.name || 'Unnamed Group');

        if (groupId && groupName) {
            setGovernanceDisplayName('groups', groupId, groupName);
        }

        const row = document.createElement('tr');

        const selectCell = document.createElement('td');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'governance-group-result-checkbox';
        checkbox.value = groupId;
        checkbox.dataset.displayLabel = groupName;
        selectCell.appendChild(checkbox);

        const nameCell = document.createElement('td');
        nameCell.textContent = groupName;

        const idCell = document.createElement('td');
        idCell.textContent = groupId;

        row.appendChild(selectCell);
        row.appendChild(nameCell);
        row.appendChild(idCell);
        tbody.appendChild(row);
    });
}

async function loadGovernanceAllowListUserResults() {
    const searchInput = document.getElementById('governance-allowlist-user-search');
    const query = String(searchInput?.value || '').trim();
    if (!query) {
        setGovernanceAllowListEditorStatus('Enter a user search term.');
        renderGovernanceAllowListUserResults([]);
        return;
    }

    const users = await governanceLookupUsers(query);
    renderGovernanceAllowListUserResults(users);
    renderGovernanceAllowListEditorSelections();
    setGovernanceAllowListEditorStatus('User results updated.');
}

async function loadGovernanceAllowListGroupResults() {
    const searchInput = document.getElementById('governance-allowlist-group-search');
    const query = String(searchInput?.value || '').trim();

    const groups = await governanceLookupGroups(query);
    renderGovernanceAllowListGroupResults(groups);
    renderGovernanceAllowListEditorSelections();
    setGovernanceAllowListEditorStatus('Group results updated.');
}

function applyGovernanceAllowListToContext() {
    if (!governanceAllowListEditorContext) {
        return;
    }

    const users = uniquePrincipalList(governanceAllowListEditorContext.workingUsers);
    const groups = uniquePrincipalList(governanceAllowListEditorContext.workingGroups);
    governanceAllowListEditorContext.setValues(users, groups);
    governanceAllowListEditorModal?.hide();
}

function openGovernanceAllowListEditor(context) {
    if (!context || typeof context.getUsers !== 'function' || typeof context.getGroups !== 'function' || typeof context.setValues !== 'function') {
        return;
    }

    ensureGovernanceAllowListEditorModal();

    governanceAllowListEditorContext = {
        ...context,
        workingUsers: uniquePrincipalList(context.getUsers()),
        workingGroups: uniquePrincipalList(context.getGroups()),
    };

    const title = document.getElementById('governance-allowlist-editor-title');
    const contextAlert = document.getElementById('governance-allowlist-editor-context');
    const userSearchInput = document.getElementById('governance-allowlist-user-search');
    const groupSearchInput = document.getElementById('governance-allowlist-group-search');
    const csvInput = document.getElementById('governance-allowlist-csv-input');

    if (title) {
        title.textContent = context.title || 'Edit Allow List';
    }
    if (contextAlert) {
        contextAlert.textContent = context.description || 'Manage users and groups that are explicitly allowed for this policy.';
    }
    if (userSearchInput) {
        userSearchInput.value = '';
    }
    if (groupSearchInput) {
        groupSearchInput.value = '';
    }
    if (csvInput) {
        csvInput.value = '';
    }

    resetGovernanceAllowListSelectionViewState();
    syncGovernanceAllowListSelectionControls();

    renderGovernanceAllowListUserResults([]);
    renderGovernanceAllowListGroupResults([]);
    renderGovernanceAllowListEditorSelections();
    setGovernanceAllowListEditorStatus('');

    governanceAllowListEditorModal?.show();
}

function readCheckedValues(selector) {
    return Array.from(document.querySelectorAll(selector))
        .filter((input) => input instanceof HTMLInputElement && input.checked)
        .map((input) => String(input.value || '').trim())
        .filter((value) => value);
}

function toggleCheckboxes(selector, checked) {
    Array.from(document.querySelectorAll(selector)).forEach((input) => {
        if (input instanceof HTMLInputElement) {
            input.checked = checked;
        }
    });
}

function removeCheckedFromList(list, checkedValues) {
    const valuesToRemove = new Set((checkedValues || []).map((value) => String(value || '').trim()));
    return (Array.isArray(list) ? list : []).filter((value) => !valuesToRemove.has(String(value || '').trim()));
}

function wireGovernanceAllowListEditorHandlers() {
    const userSearchButton = document.getElementById('governance-allowlist-user-search-btn');
    if (userSearchButton) {
        userSearchButton.addEventListener('click', async () => {
            try {
                await loadGovernanceAllowListUserResults();
            } catch (error) {
                setGovernanceAllowListEditorStatus(error.message || 'Failed to load user results.');
            }
        });
    }

    const groupSearchButton = document.getElementById('governance-allowlist-group-search-btn');
    if (groupSearchButton) {
        groupSearchButton.addEventListener('click', async () => {
            try {
                await loadGovernanceAllowListGroupResults();
            } catch (error) {
                setGovernanceAllowListEditorStatus(error.message || 'Failed to load group results.');
            }
        });
    }

    const addSelectedUsersButton = document.getElementById('governance-allowlist-add-selected-users-btn');
    if (addSelectedUsersButton) {
        addSelectedUsersButton.addEventListener('click', () => {
            if (!governanceAllowListEditorContext) {
                return;
            }
            const selectedUserIds = readCheckedValues('.governance-user-result-checkbox');
            selectedUserIds.forEach((userId) => {
                const userCheckbox = Array.from(document.querySelectorAll('.governance-user-result-checkbox')).find(
                    (checkbox) => checkbox.value === userId
                );
                const displayLabel = String(userCheckbox?.dataset.displayLabel || '').trim();
                if (displayLabel) {
                    setGovernanceDisplayName('users', userId, displayLabel);
                }
            });
            governanceAllowListEditorContext.workingUsers = uniquePrincipalList([...governanceAllowListEditorContext.workingUsers, ...selectedUserIds]);
            renderGovernanceAllowListEditorSelections();
            setGovernanceAllowListEditorStatus(`Added ${selectedUserIds.length} user${selectedUserIds.length === 1 ? '' : 's'}.`);
        });
    }

    const addSelectedGroupsButton = document.getElementById('governance-allowlist-add-selected-groups-btn');
    if (addSelectedGroupsButton) {
        addSelectedGroupsButton.addEventListener('click', () => {
            if (!governanceAllowListEditorContext) {
                return;
            }
            const selectedGroupIds = readCheckedValues('.governance-group-result-checkbox');
            selectedGroupIds.forEach((groupId) => {
                const groupCheckbox = Array.from(document.querySelectorAll('.governance-group-result-checkbox')).find(
                    (checkbox) => checkbox.value === groupId
                );
                const displayLabel = String(groupCheckbox?.dataset.displayLabel || '').trim();
                if (displayLabel) {
                    setGovernanceDisplayName('groups', groupId, displayLabel);
                }
            });
            governanceAllowListEditorContext.workingGroups = uniquePrincipalList([...governanceAllowListEditorContext.workingGroups, ...selectedGroupIds]);
            renderGovernanceAllowListEditorSelections();
            setGovernanceAllowListEditorStatus(`Added ${selectedGroupIds.length} group${selectedGroupIds.length === 1 ? '' : 's'}.`);
        });
    }

    const removeSelectedUsersButton = document.getElementById('governance-allowlist-remove-selected-users-btn');
    if (removeSelectedUsersButton) {
        removeSelectedUsersButton.addEventListener('click', () => {
            if (!governanceAllowListEditorContext) {
                return;
            }
            const selectedUserIds = readCheckedValues('.governance-selected-user-checkbox');
            governanceAllowListEditorContext.workingUsers = removeCheckedFromList(governanceAllowListEditorContext.workingUsers, selectedUserIds);
            renderGovernanceAllowListEditorSelections();
            setGovernanceAllowListEditorStatus(`Removed ${selectedUserIds.length} user${selectedUserIds.length === 1 ? '' : 's'}.`);
        });
    }

    const removeSelectedGroupsButton = document.getElementById('governance-allowlist-remove-selected-groups-btn');
    if (removeSelectedGroupsButton) {
        removeSelectedGroupsButton.addEventListener('click', () => {
            if (!governanceAllowListEditorContext) {
                return;
            }
            const selectedGroupIds = readCheckedValues('.governance-selected-group-checkbox');
            governanceAllowListEditorContext.workingGroups = removeCheckedFromList(governanceAllowListEditorContext.workingGroups, selectedGroupIds);
            renderGovernanceAllowListEditorSelections();
            setGovernanceAllowListEditorStatus(`Removed ${selectedGroupIds.length} group${selectedGroupIds.length === 1 ? '' : 's'}.`);
        });
    }

    const clearUsersButton = document.getElementById('governance-allowlist-clear-users-btn');
    if (clearUsersButton) {
        clearUsersButton.addEventListener('click', () => {
            if (!governanceAllowListEditorContext) {
                return;
            }
            governanceAllowListEditorContext.workingUsers = [];
            renderGovernanceAllowListEditorSelections();
            setGovernanceAllowListEditorStatus('Cleared selected users.');
        });
    }

    const clearGroupsButton = document.getElementById('governance-allowlist-clear-groups-btn');
    if (clearGroupsButton) {
        clearGroupsButton.addEventListener('click', () => {
            if (!governanceAllowListEditorContext) {
                return;
            }
            governanceAllowListEditorContext.workingGroups = [];
            renderGovernanceAllowListEditorSelections();
            setGovernanceAllowListEditorStatus('Cleared selected groups.');
        });
    }

    const csvApplyButton = document.getElementById('governance-allowlist-csv-apply-btn');
    if (csvApplyButton) {
        csvApplyButton.addEventListener('click', () => {
            if (!governanceAllowListEditorContext) {
                return;
            }

            const targetSelect = document.getElementById('governance-allowlist-csv-target');
            const modeSelect = document.getElementById('governance-allowlist-csv-mode');
            const csvInput = document.getElementById('governance-allowlist-csv-input');
            const target = String(targetSelect?.value || 'users');
            const mode = String(modeSelect?.value || 'merge');
            const importedValues = uniquePrincipalList(parseCsvPrincipalLines(csvInput?.value || ''));

            if (importedValues.length === 0) {
                setGovernanceAllowListEditorStatus('No CSV values detected.');
                return;
            }

            if (target === 'groups') {
                governanceAllowListEditorContext.workingGroups = mode === 'replace'
                    ? importedValues
                    : uniquePrincipalList([...governanceAllowListEditorContext.workingGroups, ...importedValues]);
            } else {
                governanceAllowListEditorContext.workingUsers = mode === 'replace'
                    ? importedValues
                    : uniquePrincipalList([...governanceAllowListEditorContext.workingUsers, ...importedValues]);
            }

            renderGovernanceAllowListEditorSelections();
            setGovernanceAllowListEditorStatus(`CSV ${mode} completed for ${target}. Imported ${importedValues.length} ID${importedValues.length === 1 ? '' : 's'}.`);
        });
    }

    const saveButton = document.getElementById('governance-allowlist-save-btn');
    if (saveButton) {
        saveButton.addEventListener('click', () => {
            applyGovernanceAllowListToContext();
        });
    }

    const selectedUserSearchInput = document.getElementById('governance-allowlist-selected-user-search');
    if (selectedUserSearchInput) {
        selectedUserSearchInput.addEventListener('input', () => {
            governanceAllowListSelectionViewState.users.search = String(selectedUserSearchInput.value || '').trim();
            governanceAllowListSelectionViewState.users.page = 1;
            renderGovernanceAllowListEditorSelections();
        });
    }

    const selectedGroupSearchInput = document.getElementById('governance-allowlist-selected-group-search');
    if (selectedGroupSearchInput) {
        selectedGroupSearchInput.addEventListener('input', () => {
            governanceAllowListSelectionViewState.groups.search = String(selectedGroupSearchInput.value || '').trim();
            governanceAllowListSelectionViewState.groups.page = 1;
            renderGovernanceAllowListEditorSelections();
        });
    }

    const selectedUserPageSizeSelect = document.getElementById('governance-allowlist-selected-user-page-size');
    if (selectedUserPageSizeSelect) {
        selectedUserPageSizeSelect.addEventListener('change', () => {
            governanceAllowListSelectionViewState.users.pageSize = normalizeGovernanceAllowListPageSize(selectedUserPageSizeSelect.value);
            governanceAllowListSelectionViewState.users.page = 1;
            renderGovernanceAllowListEditorSelections();
        });
    }

    const selectedGroupPageSizeSelect = document.getElementById('governance-allowlist-selected-group-page-size');
    if (selectedGroupPageSizeSelect) {
        selectedGroupPageSizeSelect.addEventListener('change', () => {
            governanceAllowListSelectionViewState.groups.pageSize = normalizeGovernanceAllowListPageSize(selectedGroupPageSizeSelect.value);
            governanceAllowListSelectionViewState.groups.page = 1;
            renderGovernanceAllowListEditorSelections();
        });
    }

    const selectedUsersPrevButton = document.getElementById('governance-allowlist-selected-users-prev-btn');
    if (selectedUsersPrevButton) {
        selectedUsersPrevButton.addEventListener('click', () => {
            governanceAllowListSelectionViewState.users.page = Math.max(1, governanceAllowListSelectionViewState.users.page - 1);
            renderGovernanceAllowListEditorSelections();
        });
    }

    const selectedUsersNextButton = document.getElementById('governance-allowlist-selected-users-next-btn');
    if (selectedUsersNextButton) {
        selectedUsersNextButton.addEventListener('click', () => {
            governanceAllowListSelectionViewState.users.page += 1;
            renderGovernanceAllowListEditorSelections();
        });
    }

    const selectedGroupsPrevButton = document.getElementById('governance-allowlist-selected-groups-prev-btn');
    if (selectedGroupsPrevButton) {
        selectedGroupsPrevButton.addEventListener('click', () => {
            governanceAllowListSelectionViewState.groups.page = Math.max(1, governanceAllowListSelectionViewState.groups.page - 1);
            renderGovernanceAllowListEditorSelections();
        });
    }

    const selectedGroupsNextButton = document.getElementById('governance-allowlist-selected-groups-next-btn');
    if (selectedGroupsNextButton) {
        selectedGroupsNextButton.addEventListener('click', () => {
            governanceAllowListSelectionViewState.groups.page += 1;
            renderGovernanceAllowListEditorSelections();
        });
    }

    const selectAllMappings = [
        ['governance-allowlist-select-all-user-results', '.governance-user-result-checkbox'],
        ['governance-allowlist-select-all-group-results', '.governance-group-result-checkbox'],
        ['governance-allowlist-select-all-selected-users', '.governance-selected-user-checkbox'],
        ['governance-allowlist-select-all-selected-groups', '.governance-selected-group-checkbox'],
    ];

    selectAllMappings.forEach(([masterId, checkboxSelector]) => {
        const master = document.getElementById(masterId);
        if (!master) {
            return;
        }
        master.addEventListener('change', () => {
            toggleCheckboxes(checkboxSelector, master.checked);
        });
    });
}

async function loadItemPolicies() {
    const tbody = document.getElementById('governance-item-policies-body');
    if (!tbody) {
        return;
    }

    const response = await fetch('/api/admin/governance/item-policies', {
        method: 'GET',
        headers: {
            Accept: 'application/json',
        },
    });

    if (!response.ok) {
        throw new Error('Unable to load governance item policies.');
    }

    const payload = await response.json();
    const itemPolicies = Array.isArray(payload.item_policies) ? payload.item_policies : [];

    tbody.innerHTML = '';
    itemPolicies.forEach((policy) => {
        tbody.appendChild(buildItemPolicyRow(policy));
    });
}

async function saveItemPolicy(event) {
    if (event && typeof event.preventDefault === 'function') {
        event.preventDefault();
    }

    const entityTypeInput = document.getElementById('governance-item-entity-type');
    const itemIdInput = document.getElementById('governance-item-id');
    const allowAllInput = document.getElementById('governance-item-allow-all');
    const usersInput = document.getElementById('governance-item-users');
    const groupsInput = document.getElementById('governance-item-groups');

    if (!entityTypeInput || !itemIdInput || !allowAllInput || !usersInput || !groupsInput) {
        return;
    }

    const entityType = String(entityTypeInput.value || '').trim();
    const itemId = String(itemIdInput.value || '').trim();

    if (!entityType || !itemId) {
        setGovernanceStatus('Entity type and item ID are required for item governance policies.', 'warning');
        return;
    }

    const payload = {
        allow_all: allowAllInput.checked,
        allowed_users: allowAllInput.checked ? [] : splitPrincipalList(usersInput.value),
        allowed_groups: allowAllInput.checked ? [] : splitPrincipalList(groupsInput.value),
    };

    const response = await fetch(
        `/api/admin/governance/item-policies/${encodeURIComponent(entityType)}/${encodeURIComponent(itemId)}`,
        {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                Accept: 'application/json',
            },
            body: JSON.stringify(payload),
        }
    );

    if (!response.ok) {
        throw new Error('Unable to save item governance policy.');
    }

    await loadItemPolicies();
    const reviewModalElement = document.getElementById('governance-item-policies-review-modal');
    if (reviewModalElement?.classList.contains('show')) {
        await loadGovernanceItemPolicyReview();
    }
    updateItemAllowListSummary();
    clearGovernanceStatus();
    showGovernanceToast('Item governance policy saved successfully.', 'success');
}

function wireGovernanceHandlers() {
    Object.keys(GOVERNANCE_FEATURE_LABELS).forEach((featureKey) => {
        const featureToggle = getGovernanceFeatureToggle(featureKey);
        if (!featureToggle) {
            return;
        }
        featureToggle.addEventListener('change', () => {
            syncGovernanceFeaturePolicyVisibility();
        });
    });

    const featurePolicyTableBody = document.getElementById('governance-feature-policies-body');
    if (featurePolicyTableBody) {
        featurePolicyTableBody.addEventListener('change', (event) => {
            const target = event.target;
            if (!(target instanceof HTMLInputElement)) {
                return;
            }
            if (target.classList.contains('governance-allow-all')) {
                const row = target.closest('tr');
                applyFeatureAllowAllUiState(row);
            }
        });

        featurePolicyTableBody.addEventListener('click', (event) => {
            const target = event.target;
            const editButton = target instanceof HTMLElement ? target.closest('.governance-edit-feature-allowlist-btn') : null;
            if (!editButton) {
                return;
            }

            const row = editButton.closest('tr');
            const usersInput = getGovernanceUsersInputForFeatureRow(row);
            const groupsInput = getGovernanceGroupsInputForFeatureRow(row);
            const featureKey = String(row?.dataset?.featureKey || '').trim();
            if (!usersInput || !groupsInput || !featureKey) {
                return;
            }

            openGovernanceAllowListEditor({
                title: `Edit Allow List: ${GOVERNANCE_FEATURE_LABELS[featureKey] || featureKey}`,
                description: 'Manage explicitly allowed users and groups for this feature policy.',
                getUsers: () => splitPrincipalList(usersInput.value),
                getGroups: () => splitPrincipalList(groupsInput.value),
                setValues: (users, groups) => {
                    usersInput.value = joinPrincipalList(users);
                    groupsInput.value = joinPrincipalList(groups);
                    const allowAllInput = getGovernanceFeatureAllowAllInput(row);
                    if (allowAllInput) {
                        allowAllInput.checked = false;
                    }
                    applyFeatureAllowAllUiState(row);
                },
            });
        });
    }

    const saveFeaturePoliciesButton = document.getElementById('governance-save-feature-policies-btn');
    if (saveFeaturePoliciesButton) {
        saveFeaturePoliciesButton.addEventListener('click', async () => {
            clearGovernanceStatus();
            try {
                await saveFeaturePolicies();
            } catch (error) {
                setGovernanceStatus(error.message || 'Failed to save feature policies.', 'danger');
            }
        });
    }

    const saveItemPolicyButton = document.getElementById('governance-save-item-policy-btn');
    if (saveItemPolicyButton) {
        saveItemPolicyButton.addEventListener('click', async (event) => {
            clearGovernanceStatus();
            try {
                await saveItemPolicy(event);
            } catch (error) {
                setGovernanceStatus(error.message || 'Failed to save item policy.', 'danger');
            }
        });
    }

    const itemEntityTypeInput = getItemEntityTypeInput();
    if (itemEntityTypeInput) {
        itemEntityTypeInput.addEventListener('change', async () => {
            const entityType = String(itemEntityTypeInput.value || '').trim();
            await refreshGovernanceItemLookup(entityType, false, '');
        });
    }

    const itemLookupRefreshButton = document.getElementById('governance-item-id-refresh-btn');
    if (itemLookupRefreshButton) {
        itemLookupRefreshButton.addEventListener('click', async () => {
            const entityType = String(getItemEntityTypeInput()?.value || '').trim();
            await refreshGovernanceItemLookup(entityType, true, String(getItemIdInput()?.value || '').trim());
        });
    }

    const itemAllowAllInput = getItemAllowAllInput();
    if (itemAllowAllInput) {
        itemAllowAllInput.addEventListener('change', () => {
            applyItemAllowAllUiState();
        });
    }

    const itemEditAllowListButton = document.getElementById('governance-edit-item-allowlist-btn');
    if (itemEditAllowListButton) {
        itemEditAllowListButton.addEventListener('click', () => {
            const usersInput = getItemUsersInput();
            const groupsInput = getItemGroupsInput();
            const entityTypeInput = document.getElementById('governance-item-entity-type');
            const itemIdInput = document.getElementById('governance-item-id');

            if (!usersInput || !groupsInput) {
                return;
            }

            const entityType = String(entityTypeInput?.value || '').trim();
            const itemId = String(itemIdInput?.value || '').trim();
            const contextSuffix = entityType && itemId
                ? ` (${GOVERNANCE_ITEM_ENTITY_LABELS[entityType] || entityType}: ${itemId})`
                : '';

            openGovernanceAllowListEditor({
                title: `Edit Delegated Item Allow List${contextSuffix}`,
                description: 'Manage explicitly allowed users and groups for this delegated item policy.',
                getUsers: () => splitPrincipalList(usersInput.value),
                getGroups: () => splitPrincipalList(groupsInput.value),
                setValues: (users, groups) => {
                    usersInput.value = joinPrincipalList(users);
                    groupsInput.value = joinPrincipalList(groups);
                    const allowAllInput = getItemAllowAllInput();
                    if (allowAllInput) {
                        allowAllInput.checked = false;
                    }
                    applyItemAllowAllUiState();
                },
            });
        });
    }

    const refreshItemPoliciesButton = document.getElementById('governance-refresh-item-policies-btn');
    if (refreshItemPoliciesButton) {
        refreshItemPoliciesButton.addEventListener('click', async () => {
            clearGovernanceStatus();
            try {
                await loadItemPolicies();
                setGovernanceStatus('Item governance policies refreshed.', 'info');
            } catch (error) {
                setGovernanceStatus(error.message || 'Failed to refresh item policies.', 'danger');
            }
        });
    }

    const reviewItemPoliciesButton = document.getElementById('governance-review-item-policies-btn');
    if (reviewItemPoliciesButton) {
        reviewItemPoliciesButton.addEventListener('click', () => {
            clearGovernanceStatus();
            openGovernanceItemReviewModal();
        });
    }

    const reviewSearchButton = document.getElementById('governance-item-review-search-btn');
    if (reviewSearchButton) {
        reviewSearchButton.addEventListener('click', async () => {
            const searchInput = document.getElementById('governance-item-review-search');
            const entityTypeSelect = document.getElementById('governance-item-review-entity-type');
            const pageSizeSelect = document.getElementById('governance-item-review-page-size');
            governanceItemReviewState.search = String(searchInput?.value || '').trim();
            governanceItemReviewState.entityType = String(entityTypeSelect?.value || '').trim();
            governanceItemReviewState.perPage = Math.max(1, Number(pageSizeSelect?.value || GOVERNANCE_ITEM_REVIEW_DEFAULT_PAGE_SIZE) || GOVERNANCE_ITEM_REVIEW_DEFAULT_PAGE_SIZE);
            governanceItemReviewState.page = 1;
            syncGovernanceItemReviewControls();
            try {
                await loadGovernanceItemPolicyReview();
            } catch (error) {
                setGovernanceStatus(error.message || 'Failed to search delegated item policies.', 'danger');
            }
        });
    }

    const reviewResetButton = document.getElementById('governance-item-review-reset-btn');
    if (reviewResetButton) {
        reviewResetButton.addEventListener('click', async () => {
            governanceItemReviewState.search = '';
            governanceItemReviewState.entityType = '';
            governanceItemReviewState.page = 1;
            governanceItemReviewState.perPage = GOVERNANCE_ITEM_REVIEW_DEFAULT_PAGE_SIZE;
            syncGovernanceItemReviewControls();
            try {
                await loadGovernanceItemPolicyReview();
            } catch (error) {
                setGovernanceStatus(error.message || 'Failed to reset delegated item policy filters.', 'danger');
            }
        });
    }

    const reviewPrevButton = document.getElementById('governance-item-review-prev-btn');
    if (reviewPrevButton) {
        reviewPrevButton.addEventListener('click', async () => {
            if (governanceItemReviewState.page <= 1) {
                return;
            }
            governanceItemReviewState.page -= 1;
            syncGovernanceItemReviewControls();
            try {
                await loadGovernanceItemPolicyReview();
            } catch (error) {
                setGovernanceStatus(error.message || 'Failed to load previous delegated item policy page.', 'danger');
            }
        });
    }

    const reviewNextButton = document.getElementById('governance-item-review-next-btn');
    if (reviewNextButton) {
        reviewNextButton.addEventListener('click', async () => {
            governanceItemReviewState.page += 1;
            syncGovernanceItemReviewControls();
            try {
                await loadGovernanceItemPolicyReview();
            } catch (error) {
                setGovernanceStatus(error.message || 'Failed to load next delegated item policy page.', 'danger');
            }
        });
    }
}

async function initializeGovernanceTab() {
    if (!document.getElementById('governance')) {
        return;
    }

    wireGovernanceHandlers();
    clearGovernanceStatus();

    ensureGovernanceItemReviewModal();
    ensureGovernanceAllowListEditorModal();

    try {
        await loadFeaturePolicies();
        await loadItemPolicies();
        const initialEntityType = String(getItemEntityTypeInput()?.value || 'global_agent').trim();
        await refreshGovernanceItemLookup(initialEntityType, false, String(getItemIdInput()?.value || '').trim());
        applyItemAllowAllUiState();
    } catch (error) {
        setGovernanceStatus(error.message || 'Unable to initialize governance settings.', 'danger');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initializeGovernanceTab();
});
