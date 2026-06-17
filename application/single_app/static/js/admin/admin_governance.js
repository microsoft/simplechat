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
    global_endpoint: 'Global Endpoint',
    global_agent: 'Global Agent',
    global_action: 'Global Action',
    personal_action_type: 'Personal Action Type',
    group_action_type: 'Group Action Type',
    global_action_type: 'Global Action Type',
};

const GOVERNANCE_ITEM_LOOKUP_HINTS = {
    global_endpoint: 'Select an endpoint configured in Admin Settings.',
    global_agent: 'Select a global agent available for delegation.',
    global_action: 'Select a global action available for delegation.',
    personal_action_type: 'Select an action type users can create and use in personal workspaces.',
    group_action_type: 'Select an action type groups can create and use in group workspaces.',
    global_action_type: 'Select an action type users can use from configured global actions.',
};

const GOVERNANCE_ACTION_TYPE_ALIASES = {
    sql_query: 'sql',
    sql_schema: 'sql',
    sql: 'sql',
    simple_chat: 'simplechat',
    simplechat: 'simplechat',
    open_api: 'openapi',
    openapi: 'openapi',
    model_context_protocol: 'mcp',
    mcp: 'mcp',
    microsoft_graph: 'msgraph',
    msgraph: 'msgraph',
    databricks_table: 'databricks',
    databricks: 'databricks',
    tableau: 'tableau',
    chart: 'chart',
    azure_maps: 'azure_maps',
    blob_storage: 'blob_storage',
    document_search: 'document_search',
    search: 'document_search',
};

const GOVERNANCE_ACTION_TYPE_LABELS = {
    sql: 'SQL',
    simplechat: 'SimpleChat',
    openapi: 'OpenAPI',
    mcp: 'MCP',
    msgraph: 'Microsoft Graph',
    databricks: 'Databricks',
    tableau: 'Tableau',
    chart: 'Chart',
    azure_maps: 'Azure Maps',
    blob_storage: 'Blob Storage',
    document_search: 'Document Search',
};

const GOVERNANCE_PRIMARY_TOGGLE_MAP = {
    governance_user_endpoints: 'toggle-allow-user-custom-endpoints',
    governance_group_endpoints: 'toggle-allow-group-custom-endpoints',
    governance_user_agents: 'toggle-allow-user-agents',
    governance_group_agents: 'toggle-allow-group-agents',
    governance_global_agents_usage: 'toggle-enable-agents-agents',
    governance_user_actions: 'toggle-allow-user-plugins',
    governance_group_actions: 'toggle-allow-group-plugins',
    governance_global_actions_usage: 'toggle-enable-agents-agents',
};

const GOVERNANCE_ALLOWLIST_PAGE_SIZE_DEFAULT = 50;
const GOVERNANCE_ALLOWLIST_PAGE_SIZES = [10, 25, 50, 100];
const GOVERNANCE_ALLOWLIST_TRUNCATE_ID_LENGTH = 35;

const GOVERNANCE_ITEM_REVIEW_DEFAULT_PAGE_SIZE = 25;
const GOVERNANCE_ITEM_EDITOR_PAGE_SIZE_DEFAULT = 50;

const governanceItemReviewState = {
    search: '',
    entityType: '',
    page: 1,
    perPage: GOVERNANCE_ITEM_REVIEW_DEFAULT_PAGE_SIZE,
};

let governanceAllowListEditorModal = null;
let governanceAllowListEditorContext = null;
let governanceItemPolicyDeleteModal = null;
let governanceItemPolicyDeleteContext = null;
let governanceItemPolicyEditorModal = null;
const governanceItemLookupState = {
    global_endpoint: [],
    global_agent: [],
    global_action: [],
    personal_action_type: [],
    group_action_type: [],
    global_action_type: [],
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

const governanceItemEditorSelectionViewState = {
    users: {
        search: '',
        page: 1,
        pageSize: GOVERNANCE_ITEM_EDITOR_PAGE_SIZE_DEFAULT,
    },
    groups: {
        search: '',
        page: 1,
        pageSize: GOVERNANCE_ITEM_EDITOR_PAGE_SIZE_DEFAULT,
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

function setBootstrapIcon(element, iconClass) {
    element.replaceChildren();
    const icon = document.createElement('i');
    icon.className = iconClass;
    element.appendChild(icon);
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

function buildAllowListSummary(users, groups, allowAll = false) {
    const usersCount = Array.isArray(users) ? users.length : 0;
    const groupsCount = Array.isArray(groups) ? groups.length : 0;
    if (allowAll) {
        return 'All users and groups allowed';
    }
    if (usersCount === 0 && groupsCount === 0) {
        return 'No users or groups allowed';
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

function getItemPolicyIdInput() {
    return document.getElementById('governance-item-policy-id');
}

function getItemPolicyNameInput() {
    return document.getElementById('governance-item-policy-name');
}

function getItemResourceLabelInput() {
    return document.getElementById('governance-item-resource-label');
}

function getItemLookupFilterInput() {
    return document.getElementById('governance-item-id-filter');
}

function buildDefaultItemPolicyName(entityType, itemId, resourceLabel = '') {
    const label = String(resourceLabel || itemId || 'Resource').trim();
    const entityLabel = buildItemPolicyEntityLabel(entityType) || 'Delegated Item';
    return `${label} ${entityLabel} Policy`;
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

function normalizeGovernanceActionType(actionType) {
    const normalizedType = String(actionType || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    return GOVERNANCE_ACTION_TYPE_ALIASES[normalizedType] || normalizedType;
}

function buildGovernanceActionTypeLabel(actionType, fallbackLabel = '') {
    const normalizedType = normalizeGovernanceActionType(actionType);
    if (!normalizedType) {
        return fallbackLabel || 'Unknown Action Type';
    }
    return GOVERNANCE_ACTION_TYPE_LABELS[normalizedType] || fallbackLabel || normalizedType.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

async function fetchAdminActionTypeLookupOptions() {
    const response = await fetch('/api/admin/plugins/types', {
        method: 'GET',
        headers: {
            Accept: 'application/json',
        },
    });

    if (!response.ok) {
        throw new Error('Unable to load action type lookup.');
    }

    const payload = await response.json();
    const optionsByType = new Map();
    (Array.isArray(payload) ? payload : []).forEach((actionType) => {
        const rawType = actionType?.type;
        const normalizedType = normalizeGovernanceActionType(rawType);
        if (!normalizedType || optionsByType.has(normalizedType)) {
            return;
        }
        optionsByType.set(normalizedType, normalizeGovernanceLookupOption({
            value: normalizedType,
            label: buildGovernanceActionTypeLabel(normalizedType, actionType?.display || rawType),
            subtitle: actionType?.description || rawType || '',
        }, 'Action Type'));
    });
    return Array.from(optionsByType.values()).filter((option) => option !== null);
}

async function loadGovernanceItemLookup(entityType, forceReload = false) {
    const normalizedEntityType = normalizeGovernanceItemEntityType(entityType);
    if (!normalizedEntityType) {
        return [];
    }

    if (!forceReload && Array.isArray(governanceItemLookupState[normalizedEntityType]) && governanceItemLookupState[normalizedEntityType].length > 0) {
        return governanceItemLookupState[normalizedEntityType];
    }

    if (normalizedEntityType === 'global_endpoint') {
        governanceItemLookupState.global_endpoint = getAdminEndpointLookupOptionsFromWindow();
        return governanceItemLookupState.global_endpoint;
    }
    if (normalizedEntityType === 'global_agent') {
        governanceItemLookupState.global_agent = await fetchAdminGlobalAgentLookupOptions();
        return governanceItemLookupState.global_agent;
    }
    if (normalizedEntityType === 'global_action') {
        governanceItemLookupState.global_action = await fetchAdminGlobalActionLookupOptions();
        return governanceItemLookupState.global_action;
    }
    if (['personal_action_type', 'group_action_type', 'global_action_type'].includes(normalizedEntityType)) {
        governanceItemLookupState[normalizedEntityType] = await fetchAdminActionTypeLookupOptions();
        return governanceItemLookupState[normalizedEntityType];
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
    const filterValue = String(getItemLookupFilterInput()?.value || '').trim().toLowerCase();
    const visibleOptions = filterValue
        ? options.filter((option) => {
            const optionText = `${option.value || ''} ${option.label || ''} ${option.subtitle || ''}`.toLowerCase();
            return optionText.includes(filterValue);
        })
        : options;

    itemIdInput.innerHTML = '';

    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = visibleOptions.length > 0 ? 'Select an item' : 'No items available';
    itemIdInput.appendChild(placeholder);

    visibleOptions.forEach((option) => {
        itemIdInput.appendChild(buildGovernanceItemLookupOption(option));
    });

    if (currentValue && visibleOptions.some((option) => option.value === currentValue)) {
        itemIdInput.value = currentValue;
    } else {
        itemIdInput.value = '';
    }

    const hint = GOVERNANCE_ITEM_LOOKUP_HINTS[entityType] || 'Select a delegated item.';
    if (options.length > 0) {
        const filterSummary = filterValue ? ` Showing ${visibleOptions.length} of ${options.length}.` : '';
        setGovernanceItemLookupStatus(`${hint} Loaded ${options.length} item${options.length === 1 ? '' : 's'}.${filterSummary}`, 'muted');
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
    summaryEl.textContent = buildAllowListSummary(users, groups, getGovernanceFeatureAllowAllInput(row)?.checked);
}

function updateItemAllowListSummary() {
    const usersInput = getItemUsersInput();
    const groupsInput = getItemGroupsInput();
    const summaryInput = document.getElementById('governance-item-allowlist-summary');
    if (!usersInput || !groupsInput || !summaryInput) {
        return;
    }

    summaryInput.value = buildAllowListSummary(
        splitPrincipalList(usersInput.value),
        splitPrincipalList(groupsInput.value),
        getItemAllowAllInput()?.checked,
    );
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

    if (allowedPrincipalsControls) {
        allowedPrincipalsControls.classList.toggle('d-none', allowAllInput.checked);
    }

    updateItemAllowListSummary();
    renderGovernanceItemEditorSelections();
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
    const normalizedEntityType = normalizeGovernanceItemEntityType(entityType);
    return GOVERNANCE_ITEM_ENTITY_LABELS[normalizedEntityType] || normalizedEntityType || '';
}

function normalizeGovernanceItemEntityType(entityType) {
    const normalizedEntityType = String(entityType || '').trim();
    return normalizedEntityType === 'endpoint' ? 'global_endpoint' : normalizedEntityType;
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

function isGovernanceFeatureApplicable(featureKey) {
    if (featureKey === 'governance_global_endpoints') {
        return true;
    }

    const primaryToggleId = GOVERNANCE_PRIMARY_TOGGLE_MAP[featureKey];
    if (!primaryToggleId) {
        return true;
    }

    const primaryToggle = document.getElementById(primaryToggleId);
    if (!(primaryToggle instanceof HTMLInputElement)) {
        return true;
    }

    return primaryToggle.checked;
}

function syncGovernanceFeatureToggleVisibility() {
    Object.keys(GOVERNANCE_FEATURE_LABELS).forEach((featureKey) => {
        const featureToggle = getGovernanceFeatureToggle(featureKey);
        const wrapper = featureToggle?.closest('.form-check');
        if (!wrapper) {
            return;
        }

        const isApplicable = isGovernanceFeatureApplicable(featureKey);
        const isLocked = featureToggle.dataset.governanceLocked === 'true';
        wrapper.classList.remove('d-none');
        wrapper.classList.toggle('text-body-secondary', !isApplicable);
        if (!isLocked) {
            featureToggle.disabled = !isApplicable;
        }
        if (isApplicable) {
            wrapper.removeAttribute('title');
        } else {
            wrapper.title = 'Enable the matching primary feature before governance can be enforced for this scope.';
        }
    });
}

function syncGovernanceFeaturePolicyRowVisibility(row) {
    const featureKey = String(row?.dataset?.featureKey || '').trim();
    if (!row || !featureKey) {
        return;
    }

    const featureToggle = getGovernanceFeatureToggle(featureKey);
    const shouldShow = isGovernanceFeatureApplicable(featureKey) && (!featureToggle || featureToggle.checked);
    row.classList.toggle('d-none', !shouldShow);
}

function syncGovernanceFeaturePolicyVisibility() {
    syncGovernanceFeatureToggleVisibility();
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
    usersSummary.textContent = buildAllowListSummary(policy.allowed_users, policy.allowed_groups, allowAll.checked);
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

    const policyCell = document.createElement('td');
    const entityTypeCell = document.createElement('td');
    const entityType = normalizeGovernanceItemEntityType(policy.entity_type);
    const itemId = String(policy.item_id || '');
    const policyId = String(policy.policy_id || '');
    const resourceLabel = String(policy.resource_label || '').trim();
    const policyName = String(policy.policy_name || '').trim() || buildDefaultItemPolicyName(entityType, itemId, resourceLabel);
    const allowAll = Boolean(policy.allow_all);
    const allowedUsers = Array.isArray(policy.allowed_users) ? policy.allowed_users : [];
    const allowedGroups = Array.isArray(policy.allowed_groups) ? policy.allowed_groups : [];

    const policyNameEl = document.createElement('div');
    policyNameEl.className = 'fw-semibold';
    policyNameEl.textContent = policyName;
    policyCell.appendChild(policyNameEl);

    policyCell.title = policyId ? `Policy ID: ${policyId}` : policyName;

    entityTypeCell.textContent = buildItemPolicyEntityLabel(entityType);

    const itemIdCell = document.createElement('td');
    const itemLabelEl = document.createElement('div');
    itemLabelEl.textContent = resourceLabel || itemId;
    itemLabelEl.title = itemId;
    itemIdCell.appendChild(itemLabelEl);

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
    editButton.dataset.policyId = policyId;
    editButton.dataset.policyName = policyName;
    editButton.dataset.resourceLabel = resourceLabel;
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
    deleteButton.dataset.policyId = policyId;
    deleteButton.dataset.policyName = policyName;
    actionsCell.appendChild(deleteButton);

    row.appendChild(policyCell);
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

function ensureGovernanceItemIdOption(itemIdInput, itemId, label = '') {
    const normalizedItemId = String(itemId || '').trim();
    if (!itemIdInput || !normalizedItemId) {
        return;
    }

    const hasOption = Array.from(itemIdInput.options || []).some((option) => option.value === normalizedItemId);
    if (!hasOption) {
        const option = document.createElement('option');
        option.value = normalizedItemId;
        option.textContent = label ? `${label} (${truncateGovernanceId(normalizedItemId)})` : normalizedItemId;
        itemIdInput.appendChild(option);
    }
    itemIdInput.value = normalizedItemId;
}

function resetGovernanceItemEditorSelectionViewState() {
    governanceItemEditorSelectionViewState.users.search = '';
    governanceItemEditorSelectionViewState.users.page = 1;
    governanceItemEditorSelectionViewState.users.pageSize = GOVERNANCE_ITEM_EDITOR_PAGE_SIZE_DEFAULT;

    governanceItemEditorSelectionViewState.groups.search = '';
    governanceItemEditorSelectionViewState.groups.page = 1;
    governanceItemEditorSelectionViewState.groups.pageSize = GOVERNANCE_ITEM_EDITOR_PAGE_SIZE_DEFAULT;
}

function syncGovernanceItemEditorSelectionControls() {
    const userSearchInput = document.getElementById('governance-item-selected-user-search');
    const userPageSizeSelect = document.getElementById('governance-item-selected-user-page-size');
    const groupSearchInput = document.getElementById('governance-item-selected-group-search');
    const groupPageSizeSelect = document.getElementById('governance-item-selected-group-page-size');

    if (userSearchInput) {
        userSearchInput.value = governanceItemEditorSelectionViewState.users.search;
    }
    if (userPageSizeSelect) {
        userPageSizeSelect.value = String(governanceItemEditorSelectionViewState.users.pageSize);
    }
    if (groupSearchInput) {
        groupSearchInput.value = governanceItemEditorSelectionViewState.groups.search;
    }
    if (groupPageSizeSelect) {
        groupPageSizeSelect.value = String(governanceItemEditorSelectionViewState.groups.pageSize);
    }
}

function getGovernanceItemEditorSelectedIds(listType) {
    const input = listType === 'groups' ? getItemGroupsInput() : getItemUsersInput();
    return splitPrincipalList(input?.value || '');
}

function setGovernanceItemEditorSelectedIds(listType, values) {
    const input = listType === 'groups' ? getItemGroupsInput() : getItemUsersInput();
    if (!input) {
        return;
    }
    input.value = joinPrincipalList(uniquePrincipalList(values));
    updateItemAllowListSummary();
    renderGovernanceItemEditorSelections();
}

function getFilteredGovernanceItemEditorSelectedIds(listType) {
    const allIds = getGovernanceItemEditorSelectedIds(listType);
    const state = governanceItemEditorSelectionViewState[listType];
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

function setGovernanceItemEditorStatus(message, level = 'muted') {
    const status = document.getElementById('governance-item-editor-status');
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
    status.textContent = String(message || '');
}

function renderGovernanceItemEditorSelectedList(options) {
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
    const state = governanceItemEditorSelectionViewState[listType];

    if (!tbody || !state) {
        return;
    }

    const filteredIds = getFilteredGovernanceItemEditorSelectedIds(listType);
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
            setBootstrapIcon(copyButton, 'bi bi-clipboard');
            copyButton.title = 'Copy ID';
            copyButton.addEventListener('click', (event) => {
                event.preventDefault();
                event.stopPropagation();
                navigator.clipboard.writeText(idValue).then(() => {
                    setBootstrapIcon(copyButton, 'bi bi-check');
                    setTimeout(() => {
                        setBootstrapIcon(copyButton, 'bi bi-clipboard');
                    }, 1500);
                }).catch(() => {
                    setBootstrapIcon(copyButton, 'bi bi-x');
                    setTimeout(() => {
                        setBootstrapIcon(copyButton, 'bi bi-clipboard');
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

function renderGovernanceItemEditorSelections() {
    const users = getGovernanceItemEditorSelectedIds('users');
    const groups = getGovernanceItemEditorSelectedIds('groups');

    void hydrateGovernanceDisplayNames('users', users);
    void hydrateGovernanceDisplayNames('groups', groups);

    renderGovernanceItemEditorSelectedList({
        listType: 'users',
        containerId: 'governance-item-selected-users',
        checkboxClass: 'governance-item-selected-user-checkbox',
        emptyMessage: 'No users selected.',
        summaryId: 'governance-item-selected-users-summary',
        prevButtonId: 'governance-item-selected-users-prev-btn',
        nextButtonId: 'governance-item-selected-users-next-btn',
    });
    renderGovernanceItemEditorSelectedList({
        listType: 'groups',
        containerId: 'governance-item-selected-groups',
        checkboxClass: 'governance-item-selected-group-checkbox',
        emptyMessage: 'No groups selected.',
        summaryId: 'governance-item-selected-groups-summary',
        prevButtonId: 'governance-item-selected-groups-prev-btn',
        nextButtonId: 'governance-item-selected-groups-next-btn',
    });
}

async function openGovernanceItemPolicyEditor(policy = null) {
    const modalElement = ensureGovernanceItemPolicyEditorModal();
    if (!modalElement) {
        return;
    }

    const title = document.getElementById('governance-item-policy-editor-title');
    const policyIdInput = getItemPolicyIdInput();
    const policyNameInput = getItemPolicyNameInput();
    const resourceLabelInput = getItemResourceLabelInput();
    const entityTypeInput = getItemEntityTypeInput();
    const itemIdInput = getItemIdInput();
    const itemFilterInput = getItemLookupFilterInput();
    const allowAllInput = getItemAllowAllInput();
    const usersInput = getItemUsersInput();
    const groupsInput = getItemGroupsInput();

    if (!entityTypeInput || !itemIdInput || !allowAllInput || !usersInput || !groupsInput) {
        return;
    }

    const entityType = normalizeGovernanceItemEntityType(policy?.entity_type) || 'global_agent';
    const itemId = String(policy?.item_id || '').trim();
    const resourceLabel = String(policy?.resource_label || '').trim();
    const policyName = String(policy?.policy_name || '').trim() || buildDefaultItemPolicyName(entityType, itemId, resourceLabel);

    if (title) {
        title.textContent = policy?.policy_id ? 'Edit Delegated Item Policy' : 'New Delegated Item Policy';
    }
    if (itemFilterInput) {
        itemFilterInput.value = '';
    }

    entityTypeInput.value = entityType;
    if (policyIdInput) {
        policyIdInput.value = String(policy?.policy_id || '').trim();
    }
    if (policyNameInput) {
        policyNameInput.value = policyName;
    }
    if (resourceLabelInput) {
        resourceLabelInput.value = resourceLabel;
    }
    resetGovernanceItemEditorSelectionViewState();
    syncGovernanceItemEditorSelectionControls();
    renderGovernanceItemEditorUserResults([]);
    renderGovernanceItemEditorGroupResults([]);
    setGovernanceItemEditorStatus('');

    await refreshGovernanceItemLookup(entityType, false, itemId);
    ensureGovernanceItemIdOption(itemIdInput, itemId, resourceLabel);

    allowAllInput.checked = policy ? Boolean(policy.allow_all) : true;
    usersInput.value = joinPrincipalList(policy?.allowed_users || []);
    groupsInput.value = joinPrincipalList(policy?.allowed_groups || []);

    applyItemAllowAllUiState();
    governanceItemPolicyEditorModal?.show();
    itemIdInput.focus();
}

async function openGovernanceDelegatedItemEditorFromResource(options = {}) {
    const entityType = normalizeGovernanceItemEntityType(options.entityType || options.entity_type || '');
    const itemId = String(options.itemId || options.item_id || '').trim();
    const resourceLabel = String(options.resourceLabel || options.resource_label || '').trim();
    const policyName = String(options.policyName || options.policy_name || '').trim() || buildDefaultItemPolicyName(entityType, itemId, resourceLabel);

    if (!entityType || !itemId) {
        setGovernanceStatus('Unable to open delegated item policy editor without a resource ID.', 'warning');
        return;
    }

    if (typeof window.openAdminSettingsTab === 'function') {
        window.openAdminSettingsTab('#governance');
    }

    await openGovernanceItemPolicyEditor({
        entity_type: entityType,
        item_id: itemId,
        policy_name: policyName,
        resource_label: resourceLabel,
        allow_all: true,
        allowed_users: [],
        allowed_groups: [],
    });
}

window.openGovernanceDelegatedItemEditor = openGovernanceDelegatedItemEditorFromResource;

function ensureGovernanceItemPolicyEditorModal() {
    let modalElement = document.getElementById('governance-item-policy-editor-modal');
    if (!modalElement) {
        const modalMarkup = `
            <div class="modal fade" id="governance-item-policy-editor-modal" tabindex="-1" aria-hidden="true">
                <div class="modal-dialog modal-xl modal-dialog-scrollable">
                    <div class="modal-content">
                        <div class="modal-header">
                            <div>
                                <h5 class="modal-title mb-1" id="governance-item-policy-editor-title">Edit Delegated Item Policy</h5>
                                <div class="small text-muted">Choose the delegated item or action type, then search or bulk-load allowed users and groups.</div>
                            </div>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <div class="alert alert-info py-2 small" role="alert">
                                Delegated item policies are OR combined whitelists. Action type policies grant create/use entitlement for a type; global action policies grant access to one configured global action.
                            </div>
                            <div class="row g-3 mb-3">
                                <div class="col-lg-8">
                                    <label class="form-label" for="governance-item-policy-name">Policy Name</label>
                                    <input type="text" class="form-control" id="governance-item-policy-name" placeholder="Friendly name for this whitelist">
                                </div>
                                <div class="col-lg-4">
                                    <label class="form-label" for="governance-item-resource-label">Resource Label</label>
                                    <input type="text" class="form-control" id="governance-item-resource-label" placeholder="Shown in the policy list" readonly>
                                </div>
                            </div>
                            <div class="row g-3 align-items-start">
                                <div class="col-lg-3 col-md-4">
                                    <label class="form-label" for="governance-item-entity-type">Entity Type</label>
                                    <select class="form-select" id="governance-item-entity-type">
                                        <option value="global_agent" selected>Global Agent</option>
                                        <option value="global_action">Global Action</option>
                                        <option value="global_endpoint">Global Endpoint</option>
                                        <option value="personal_action_type">Personal Action Type</option>
                                        <option value="group_action_type">Group Action Type</option>
                                        <option value="global_action_type">Global Action Type</option>
                                    </select>
                                </div>
                                <div class="col-lg-6 col-md-8">
                                    <label class="form-label" for="governance-item-id-filter">Delegated Item</label>
                                    <input type="search" class="form-control mb-2" id="governance-item-id-filter" placeholder="Filter delegated items by name or ID">
                                    <div class="input-group">
                                        <select class="form-select" id="governance-item-id">
                                            <option value="">Loading items...</option>
                                        </select>
                                        <button type="button" class="btn btn-outline-secondary" id="governance-item-id-refresh-btn" title="Refresh lookup" aria-label="Refresh delegated item lookup">
                                            <i class="bi bi-arrow-clockwise"></i>
                                        </button>
                                    </div>
                                    <div class="form-text" id="governance-item-id-status">Choose an entity type to load available delegated items.</div>
                                </div>
                                <div class="col-lg-3 col-md-4">
                                    <label class="form-label" for="governance-item-allow-all">Access</label>
                                    <div class="border rounded px-3 py-2 bg-body h-100 d-flex align-items-center">
                                        <div class="form-check form-switch mb-0">
                                            <input class="form-check-input" type="checkbox" role="switch" id="governance-item-allow-all" checked>
                                            <label class="form-check-label ms-2" for="governance-item-allow-all">Allow All</label>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div class="mt-3">
                                <label class="form-label" for="governance-item-allowlist-summary">Allowed Principals</label>
                                <input type="text" class="form-control" id="governance-item-allowlist-summary" placeholder="No users or groups allowed" readonly>
                            </div>

                            <div class="mt-3 pt-3 border-top d-none" id="governance-item-allowed-principals-controls">
                                <div class="row g-3">
                                    <div class="col-lg-6">
                                        <h6 class="mb-2">User Lookup</h6>
                                        <div class="input-group mb-2">
                                            <input type="search" class="form-control" id="governance-item-user-search" placeholder="Search users by name or email">
                                            <button type="button" class="btn btn-outline-primary" id="governance-item-user-search-btn">Search</button>
                                        </div>
                                        <div class="table-responsive border rounded">
                                            <table class="table table-sm align-middle mb-0">
                                                <thead>
                                                    <tr>
                                                        <th style="width: 40px;"><input type="checkbox" id="governance-item-select-all-user-results"></th>
                                                        <th>User</th>
                                                        <th>Email</th>
                                                    </tr>
                                                </thead>
                                                <tbody id="governance-item-user-results"></tbody>
                                            </table>
                                        </div>
                                        <div class="d-flex justify-content-end mt-2">
                                            <button type="button" class="btn btn-sm btn-primary" id="governance-item-add-selected-users-btn">Add Selected Users</button>
                                        </div>
                                    </div>

                                    <div class="col-lg-6">
                                        <h6 class="mb-2">Group Lookup</h6>
                                        <div class="input-group mb-2">
                                            <input type="search" class="form-control" id="governance-item-group-search" placeholder="Search groups by name">
                                            <button type="button" class="btn btn-outline-primary" id="governance-item-group-search-btn">Search</button>
                                        </div>
                                        <div class="table-responsive border rounded">
                                            <table class="table table-sm align-middle mb-0">
                                                <thead>
                                                    <tr>
                                                        <th style="width: 40px;"><input type="checkbox" id="governance-item-select-all-group-results"></th>
                                                        <th>Group</th>
                                                        <th>Group ID</th>
                                                    </tr>
                                                </thead>
                                                <tbody id="governance-item-group-results"></tbody>
                                            </table>
                                        </div>
                                        <div class="d-flex justify-content-end mt-2">
                                            <button type="button" class="btn btn-sm btn-primary" id="governance-item-add-selected-groups-btn">Add Selected Groups</button>
                                        </div>
                                    </div>
                                </div>

                                <hr>

                                <div class="row g-3">
                                    <div class="col-lg-6">
                                        <h6 class="mb-2">Selected Users</h6>
                                        <div class="row g-2 align-items-end mb-2">
                                            <div class="col-8">
                                                <label class="form-label small mb-1" for="governance-item-selected-user-search">Find in Selected Users</label>
                                                <input type="search" class="form-control form-control-sm" id="governance-item-selected-user-search" placeholder="Filter by user ID or email">
                                            </div>
                                            <div class="col-4">
                                                <label class="form-label small mb-1" for="governance-item-selected-user-page-size">Page Size</label>
                                                <select class="form-select form-select-sm" id="governance-item-selected-user-page-size">
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
                                                        <th style="width: 40px;"><input type="checkbox" id="governance-item-select-all-selected-users"></th>
                                                        <th>User</th>
                                                        <th style="width: 40px;"></th>
                                                    </tr>
                                                </thead>
                                                <tbody id="governance-item-selected-users"></tbody>
                                            </table>
                                        </div>
                                        <div class="d-flex align-items-center justify-content-between mt-2">
                                            <div class="small text-muted" id="governance-item-selected-users-summary"></div>
                                            <div class="btn-group btn-group-sm" role="group" aria-label="Selected item users pagination">
                                                <button type="button" class="btn btn-outline-secondary" id="governance-item-selected-users-prev-btn">Previous</button>
                                                <button type="button" class="btn btn-outline-secondary" id="governance-item-selected-users-next-btn">Next</button>
                                            </div>
                                        </div>
                                        <div class="d-flex justify-content-end mt-2 gap-2">
                                            <button type="button" class="btn btn-sm btn-outline-danger" id="governance-item-remove-selected-users-btn">Remove Selected</button>
                                            <button type="button" class="btn btn-sm btn-outline-secondary" id="governance-item-clear-users-btn">Clear Users</button>
                                        </div>
                                    </div>

                                    <div class="col-lg-6">
                                        <h6 class="mb-2">Selected Groups</h6>
                                        <div class="row g-2 align-items-end mb-2">
                                            <div class="col-8">
                                                <label class="form-label small mb-1" for="governance-item-selected-group-search">Find in Selected Groups</label>
                                                <input type="search" class="form-control form-control-sm" id="governance-item-selected-group-search" placeholder="Filter by group ID or name">
                                            </div>
                                            <div class="col-4">
                                                <label class="form-label small mb-1" for="governance-item-selected-group-page-size">Page Size</label>
                                                <select class="form-select form-select-sm" id="governance-item-selected-group-page-size">
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
                                                        <th style="width: 40px;"><input type="checkbox" id="governance-item-select-all-selected-groups"></th>
                                                        <th>Group</th>
                                                        <th style="width: 40px;"></th>
                                                    </tr>
                                                </thead>
                                                <tbody id="governance-item-selected-groups"></tbody>
                                            </table>
                                        </div>
                                        <div class="d-flex align-items-center justify-content-between mt-2">
                                            <div class="small text-muted" id="governance-item-selected-groups-summary"></div>
                                            <div class="btn-group btn-group-sm" role="group" aria-label="Selected item groups pagination">
                                                <button type="button" class="btn btn-outline-secondary" id="governance-item-selected-groups-prev-btn">Previous</button>
                                                <button type="button" class="btn btn-outline-secondary" id="governance-item-selected-groups-next-btn">Next</button>
                                            </div>
                                        </div>
                                        <div class="d-flex justify-content-end mt-2 gap-2">
                                            <button type="button" class="btn btn-sm btn-outline-danger" id="governance-item-remove-selected-groups-btn">Remove Selected</button>
                                            <button type="button" class="btn btn-sm btn-outline-secondary" id="governance-item-clear-groups-btn">Clear Groups</button>
                                        </div>
                                    </div>
                                </div>

                                <hr>

                                <div>
                                    <h6 class="mb-2">CSV Import</h6>
                                    <div class="row g-2 align-items-end">
                                        <div class="col-md-3">
                                            <label class="form-label" for="governance-item-csv-target">Target</label>
                                            <select class="form-select" id="governance-item-csv-target">
                                                <option value="users">Users</option>
                                                <option value="groups">Groups</option>
                                            </select>
                                        </div>
                                        <div class="col-md-3">
                                            <label class="form-label" for="governance-item-csv-mode">Mode</label>
                                            <select class="form-select" id="governance-item-csv-mode">
                                                <option value="merge">Merge</option>
                                                <option value="replace">Replace</option>
                                            </select>
                                        </div>
                                        <div class="col-md-6 d-grid">
                                            <button type="button" class="btn btn-outline-primary" id="governance-item-csv-apply-btn">Apply CSV</button>
                                        </div>
                                    </div>
                                    <textarea class="form-control mt-2" id="governance-item-csv-input" rows="4" placeholder="Paste one ID per line or comma-separated IDs"></textarea>
                                    <div class="form-text">Use this for quick bulk updates when IDs are already known.</div>
                                </div>
                            </div>

                            <div class="small text-muted mt-3" id="governance-item-editor-status"></div>

                            <div class="d-none" aria-hidden="true">
                                <input type="text" class="form-control" id="governance-item-policy-id">
                                <input type="text" class="form-control" id="governance-item-users">
                                <input type="text" class="form-control" id="governance-item-groups">
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-primary" id="governance-save-item-policy-btn">Save Item Policy</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const wrapper = document.createElement('div');
    // xss-check: ignore - modalMarkup is a static Bootstrap shell; untrusted values are populated with DOM APIs.
        wrapper.innerHTML = modalMarkup.trim();
        modalElement = wrapper.firstElementChild;
        document.body.appendChild(modalElement);
    }

    if (!governanceItemPolicyEditorModal) {
        governanceItemPolicyEditorModal = bootstrap.Modal.getOrCreateInstance(modalElement);
    }

    if (!modalElement.dataset.wired) {
        modalElement.dataset.wired = 'true';
        wireGovernanceItemPolicyEditorHandlers(modalElement);
    }

    return modalElement;
}

function renderGovernanceItemEditorUserResults(users) {
    const tbody = document.getElementById('governance-item-user-results');
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
        checkbox.className = 'governance-item-user-result-checkbox';
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

function renderGovernanceItemEditorGroupResults(groups) {
    const tbody = document.getElementById('governance-item-group-results');
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
        checkbox.className = 'governance-item-group-result-checkbox';
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

async function loadGovernanceItemEditorUserResults() {
    const searchInput = document.getElementById('governance-item-user-search');
    const query = String(searchInput?.value || '').trim();
    if (!query) {
        setGovernanceItemEditorStatus('Enter a user search term.', 'warning');
        renderGovernanceItemEditorUserResults([]);
        return;
    }

    const users = await governanceLookupUsers(query);
    renderGovernanceItemEditorUserResults(users);
    renderGovernanceItemEditorSelections();
    setGovernanceItemEditorStatus('User results updated.', 'success');
}

async function loadGovernanceItemEditorGroupResults() {
    const searchInput = document.getElementById('governance-item-group-search');
    const query = String(searchInput?.value || '').trim();
    const groups = await governanceLookupGroups(query);
    renderGovernanceItemEditorGroupResults(groups);
    renderGovernanceItemEditorSelections();
    setGovernanceItemEditorStatus('Group results updated.', 'success');
}

function wireGovernanceItemPolicyEditorHandlers(modalElement) {
    const saveButton = modalElement.querySelector('#governance-save-item-policy-btn');
    if (saveButton) {
        saveButton.addEventListener('click', async (event) => {
            clearGovernanceStatus();
            try {
                await saveItemPolicy(event);
            } catch (error) {
                setGovernanceItemEditorStatus(error.message || 'Failed to save item policy.', 'danger');
                setGovernanceStatus(error.message || 'Failed to save item policy.', 'danger');
            }
        });
    }

    const entityTypeInput = modalElement.querySelector('#governance-item-entity-type');
    if (entityTypeInput) {
        entityTypeInput.addEventListener('change', async () => {
            const entityType = String(entityTypeInput.value || '').trim();
            const filterInput = getItemLookupFilterInput();
            if (filterInput) {
                filterInput.value = '';
            }
            await refreshGovernanceItemLookup(entityType, false, '');
        });
    }

    const itemLookupRefreshButton = modalElement.querySelector('#governance-item-id-refresh-btn');
    if (itemLookupRefreshButton) {
        itemLookupRefreshButton.addEventListener('click', async () => {
            const entityType = String(getItemEntityTypeInput()?.value || '').trim();
            await refreshGovernanceItemLookup(entityType, true, String(getItemIdInput()?.value || '').trim());
        });
    }

    const itemLookupFilterInput = modalElement.querySelector('#governance-item-id-filter');
    if (itemLookupFilterInput) {
        itemLookupFilterInput.addEventListener('input', () => {
            const entityType = String(getItemEntityTypeInput()?.value || '').trim();
            renderGovernanceItemLookupOptions(entityType, String(getItemIdInput()?.value || '').trim());
        });
    }

    const allowAllInput = modalElement.querySelector('#governance-item-allow-all');
    if (allowAllInput) {
        allowAllInput.addEventListener('change', () => {
            applyItemAllowAllUiState();
        });
    }

    const userSearchButton = modalElement.querySelector('#governance-item-user-search-btn');
    if (userSearchButton) {
        userSearchButton.addEventListener('click', async () => {
            try {
                await loadGovernanceItemEditorUserResults();
            } catch (error) {
                setGovernanceItemEditorStatus(error.message || 'Failed to load user results.', 'danger');
            }
        });
    }

    const groupSearchButton = modalElement.querySelector('#governance-item-group-search-btn');
    if (groupSearchButton) {
        groupSearchButton.addEventListener('click', async () => {
            try {
                await loadGovernanceItemEditorGroupResults();
            } catch (error) {
                setGovernanceItemEditorStatus(error.message || 'Failed to load group results.', 'danger');
            }
        });
    }

    const addSelectedUsersButton = modalElement.querySelector('#governance-item-add-selected-users-btn');
    if (addSelectedUsersButton) {
        addSelectedUsersButton.addEventListener('click', () => {
            const selectedUserIds = readCheckedValues('.governance-item-user-result-checkbox');
            selectedUserIds.forEach((userId) => {
                const userCheckbox = Array.from(document.querySelectorAll('.governance-item-user-result-checkbox')).find(
                    (checkbox) => checkbox.value === userId
                );
                const displayLabel = String(userCheckbox?.dataset.displayLabel || '').trim();
                if (displayLabel) {
                    setGovernanceDisplayName('users', userId, displayLabel);
                }
            });
            setGovernanceItemEditorSelectedIds('users', [...getGovernanceItemEditorSelectedIds('users'), ...selectedUserIds]);
            setGovernanceItemEditorStatus(`Added ${selectedUserIds.length} user${selectedUserIds.length === 1 ? '' : 's'}.`, 'success');
        });
    }

    const addSelectedGroupsButton = modalElement.querySelector('#governance-item-add-selected-groups-btn');
    if (addSelectedGroupsButton) {
        addSelectedGroupsButton.addEventListener('click', () => {
            const selectedGroupIds = readCheckedValues('.governance-item-group-result-checkbox');
            selectedGroupIds.forEach((groupId) => {
                const groupCheckbox = Array.from(document.querySelectorAll('.governance-item-group-result-checkbox')).find(
                    (checkbox) => checkbox.value === groupId
                );
                const displayLabel = String(groupCheckbox?.dataset.displayLabel || '').trim();
                if (displayLabel) {
                    setGovernanceDisplayName('groups', groupId, displayLabel);
                }
            });
            setGovernanceItemEditorSelectedIds('groups', [...getGovernanceItemEditorSelectedIds('groups'), ...selectedGroupIds]);
            setGovernanceItemEditorStatus(`Added ${selectedGroupIds.length} group${selectedGroupIds.length === 1 ? '' : 's'}.`, 'success');
        });
    }

    const removeSelectedUsersButton = modalElement.querySelector('#governance-item-remove-selected-users-btn');
    if (removeSelectedUsersButton) {
        removeSelectedUsersButton.addEventListener('click', () => {
            const selectedUserIds = readCheckedValues('.governance-item-selected-user-checkbox');
            setGovernanceItemEditorSelectedIds('users', removeCheckedFromList(getGovernanceItemEditorSelectedIds('users'), selectedUserIds));
            setGovernanceItemEditorStatus(`Removed ${selectedUserIds.length} user${selectedUserIds.length === 1 ? '' : 's'}.`, 'success');
        });
    }

    const removeSelectedGroupsButton = modalElement.querySelector('#governance-item-remove-selected-groups-btn');
    if (removeSelectedGroupsButton) {
        removeSelectedGroupsButton.addEventListener('click', () => {
            const selectedGroupIds = readCheckedValues('.governance-item-selected-group-checkbox');
            setGovernanceItemEditorSelectedIds('groups', removeCheckedFromList(getGovernanceItemEditorSelectedIds('groups'), selectedGroupIds));
            setGovernanceItemEditorStatus(`Removed ${selectedGroupIds.length} group${selectedGroupIds.length === 1 ? '' : 's'}.`, 'success');
        });
    }

    const clearUsersButton = modalElement.querySelector('#governance-item-clear-users-btn');
    if (clearUsersButton) {
        clearUsersButton.addEventListener('click', () => {
            setGovernanceItemEditorSelectedIds('users', []);
            setGovernanceItemEditorStatus('Cleared selected users.', 'success');
        });
    }

    const clearGroupsButton = modalElement.querySelector('#governance-item-clear-groups-btn');
    if (clearGroupsButton) {
        clearGroupsButton.addEventListener('click', () => {
            setGovernanceItemEditorSelectedIds('groups', []);
            setGovernanceItemEditorStatus('Cleared selected groups.', 'success');
        });
    }

    const csvApplyButton = modalElement.querySelector('#governance-item-csv-apply-btn');
    if (csvApplyButton) {
        csvApplyButton.addEventListener('click', () => {
            const targetSelect = document.getElementById('governance-item-csv-target');
            const modeSelect = document.getElementById('governance-item-csv-mode');
            const csvInput = document.getElementById('governance-item-csv-input');
            const target = String(targetSelect?.value || 'users');
            const mode = String(modeSelect?.value || 'merge');
            const importedValues = uniquePrincipalList(parseCsvPrincipalLines(csvInput?.value || ''));

            if (importedValues.length === 0) {
                setGovernanceItemEditorStatus('No CSV values detected.', 'warning');
                return;
            }

            const existingValues = getGovernanceItemEditorSelectedIds(target);
            const nextValues = mode === 'replace' ? importedValues : uniquePrincipalList([...existingValues, ...importedValues]);
            setGovernanceItemEditorSelectedIds(target, nextValues);
            setGovernanceItemEditorStatus(`CSV ${mode} completed for ${target}. Imported ${importedValues.length} ID${importedValues.length === 1 ? '' : 's'}.`, 'success');
        });
    }

    const selectedUserSearchInput = modalElement.querySelector('#governance-item-selected-user-search');
    if (selectedUserSearchInput) {
        selectedUserSearchInput.addEventListener('input', () => {
            governanceItemEditorSelectionViewState.users.search = String(selectedUserSearchInput.value || '').trim();
            governanceItemEditorSelectionViewState.users.page = 1;
            renderGovernanceItemEditorSelections();
        });
    }

    const selectedGroupSearchInput = modalElement.querySelector('#governance-item-selected-group-search');
    if (selectedGroupSearchInput) {
        selectedGroupSearchInput.addEventListener('input', () => {
            governanceItemEditorSelectionViewState.groups.search = String(selectedGroupSearchInput.value || '').trim();
            governanceItemEditorSelectionViewState.groups.page = 1;
            renderGovernanceItemEditorSelections();
        });
    }

    const selectedUserPageSizeSelect = modalElement.querySelector('#governance-item-selected-user-page-size');
    if (selectedUserPageSizeSelect) {
        selectedUserPageSizeSelect.addEventListener('change', () => {
            governanceItemEditorSelectionViewState.users.pageSize = normalizeGovernanceAllowListPageSize(selectedUserPageSizeSelect.value);
            governanceItemEditorSelectionViewState.users.page = 1;
            renderGovernanceItemEditorSelections();
        });
    }

    const selectedGroupPageSizeSelect = modalElement.querySelector('#governance-item-selected-group-page-size');
    if (selectedGroupPageSizeSelect) {
        selectedGroupPageSizeSelect.addEventListener('change', () => {
            governanceItemEditorSelectionViewState.groups.pageSize = normalizeGovernanceAllowListPageSize(selectedGroupPageSizeSelect.value);
            governanceItemEditorSelectionViewState.groups.page = 1;
            renderGovernanceItemEditorSelections();
        });
    }

    const selectedUsersPrevButton = modalElement.querySelector('#governance-item-selected-users-prev-btn');
    if (selectedUsersPrevButton) {
        selectedUsersPrevButton.addEventListener('click', () => {
            governanceItemEditorSelectionViewState.users.page = Math.max(1, governanceItemEditorSelectionViewState.users.page - 1);
            renderGovernanceItemEditorSelections();
        });
    }

    const selectedUsersNextButton = modalElement.querySelector('#governance-item-selected-users-next-btn');
    if (selectedUsersNextButton) {
        selectedUsersNextButton.addEventListener('click', () => {
            governanceItemEditorSelectionViewState.users.page += 1;
            renderGovernanceItemEditorSelections();
        });
    }

    const selectedGroupsPrevButton = modalElement.querySelector('#governance-item-selected-groups-prev-btn');
    if (selectedGroupsPrevButton) {
        selectedGroupsPrevButton.addEventListener('click', () => {
            governanceItemEditorSelectionViewState.groups.page = Math.max(1, governanceItemEditorSelectionViewState.groups.page - 1);
            renderGovernanceItemEditorSelections();
        });
    }

    const selectedGroupsNextButton = modalElement.querySelector('#governance-item-selected-groups-next-btn');
    if (selectedGroupsNextButton) {
        selectedGroupsNextButton.addEventListener('click', () => {
            governanceItemEditorSelectionViewState.groups.page += 1;
            renderGovernanceItemEditorSelections();
        });
    }

    const selectAllMappings = [
        ['governance-item-select-all-user-results', '.governance-item-user-result-checkbox'],
        ['governance-item-select-all-group-results', '.governance-item-group-result-checkbox'],
        ['governance-item-select-all-selected-users', '.governance-item-selected-user-checkbox'],
        ['governance-item-select-all-selected-groups', '.governance-item-selected-group-checkbox'],
    ];

    selectAllMappings.forEach(([masterId, checkboxSelector]) => {
        const master = modalElement.querySelector(`#${masterId}`);
        if (!master) {
            return;
        }
        master.addEventListener('change', () => {
            toggleCheckboxes(checkboxSelector, master.checked);
        });
    });
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
    // xss-check: ignore - modalMarkup is a static Bootstrap shell; untrusted values are populated with DOM APIs.
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

function openGovernanceItemPolicyDeleteModal(entityType, itemId, policyId = '', policyName = '') {
    const normalizedEntityType = normalizeGovernanceItemEntityType(entityType);
    const normalizedItemId = String(itemId || '').trim();
    const normalizedPolicyId = String(policyId || '').trim();
    const normalizedPolicyName = String(policyName || '').trim();
    if (!normalizedEntityType || !normalizedItemId) {
        return;
    }

    governanceItemPolicyDeleteContext = {
        entityType: normalizedEntityType,
        itemId: normalizedItemId,
        policyId: normalizedPolicyId,
    };

    ensureGovernanceItemPolicyDeleteModal();
    const summary = document.getElementById('governance-item-policy-delete-summary');
    if (summary) {
        const policyPrefix = normalizedPolicyName ? `${normalizedPolicyName} - ` : '';
        summary.textContent = `${policyPrefix}${buildItemPolicyEntityLabel(normalizedEntityType)}: ${normalizedItemId}`;
    }
    governanceItemPolicyDeleteModal?.show();
}

async function deleteGovernanceItemPolicyFromContext() {
    if (!governanceItemPolicyDeleteContext) {
        return;
    }

    const { entityType, itemId, policyId } = governanceItemPolicyDeleteContext;
    const deleteUrl = policyId
        ? `/api/admin/governance/item-policies/${encodeURIComponent(entityType)}/${encodeURIComponent(itemId)}/${encodeURIComponent(policyId)}`
        : `/api/admin/governance/item-policies/${encodeURIComponent(entityType)}/${encodeURIComponent(itemId)}`;
    const response = await fetch(
        deleteUrl,
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
    const policyIdInput = getItemPolicyIdInput();
    if (entityTypeInput?.value === entityType && itemIdInput?.value === itemId && (!policyId || policyIdInput?.value === policyId)) {
        const allowAllInput = getItemAllowAllInput();
        const usersInput = getItemUsersInput();
        const groupsInput = getItemGroupsInput();
        const policyNameInput = getItemPolicyNameInput();
        const resourceLabelInput = getItemResourceLabelInput();
        if (policyIdInput) {
            policyIdInput.value = '';
        }
        if (policyNameInput) {
            policyNameInput.value = '';
        }
        if (resourceLabelInput) {
            resourceLabelInput.value = '';
        }
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
    showGovernanceToast('Delegated item policy deleted.', 'success');
}

function ensureGovernanceItemReviewPanel() {
    const panelElement = document.getElementById('governance-item-policies-section');
    if (panelElement) {
        wireGovernanceItemReviewHandlers(panelElement);
    }
    return panelElement;
}

function openGovernanceItemReviewModal() {
    const panelElement = ensureGovernanceItemReviewPanel();
    if (!panelElement) {
        return;
    }

    panelElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
    loadGovernanceItemPolicyReview().catch((error) => {
        setGovernanceStatus(error.message || 'Failed to load delegated item policies.', 'danger');
    });
}

function wireGovernanceItemReviewHandlers(panelElement) {
    if (!panelElement || panelElement.dataset.reviewWired) {
        return;
    }

    const itemPolicyReviewBody = panelElement.querySelector('#governance-item-policies-review-body');
    if (!itemPolicyReviewBody) {
        return;
    }

    panelElement.dataset.reviewWired = 'true';
    itemPolicyReviewBody.addEventListener('click', async (event) => {
        const target = event.target;
        const editButton = target instanceof HTMLElement ? target.closest('.governance-edit-item-policy-btn') : null;
        const deleteButton = target instanceof HTMLElement ? target.closest('.governance-delete-item-policy-btn') : null;

        if (deleteButton) {
            openGovernanceItemPolicyDeleteModal(
                deleteButton.dataset.entityType,
                deleteButton.dataset.itemId,
                deleteButton.dataset.policyId,
                deleteButton.dataset.policyName,
            );
            return;
        }

        if (!editButton) {
            return;
        }

        const policy = {
            entity_type: editButton.dataset.entityType || '',
            item_id: editButton.dataset.itemId || '',
            policy_id: editButton.dataset.policyId || '',
            policy_name: editButton.dataset.policyName || '',
            resource_label: editButton.dataset.resourceLabel || '',
            allow_all: editButton.dataset.allowAll === 'true',
            allowed_users: parseGovernancePrincipalDataset(editButton.dataset.allowedUsers),
            allowed_groups: parseGovernancePrincipalDataset(editButton.dataset.allowedGroups),
        };

        try {
            await openGovernanceItemPolicyEditor(policy);
        } catch (error) {
            setGovernanceStatus(error.message || 'Failed to open delegated item policy editor.', 'danger');
        }
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
        emptyCell.colSpan = 7;
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
    // xss-check: ignore - modalMarkup is a static Bootstrap shell; untrusted values are populated with DOM APIs.
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

    if (hasUpdates) {
        if (governanceAllowListEditorContext) {
            renderGovernanceAllowListEditorSelections();
        }
        if (document.getElementById('governance-item-policy-editor-modal')?.classList.contains('show')) {
            renderGovernanceItemEditorSelections();
        }
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
            setBootstrapIcon(copyButton, 'bi bi-clipboard');
            copyButton.title = 'Copy ID';
            copyButton.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                navigator.clipboard.writeText(idValue).then(() => {
                    setBootstrapIcon(copyButton, 'bi bi-check');
                    setTimeout(() => {
                        setBootstrapIcon(copyButton, 'bi bi-clipboard');
                    }, 1500);
                }).catch(() => {
                    setBootstrapIcon(copyButton, 'bi bi-x');
                    setTimeout(() => {
                        setBootstrapIcon(copyButton, 'bi bi-clipboard');
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
    await loadGovernanceItemPolicyReview(1);
}

async function saveItemPolicy(event) {
    if (event && typeof event.preventDefault === 'function') {
        event.preventDefault();
    }

    const entityTypeInput = document.getElementById('governance-item-entity-type');
    const itemIdInput = document.getElementById('governance-item-id');
    const policyIdInput = getItemPolicyIdInput();
    const policyNameInput = getItemPolicyNameInput();
    const resourceLabelInput = getItemResourceLabelInput();
    const allowAllInput = document.getElementById('governance-item-allow-all');
    const usersInput = document.getElementById('governance-item-users');
    const groupsInput = document.getElementById('governance-item-groups');

    if (!entityTypeInput || !itemIdInput || !allowAllInput || !usersInput || !groupsInput) {
        return;
    }

    const entityType = normalizeGovernanceItemEntityType(entityTypeInput.value);
    const itemId = String(itemIdInput.value || '').trim();
    const resourceLabel = String(resourceLabelInput?.value || '').trim();
    const policyName = String(policyNameInput?.value || '').trim() || buildDefaultItemPolicyName(entityType, itemId, resourceLabel);

    if (!entityType || !itemId) {
        setGovernanceItemEditorStatus('Entity type and item ID are required for item governance policies.', 'warning');
        return;
    }

    if (!policyName) {
        setGovernanceItemEditorStatus('Policy name is required for delegated item policies.', 'warning');
        return;
    }

    const payload = {
        policy_id: String(policyIdInput?.value || '').trim(),
        policy_name: policyName,
        resource_label: resourceLabel,
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
    updateItemAllowListSummary();
    governanceItemPolicyEditorModal?.hide();
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

    Object.values(GOVERNANCE_PRIMARY_TOGGLE_MAP).forEach((primaryToggleId) => {
        const primaryToggle = document.getElementById(primaryToggleId);
        if (!(primaryToggle instanceof HTMLInputElement)) {
            return;
        }
        primaryToggle.addEventListener('change', () => {
            syncGovernanceFeaturePolicyVisibility();
        });
    });

    document.querySelectorAll('.governance-primary-link').forEach((linkButton) => {
        linkButton.addEventListener('click', () => {
            const targetId = String(linkButton.getAttribute('data-governance-target') || '').trim();
            if (typeof window.openAdminSettingsTab === 'function') {
                window.openAdminSettingsTab('#governance');
            }
            window.setTimeout(() => {
                const target = document.getElementById(targetId);
                const wrapper = target?.closest('.form-check');
                if (target instanceof HTMLInputElement && target.disabled && target.dataset.governanceLocked !== 'true') {
                    wrapper?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    setGovernanceStatus('Enable the matching primary feature before configuring governance for it.', 'warning');
                    return;
                }
                if (wrapper?.classList.contains('d-none')) {
                    setGovernanceStatus('Enable the matching primary feature before configuring governance for it.', 'warning');
                    return;
                }
                target?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                target?.focus();
            }, 100);
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

    const newItemPolicyButton = document.getElementById('governance-new-item-policy-btn');
    if (newItemPolicyButton) {
        newItemPolicyButton.addEventListener('click', async () => {
            clearGovernanceStatus();
            try {
                await openGovernanceItemPolicyEditor();
            } catch (error) {
                setGovernanceStatus(error.message || 'Failed to open delegated item policy editor.', 'danger');
            }
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

    ensureGovernanceItemReviewPanel();
    ensureGovernanceAllowListEditorModal();
    ensureGovernanceItemPolicyEditorModal();

    try {
        await loadFeaturePolicies();
        await loadItemPolicies();
    } catch (error) {
        setGovernanceStatus(error.message || 'Unable to initialize governance settings.', 'danger');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initializeGovernanceTab();
});
