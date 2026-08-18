// admin_settings.js
import { showToast } from "../chat/chat-toast.js";
import { sanitizeHttpUrl } from "../chat/chat-utils.js";

let gptSelected = window.gptSelected || [];
let gptAll      = window.gptAll || [];

let embeddingSelected = window.embeddingSelected || [];
let embeddingAll      = window.embeddingAll || [];

let imageSelected = window.imageSelected || [];
let imageAll      = window.imageAll || [];

let classificationCategories = window.classificationCategories || [];
let enableDocumentClassification = window.enableDocumentClassification || false;

let externalLinks = window.externalLinks || [];
let enableExternalLinks = window.enableExternalLinks || false;
let externalLinksMenuName = window.externalLinksMenuName || 'External Links';
let agentsPagePromotedPopularAgents = Array.isArray(window.agentsPagePromotedPopularAgents)
    ? window.agentsPagePromotedPopularAgents
    : [];
let enableSemanticKernel = Boolean(window.enableSemanticKernel);
let releaseNotificationsRegistration = window.releaseNotificationsRegistration || {
    registered: false,
    name: '',
    email: '',
    organization: '',
    registeredAt: '',
    updatedAt: '',
    recipientEmail: 'simplechat@microsoft.com',
    appVersion: ''
};

// Track whether form has been modified since last save
let formModified = false;
let currentCosmosContainers = [];
let currentCosmosMetricsWindowMinutes = 0;
let currentCosmosStatusLoaded = false;
let currentCosmosContainerSort = { field: 'container_name', direction: 'asc' };
let pendingFileProcessingLogCleanup = null;
let documentAccessIndexStatusPollId = null;
let redisExplorerState = {
    cursor: '0',
    nextCursor: '0',
    cursorHistory: [],
    filter: '',
    pageSize: 25,
    loaded: false,
    selectedKey: ''
};

const COSMOS_CONTAINER_SORT_FIELDS = new Set([
    'container_name',
    'current_ru',
    'ru_utilization',
    'request_units',
    'policy'
]);
const COSMOS_CONTAINER_TEXT_SORT_FIELDS = new Set(['container_name', 'policy']);
const COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU = 10000;
const COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE = 'Throughput above 10,000 RU/s is monitored only in SimpleChat. Use the Azure portal to change capacity; capacity changes above this level can take 4 to 6 hours.';
const DOCUMENT_ACCESS_INDEX_STATUS_POLL_INTERVAL_MS = 7500;
const GROUP_WORKFLOW_ASSIGNMENT_PARSE_DEPTH_LIMIT = 5;

const enableClassificationToggle = document.getElementById('enable_document_classification');
const classificationSettingsDiv = document.getElementById('document_classification_settings');
const classificationTbody = document.getElementById('classification-categories-tbody');
const addClassificationBtn = document.getElementById('add-classification-btn');
const classificationJsonInput = document.getElementById('document_classification_categories_json');

const enableExternalLinksToggle = document.getElementById('enable_external_links');
const externalLinksSettingsDiv = document.getElementById('external_links_settings');
const externalLinksTbody = document.getElementById('external-links-tbody');
const addExternalLinkBtn = document.getElementById('add-external-link-btn');
const externalLinksJsonInput = document.getElementById('external_links_json');
const promotedPopularAgentsInput = document.getElementById('agents_page_promoted_popular_agents_json');
const promotedPopularAgentsSelect = document.getElementById('agents-page-promoted-agent-select');
const promotedPopularAgentsAddButton = document.getElementById('agents-page-promoted-agent-add');
const promotedPopularAgentsBody = document.getElementById('agents-page-promoted-popular-tbody');
const promotedPopularAgentsEmpty = document.getElementById('agents-page-promoted-popular-empty');
const promotedPopularAgentsLoadError = document.getElementById('agents-page-promoted-popular-load-error');
let agentsPagePromotedAvailableAgents = [];

const enableSupportMenuToggle = document.getElementById('enable_support_menu');
const supportMenuSettingsDiv = document.getElementById('support_menu_settings');
const enableSupportSendFeedbackToggle = document.getElementById('enable_support_send_feedback');
const supportFeedbackRecipientGroup = document.getElementById('support_feedback_recipient_group');
const enableSupportLatestFeaturesToggle = document.getElementById('enable_support_latest_features');
const supportLatestFeaturesSettingsDiv = document.getElementById('support_latest_features_settings');

const adminForm = document.getElementById('admin-settings-form');
const saveButton = document.getElementById('floating-save-btn') || (adminForm ? adminForm.querySelector('button[type="submit"]') : null);
const enableGroupWorkspacesToggle = document.getElementById('enable_group_workspaces');
const createGroupPermissionSettingDiv = document.getElementById('create_group_permission_setting');
const groupWorkflowAssignmentsInput = document.getElementById('group_workflow_allowed_group_ids');
const groupWorkflowAssignmentSummary = document.getElementById('group-workflow-assignment-summary');
const groupWorkflowAssignmentModal = document.getElementById('groupWorkflowAssignmentModal');
const groupWorkflowGroupSearchInput = document.getElementById('group-workflow-group-search');
const groupWorkflowGroupSearchBtn = document.getElementById('group-workflow-group-search-btn');
const groupWorkflowAssignmentStatus = document.getElementById('group-workflow-assignment-status');
const groupWorkflowAssignmentError = document.getElementById('group-workflow-assignment-error');
const groupWorkflowAssignmentGroupsBody = document.getElementById('group-workflow-assignment-groups-body');
const groupWorkflowAssignedGroupIds = new Set();
const groupWorkflowDiscoveredGroups = new Map();
const fileDownloadGroupAssignmentsInput = document.getElementById('file_download_allowed_group_ids');
const fileDownloadGroupAssignmentSummary = document.getElementById('file-download-group-assignment-summary');
const fileDownloadGroupAssignmentModal = document.getElementById('fileDownloadGroupAssignmentModal');
const fileDownloadGroupSearchInput = document.getElementById('file-download-group-assignment-search');
const fileDownloadGroupSearchBtn = document.getElementById('file-download-group-assignment-search-btn');
const fileDownloadGroupAssignmentStatus = document.getElementById('file-download-group-assignment-status');
const fileDownloadGroupAssignmentError = document.getElementById('file-download-group-assignment-error');
const fileDownloadGroupAssignmentBody = document.getElementById('file-download-group-assignment-body');
const fileDownloadPublicAssignmentsInput = document.getElementById('file_download_allowed_public_workspace_ids');
const fileDownloadPublicAssignmentSummary = document.getElementById('file-download-public-workspace-assignment-summary');
const fileDownloadPublicAssignmentModal = document.getElementById('fileDownloadPublicWorkspaceAssignmentModal');
const fileDownloadPublicSearchInput = document.getElementById('file-download-public-workspace-assignment-search');
const fileDownloadPublicSearchBtn = document.getElementById('file-download-public-workspace-assignment-search-btn');
const fileDownloadPublicAssignmentStatus = document.getElementById('file-download-public-workspace-assignment-status');
const fileDownloadPublicAssignmentError = document.getElementById('file-download-public-workspace-assignment-error');
const fileDownloadPublicAssignmentBody = document.getElementById('file-download-public-workspace-assignment-body');

function setupAdminFormAutofillMetadata() {
    if (!adminForm) {
        return;
    }

    adminForm.setAttribute('autocomplete', 'off');
    adminForm.setAttribute('data-lpignore', 'true');
    adminForm.setAttribute('data-1p-ignore', 'true');
    adminForm.setAttribute('data-bwignore', 'true');

    adminForm.querySelectorAll('input, select, textarea').forEach(field => {
        if (!field.hasAttribute('autocomplete')) {
            field.setAttribute('autocomplete', 'off');
        }

        if (!field.hasAttribute('data-lpignore')) {
            field.setAttribute('data-lpignore', 'true');
        }

        if (!field.hasAttribute('data-1p-ignore')) {
            field.setAttribute('data-1p-ignore', 'true');
        }

        if (!field.hasAttribute('data-bwignore')) {
            field.setAttribute('data-bwignore', 'true');
        }
    });
}

function parsePolicyListValue(value) {
    return String(value || '')
        .split(/[\n,;]+/)
        .map(item => item.trim())
        .filter(Boolean);
}

function normalizeDomainPolicyValue(value) {
    let normalizedValue = String(value || '').trim().toLowerCase();
    if (!normalizedValue) {
        return '';
    }

    normalizedValue = normalizedValue.replace(/^https?:\/\//i, '');
    normalizedValue = normalizedValue.split('/')[0].split('?')[0].split('#')[0].trim();
    normalizedValue = normalizedValue.replace(/\s+/g, '');
    return normalizedValue.replace(/\.+$/, '');
}

function normalizeUserPolicyValue(value) {
    return String(value || '').trim().toLowerCase();
}

function normalizePolicyValue(value, policyKind) {
    return policyKind === 'domain'
        ? normalizeDomainPolicyValue(value)
        : normalizeUserPolicyValue(value);
}

function createIconButton(iconClass, label, buttonClass = 'btn-outline-secondary') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `btn btn-sm ${buttonClass}`;
    button.title = label;
    button.setAttribute('aria-label', label);

    const icon = document.createElement('i');
    icon.className = iconClass;
    icon.setAttribute('aria-hidden', 'true');
    button.appendChild(icon);

    return button;
}

function normalizeAdminText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function getAdminAgentDisplayName(agent) {
    return normalizeAdminText(agent?.display_name || agent?.displayName || agent?.name || 'Unnamed Agent') || 'Unnamed Agent';
}

function getAdminAgentScopeType(agent) {
    const scopeType = normalizeAdminText(agent?.scope_type).toLowerCase();
    if (agent?.is_group || scopeType === 'group') {
        return 'group';
    }
    if (agent?.is_global || scopeType === 'global' || scopeType === 'enterprise') {
        return 'global';
    }
    return 'personal';
}

function getAdminAgentScopeLabel(agent) {
    const scopeType = getAdminAgentScopeType(agent);
    if (scopeType === 'group') {
        return normalizeAdminText(agent?.group_name || agent?.scope_name || 'Group');
    }
    if (scopeType === 'global') {
        return 'Enterprise';
    }
    return 'Personal';
}

function normalizePromotedPopularWindow(value) {
    const normalizedValue = normalizeAdminText(value).toLowerCase().replace(/-/g, '_');
    if (normalizedValue === 'all' || normalizedValue === 'alltime') {
        return 'all_time';
    }
    if (normalizedValue === '30' || normalizedValue === 'last30' || normalizedValue === 'last_30_days') {
        return '30_days';
    }
    return ['all_time', '30_days', 'both'].includes(normalizedValue) ? normalizedValue : 'both';
}

function normalizePromotedPopularAgent(candidate) {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
        return null;
    }
    const catalogKey = normalizeAdminText(candidate.catalog_key);
    if (!catalogKey) {
        return null;
    }
    return {
        catalog_key: catalogKey,
        display_name: getAdminAgentDisplayName(candidate),
        scope_label: normalizeAdminText(candidate.scope_label || candidate.scope_name || getAdminAgentScopeLabel(candidate)),
        scope_type: getAdminAgentScopeType(candidate),
        window: normalizePromotedPopularWindow(candidate.window),
    };
}

function normalizePromotedPopularAgents(candidates) {
    const seenCatalogKeys = new Set();
    const normalizedAgents = [];
    (Array.isArray(candidates) ? candidates : []).forEach(candidate => {
        const normalizedAgent = normalizePromotedPopularAgent(candidate);
        if (!normalizedAgent || seenCatalogKeys.has(normalizedAgent.catalog_key)) {
            return;
        }
        seenCatalogKeys.add(normalizedAgent.catalog_key);
        normalizedAgents.push(normalizedAgent);
    });
    return normalizedAgents;
}

function setPromotedPopularLoadError(message) {
    if (!promotedPopularAgentsLoadError) {
        return;
    }
    promotedPopularAgentsLoadError.textContent = message || '';
    promotedPopularAgentsLoadError.classList.toggle('d-none', !message);
}

function syncPromotedPopularAgentsInput() {
    agentsPagePromotedPopularAgents = normalizePromotedPopularAgents(agentsPagePromotedPopularAgents);
    if (promotedPopularAgentsInput) {
        promotedPopularAgentsInput.value = JSON.stringify(agentsPagePromotedPopularAgents);
    }
}

function renderPromotedPopularAgentSelect() {
    if (!promotedPopularAgentsSelect) {
        return;
    }

    promotedPopularAgentsSelect.textContent = '';
    const promotedKeys = new Set(agentsPagePromotedPopularAgents.map(agent => agent.catalog_key));
    const availableAgents = agentsPagePromotedAvailableAgents
        .map(agent => normalizePromotedPopularAgent(agent))
        .filter(agent => agent && !promotedKeys.has(agent.catalog_key))
        .sort((left, right) => left.display_name.localeCompare(right.display_name, undefined, { sensitivity: 'base' }));

    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = availableAgents.length ? 'Select an agent to promote...' : 'No additional agents available';
    promotedPopularAgentsSelect.appendChild(placeholder);

    availableAgents.forEach(agent => {
        const option = document.createElement('option');
        option.value = agent.catalog_key;
        option.textContent = `${agent.display_name} (${agent.scope_label})`;
        promotedPopularAgentsSelect.appendChild(option);
    });

    if (promotedPopularAgentsAddButton) {
        promotedPopularAgentsAddButton.disabled = availableAgents.length === 0;
    }
}

function createPromotedPopularWindowSelect(agent, index) {
    const select = document.createElement('select');
    select.className = 'form-select form-select-sm';
    select.setAttribute('aria-label', `Popular tab time range for ${agent.display_name}`);
    [
        ['both', 'Both'],
        ['all_time', 'All Time'],
        ['30_days', 'Last 30 Days'],
    ].forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        option.selected = agent.window === value;
        select.appendChild(option);
    });
    select.addEventListener('change', () => {
        agentsPagePromotedPopularAgents[index].window = normalizePromotedPopularWindow(select.value);
        syncPromotedPopularAgentsInput();
        markFormAsModified();
    });
    return select;
}

function renderPromotedPopularAgents() {
    if (!promotedPopularAgentsBody) {
        return;
    }

    syncPromotedPopularAgentsInput();
    promotedPopularAgentsBody.textContent = '';
    promotedPopularAgentsEmpty?.classList.toggle('d-none', agentsPagePromotedPopularAgents.length > 0);

    agentsPagePromotedPopularAgents.forEach((agent, index) => {
        const row = document.createElement('tr');

        const agentCell = document.createElement('td');
        const nameElement = document.createElement('div');
        nameElement.className = 'fw-semibold';
        nameElement.textContent = agent.display_name;
        const scopeElement = document.createElement('div');
        scopeElement.className = 'text-muted small';
        scopeElement.textContent = agent.scope_label;
        agentCell.appendChild(nameElement);
        agentCell.appendChild(scopeElement);

        const windowCell = document.createElement('td');
        windowCell.appendChild(createPromotedPopularWindowSelect(agent, index));

        const actionsCell = document.createElement('td');
        actionsCell.className = 'text-end text-nowrap';
        const moveUpButton = createIconButton('bi bi-arrow-up', `Move ${agent.display_name} up`);
        moveUpButton.disabled = index === 0;
        moveUpButton.addEventListener('click', () => {
            const previousAgent = agentsPagePromotedPopularAgents[index - 1];
            agentsPagePromotedPopularAgents[index - 1] = agent;
            agentsPagePromotedPopularAgents[index] = previousAgent;
            renderPromotedPopularAgents();
            markFormAsModified();
        });
        const moveDownButton = createIconButton('bi bi-arrow-down', `Move ${agent.display_name} down`);
        moveDownButton.disabled = index === agentsPagePromotedPopularAgents.length - 1;
        moveDownButton.addEventListener('click', () => {
            const nextAgent = agentsPagePromotedPopularAgents[index + 1];
            agentsPagePromotedPopularAgents[index + 1] = agent;
            agentsPagePromotedPopularAgents[index] = nextAgent;
            renderPromotedPopularAgents();
            markFormAsModified();
        });
        const removeButton = createIconButton('bi bi-trash', `Remove ${agent.display_name}`, 'btn-outline-danger');
        removeButton.addEventListener('click', () => {
            agentsPagePromotedPopularAgents.splice(index, 1);
            renderPromotedPopularAgents();
            renderPromotedPopularAgentSelect();
            markFormAsModified();
        });
        actionsCell.appendChild(moveUpButton);
        actionsCell.appendChild(document.createTextNode(' '));
        actionsCell.appendChild(moveDownButton);
        actionsCell.appendChild(document.createTextNode(' '));
        actionsCell.appendChild(removeButton);

        row.appendChild(agentCell);
        row.appendChild(windowCell);
        row.appendChild(actionsCell);
        promotedPopularAgentsBody.appendChild(row);
    });

    renderPromotedPopularAgentSelect();
}

async function loadPromotedPopularAvailableAgents() {
    if (!promotedPopularAgentsSelect) {
        return;
    }
    if (!enableSemanticKernel) {
        agentsPagePromotedAvailableAgents = [];
        setPromotedPopularLoadError('');
        promotedPopularAgentsSelect.textContent = '';
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'Enable Agents to load available agents';
        promotedPopularAgentsSelect.appendChild(option);
        if (promotedPopularAgentsAddButton) {
            promotedPopularAgentsAddButton.disabled = true;
        }
        return;
    }
    try {
        const response = await fetch('/api/agents/catalog?include_usage=true');
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.error || 'Failed to load available agents.');
        }
        agentsPagePromotedAvailableAgents = Array.isArray(payload.agents) ? payload.agents : [];
        setPromotedPopularLoadError('');
    } catch (error) {
        agentsPagePromotedAvailableAgents = [];
        setPromotedPopularLoadError(error.message || 'Failed to load available agents.');
    }
    renderPromotedPopularAgentSelect();
}

function setupAgentsPagePromotedPopularAgents() {
    if (!promotedPopularAgentsInput || !promotedPopularAgentsBody) {
        return;
    }

    try {
        const storedAgents = JSON.parse(promotedPopularAgentsInput.value || '[]');
        agentsPagePromotedPopularAgents = normalizePromotedPopularAgents(storedAgents);
    } catch (error) {
        agentsPagePromotedPopularAgents = normalizePromotedPopularAgents(agentsPagePromotedPopularAgents);
    }

    promotedPopularAgentsAddButton?.addEventListener('click', () => {
        const catalogKey = normalizeAdminText(promotedPopularAgentsSelect?.value);
        if (!catalogKey) {
            return;
        }
        const selectedAgent = agentsPagePromotedAvailableAgents.find(agent => normalizeAdminText(agent?.catalog_key) === catalogKey);
        const normalizedAgent = normalizePromotedPopularAgent(selectedAgent);
        if (!normalizedAgent) {
            return;
        }
        agentsPagePromotedPopularAgents.push(normalizedAgent);
        renderPromotedPopularAgents();
        markFormAsModified();
    });

    renderPromotedPopularAgents();
    loadPromotedPopularAvailableAgents();
}

function getFieldValue(fieldId) {
    return document.getElementById(fieldId)?.value || '';
}

function isFieldChecked(fieldId) {
    return Boolean(document.getElementById(fieldId)?.checked);
}

function setButtonBusy(button, isBusy, busyText) {
    if (!button) {
        return;
    }

    if (!button.dataset.originalText) {
        button.dataset.originalText = button.textContent.trim();
    }
    if (!button.dataset.originalHtml) {
        button.dataset.originalHtml = button.innerHTML;
    }

    button.disabled = isBusy;
    if (isBusy) {
        button.textContent = busyText;
    } else {
        button.innerHTML = button.dataset.originalHtml;
    }
}

async function copyTextToClipboard(text) {
    if (!text) {
        throw new Error('No text was available to copy.');
    }

    if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
    }

    const fallbackTextarea = document.createElement('textarea');
    fallbackTextarea.value = text;
    fallbackTextarea.setAttribute('readonly', 'readonly');
    fallbackTextarea.classList.add('visually-hidden');
    document.body.append(fallbackTextarea);
    try {
        fallbackTextarea.focus();
        fallbackTextarea.select();
        if (!document.execCommand('copy')) {
            throw new Error('Clipboard copy command was not available.');
        }
    } finally {
        fallbackTextarea.remove();
    }
}

function setupInboundMcpObservabilityCopyButtons() {
    document.querySelectorAll('.inbound-mcp-kql-copy-btn').forEach(button => {
        button.addEventListener('click', async () => {
            const targetId = button.dataset.kqlTarget || '';
            const queryText = document.getElementById(targetId)?.textContent || '';
            try {
                await copyTextToClipboard(queryText.trim());
                showToast('Application Insights query copied to clipboard.', 'success');
            } catch (error) {
                showToast(error.message || 'Could not copy the Application Insights query.', 'danger');
            }
        });
    });
}

function setupInboundMcpEasyAuthGuard() {
    const enableToggle = document.getElementById('enable_inbound_mcp_server');
    const modalElement = document.getElementById('inboundMcpEasyAuthModal');
    const confirmCheckbox = document.getElementById('inbound-mcp-easy-auth-confirm');
    const verifyButton = document.getElementById('inbound-mcp-easy-auth-verify');
    const statusElement = document.getElementById('inbound-mcp-easy-auth-status');
    const resultsList = document.getElementById('inbound-mcp-easy-auth-results');
    const copyScriptButton = document.getElementById('inbound-mcp-copy-script');
    const scriptCodeElement = document.getElementById('inbound-mcp-easy-auth-script-code');

    if (!enableToggle || !modalElement || !confirmCheckbox || !verifyButton) {
        return;
    }

    const modal = bootstrap.Modal.getOrCreateInstance(modalElement);
    const wasEnabledOnLoad = enableToggle.checked;
    let easyAuthVerified = wasEnabledOnLoad;

    const setStatus = (message, variant = 'info') => {
        if (!statusElement) {
            return;
        }
        statusElement.textContent = message || '';
        statusElement.className = `alert alert-${variant}${message ? '' : ' d-none'}`;
    };

    const renderResults = endpoints => {
        if (!resultsList) {
            return;
        }
        resultsList.replaceChildren();
        if (!Array.isArray(endpoints) || endpoints.length === 0) {
            resultsList.classList.add('d-none');
            return;
        }
        endpoints.forEach(endpoint => {
            const item = document.createElement('li');
            const statusBadge = document.createElement('span');
            const path = document.createElement('code');
            const message = document.createElement('span');

            item.className = 'list-group-item d-flex flex-column flex-lg-row gap-2 justify-content-between';
            statusBadge.className = `badge align-self-start ${endpoint.success ? 'text-bg-success' : 'text-bg-danger'}`;
            statusBadge.textContent = endpoint.success ? 'OK' : 'Needs fix';
            path.textContent = endpoint.path || 'Unknown endpoint';
            message.textContent = endpoint.message || 'No details returned.';

            item.append(statusBadge, path, message);
            resultsList.append(item);
        });
        resultsList.classList.remove('d-none');
    };

    const resetModalState = () => {
        confirmCheckbox.checked = false;
        setButtonBusy(verifyButton, false);
        verifyButton.disabled = true;
        setStatus('', 'info');
        renderResults([]);
    };

    confirmCheckbox.addEventListener('change', () => {
        verifyButton.disabled = !confirmCheckbox.checked;
    });

    copyScriptButton?.addEventListener('click', async () => {
        const scriptText = scriptCodeElement?.textContent || '';
        if (!scriptText) {
            showToast('No PowerShell script was available to copy.', 'warning');
            return;
        }

        try {
            await copyTextToClipboard(scriptText);
            showToast('PowerShell script copied to clipboard.', 'success');
        } catch (error) {
            showToast(error.message || 'Could not copy the PowerShell script.', 'danger');
        }
    });

    enableToggle.addEventListener('change', event => {
        if (!enableToggle.checked || easyAuthVerified) {
            return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        enableToggle.checked = false;
        resetModalState();
        modal.show();
    });

    verifyButton.addEventListener('click', async () => {
        if (!confirmCheckbox.checked) {
            return;
        }

        setButtonBusy(verifyButton, true, 'Verifying endpoints...');
        setStatus('Checking unauthenticated access to the inbound MCP endpoints...', 'info');
        renderResults([]);

        try {
            const response = await fetch('/api/admin/settings/inbound-mcp/easy-auth-check', {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                },
                credentials: 'same-origin'
            });
            const payload = await response.json();
            renderResults(payload.endpoints);

            if (!response.ok || payload.success !== true) {
                setStatus(payload.message || 'Easy Auth exclusion verification failed.', 'danger');
                enableToggle.checked = false;
                easyAuthVerified = false;
                return;
            }

            easyAuthVerified = true;
            enableToggle.checked = true;
            setStatus(payload.message || 'Easy Auth exclusions verified.', 'success');
            markFormAsModified();
            modal.hide();
            showToast('Inbound MCP endpoint exclusions verified. Save settings to enable the server.', 'success');
        } catch (error) {
            setStatus(error.message || 'Easy Auth exclusion verification failed.', 'danger');
            enableToggle.checked = false;
            easyAuthVerified = false;
        } finally {
            setButtonBusy(verifyButton, false);
            verifyButton.disabled = !confirmCheckbox.checked;
        }
    });

    adminForm?.addEventListener('submit', event => {
        if (!enableToggle.checked || easyAuthVerified) {
            return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        resetModalState();
        modal.show();
        showToast('Verify the inbound MCP Easy Auth exclusions before saving.', 'warning');
    });
}

const inboundMcpEntryListConfigs = {
    clients: {
        hiddenId: 'inbound_mcp_allowed_client_app_entries_json',
        bodyId: 'inbound-mcp-client-app-entries-body',
        summaryId: 'inbound-mcp-client-app-entries-summary',
        modalTitle: 'Client app ID',
        valueLabel: 'Client app ID',
        emptyMessage: 'No client app IDs are allowed.',
        valueHeader: 'Client app ID',
        requireGuid: true,
        lowercase: true,
    },
    tenants: {
        hiddenId: 'inbound_mcp_allowed_tenant_entries_json',
        bodyId: 'inbound-mcp-tenant-entries-body',
        summaryId: 'inbound-mcp-tenant-entries-summary',
        modalTitle: 'Tenant ID',
        valueLabel: 'Tenant ID',
        emptyMessage: 'Only the configured SimpleChat tenant is allowed.',
        valueHeader: 'Tenant ID',
        requireGuid: true,
        lowercase: true,
    },
    sources: {
        hiddenId: 'inbound_mcp_allowed_source_entries_json',
        bodyId: 'inbound-mcp-source-entries-body',
        summaryId: 'inbound-mcp-source-entries-summary',
        modalTitle: 'Source ID',
        valueLabel: 'Source value',
        emptyMessage: 'No explicit source IDs are configured.',
        valueHeader: 'Source value',
        requireGuid: false,
        lowercase: false,
        disallowWildcard: true,
    },
};
const inboundMcpEntriesByList = {
    clients: [],
    tenants: [],
    sources: [],
};

function normalizeInboundMcpEntry(candidate, config) {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
        return null;
    }
    let value = normalizeAdminText(candidate.value || candidate.id || candidate.guid || candidate.client_id || candidate.tenant_id || candidate.source_id);
    if (config.lowercase) {
        value = value.toLowerCase();
    }
    if (!value) {
        return null;
    }
    return {
        value,
        description: normalizeAdminText(candidate.description || candidate.label || candidate.name),
    };
}

function parseInboundMcpEntries(hiddenField, config) {
    let parsedEntries = [];
    try {
        const parsedValue = JSON.parse(hiddenField?.value || '[]');
        parsedEntries = Array.isArray(parsedValue) ? parsedValue : [];
    } catch (error) {
        parsedEntries = [];
    }

    const seenValues = new Set();
    return parsedEntries
        .map(candidate => normalizeInboundMcpEntry(candidate, config))
        .filter(Boolean)
        .filter(entry => {
            const key = config.lowercase ? entry.value.toLowerCase() : entry.value;
            if (seenValues.has(key)) {
                return false;
            }
            seenValues.add(key);
            return true;
        });
}

function syncInboundMcpEntryInput(listKey, markModified = true) {
    const config = inboundMcpEntryListConfigs[listKey];
    const hiddenField = document.getElementById(config?.hiddenId || '');
    if (!config || !hiddenField) {
        return;
    }
    hiddenField.value = JSON.stringify(inboundMcpEntriesByList[listKey] || []);
    if (markModified) {
        markFormAsModified();
    }
}

function createInboundMcpEntryActionButton(iconClass, label, buttonClass, handler) {
    const button = createIconButton(iconClass, label, buttonClass);
    button.addEventListener('click', handler);
    return button;
}

function renderInboundMcpEntries(listKey) {
    const config = inboundMcpEntryListConfigs[listKey];
    const body = document.getElementById(config?.bodyId || '');
    const summary = document.getElementById(config?.summaryId || '');
    if (!config || !body) {
        return;
    }

    syncInboundMcpEntryInput(listKey, false);
    body.replaceChildren();
    const entries = inboundMcpEntriesByList[listKey] || [];
    if (summary) {
        summary.textContent = entries.length === 0
            ? config.emptyMessage
            : `${entries.length} entr${entries.length === 1 ? 'y' : 'ies'} configured.`;
    }

    if (entries.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 3;
        cell.className = 'text-center text-muted';
        cell.textContent = config.emptyMessage;
        row.appendChild(cell);
        body.appendChild(row);
        return;
    }

    entries.forEach((entry, index) => {
        const row = document.createElement('tr');

        const valueCell = document.createElement('td');
        const valueCode = document.createElement('code');
        valueCode.textContent = entry.value;
        valueCell.appendChild(valueCode);

        const descriptionCell = document.createElement('td');
        descriptionCell.textContent = entry.description || 'No description';
        if (!entry.description) {
            descriptionCell.className = 'text-muted';
        }

        const actionCell = document.createElement('td');
        actionCell.className = 'text-end text-nowrap';
        actionCell.appendChild(createInboundMcpEntryActionButton('bi bi-pencil', `Edit ${config.valueHeader}`, 'btn-outline-secondary', () => {
            openInboundMcpEntryModal(listKey, index);
        }));
        actionCell.appendChild(document.createTextNode(' '));
        actionCell.appendChild(createInboundMcpEntryActionButton('bi bi-trash', `Remove ${config.valueHeader}`, 'btn-outline-danger', () => {
            inboundMcpEntriesByList[listKey].splice(index, 1);
            renderInboundMcpEntries(listKey);
            syncInboundMcpEntryInput(listKey);
        }));

        row.appendChild(valueCell);
        row.appendChild(descriptionCell);
        row.appendChild(actionCell);
        body.appendChild(row);
    });
}

function openInboundMcpEntryModal(listKey, editIndex = -1) {
    const config = inboundMcpEntryListConfigs[listKey];
    const modalElement = document.getElementById('inboundMcpEntryModal');
    if (!config || !modalElement) {
        return;
    }

    const modal = bootstrap.Modal.getOrCreateInstance(modalElement);
    const title = document.getElementById('inboundMcpEntryModalLabel');
    const listInput = document.getElementById('inbound-mcp-entry-list-key');
    const editIndexInput = document.getElementById('inbound-mcp-entry-edit-index');
    const valueInput = document.getElementById('inbound-mcp-entry-value');
    const descriptionInput = document.getElementById('inbound-mcp-entry-description');
    const valueLabel = document.getElementById('inbound-mcp-entry-value-label');

    const existingEntry = editIndex >= 0 ? inboundMcpEntriesByList[listKey]?.[editIndex] : null;
    if (title) {
        title.textContent = `${existingEntry ? 'Edit' : 'Add'} ${config.modalTitle}`;
    }
    if (valueLabel) {
        valueLabel.textContent = config.valueLabel;
    }
    if (listInput) {
        listInput.value = listKey;
    }
    if (editIndexInput) {
        editIndexInput.value = String(editIndex);
    }
    if (valueInput) {
        valueInput.value = existingEntry?.value || '';
        valueInput.classList.remove('is-invalid');
    }
    if (descriptionInput) {
        descriptionInput.value = existingEntry?.description || '';
    }
    modal.show();
    valueInput?.focus();
}

function saveInboundMcpEntryFromModal() {
    const listKey = normalizeAdminText(document.getElementById('inbound-mcp-entry-list-key')?.value);
    const config = inboundMcpEntryListConfigs[listKey];
    const editIndex = Number(document.getElementById('inbound-mcp-entry-edit-index')?.value || '-1');
    const valueInput = document.getElementById('inbound-mcp-entry-value');
    const descriptionInput = document.getElementById('inbound-mcp-entry-description');
    const valueError = document.getElementById('inbound-mcp-entry-value-error');
    if (!config || !valueInput) {
        return;
    }

    let value = normalizeAdminText(valueInput.value);
    if (config.lowercase) {
        value = value.toLowerCase();
    }
    let errorMessage = '';
    if (!value) {
        errorMessage = 'Value is required.';
    } else if (config.requireGuid && !isGuidLike(value)) {
        errorMessage = `${config.valueLabel} must be a GUID.`;
    } else if (config.disallowWildcard && value === '*') {
        errorMessage = 'Use wildcard source access in Governance policies; keep this list to explicit source values.';
    }

    if (errorMessage) {
        valueInput.classList.add('is-invalid');
        if (valueError) {
            valueError.textContent = errorMessage;
        }
        return;
    }
    valueInput.classList.remove('is-invalid');

    const duplicateIndex = (inboundMcpEntriesByList[listKey] || []).findIndex((entry, index) => {
        if (index === editIndex) {
            return false;
        }
        const left = config.lowercase ? entry.value.toLowerCase() : entry.value;
        const right = config.lowercase ? value.toLowerCase() : value;
        return left === right;
    });
    if (duplicateIndex >= 0) {
        valueInput.classList.add('is-invalid');
        if (valueError) {
            valueError.textContent = 'That value is already configured.';
        }
        return;
    }

    const nextEntry = {
        value,
        description: normalizeAdminText(descriptionInput?.value),
    };
    if (editIndex >= 0 && inboundMcpEntriesByList[listKey]?.[editIndex]) {
        inboundMcpEntriesByList[listKey][editIndex] = nextEntry;
    } else {
        inboundMcpEntriesByList[listKey].push(nextEntry);
    }
    renderInboundMcpEntries(listKey);
    syncInboundMcpEntryInput(listKey);
    bootstrap.Modal.getInstance(document.getElementById('inboundMcpEntryModal'))?.hide();
}

function ensureDefaultInboundMcpTenantEntry() {
    const container = document.getElementById('inbound-mcp-configuration');
    const defaultTenantId = normalizeAdminText(container?.dataset.defaultTenantId).toLowerCase();
    if (!defaultTenantId || defaultTenantId.startsWith('<')) {
        return;
    }
    const tenantEntries = inboundMcpEntriesByList.tenants || [];
    if (tenantEntries.some(entry => entry.value.toLowerCase() === defaultTenantId)) {
        return;
    }
    tenantEntries.unshift({
        value: defaultTenantId,
        description: 'SimpleChat tenant',
    });
}

function setupInboundMcpEntryEditors() {
    const configurationSection = document.getElementById('inbound-mcp-configuration');
    if (!configurationSection) {
        return;
    }

    Object.entries(inboundMcpEntryListConfigs).forEach(([listKey, config]) => {
        const hiddenField = document.getElementById(config.hiddenId);
        inboundMcpEntriesByList[listKey] = parseInboundMcpEntries(hiddenField, config);
        renderInboundMcpEntries(listKey);
    });

    document.querySelectorAll('.inbound-mcp-entry-add-btn').forEach(button => {
        button.addEventListener('click', () => {
            openInboundMcpEntryModal(button.dataset.mcpEntryList);
        });
    });

    document.getElementById('inbound-mcp-entry-save-btn')?.addEventListener('click', saveInboundMcpEntryFromModal);

    const tenantToggle = document.getElementById('inbound_mcp_allow_external_tenants');
    const tenantContainer = document.getElementById('inbound-mcp-tenant-list-container');
    tenantToggle?.addEventListener('change', () => {
        if (tenantToggle.checked) {
            ensureDefaultInboundMcpTenantEntry();
            renderInboundMcpEntries('tenants');
            syncInboundMcpEntryInput('tenants');
        }
        tenantContainer?.classList.toggle('d-none', !tenantToggle.checked);
    });

    const sourceToggle = document.getElementById('inbound_mcp_allow_all_source_ids');
    const sourceContainer = document.getElementById('inbound-mcp-source-list-container');
    const allSourceGovernanceCallout = document.getElementById('inbound-mcp-all-source-governance-callout');
    const controlledSourceGovernanceCallout = document.getElementById('inbound-mcp-controlled-source-governance-callout');
    const syncSourceGovernanceCallouts = () => {
        const allowAllSources = Boolean(sourceToggle?.checked);
        allSourceGovernanceCallout?.classList.toggle('d-none', !allowAllSources);
        controlledSourceGovernanceCallout?.classList.toggle('d-none', allowAllSources);
    };
    if (sourceToggle && !sourceToggle.checked) {
        inboundMcpEntriesByList.sources = (inboundMcpEntriesByList.sources || []).filter(entry => entry.value !== '*');
        renderInboundMcpEntries('sources');
        syncInboundMcpEntryInput('sources', false);
    }
    sourceToggle?.addEventListener('change', () => {
        if (!sourceToggle.checked) {
            inboundMcpEntriesByList.sources = (inboundMcpEntriesByList.sources || []).filter(entry => entry.value !== '*');
            renderInboundMcpEntries('sources');
            syncInboundMcpEntryInput('sources');
        }
        sourceContainer?.classList.toggle('d-none', sourceToggle.checked);
        syncSourceGovernanceCallouts();
        markFormAsModified();
    });
    syncSourceGovernanceCallouts();

    if (tenantToggle?.checked) {
        ensureDefaultInboundMcpTenantEntry();
        renderInboundMcpEntries('tenants');
        syncInboundMcpEntryInput('tenants', false);
    }
}

function setElementText(elementId, value) {
    const element = document.getElementById(elementId);
    if (element) {
        element.textContent = value || 'Not loaded';
    }
}

function getFileProcessingLogCleanupElements() {
    return {
        ageInput: document.getElementById('file-processing-log-cleanup-age'),
        unitSelect: document.getElementById('file-processing-log-cleanup-unit'),
        deleteOlderButton: document.getElementById('delete-old-file-processing-logs-btn'),
        deleteAllButton: document.getElementById('delete-all-file-processing-logs-btn'),
        modalElement: document.getElementById('fileProcessingLogCleanupModal'),
        confirmationText: document.getElementById('file-processing-log-cleanup-confirmation'),
        confirmButton: document.getElementById('confirm-file-processing-log-cleanup-btn')
    };
}

function setFileProcessingLogCleanupBusy(elements, isBusy) {
    elements.ageInput.disabled = isBusy;
    elements.unitSelect.disabled = isBusy;
    elements.deleteOlderButton.disabled = isBusy;
    elements.deleteAllButton.disabled = isBusy;
    setButtonBusy(elements.confirmButton, isBusy, 'Deleting...');
}

function showFileProcessingLogCleanupConfirmation(elements, requestPayload, message) {
    pendingFileProcessingLogCleanup = requestPayload;
    elements.confirmationText.textContent = message;
    bootstrap.Modal.getOrCreateInstance(elements.modalElement).show();
}

async function executeFileProcessingLogCleanup(elements) {
    if (!pendingFileProcessingLogCleanup) {
        return;
    }

    setFileProcessingLogCleanupBusy(elements, true);
    try {
        const response = await fetch('/api/admin/settings/file-processing-logs/cleanup', {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                ...pendingFileProcessingLogCleanup,
                confirmed: true
            })
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.success) {
            const partialCount = Number.isInteger(payload.deleted_count) && payload.deleted_count > 0
                ? ` ${payload.deleted_count} log${payload.deleted_count === 1 ? '' : 's'} were deleted before the operation stopped.`
                : '';
            throw new Error(`${payload.error || 'Unable to delete file processing logs.'}${partialCount}`);
        }

        const deletedCount = Number(payload.deleted_count) || 0;
        bootstrap.Modal.getInstance(elements.modalElement)?.hide();
        showToast(
            `${deletedCount} file processing log${deletedCount === 1 ? '' : 's'} deleted.`,
            'success'
        );
        pendingFileProcessingLogCleanup = null;
    } catch (error) {
        showToast(error.message || 'Unable to delete file processing logs.', 'danger');
    } finally {
        setFileProcessingLogCleanupBusy(elements, false);
    }
}

function setupFileProcessingLogCleanup() {
    const elements = getFileProcessingLogCleanupElements();
    if (Object.values(elements).some(element => !element)) {
        return;
    }

    elements.ageInput.addEventListener('input', () => {
        elements.ageInput.classList.remove('is-invalid');
    });
    elements.deleteOlderButton.addEventListener('click', () => {
        const age = Number(elements.ageInput.value);
        if (!Number.isInteger(age) || age < 1) {
            elements.ageInput.classList.add('is-invalid');
            elements.ageInput.focus();
            showToast('Enter a whole-number log age greater than zero.', 'warning');
            return;
        }

        const unit = elements.unitSelect.value;
        const singularUnit = unit.endsWith('s') ? unit.slice(0, -1) : unit;
        const ageLabel = `${age} ${age === 1 ? singularUnit : unit}`;
        showFileProcessingLogCleanupConfirmation(
            elements,
            { delete_all: false, age, unit },
            `Delete every file processing log older than ${ageLabel}?`
        );
    });
    elements.deleteAllButton.addEventListener('click', () => {
        showFileProcessingLogCleanupConfirmation(
            elements,
            { delete_all: true },
            'Delete every stored file processing log?'
        );
    });
    elements.confirmButton.addEventListener('click', () => {
        executeFileProcessingLogCleanup(elements);
    });
    elements.modalElement.addEventListener('hidden.bs.modal', () => {
        if (!elements.confirmButton.disabled) {
            pendingFileProcessingLogCleanup = null;
        }
    });
}

function formatNumber(value) {
    if (value === null || value === undefined || value === '') {
        return 'Not available';
    }
    const numericValue = Number(value);
    if (Number.isNaN(numericValue)) {
        return 'Not available';
    }
    return numericValue.toLocaleString();
}

function formatRedisStatus(value) {
    const normalizedValue = String(value || '').trim();
    if (!normalizedValue) {
        return 'Not loaded';
    }

    return normalizedValue
        .replace(/_/g, ' ')
        .replace(/\b\w/g, character => character.toUpperCase());
}

function getRedisMonitoringStatusVariant(value) {
    const normalizedValue = String(value || '').trim().toLowerCase();
    if (normalizedValue === 'healthy' || normalizedValue === 'active') {
        return 'success';
    }
    if (['degraded', 'not_configured', 'unavailable'].includes(normalizedValue)) {
        return 'warning';
    }
    if (normalizedValue === 'error') {
        return 'danger';
    }
    return 'secondary';
}

function setRedisMonitoringMessage(message, variant = 'info') {
    const messageElement = document.getElementById('redis-monitoring-message');
    if (!messageElement) {
        return;
    }

    messageElement.textContent = message || '';
    messageElement.className = `alert alert-${variant} small mb-3`;
    messageElement.classList.toggle('d-none', !message);
}

function setRedisMonitoringBadge(elementId, value, variant = 'secondary') {
    const badge = document.getElementById(elementId);
    if (!badge) {
        return;
    }

    const safeVariants = new Set(['primary', 'secondary', 'success', 'danger', 'warning', 'info']);
    badge.textContent = value || 'Not loaded';
    badge.className = `badge text-bg-${safeVariants.has(variant) ? variant : 'secondary'}`;
}

function formatRedisMetric(value, unit) {
    if (value === null || value === undefined || value === '') {
        return 'Not available';
    }
    const numericValue = Number(value);
    if (Number.isNaN(numericValue)) {
        return 'Not available';
    }
    return `${numericValue.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${unit}`;
}

function formatRedisPercent(value) {
    if (value === null || value === undefined || value === '') {
        return 'Not available';
    }
    const numericValue = Number(value);
    if (Number.isNaN(numericValue)) {
        return 'Not available';
    }
    return `${numericValue.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
}

function formatRedisMemoryUsage(memory) {
    const usedMemory = memory?.used_memory_human || formatRedisMetric(memory?.used_memory, 'bytes');
    const maxMemory = memory?.maxmemory_human || formatRedisMetric(memory?.maxmemory, 'bytes');
    const usagePercent = formatRedisPercent(memory?.usage_percent);

    if (usedMemory === 'Not available') {
        return 'Not available';
    }
    if (maxMemory === 'Not available' || Number(memory?.maxmemory || 0) === 0) {
        return `${usedMemory} / no maxmemory limit`;
    }
    if (usagePercent === 'Not available') {
        return `${usedMemory} / ${maxMemory}`;
    }
    return `${usedMemory} / ${maxMemory} (${usagePercent})`;
}

function formatRedisRuntime(value) {
    return value ? 'Active' : 'Inactive';
}

function setRedisTestResult(resultDiv, message, variant = 'muted') {
    if (!resultDiv) {
        return;
    }

    const safeVariants = new Set(['success', 'danger', 'muted', 'info']);
    resultDiv.textContent = message || '';
    resultDiv.className = `mt-2 text-${safeVariants.has(variant) ? variant : 'muted'}`;
}

function formatRu(value) {
    const formattedValue = formatNumber(value);
    return formattedValue === 'Not available' ? formattedValue : `${formattedValue} RU/s`;
}

function formatRequestUnits(value) {
    return formatNumber(value);
}

function isCosmosThroughputPortalManaged(target) {
    const currentRu = getNullableNumber(target?.current_ru);
    return Boolean(target?.portal_managed_scaling_required) || (
        Boolean(target?.is_scalable)
        && currentRu !== null
        && currentRu > COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU
    );
}

function isCosmosScaleUpBlockedBySimpleChatLimit(target) {
    const currentRu = getNullableNumber(target?.current_ru);
    return Boolean(target?.is_scalable)
        && currentRu !== null
        && currentRu >= COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU;
}

function getCosmosPortalManagedMessage(target) {
    return target?.portal_managed_message || COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE;
}

function createCosmosPortalManagedBadge(target) {
    const badge = document.createElement('span');
    badge.className = 'badge text-bg-info ms-2 align-middle';
    badge.title = getCosmosPortalManagedMessage(target);
    badge.setAttribute('aria-label', 'Monitor only in SimpleChat');

    const icon = document.createElement('i');
    icon.className = 'bi bi-info-circle me-1';
    icon.setAttribute('aria-hidden', 'true');
    badge.appendChild(icon);
    badge.appendChild(document.createTextNode('Monitor only'));
    return badge;
}

function getNumericFieldValue(fieldId, fallbackValue) {
    const numericValue = Number(getFieldValue(fieldId));
    return Number.isNaN(numericValue) ? fallbackValue : numericValue;
}

function getNullableNumber(value) {
    if (value === null || value === undefined || value === '') {
        return null;
    }
    const numericValue = Number(value);
    return Number.isNaN(numericValue) ? null : numericValue;
}

function formatPercent(value) {
    if (value === null || value === undefined || value === '') {
        return 'Not available';
    }
    const numericValue = Number(value);
    if (Number.isNaN(numericValue)) {
        return 'Not available';
    }
    return `${numericValue.toFixed(1)}%`;
}

function setCosmosThroughputMessage(message, variant = 'info') {
    const messageElement = document.getElementById('cosmos-throughput-message');
    if (!messageElement) {
        return;
    }

    messageElement.textContent = message || '';
    messageElement.className = `alert alert-${variant} mt-3`;
    messageElement.classList.toggle('d-none', !message);
}

function setCosmosThroughputValidationResult(data) {
    const messageElement = document.getElementById('cosmos-throughput-message');
    if (!messageElement) {
        return;
    }

    messageElement.replaceChildren();
    messageElement.className = `alert alert-${data?.variant || (data?.success ? 'success' : 'danger')} mt-3`;

    const summary = document.createElement('div');
    summary.className = 'fw-semibold mb-2';
    summary.textContent = data?.message || 'Cosmos throughput access validation completed.';
    messageElement.appendChild(summary);

    const checks = Array.isArray(data?.checks) ? data.checks : [];
    if (checks.length > 0) {
        const list = document.createElement('ul');
        list.className = 'mb-0 ps-3 small';
        checks.forEach(check => {
            const item = document.createElement('li');
            const statusText = check?.passed ? 'Passed' : 'Failed';
            item.textContent = `${statusText} - ${check?.label || 'Check'}: ${check?.message || 'No detail returned.'}`;
            list.appendChild(item);
        });
        messageElement.appendChild(list);
    }

    messageElement.classList.remove('d-none');
}

function setCosmosThroughputValidationMessage(errors) {
    const messageElement = document.getElementById('cosmos-throughput-validation-message');
    if (!messageElement) {
        return;
    }

    messageElement.textContent = Array.isArray(errors) && errors.length > 0 ? errors.join(' ') : '';
    messageElement.className = 'alert alert-danger';
    messageElement.classList.toggle('d-none', !errors || errors.length === 0);
}

const COSMOS_THROUGHPUT_VALIDATION_FIELD_IDS = [
    'cosmos_throughput_metrics_window_minutes',
    'cosmos_throughput_scale_up_threshold_percent',
    'cosmos_throughput_scale_down_threshold_percent',
    'cosmos_throughput_scale_up_cooldown_minutes',
    'cosmos_throughput_scale_down_cooldown_minutes'
];

function clearCosmosThroughputValidationState() {
    COSMOS_THROUGHPUT_VALIDATION_FIELD_IDS.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (!field) {
            return;
        }
        field.classList.remove('is-invalid');
        field.setCustomValidity('');
    });

    document.querySelectorAll('.cosmos-container-policy-input.is-invalid').forEach(input => {
        input.classList.remove('is-invalid');
        input.setCustomValidity('');
    });
    setCosmosThroughputValidationMessage([]);
}

function getPolicyNumericValue(policy, fieldName, fallbackValue) {
    const numericValue = Number(policy?.[fieldName]);
    return Number.isNaN(numericValue) ? fallbackValue : numericValue;
}

function markCosmosFieldInvalid(fieldId, message) {
    const field = document.getElementById(fieldId);
    if (!field) {
        return null;
    }
    field.classList.add('is-invalid');
    field.setCustomValidity(message);
    return field;
}

function markCosmosContainerPolicyFieldsInvalid(containerName, fieldNames, message) {
    const markedInputs = [];
    const inputs = document.querySelectorAll('.cosmos-container-policy-input[data-container-name][data-policy-field]');
    inputs.forEach(input => {
        if (input.dataset.containerName !== containerName || !fieldNames.includes(input.dataset.policyField)) {
            return;
        }
        input.classList.add('is-invalid');
        input.setCustomValidity(message);
        markedInputs.push(input);
    });
    return markedInputs;
}

function validateCosmosThroughputSettings(options = {}) {
    clearCosmosThroughputValidationState();
    if (!isFieldChecked('cosmos_throughput_autoscale_enabled')) {
        return { isValid: true, errors: [] };
    }

    const errors = [];
    const invalidFields = [];
    const metricsWindow = getNumericFieldValue('cosmos_throughput_metrics_window_minutes', 5);
    const scaleUpThreshold = getNumericFieldValue('cosmos_throughput_scale_up_threshold_percent', 90);
    const scaleDownThreshold = getNumericFieldValue('cosmos_throughput_scale_down_threshold_percent', 70);
    const scaleUpInterval = getNumericFieldValue('cosmos_throughput_scale_up_cooldown_minutes', 5);
    const scaleDownInterval = getNumericFieldValue('cosmos_throughput_scale_down_cooldown_minutes', 20);

    function addGlobalError(message, fieldIds) {
        errors.push(`Cosmos throughput policy: ${message}`);
        fieldIds.forEach(fieldId => {
            const field = markCosmosFieldInvalid(fieldId, message);
            if (field) {
                invalidFields.push(field);
            }
        });
    }

    if (scaleUpThreshold <= scaleDownThreshold) {
        addGlobalError('Scale Up At must be higher than Scale Down At.', [
            'cosmos_throughput_scale_up_threshold_percent',
            'cosmos_throughput_scale_down_threshold_percent'
        ]);
    }
    if (scaleUpInterval < metricsWindow) {
        addGlobalError('Scale Up Interval must be greater than or equal to the Metrics Window.', [
            'cosmos_throughput_metrics_window_minutes',
            'cosmos_throughput_scale_up_cooldown_minutes'
        ]);
    }
    if (scaleDownInterval < metricsWindow) {
        addGlobalError('Scale Down Interval must be greater than or equal to the Metrics Window.', [
            'cosmos_throughput_metrics_window_minutes',
            'cosmos_throughput_scale_down_cooldown_minutes'
        ]);
    }

    if (!isCosmosContainerPolicyEnforced()) {
        const policies = collectCosmosContainerPolicies();
        Object.entries(policies).forEach(([containerName, policy]) => {
            if (policy?.enabled === false) {
                return;
            }

            const policyScaleUpThreshold = getPolicyNumericValue(policy, 'scale_up_threshold_percent', scaleUpThreshold);
            const policyScaleDownThreshold = getPolicyNumericValue(policy, 'scale_down_threshold_percent', scaleDownThreshold);
            const policyScaleUpInterval = getPolicyNumericValue(policy, 'scale_up_cooldown_minutes', scaleUpInterval);
            const policyScaleDownInterval = getPolicyNumericValue(policy, 'scale_down_cooldown_minutes', scaleDownInterval);

            function addContainerError(message, fieldNames) {
                errors.push(`Container '${containerName}' policy: ${message}`);
                invalidFields.push(...markCosmosContainerPolicyFieldsInvalid(containerName, fieldNames, message));
            }

            if (policyScaleUpThreshold <= policyScaleDownThreshold) {
                addContainerError('Scale Up At must be higher than Scale Down At.', [
                    'scale_up_threshold_percent',
                    'scale_down_threshold_percent'
                ]);
            }
            if (policyScaleUpInterval < metricsWindow) {
                addContainerError('Scale Up Interval must be greater than or equal to the Metrics Window.', [
                    'scale_up_cooldown_minutes'
                ]);
            }
            if (policyScaleDownInterval < metricsWindow) {
                addContainerError('Scale Down Interval must be greater than or equal to the Metrics Window.', [
                    'scale_down_cooldown_minutes'
                ]);
            }
        });
    }

    if (errors.length === 0) {
        return { isValid: true, errors: [] };
    }

    setCosmosThroughputValidationMessage(errors);
    if (options.report && invalidFields.length > 0) {
        document.getElementById('scale-tab')?.click();
        invalidFields[0].focus({ preventScroll: false });
        invalidFields[0].reportValidity();
    }
    return { isValid: false, errors };
}

function readCosmosContainerPolicies() {
    const policyField = document.getElementById('cosmos_throughput_container_policies_json');
    if (!policyField) {
        return {};
    }

    try {
        const parsedPolicies = JSON.parse(policyField.value || '{}');
        return parsedPolicies && typeof parsedPolicies === 'object' && !Array.isArray(parsedPolicies)
            ? parsedPolicies
            : {};
    } catch (error) {
        return {};
    }
}

function writeCosmosContainerPolicies(policies) {
    const policyField = document.getElementById('cosmos_throughput_container_policies_json');
    if (!policyField) {
        return;
    }

    policyField.value = JSON.stringify(policies || {});
    markFormAsModified();
}

function isCosmosContainerPolicyEnforced() {
    return isFieldChecked('cosmos_throughput_enforce_container_defaults');
}

function buildGlobalCosmosContainerPolicy(containerName = '') {
    return {
        container_name: containerName,
        enabled: true,
        auto_scale_up_enabled: isFieldChecked('cosmos_throughput_auto_scale_up_enabled'),
        auto_scale_down_enabled: isFieldChecked('cosmos_throughput_auto_scale_down_enabled'),
        scale_up_threshold_percent: getNumericFieldValue('cosmos_throughput_scale_up_threshold_percent', 90),
        scale_down_threshold_percent: getNumericFieldValue('cosmos_throughput_scale_down_threshold_percent', 70),
        scale_up_step_ru: getNumericFieldValue('cosmos_throughput_scale_up_step_ru', 1000),
        scale_down_step_ru: getNumericFieldValue('cosmos_throughput_scale_down_step_ru', 1000),
        scale_up_cooldown_minutes: getNumericFieldValue('cosmos_throughput_scale_up_cooldown_minutes', 5),
        scale_down_cooldown_minutes: getNumericFieldValue('cosmos_throughput_scale_down_cooldown_minutes', 20),
        min_ru: getNumericFieldValue('cosmos_throughput_min_ru', 1000),
        max_ru: getNumericFieldValue('cosmos_throughput_max_ru', COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU),
        ignore_min_limit: isFieldChecked('cosmos_throughput_ignore_min_limit'),
        ignore_max_limit: isFieldChecked('cosmos_throughput_ignore_max_limit'),
        convert_manual_to_autoscale_enabled: isFieldChecked('cosmos_throughput_convert_manual_to_autoscale_enabled')
    };
}

function mergeRuntimePolicyFields(policy, existingPolicy) {
    const mergedPolicy = { ...policy };
    if (existingPolicy?.last_scale_up_at) {
        mergedPolicy.last_scale_up_at = existingPolicy.last_scale_up_at;
    }
    if (existingPolicy?.last_scale_down_at) {
        mergedPolicy.last_scale_down_at = existingPolicy.last_scale_down_at;
    }
    if (existingPolicy?.last_mode_conversion_at) {
        mergedPolicy.last_mode_conversion_at = existingPolicy.last_mode_conversion_at;
    }
    return mergedPolicy;
}

function getCosmosContainerPolicy(container) {
    const savedPolicies = readCosmosContainerPolicies();
    const containerName = container?.container_name || '';
    if (isCosmosContainerPolicyEnforced()) {
        const existingPolicy = savedPolicies[containerName] || container?.policy || {};
        return mergeRuntimePolicyFields(buildGlobalCosmosContainerPolicy(containerName), existingPolicy);
    }

    return {
        ...(container?.policy || {}),
        ...(savedPolicies[containerName] || {}),
        container_name: containerName
    };
}

function createPolicyCheckbox(containerName, fieldName, checked, label) {
    const wrapper = document.createElement('div');
    wrapper.className = 'form-check form-switch mb-1';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'form-check-input cosmos-container-policy-input';
    checkbox.checked = Boolean(checked);
    checkbox.dataset.containerName = containerName;
    checkbox.dataset.policyField = fieldName;

    const checkboxLabel = document.createElement('label');
    checkboxLabel.className = 'form-check-label small';
    checkboxLabel.textContent = label;

    wrapper.appendChild(checkbox);
    wrapper.appendChild(checkboxLabel);
    return wrapper;
}

function createPolicyNumberInput(containerName, fieldName, value, min, max, step, label) {
    const wrapper = document.createElement('label');
    wrapper.className = 'form-label small d-block mb-1';
    wrapper.textContent = label;

    const input = document.createElement('input');
    input.type = 'number';
    input.className = 'form-control form-control-sm cosmos-container-policy-input mt-1';
    input.value = value ?? '';
    input.min = String(min);
    if (max !== null && max !== undefined) {
        input.max = String(max);
    }
    input.step = String(step);
    input.dataset.containerName = containerName;
    input.dataset.policyField = fieldName;
    input.dataset.policyType = 'number';
    input.addEventListener('input', () => {
        input.classList.remove('is-invalid');
        input.setCustomValidity('');
    });

    wrapper.appendChild(input);
    return wrapper;
}

function createManualContainerScaleButton(containerName, direction, disabled, disabledReason = '') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = direction === 'up' ? 'btn btn-outline-primary btn-sm' : 'btn btn-outline-secondary btn-sm';
    button.disabled = disabled;
    button.textContent = direction === 'up' ? 'Up' : 'Down';
    const actionLabel = direction === 'up' ? 'Scale this container up' : 'Scale this container down';
    button.title = disabledReason || actionLabel;
    button.setAttribute('aria-label', disabledReason ? `${actionLabel}: ${disabledReason}` : actionLabel);
    button.addEventListener('click', () => manuallyScaleCosmosThroughput(direction, containerName, button));
    return button;
}

function createCosmosAutoscaleConversionButton(containerName, mode, isScalable, buttonClass = 'btn-outline-secondary', disabledReason = '') {
    const disabled = mode !== 'manual' || !isScalable || Boolean(disabledReason);
    const button = createIconButton('bi bi-lightning-charge', `Convert ${containerName || 'database'} manual throughput to Cosmos autoscale`, buttonClass);
    button.disabled = disabled;
    if (disabledReason) {
        button.title = disabledReason;
        button.setAttribute('aria-label', `Convert ${containerName || 'database'} manual throughput to Cosmos autoscale: ${disabledReason}`);
    }
    button.addEventListener('click', () => convertCosmosThroughputToAutoscale(containerName, button));
    return button;
}

function collectCosmosContainerPolicies() {
    const policies = readCosmosContainerPolicies();
    const inputs = document.querySelectorAll('.cosmos-container-policy-input[data-container-name][data-policy-field]');
    inputs.forEach(input => {
        const containerName = input.dataset.containerName;
        const policyField = input.dataset.policyField;
        if (!containerName || !policyField) {
            return;
        }

        policies[containerName] = policies[containerName] || { container_name: containerName };
        if (input.type === 'checkbox') {
            policies[containerName][policyField] = input.checked;
        } else if (input.dataset.policyType === 'number') {
            policies[containerName][policyField] = Number(input.value || 0);
        } else {
            policies[containerName][policyField] = input.value;
        }
    });

    return policies;
}

function getContainerRuUtilization(container) {
    const utilizationValue = getContainerRuUtilizationValue(container);
    return utilizationValue === null ? 'Not available' : `${utilizationValue.toFixed(1)}%${container?.normalized_ru_percent === null || container?.normalized_ru_percent === undefined || container?.normalized_ru_percent === '' ? ' est.' : ''}`;
}

function getContainerRuUtilizationValue(container) {
    const normalizedValue = getNullableNumber(container?.normalized_ru_percent);
    if (normalizedValue !== null) {
        return normalizedValue;
    }

    const requestUnitsValue = container?.request_units;
    const currentRuValue = container?.current_ru;
    const windowMinutes = Number(currentCosmosMetricsWindowMinutes);
    if (
        requestUnitsValue !== null
        && requestUnitsValue !== undefined
        && currentRuValue !== null
        && currentRuValue !== undefined
        && windowMinutes > 0
    ) {
        const requestUnits = Number(requestUnitsValue);
        const currentRu = Number(currentRuValue);
        if (!Number.isNaN(requestUnits) && !Number.isNaN(currentRu) && currentRu > 0) {
            const averageRuPerSecond = requestUnits / (windowMinutes * 60);
            return (averageRuPerSecond / currentRu) * 100;
        }
    }

    return null;
}

function getCosmosContainerPolicyLabel(container) {
    if (isCosmosThroughputPortalManaged(container)) {
        return 'Monitor only';
    }
    const policy = getCosmosContainerPolicy(container);
    if (isCosmosContainerPolicyEnforced()) {
        return 'Global policy';
    }
    return policy.enabled === false ? 'Disabled' : `${policy.min_ru || 'min'}-${policy.max_ru || 'max'} RU/s`;
}

function getCosmosContainerSortValue(container, fieldName) {
    switch (fieldName) {
        case 'container_name':
            return String(container?.container_name || 'database').toLowerCase();
        case 'current_ru':
            return getNullableNumber(container?.current_ru);
        case 'ru_utilization':
            return getContainerRuUtilizationValue(container);
        case 'request_units':
            return getNullableNumber(container?.request_units);
        case 'policy':
            return getCosmosContainerPolicyLabel(container).toLowerCase();
        default:
            return '';
    }
}

function compareCosmosContainerValues(firstValue, secondValue, fieldName, direction) {
    const firstMissing = firstValue === null || firstValue === undefined || firstValue === '';
    const secondMissing = secondValue === null || secondValue === undefined || secondValue === '';
    if (firstMissing && secondMissing) {
        return 0;
    }
    if (firstMissing) {
        return 1;
    }
    if (secondMissing) {
        return -1;
    }

    const multiplier = direction === 'desc' ? -1 : 1;
    if (COSMOS_CONTAINER_TEXT_SORT_FIELDS.has(fieldName)) {
        return String(firstValue).localeCompare(String(secondValue), undefined, { sensitivity: 'base', numeric: true }) * multiplier;
    }
    return (Number(firstValue) - Number(secondValue)) * multiplier;
}

function getFilteredCosmosContainers(containers) {
    const filterValue = String(document.getElementById('cosmos-throughput-container-filter')?.value || '').trim().toLowerCase();
    if (!filterValue) {
        return Array.isArray(containers) ? [...containers] : [];
    }

    return (Array.isArray(containers) ? containers : []).filter(container => (
        String(container?.container_name || 'database').toLowerCase().includes(filterValue)
    ));
}

function getFilteredCosmosPolicyContainers(containers) {
    const filterValue = String(document.getElementById('cosmos-throughput-container-policy-filter')?.value || '').trim().toLowerCase();
    if (!filterValue) {
        return Array.isArray(containers) ? [...containers] : [];
    }

    return (Array.isArray(containers) ? containers : []).filter(container => (
        String(container?.container_name || 'database').toLowerCase().includes(filterValue)
    ));
}

function updateCosmosContainerPolicyFilterControls(totalCount, visibleCount) {
    const countElement = document.getElementById('cosmos-throughput-container-policy-filter-count');
    if (countElement) {
        countElement.textContent = totalCount > 0 ? `Showing ${visibleCount} of ${totalCount} containers` : '';
    }
}

function setCosmosContainerPolicyFilter(containerName = '') {
    const filterInput = document.getElementById('cosmos-throughput-container-policy-filter');
    if (filterInput) {
        filterInput.value = containerName;
    }
}

function getSortedCosmosContainers(containers) {
    const fieldName = COSMOS_CONTAINER_SORT_FIELDS.has(currentCosmosContainerSort.field)
        ? currentCosmosContainerSort.field
        : 'container_name';
    const direction = currentCosmosContainerSort.direction === 'desc' ? 'desc' : 'asc';
    return [...containers].sort((firstContainer, secondContainer) => {
        const primaryComparison = compareCosmosContainerValues(
            getCosmosContainerSortValue(firstContainer, fieldName),
            getCosmosContainerSortValue(secondContainer, fieldName),
            fieldName,
            direction,
        );
        if (primaryComparison !== 0) {
            return primaryComparison;
        }

        return compareCosmosContainerValues(
            getCosmosContainerSortValue(firstContainer, 'container_name'),
            getCosmosContainerSortValue(secondContainer, 'container_name'),
            'container_name',
            'asc',
        );
    });
}

function updateCosmosContainerTableControls(totalCount, visibleCount) {
    const countElement = document.getElementById('cosmos-throughput-container-filter-count');
    if (countElement) {
        countElement.textContent = totalCount > 0 ? `Showing ${visibleCount} of ${totalCount} containers` : '';
    }

    document.querySelectorAll('.cosmos-throughput-container-sort').forEach(button => {
        const fieldName = button.dataset.sortField;
        const isActive = fieldName === currentCosmosContainerSort.field;
        const direction = currentCosmosContainerSort.direction === 'desc' ? 'desc' : 'asc';
        const headerCell = button.closest('th');
        if (headerCell) {
            headerCell.setAttribute('aria-sort', isActive ? (direction === 'desc' ? 'descending' : 'ascending') : 'none');
        }
        const icon = button.querySelector('i');
        if (icon) {
            icon.className = isActive
                ? `bi ${direction === 'desc' ? 'bi-arrow-down-short' : 'bi-arrow-up-short'} ms-1`
                : 'bi bi-arrow-down-up ms-1';
        }
    });
}

function renderCosmosContainerMetrics(containers) {
    const tableBody = document.getElementById('cosmos-throughput-containers-body');
    if (!tableBody) {
        return;
    }

    tableBody.replaceChildren();
    const sourceContainers = Array.isArray(containers) ? containers : [];
    const visibleContainers = getSortedCosmosContainers(getFilteredCosmosContainers(sourceContainers));
    updateCosmosContainerTableControls(sourceContainers.length, visibleContainers.length);

    if (sourceContainers.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 7;
        cell.className = 'text-muted';
        cell.textContent = 'No containers were returned for the configured Cosmos database.';
        row.appendChild(cell);
        tableBody.appendChild(row);
        return;
    }

    if (visibleContainers.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 7;
        cell.className = 'text-muted';
        cell.textContent = 'No containers match the current filter.';
        row.appendChild(cell);
        tableBody.appendChild(row);
        return;
    }

    visibleContainers.forEach(container => {
        const row = document.createElement('tr');
        const containerName = container.container_name || 'database';
        const portalManaged = isCosmosThroughputPortalManaged(container);
        const policyLabel = getCosmosContainerPolicyLabel(container);

        const containerCell = document.createElement('td');
        const containerNameText = document.createElement('span');
        containerNameText.textContent = containerName;
        containerCell.appendChild(containerNameText);
        if (portalManaged) {
            containerCell.appendChild(createCosmosPortalManagedBadge(container));
            const helper = document.createElement('div');
            helper.className = 'small text-muted mt-1';
            helper.textContent = 'Capacity changes must be made in the Azure portal.';
            containerCell.appendChild(helper);
        }
        row.appendChild(containerCell);

        [
            container.mode || 'unknown',
            formatRu(container.current_ru),
            getContainerRuUtilization(container),
            formatRequestUnits(container.request_units),
            policyLabel
        ].forEach(value => {
            const cell = document.createElement('td');
            cell.textContent = value;
            row.appendChild(cell);
        });

        const actionCell = document.createElement('td');
        actionCell.className = 'text-nowrap';
        const actionGroup = document.createElement('div');
        actionGroup.className = 'btn-group btn-group-sm';
        actionGroup.setAttribute('role', 'group');
        actionGroup.setAttribute('aria-label', `Actions for ${containerName}`);
        const configureButton = createIconButton('bi bi-gear', `Configure ${containerName} throughput policy`);
        configureButton.setAttribute('data-bs-toggle', 'modal');
        configureButton.setAttribute('data-bs-target', '#cosmosThroughputContainerModal');
        configureButton.addEventListener('click', () => {
            setCosmosContainerPolicyFilter(containerName);
            renderCosmosContainerPolicyModal(currentCosmosContainers);
        });
        actionGroup.appendChild(configureButton);
        const portalManagedMessage = portalManaged ? getCosmosPortalManagedMessage(container) : '';
        const scaleUpDisabledReason = portalManagedMessage || (isCosmosScaleUpBlockedBySimpleChatLimit(container) ? COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE : '');
        actionGroup.appendChild(createCosmosAutoscaleConversionButton(containerName, container.mode, container.is_scalable, 'btn-outline-secondary', portalManagedMessage));
        actionGroup.appendChild(createManualContainerScaleButton(containerName, 'up', !container.is_scalable || Boolean(scaleUpDisabledReason), scaleUpDisabledReason));
        actionGroup.appendChild(createManualContainerScaleButton(containerName, 'down', !container.is_scalable || portalManaged, portalManagedMessage));
        actionCell.appendChild(actionGroup);
        row.appendChild(actionCell);

        tableBody.appendChild(row);
    });
}

function renderCosmosContainerPolicyModal(containers) {
    const tableBody = document.getElementById('cosmos-throughput-container-policies-body');
    if (!tableBody) {
        return;
    }

    const globalPolicyEnforced = isCosmosContainerPolicyEnforced();
    tableBody.replaceChildren();
    const sourceContainers = Array.isArray(containers) ? containers : [];
    const visibleContainers = getFilteredCosmosPolicyContainers(sourceContainers);
    updateCosmosContainerPolicyFilterControls(sourceContainers.length, visibleContainers.length);
    if (sourceContainers.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 8;
        cell.className = 'text-muted';
        cell.textContent = 'Refresh Cosmos throughput status to load containers.';
        row.appendChild(cell);
        tableBody.appendChild(row);
        return;
    }

    if (visibleContainers.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 8;
        cell.className = 'text-muted';
        cell.textContent = 'No container policies match the current filter.';
        row.appendChild(cell);
        tableBody.appendChild(row);
        return;
    }

    visibleContainers.forEach(container => {
        const containerName = container.container_name || '';
        const policy = getCosmosContainerPolicy(container);
        const portalManaged = isCosmosThroughputPortalManaged(container);
        const row = document.createElement('tr');

        const nameCell = document.createElement('td');
        const nameText = document.createElement('div');
        nameText.className = 'fw-semibold';
        nameText.textContent = containerName;
        if (portalManaged) {
            nameText.appendChild(createCosmosPortalManagedBadge(container));
        }
        const metaText = document.createElement('div');
        metaText.className = 'small text-muted';
        metaText.textContent = portalManaged
            ? `${container.mode || 'unknown'} | ${formatRu(container.current_ru)} | monitor only in SimpleChat`
            : globalPolicyEnforced
            ? `${container.mode || 'unknown'} | ${formatRu(container.current_ru)} | global policy enforced`
            : `${container.mode || 'unknown'} | ${formatRu(container.current_ru)}`;
        nameCell.appendChild(nameText);
        nameCell.appendChild(metaText);
        row.appendChild(nameCell);

        const enabledCell = document.createElement('td');
        enabledCell.appendChild(createPolicyCheckbox(containerName, 'enabled', policy.enabled !== false, 'Enabled'));
        row.appendChild(enabledCell);

        const upCell = document.createElement('td');
        upCell.appendChild(createPolicyCheckbox(containerName, 'auto_scale_up_enabled', policy.auto_scale_up_enabled !== false, 'Auto'));
        upCell.appendChild(createPolicyNumberInput(containerName, 'scale_up_threshold_percent', policy.scale_up_threshold_percent || 90, 1, 100, 1, 'At %'));
        upCell.appendChild(createPolicyNumberInput(containerName, 'scale_up_step_ru', policy.scale_up_step_ru || 1000, 100, null, 100, 'Step RU/s'));
        upCell.appendChild(createPolicyNumberInput(containerName, 'scale_up_cooldown_minutes', policy.scale_up_cooldown_minutes || 5, 1, 1440, 1, 'Interval min'));
        row.appendChild(upCell);

        const downCell = document.createElement('td');
        downCell.appendChild(createPolicyCheckbox(containerName, 'auto_scale_down_enabled', policy.auto_scale_down_enabled !== false, 'Auto'));
        downCell.appendChild(createPolicyNumberInput(containerName, 'scale_down_threshold_percent', policy.scale_down_threshold_percent || 70, 0, 99, 1, 'At %'));
        downCell.appendChild(createPolicyNumberInput(containerName, 'scale_down_step_ru', policy.scale_down_step_ru || 1000, 100, null, 100, 'Step RU/s'));
        downCell.appendChild(createPolicyNumberInput(containerName, 'scale_down_cooldown_minutes', policy.scale_down_cooldown_minutes || 20, 1, 1440, 1, 'Interval min'));
        row.appendChild(downCell);

        const autoscaleCell = document.createElement('td');
        autoscaleCell.appendChild(createPolicyCheckbox(containerName, 'convert_manual_to_autoscale_enabled', policy.convert_manual_to_autoscale_enabled, 'Convert manual'));
        if (policy.last_mode_conversion_at) {
            const helper = document.createElement('div');
            helper.className = 'small text-muted mt-1';
            helper.textContent = `Last converted ${policy.last_mode_conversion_at}`;
            autoscaleCell.appendChild(helper);
        }
        row.appendChild(autoscaleCell);

        const minCell = document.createElement('td');
        minCell.appendChild(createPolicyNumberInput(containerName, 'min_ru', policy.min_ru || 1000, 100, null, 100, 'Min'));
        minCell.appendChild(createPolicyCheckbox(containerName, 'ignore_min_limit', policy.ignore_min_limit, 'Ignore'));
        row.appendChild(minCell);

        const maxCell = document.createElement('td');
        maxCell.appendChild(createPolicyNumberInput(containerName, 'max_ru', policy.max_ru || COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU, 100, COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU, 100, 'Max'));
        maxCell.appendChild(createPolicyCheckbox(containerName, 'ignore_max_limit', policy.ignore_max_limit, 'Ignore'));
        row.appendChild(maxCell);

        const manualCell = document.createElement('td');
        const portalManagedMessage = portalManaged ? getCosmosPortalManagedMessage(container) : '';
        const scaleUpDisabledReason = portalManagedMessage || (isCosmosScaleUpBlockedBySimpleChatLimit(container) ? COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE : '');
        manualCell.appendChild(createCosmosAutoscaleConversionButton(containerName, container.mode, container.is_scalable, 'btn-outline-primary', portalManagedMessage));
        manualCell.appendChild(createManualContainerScaleButton(containerName, 'up', !container.is_scalable || Boolean(scaleUpDisabledReason), scaleUpDisabledReason));
        manualCell.appendChild(createManualContainerScaleButton(containerName, 'down', !container.is_scalable || portalManaged, portalManagedMessage));
        if (portalManaged || !container.is_scalable) {
            const helper = document.createElement('div');
            helper.className = 'small text-muted mt-1';
            helper.textContent = portalManaged ? 'Use Azure portal for capacity changes.' : 'Shared throughput';
            manualCell.appendChild(helper);
        }
        row.appendChild(manualCell);

        if (globalPolicyEnforced || portalManaged) {
            row.querySelectorAll('.cosmos-container-policy-input').forEach(input => {
                input.disabled = true;
            });
        }

        tableBody.appendChild(row);
    });
}

function applyGlobalCosmosContainerPolicyToCurrentContainers() {
    if (!Array.isArray(currentCosmosContainers) || currentCosmosContainers.length === 0) {
        setCosmosThroughputMessage('Refresh Cosmos throughput status before applying the global policy to containers.', 'warning');
        return;
    }

    const policies = readCosmosContainerPolicies();
    currentCosmosContainers.forEach(container => {
        const containerName = container?.container_name || '';
        if (!containerName) {
            return;
        }
        const existingPolicy = policies[containerName] || container?.policy || {};
        policies[containerName] = mergeRuntimePolicyFields(buildGlobalCosmosContainerPolicy(containerName), existingPolicy);
    });

    writeCosmosContainerPolicies(policies);
    renderCosmosContainerMetrics(currentCosmosContainers);
    renderCosmosContainerPolicyModal(currentCosmosContainers);
    setCosmosThroughputMessage('Global container policy is staged for the currently discovered containers. Save Admin Settings to persist it.', 'info');
}

function updateCosmosThroughputStatusPanel(status) {
    const throughput = status?.throughput || {};
    const metrics = status?.metrics || {};
    currentCosmosContainers = status?.containers || [];
    currentCosmosStatusLoaded = true;
    currentCosmosMetricsWindowMinutes = metrics?.window_minutes || Number(document.getElementById('cosmos_throughput_metrics_window_minutes')?.value || 0);
    setElementText('cosmos-throughput-mode', status?.capacity_scope === 'container' ? 'container targeted' : throughput.mode || 'Unknown');
    setElementText('cosmos-throughput-current-ru', formatRu(throughput.current_ru));
    setElementText('cosmos-throughput-utilization', formatPercent(metrics.normalized_ru_percent));
    setElementText('cosmos-throughput-last-checked', status?.last_checked_at || 'Not loaded');
    renderCosmosContainerMetrics(currentCosmosContainers);
    renderCosmosContainerPolicyModal(currentCosmosContainers);

    const databasePortalManaged = isCosmosThroughputPortalManaged(throughput);
    const globalScaleButtonsDisabled = status?.capacity_scope === 'container' || !throughput.is_scalable || databasePortalManaged;
    const globalScaleUpButtonDisabled = globalScaleButtonsDisabled || isCosmosScaleUpBlockedBySimpleChatLimit(throughput);
    const globalConvertButtonDisabled = status?.capacity_scope === 'container' || throughput.mode !== 'manual' || !throughput.is_scalable || databasePortalManaged;
    document.getElementById('cosmos-throughput-convert-autoscale-btn')?.toggleAttribute('disabled', globalConvertButtonDisabled);
    document.getElementById('cosmos-throughput-scale-up-btn')?.toggleAttribute('disabled', globalScaleUpButtonDisabled);
    document.getElementById('cosmos-throughput-scale-down-btn')?.toggleAttribute('disabled', globalScaleButtonsDisabled);
}

function hasContainerLevelCosmosMetrics(status) {
    return (status?.containers || []).some(container => (
        container?.normalized_ru_percent !== null
        && container?.normalized_ru_percent !== undefined
    ) || (
        container?.request_units !== null
        && container?.request_units !== undefined
    ));
}

function hasPortalManagedCosmosThroughput(status) {
    return Boolean(status?.throughput?.portal_managed_scaling_required) || (status?.containers || []).some(container => (
        isCosmosThroughputPortalManaged(container)
    ));
}

function getCachedCosmosThroughputStatus() {
    const cachedStatus = window.cosmosThroughputCachedStatus;
    if (!cachedStatus || typeof cachedStatus !== 'object' || Array.isArray(cachedStatus)) {
        return null;
    }

    const hasStatusData = Boolean(
        cachedStatus.last_checked_at
        || cachedStatus.capacity_scope
        || (Array.isArray(cachedStatus.containers) && cachedStatus.containers.length > 0)
    );
    return hasStatusData ? cachedStatus : null;
}

function initializeCosmosThroughputStatusView() {
    const cachedStatus = getCachedCosmosThroughputStatus();
    const automationEnabled = isFieldChecked('cosmos_throughput_autoscale_enabled');

    if (cachedStatus) {
        updateCosmosThroughputStatusPanel(cachedStatus);
        const refreshText = automationEnabled
            ? 'Background automation refreshes this saved view on the Metrics Window cadence while enabled.'
            : 'Automation is currently disabled; use Refresh to update this saved view.';
        setCosmosThroughputMessage(`Showing last saved Cosmos throughput status. ${refreshText}`, 'info');
        return;
    }

    if (automationEnabled) {
        setCosmosThroughputMessage('No saved Cosmos throughput status is available yet. Loading the first status check now...', 'info');
        loadCosmosThroughputStatus();
    }
}

async function loadCosmosThroughputStatus(event = null) {
    const triggerButton = event?.currentTarget || document.getElementById('cosmos-throughput-refresh-btn');
    if (triggerButton) {
        setButtonBusy(triggerButton, true, 'Loading...');
    }
    setCosmosThroughputMessage('Loading Cosmos throughput status...', 'info');

    try {
        const response = await fetch('/api/admin/settings/cosmos-throughput/status', {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin'
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to load Cosmos throughput status.');
        }

        updateCosmosThroughputStatusPanel(data);
        if (!data.configured) {
            setCosmosThroughputMessage(data.error || 'Cosmos throughput management needs subscription, resource group, account, and database settings.', 'warning');
        } else if (data.throughput_error) {
            setCosmosThroughputMessage(`Cosmos database throughput could not be read. ${data.throughput_error}`, 'danger');
        } else if (data.capacity_scope === 'container' && data.metrics?.normalized_ru_percent !== null && data.metrics?.normalized_ru_percent !== undefined && !hasContainerLevelCosmosMetrics(data)) {
            setCosmosThroughputMessage('Azure Monitor returned aggregate RU utilization, but not per-container metric dimensions for this window. Container autoscale waits for per-container utilization before scaling individual containers; Refresh again after a few minutes.', 'warning');
        } else if (hasPortalManagedCosmosThroughput(data)) {
            setCosmosThroughputMessage('One or more Cosmos throughput targets are above 10,000 RU/s. SimpleChat will monitor utilization and request units only; use the Azure portal for capacity changes, which can take 4 to 6 hours.', 'warning');
        } else if (data.capacity_scope === 'container') {
            setCosmosThroughputMessage('Container-targeted throughput is active. Dedicated-throughput containers can be monitored and scaled individually; containers sharing database throughput remain view-only.', 'info');
        } else if (data.metric_error) {
            setCosmosThroughputMessage('Throughput loaded, but Azure Monitor metrics are unavailable. Check the app identity permissions and Cosmos metrics availability.', 'warning');
        } else {
            setCosmosThroughputMessage('Cosmos throughput status loaded.', 'success');
        }
    } catch (error) {
        setCosmosThroughputMessage(error.message || 'Failed to load Cosmos throughput status.', 'danger');
    } finally {
        if (triggerButton) {
            setButtonBusy(triggerButton, false);
        }
    }
}

function buildCosmosThroughputAccessPayload() {
    return {
        cosmos_throughput_autoscale_enabled: isFieldChecked('cosmos_throughput_autoscale_enabled'),
        cosmos_throughput_auto_scale_up_enabled: isFieldChecked('cosmos_throughput_auto_scale_up_enabled'),
        cosmos_throughput_auto_scale_down_enabled: isFieldChecked('cosmos_throughput_auto_scale_down_enabled'),
        cosmos_throughput_subscription_id: getFieldValue('cosmos_throughput_subscription_id'),
        cosmos_throughput_resource_group: getFieldValue('cosmos_throughput_resource_group'),
        cosmos_throughput_account_name: getFieldValue('cosmos_throughput_account_name'),
        cosmos_throughput_database_name: getFieldValue('cosmos_throughput_database_name'),
        cosmos_throughput_metrics_window_minutes: getNumericFieldValue('cosmos_throughput_metrics_window_minutes', 5),
        cosmos_throughput_scale_up_threshold_percent: getNumericFieldValue('cosmos_throughput_scale_up_threshold_percent', 90),
        cosmos_throughput_scale_down_threshold_percent: getNumericFieldValue('cosmos_throughput_scale_down_threshold_percent', 70),
        cosmos_throughput_scale_up_step_ru: getNumericFieldValue('cosmos_throughput_scale_up_step_ru', 1000),
        cosmos_throughput_scale_down_step_ru: getNumericFieldValue('cosmos_throughput_scale_down_step_ru', 1000),
        cosmos_throughput_scale_up_cooldown_minutes: getNumericFieldValue('cosmos_throughput_scale_up_cooldown_minutes', 5),
        cosmos_throughput_scale_down_cooldown_minutes: getNumericFieldValue('cosmos_throughput_scale_down_cooldown_minutes', 20),
        cosmos_throughput_min_ru: getNumericFieldValue('cosmos_throughput_min_ru', 1000),
        cosmos_throughput_max_ru: getNumericFieldValue('cosmos_throughput_max_ru', COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU),
        cosmos_throughput_ignore_min_limit: isFieldChecked('cosmos_throughput_ignore_min_limit'),
        cosmos_throughput_ignore_max_limit: isFieldChecked('cosmos_throughput_ignore_max_limit'),
        cosmos_throughput_convert_manual_to_autoscale_enabled: isFieldChecked('cosmos_throughput_convert_manual_to_autoscale_enabled'),
        cosmos_throughput_enforce_container_defaults: isFieldChecked('cosmos_throughput_enforce_container_defaults'),
        cosmos_throughput_container_policies: collectCosmosContainerPolicies()
    };
}

async function validateCosmosThroughputAccess(triggerButton = null) {
    const button = triggerButton || document.getElementById('cosmos-throughput-validate-access-btn');
    if (button) {
        setButtonBusy(button, true, 'Validating...');
    }
    setCosmosThroughputMessage('Validating Cosmos throughput configuration and access...', 'info');

    try {
        const response = await fetch('/api/admin/settings/cosmos-throughput/validate-access', {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin',
            body: JSON.stringify(buildCosmosThroughputAccessPayload())
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to validate Cosmos throughput access.');
        }

        if (data.status?.configured) {
            updateCosmosThroughputStatusPanel(data.status);
        }
        setCosmosThroughputValidationResult(data);
    } catch (error) {
        setCosmosThroughputMessage(error.message || 'Failed to validate Cosmos throughput access.', 'danger');
    } finally {
        if (button) {
            setButtonBusy(button, false);
        }
    }
}

async function manuallyScaleCosmosThroughput(direction, containerName = '', triggerButton = null) {
    const button = triggerButton || document.getElementById(`cosmos-throughput-scale-${direction}-btn`);
    if (button) {
        setButtonBusy(button, true, direction === 'up' ? 'Scaling up...' : 'Scaling down...');
    }
    const targetText = containerName ? ` for ${containerName}` : '';
    setCosmosThroughputMessage(direction === 'up' ? `Submitting scale-up request${targetText}...` : `Submitting scale-down request${targetText}...`, 'info');

    try {
        const response = await fetch('/api/admin/settings/cosmos-throughput/scale', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ direction, container_name: containerName })
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Cosmos throughput scale request failed.');
        }

        const scaledTarget = data.container_name ? ` for ${data.container_name}` : '';
        setCosmosThroughputMessage(`Cosmos throughput${scaledTarget} changed from ${formatRu(data.from_ru)} to ${formatRu(data.to_ru)}.`, 'success');
        await loadCosmosThroughputStatus();
    } catch (error) {
        setCosmosThroughputMessage(error.message || 'Cosmos throughput scale request failed.', 'danger');
    } finally {
        if (button) {
            setButtonBusy(button, false, direction === 'up' ? 'Scale Up' : 'Scale Down');
        }
    }
}

async function convertCosmosThroughputToAutoscale(containerName = '', triggerButton = null) {
    const targetText = containerName ? ` for ${containerName}` : '';
    if (triggerButton) {
        setButtonBusy(triggerButton, true, 'Converting...');
    }
    setCosmosThroughputMessage(`Converting manual Cosmos throughput${targetText} to native autoscale...`, 'info');

    try {
        const response = await fetch('/api/admin/settings/cosmos-throughput/convert-autoscale', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ container_name: containerName })
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Cosmos throughput mode conversion failed.');
        }

        const convertedTarget = data.container_name ? ` for ${data.container_name}` : '';
        setCosmosThroughputMessage(`Cosmos throughput${convertedTarget} converted from manual ${formatRu(data.from_ru)} to autoscale max ${formatRu(data.to_ru)}.`, 'success');
        await loadCosmosThroughputStatus();
    } catch (error) {
        setCosmosThroughputMessage(error.message || 'Cosmos throughput mode conversion failed.', 'danger');
    } finally {
        if (triggerButton) {
            setButtonBusy(triggerButton, false);
        }
    }
}

function renderRedisMonitoringStatus(statusPayload) {
    const configuration = statusPayload?.configuration || {};
    const runtime = statusPayload?.runtime || {};
    const health = statusPayload?.health || {};
    const memory = statusPayload?.memory || {};
    const clients = statusPayload?.clients || {};
    const stats = statusPayload?.stats || {};
    const keyspace = statusPayload?.keyspace || {};
    const server = statusPayload?.server || {};
    const daiCache = statusPayload?.dai_cache || {};

    let configurationText = 'Disabled';
    let configurationVariant = 'secondary';
    if (configuration.enabled && configuration.configured) {
        configurationText = 'Enabled';
        configurationVariant = 'success';
    } else if (configuration.enabled) {
        configurationText = 'Needs host';
        configurationVariant = 'warning';
    }

    setRedisMonitoringBadge('redis-monitoring-config-status', configurationText, configurationVariant);
    setRedisMonitoringBadge(
        'redis-monitoring-health-status',
        formatRedisStatus(health.status),
        getRedisMonitoringStatusVariant(health.status)
    );
    setRedisMonitoringBadge(
        'redis-monitoring-app-cache-status',
        formatRedisRuntime(runtime.app_cache_using_redis),
        runtime.app_cache_using_redis ? 'success' : 'secondary'
    );
    setRedisMonitoringBadge(
        'redis-monitoring-session-status',
        formatRedisRuntime(runtime.session_using_redis),
        runtime.session_using_redis ? 'success' : 'secondary'
    );

    setElementText('redis-monitoring-ping-latency', formatRedisMetric(health.ping_latency_ms, 'ms'));
    setElementText('redis-monitoring-memory-usage', formatRedisMemoryUsage(memory));
    setElementText(
        'redis-monitoring-memory-policy',
        memory.maxmemory_policy ? `Policy: ${memory.maxmemory_policy}` : 'Policy: Not available'
    );
    setElementText('redis-monitoring-connected-clients', formatNumber(clients.connected_clients));
    setElementText('redis-monitoring-ops-per-sec', formatNumber(stats.instantaneous_ops_per_sec));
    setElementText('redis-monitoring-hit-rate', formatRedisPercent(stats.keyspace_hit_rate_percent));
    setElementText('redis-monitoring-key-count', formatNumber(keyspace.total_keys));
    setElementText('redis-monitoring-dai-version-markers', formatNumber(daiCache.version_marker_count));
    setElementText(
        'redis-monitoring-dai-version-marker-expiry',
        `${formatNumber(daiCache.version_marker_no_expiry_count)} no-expiry marker(s)`
    );
    setElementText('redis-monitoring-dai-payload-keys', formatNumber(daiCache.payload_key_count));
    setElementText(
        'redis-monitoring-dai-version-ttl-policy',
        `Version TTL: ${formatRedisExplorerTtl(daiCache.version_marker_ttl_seconds)}`
    );
    setElementText('redis-monitoring-expired-keys', formatNumber(stats.expired_keys));
    setElementText('redis-monitoring-evicted-keys', formatNumber(stats.evicted_keys));
    setElementText('redis-monitoring-fragmentation', formatNumber(memory.mem_fragmentation_ratio));
    setElementText('redis-monitoring-errors', formatNumber(stats.total_error_replies));
    setElementText('redis-monitoring-rejected-connections', formatNumber(stats.rejected_connections));
    setElementText('redis-monitoring-version', server.redis_version || 'Not available');
    setElementText('redis-monitoring-source', formatRedisStatus(runtime.monitoring_source));
    setElementText('redis-monitoring-checked-at', statusPayload?.checked_at || 'Not available');
    setElementText('redis-monitoring-last-error', health.last_error || 'None');
}

async function loadRedisMonitoringStatus(event = null, options = {}) {
    const showLoading = options.showLoading !== false;
    const triggerButton = event?.currentTarget || (showLoading ? document.getElementById('redis-monitoring-refresh-btn') : null);
    if (triggerButton) {
        setButtonBusy(triggerButton, true, 'Loading...');
    }
    if (showLoading) {
        setRedisMonitoringMessage('Loading Redis monitoring status...', 'info');
    }

    try {
        const response = await fetch('/api/admin/settings/redis-monitoring/status', {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin'
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to load Redis monitoring status.');
        }

        renderRedisMonitoringStatus(data);
        if (data.health?.status === 'healthy') {
            setRedisMonitoringMessage('Redis monitoring status loaded.', 'success');
        } else if (data.health?.last_error) {
            setRedisMonitoringMessage(data.health.last_error, data.health.status === 'error' ? 'danger' : 'warning');
        } else if (showLoading) {
            setRedisMonitoringMessage('Redis monitoring status loaded.', 'info');
        }
    } catch (error) {
        setRedisMonitoringMessage(error.message || 'Failed to load Redis monitoring status.', 'danger');
    } finally {
        if (triggerButton) {
            setButtonBusy(triggerButton, false);
        }
    }
}

function setRedisExplorerMessage(message, variant = 'info') {
    const messageElement = document.getElementById('redis-explorer-message');
    if (!messageElement) {
        return;
    }

    messageElement.textContent = message || '';
    messageElement.className = `alert alert-${variant} small`;
    messageElement.classList.toggle('d-none', !message);
}

function formatRedisExplorerTtl(ttlSeconds) {
    const numericValue = Number(ttlSeconds);
    if (Number.isNaN(numericValue)) {
        return 'Not available';
    }
    if (numericValue === -2) {
        return 'Expired or missing';
    }
    if (numericValue === -1) {
        return 'No expiry';
    }
    return `${numericValue.toLocaleString()} sec`;
}

function formatRedisExplorerMemory(bytes) {
    const numericValue = Number(bytes);
    if (Number.isNaN(numericValue) || numericValue < 0) {
        return 'Not available';
    }
    if (numericValue >= 1024 * 1024) {
        return `${(numericValue / (1024 * 1024)).toLocaleString(undefined, { maximumFractionDigits: 2 })} MB`;
    }
    if (numericValue >= 1024) {
        return `${(numericValue / 1024).toLocaleString(undefined, { maximumFractionDigits: 2 })} KB`;
    }
    return `${numericValue.toLocaleString()} bytes`;
}


function formatRedisExplorerResolutionLabel(resolution) {
    if (!resolution) {
        return '';
    }
    if (resolution.resolved && resolution.entity_type) {
        const entityType = formatRedisStatus(resolution.entity_type);
        const entityName = resolution.entity_name || resolution.entity_id || 'Unknown';
        return `${resolution.label || 'SimpleChat entity'}: ${entityType} - ${entityName}`;
    }
    return resolution.label || '';
}


function formatRedisExplorerResolutionEntity(resolution) {
    if (!resolution) {
        return 'Not resolved';
    }
    if (!resolution.resolved) {
        return formatRedisStatus(resolution.resolution_status || 'unresolved');
    }
    const parts = [];
    if (resolution.entity_type) {
        parts.push(`Entity: ${formatRedisStatus(resolution.entity_type)}`);
    }
    if (resolution.entity_name) {
        parts.push(`Name: ${resolution.entity_name}`);
    }
    if (resolution.entity_status) {
        parts.push(`Status: ${formatRedisStatus(resolution.entity_status)}`);
    }
    if (Number.isFinite(Number(resolution.row_count))) {
        parts.push(`DAI rows: ${formatNumber(resolution.row_count)}`);
    }
    return parts.join(' | ') || 'Resolved';
}


function renderRedisExplorerResolution(resolution) {
    const resolutionCard = document.getElementById('redis-explorer-resolution-card');
    if (!resolutionCard) {
        return;
    }

    resolutionCard.classList.toggle('d-none', !resolution);
    if (!resolution) {
        return;
    }

    setElementText('redis-explorer-resolution-kind', resolution.label || formatRedisStatus(resolution.kind));
    setElementText('redis-explorer-resolution-entity', formatRedisExplorerResolutionEntity(resolution));
    setElementText('redis-explorer-resolution-scope', resolution.scope_key || resolution.cache_hash || resolution.scope_hash || 'No reversible scope key available');
    setElementText('redis-explorer-resolution-note', resolution.note || 'Resolved from Redis key classification.');
}


function setRedisExplorerPreviewVisible(isVisible) {
    document.getElementById('redis-explorer-preview-empty')?.classList.toggle('d-none', isVisible);
    document.getElementById('redis-explorer-preview-panel')?.classList.toggle('d-none', !isVisible);
}

function resetRedisExplorerPreview() {
    redisExplorerState.selectedKey = '';
    setRedisExplorerPreviewVisible(false);
    setElementText('redis-explorer-preview-key', 'Not loaded');
    setElementText('redis-explorer-preview-type', 'Not loaded');
    setElementText('redis-explorer-preview-ttl', 'Not loaded');
    setElementText('redis-explorer-preview-memory', 'Not loaded');
    setElementText('redis-explorer-preview-redacted', 'Not loaded');
    setElementText('redis-explorer-preview-content', 'Not loaded');
    renderRedisExplorerResolution(null);
}

function getRedisExplorerScopeLabel() {
    const filter = (redisExplorerState.filter || '').trim();
    return filter ? `Filter: "${filter}"` : 'Browsing all keys';
}

function renderRedisExplorerKeys(payload) {
    const keyList = document.getElementById('redis-explorer-key-list');
    if (!keyList) {
        return;
    }

    const keys = Array.isArray(payload?.keys) ? payload.keys : [];
    keyList.replaceChildren();
    const pageNumber = redisExplorerState.cursorHistory.length + 1;
    setElementText(
        'redis-explorer-key-count',
        `${getRedisExplorerScopeLabel()} | Page ${formatNumber(pageNumber)} | ${formatNumber(keys.length)} key(s)${payload?.has_more ? ' / more available' : ''}`
    );

    if (keys.length === 0) {
        const emptyState = document.createElement('div');
        emptyState.className = 'list-group-item text-muted small';
        emptyState.textContent = 'No Redis keys matched this page and filter.';
        keyList.appendChild(emptyState);
    } else {
        keys.forEach(item => {
            const keyButton = document.createElement('button');
            keyButton.type = 'button';
            keyButton.className = 'list-group-item list-group-item-action';
            keyButton.setAttribute('role', 'option');

            const keyName = document.createElement('div');
            keyName.className = 'fw-semibold text-break';
            keyName.textContent = item.key || '(empty key)';

            const metadata = document.createElement('div');
            metadata.className = 'small text-muted';
            metadata.textContent = [
                `Type: ${formatRedisStatus(item.type || 'unknown')}`,
                `TTL: ${formatRedisExplorerTtl(item.ttl_seconds)}`,
                item.preview_restricted ? 'Preview: restricted' : 'Preview: sanitized'
            ].join(' | ');

            keyButton.appendChild(keyName);
            keyButton.appendChild(metadata);
            const resolutionLabel = formatRedisExplorerResolutionLabel(item.resolution);
            if (resolutionLabel) {
                const resolutionMetadata = document.createElement('div');
                resolutionMetadata.className = 'small text-primary';
                resolutionMetadata.textContent = resolutionLabel;
                keyButton.appendChild(resolutionMetadata);
            }
            keyButton.addEventListener('click', () => loadRedisExplorerValue(item.key, keyButton));
            keyList.appendChild(keyButton);
        });
    }
    keyList.scrollTop = 0;

    redisExplorerState.nextCursor = String(payload?.next_cursor || '0');
    document.getElementById('redis-explorer-prev-btn')?.toggleAttribute(
        'disabled',
        redisExplorerState.cursorHistory.length === 0
    );
    document.getElementById('redis-explorer-next-btn')?.toggleAttribute(
        'disabled',
        !payload?.has_more
    );
}

function getRedisExplorerRequestState(options = {}) {
    const reset = Boolean(options.reset);
    const filterInput = document.getElementById('redis-explorer-filter');
    const pageSizeSelect = document.getElementById('redis-explorer-page-size');
    if (reset) {
        redisExplorerState.cursor = '0';
        redisExplorerState.nextCursor = '0';
        redisExplorerState.cursorHistory = [];
    }
    redisExplorerState.filter = filterInput?.value || '';
    redisExplorerState.pageSize = Number(pageSizeSelect?.value || 25);
    return {
        cursor: redisExplorerState.cursor,
        filter: redisExplorerState.filter,
        pageSize: redisExplorerState.pageSize
    };
}

async function loadRedisExplorerKeys(options = {}) {
    const triggerButton = options.triggerButton || null;
    if (triggerButton) {
        setButtonBusy(triggerButton, true, 'Loading...');
    }
    setRedisExplorerMessage('Loading Redis keys...', 'info');
    resetRedisExplorerPreview();

    try {
        const requestState = getRedisExplorerRequestState(options);
        const query = new URLSearchParams({
            cursor: requestState.cursor,
            page_size: String(requestState.pageSize),
            filter: requestState.filter
        });
        const response = await fetch(`/api/admin/settings/redis-explorer/keys?${query.toString()}`, {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin'
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || data.last_error || 'Failed to load Redis keys.');
        }

        renderRedisExplorerKeys(data);
        redisExplorerState.loaded = true;
        setRedisExplorerMessage(`${getRedisExplorerScopeLabel()} loaded. Select a key to view sanitized preview content.`, 'success');
    } catch (error) {
        renderRedisExplorerKeys({ keys: [], has_more: false, next_cursor: '0' });
        setRedisExplorerMessage(error.message || 'Failed to load Redis keys.', 'danger');
    } finally {
        if (triggerButton) {
            setButtonBusy(triggerButton, false);
        }
    }
}

async function loadRedisExplorerValue(key, triggerButton = null) {
    if (!key) {
        return;
    }
    if (triggerButton) {
        setButtonBusy(triggerButton, true, 'Loading...');
    }
    setRedisExplorerMessage('Loading sanitized Redis key preview...', 'info');

    try {
        const response = await fetch('/api/admin/settings/redis-explorer/value', {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin',
            body: JSON.stringify({ key })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || data.preview || 'Failed to load Redis key preview.');
        }

        redisExplorerState.selectedKey = key;
        setRedisExplorerPreviewVisible(true);
        setElementText('redis-explorer-preview-key', data.key || key);
        setElementText('redis-explorer-preview-type', formatRedisStatus(data.type || 'unknown'));
        setElementText('redis-explorer-preview-ttl', formatRedisExplorerTtl(data.ttl_seconds));
        setElementText('redis-explorer-preview-memory', formatRedisExplorerMemory(data.memory_usage_bytes));
        setElementText(
            'redis-explorer-preview-redacted',
            data.preview_restricted ? 'Restricted' : data.redacted ? 'Redacted' : 'Sanitized'
        );
        renderRedisExplorerResolution(data.resolution);
        setElementText('redis-explorer-preview-content', data.preview || 'No preview available.');
        const previewContent = document.getElementById('redis-explorer-preview-content');
        if (previewContent) {
            previewContent.scrollTop = 0;
        }
        setRedisExplorerMessage(
            data.truncated ? 'Preview loaded and truncated to the safe display limit.' : 'Sanitized preview loaded.',
            data.preview_restricted || data.redacted || data.truncated ? 'warning' : 'success'
        );
    } catch (error) {
        setRedisExplorerMessage(error.message || 'Failed to load Redis key preview.', 'danger');
    } finally {
        if (triggerButton) {
            setButtonBusy(triggerButton, false);
        }
    }
}

function setupRedisExplorerControls() {
    const modalElement = document.getElementById('redisExplorerModal');
    if (!modalElement) {
        return;
    }

    modalElement.addEventListener('shown.bs.modal', () => {
        if (!redisExplorerState.loaded) {
            loadRedisExplorerKeys({ reset: true });
        }
    });
    document.getElementById('redis-explorer-search-btn')?.addEventListener('click', event => {
        loadRedisExplorerKeys({ reset: true, triggerButton: event.currentTarget });
    });
    document.getElementById('redis-explorer-browse-all-btn')?.addEventListener('click', event => {
        const filterInput = document.getElementById('redis-explorer-filter');
        if (filterInput) {
            filterInput.value = '';
        }
        loadRedisExplorerKeys({ reset: true, triggerButton: event.currentTarget });
    });
    document.getElementById('redis-explorer-refresh-btn')?.addEventListener('click', event => {
        loadRedisExplorerKeys({ triggerButton: event.currentTarget });
    });
    document.getElementById('redis-explorer-filter')?.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            event.preventDefault();
            loadRedisExplorerKeys({ reset: true });
        }
    });
    document.getElementById('redis-explorer-page-size')?.addEventListener('change', () => {
        loadRedisExplorerKeys({ reset: true });
    });
    document.getElementById('redis-explorer-next-btn')?.addEventListener('click', event => {
        redisExplorerState.cursorHistory.push(redisExplorerState.cursor);
        redisExplorerState.cursor = redisExplorerState.nextCursor || '0';
        loadRedisExplorerKeys({ triggerButton: event.currentTarget });
    });
    document.getElementById('redis-explorer-prev-btn')?.addEventListener('click', event => {
        redisExplorerState.cursor = redisExplorerState.cursorHistory.pop() || '0';
        loadRedisExplorerKeys({ triggerButton: event.currentTarget });
    });
}

function setupRedisMonitoringControls() {
    const section = document.getElementById('redis-monitoring-section');
    if (!section) {
        return;
    }

    document.getElementById('redis-monitoring-refresh-btn')?.addEventListener('click', loadRedisMonitoringStatus);
    setupRedisExplorerControls();
    loadRedisMonitoringStatus(null, { showLoading: false });
}

function setDocumentAccessIndexMessage(message, variant = 'info') {
    const messageElement = document.getElementById('document-access-index-message');
    if (!messageElement) {
        return;
    }

    messageElement.textContent = message || '';
    messageElement.className = `alert alert-${variant} small mb-3`;
    messageElement.classList.toggle('d-none', !message);
}

function formatDocumentAccessIndexStatus(value) {
    const normalizedValue = String(value || '').trim();
    if (!normalizedValue) {
        return 'Not loaded';
    }

    return normalizedValue
        .replace(/_/g, ' ')
        .replace(/\b\w/g, character => character.toUpperCase());
}

function getDocumentAccessIndexStatusVariant(value) {
    const normalizedValue = String(value || '').trim().toLowerCase();
    if (['succeeded', 'skipped_completed', 'completed', 'dry_run_completed', 'reconciled', 'matched', 'aligned'].includes(normalizedValue)) {
        return 'success';
    }
    if (['running', 'in_progress'].includes(normalizedValue)) {
        return 'primary';
    }
    if (['succeeded_with_errors', 'completed_with_errors', 'reconciled_with_errors', 'mismatch', 'missing_expected_indexes'].includes(normalizedValue)) {
        return 'warning';
    }
    if (['failed', 'error'].includes(normalizedValue)) {
        return 'danger';
    }
    return 'secondary';
}

function setDocumentAccessIndexBadge(elementId, value, variant = 'secondary') {
    const badge = document.getElementById(elementId);
    if (!badge) {
        return;
    }

    const safeVariants = new Set(['primary', 'secondary', 'success', 'danger', 'warning', 'info']);
    badge.textContent = value || 'Not loaded';
    badge.className = `badge text-bg-${safeVariants.has(variant) ? variant : 'secondary'}`;
}

function formatDocumentAccessIndexBoolean(value, enabledText = 'Enabled', disabledText = 'Disabled') {
    return value ? enabledText : disabledText;
}

function formatDocumentAccessIndexList(items) {
    if (!Array.isArray(items) || items.length === 0) {
        return 'None';
    }

    return items.map(item => String(item || '').trim()).filter(Boolean).join(', ') || 'None';
}

function formatDocumentAccessIndexMetric(value, unit) {
    if (value === null || value === undefined || value === '') {
        return 'Not available';
    }
    const numericValue = Number(value);
    if (Number.isNaN(numericValue)) {
        return 'Not available';
    }
    return `${numericValue.toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unit}`;
}

function formatDocumentAccessIndexPercent(value) {
    if (value === null || value === undefined || value === '') {
        return 'Not available';
    }
    const numericValue = Number(value);
    if (Number.isNaN(numericValue)) {
        return 'Not available';
    }
    return `${numericValue.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
}

function formatDocumentAccessIndexMetricPair(sourceValue, projectionValue, unit) {
    const sourceMetric = formatDocumentAccessIndexMetric(sourceValue, unit);
    const projectionMetric = formatDocumentAccessIndexMetric(projectionValue, unit);
    if (sourceMetric === 'Not available' || projectionMetric === 'Not available') {
        return 'Not available';
    }
    return `${sourceMetric} / ${projectionMetric}`;
}

function formatDocumentAccessIndexSavings(value, unit, positiveLabel, negativeLabel) {
    if (value === null || value === undefined || value === '') {
        return 'Not available';
    }
    const numericValue = Number(value);
    if (Number.isNaN(numericValue)) {
        return 'Not available';
    }
    if (Math.abs(numericValue) < 0.001) {
        return `0 ${unit} difference`;
    }
    const label = numericValue > 0 ? positiveLabel : negativeLabel;
    return `${formatDocumentAccessIndexMetric(Math.abs(numericValue), unit)} ${label}`;
}

function getDocumentAccessIndexRollingWindow(shadowValidation, windowKey) {
    const windows = shadowValidation?.rolling_metrics?.windows || {};
    return windows[windowKey] || {};
}

function getDocumentAccessIndexReadWindow(readMetrics, windowKey) {
    const windows = readMetrics?.windows || {};
    return windows[windowKey] || {};
}

function getDocumentAccessIndexCacheWindow(cacheMetrics, windowKey) {
    const windows = cacheMetrics?.windows || {};
    return windows[windowKey] || {};
}

function formatConversationCacheOperationCounts(operationCounts) {
    const entries = Object.entries(operationCounts || {})
        .filter(([, count]) => Number(count || 0) > 0)
        .sort(([left], [right]) => left.localeCompare(right));
    if (entries.length === 0) {
        return 'No samples';
    }

    return entries
        .map(([operation, count]) => `${formatDocumentAccessIndexStatus(operation)}: ${formatNumber(count)}`)
        .join(', ');
}

function formatDocumentAccessIndexSampleSummary(windowMetrics) {
    if (!windowMetrics || Number(windowMetrics.sample_count || 0) === 0) {
        return 'No samples';
    }

    const sampleCount = formatNumber(windowMetrics.sample_count || 0);
    const matchedCount = formatNumber(windowMetrics.matched_count || 0);
    const mismatchCount = formatNumber(windowMetrics.mismatch_count || 0);
    const errorCount = formatNumber(windowMetrics.error_count || 0);
    const comparableCount = formatNumber(windowMetrics.comparable_sample_count || 0);
    return `${sampleCount} samples (${comparableCount} comparable, ${matchedCount} matched, ${mismatchCount} mismatch, ${errorCount} error)`;
}

function formatDocumentAccessIndexReadSample(sample) {
    if (!sample) {
        return 'No samples';
    }
    const status = formatDocumentAccessIndexStatus(sample.status || 'unknown');
    const operation = formatDocumentAccessIndexStatus(sample.operation || 'read');
    const scope = sample.source_scope ? ` / ${sample.source_scope}` : '';
    return `${status} (${operation}${scope})`;
}

function formatDocumentAccessIndexCacheEvent(sample) {
    if (!sample) {
        return 'No cache events';
    }
    const eventType = formatDocumentAccessIndexStatus(sample.event_type || 'unknown');
    const operation = formatDocumentAccessIndexStatus(sample.operation || 'cache');
    const reason = sample.reason ? ` / ${formatDocumentAccessIndexStatus(sample.reason)}` : '';
    return `${eventType} (${operation}${reason})`;
}

function formatDocumentAccessIndexLatencyWindow(windowMetrics) {
    const averageLatency = formatDocumentAccessIndexMetric(windowMetrics?.elapsed_ms_avg, 'ms');
    const p95Latency = formatDocumentAccessIndexMetric(windowMetrics?.elapsed_ms_p95, 'ms');
    if (averageLatency === 'Not available' && p95Latency === 'Not available') {
        return 'Not available';
    }
    return `${averageLatency} / ${p95Latency}`;
}

function renderConversationCacheStatus(statusPayload) {
    const conversationCache = statusPayload?.conversation_cache || {};
    const settings = conversationCache?.settings || {};
    const metrics = conversationCache?.metrics || {};
    const cache15m = getDocumentAccessIndexCacheWindow(metrics, '15m');
    const cacheEnabled = settings.enabled !== false;
    const ttlSeconds = Number(settings.ttl_seconds ?? 120);
    const runtimeStatus = cacheEnabled
        ? (ttlSeconds > 0 ? `Enabled / ${formatDocumentAccessIndexMetric(ttlSeconds, 'sec')}` : 'Enabled / Writes disabled')
        : 'Disabled';

    setDocumentAccessIndexBadge(
        'conversation-cache-runtime-status',
        runtimeStatus,
        cacheEnabled ? 'success' : 'secondary'
    );
    setElementText(
        'conversation-cache-15m-hit-rate',
        formatDocumentAccessIndexPercent(cache15m.hit_rate_percent)
    );
    setElementText(
        'conversation-cache-15m-hits-misses',
        `${formatNumber(cache15m.hit_count || 0)} / ${formatNumber(cache15m.miss_count || 0)}`
    );
    setElementText(
        'conversation-cache-15m-bypasses-errors',
        `${formatNumber(cache15m.bypass_count || 0)} / ${formatNumber(cache15m.error_count || 0)}`
    );
    setElementText(
        'conversation-cache-15m-writes-invalidations',
        `${formatNumber(cache15m.write_count || 0)} / ${formatNumber(cache15m.invalidation_count || 0)}`
    );
    setElementText(
        'conversation-cache-15m-operation-counts',
        formatConversationCacheOperationCounts(cache15m.operation_counts)
    );
    setElementText(
        'conversation-cache-last-event',
        formatDocumentAccessIndexCacheEvent(metrics.last_event)
    );
    setElementText(
        'conversation-cache-last-invalidation',
        formatDocumentAccessIndexCacheEvent(metrics.last_invalidation)
    );
}

function setCosmosMaintenanceMessage(message, variant = 'info') {
    const messageElement = document.getElementById('cosmos-maintenance-message');
    if (!messageElement) {
        return;
    }

    messageElement.textContent = message || '';
    messageElement.className = `alert alert-${variant} small mb-3`;
    messageElement.classList.toggle('d-none', !message);
}

function getCosmosIndexingPolicyStatusText(indexingPolicy) {
    if (!indexingPolicy || Object.keys(indexingPolicy).length === 0) {
        return 'not_loaded';
    }
    if (Number(indexingPolicy.failed_container_count || 0) > 0) {
        return 'failed';
    }
    if (Number(indexingPolicy.containers_missing_expected_indexes || 0) > 0) {
        return 'missing_expected_indexes';
    }
    return 'aligned';
}

function formatStaleCacheCleanupCategories(categories) {
    if (!Array.isArray(categories) || categories.length === 0) {
        return 'No categories';
    }

    return categories
        .map(category => {
            const name = formatDocumentAccessIndexStatus(category.category || 'unknown');
            const candidates = formatNumber(category.candidate_count || 0);
            const deleted = formatNumber(category.deleted_count || 0);
            const failed = formatNumber(category.failed_count || 0);
            return `${name}: ${candidates} candidates / ${deleted} deleted / ${failed} failed`;
        })
        .join('; ');
}

function renderCosmosMaintenanceStatus(statusPayload) {
    const indexingPolicy = statusPayload?.cosmos_indexing_policies || {};
    const cleanup = statusPayload?.stale_cache_cleanup || {};
    const indexingStatus = getCosmosIndexingPolicyStatusText(indexingPolicy);
    const cleanupStatus = cleanup.status || 'not_run';

    setDocumentAccessIndexBadge(
        'cosmos-indexing-policy-status',
        formatDocumentAccessIndexStatus(indexingStatus),
        getDocumentAccessIndexStatusVariant(indexingStatus)
    );
    setElementText('cosmos-indexing-policy-mode', formatDocumentAccessIndexStatus(indexingPolicy.mode || 'not_loaded'));
    setElementText('cosmos-indexing-policy-container-count', formatNumber(indexingPolicy.container_count || 0));
    setElementText(
        'cosmos-indexing-policy-missing-count',
        formatNumber(indexingPolicy.containers_missing_expected_indexes || 0)
    );
    setElementText('cosmos-indexing-policy-updated-count', formatNumber(indexingPolicy.updated_container_count || 0));
    setElementText('cosmos-indexing-policy-failed-count', formatNumber(indexingPolicy.failed_container_count || 0));
    setElementText('cosmos-indexing-policy-last-evaluated', indexingPolicy.evaluated_at || 'Not loaded');

    setDocumentAccessIndexBadge(
        'stale-cache-cleanup-status',
        formatDocumentAccessIndexStatus(cleanupStatus),
        getDocumentAccessIndexStatusVariant(cleanupStatus)
    );
    setElementText('stale-cache-cleanup-mode', formatDocumentAccessIndexStatus(cleanup.mode || 'not_run'));
    setElementText('stale-cache-cleanup-candidates', formatNumber(cleanup.candidate_count || 0));
    setElementText('stale-cache-cleanup-deleted', formatNumber(cleanup.deleted_count || 0));
    setElementText('stale-cache-cleanup-failed', formatNumber(cleanup.failed_count || 0));
    setElementText('stale-cache-cleanup-more-candidates', cleanup.has_more_candidates ? 'Yes' : 'No');
    setElementText('stale-cache-cleanup-categories', formatStaleCacheCleanupCategories(cleanup.categories));
    setElementText('stale-cache-cleanup-last-evaluated', cleanup.evaluated_at || 'Not run yet');
}

function getStaleCacheCleanupStatusFromRunResult(result) {
    const cleanupStep = Array.isArray(result?.steps)
        ? result.steps.find(step => step?.name === 'stale_cache_document_cleanup')
        : null;
    return cleanupStep?.results || null;
}

function getCosmosIndexingPolicyStatusFromRunResult(result) {
    const indexingStep = Array.isArray(result?.steps)
        ? result.steps.find(step => step?.name === 'cosmos_indexing_policy_maintenance')
        : null;
    return indexingStep?.results || null;
}

function getNormalizedDocumentAccessIndexStatus(status) {
    return String(status || '').trim().toLowerCase();
}

function isDocumentAccessIndexBackfillRunning(status) {
    return getNormalizedDocumentAccessIndexStatus(status) === 'running';
}

function isDocumentAccessIndexBackfillInProgress(status) {
    return getNormalizedDocumentAccessIndexStatus(status) === 'in_progress';
}

function stopDocumentAccessIndexPolling() {
    if (documentAccessIndexStatusPollId) {
        window.clearInterval(documentAccessIndexStatusPollId);
        documentAccessIndexStatusPollId = null;
    }
}

function startDocumentAccessIndexPolling() {
    if (documentAccessIndexStatusPollId) {
        return;
    }

    documentAccessIndexStatusPollId = window.setInterval(() => {
        loadDocumentAccessIndexStatus(null, { showLoading: false });
    }, DOCUMENT_ACCESS_INDEX_STATUS_POLL_INTERVAL_MS);
}

function getDocumentAccessIndexBackfillStatusFromRunResult(result) {
    const backfillStep = Array.isArray(result?.steps)
        ? result.steps.find(step => step?.name === 'document_access_index_backfill')
        : null;
    return backfillStep?.results?.current_status || null;
}

async function fetchAppMaintenanceStatus(errorMessage = 'Failed to load app maintenance status.') {
    const response = await fetch('/api/admin/settings/app-maintenance/status', {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin'
    });
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.error || errorMessage);
    }
    return data;
}

function renderDocumentAccessIndexStatus(statusPayload) {
    const backfillStatus = statusPayload?.document_access_index_backfill || statusPayload;
    const state = backfillStatus?.state || {};
    const settings = backfillStatus?.settings || {};
    const shadowValidation = backfillStatus?.shadow_validation || {};
    const maintenance = backfillStatus?.maintenance || {};
    const readMetrics = backfillStatus?.read_metrics || {};
    const cacheMetrics = backfillStatus?.cache_metrics || {};
    const statusText = String(state.status || 'not_started');

    setDocumentAccessIndexBadge(
        'document-access-index-container-status',
        formatDocumentAccessIndexBoolean(settings.container_enabled, 'Enabled', 'Disabled'),
        settings.container_enabled ? 'success' : 'secondary'
    );
    setDocumentAccessIndexBadge(
        'document-access-index-write-through-status',
        formatDocumentAccessIndexBoolean(settings.write_through_enabled, 'Enabled', 'Disabled'),
        settings.write_through_enabled ? 'success' : 'secondary'
    );
    setDocumentAccessIndexBadge(
        'document-access-index-read-status',
        settings.reads_enabled ? 'Enabled' : 'Disabled',
        settings.reads_enabled ? 'success' : 'secondary'
    );
    setDocumentAccessIndexBadge(
        'document-access-index-cache-status',
        settings.cache_enabled ? `Enabled / ${formatDocumentAccessIndexMetric(settings.cache_ttl_seconds, 'sec')}` : 'Disabled',
        settings.cache_enabled ? 'success' : 'secondary'
    );
    setDocumentAccessIndexBadge(
        'document-access-index-shadow-status',
        settings.shadow_validation_enabled ? 'Enabled' : 'Disabled',
        settings.shadow_validation_enabled ? 'warning' : 'secondary'
    );
    setDocumentAccessIndexBadge(
        'document-access-index-backfill-status',
        formatDocumentAccessIndexStatus(statusText),
        getDocumentAccessIndexStatusVariant(statusText)
    );
    setDocumentAccessIndexBadge(
        'document-access-index-maintenance-mode',
        maintenance.auto_maintenance_enabled ? 'Automatic' : 'Disabled',
        maintenance.auto_maintenance_enabled ? 'success' : 'secondary'
    );

    setElementText('document-access-index-repair-count', formatNumber(backfillStatus?.repair_required_count));
    setElementText(
        'document-access-index-maintenance-next-action',
        formatDocumentAccessIndexStatus(maintenance.next_action || 'monitor')
    );
    setElementText(
        'document-access-index-maintenance-more-work',
        maintenance.has_more_work ? 'Yes' : 'No'
    );
    setElementText(
        'document-access-index-maintenance-active-interval',
        formatDocumentAccessIndexMetric(maintenance.active_interval_seconds, 'sec')
    );
    const read15m = getDocumentAccessIndexReadWindow(readMetrics, '15m');
    const cache15m = getDocumentAccessIndexCacheWindow(cacheMetrics, '15m');
    setElementText('document-access-index-read-15m-attempts', formatNumber(read15m.sample_count || 0));
    setElementText(
        'document-access-index-cache-15m-hit-rate',
        formatDocumentAccessIndexPercent(cache15m.hit_rate_percent)
    );
    setElementText(
        'document-access-index-cache-15m-hits-misses',
        `${formatNumber(cache15m.hit_count || 0)} / ${formatNumber(cache15m.miss_count || 0)}`
    );
    setElementText(
        'document-access-index-cache-15m-bypasses-errors',
        `${formatNumber(cache15m.bypass_count || 0)} / ${formatNumber(cache15m.error_count || 0)}`
    );
    setElementText(
        'document-access-index-cache-15m-invalidations',
        formatNumber(cache15m.invalidation_count || 0)
    );
    setElementText('document-access-index-read-15m-served', formatNumber(read15m.served_from_index_count || 0));
    setElementText('document-access-index-read-15m-fallbacks', formatNumber(read15m.source_fallback_count || 0));
    setElementText(
        'document-access-index-read-15m-fallback-rate',
        formatDocumentAccessIndexPercent(read15m.fallback_rate_percent)
    );
    setElementText(
        'document-access-index-read-15m-ru',
        formatDocumentAccessIndexMetric(read15m.request_charge, 'RU')
    );
    setElementText(
        'document-access-index-read-15m-latency',
        formatDocumentAccessIndexLatencyWindow(read15m)
    );
    setElementText(
        'document-access-index-read-last-fallback',
        formatDocumentAccessIndexReadSample(readMetrics.last_fallback_sample)
    );
    setElementText(
        'document-access-index-read-last-sample',
        formatDocumentAccessIndexReadSample(readMetrics.last_sample)
    );
    setElementText(
        'document-access-index-cache-last-event',
        formatDocumentAccessIndexCacheEvent(cacheMetrics.last_event)
    );
    setDocumentAccessIndexBadge(
        'document-access-index-shadow-last-status',
        formatDocumentAccessIndexStatus(shadowValidation.status || 'not_run'),
        getDocumentAccessIndexStatusVariant(shadowValidation.status || 'not_run')
    );
    setElementText(
        'document-access-index-shadow-mismatches',
        `${formatNumber(shadowValidation.missing_count || 0)} missing / ${formatNumber(shadowValidation.extra_count || 0)} extra`
    );
    setElementText(
        'document-access-index-shadow-ru-comparison',
        formatDocumentAccessIndexMetricPair(shadowValidation.source_query_ru, shadowValidation.validation_index_ru, 'RU')
    );
    setElementText(
        'document-access-index-shadow-validation-ru',
        formatDocumentAccessIndexMetric(shadowValidation.validation_index_ru, 'RU')
    );
    setElementText(
        'document-access-index-shadow-candidate-ru',
        formatDocumentAccessIndexMetric(shadowValidation.candidate_read_ru, 'RU')
    );
    setElementText(
        'document-access-index-shadow-wave5-ru-savings',
        formatDocumentAccessIndexSavings(shadowValidation.estimated_wave5_ru_savings, 'RU', 'less', 'more')
    );
    setElementText(
        'document-access-index-shadow-ms-comparison',
        formatDocumentAccessIndexMetricPair(shadowValidation.source_query_ms, shadowValidation.candidate_read_ms, 'ms')
    );
    setElementText(
        'document-access-index-shadow-ms-savings',
        formatDocumentAccessIndexSavings(shadowValidation.estimated_wave5_ms_savings, 'ms', 'faster', 'slower')
    );
    const rolling5m = getDocumentAccessIndexRollingWindow(shadowValidation, '5m');
    const rolling15m = getDocumentAccessIndexRollingWindow(shadowValidation, '15m');
    setElementText(
        'document-access-index-rolling-5m-ru-comparison',
        formatDocumentAccessIndexMetricPair(rolling5m.source_query_ru, rolling5m.candidate_read_ru, 'RU')
    );
    setElementText(
        'document-access-index-rolling-5m-wave5-ru-savings',
        formatDocumentAccessIndexSavings(rolling5m.estimated_wave5_ru_savings, 'RU', 'less', 'more')
    );
    setElementText(
        'document-access-index-rolling-15m-ru-comparison',
        formatDocumentAccessIndexMetricPair(rolling15m.source_query_ru, rolling15m.candidate_read_ru, 'RU')
    );
    setElementText(
        'document-access-index-rolling-15m-wave5-ru-savings',
        formatDocumentAccessIndexSavings(rolling15m.estimated_wave5_ru_savings, 'RU', 'less', 'more')
    );
    setElementText(
        'document-access-index-rolling-15m-validation-overhead',
        formatDocumentAccessIndexMetric(rolling15m.validation_index_ru, 'RU')
    );
    setElementText(
        'document-access-index-rolling-15m-samples',
        formatDocumentAccessIndexSampleSummary(rolling15m)
    );
    setElementText('document-access-index-current-scope', state.current_source_scope || 'None');
    setElementText('document-access-index-completed-scopes', formatDocumentAccessIndexList(state.completed_source_scopes));
    setElementText('document-access-index-total-processed', formatNumber(state.total_documents_processed || 0));
    setElementText('document-access-index-total-failed', formatNumber(state.total_documents_failed || 0));
    setElementText('document-access-index-total-upserted', formatNumber(state.total_rows_upserted || 0));
    setElementText('document-access-index-total-deleted', formatNumber(state.total_rows_deleted || 0));
    setElementText('document-access-index-last-completed', state.last_completed_at || 'Not completed yet');
    setElementText('document-access-index-last-error', state.last_error || 'None');

    const runButton = document.getElementById('document-access-index-run-batch-btn');
    const resetButton = document.getElementById('document-access-index-reset-btn');
    if (runButton) {
        runButton.disabled = settings.container_enabled === false;
    }
    if (resetButton) {
        resetButton.disabled = settings.container_enabled === false;
    }

    if (isDocumentAccessIndexBackfillRunning(statusText)) {
        startDocumentAccessIndexPolling();
    } else {
        stopDocumentAccessIndexPolling();
    }
}

async function loadDocumentAccessIndexStatus(event = null, options = {}) {
    const showLoading = options.showLoading !== false;
    const triggerButton = event?.currentTarget || (showLoading ? document.getElementById('document-access-index-refresh-btn') : null);
    const isConversationCacheTrigger = triggerButton?.id === 'conversation-cache-refresh-btn';
    if (triggerButton) {
        setButtonBusy(triggerButton, true, 'Loading...');
    }
    if (showLoading) {
        setDocumentAccessIndexMessage(
            isConversationCacheTrigger ? 'Loading conversation cache metrics...' : 'Loading document access index status...',
            'info'
        );
    }

    try {
        const data = await fetchAppMaintenanceStatus('Failed to load document access index status.');

        renderDocumentAccessIndexStatus(data);
        renderConversationCacheStatus(data);
        renderCosmosMaintenanceStatus(data);
        if (showLoading) {
            setDocumentAccessIndexMessage(
                isConversationCacheTrigger ? 'Conversation cache metrics loaded.' : 'Document access index status loaded.',
                'success'
            );
        }
    } catch (error) {
        setDocumentAccessIndexMessage(
            error.message || (
                isConversationCacheTrigger
                    ? 'Failed to load conversation cache metrics.'
                    : 'Failed to load document access index status.'
            ),
            'danger'
        );
        stopDocumentAccessIndexPolling();
    } finally {
        if (triggerButton) {
            setButtonBusy(triggerButton, false);
        }
    }
}

async function loadCosmosMaintenanceStatus(event = null, options = {}) {
    const showLoading = options.showLoading !== false;
    const triggerButton = event?.currentTarget || (showLoading ? document.getElementById('cosmos-maintenance-refresh-btn') : null);
    if (triggerButton) {
        setButtonBusy(triggerButton, true, 'Loading...');
    }
    if (showLoading) {
        setCosmosMaintenanceMessage('Loading Cosmos maintenance status...', 'info');
    }

    try {
        const data = await fetchAppMaintenanceStatus('Failed to load Cosmos maintenance status.');
        renderDocumentAccessIndexStatus(data);
        renderConversationCacheStatus(data);
        renderCosmosMaintenanceStatus(data);
        if (showLoading) {
            setCosmosMaintenanceMessage('Cosmos maintenance status loaded.', 'success');
        }
    } catch (error) {
        setCosmosMaintenanceMessage(error.message || 'Failed to load Cosmos maintenance status.', 'danger');
    } finally {
        if (triggerButton) {
            setButtonBusy(triggerButton, false);
        }
    }
}

async function runStaleCacheCleanup(options = {}) {
    const applyChanges = Boolean(options.applyChanges);
    const triggerButton = options.triggerButton || document.getElementById(
        applyChanges ? 'stale-cache-cleanup-apply-confirm-btn' : 'stale-cache-cleanup-dry-run-btn'
    );
    if (triggerButton) {
        setButtonBusy(triggerButton, true, applyChanges ? 'Deleting...' : 'Scanning...');
    }
    setCosmosMaintenanceMessage(
        applyChanges ? 'Deleting one bounded batch of stale cache documents...' : 'Scanning for stale cache cleanup candidates...',
        'info'
    );

    try {
        const response = await fetch('/api/admin/settings/app-maintenance/run', {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                apply_cosmos_indexing_policies: false,
                run_document_access_index_backfill: false,
                run_stale_cache_cleanup: true,
                apply_stale_cache_cleanup: applyChanges
            })
        });
        const data = await response.json();
        const cleanupResult = getStaleCacheCleanupStatusFromRunResult(data);
        if (cleanupResult) {
            renderCosmosMaintenanceStatus({ stale_cache_cleanup: cleanupResult });
        }
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Stale cache cleanup failed.');
        }

        const candidates = formatNumber(cleanupResult?.candidate_count || 0);
        const deleted = formatNumber(cleanupResult?.deleted_count || 0);
        const message = applyChanges
            ? `Stale cache cleanup deleted ${deleted} document(s) from ${candidates} candidate(s).`
            : `Stale cache cleanup dry run found ${candidates} candidate document(s).`;
        setCosmosMaintenanceMessage(message, cleanupResult?.has_more_candidates ? 'warning' : 'success');
        showToast(message, cleanupResult?.has_more_candidates ? 'warning' : 'success');

        const modalElement = document.getElementById('staleCacheCleanupApplyModal');
        if (applyChanges && modalElement) {
            bootstrap.Modal.getInstance(modalElement)?.hide();
        }
        await loadCosmosMaintenanceStatus(null, { showLoading: false });
    } catch (error) {
        setCosmosMaintenanceMessage(error.message || 'Stale cache cleanup failed.', 'danger');
        showToast(error.message || 'Stale cache cleanup failed.', 'danger');
    } finally {
        if (triggerButton) {
            setButtonBusy(triggerButton, false);
        }
    }
}

async function runCosmosIndexingPolicyApply(options = {}) {
    const triggerButton = options.triggerButton || document.getElementById('cosmos-indexing-policy-apply-confirm-btn');
    if (triggerButton) {
        setButtonBusy(triggerButton, true, 'Applying...');
    }
    setCosmosMaintenanceMessage(
        'Submitting missing Cosmos composite index updates. Index transformation may continue asynchronously in Azure Cosmos DB.',
        'info'
    );

    try {
        const response = await fetch('/api/admin/settings/app-maintenance/run', {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                apply_cosmos_indexing_policies: true,
                run_document_access_index_backfill: false,
                run_stale_cache_cleanup: false
            })
        });
        const data = await response.json();
        const indexingResult = getCosmosIndexingPolicyStatusFromRunResult(data);
        if (indexingResult) {
            renderCosmosMaintenanceStatus({ cosmos_indexing_policies: indexingResult });
        }
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Cosmos indexing policy update failed.');
        }

        const updated = formatNumber(indexingResult?.updated_container_count || 0);
        const missing = formatNumber(indexingResult?.containers_missing_expected_indexes || 0);
        const message = Number(indexingResult?.updated_container_count || 0) > 0
            ? `Cosmos indexing policy update submitted for ${updated} container(s). Refresh later to monitor transformation status.`
            : `Cosmos indexing policies are already aligned. Missing expected indexes: ${missing}.`;
        setCosmosMaintenanceMessage(message, 'success');
        showToast(message, 'success');

        const modalElement = document.getElementById('cosmosIndexingPolicyApplyModal');
        if (modalElement) {
            bootstrap.Modal.getInstance(modalElement)?.hide();
        }
        await loadCosmosMaintenanceStatus(null, { showLoading: false });
    } catch (error) {
        setCosmosMaintenanceMessage(error.message || 'Cosmos indexing policy update failed.', 'danger');
        showToast(error.message || 'Cosmos indexing policy update failed.', 'danger');
    } finally {
        if (triggerButton) {
            setButtonBusy(triggerButton, false);
        }
    }
}

async function runDocumentAccessIndexBackfillBatch(options = {}) {
    const reset = Boolean(options.reset);
    const triggerButton = options.triggerButton || document.getElementById(reset ? 'document-access-index-reset-confirm-btn' : 'document-access-index-run-batch-btn');
    if (triggerButton) {
        setButtonBusy(triggerButton, true, reset ? 'Resetting...' : 'Running...');
    }
    setDocumentAccessIndexMessage(reset ? 'Resetting backfill checkpoint and running one batch...' : 'Running one document access backfill batch...', 'info');

    try {
        const response = await fetch('/api/admin/settings/app-maintenance/run', {
            method: 'POST',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                apply_cosmos_indexing_policies: false,
                run_document_access_index_backfill: true,
                reset_document_access_index_backfill: reset
            })
        });
        const data = await response.json();
        const currentStatus = getDocumentAccessIndexBackfillStatusFromRunResult(data);
        if (currentStatus) {
            renderDocumentAccessIndexStatus(currentStatus);
        }
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Document access index backfill batch failed.');
        }

        const status = currentStatus?.state?.status || 'completed';
        const statusVariant = getDocumentAccessIndexStatusVariant(status);
        if (isDocumentAccessIndexBackfillRunning(status)) {
            setDocumentAccessIndexMessage('Backfill batch is still running. Status will refresh automatically.', 'info');
        } else if (isDocumentAccessIndexBackfillInProgress(status)) {
            setDocumentAccessIndexMessage('Backfill batch completed and more documents remain. Run another batch or leave scheduled backfill enabled to continue during maintenance.', 'info');
        } else if (statusVariant === 'danger' || statusVariant === 'warning') {
            setDocumentAccessIndexMessage('Backfill batch completed with errors. Review the repair backlog and last error details.', 'warning');
        } else {
            setDocumentAccessIndexMessage('Document access index backfill batch completed.', 'success');
        }
        showToast(
            statusVariant === 'danger' || statusVariant === 'warning'
                ? 'Document access index backfill batch completed with errors.'
                : 'Document access index backfill batch completed.',
            statusVariant === 'danger' ? 'danger' : statusVariant === 'warning' ? 'warning' : 'success'
        );

        const modalElement = document.getElementById('documentAccessIndexResetModal');
        if (reset && modalElement) {
            bootstrap.Modal.getInstance(modalElement)?.hide();
        }
    } catch (error) {
        setDocumentAccessIndexMessage(error.message || 'Document access index backfill batch failed.', 'danger');
        showToast(error.message || 'Document access index backfill batch failed.', 'danger');
        stopDocumentAccessIndexPolling();
    } finally {
        if (triggerButton) {
            setButtonBusy(triggerButton, false);
        }
    }
}

function setupDocumentAccessIndexControls() {
    const section = document.getElementById('document-access-index-section');
    if (!section) {
        return;
    }

    document.getElementById('document-access-index-refresh-btn')?.addEventListener('click', loadDocumentAccessIndexStatus);
    document.getElementById('conversation-cache-refresh-btn')?.addEventListener('click', loadDocumentAccessIndexStatus);
    document.getElementById('document-access-index-run-batch-btn')?.addEventListener('click', event => {
        runDocumentAccessIndexBackfillBatch({ triggerButton: event.currentTarget });
    });
    document.getElementById('document-access-index-reset-confirm-btn')?.addEventListener('click', event => {
        runDocumentAccessIndexBackfillBatch({ reset: true, triggerButton: event.currentTarget });
    });
    loadDocumentAccessIndexStatus(null, { showLoading: false });
}

function setupCosmosMaintenanceControls() {
    const section = document.getElementById('cosmos-maintenance-section');
    if (!section) {
        return;
    }

    document.getElementById('cosmos-maintenance-refresh-btn')?.addEventListener('click', loadCosmosMaintenanceStatus);
    document.getElementById('cosmos-indexing-policy-apply-confirm-btn')?.addEventListener('click', event => {
        runCosmosIndexingPolicyApply({ triggerButton: event.currentTarget });
    });
    document.getElementById('stale-cache-cleanup-dry-run-btn')?.addEventListener('click', event => {
        runStaleCacheCleanup({ applyChanges: false, triggerButton: event.currentTarget });
    });
    document.getElementById('stale-cache-cleanup-apply-confirm-btn')?.addEventListener('click', event => {
        runStaleCacheCleanup({ applyChanges: true, triggerButton: event.currentTarget });
    });
}

function setupCosmosThroughputControls() {
    const section = document.getElementById('cosmos-throughput-section');
    if (!section) {
        return;
    }

    const automationToggle = document.getElementById('cosmos_throughput_autoscale_enabled');
    const automationSettings = document.getElementById('cosmos-throughput-automation-settings');
    if (automationToggle && automationSettings) {
        automationToggle.addEventListener('change', () => {
            automationSettings.classList.toggle('d-none', !automationToggle.checked);
            validateCosmosThroughputSettings();
        });
        automationSettings.classList.toggle('d-none', !automationToggle.checked);
    }

    COSMOS_THROUGHPUT_VALIDATION_FIELD_IDS.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (!field) {
            return;
        }
        field.addEventListener('input', () => validateCosmosThroughputSettings());
        field.addEventListener('change', () => validateCosmosThroughputSettings());
    });

    document.getElementById('cosmos-throughput-container-filter')?.addEventListener('input', () => {
        renderCosmosContainerMetrics(currentCosmosContainers);
    });
    document.getElementById('cosmos-throughput-container-policy-filter')?.addEventListener('input', () => {
        renderCosmosContainerPolicyModal(currentCosmosContainers);
    });

    document.querySelectorAll('.cosmos-throughput-container-sort').forEach(button => {
        button.addEventListener('click', () => {
            const fieldName = button.dataset.sortField;
            if (!COSMOS_CONTAINER_SORT_FIELDS.has(fieldName)) {
                return;
            }

            if (currentCosmosContainerSort.field === fieldName) {
                currentCosmosContainerSort.direction = currentCosmosContainerSort.direction === 'desc' ? 'asc' : 'desc';
            } else {
                currentCosmosContainerSort = {
                    field: fieldName,
                    direction: COSMOS_CONTAINER_TEXT_SORT_FIELDS.has(fieldName) ? 'asc' : 'desc'
                };
            }
            renderCosmosContainerMetrics(currentCosmosContainers);
        });
    });

    document.getElementById('cosmos-throughput-refresh-btn')?.addEventListener('click', loadCosmosThroughputStatus);
    document.getElementById('cosmos-throughput-refresh-table-btn')?.addEventListener('click', loadCosmosThroughputStatus);
    document.getElementById('cosmos-throughput-validate-access-btn')?.addEventListener('click', event => validateCosmosThroughputAccess(event.currentTarget));
    document.getElementById('cosmos-throughput-run-setup-test-btn')?.addEventListener('click', event => validateCosmosThroughputAccess(event.currentTarget));
    document.getElementById('cosmos-throughput-convert-autoscale-btn')?.addEventListener('click', event => convertCosmosThroughputToAutoscale('', event.currentTarget));
    document.getElementById('cosmos-throughput-scale-up-btn')?.addEventListener('click', () => manuallyScaleCosmosThroughput('up'));
    document.getElementById('cosmos-throughput-scale-down-btn')?.addEventListener('click', () => manuallyScaleCosmosThroughput('down'));
    document.getElementById('cosmos-throughput-container-policies-btn')?.addEventListener('click', () => {
        setCosmosContainerPolicyFilter('');
        renderCosmosContainerPolicyModal(currentCosmosContainers);
    });
    document.getElementById('cosmos_throughput_enforce_container_defaults')?.addEventListener('change', () => {
        renderCosmosContainerMetrics(currentCosmosContainers);
        renderCosmosContainerPolicyModal(currentCosmosContainers);
        markFormAsModified();
    });
    document.getElementById('cosmos_throughput_convert_manual_to_autoscale_enabled')?.addEventListener('change', () => {
        renderCosmosContainerMetrics(currentCosmosContainers);
        renderCosmosContainerPolicyModal(currentCosmosContainers);
        markFormAsModified();
    });
    document.getElementById('cosmos-throughput-apply-global-policy-btn')?.addEventListener('click', applyGlobalCosmosContainerPolicyToCurrentContainers);
    document.getElementById('cosmos-throughput-save-container-policies-btn')?.addEventListener('click', () => {
        const validationResult = validateCosmosThroughputSettings({ report: true });
        if (!validationResult.isValid) {
            return;
        }
        writeCosmosContainerPolicies(collectCosmosContainerPolicies());
        renderCosmosContainerMetrics(currentCosmosContainers);
        setCosmosThroughputMessage('Container throughput policies are staged. Save Admin Settings to persist them.', 'info');
    });
    if (!currentCosmosStatusLoaded) {
        initializeCosmosThroughputStatusView();
    }
}

function createTextElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
        element.className = className;
    }
    element.textContent = text || '';
    return element;
}

function appendTextList(container, title, items) {
    if (!Array.isArray(items) || items.length === 0) {
        return;
    }

    container.appendChild(createTextElement('div', 'fw-semibold mt-2', title));
    const list = document.createElement('ul');
    list.className = 'mb-0 ps-3';
    items.forEach(item => {
        const listItem = document.createElement('li');
        listItem.textContent = String(item || '');
        list.appendChild(listItem);
    });
    container.appendChild(list);
}

function renderAdminTestLoading(container, message) {
    if (!container) {
        return;
    }

    container.replaceChildren();
    const alert = document.createElement('div');
    alert.className = 'alert alert-info mb-0';
    alert.textContent = message;
    container.appendChild(alert);
}

function renderAdminTestResult(container, resultOptions) {
    if (!container) {
        return;
    }

    const variantMap = {
        success: 'success',
        warning: 'warning',
        danger: 'danger',
        info: 'info'
    };
    const variant = variantMap[resultOptions.variant] || 'info';
    container.replaceChildren();

    const alert = document.createElement('div');
    alert.className = `alert alert-${variant} mb-0`;
    alert.appendChild(createTextElement('div', 'fw-semibold', resultOptions.title));

    if (resultOptions.message) {
        alert.appendChild(createTextElement('div', 'mt-1', resultOptions.message));
    }
    if (resultOptions.preview) {
        alert.appendChild(createTextElement('div', 'fw-semibold mt-2', 'Response Preview'));
        alert.appendChild(createTextElement('div', 'small text-break', resultOptions.preview));
    }

    appendTextList(alert, 'Details', resultOptions.details);
    appendTextList(alert, 'Guidance', resultOptions.guidance);
    container.appendChild(alert);
}

function setupDeepResearchPolicyEditors() {
    document.querySelectorAll('[data-deep-research-policy], [data-url-access-policy]').forEach(editor => {
        const policyName = editor.dataset.urlAccessPolicy || editor.dataset.deepResearchPolicy;
        const policyKind = editor.dataset.policyKind || 'text';
        const hiddenField = document.getElementById(policyName);
        const listContainer = editor.querySelector('[data-policy-list]');
        if (!policyName || !hiddenField || !listContainer) {
            return;
        }

        let policyItems = parsePolicyListValue(hiddenField.value)
            .map(item => normalizePolicyValue(item, policyKind))
            .filter(Boolean)
            .filter((item, index, items) => items.indexOf(item) === index);

        const syncHiddenField = () => {
            hiddenField.value = policyItems.join('\n');
        };

        const renderEmptyState = () => {
            const emptyState = document.createElement('div');
            emptyState.className = 'list-group-item text-muted small';
            emptyState.textContent = policyKind === 'domain'
                ? 'No domain rules configured.'
                : 'No user rules configured.';
            listContainer.appendChild(emptyState);
        };

        const renderPolicyItems = () => {
            listContainer.replaceChildren();
            syncHiddenField();

            if (policyItems.length === 0) {
                renderEmptyState();
                return;
            }

            policyItems.forEach((item, index) => {
                const row = document.createElement('div');
                row.className = 'list-group-item d-flex align-items-center gap-2';

                const input = document.createElement('input');
                input.type = 'text';
                input.className = 'form-control form-control-sm';
                input.value = item;
                input.setAttribute('aria-label', `Edit ${policyKind} policy entry`);

                const applyEdit = () => {
                    const normalizedValue = normalizePolicyValue(input.value, policyKind);
                    if (!normalizedValue) {
                        policyItems.splice(index, 1);
                        renderPolicyItems();
                        markFormAsModified();
                        return;
                    }

                    const duplicateIndex = policyItems.findIndex((existingItem, existingIndex) => (
                        existingIndex !== index && existingItem.toLowerCase() === normalizedValue.toLowerCase()
                    ));
                    if (duplicateIndex >= 0) {
                        input.value = policyItems[index];
                        showToast('That policy entry already exists.', 'warning');
                        return;
                    }

                    if (policyItems[index] !== normalizedValue) {
                        policyItems[index] = normalizedValue;
                        renderPolicyItems();
                        markFormAsModified();
                    } else {
                        input.value = normalizedValue;
                    }
                };

                input.addEventListener('change', applyEdit);
                input.addEventListener('keydown', event => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        applyEdit();
                    }
                });

                const deleteButton = createIconButton('bi bi-trash', 'Delete policy entry', 'btn-outline-danger');
                deleteButton.addEventListener('click', () => {
                    policyItems.splice(index, 1);
                    renderPolicyItems();
                    markFormAsModified();
                });

                row.appendChild(input);
                row.appendChild(deleteButton);
                listContainer.appendChild(row);
            });
        };

        const addPolicyItems = (rawItems, options = {}) => {
            const { silent = false } = options;
            const normalizedItems = rawItems
                .map(item => normalizePolicyValue(item, policyKind))
                .filter(Boolean);
            const startingCount = policyItems.length;

            normalizedItems.forEach(item => {
                const alreadyExists = policyItems.some(existingItem => existingItem.toLowerCase() === item.toLowerCase());
                if (!alreadyExists) {
                    policyItems.push(item);
                }
            });

            if (policyItems.length !== startingCount) {
                renderPolicyItems();
                markFormAsModified();
            } else if (!silent && normalizedItems.length > 0) {
                showToast('No new policy entries were added.', 'info');
            }
        };

        const newInput = editor.querySelector('[data-policy-new-input]');
        const addButton = editor.querySelector('[data-policy-add-button]');
        if (newInput && addButton) {
            const addFromInput = () => {
                addPolicyItems([newInput.value]);
                newInput.value = '';
                newInput.focus();
            };
            addButton.addEventListener('click', addFromInput);
            newInput.addEventListener('keydown', event => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    addFromInput();
                }
            });
        }

        setupDeepResearchUserPolicySearch(editor, addPolicyItems);
        setupDeepResearchUserPolicyBulkAdd(editor, addPolicyItems);
        renderPolicyItems();
    });
}

function setupDeepResearchUserPolicySearch(editor, addPolicyItems) {
    const searchInput = editor.querySelector('[data-user-search-input]');
    const searchButton = editor.querySelector('[data-user-search-button]');
    const searchStatus = editor.querySelector('[data-user-search-status]');
    const resultsContainer = editor.querySelector('[data-user-search-results]');
    if (!searchInput || !searchButton || !resultsContainer) {
        return;
    }

    const setStatus = (message, tone = 'muted') => {
        if (!searchStatus) {
            return;
        }
        searchStatus.textContent = message || '';
        searchStatus.className = `small text-${tone} mt-1`;
    };

    const renderResults = users => {
        resultsContainer.replaceChildren();
        resultsContainer.classList.remove('d-none');

        if (!Array.isArray(users) || users.length === 0) {
            const emptyState = document.createElement('div');
            emptyState.className = 'list-group-item text-muted small';
            emptyState.textContent = 'No users found.';
            resultsContainer.appendChild(emptyState);
            return;
        }

        users.forEach(user => {
            const row = document.createElement('div');
            row.className = 'list-group-item d-flex align-items-center justify-content-between gap-2';

            const textWrapper = document.createElement('div');
            textWrapper.className = 'min-w-0';

            const nameEl = document.createElement('div');
            nameEl.className = 'fw-semibold text-truncate';
            nameEl.textContent = user.displayName || '(no name)';

            const emailEl = document.createElement('div');
            emailEl.className = 'small text-muted text-truncate';
            emailEl.textContent = user.email || user.id || '';

            textWrapper.appendChild(nameEl);
            textWrapper.appendChild(emailEl);

            const addButton = document.createElement('button');
            addButton.type = 'button';
            addButton.className = 'btn btn-sm btn-outline-primary flex-shrink-0';
            addButton.textContent = 'Add';
            addButton.addEventListener('click', () => {
                addPolicyItems([user.email || user.id || '']);
            });

            row.appendChild(textWrapper);
            row.appendChild(addButton);
            resultsContainer.appendChild(row);
        });
    };

    const searchUsers = async () => {
        const query = searchInput.value.trim();
        if (!query) {
            searchInput.classList.add('is-invalid');
            setStatus('Enter a name or email to search.', 'warning');
            return;
        }

        searchInput.classList.remove('is-invalid');
        searchButton.disabled = true;
        setStatus('Searching...', 'muted');

        try {
            const response = await fetch(`/api/userSearch?query=${encodeURIComponent(query)}`);
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || response.statusText || 'User search failed');
            }
            renderResults(payload);
            const resultCount = Array.isArray(payload) ? payload.length : 0;
            setStatus(
                resultCount > 0 ? `Found ${resultCount} user(s).` : 'No users found.',
                resultCount > 0 ? 'success' : 'muted'
            );
        } catch (error) {
            resultsContainer.classList.add('d-none');
            resultsContainer.replaceChildren();
            setStatus(`Search failed: ${error.message}`, 'danger');
            showToast(`User search failed: ${error.message}`, 'danger');
        } finally {
            searchButton.disabled = false;
        }
    };

    searchButton.addEventListener('click', searchUsers);
    searchInput.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            event.preventDefault();
            searchUsers();
        }
    });
}

function setupDeepResearchUserPolicyBulkAdd(editor, addPolicyItems) {
    const bulkInput = editor.querySelector('[data-user-bulk-input]');
    const bulkAddButton = editor.querySelector('[data-user-bulk-add-button]');
    if (!bulkInput || !bulkAddButton) {
        return;
    }

    bulkAddButton.addEventListener('click', () => {
        const entries = parsePolicyListValue(bulkInput.value);
        if (entries.length === 0) {
            bulkInput.classList.add('is-invalid');
            showToast('Enter at least one email or user id to add.', 'warning');
            return;
        }

        bulkInput.classList.remove('is-invalid');
        addPolicyItems(entries);
        bulkInput.value = '';
    });
}

function setupDeepResearchAllowedUsersManager() {
    const hiddenField = document.getElementById('source_review_allowed_users');
    const summary = document.getElementById('deep_research_allowed_users_summary');
    const countLabel = document.getElementById('deep_research_allowed_users_count');
    const filterInput = document.getElementById('deep_research_allowed_users_filter');
    const usersTableBody = document.getElementById('deep_research_allowed_users_tbody');
    const searchInput = document.getElementById('deep_research_user_search_term');
    const searchButton = document.getElementById('deep_research_user_search_button');
    const searchStatus = document.getElementById('deep_research_user_search_status');
    const searchResultsTable = document.getElementById('deep_research_user_search_results_table');
    const manualIdentifierInput = document.getElementById('deep_research_manual_user_identifier');
    const manualAddButton = document.getElementById('deep_research_manual_user_add_button');
    const csvInput = document.getElementById('deep_research_allowed_users_csv_input');
    const csvStatus = document.getElementById('deep_research_allowed_users_csv_status');
    const csvExampleButton = document.getElementById('deep_research_allowed_users_csv_example_button');

    if (!hiddenField || !usersTableBody) {
        return;
    }

    let allowedUsers = parsePolicyListValue(hiddenField.value)
        .map(normalizeUserPolicyValue)
        .filter(Boolean)
        .filter((item, index, items) => items.indexOf(item) === index);

    const syncHiddenField = (markModified = true) => {
        hiddenField.value = allowedUsers.join('\n');
        if (markModified) {
            markFormAsModified();
        }
    };

    const setSearchStatus = (message, tone = 'muted') => {
        if (!searchStatus) {
            return;
        }
        searchStatus.textContent = message || '';
        searchStatus.className = `form-text text-${tone}`;
    };

    const setCsvStatus = (message, tone = 'info') => {
        if (!csvStatus) {
            return;
        }
        csvStatus.replaceChildren();
        if (!message) {
            csvStatus.classList.add('d-none');
            return;
        }
        csvStatus.className = `alert alert-${tone} mt-3`;
        const messageNode = document.createElement('div');
        messageNode.textContent = message;
        csvStatus.appendChild(messageNode);
    };

    const userTypeLabel = identifier => {
        if (isEmailLike(identifier)) {
            return 'Email';
        }
        if (isGuidLike(identifier)) {
            return 'User ID';
        }
        return 'Identifier';
    };

    const addAllowedUsers = (rawItems, options = {}) => {
        const { source = 'manual' } = options;
        const normalizedItems = rawItems
            .map(normalizeUserPolicyValue)
            .filter(Boolean);
        if (normalizedItems.length === 0) {
            showToast('Enter at least one email or user ID to add.', 'warning');
            return 0;
        }

        const existingItems = new Set(allowedUsers.map(item => item.toLowerCase()));
        const startingCount = allowedUsers.length;
        normalizedItems.forEach(item => {
            const itemKey = item.toLowerCase();
            if (!existingItems.has(itemKey)) {
                allowedUsers.push(item);
                existingItems.add(itemKey);
            }
        });

        const addedCount = allowedUsers.length - startingCount;
        if (addedCount > 0) {
            renderAllowedUsers();
            syncHiddenField();
            showToast(`${addedCount} allowed user${addedCount === 1 ? '' : 's'} added.`, 'success');
        } else if (source !== 'initial') {
            showToast('No new allowed users were added.', 'info');
        }
        return addedCount;
    };

    const removeAllowedUser = identifier => {
        const normalizedIdentifier = normalizeUserPolicyValue(identifier);
        allowedUsers = allowedUsers.filter(item => item.toLowerCase() !== normalizedIdentifier.toLowerCase());
        renderAllowedUsers();
        syncHiddenField();
    };

    const renderAllowedUsers = () => {
        const filterValue = normalizeUserPolicyValue(filterInput ? filterInput.value : '');
        const filteredUsers = allowedUsers.filter(identifier => !filterValue || identifier.includes(filterValue));
        usersTableBody.replaceChildren();

        if (summary) {
            summary.textContent = allowedUsers.length === 0
                ? 'No specific users selected.'
                : `${allowedUsers.length} allowed user${allowedUsers.length === 1 ? '' : 's'} selected.`;
        }
        if (countLabel) {
            countLabel.textContent = allowedUsers.length === 0
                ? 'All signed-in users are allowed.'
                : `${allowedUsers.length} allowed user${allowedUsers.length === 1 ? '' : 's'}.`;
        }

        if (filteredUsers.length === 0) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 3;
            cell.className = 'text-center text-muted py-4';
            cell.textContent = allowedUsers.length === 0 ? 'No allowed users configured.' : 'No allowed users match the filter.';
            row.appendChild(cell);
            usersTableBody.appendChild(row);
            return;
        }

        filteredUsers.forEach(identifier => {
            const row = document.createElement('tr');

            const identifierCell = document.createElement('td');
            identifierCell.textContent = identifier;

            const typeCell = document.createElement('td');
            typeCell.textContent = userTypeLabel(identifier);

            const actionCell = document.createElement('td');
            const removeButton = createIconButton('bi bi-trash', 'Remove allowed user', 'btn-outline-danger');
            removeButton.addEventListener('click', () => removeAllowedUser(identifier));
            actionCell.appendChild(removeButton);

            row.appendChild(identifierCell);
            row.appendChild(typeCell);
            row.appendChild(actionCell);
            usersTableBody.appendChild(row);
        });
    };

    const renderSearchResults = users => {
        const tableBody = searchResultsTable ? searchResultsTable.querySelector('tbody') : null;
        if (!tableBody) {
            return;
        }
        tableBody.replaceChildren();

        if (!Array.isArray(users) || users.length === 0) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 3;
            cell.className = 'text-center text-muted';
            cell.textContent = 'No results.';
            row.appendChild(cell);
            tableBody.appendChild(row);
            return;
        }

        users.forEach(user => {
            const identifier = normalizeUserPolicyValue(user.email || user.id || '');
            const row = document.createElement('tr');

            const nameCell = document.createElement('td');
            nameCell.textContent = user.displayName || '(no name)';

            const emailCell = document.createElement('td');
            emailCell.textContent = user.email || user.id || '';

            const actionCell = document.createElement('td');
            const selectButton = document.createElement('button');
            selectButton.type = 'button';
            selectButton.className = 'btn btn-sm btn-primary';
            selectButton.textContent = 'Select';
            selectButton.disabled = !identifier;
            selectButton.addEventListener('click', () => {
                addAllowedUsers([identifier], { source: 'search' });
            });
            actionCell.appendChild(selectButton);

            row.appendChild(nameCell);
            row.appendChild(emailCell);
            row.appendChild(actionCell);
            tableBody.appendChild(row);
        });
    };

    const searchUsers = async () => {
        if (!searchInput || !searchButton) {
            return;
        }
        const query = searchInput.value.trim();
        if (!query) {
            searchInput.classList.add('is-invalid');
            setSearchStatus('Enter a name or email to search.', 'warning');
            return;
        }

        searchInput.classList.remove('is-invalid');
        searchButton.disabled = true;
        setSearchStatus('Searching...', 'muted');

        try {
            const response = await fetch(`/api/userSearch?query=${encodeURIComponent(query)}`, {
                credentials: 'same-origin',
            });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || response.statusText || 'User search failed');
            }
            renderSearchResults(payload);
            const resultCount = Array.isArray(payload) ? payload.length : 0;
            setSearchStatus(
                resultCount > 0 ? `Found ${resultCount} user(s).` : 'No users found.',
                resultCount > 0 ? 'success' : 'muted'
            );
        } catch (error) {
            renderSearchResults([]);
            setSearchStatus(`Search failed: ${error.message}`, 'danger');
            showToast(`User search failed: ${error.message}`, 'danger');
        } finally {
            searchButton.disabled = false;
        }
    };

    const addManualUser = () => {
        if (!manualIdentifierInput) {
            return;
        }
        const addedCount = addAllowedUsers([manualIdentifierInput.value], { source: 'manual' });
        if (addedCount > 0) {
            manualIdentifierInput.value = '';
            manualIdentifierInput.focus();
        }
    };

    const downloadCsvExample = () => {
        const csvContent = 'userId,displayName,email\n00000000-0000-0000-0000-000000000001,John Smith,john.smith@contoso.com\n00000000-0000-0000-0000-000000000002,Jane Doe,jane.doe@contoso.com\n';
        const blob = new Blob([csvContent], { type: 'text/csv' });
        const objectUrl = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = 'deep_research_allowed_users_example.csv';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(objectUrl);
    };

    const handleCsvFileSelect = event => {
        const file = event.target.files[0];
        if (!file) {
            setCsvStatus('');
            return;
        }

        const reader = new FileReader();
        reader.onload = loadEvent => {
            try {
                const parsedUsers = parseDeepResearchAllowedUsersCsv(loadEvent.target.result || '');
                const addedCount = addAllowedUsers(parsedUsers, { source: 'csv' });
                setCsvStatus(
                    `${parsedUsers.length} valid row${parsedUsers.length === 1 ? '' : 's'} parsed. ${addedCount} new allowed user${addedCount === 1 ? '' : 's'} added.`,
                    'success'
                );
            } catch (error) {
                setCsvStatus(error.message, 'danger');
                showToast(error.message, 'danger');
            } finally {
                event.target.value = '';
            }
        };
        reader.onerror = () => {
            setCsvStatus('Unable to read the selected CSV file.', 'danger');
        };
        reader.readAsText(file);
    };

    if (searchButton) {
        searchButton.addEventListener('click', searchUsers);
    }
    if (searchInput) {
        searchInput.addEventListener('keydown', event => {
            if (event.key === 'Enter') {
                event.preventDefault();
                searchUsers();
            }
        });
    }
    if (manualAddButton) {
        manualAddButton.addEventListener('click', addManualUser);
    }
    if (manualIdentifierInput) {
        manualIdentifierInput.addEventListener('keydown', event => {
            if (event.key === 'Enter') {
                event.preventDefault();
                addManualUser();
            }
        });
    }
    if (filterInput) {
        filterInput.addEventListener('input', renderAllowedUsers);
    }
    if (csvInput) {
        csvInput.addEventListener('change', handleCsvFileSelect);
    }
    if (csvExampleButton) {
        csvExampleButton.addEventListener('click', downloadCsvExample);
    }

    syncHiddenField(false);
    renderAllowedUsers();
    renderSearchResults([]);
}

function parseDeepResearchAllowedUsersCsv(csvText) {
    const lines = String(csvText || '')
        .split(/\r?\n/)
        .filter(line => line.trim());
    if (lines.length < 2) {
        throw new Error('CSV must contain a header row and at least one data row.');
    }

    const headers = parseCsvLine(lines[0]).map(header => header.trim().toLowerCase());
    const userIdIndex = headers.indexOf('userid');
    const emailIndex = headers.indexOf('email');
    if (emailIndex < 0 && userIdIndex < 0) {
        throw new Error('CSV must include an email or userId column.');
    }

    const dataRows = lines.slice(1);
    if (dataRows.length > 1000) {
        throw new Error(`Too many rows. Maximum 1,000 users allowed (found ${dataRows.length}).`);
    }

    const parsedUsers = [];
    const errors = [];
    dataRows.forEach((line, index) => {
        const rowNumber = index + 2;
        const columns = parseCsvLine(line);
        const email = emailIndex >= 0 ? normalizeUserPolicyValue(columns[emailIndex] || '') : '';
        const userId = userIdIndex >= 0 ? normalizeUserPolicyValue(columns[userIdIndex] || '') : '';
        const identifier = email || userId;
        if (!identifier) {
            errors.push(`Row ${rowNumber}: email or userId is required.`);
            return;
        }
        if (email && !isEmailLike(email)) {
            errors.push(`Row ${rowNumber}: invalid email format.`);
            return;
        }
        if (!email && userId && !isGuidLike(userId)) {
            errors.push(`Row ${rowNumber}: invalid userId format.`);
            return;
        }
        parsedUsers.push(identifier);
    });

    if (errors.length > 0) {
        throw new Error(`Found ${errors.length} validation error(s): ${errors.slice(0, 5).join(' ')}`);
    }
    if (parsedUsers.length === 0) {
        throw new Error('No valid allowed users were found in the CSV file.');
    }
    return parsedUsers;
}

function parseCsvLine(line) {
    const columns = [];
    let currentValue = '';
    let insideQuotes = false;
    const value = String(line || '');

    for (let index = 0; index < value.length; index++) {
        const character = value[index];
        const nextCharacter = value[index + 1];
        if (character === '"' && insideQuotes && nextCharacter === '"') {
            currentValue += '"';
            index++;
            continue;
        }
        if (character === '"') {
            insideQuotes = !insideQuotes;
            continue;
        }
        if (character === ',' && !insideQuotes) {
            columns.push(currentValue.trim());
            currentValue = '';
            continue;
        }
        currentValue += character;
    }
    columns.push(currentValue.trim());
    return columns;
}

function isEmailLike(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value || '').trim());
}

function isGuidLike(value) {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(String(value || '').trim());
}

function normalizeGroupWorkflowGroupId(value) {
    const groupId = String(value || '').trim();
    return isGuidLike(groupId) ? groupId.toLowerCase() : '';
}

function collectGroupWorkflowAssignmentIds(value, depth = 0) {
    if (depth > GROUP_WORKFLOW_ASSIGNMENT_PARSE_DEPTH_LIMIT) {
        return [];
    }

    const rawValue = String(value || '').trim();
    if (!rawValue) {
        return [];
    }

    if (rawValue.startsWith('[') || rawValue.startsWith('"')) {
        try {
            const parsedValue = JSON.parse(rawValue);
            if (Array.isArray(parsedValue)) {
                const nestedIds = [];
                parsedValue.forEach(item => {
                    nestedIds.push(...collectGroupWorkflowAssignmentIds(item, depth + 1));
                });
                return nestedIds;
            }
            if (typeof parsedValue === 'string' && parsedValue !== rawValue) {
                return collectGroupWorkflowAssignmentIds(parsedValue, depth + 1);
            }
        } catch (error) {
            // Fall back to delimiter parsing for older saved form values.
        }
    }

    return rawValue
        .split(/[\n,;]+/)
        .map(normalizeGroupWorkflowGroupId)
        .filter(Boolean);
}

function parseGroupWorkflowAssignmentIds(value) {
    return Array.from(new Set(collectGroupWorkflowAssignmentIds(value)));
}

function syncGroupWorkflowAssignmentField() {
    if (!groupWorkflowAssignmentsInput) {
        return;
    }

    groupWorkflowAssignmentsInput.value = JSON.stringify(Array.from(groupWorkflowAssignedGroupIds));
}

function updateGroupWorkflowAssignmentSummary() {
    if (!groupWorkflowAssignmentSummary) {
        return;
    }

    const assignedCount = groupWorkflowAssignedGroupIds.size;
    groupWorkflowAssignmentSummary.textContent = assignedCount === 1
        ? '1 group assigned.'
        : `${assignedCount} groups assigned.`;
}

function setGroupWorkflowAssignmentError(message) {
    if (!groupWorkflowAssignmentError) {
        return;
    }

    groupWorkflowAssignmentError.textContent = message || '';
    groupWorkflowAssignmentError.classList.toggle('d-none', !message);
}

function setGroupWorkflowAssignmentStatus(message) {
    if (groupWorkflowAssignmentStatus) {
        groupWorkflowAssignmentStatus.textContent = message || '';
    }
}

function createGroupWorkflowAssignmentEmptyRow(message) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 3;
    cell.className = 'text-center text-muted py-3';
    cell.textContent = message;
    row.appendChild(cell);
    return row;
}

function renderGroupWorkflowAssignmentRows(groups) {
    if (!groupWorkflowAssignmentGroupsBody) {
        return;
    }

    groupWorkflowAssignmentGroupsBody.replaceChildren();

    if (!Array.isArray(groups) || groups.length === 0) {
        groupWorkflowAssignmentGroupsBody.appendChild(createGroupWorkflowAssignmentEmptyRow('No groups found.'));
        return;
    }

    const rows = groups.map(group => {
        const groupId = normalizeGroupWorkflowGroupId(group?.id);
        const row = document.createElement('tr');

        const nameCell = document.createElement('td');
        const name = document.createElement('div');
        name.className = 'fw-semibold';
        name.textContent = group?.name || 'Unnamed group';
        const meta = document.createElement('div');
        meta.className = 'small text-muted';
        meta.textContent = groupId;
        nameCell.appendChild(name);
        nameCell.appendChild(meta);

        const descriptionCell = document.createElement('td');
        descriptionCell.textContent = group?.description || '-';

        const actionCell = document.createElement('td');
        actionCell.className = 'text-end';
        const actionButton = document.createElement('button');
        actionButton.type = 'button';
        actionButton.className = groupWorkflowAssignedGroupIds.has(groupId)
            ? 'btn btn-sm btn-outline-danger'
            : 'btn btn-sm btn-outline-primary';
        actionButton.textContent = groupWorkflowAssignedGroupIds.has(groupId) ? 'Remove' : 'Assign';
        actionButton.disabled = !groupId;
        actionButton.addEventListener('click', () => {
            if (!groupId) {
                return;
            }
            if (groupWorkflowAssignedGroupIds.has(groupId)) {
                groupWorkflowAssignedGroupIds.delete(groupId);
            } else {
                groupWorkflowAssignedGroupIds.add(groupId);
                groupWorkflowDiscoveredGroups.set(groupId, group);
            }
            syncGroupWorkflowAssignmentField();
            updateGroupWorkflowAssignmentSummary();
            renderGroupWorkflowAssignmentRows(groups);
            markFormAsModified();
        });
        actionCell.appendChild(actionButton);

        row.appendChild(nameCell);
        row.appendChild(descriptionCell);
        row.appendChild(actionCell);
        return row;
    });

    groupWorkflowAssignmentGroupsBody.replaceChildren(...rows);
}

async function searchGroupWorkflowAssignmentGroups() {
    if (!groupWorkflowAssignmentGroupsBody) {
        return;
    }

    const query = groupWorkflowGroupSearchInput?.value?.trim() || '';
    const originalButtonText = groupWorkflowGroupSearchBtn?.textContent || 'Search';

    setGroupWorkflowAssignmentError('');
    setGroupWorkflowAssignmentStatus('Searching groups...');
    if (groupWorkflowGroupSearchBtn) {
        groupWorkflowGroupSearchBtn.disabled = true;
        groupWorkflowGroupSearchBtn.textContent = 'Searching...';
    }

    try {
        const url = new URL('/api/groups/discover', window.location.origin);
        url.searchParams.set('showAll', 'true');
        if (query) {
            url.searchParams.set('search', query);
        }

        const response = await fetch(url.toString(), { headers: { 'Accept': 'application/json' } });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload?.error || 'Unable to load groups.');
        }

        const groups = Array.isArray(payload) ? payload : [];
        groups.forEach(group => {
            const groupId = normalizeGroupWorkflowGroupId(group?.id);
            if (groupId) {
                groupWorkflowDiscoveredGroups.set(groupId, group);
            }
        });
        renderGroupWorkflowAssignmentRows(groups);
        setGroupWorkflowAssignmentStatus(groups.length === 1 ? '1 group found.' : `${groups.length} groups found.`);
    } catch (error) {
        setGroupWorkflowAssignmentError(error.message || 'Unable to load groups.');
        setGroupWorkflowAssignmentStatus('Search failed.');
    } finally {
        if (groupWorkflowGroupSearchBtn) {
            groupWorkflowGroupSearchBtn.disabled = false;
            groupWorkflowGroupSearchBtn.textContent = originalButtonText;
        }
    }
}

function setupGroupWorkflowAssignments() {
    if (!groupWorkflowAssignmentsInput) {
        return;
    }

    parseGroupWorkflowAssignmentIds(groupWorkflowAssignmentsInput.value).forEach(groupId => {
        groupWorkflowAssignedGroupIds.add(groupId);
    });
    syncGroupWorkflowAssignmentField();
    updateGroupWorkflowAssignmentSummary();

    if (groupWorkflowAssignmentGroupsBody && groupWorkflowAssignedGroupIds.size > 0) {
        groupWorkflowAssignmentGroupsBody.replaceChildren(createGroupWorkflowAssignmentEmptyRow('Search for groups to review current assignments.'));
    }

    groupWorkflowGroupSearchBtn?.addEventListener('click', searchGroupWorkflowAssignmentGroups);
    groupWorkflowGroupSearchInput?.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            event.preventDefault();
            void searchGroupWorkflowAssignmentGroups();
        }
    });
    groupWorkflowAssignmentModal?.addEventListener('shown.bs.modal', () => {
        if (groupWorkflowDiscoveredGroups.size === 0) {
            void searchGroupWorkflowAssignmentGroups();
        }
    });
    adminForm?.addEventListener('submit', syncGroupWorkflowAssignmentField);
}

function parseFileDownloadAssignmentIds(value) {
    const rawValue = String(value || '').trim();
    if (!rawValue) {
        return [];
    }

    try {
        const parsedValue = JSON.parse(rawValue);
        if (Array.isArray(parsedValue)) {
            return parsedValue.map(item => String(item || '').trim()).filter(Boolean);
        }
    } catch (error) {
        // Fall back to comma/newline parsing for older saved form values.
    }

    return rawValue
        .split(/[\n,;]+/)
        .map(item => String(item || '').trim())
        .filter(Boolean);
}

function createFileDownloadAssignmentManager(config) {
    const assignedIds = new Set();

    function syncField() {
        if (config.input) {
            config.input.value = JSON.stringify(Array.from(assignedIds));
        }
    }

    function updateSummary() {
        if (!config.summary) {
            return;
        }

        const count = assignedIds.size;
        config.summary.textContent = count === 1
            ? `1 ${config.summarySingular} assigned.`
            : `${count} ${config.summaryPlural} assigned.`;
    }

    function setError(message) {
        if (!config.error) {
            return;
        }

        config.error.textContent = message || '';
        config.error.classList.toggle('d-none', !message);
    }

    function setStatus(message) {
        if (config.status) {
            config.status.textContent = message || '';
        }
    }

    function createEmptyRow(message) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 3;
        cell.className = 'text-center text-muted py-3';
        cell.textContent = message;
        row.appendChild(cell);
        return row;
    }

    function renderRows(items) {
        if (!config.body) {
            return;
        }

        if (!Array.isArray(items) || items.length === 0) {
            config.body.replaceChildren(createEmptyRow(config.emptyMessage));
            return;
        }

        const rows = items.map(item => {
            const itemId = String(item?.id || '').trim();
            const row = document.createElement('tr');

            const nameCell = document.createElement('td');
            const name = document.createElement('div');
            name.className = 'fw-semibold';
            name.textContent = item?.[config.titleField] || config.unnamedLabel;
            const meta = document.createElement('div');
            meta.className = 'small text-muted';
            meta.textContent = itemId;
            nameCell.appendChild(name);
            nameCell.appendChild(meta);

            const descriptionCell = document.createElement('td');
            descriptionCell.textContent = item?.description || '-';

            const actionCell = document.createElement('td');
            actionCell.className = 'text-end';
            const actionButton = document.createElement('button');
            actionButton.type = 'button';
            actionButton.className = assignedIds.has(itemId)
                ? 'btn btn-sm btn-outline-danger'
                : 'btn btn-sm btn-outline-primary';
            actionButton.textContent = assignedIds.has(itemId) ? 'Remove' : 'Assign';
            actionButton.disabled = !itemId;
            actionButton.addEventListener('click', () => {
                if (!itemId) {
                    return;
                }
                if (assignedIds.has(itemId)) {
                    assignedIds.delete(itemId);
                } else {
                    assignedIds.add(itemId);
                }
                syncField();
                updateSummary();
                renderRows(items);
                markFormAsModified();
            });
            actionCell.appendChild(actionButton);

            row.appendChild(nameCell);
            row.appendChild(descriptionCell);
            row.appendChild(actionCell);
            return row;
        });

        config.body.replaceChildren(...rows);
    }

    async function searchItems() {
        if (!config.body) {
            return;
        }

        const query = config.searchInput?.value?.trim() || '';
        const originalButtonText = config.searchButton?.textContent || 'Search';
        setError('');
        setStatus(`Searching ${config.summaryPlural}...`);

        if (config.searchButton) {
            config.searchButton.disabled = true;
            config.searchButton.textContent = 'Searching...';
        }

        try {
            const url = new URL(config.endpoint, window.location.origin);
            if (query) {
                url.searchParams.set('search', query);
                url.searchParams.set('q', query);
            }
            if (config.showAll) {
                url.searchParams.set('showAll', 'true');
            }

            const response = await fetch(url.toString(), { headers: { 'Accept': 'application/json' } });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload?.error || `Unable to load ${config.summaryPlural}.`);
            }

            const items = Array.isArray(payload)
                ? payload
                : (Array.isArray(payload?.[config.resultsKey]) ? payload[config.resultsKey] : []);
            renderRows(items);
            setStatus(items.length === 1 ? `1 ${config.summarySingular} found.` : `${items.length} ${config.summaryPlural} found.`);
        } catch (error) {
            setError(error.message || `Unable to load ${config.summaryPlural}.`);
            setStatus('Search failed.');
        } finally {
            if (config.searchButton) {
                config.searchButton.disabled = false;
                config.searchButton.textContent = originalButtonText;
            }
        }
    }

    function setup() {
        if (!config.input) {
            return;
        }

        parseFileDownloadAssignmentIds(config.input.value).forEach(itemId => assignedIds.add(itemId));
        syncField();
        updateSummary();

        if (config.body && assignedIds.size > 0) {
            config.body.replaceChildren(createEmptyRow(config.reviewMessage));
        }

        config.searchButton?.addEventListener('click', searchItems);
        config.searchInput?.addEventListener('keydown', event => {
            if (event.key === 'Enter') {
                event.preventDefault();
                void searchItems();
            }
        });
        config.modal?.addEventListener('shown.bs.modal', () => {
            if (config.body && config.body.children.length <= 1) {
                void searchItems();
            }
        });
        adminForm?.addEventListener('submit', syncField);
    }

    return { setup };
}

function setupFileDownloadAssignments() {
    createFileDownloadAssignmentManager({
        input: fileDownloadGroupAssignmentsInput,
        summary: fileDownloadGroupAssignmentSummary,
        modal: fileDownloadGroupAssignmentModal,
        searchInput: fileDownloadGroupSearchInput,
        searchButton: fileDownloadGroupSearchBtn,
        status: fileDownloadGroupAssignmentStatus,
        error: fileDownloadGroupAssignmentError,
        body: fileDownloadGroupAssignmentBody,
        endpoint: '/api/groups/discover',
        resultsKey: 'groups',
        titleField: 'name',
        summarySingular: 'group',
        summaryPlural: 'groups',
        unnamedLabel: 'Unnamed group',
        emptyMessage: 'No groups found.',
        reviewMessage: 'Search for groups to review current assignments.',
        showAll: true,
    }).setup();

    createFileDownloadAssignmentManager({
        input: fileDownloadPublicAssignmentsInput,
        summary: fileDownloadPublicAssignmentSummary,
        modal: fileDownloadPublicAssignmentModal,
        searchInput: fileDownloadPublicSearchInput,
        searchButton: fileDownloadPublicSearchBtn,
        status: fileDownloadPublicAssignmentStatus,
        error: fileDownloadPublicAssignmentError,
        body: fileDownloadPublicAssignmentBody,
        endpoint: '/api/admin/file-sync/public-workspaces/search',
        resultsKey: 'workspaces',
        titleField: 'name',
        summarySingular: 'public workspace',
        summaryPlural: 'public workspaces',
        unnamedLabel: 'Unnamed public workspace',
        emptyMessage: 'No public workspaces found.',
        reviewMessage: 'Search for public workspaces to review current assignments.',
    }).setup();
}

function setKeyVaultReminderStatus(message, variant = 'info') {
    const statusElement = document.getElementById('key-vault-reminders-status-message');
    if (!statusElement) {
        return;
    }

    statusElement.textContent = message || '';
    statusElement.className = `alert alert-${variant}${message ? '' : ' d-none'}`;
}

function appendKeyVaultReminderCell(row, text, className = '') {
    const cell = document.createElement('td');
    if (className) {
        cell.className = className;
    }
    cell.textContent = text || '';
    row.appendChild(cell);
}

function formatKeyVaultReminderExpiry(reminder) {
    const expiresOn = reminder.expires_on || 'Unknown';
    if (typeof reminder.days_until_expiry !== 'number') {
        return expiresOn;
    }
    if (reminder.days_until_expiry < 0) {
        return `${expiresOn} (${Math.abs(reminder.days_until_expiry)} days expired)`;
    }
    if (reminder.days_until_expiry === 0) {
        return `${expiresOn} (today)`;
    }
    return `${expiresOn} (${reminder.days_until_expiry} days)`;
}

function renderKeyVaultReminderInventory(reminders) {
    const tableBody = document.getElementById('key-vault-reminders-table-body');
    if (!tableBody) {
        return;
    }

    tableBody.replaceChildren();
    if (!Array.isArray(reminders) || reminders.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 8;
        cell.className = 'text-muted';
        cell.textContent = 'No Key Vault reminder inventory entries match the current filters.';
        row.appendChild(cell);
        tableBody.appendChild(row);
        return;
    }

    reminders.forEach(reminder => {
        const row = document.createElement('tr');
        const sourceLabel = reminder.source_display_name || reminder.source_name || reminder.source_id || '';
        const fieldLabel = reminder.field_label || reminder.field_path || '';
        const statusLabel = reminder.key_vault_sync_status === 'sync_failed'
            ? `${reminder.status || 'sync_failed'}: ${reminder.key_vault_sync_error || 'Key Vault sync failed'}`
            : (reminder.status || '');

        appendKeyVaultReminderCell(row, formatKeyVaultReminderExpiry(reminder));
        appendKeyVaultReminderCell(row, `${reminder.scope || ''}: ${reminder.scope_value || ''}`);
        appendKeyVaultReminderCell(row, sourceLabel);
        appendKeyVaultReminderCell(row, fieldLabel);
        appendKeyVaultReminderCell(row, reminder.contact_email || '');
        appendKeyVaultReminderCell(row, statusLabel);
        appendKeyVaultReminderCell(row, reminder.id || '', 'font-monospace small');
        appendKeyVaultReminderCell(row, reminder.secret_name || '', 'font-monospace small');
        tableBody.appendChild(row);
    });
}

async function loadKeyVaultReminderInventory() {
    const refreshButton = document.getElementById('key-vault-reminders-refresh');
    const searchInput = document.getElementById('key-vault-reminders-search');
    const statusSelect = document.getElementById('key-vault-reminders-status');
    const params = new URLSearchParams();
    if (searchInput?.value.trim()) {
        params.set('search', searchInput.value.trim());
    }
    if (statusSelect?.value) {
        params.set('status', statusSelect.value);
    }

    setKeyVaultReminderStatus('Loading Key Vault reminder inventory...', 'info');
    if (refreshButton) {
        refreshButton.disabled = true;
    }

    try {
        const response = await fetch(`/api/admin/settings/key-vault/secret-reminders?${params.toString()}`);
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to load Key Vault reminder inventory.');
        }
        renderKeyVaultReminderInventory(data.reminders || []);
        setKeyVaultReminderStatus(`Loaded ${Array.isArray(data.reminders) ? data.reminders.length : 0} reminder entries.`, 'success');
    } catch (error) {
        renderKeyVaultReminderInventory([]);
        setKeyVaultReminderStatus(error.message || 'Failed to load Key Vault reminder inventory.', 'danger');
    } finally {
        if (refreshButton) {
            refreshButton.disabled = false;
        }
    }
}

async function runKeyVaultReminderSweep() {
    const runButton = document.getElementById('key-vault-reminders-run');
    setKeyVaultReminderStatus('Running Key Vault reminder sweep...', 'info');
    if (runButton) {
        runButton.disabled = true;
    }

    try {
        const response = await fetch('/api/admin/settings/key-vault/secret-reminders/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to run Key Vault reminder sweep.');
        }
        const result = data.result || {};
        setKeyVaultReminderStatus(
            `Reminder sweep checked ${result.checked || 0} entries and created ${result.notifications_created || 0} notifications.`,
            'success'
        );
        await loadKeyVaultReminderInventory();
    } catch (error) {
        setKeyVaultReminderStatus(error.message || 'Failed to run Key Vault reminder sweep.', 'danger');
    } finally {
        if (runButton) {
            runButton.disabled = false;
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    setupAdminFormAutofillMetadata();

    // --- Existing Setup ---
    renderGPTModels();
    renderEmbeddingModels();
    renderImageModels();

    updateGptHiddenInput();
    updateEmbeddingHiddenInput();
    updateImageHiddenInput();

    setupToggles(); // This function will be extended below
    setupGroupWorkflowAssignments();
    setupFileDownloadAssignments();
    setupLandingPageLogoScaleControl();
    setupDocumentActionCapabilityControls();
    setupDeepResearchPolicyEditors();
    setupDeepResearchAllowedUsersManager();
    
    // Initialize tooltips
    initializeTooltips();

    setupTestButtons();

    activateTabFromHash(); // Keep tab activation logic

    setupLatestFeaturesMirrors();
    setupLatestFeatureImageModal();
    setupSendFeedbackForms();
    setupReleaseNotificationsRegistration();

    document.querySelectorAll('.nav-link').forEach(tab => {
        tab.addEventListener('click', function () {
            history.pushState(null, null, this.getAttribute('data-bs-target'));
        });
    });

    document.addEventListener('click', function (event) {
        const trigger = event.target.closest('[data-open-admin-tab]');
        if (!trigger) {
            return;
        }

        event.preventDefault();
        openAdminSettingsTab(
            trigger.getAttribute('data-open-admin-tab'),
            trigger.getAttribute('data-open-admin-section') || ''
        );
    });

    window.addEventListener("popstate", activateTabFromHash);

    // --- NEW: Classification Setup ---
    setupClassification(); // Initialize classification section
    
    // --- NEW: External Links Setup ---
    setupExternalLinks(); // Initialize external links section

    // --- NEW: Support Menu Setup ---
    setupSupportMenuSettings();

    // --- Agents page promoted Popular tab setup ---
    setupAgentsPagePromotedPopularAgents();

    // --- NEW: Chunk size controls ---
    setupChunkSizeControls();

    setupRedisMonitoringControls();
    setupCosmosMaintenanceControls();
    setupDocumentAccessIndexControls();
    setupCosmosThroughputControls();
    setupFileProcessingLogCleanup();
    setupInboundMcpEntryEditors();
    setupInboundMcpObservabilityCopyButtons();
    setupInboundMcpEasyAuthGuard();
    
    // --- Setup form change tracking ---
    setupFormChangeTracking();

    // --- Setup Settings Walkthrough (after all other components are ready) ---
    setTimeout(() => {
        setupSettingsWalkthrough();
    }, 100);


    // --- Add form submission validation ---
    if (adminForm) {
        adminForm.addEventListener('submit', function(e) {
            try {
                const cosmosValidationResult = validateCosmosThroughputSettings({ report: true });
                if (!cosmosValidationResult.isValid) {
                    e.preventDefault();
                    e.stopImmediatePropagation();
                    return;
                }

                console.log('🚀 Form submission started - gathering tab information...');
                
                // Capture the current active tab before form submission
                const activeTab = getCurrentActiveTab();
                
                if (activeTab) {
                    // Store the active tab in sessionStorage to restore after redirect
                    sessionStorage.setItem('adminSettingsActiveTab', activeTab);
                } else {
                    console.warn('⚠️ Form submission - No active tab detected, tab preservation may not work');
                }
                
                // Ensure classification categories is valid JSON before submission
                if (classificationJsonInput) {
                    const jsonString = updateClassificationJsonInput();
                    console.log("Classification categories before submission:", jsonString);
                    
                    // Verify JSON is valid by parsing it
                    try {
                        JSON.parse(jsonString);
                    } catch (jsonErr) {
                        console.error("Invalid JSON for classification categories:", jsonErr);
                        // Set to empty array if invalid
                        classificationJsonInput.value = "[]";
                    }
                }
            } catch (err) {
                console.error("Error in form submission validation:", err);
                // Allow form to submit even if there's an error to avoid blocking users
            }
        });
    }
});

/**
 * Gets the current active tab's target hash (e.g., "#general", "#agents")
 * @returns {string|null} The hash of the currently active tab, or null if none found
 */
function getCurrentActiveTab() {    
    // First check if we're using sidebar navigation
    const sidebarToggle = document.getElementById('admin-settings-toggle');
    
    if (sidebarToggle) {
        
        // For sidebar navigation, check for active sidebar nav links
        // First check for active section (more specific)
        const activeSidebarSection = document.querySelector('.admin-nav-section.active');
        if (activeSidebarSection) {
            const tabId = activeSidebarSection.getAttribute('data-tab');
            return tabId ? '#' + tabId : null;
        }
        
        // Then check for active tab (less specific)
        const activeSidebarTab = document.querySelector('.admin-nav-tab.active');
        console.log('🔍 getCurrentActiveTab - Looking for .admin-nav-tab.active:', activeSidebarTab);
        if (activeSidebarTab) {
            const tabId = activeSidebarTab.getAttribute('data-tab');
            return tabId ? '#' + tabId : null;
        }
        
        // Fallback: check which tab pane is currently visible for sidebar nav
        const activeTabPane = document.querySelector('.tab-pane.show.active');
        if (activeTabPane) {
            return '#' + activeTabPane.id;
        }
        
        // If no active tab found but we have a hash, use that
        if (window.location.hash) {
            return window.location.hash;
        }
                
        // Debug: List all available sidebar navigation elements
        const allSections = document.querySelectorAll('.admin-nav-section');
        const allTabs = document.querySelectorAll('.admin-nav-tab');
        const allPanes = document.querySelectorAll('.tab-pane');
        allSections.forEach(section => {
            console.log('  - Section:', section.getAttribute('data-tab'), 'active:', section.classList.contains('active'));
        });
        allTabs.forEach(tab => {
            console.log('  - Tab:', tab.getAttribute('data-tab'), 'active:', tab.classList.contains('active'));
        });
        allPanes.forEach(pane => {
            console.log('  - Pane:', pane.id, 'show:', pane.classList.contains('show'), 'active:', pane.classList.contains('active'));
        });
        
    } else {
        
        // For tab navigation, check Bootstrap tab buttons
        const activeTabButton = document.querySelector('button.nav-link.active[data-bs-target]');
        console.log('🔍 getCurrentActiveTab - Looking for button.nav-link.active[data-bs-target]:', activeTabButton);
        if (activeTabButton) {
            const target = activeTabButton.getAttribute('data-bs-target');
            return target;
        }
        
        // Fallback: check which tab pane is currently visible for tab nav
        const activeTabPane = document.querySelector('.tab-pane.fade.show.active');
        console.log('🔍 getCurrentActiveTab - Looking for .tab-pane.fade.show.active:', activeTabPane);
        if (activeTabPane) {
            return '#' + activeTabPane.id;
        }
        
        console.log('❌ getCurrentActiveTab - No active Bootstrap tab elements found');
    }
    
    console.log('❌ getCurrentActiveTab - No active tab found anywhere');
    return null;
}

function activateTabFromHash() {
    const timestamp = new Date().toLocaleTimeString();
    console.log('activateTabFromHash - Called');
    
    let hash = window.location.hash;
    
    // If no hash in URL, check sessionStorage for saved tab from form submission
    if (!hash) {
        const savedTab = sessionStorage.getItem('adminSettingsActiveTab');
        
        if (savedTab) {
            hash = savedTab;
            
            // Clear the saved tab to prevent it from affecting future navigation
            sessionStorage.removeItem('adminSettingsActiveTab');
            
            // Update URL with the restored hash
            history.replaceState(null, null, hash);
        } else {
            console.log(`❌ [${timestamp}] activateTabFromHash - No saved tab found in sessionStorage`);
        }
    } else {
        console.log(`✅ [${timestamp}] activateTabFromHash - Hash found in URL:`, hash);
    }
    
    if (hash) {
        const tabId = hash.startsWith('#') ? hash.substring(1) : hash;
        
        // Check if we're using sidebar navigation
        const sidebarToggle = document.getElementById('admin-settings-toggle');
        
        if (sidebarToggle) {
            // Try different ways to access the showAdminTab function
            let showTabFunction = null;
            if (typeof showAdminTab === 'function') {
                showTabFunction = showAdminTab;
            } else if (typeof window.showAdminTab === 'function') {
                showTabFunction = window.showAdminTab;
            }
            
            if (showTabFunction) {
                showTabFunction(tabId);
            } else {
                // Manual tab activation fallback
                // Hide all tab panes
                document.querySelectorAll('.tab-pane').forEach(pane => {
                    pane.classList.remove('show', 'active');
                });
                
                // Show the selected tab pane
                const targetTab = document.getElementById(tabId);
                if (targetTab) {
                    targetTab.classList.add('show', 'active');
                }
            }
            
            // Set active nav link for sidebar - handle both tab and section level
            
            // First clear all active states
            const allTabs = document.querySelectorAll('.admin-nav-tab');
            const allSections = document.querySelectorAll('.admin-nav-section');
            
            allTabs.forEach(link => {
                link.classList.remove('active');
            });
            allSections.forEach(link => {
                link.classList.remove('active');
            });
            
            // Set the main tab as active
            const navLink = document.querySelector(`.admin-nav-tab[data-tab="${tabId}"]`);
            const navSection = document.querySelector(`.admin-nav-section[data-tab="${tabId}"]`);
            
            if (navLink) {
                navLink.classList.add('active');
            }
            
            if (navSection) {
                navSection.classList.add('active');
            }
            
            // Also expand the submenu if it exists
            const submenu = document.getElementById(tabId + '-submenu');
            if (submenu) {
                submenu.style.display = 'block';
            }
            
        } else {
            // Use Bootstrap tab navigation
            const tabButton = document.querySelector(`button.nav-link[data-bs-target="${hash}"]`);
            if (tabButton) {
                const tab = new bootstrap.Tab(tabButton);
                tab.show();
            }
        }
    }
}

function renderGPTModels() {
    const listDiv = document.getElementById('gpt_models_list');
    if (!listDiv) return;

    if (!gptAll || gptAll.length === 0) {
        listDiv.innerHTML = '<p class="text-warning">No GPT models found. Click "Fetch GPT Models" to populate.</p>';
        return;
    }

    let html = '<ul class="list-group">';
    gptAll.forEach(m => {
        const isSelected = gptSelected.some(sel => sel.deploymentName === m.deploymentName);
        // use green for selected, blue for not
        const btnClass = isSelected ? 'btn-success' : 'btn-primary';
        const btnLabel = isSelected ? 'Selected' : 'Select';

        html += `
            <li class="list-group-item d-flex justify-content-between align-items-center">
                <span>${m.deploymentName} (Model: ${m.modelName})</span>
                <button
                  class="btn btn-sm ${btnClass}"
                  onclick="selectGptModel('${m.deploymentName}', '${m.modelName}')"
                >
                  ${btnLabel}
                </button>
            </li>
        `;
    });
    html += '</ul>';
    listDiv.innerHTML = html;
}


function renderEmbeddingModels() {
    const listDiv = document.getElementById('embedding_models_list');
    if (!listDiv) return;

    if (!embeddingAll || embeddingAll.length === 0) {
        listDiv.innerHTML = '<p class="text-warning">No embedding models found. Click "Fetch Embedding Models" to populate.</p>';
        return;
    }

    let html = '<ul class="list-group">';
    embeddingAll.forEach(m => {
        const isSelected = embeddingSelected.some(sel =>
            sel.deploymentName === m.deploymentName &&
            sel.modelName === m.modelName
        );
        const buttonLabel = isSelected ? 'Selected' : 'Select';
        const buttonDisabled = isSelected ? 'disabled' : '';
        html += `
            <li class="list-group-item d-flex justify-content-between align-items-center">
                <span>${m.deploymentName} (Model: ${m.modelName})</span>
                <button class="btn btn-sm btn-primary" ${buttonDisabled}
                    onclick="selectEmbeddingModel('${m.deploymentName}', '${m.modelName}')">
                    ${buttonLabel}
                </button>
            </li>
        `;
    });
    html += '</ul>';
    listDiv.innerHTML = html;
}

function renderImageModels() {
    const listDiv = document.getElementById('image_models_list');
    if (!listDiv) return;

    if (!imageAll || imageAll.length === 0) {
        listDiv.innerHTML = '<p class="text-warning">No image models found. Click "Fetch Image Models" to populate.</p>';
        return;
    }

    let html = '<ul class="list-group">';
    imageAll.forEach(m => {
        const isSelected = imageSelected.some(sel =>
            sel.deploymentName === m.deploymentName &&
            sel.modelName === m.modelName
        );
        const buttonLabel = isSelected ? 'Selected' : 'Select';
        const buttonDisabled = isSelected ? 'disabled' : '';
        html += `
            <li class="list-group-item d-flex justify-content-between align-items-center">
                <span>${m.deploymentName} (Model: ${m.modelName})</span>
                <button class="btn btn-sm btn-primary" ${buttonDisabled}
                    onclick="selectImageModel('${m.deploymentName}', '${m.modelName}')">
                    ${buttonLabel}
                </button>
            </li>
        `;
    });
    html += '</ul>';
    listDiv.innerHTML = html;
}

const fetchGptBtn = document.getElementById('fetch_gpt_models_btn');
if (fetchGptBtn) {
    fetchGptBtn.addEventListener('click', async () => {
        const listDiv = document.getElementById('gpt_models_list');
        listDiv.innerHTML = 'Fetching...';
        try {
            const resp = await fetch('/api/models/gpt');
            const data = await resp.json();
            if (resp.ok && data.models && data.models.length > 0) {
                // Clear old models and replace with new ones
                gptAll = data.models;
                
                // Filter out selected models that no longer exist in the newly fetched list
                gptSelected = gptSelected.filter(selected => 
                    gptAll.some(model => model.deploymentName === selected.deploymentName)
                );
                
                renderGPTModels();
                updateGptHiddenInput();
                markFormAsModified();
            } else {
                listDiv.innerHTML = `<p class="text-danger">Error: ${data.error || 'No GPT models found'}</p>`;
            }
        } catch (err) {
            listDiv.innerHTML = `<p class="text-danger">Error fetching GPT models: ${err.message}</p>`;
        }
    });
}

window.selectGptModel = (deploymentName, modelName) => {
    const idx = gptSelected.findIndex(x => x.deploymentName === deploymentName);
  
    if (idx === -1) {
      // not yet selected → add
      gptSelected.push({ deploymentName, modelName });
    } else {
      // already selected → remove
      gptSelected.splice(idx, 1);
    }
  
    updateGptHiddenInput();  // rewrite the JSON payload
    renderGPTModels();       // refresh the button states
    markFormAsModified();    // mark form as modified
  };

function updateGptHiddenInput() {
    const gptInput = document.getElementById('gpt_model_json');
    if (!gptInput) return;
    const payload = {
        selected: gptSelected,
        all: gptAll
    };
    gptInput.value = JSON.stringify(payload);
}

const fetchEmbeddingBtn = document.getElementById('fetch_embedding_models_btn');
if (fetchEmbeddingBtn) {
    fetchEmbeddingBtn.addEventListener('click', async () => {
        const listDiv = document.getElementById('embedding_models_list');
        listDiv.innerHTML = 'Fetching...';
        try {
            const resp = await fetch('/api/models/embedding');
            const data = await resp.json();
            if (resp.ok && data.models && data.models.length > 0) {
                // Clear old models and replace with new ones
                embeddingAll = data.models;
                
                // Filter out selected models that no longer exist in the newly fetched list
                embeddingSelected = embeddingSelected.filter(selected => 
                    embeddingAll.some(model => model.deploymentName === selected.deploymentName)
                );
                
                renderEmbeddingModels();
                updateEmbeddingHiddenInput();
                markFormAsModified();
            } else {
                listDiv.innerHTML = `<p class="text-danger">Error: ${data.error || 'No embedding models found'}</p>`;
            }
        } catch (err) {
            listDiv.innerHTML = `<p class="text-danger">Error fetching embedding models: ${err.message}</p>`;
        }
    });
}

window.selectEmbeddingModel = (deploymentName, modelName) => {
    embeddingSelected = [{ deploymentName, modelName }];
    renderEmbeddingModels();
    updateEmbeddingHiddenInput();
    markFormAsModified();    // mark form as modified
};

function updateEmbeddingHiddenInput() {
    const embInput = document.getElementById('embedding_model_json');
    if (!embInput) return;
    const payload = {
        selected: embeddingSelected,
        all: embeddingAll
    };
    embInput.value = JSON.stringify(payload);
}

const fetchImageBtn = document.getElementById('fetch_image_models_btn');
if (fetchImageBtn) {
    fetchImageBtn.addEventListener('click', async () => {
        const listDiv = document.getElementById('image_models_list');
        listDiv.innerHTML = 'Fetching...';
        try {
            const resp = await fetch('/api/models/image');
            const data = await resp.json();
            if (resp.ok && data.models && data.models.length > 0) {
                // Clear old models and replace with new ones
                imageAll = data.models;
                
                // Filter out selected models that no longer exist in the newly fetched list
                imageSelected = imageSelected.filter(selected => 
                    imageAll.some(model => model.deploymentName === selected.deploymentName)
                );
                
                renderImageModels();
                updateImageHiddenInput();
                markFormAsModified();
            } else {
                listDiv.innerHTML = `<p class="text-danger">Error: ${data.error || 'No image models found'}</p>`;
            }
        } catch (err) {
            listDiv.innerHTML = `<p class="text-danger">Error fetching image models: ${err.message}</p>`;
        }
    });
}

window.selectImageModel = (deploymentName, modelName) => {
    imageSelected = [{ deploymentName, modelName: modelName || null }];
    document.getElementById('image_gen_model').value = deploymentName;
    renderImageModels();
    updateImageHiddenInput();
    markFormAsModified();    // mark form as modified
};

function updateImageHiddenInput() {
    const imgInput = document.getElementById('image_gen_model_json');
    if (!imgInput) return;
    const payload = {
        selected: imageSelected,
        all: imageAll
    };
    imgInput.value = JSON.stringify(payload);
}

// --- Helper to escape HTML for input values ---
function escapeHtml(unsafe) {
    if (unsafe === null || typeof unsafe === 'undefined') {
        return '';
    }
    return unsafe
         .toString()
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

// --- *** NEW: Classification Functions *** ---

/**
 * Sets up initial state and event listeners for the classification section.
 */
function setupClassification() {
    if (!classificationTbody || !enableClassificationToggle || !addClassificationBtn || !classificationSettingsDiv || !adminForm) {
        console.warn("Classification elements not found, skipping setup.");
        return;
    }

    // Initial render
    renderClassificationCategories();

    // Initial visibility based on toggle state (already handled by Jinja style, but good practice)
    toggleClassificationSettingsVisibility();

    // Event listener for the main enable/disable toggle
    enableClassificationToggle.addEventListener('change', toggleClassificationSettingsVisibility);

    // Event listener for the "Add New" button
    addClassificationBtn.addEventListener('click', handleAddClassification);

    // Event delegation for buttons within the table body
    classificationTbody.addEventListener('click', handleClassificationAction);

    // Event delegation for color input changes
    classificationTbody.addEventListener('input', handleClassificationColorChange);

    // Update hidden input before form submission
    adminForm.addEventListener('submit', updateClassificationJsonInput);
}

/**
 * Shows or hides the classification settings area based on the toggle switch.
 */
function toggleClassificationSettingsVisibility() {
    if (classificationSettingsDiv && enableClassificationToggle) {
        classificationSettingsDiv.style.display = enableClassificationToggle.checked ? 'block' : 'none';
    }
}

/**
 * Renders the classification category rows in the table body.
 */
function renderClassificationCategories() {
    if (!classificationTbody) return;

    classificationTbody.innerHTML = ''; // Clear existing rows
    classificationCategories.forEach((category, index) => {
        const row = createClassificationRow(category, index);
        classificationTbody.appendChild(row);
    });
    updateClassificationJsonInput(); // Update hidden input after rendering
}

/**
 * Creates a single table row (<tr>) for a classification category.
 * @param {object} category - The category object {label, color}.
 * @param {number} index - The index of the category in the array.
 * @param {boolean} isNew - Optional flag if the row is newly added and editable by default.
 * @returns {HTMLTableRowElement} The created table row element.
 */
function createClassificationRow(category, index, isNew = false) {
    const tr = document.createElement('tr');
    tr.setAttribute('data-index', index);
    if (isNew) {
        tr.setAttribute('data-is-new', 'true'); // Mark as new and unsaved
    }

    const safeLabel = escapeHtml(category.label);
    const safeColor = escapeHtml(category.color);

    const isEditable = isNew; // New rows are editable by default
    const inputState = isEditable ? '' : 'readonly';
    const colorInputState = isEditable ? '' : 'disabled';
    const editBtnDisplay = isEditable ? 'none' : 'inline-block';
    const saveBtnDisplay = isEditable ? 'inline-block' : 'none';
    const deleteBtnDisplay = 'inline-block'; // Always show delete initially

    tr.innerHTML = `
        <td>
            <input type="text" class="form-control form-control-sm classification-label" value="${safeLabel}" ${inputState} data-original-value="${safeLabel}">
        </td>
        <td>
            <div class="color-swatch-container">
                 <label for="color-input-${index}" class="color-input-swatch" style="background-color: ${safeColor};" title="Click to change color"></label>
                 <input type="color" id="color-input-${index}" class="classification-color-input" value="${safeColor}" ${colorInputState} data-original-value="${safeColor}">
                 <span class="classification-color-hex small ms-1">${safeColor}</span>
            </div>
        </td>
        <td>
            <button type="button" class="btn btn-sm btn-secondary edit-btn me-1" style="display: ${editBtnDisplay};" title="Edit">
                <i class="bi bi-pencil-fill"></i>
            </button>
            <button type="button" class="btn btn-sm btn-success save-btn me-1" style="display: ${saveBtnDisplay};" title="Save">
                <i class="bi bi-check-lg"></i>
            </button>
            <button type="button" class="btn btn-sm btn-danger delete-btn" style="display: ${deleteBtnDisplay};" title="Delete">
                <i class="bi bi-trash-fill"></i>
            </button>
        </td>
    `;
    return tr;
}

/**
 * Handles clicks on the "Add New Category" button.
 */
function handleAddClassification() {
    // Use a unique temporary index for new rows until saved
    const tempIndex = `new-${Date.now()}`;
    const newCategory = { label: '', color: '#808080' }; // Default new category
    const newRow = createClassificationRow(newCategory, tempIndex, true); // Pass true for isNew
    classificationTbody.appendChild(newRow);

    // Focus the new label input
    const newLabelInput = newRow.querySelector('.classification-label');
    if (newLabelInput) {
        newLabelInput.focus();
    }
    markFormAsModified(); // Mark form as modified when adding a new category
    // Do NOT update the main `classificationCategories` array or JSON input yet.
}

/**
 * Handles clicks within the classification table body (Edit, Save, Delete).
 * Uses event delegation.
 * @param {Event} event - The click event.
 */
function handleClassificationAction(event) {
    const target = event.target.closest('button'); // Find the clicked button, even if icon is clicked
    if (!target) return; // Exit if click wasn't on a button or its child

    const row = target.closest('tr');
    if (!row) return; // Exit if button is not within a row

    const indexAttr = row.getAttribute('data-index');
    const isNew = row.getAttribute('data-is-new') === 'true';

    if (target.classList.contains('edit-btn')) {
        handleEditClassification(row);
    } else if (target.classList.contains('save-btn')) {
        handleSaveClassification(row, indexAttr, isNew);
    } else if (target.classList.contains('delete-btn')) {
        handleDeleteClassification(row, indexAttr, isNew);
    }
}

/**
 * Handles clicks on the "Edit" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to make editable.
 */
function handleEditClassification(row) {
    const labelInput = row.querySelector('.classification-label');
    const colorInput = row.querySelector('.classification-color-input');
    const editBtn = row.querySelector('.edit-btn');
    const saveBtn = row.querySelector('.save-btn');

    if (labelInput) {
        labelInput.readOnly = false;
        // Store current value as original for potential cancellation (if implemented)
        labelInput.dataset.originalValue = labelInput.value;
    }
    if (colorInput) {
        colorInput.disabled = false;
        colorInput.dataset.originalValue = colorInput.value;
        // Trigger click on the hidden color input when swatch is clicked
         const swatch = row.querySelector('.color-input-swatch');
         if (swatch) {
             // Ensure only one listener is added
             swatch.onclick = () => colorInput.click();
         }
    }
    if (editBtn) editBtn.style.display = 'none';
    if (saveBtn) saveBtn.style.display = 'inline-block';

    labelInput?.focus();
}

/**
 * Handles clicks on the "Save" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to save.
 * @param {string|number} indexAttr - The original index attribute ('new-...' or number).
 * @param {boolean} isNew - Whether this was a newly added row.
 */
function handleSaveClassification(row, indexAttr, isNew) {
    const labelInput = row.querySelector('.classification-label');
    const colorInput = row.querySelector('.classification-color-input');
    const colorHexSpan = row.querySelector('.classification-color-hex');
    const editBtn = row.querySelector('.edit-btn');
    const saveBtn = row.querySelector('.save-btn');
    const swatch = row.querySelector('.color-input-swatch');


    const newLabel = labelInput ? labelInput.value.trim() : '';
    const newColor = colorInput ? colorInput.value : '#000000';

    // Basic validation
    if (!newLabel) {
        showToast('Label cannot be empty.', 'warning');
        labelInput?.focus();
        return;
    }

    const updatedCategory = { label: newLabel, color: newColor };

    if (isNew) {
        // Add to the main array
        classificationCategories.push(updatedCategory);
        // Remove the 'new' marker and potentially update index if needed, but re-rendering handles this
        row.removeAttribute('data-is-new');
        // Re-render the whole table to get correct indices and state
        renderClassificationCategories();
        markFormAsModified(); // Mark form as modified
    } else {
        // Update existing item in the array
        const index = parseInt(indexAttr, 10);
        if (!isNaN(index) && index >= 0 && index < classificationCategories.length) {
            classificationCategories[index] = updatedCategory;

            // Update UI for the current row without full re-render
            if (labelInput) {
                labelInput.readOnly = true;
                labelInput.value = newLabel; // Ensure value is updated if different
                labelInput.dataset.originalValue = newLabel;
            }
            if (colorInput) {
                colorInput.disabled = true;
                colorInput.value = newColor; // Ensure value is updated
                colorInput.dataset.originalValue = newColor;
            }
             if (colorHexSpan) {
                 colorHexSpan.textContent = newColor;
             }
            if (swatch) {
                 swatch.style.backgroundColor = newColor;
                 swatch.onclick = null; // Remove click listener
            }
            if (editBtn) editBtn.style.display = 'inline-block';
            if (saveBtn) saveBtn.style.display = 'none';

            updateClassificationJsonInput(); // Update hidden input
            markFormAsModified(); // Mark form as modified
        } else {
            console.error("Invalid index for saving classification:", indexAttr);
            // Fallback to re-render if something went wrong
            renderClassificationCategories();
        }
    }
}


/**
 * Handles clicks on the "Delete" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to delete.
 * @param {string|number} indexAttr - The index attribute ('new-...' or number).
 * @param {boolean} isNew - Whether this was a newly added, unsaved row.
 */
function handleDeleteClassification(row, indexAttr, isNew) {
    if (isNew) {
        // Just remove the row from the DOM, it's not in the array yet
        row.remove();
    } else {
        // Ask for confirmation for existing items
        if (confirm('Are you sure you want to delete this classification category?')) {
            const index = parseInt(indexAttr, 10);
            if (!isNaN(index) && index >= 0 && index < classificationCategories.length) {
                classificationCategories.splice(index, 1); // Remove from array
                // Re-render the table to update indices and UI
                renderClassificationCategories();
                markFormAsModified(); // Mark form as modified
            } else {
                console.error("Invalid index for deleting classification:", indexAttr);
                // Fallback: remove row from DOM and update JSON
                row.remove();
                updateClassificationJsonInput();
                markFormAsModified(); // Mark form as modified
            }
        }
    }
}

/**
 * Handles changes to the color input element.
 * @param {Event} event - The input event.
 */
function handleClassificationColorChange(event) {
    const target = event.target;
    if (target.classList.contains('classification-color-input')) {
        const row = target.closest('tr');
        if (row) {
            const colorHexSpan = row.querySelector('.classification-color-hex');
            const swatch = row.querySelector('.color-input-swatch');
            const newColor = target.value;
            if (colorHexSpan) {
                colorHexSpan.textContent = newColor;
            }
             if (swatch) {
                swatch.style.backgroundColor = newColor;
            }
            markFormAsModified(); // Mark form as modified when color changes
        }
    }
}

/**
 * Updates the hidden input field with the current classification categories as JSON.
 */
function updateClassificationJsonInput() {
    if (classificationJsonInput) {
        try {
            // First make sure classificationCategories is an array
            if (!Array.isArray(classificationCategories)) {
                classificationCategories = [];
            }
            
            // Ensure we only stringify valid categories with required properties
            const validCategories = classificationCategories.filter(cat => 
                cat && 
                typeof cat === 'object' &&
                typeof cat.label === 'string' && 
                typeof cat.color === 'string'
            );
            
            const jsonString = JSON.stringify(validCategories);
            classificationJsonInput.value = jsonString;
            return jsonString;
        } catch (e) {
            console.error("Error stringifying classification categories:", e);
            classificationJsonInput.value = "[]"; // Set to empty array on error
            return "[]";
        }
    }
    return "[]";
}

function setupSupportMenuSettings() {
    if (enableSupportMenuToggle) {
        enableSupportMenuToggle.addEventListener('change', toggleSupportMenuSettingsVisibility);
    }

    if (enableSupportSendFeedbackToggle) {
        enableSupportSendFeedbackToggle.addEventListener('change', toggleSupportFeedbackRecipientVisibility);
    }

    if (enableSupportLatestFeaturesToggle) {
        enableSupportLatestFeaturesToggle.addEventListener('change', toggleSupportLatestFeaturesVisibility);
    }

    toggleSupportMenuSettingsVisibility();
}


function toggleSupportMenuSettingsVisibility() {
    if (supportMenuSettingsDiv && enableSupportMenuToggle) {
        supportMenuSettingsDiv.style.display = enableSupportMenuToggle.checked ? 'block' : 'none';
    }

    toggleSupportFeedbackRecipientVisibility();
    toggleSupportLatestFeaturesVisibility();
}


function toggleSupportFeedbackRecipientVisibility() {
    if (supportFeedbackRecipientGroup && enableSupportMenuToggle && enableSupportSendFeedbackToggle) {
        supportFeedbackRecipientGroup.style.display = (
            enableSupportMenuToggle.checked && enableSupportSendFeedbackToggle.checked
        ) ? 'block' : 'none';
    }
}


function toggleSupportLatestFeaturesVisibility() {
    if (supportLatestFeaturesSettingsDiv && enableSupportMenuToggle && enableSupportLatestFeaturesToggle) {
        supportLatestFeaturesSettingsDiv.style.display = (
            enableSupportMenuToggle.checked && enableSupportLatestFeaturesToggle.checked
        ) ? 'block' : 'none';
    }
}

// --- *** NEW: External Links Functions *** ---

/**
 * Sets up initial state and event listeners for the external links section.
 */
function setupExternalLinks() {
    if (enableExternalLinksToggle) {
        enableExternalLinksToggle.addEventListener('change', toggleExternalLinksSettingsVisibility);
        toggleExternalLinksSettingsVisibility(); // Set initial state
    }

    if (addExternalLinkBtn) {
        addExternalLinkBtn.addEventListener('click', handleAddExternalLink);
    }

    if (externalLinksTbody) {
        externalLinksTbody.addEventListener('click', handleExternalLinksAction);
    }

    // Render existing external links
    renderExternalLinks();
    updateExternalLinksJsonInput();
}

/**
 * Shows or hides the external links settings area based on the toggle switch.
 */
function toggleExternalLinksSettingsVisibility() {
    if (externalLinksSettingsDiv && enableExternalLinksToggle) {
        externalLinksSettingsDiv.style.display = enableExternalLinksToggle.checked ? 'block' : 'none';
    }
}

/**
 * Renders the external links rows in the table body.
 */
function renderExternalLinks() {
    if (!externalLinksTbody) return;

    // Clear existing content
    externalLinksTbody.innerHTML = '';

    // Render each external link
    externalLinks.forEach((link, index) => {
        const row = createExternalLinkRow(link, index);
        externalLinksTbody.appendChild(row);
    });

    // Update hidden input
    updateExternalLinksJsonInput();
}

/**
 * Creates a single table row (<tr>) for an external link.
 * @param {object} link - The link object {label, url}.
 * @param {number} index - The index of the link in the array.
 * @param {boolean} isNew - Optional flag if the row is newly added and editable by default.
 * @returns {HTMLTableRowElement} The created table row element.
 */
function createExternalLinkRow(link, index, isNew = false) {
    const row = document.createElement('tr');
    row.dataset.index = String(index);

    if (isNew) {
        populateExternalLinkEditorRow(row, link, index);
    } else {
        const labelCell = document.createElement('td');
        labelCell.className = 'external-link-label';
        labelCell.textContent = link.label;

        const urlCell = document.createElement('td');
        urlCell.className = 'external-link-url';
        const safeUrl = sanitizeHttpUrl(link.url);
        if (safeUrl) {
            const anchor = document.createElement('a');
            anchor.href = safeUrl;
            anchor.target = '_blank';
            anchor.rel = 'noopener noreferrer';
            anchor.textContent = link.url;
            urlCell.appendChild(anchor);
        } else {
            urlCell.textContent = link.url;
        }

        const actionsCell = document.createElement('td');
        actionsCell.className = 'text-nowrap';

        const moveUpButton = createIconButton('bi bi-arrow-up', `Move ${link.label} up`);
        moveUpButton.classList.add('external-link-move-up-btn');
        moveUpButton.dataset.index = String(index);
        moveUpButton.disabled = index === 0;

        const moveDownButton = createIconButton('bi bi-arrow-down', `Move ${link.label} down`);
        moveDownButton.classList.add('external-link-move-down-btn', 'ms-1');
        moveDownButton.dataset.index = String(index);
        moveDownButton.disabled = index === externalLinks.length - 1;

        const editButton = document.createElement('button');
        editButton.type = 'button';
        editButton.className = 'btn btn-sm btn-outline-primary ms-1 external-link-edit-btn';
        editButton.dataset.index = String(index);
        editButton.textContent = 'Edit';

        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'btn btn-sm btn-outline-danger ms-1 external-link-delete-btn';
        deleteButton.dataset.index = String(index);
        deleteButton.textContent = 'Delete';

        actionsCell.append(moveUpButton, moveDownButton, editButton, deleteButton);
        row.append(labelCell, urlCell, actionsCell);
    }

    return row;
}

function populateExternalLinkEditorRow(row, link, index) {
    const labelCell = document.createElement('td');
    const labelInput = document.createElement('input');
    labelInput.type = 'text';
    labelInput.className = 'form-control form-control-sm external-link-label-input';
    labelInput.value = link.label;
    labelInput.placeholder = 'Link Label';
    labelCell.appendChild(labelInput);

    const urlCell = document.createElement('td');
    const urlInput = document.createElement('input');
    urlInput.type = 'url';
    urlInput.className = 'form-control form-control-sm external-link-url-input';
    urlInput.value = link.url;
    urlInput.placeholder = 'https://example.com';
    urlCell.appendChild(urlInput);

    const actionsCell = document.createElement('td');
    const saveButton = document.createElement('button');
    saveButton.type = 'button';
    saveButton.className = 'btn btn-sm btn-success external-link-save-btn';
    saveButton.dataset.index = String(index);
    saveButton.textContent = 'Save';

    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'btn btn-sm btn-secondary ms-1 external-link-cancel-btn';
    cancelButton.dataset.index = String(index);
    cancelButton.textContent = 'Cancel';

    actionsCell.append(saveButton, cancelButton);
    row.replaceChildren(labelCell, urlCell, actionsCell);
}

/**
 * Handles clicks on the "Add New Link" button.
 */
function handleAddExternalLink() {
    // Create a new temporary link for editing
    const newLink = { label: '', url: '' };
    const newIndex = `new-${Date.now()}`; // Use timestamp to avoid conflicts
    
    // Create and add the new row in edit mode
    const newRow = createExternalLinkRow(newLink, newIndex, true);
    newRow.setAttribute('data-index', newIndex);
    
    if (externalLinksTbody) {
        externalLinksTbody.appendChild(newRow);
    }
    
    // Focus on the label input
    const labelInput = newRow.querySelector('.external-link-label-input');
    if (labelInput) {
        labelInput.focus();
    }
    
    markFormAsModified();
}

/**
 * Handles clicks within the external links table body (Edit, Save, Delete, Cancel).
 * Uses event delegation.
 * @param {Event} event - The click event.
 */
function handleExternalLinksAction(event) {
    const target = event.target.closest('button');
    if (!target) return;

    const row = target.closest('tr');
    if (!row) return;

    const indexAttr = target.getAttribute('data-index') || row.getAttribute('data-index');
    const isNew = typeof indexAttr === 'string' && indexAttr.startsWith('new-');

    if (target.classList.contains('external-link-edit-btn')) {
        handleEditExternalLink(row);
    } else if (target.classList.contains('external-link-save-btn')) {
        handleSaveExternalLink(row, indexAttr, isNew);
    } else if (target.classList.contains('external-link-cancel-btn')) {
        handleCancelExternalLink(row, indexAttr, isNew);
    } else if (target.classList.contains('external-link-delete-btn')) {
        handleDeleteExternalLink(row, indexAttr, isNew);
    } else if (target.classList.contains('external-link-move-up-btn')) {
        handleMoveExternalLink(indexAttr, -1);
    } else if (target.classList.contains('external-link-move-down-btn')) {
        handleMoveExternalLink(indexAttr, 1);
    }
}

function handleMoveExternalLink(indexAttr, direction) {
    const index = Number.parseInt(indexAttr, 10);
    const destinationIndex = index + direction;

    if (
        !Number.isInteger(index)
        || ![-1, 1].includes(direction)
        || destinationIndex < 0
        || destinationIndex >= externalLinks.length
    ) {
        return;
    }

    [externalLinks[index], externalLinks[destinationIndex]] = [
        externalLinks[destinationIndex],
        externalLinks[index],
    ];
    renderExternalLinks();
    markFormAsModified();
}

/**
 * Handles clicks on the "Edit" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to make editable.
 */
function handleEditExternalLink(row) {
    const index = Number.parseInt(row.dataset.index, 10);
    const link = externalLinks[index];
    if (!link) return;

    populateExternalLinkEditorRow(row, link, index);

    // Focus on the label input
    const labelInput = row.querySelector('.external-link-label-input');
    if (labelInput) {
        labelInput.focus();
    }

    markFormAsModified();
}

/**
 * Handles clicks on the "Save" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to save.
 * @param {string|number} indexAttr - The original index attribute ('new-...' or number).
 * @param {boolean} isNew - Whether this was a newly added row.
 */
function handleSaveExternalLink(row, indexAttr, isNew) {
    const labelInput = row.querySelector('.external-link-label-input');
    const urlInput = row.querySelector('.external-link-url-input');

    if (!labelInput || !urlInput) return;

    const label = labelInput.value.trim();
    const url = urlInput.value.trim();

    // Validation
    if (!label) {
        showToast('Please enter a label for the link.', 'warning');
        labelInput.focus();
        return;
    }

    if (!url) {
        showToast('Please enter a URL for the link.', 'warning');
        urlInput.focus();
        return;
    }

    // Basic URL validation
    try {
        new URL(url);
    } catch (e) {
        showToast('Please enter a valid URL (e.g., https://example.com).', 'warning');
        urlInput.focus();
        return;
    }

    const linkData = { label, url };

    if (isNew) {
        externalLinks.push(linkData);
    } else {
        const index = Number.parseInt(indexAttr, 10);
        if (index < 0 || index >= externalLinks.length) {
            return;
        }
        externalLinks[index] = linkData;
    }

    renderExternalLinks();
    markFormAsModified();
}

/**
 * Handles clicks on the "Cancel" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to cancel editing.
 * @param {string|number} indexAttr - The index attribute ('new-...' or number).
 * @param {boolean} isNew - Whether this was a newly added, unsaved row.
 */
function handleCancelExternalLink(row, indexAttr, isNew) {
    if (isNew) {
        // Remove the row entirely for new, unsaved links
        row.remove();
    } else {
        // Restore the original read-only row for existing links
        const index = parseInt(indexAttr);
        const link = externalLinks[index];
        if (link) {
            const restoredRow = createExternalLinkRow(link, index, false);
            row.parentNode.replaceChild(restoredRow, row);
        }
    }
}

/**
 * Handles clicks on the "Delete" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to delete.
 * @param {string|number} indexAttr - The index attribute ('new-...' or number).
 * @param {boolean} isNew - Whether this was a newly added, unsaved row.
 */
function handleDeleteExternalLink(row, indexAttr, isNew) {
    if (isNew) {
        // Just remove the row for unsaved new links
        row.remove();
        return;
    }

    const index = parseInt(indexAttr);
    const link = externalLinks[index];
    
    if (link && confirm(`Are you sure you want to delete the link "${link.label}"?`)) {
        // Remove from array
        externalLinks.splice(index, 1);
        
        // Re-render all links to update indices
        renderExternalLinks();
        
        markFormAsModified();
    }
}

/**
 * Updates the hidden input field with the current external links as JSON.
 */
function updateExternalLinksJsonInput() {
    if (externalLinksJsonInput) {
        try {
            // First make sure externalLinks is an array
            if (!Array.isArray(externalLinks)) {
                externalLinks = [];
            }
            
            // Ensure we only stringify valid links with required properties
            const validLinks = externalLinks.filter(link => 
                link && 
                typeof link === 'object' &&
                typeof link.label === 'string' && 
                typeof link.url === 'string'
            );
            
            const jsonString = JSON.stringify(validLinks);
            externalLinksJsonInput.value = jsonString;
            return jsonString;
        } catch (e) {
            console.error("Error stringifying external links:", e);
            externalLinksJsonInput.value = "[]"; // Set to empty array on error
            return "[]";
        }
    }
    return "[]";
}

function setupChunkSizeControls() {
    const overrideToggle = document.getElementById('enable_chunk_size_override');
    const fieldsContainer = document.getElementById('chunk-size-fields');
    const capWarning = document.getElementById('chunk-size-cap-warning');
    const capWarningText = document.getElementById('chunk-size-cap-warning-text');
    const capInput = document.getElementById('chunk_size_cap');
    const chunkInputs = document.querySelectorAll('.chunk-size-input');

    if (!overrideToggle || !fieldsContainer || !chunkInputs || chunkInputs.length === 0) {
        return;
    }

    const capValue = capInput ? parseInt(capInput.value, 10) : null;

    const updateCapWarning = () => {
        if (!capValue || Number.isNaN(capValue)) {
            if (capWarning) capWarning.classList.add('d-none');
            return;
        }

        const exceeding = [];
        chunkInputs.forEach(input => {
            const raw = parseInt(input.value || '0', 10);
            if (!Number.isNaN(raw) && raw > capValue) {
                exceeding.push(input.dataset.label || input.name || 'A chunk size');
            }
        });

        if (capWarning && capWarningText) {
            if (exceeding.length > 0 && overrideToggle.checked) {
                capWarningText.textContent = `${exceeding.join(', ')} will be reduced to ${capValue} because of the cap.`;
                capWarning.classList.remove('d-none');
            } else {
                capWarning.classList.add('d-none');
            }
        }
    };

    const updateVisibility = (suppressChange = false) => {
        const enabled = overrideToggle.checked;
        fieldsContainer.classList.toggle('d-none', !enabled);
        if (!enabled && capWarning) {
            capWarning.classList.add('d-none');
        } else {
            updateCapWarning();
        }
        if (!suppressChange) {
            markFormAsModified();
        }
    };

    overrideToggle.addEventListener('change', updateVisibility);
    chunkInputs.forEach(input => {
        input.addEventListener('input', () => {
            updateCapWarning();
            markFormAsModified();
        });
    });

    // Initial state
    updateVisibility(true);
}

function setupToggles() {
    // --- Enable Agents (Semantic Kernel) Toggle ---
    const agentsMainContent = document.getElementById('agents-main-content');
    const agentsDisabledMsg = document.getElementById('agents-disabled-message');
    const pluginsMainContent = document.getElementById('plugins-main-content');
    const pluginsDisabledMsg = document.getElementById('plugins-disabled-message');
    // Use backend-rendered value to show/hide content
    if (typeof settings !== 'undefined' && settings) {
        const enabled = !!settings.enable_semantic_kernel;
        if (agentsMainContent && agentsDisabledMsg) {
            agentsMainContent.style.display = enabled ? 'block' : 'none';
            agentsDisabledMsg.style.display = enabled ? 'none' : 'block';
        }
        if (pluginsMainContent && pluginsDisabledMsg) {
            pluginsMainContent.style.display = enabled ? 'block' : 'none';
            pluginsDisabledMsg.style.display = enabled ? 'none' : 'block';
        }
    }
    if (document.getElementById('core-plugin-toggles')) {
        // --- Core Plugin Toggles ---
        const timeToggle = document.getElementById('toggle-time-plugin');
        const httpToggle = document.getElementById('toggle-http-plugin');
        const waitToggle = document.getElementById('toggle-wait-plugin');
        const mathToggle = document.getElementById('toggle-math-plugin');
        const textToggle = document.getElementById('toggle-text-plugin');
        const factMemoryToggle = document.getElementById('toggle-fact-memory-plugin');
        const embeddingToggle = document.getElementById('toggle-default-embedding-model-plugin');
        const allowUserPluginsToggle = document.getElementById('toggle-allow-user-plugins');
        const allowGroupPluginsToggle = document.getElementById('toggle-allow-group-plugins');
        const toggles = [timeToggle, httpToggle, waitToggle, mathToggle, textToggle, factMemoryToggle, embeddingToggle, allowUserPluginsToggle, allowGroupPluginsToggle];
        // Feedback area
        let feedbackDiv = document.getElementById('core-plugin-toggles-feedback');
        if (!feedbackDiv) {
            feedbackDiv = document.createElement('div');
            feedbackDiv.id = 'core-plugin-toggles-feedback';
            feedbackDiv.className = 'mt-2';
            const togglesDiv = document.getElementById('core-plugin-toggles');
            if (togglesDiv) togglesDiv.appendChild(feedbackDiv);
        }

        // Helper to show feedback
        function showFeedback(msg, type = 'info') {
            feedbackDiv.innerHTML = `<div class="alert alert-${type} py-1 px-2 mb-0">${msg}</div>`;
            setTimeout(() => { feedbackDiv.innerHTML = ''; }, 3000);
        }

        // Fetch current settings and set toggle states
        async function loadCorePluginToggles() {
            try {
                const resp = await fetch('/api/admin/plugins/settings');
                if (!resp.ok) throw new Error('Failed to fetch plugin settings');
                const settings = await resp.json();
                if (timeToggle) timeToggle.checked = !!settings.enable_time_plugin;
                if (httpToggle) httpToggle.checked = !!settings.enable_http_plugin;
                if (waitToggle) waitToggle.checked = !!settings.enable_wait_plugin;
                if (mathToggle) mathToggle.checked = !!settings.enable_math_plugin;
                if (textToggle) textToggle.checked = !!settings.enable_text_plugin;
                if (embeddingToggle) embeddingToggle.checked = !!settings.enable_default_embedding_model_plugin;
                if (factMemoryToggle) factMemoryToggle.checked = !!settings.enable_fact_memory_plugin;
                const depNote = document.getElementById('tabular-processing-dependency-note');
                if (depNote) {
                    const tabularEnabled = !!settings.enable_tabular_processing_plugin;
                    depNote.textContent = tabularEnabled
                        ? 'Enabled automatically because Enhanced Citations is enabled'
                        : 'Enhanced Citations must be enabled to use tabular processing';
                    depNote.className = tabularEnabled ? 'text-muted d-block ms-4' : 'text-danger d-block ms-4';
                }
                if (allowUserPluginsToggle) allowUserPluginsToggle.checked = !!settings.allow_user_plugins;
                if (allowGroupPluginsToggle) allowGroupPluginsToggle.checked = !!settings.allow_group_plugins;
            } catch (err) {
                showFeedback('Error loading plugin toggle states: ' + err.message, 'danger');
            }
        }
        // Initial load
        loadCorePluginToggles();

        // Handler for toggle changes
        function onToggleChange() {
            // Disable toggles while saving
            toggles.forEach(t => t && (t.disabled = true));
            const payload = {
                enable_time_plugin: timeToggle ? timeToggle.checked : false,
                enable_http_plugin: httpToggle ? httpToggle.checked : false,
                enable_wait_plugin: waitToggle ? waitToggle.checked : false,
                enable_math_plugin: mathToggle ? mathToggle.checked : false,
                enable_text_plugin: textToggle ? textToggle.checked : false,
                enable_default_embedding_model_plugin: embeddingToggle ? embeddingToggle.checked : false,
                enable_fact_memory_plugin: factMemoryToggle ? factMemoryToggle.checked : false,
                allow_user_plugins: allowUserPluginsToggle ? allowUserPluginsToggle.checked : false,
                allow_group_plugins: allowGroupPluginsToggle ? allowGroupPluginsToggle.checked : false
            };
            fetch('/api/admin/plugins/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(async resp => {
                const data = await resp.json();
                if (resp.ok) {
                    showFeedback('Plugin settings updated. Restart required to take effect.', 'success');
                } else {
                    showFeedback('Error: ' + (data.error || 'Failed to update plugin settings'), 'danger');
                }
            })
            .catch(err => {
                showFeedback('Error: ' + err.message, 'danger');
            })
            .finally(() => {
                toggles.forEach(t => t && (t.disabled = false));
            });
        }
        toggles.forEach(t => t && t.addEventListener('change', onToggleChange));

        // --- Ensure toggles always reflect backend state on Plugins tab activation ---
        // Listen for Bootstrap tab activation events
        document.querySelectorAll('button[data-bs-toggle="tab"]').forEach(tabBtn => {
            tabBtn.addEventListener('shown.bs.tab', function (event) {
                const target = event.target.getAttribute('data-bs-target');
                if (target === '#plugins') {
                    loadCorePluginToggles();
                }
            });
        });
    }

    // --- User/Group Plugin Toggles ---
    const allowUserPluginsToggle = document.getElementById('allow_user_plugins');
    const allowGroupPluginsToggle = document.getElementById('allow_group_plugins');
    let pluginSettingsFeedbackDiv = document.getElementById('plugin-settings-feedback');
    if (!pluginSettingsFeedbackDiv) {
        pluginSettingsFeedbackDiv = document.createElement('div');
        pluginSettingsFeedbackDiv.id = 'plugin-settings-feedback';
        pluginSettingsFeedbackDiv.className = 'mt-2';
        // Try to append to plugins card
        const pluginsCard = document.getElementById('user-group-plugin-toggles');
        if (pluginsCard) pluginsCard.appendChild(pluginSettingsFeedbackDiv);
    }

    function showPluginSettingsFeedback(msg, type = 'info') {
        pluginSettingsFeedbackDiv.innerHTML = `<div class="alert alert-${type} py-1 px-2 mb-0">${msg}</div>`;
        setTimeout(() => { pluginSettingsFeedbackDiv.innerHTML = ''; }, 3000);
    }

    function saveUserGroupPluginSettings() {
        // Disable toggles while saving
        if (allowUserPluginsToggle) allowUserPluginsToggle.disabled = true;
        if (allowGroupPluginsToggle) allowGroupPluginsToggle.disabled = true;
        const payload = {
            allow_user_plugins: allowUserPluginsToggle ? allowUserPluginsToggle.checked : false,
            allow_group_plugins: allowGroupPluginsToggle ? allowGroupPluginsToggle.checked : false
        };
        fetch('/api/admin/plugins/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(async resp => {
            const data = await resp.json();
            if (resp.ok) {
                showPluginSettingsFeedback('Plugin settings updated.', 'success');
            } else {
                showPluginSettingsFeedback('Error: ' + (data.error || 'Failed to update plugin settings'), 'danger');
            }
        })
        .catch(err => {
            showPluginSettingsFeedback('Error: ' + err.message, 'danger');
        })
        .finally(() => {
            if (allowUserPluginsToggle) allowUserPluginsToggle.disabled = false;
            if (allowGroupPluginsToggle) allowGroupPluginsToggle.disabled = false;
        });
    }

    if (allowUserPluginsToggle) {
        allowUserPluginsToggle.addEventListener('change', saveUserGroupPluginSettings);
    }
    if (allowGroupPluginsToggle) {
        allowGroupPluginsToggle.addEventListener('change', saveUserGroupPluginSettings);
    }

    // --- Agent Settings Toggles (corrected) ---
    const allowUserAgentsToggle = document.getElementById('toggle-allow-user-agents');
    const allowUserCustomAgentEndpointsToggle = document.getElementById('toggle-allow-user-custom-endpoints');
    const allowGroupAgentsToggle = document.getElementById('toggle-allow-group-agents');
    const allowGroupCustomAgentEndpointsToggle = document.getElementById('toggle-allow-group-custom-endpoints');
    let agentSettingsFeedbackDiv = document.getElementById('agent-settings-feedback');
    if (!agentSettingsFeedbackDiv) {
        agentSettingsFeedbackDiv = document.createElement('div');
        agentSettingsFeedbackDiv.id = 'agent-settings-feedback';
        agentSettingsFeedbackDiv.className = 'mt-2';
        const agentTogglesCard = document.getElementById('agent-toggles-card');
        if (agentTogglesCard) {
            agentTogglesCard.insertAdjacentElement('afterend', agentSettingsFeedbackDiv);
        } else {
            // Fallback to previous behavior
            (document.getElementById('agents-main-content') || document.body).appendChild(agentSettingsFeedbackDiv);
        }
    }

    function showAgentSettingsFeedback(msg, type = 'info') {
        agentSettingsFeedbackDiv.innerHTML = `<div class="alert alert-${type} py-1 px-2 mb-0">${msg}</div>`;
        setTimeout(() => { agentSettingsFeedbackDiv.innerHTML = ''; }, 3000);
    }

    // Fetch agent settings and set toggles
    async function loadAgentSettings() {
        try {
            const resp = await fetch('/api/admin/agent/settings');
            if (!resp.ok) throw new Error('Failed to fetch agent settings');
            const settings = await resp.json();
            if (allowUserAgentsToggle) allowUserAgentsToggle.checked = !!settings.allow_user_agents;
            if (allowUserCustomAgentEndpointsToggle) allowUserCustomAgentEndpointsToggle.checked = !!settings.allow_user_custom_endpoints;
            if (allowGroupAgentsToggle) allowGroupAgentsToggle.checked = !!settings.allow_group_agents;
            if (allowGroupCustomAgentEndpointsToggle) allowGroupCustomAgentEndpointsToggle.checked = !!settings.allow_group_custom_endpoints;
        } catch (err) {
            showAgentSettingsFeedback('Error loading agent settings: ' + err.message, 'danger');
        }
    }
    // Initial load - only if agents are enabled
    if (typeof settings !== 'undefined' && settings && settings.enable_semantic_kernel) {
        loadAgentSettings();
    }

    // Handler for toggle changes
    function saveAgentSetting(settingName, value) {
        const toggleMap = {
            'allow_user_agents': allowUserAgentsToggle,
            'allow_user_custom_endpoints': allowUserCustomAgentEndpointsToggle,
            'allow_group_agents': allowGroupAgentsToggle,
            'allow_group_custom_endpoints': allowGroupCustomAgentEndpointsToggle
        };
        const toggle = toggleMap[settingName];
        if (toggle) toggle.disabled = true;
        fetch(`/api/admin/agents/settings/${settingName}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value })
        })
        .then(async resp => {
            const data = await resp.json();
            if (resp.ok) {
                showAgentSettingsFeedback('Agent setting updated.', 'success');
            } else {
                showAgentSettingsFeedback('Error: ' + (data.error || 'Failed to update agent setting'), 'danger');
            }
        })
        .catch(err => {
            showAgentSettingsFeedback('Error: ' + err.message, 'danger');
        })
        .finally(() => {
            if (toggle) toggle.disabled = false;
        });
    }

    if (allowUserAgentsToggle) {
        allowUserAgentsToggle.addEventListener('change', () => {
            saveAgentSetting('allow_user_agents', allowUserAgentsToggle.checked);
        });
    }
    if (allowUserCustomAgentEndpointsToggle) {
        allowUserCustomAgentEndpointsToggle.addEventListener('change', () => {
            saveAgentSetting('allow_user_custom_endpoints', allowUserCustomAgentEndpointsToggle.checked);
        });
    }
    if (allowGroupAgentsToggle) {
        allowGroupAgentsToggle.addEventListener('change', () => {
            saveAgentSetting('allow_group_agents', allowGroupAgentsToggle.checked);
        });
    }
    if (allowGroupCustomAgentEndpointsToggle) {
        allowGroupCustomAgentEndpointsToggle.addEventListener('change', () => {
            saveAgentSetting('allow_group_custom_endpoints', allowGroupCustomAgentEndpointsToggle.checked);
        });
    }

    // --- Logging Toggle ---
    const enableAppInsightsLoggingToggle = document.getElementById('enable_appinsights_global_logging');
    if (enableAppInsightsLoggingToggle) {
        enableAppInsightsLoggingToggle.addEventListener('change', () => {
            markFormAsModified();
        });
    }

    const enableGptApim = document.getElementById('enable_gpt_apim');
    if (enableGptApim) {
        enableGptApim.addEventListener('change', function () {
            document.getElementById('non_apim_gpt_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_gpt_settings').style.display = this.checked ? 'block' : 'none';
            // Toggle visibility of APIM model note and fetch step in the walkthrough
            const apimModelNote = document.getElementById('apim-model-note');
            const fetchModelsStep = document.getElementById('fetch-models-step');
            if (apimModelNote && fetchModelsStep) {
                apimModelNote.style.display = this.checked ? 'block' : 'none';
                fetchModelsStep.style.display = this.checked ? 'none' : 'block';
            }
            markFormAsModified();
        });
    }

    const enableEmbeddingApim = document.getElementById('enable_embedding_apim');
    if (enableEmbeddingApim) {
        enableEmbeddingApim.addEventListener('change', function () {
            document.getElementById('non_apim_embedding_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_embedding_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableImageGen = document.getElementById('enable_image_generation');
    if (enableImageGen) {
        enableImageGen.addEventListener('change', function () {
            document.getElementById('image_gen_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableImageGenApim = document.getElementById('enable_image_gen_apim');
    if (enableImageGenApim) {
        enableImageGenApim.addEventListener('change', function () {
            document.getElementById('non_apim_image_gen_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_image_gen_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableRedisCache = document.getElementById('enable_redis_cache');
    const redisSettingsDiv = document.getElementById('redis_cache_settings');
    if (enableRedisCache && redisSettingsDiv) {
        updateRedisCanonicalCacheVisibility(enableRedisCache.checked);
        enableRedisCache.addEventListener('change', function () {
            updateRedisCanonicalCacheVisibility(this.checked);
            markFormAsModified();
        });
    }

    const enableIdleTimeoutToggle = document.getElementById('enable_idle_timeout');
    const idleTimeoutSettingsDiv = document.getElementById('idle_timeout_settings');
    if (enableIdleTimeoutToggle && idleTimeoutSettingsDiv) {
        idleTimeoutSettingsDiv.classList.toggle('d-none', !enableIdleTimeoutToggle.checked);
        enableIdleTimeoutToggle.addEventListener('change', function () {
            idleTimeoutSettingsDiv.classList.toggle('d-none', !this.checked);
            markFormAsModified();
        });
    }

    const enableEnhancedCitation = document.getElementById('enable_enhanced_citations');
    if (enableEnhancedCitation) {
        toggleEnhancedCitation(enableEnhancedCitation.checked);
        enableEnhancedCitation.addEventListener('change', function(){
            toggleEnhancedCitation(this.checked);
            markFormAsModified();
        });
    }

    const documentIntelligenceExtractionMode = document.getElementById('document_intelligence_pdf_image_extraction_mode');
    const documentIntelligenceAutoSamplePagesGroup = document.getElementById('document_intelligence_auto_sample_pages_group');
    const documentIntelligenceAutoSamplePages = document.getElementById('document_intelligence_auto_sample_pages');
    const updateDocumentIntelligenceAutoControls = () => {
        if (!documentIntelligenceExtractionMode || !documentIntelligenceAutoSamplePagesGroup) {
            return;
        }
        documentIntelligenceAutoSamplePagesGroup.classList.toggle('d-none', documentIntelligenceExtractionMode.value !== 'auto');
    };
    if (documentIntelligenceExtractionMode) {
        updateDocumentIntelligenceAutoControls();
        documentIntelligenceExtractionMode.addEventListener('change', function () {
            updateDocumentIntelligenceAutoControls();
            markFormAsModified();
        });
    }
    if (documentIntelligenceAutoSamplePages) {
        documentIntelligenceAutoSamplePages.addEventListener('input', markFormAsModified);
    }

    const enableEnhancedExtraction = document.getElementById('enable_enhanced_extraction');
    const enhancedExtractionSettings = document.getElementById('enhanced_extraction_settings');
    const updateEnhancedExtractionControls = () => {
        if (!enableEnhancedExtraction || !enhancedExtractionSettings) {
            return;
        }
        enhancedExtractionSettings.classList.toggle('d-none', !enableEnhancedExtraction.checked);
    };
    if (enableEnhancedExtraction) {
        updateEnhancedExtractionControls();
        enableEnhancedExtraction.addEventListener('change', function () {
            updateEnhancedExtractionControls();
            // Turning Enhanced on defaults to Auto so it upgrades only when structure is detected.
            if (this.checked && documentIntelligenceExtractionMode && documentIntelligenceExtractionMode.value === 'read') {
                documentIntelligenceExtractionMode.value = 'auto';
                updateDocumentIntelligenceAutoControls();
            }
            markFormAsModified();
        });
    }

    const contentUnderstandingAuthType = document.getElementById('azure_content_understanding_authentication_type');
    const contentUnderstandingKeyContainer = document.getElementById('azure_content_understanding_key_container');
    const updateContentUnderstandingAuthControls = () => {
        if (!contentUnderstandingAuthType || !contentUnderstandingKeyContainer) {
            return;
        }
        contentUnderstandingKeyContainer.classList.toggle('d-none', contentUnderstandingAuthType.value === 'managed_identity');
    };
    if (contentUnderstandingAuthType) {
        updateContentUnderstandingAuthControls();
        contentUnderstandingAuthType.addEventListener('change', function () {
            updateContentUnderstandingAuthControls();
            markFormAsModified();
        });
    }

    const enableOfficeEmbeddedImageAnalysis = document.getElementById('enable_office_embedded_image_analysis');
    const officeEmbeddedImageOptions = document.getElementById('office_embedded_image_options');
    const updateOfficeEmbeddedImageControls = () => {
        if (!enableOfficeEmbeddedImageAnalysis || !officeEmbeddedImageOptions) {
            return;
        }
        officeEmbeddedImageOptions.classList.toggle('d-none', !enableOfficeEmbeddedImageAnalysis.checked);
    };
    if (enableOfficeEmbeddedImageAnalysis) {
        updateOfficeEmbeddedImageControls();
        enableOfficeEmbeddedImageAnalysis.addEventListener('change', function () {
            updateOfficeEmbeddedImageControls();
            markFormAsModified();
        });
    }

    const enableContentSafetyCheckbox = document.getElementById('enable_content_safety');
    if (enableContentSafetyCheckbox) {
        enableContentSafetyCheckbox.addEventListener('change', function() {
            const safetySettings = document.getElementById('content_safety_settings');
            safetySettings.style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableContentSafetyApim = document.getElementById('enable_content_safety_apim');
    if (enableContentSafetyApim) {
        enableContentSafetyApim.addEventListener('change', function() {
            document.getElementById('non_apim_content_safety_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_content_safety_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableKeyVaultCheckbox = document.getElementById('enable_key_vault_secret_storage');
    if (enableKeyVaultCheckbox) {
        const keyVaultSettings = document.getElementById('key_vault_settings');
        if (keyVaultSettings) {
            keyVaultSettings.classList.toggle('d-none', !enableKeyVaultCheckbox.checked);
        }
        enableKeyVaultCheckbox.addEventListener('change', function() {
            if (keyVaultSettings) {
                keyVaultSettings.classList.toggle('d-none', !this.checked);
            }
            markFormAsModified();
        });
    }

    const enableKeyVaultRemindersCheckbox = document.getElementById('enable_key_vault_secret_expiration_reminders');
    const keyVaultReminderSettings = document.getElementById('key_vault_expiration_reminder_settings');
    if (enableKeyVaultRemindersCheckbox && keyVaultReminderSettings) {
        keyVaultReminderSettings.classList.toggle('d-none', !enableKeyVaultRemindersCheckbox.checked);
        enableKeyVaultRemindersCheckbox.addEventListener('change', function() {
            keyVaultReminderSettings.classList.toggle('d-none', !this.checked);
            markFormAsModified();
        });
    }

    document.getElementById('key-vault-reminders-refresh')?.addEventListener('click', () => {
        void loadKeyVaultReminderInventory();
    });
    document.getElementById('key-vault-reminders-run')?.addEventListener('click', () => {
        void runKeyVaultReminderSweep();
    });
    document.getElementById('key-vault-reminders-search')?.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            event.preventDefault();
            void loadKeyVaultReminderInventory();
        }
    });
    document.getElementById('key-vault-reminders-status')?.addEventListener('change', () => {
        void loadKeyVaultReminderInventory();
    });

    const enableWebSearch = document.getElementById('enable_web_search');
    const webSearchFoundrySettings = document.getElementById('web_search_foundry_settings');
    const webSearchConsentInput = document.getElementById('web_search_consent_accepted');
    const webSearchConsentModalEl = document.getElementById('web-search-consent-modal');
    const webSearchConsentAcceptBtn = document.getElementById('web-search-consent-accept');
    const webSearchConsentDeclineBtn = document.getElementById('web-search-consent-decline');
    let webSearchConsentModal = null;
    const toggleVisibility = (element, isVisible) => {
        if (!element) {
            return;
        }
        element.classList.toggle('d-none', !isVisible);
    };
    if (enableWebSearch && webSearchFoundrySettings) {
        const setConsentAccepted = (value) => {
            if (webSearchConsentInput) {
                webSearchConsentInput.value = value ? 'true' : 'false';
            }
        };

        const showConsentModal = () => {
            if (!webSearchConsentModalEl) {
                showToast('Consent modal could not be loaded.', 'warning');
                return;
            }

            if (!webSearchConsentModal) {
                webSearchConsentModal = new bootstrap.Modal(webSearchConsentModalEl, {
                    backdrop: 'static',
                    keyboard: false
                });
            }

            webSearchConsentModal.show();
        };

        const hasConsent = () => webSearchConsentInput?.value === 'true';

        if (enableWebSearch.checked && !hasConsent()) {
            enableWebSearch.checked = false;
        }
        toggleVisibility(webSearchFoundrySettings, enableWebSearch.checked && hasConsent());

        enableWebSearch.addEventListener('change', function () {
            if (this.checked && !hasConsent()) {
                this.checked = false;
                toggleVisibility(webSearchFoundrySettings, false);
                showConsentModal();
                return;
            }

            toggleVisibility(webSearchFoundrySettings, this.checked);
            markFormAsModified();
        });

        if (webSearchConsentAcceptBtn) {
            webSearchConsentAcceptBtn.addEventListener('click', () => {
                setConsentAccepted(true);
                enableWebSearch.checked = true;
                toggleVisibility(webSearchFoundrySettings, true);
                markFormAsModified();
                if (webSearchConsentModal) {
                    webSearchConsentModal.hide();
                }
            });
        }

        if (webSearchConsentDeclineBtn) {
            webSearchConsentDeclineBtn.addEventListener('click', () => {
                setConsentAccepted(false);
                enableWebSearch.checked = false;
                toggleVisibility(webSearchFoundrySettings, false);
                markFormAsModified();
                if (webSearchConsentModal) {
                    webSearchConsentModal.hide();
                }
            });
        }
    }

    // Web Search User Notice toggle
    const enableWebSearchUserNotice = document.getElementById('enable_web_search_user_notice');
    const webSearchUserNoticeSettings = document.getElementById('web_search_user_notice_settings');
    if (enableWebSearchUserNotice && webSearchUserNoticeSettings) {
        enableWebSearchUserNotice.addEventListener('change', function() {
            toggleVisibility(webSearchUserNoticeSettings, this.checked);
            markFormAsModified();
        });
    }

    const enableAiNotice = document.getElementById('enable_ai_notice');
    const aiNoticeSettings = document.getElementById('ai_notice_settings');
    if (enableAiNotice && aiNoticeSettings) {
        toggleVisibility(aiNoticeSettings, enableAiNotice.checked);
        enableAiNotice.addEventListener('change', function() {
            toggleVisibility(aiNoticeSettings, this.checked);
            markFormAsModified();
        });
    }

    const enableUrlAccess = document.getElementById('enable_url_access');
    const urlAccessSettings = document.getElementById('url_access_settings');
    const applyUrlAccessDefaults = () => {
        const numericDefaults = {
            url_access_max_chat_urls_per_turn: '10',
            url_access_max_workflow_urls_per_run: '50',
        };
        Object.entries(numericDefaults).forEach(([fieldId, value]) => {
            const field = document.getElementById(fieldId);
            if (field && !field.value) {
                field.value = value;
            }
        });
    };

    if (enableUrlAccess && urlAccessSettings) {
        toggleVisibility(urlAccessSettings, enableUrlAccess.checked);
        enableUrlAccess.addEventListener('change', function () {
            toggleVisibility(urlAccessSettings, this.checked);
            if (this.checked) {
                applyUrlAccessDefaults();
            }
            markFormAsModified();
        });
    }

    const enableSourceReview = document.getElementById('enable_source_review');
    const sourceReviewSettings = document.getElementById('source_review_settings');
    const enableDeepSourceReview = document.getElementById('enable_deep_source_review');
    const sourceReviewDeepSettings = document.getElementById('source_review_deep_settings');

    const applyDeepResearchMaxDefaults = () => {
        const defaultMode = document.getElementById('source_review_default_mode');
        const numericDefaults = {
            source_review_max_pages_per_turn: '10',
            source_review_max_seed_pages_per_turn: '10',
            deep_research_max_user_urls_per_turn: '100',
            deep_research_max_search_queries_per_turn: '8',
            source_review_timeout_seconds: '30',
            source_review_max_redirects: '5',
            source_review_max_bytes_per_page_mb: '5',
            source_review_max_depth: '2',
            source_review_js_load_more_clicks: '12',
        };
        const enabledDefaults = [
            'enable_deep_source_review',
            'deep_research_enable_query_planning',
            'deep_research_enable_ledger_artifact',
            'source_review_enable_llm_planning',
            'source_review_allow_js_rendering',
            'source_review_respect_robots_txt',
            'source_review_audit_logging',
        ];

        if (defaultMode) {
            defaultMode.value = 'manual';
        }
        Object.entries(numericDefaults).forEach(([fieldId, value]) => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.value = value;
            }
        });
        enabledDefaults.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.checked = true;
            }
        });
        if (sourceReviewDeepSettings) {
            toggleVisibility(sourceReviewDeepSettings, true);
        }
    };

    if (enableSourceReview && sourceReviewSettings) {
        toggleVisibility(sourceReviewSettings, enableSourceReview.checked);
        enableSourceReview.addEventListener('change', function () {
            toggleVisibility(sourceReviewSettings, this.checked);
            if (this.checked) {
                applyDeepResearchMaxDefaults();
            }
            markFormAsModified();
        });
    }

    if (enableDeepSourceReview && sourceReviewDeepSettings) {
        toggleVisibility(sourceReviewDeepSettings, enableDeepSourceReview.checked);
        enableDeepSourceReview.addEventListener('change', function () {
            toggleVisibility(sourceReviewDeepSettings, this.checked);
            markFormAsModified();
        });
    }

    const foundryAuthType = document.getElementById('web_search_foundry_auth_type');
    const foundryMiType = document.getElementById('web_search_foundry_managed_identity_type');
    const foundryCloud = document.getElementById('web_search_foundry_cloud');
    const foundrySpFields = document.getElementById('web_search_foundry_service_principal_fields');
    const foundryMiTypeContainer = document.getElementById('web_search_foundry_managed_identity_type_container');
    const foundryMiClientIdContainer = document.getElementById('web_search_foundry_managed_identity_client_id_container');
    const foundryCloudContainer = document.getElementById('web_search_foundry_cloud_container');
    const foundryAuthorityContainer = document.getElementById('web_search_foundry_authority_container');

    function updateFoundryAuthVisibility() {
        const authType = foundryAuthType?.value || 'managed_identity';
        const cloudValue = foundryCloud?.value || '';

        toggleVisibility(foundrySpFields, authType === 'service_principal');
        toggleVisibility(foundryCloudContainer, authType === 'service_principal');
        toggleVisibility(
            foundryAuthorityContainer,
            authType === 'service_principal' && cloudValue === 'custom'
        );
        toggleVisibility(foundryMiTypeContainer, authType === 'managed_identity');
        if (foundryMiClientIdContainer) {
            const miType = foundryMiType?.value || 'system_assigned';
            toggleVisibility(
                foundryMiClientIdContainer,
                authType === 'managed_identity' && miType === 'user_assigned'
            );
        }
    }

    if (foundryAuthType || foundryMiType || foundryCloud) {
        updateFoundryAuthVisibility();
    }

    if (foundryMiType) {
        foundryMiType.addEventListener('change', () => {
            updateFoundryAuthVisibility();
            markFormAsModified();
        });
    }

    if (foundryCloud) {
        foundryCloud.addEventListener('change', () => {
            updateFoundryAuthVisibility();
            markFormAsModified();
        });
    }

    if (foundryAuthType) {
        foundryAuthType.addEventListener('change', () => {
            updateFoundryAuthVisibility();
            markFormAsModified();
        });
    }

    const toggleFoundrySecret = document.getElementById('toggle_web_search_foundry_client_secret');
    const foundrySecretInput = document.getElementById('web_search_foundry_client_secret');
    if (toggleFoundrySecret && foundrySecretInput) {
        toggleFoundrySecret.addEventListener('click', () => {
            foundrySecretInput.type = foundrySecretInput.type === 'password' ? 'text' : 'password';
            toggleFoundrySecret.textContent = foundrySecretInput.type === 'password' ? 'Show' : 'Hide';
        });
    }

    const enableAiSearchApim = document.getElementById('enable_ai_search_apim');
    if (enableAiSearchApim) {
        enableAiSearchApim.addEventListener('change', function () {
            document.getElementById('non_apim_ai_search_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_ai_search_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableDocumentIntelligenceApim = document.getElementById('enable_document_intelligence_apim');
    if (enableDocumentIntelligenceApim) {
        enableDocumentIntelligenceApim.addEventListener('change', function () {
            document.getElementById('non_apim_document_intelligence_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_document_intelligence_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const gptAuthType = document.getElementById('azure_openai_gpt_authentication_type');
    if (gptAuthType) {
        gptAuthType.addEventListener('change', function () {
            document.getElementById('gpt_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const embeddingAuthType = document.getElementById('azure_openai_embedding_authentication_type');
    if (embeddingAuthType) {
        embeddingAuthType.addEventListener('change', function () {
            document.getElementById('embedding_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const imgAuthType = document.getElementById('azure_openai_image_gen_authentication_type');
    if (imgAuthType) {
        imgAuthType.addEventListener('change', function () {
            document.getElementById('image_gen_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const contentSafetyAuthType = document.getElementById('content_safety_authentication_type');
    if (contentSafetyAuthType) {
        contentSafetyAuthType.addEventListener('change', function () {
            document.getElementById('content_safety_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const aiSearchAuthType = document.getElementById('azure_ai_search_authentication_type');
    if (aiSearchAuthType) {
        aiSearchAuthType.addEventListener('change', function () {
            document.getElementById('azure_ai_search_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const docIntelAuthType = document.getElementById('azure_document_intelligence_authentication_type');
    if (docIntelAuthType) {
        docIntelAuthType.addEventListener('change', function () {
            document.getElementById('azure_document_intelligence_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const speechAuthType = document.getElementById('speech_service_authentication_type');
    const speechEndpointInput = document.getElementById('speech_service_endpoint');
    const speechKeyContainer = document.getElementById('speech_service_key_container');
    const speechResourceIdContainer = document.getElementById('speech_service_resource_id_container');
    const speechResourceIdInput = document.getElementById('speech_service_resource_id');
    const speechSubscriptionInput = document.getElementById('speech_service_subscription_id');
    const speechResourceGroupInput = document.getElementById('speech_service_resource_group');
    const speechResourceNameInput = document.getElementById('speech_service_resource_name');
    const buildSpeechResourceIdButton = document.getElementById('build_speech_resource_id_btn');
    const speechResourceIdBuilderStatus = document.getElementById('speech_resource_id_builder_status');

    function inferSpeechResourceNameFromEndpoint(endpointValue) {
        const trimmedValue = (endpointValue || '').trim();
        if (!trimmedValue) {
            return '';
        }

        try {
            const parsedUrl = new URL(trimmedValue);
            const hostName = parsedUrl.hostname.toLowerCase();
            const supportedSuffixes = [
                '.cognitiveservices.azure.com',
                '.cognitiveservices.azure.us'
            ];

            for (const suffix of supportedSuffixes) {
                if (hostName.endsWith(suffix)) {
                    const resourceName = hostName.slice(0, -suffix.length);
                    if (resourceName && !resourceName.includes('.')) {
                        return resourceName;
                    }
                }
            }
        } catch (error) {
            return '';
        }

        return '';
    }

    function setSpeechResourceIdBuilderStatus(message) {
        if (speechResourceIdBuilderStatus) {
            speechResourceIdBuilderStatus.textContent = message;
        }
    }

    function buildSpeechResourceIdFromFields() {
        const subscriptionId = speechSubscriptionInput?.value?.trim() || '';
        const resourceGroup = speechResourceGroupInput?.value?.trim() || '';
        const resourceName = speechResourceNameInput?.value?.trim() || '';

        if (!subscriptionId || !resourceGroup || !resourceName) {
            return '';
        }

        return `/subscriptions/${subscriptionId}/resourceGroups/${resourceGroup}/providers/Microsoft.CognitiveServices/accounts/${resourceName}`;
    }

    function syncSpeechResourceIdBuilder(force) {
        if (!speechResourceIdInput) {
            return '';
        }

        if (speechResourceNameInput && !speechResourceNameInput.value.trim()) {
            const inferredResourceName = inferSpeechResourceNameFromEndpoint(speechEndpointInput?.value || '');
            if (inferredResourceName) {
                speechResourceNameInput.value = inferredResourceName;
            }
        }

        const builtResourceId = buildSpeechResourceIdFromFields();
        const currentValue = speechResourceIdInput.value.trim();
        const previousGeneratedValue = speechResourceIdInput.dataset.generatedValue || '';
        const wasGenerated = speechResourceIdInput.dataset.generated === 'true' || currentValue === '' || currentValue === previousGeneratedValue;

        if (builtResourceId) {
            speechResourceIdInput.dataset.generatedValue = builtResourceId;
            if (force || wasGenerated) {
                speechResourceIdInput.value = builtResourceId;
                speechResourceIdInput.dataset.generated = 'true';
            }
            setSpeechResourceIdBuilderStatus('Resource ID can be generated from the helper fields. You can still override it manually if needed.');
            return builtResourceId;
        }

        const missingParts = [];
        if (!speechSubscriptionInput?.value?.trim()) {
            missingParts.push('Subscription ID');
        }
        if (!speechResourceGroupInput?.value?.trim()) {
            missingParts.push('Resource Group');
        }
        if (!speechResourceNameInput?.value?.trim()) {
            missingParts.push('Speech Resource Name');
        }

        speechResourceIdInput.dataset.generatedValue = '';
        if (speechResourceIdInput.dataset.generated === 'true' && !currentValue) {
            speechResourceIdInput.dataset.generated = 'false';
        }

        setSpeechResourceIdBuilderStatus(`To auto-build the resource ID, provide: ${missingParts.join(', ')}.`);
        return '';
    }

    if (speechAuthType) {
        const updateSpeechAuthFields = function () {
            const usingKeyAuth = this.value === 'key';
            setSectionVisibility(speechKeyContainer, usingKeyAuth);
            setSectionVisibility(speechResourceIdContainer, !usingKeyAuth);
        };

        updateSpeechAuthFields.call(speechAuthType);
        speechAuthType.addEventListener('change', function () {
            updateSpeechAuthFields.call(this);
            markFormAsModified();
        });
    }

    if (speechResourceIdInput) {
        syncSpeechResourceIdBuilder(false);
        speechResourceIdInput.addEventListener('input', function () {
            const builtResourceId = buildSpeechResourceIdFromFields();
            this.dataset.generated = builtResourceId && this.value.trim() === builtResourceId ? 'true' : 'false';
        });
    }

    [speechEndpointInput, speechSubscriptionInput, speechResourceGroupInput, speechResourceNameInput].forEach((element) => {
        if (!element) {
            return;
        }

        element.addEventListener('input', () => {
            syncSpeechResourceIdBuilder(false);
            markFormAsModified();
        });
    });

    if (buildSpeechResourceIdButton) {
        buildSpeechResourceIdButton.addEventListener('click', () => {
            const builtResourceId = syncSpeechResourceIdBuilder(true);
            if (builtResourceId) {
                markFormAsModified();
            }
        });
    }

    const officeAuthType = document.getElementById('office_docs_authentication_type');
    const connStrGroup = document.getElementById('office_docs_storage_conn_str_group');
    const urlGroup = document.getElementById('office_docs_storage_url_group');
    const connStrInput = document.getElementById('office_docs_storage_account_url');
    const urlInput = document.getElementById('office_docs_storage_account_blob_endpoint');

    if (officeAuthType && connStrGroup && urlGroup && connStrInput && urlInput) {
        officeAuthType.addEventListener('change', function() {
            if (this.value === 'managed_identity') {
                connStrGroup.style.display = 'none';
                urlGroup.style.display = '';
            } else {
                connStrGroup.style.display = '';
                urlGroup.style.display = 'none';
            }
            markFormAsModified();
        });
    }

    // Toggle visibility of connection string
    const toggleConnStrBtn = document.getElementById('toggle_office_conn_str');
    if (toggleConnStrBtn && connStrInput) {
        toggleConnStrBtn.addEventListener('click', function() {
            connStrInput.type = connStrInput.type === 'password' ? 'text' : 'password';
            toggleConnStrBtn.textContent = connStrInput.type === 'password' ? 'Show' : 'Hide';
        });
    }

    // Toggle visibility of blob service endpoint URL
    const toggleUrlBtn = document.getElementById('toggle_office_url');
    if (toggleUrlBtn && urlInput) {
        toggleUrlBtn.addEventListener('click', function() {
            urlInput.type = urlInput.type === 'password' ? 'text' : 'password';
            toggleUrlBtn.textContent = urlInput.type === 'password' ? 'Show' : 'Hide';
        });
    }

    const videoAuthType = document.getElementById('video_files_authentication_type');
    if (videoAuthType) {
        videoAuthType.addEventListener('change', function(){
            document.getElementById('video_files_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const audioAuthType = document.getElementById('audio_files_authentication_type');
    if (audioAuthType) {
        audioAuthType.addEventListener('change', function(){
            document.getElementById('audio_files_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    // Redis auth type dropdown logic
    const redisAuthType = document.getElementById('redis_auth_type');
    if (redisAuthType) {
        updateRedisCanonicalAuthVisibility(redisAuthType.value);

        redisAuthType.addEventListener('change', function () {
            updateRedisCanonicalAuthVisibility(this.value);
            updateRedisMirrorVisibility(this.value);
            markFormAsModified();
        });
    }

    if (enableGroupWorkspacesToggle && createGroupPermissionSettingDiv) {
        const enableGroupCreationSetting = document.getElementById('enable_group_creation_setting');
        
        // Initial state
        createGroupPermissionSettingDiv.style.display = enableGroupWorkspacesToggle.checked ? 'block' : 'none';
        if (enableGroupCreationSetting) {
            enableGroupCreationSetting.style.display = enableGroupWorkspacesToggle.checked ? 'block' : 'none';
        }
        
        // Listener for changes
        enableGroupWorkspacesToggle.addEventListener('change', function() {
            createGroupPermissionSettingDiv.style.display = this.checked ? 'block' : 'none';
            if (enableGroupCreationSetting) {
                enableGroupCreationSetting.style.display = this.checked ? 'block' : 'none';
            }
            markFormAsModified();
        });
    }

    // Enable File Sharing toggle
    const enableFileSharingToggle = document.getElementById('enable_file_sharing');
    if (enableFileSharingToggle) {
        enableFileSharingToggle.addEventListener('change', function() {
            markFormAsModified();
        });
    }

    const enableFileSyncToggle = document.getElementById('enable_file_sync');
    const fileSyncSettings = document.getElementById('file_sync_settings');
    if (enableFileSyncToggle && fileSyncSettings) {
        const updateFileSyncSettingsVisibility = () => {
            fileSyncSettings.classList.toggle('d-none', !enableFileSyncToggle.checked);
        };
        updateFileSyncSettingsVisibility();
        enableFileSyncToggle.addEventListener('change', function() {
            updateFileSyncSettingsVisibility();
            markFormAsModified();
        });
    }
    setupFileSyncAdminTargets();
    
    // --- Workspace Dependency Validation ---
    setupWorkspaceDependencyValidation();
}

function setupFileSyncAdminTargets() {
    document.querySelectorAll('[data-file-sync-admin-target]').forEach(container => {
        setupFileSyncAdminTarget(container);
    });
}

function setupFileSyncAdminTarget(container) {
    const scope = container.dataset.scope || '';
    const searchEndpoint = container.dataset.searchEndpoint || '';
    const resultsKey = container.dataset.resultsKey || 'items';
    const valueField = container.dataset.valueField || 'id';
    const titleField = container.dataset.titleField || 'name';
    const subtitleField = container.dataset.subtitleField || '';
    const queryInput = container.querySelector('[data-file-sync-admin-target-query]');
    const searchButton = container.querySelector('[data-file-sync-admin-target-search]');
    const resultsContainer = container.querySelector('[data-file-sync-admin-target-results]');
    const targetInput = container.querySelector('[data-file-sync-admin-target-id]');
    const manageButton = container.querySelector('[data-file-sync-admin-target-manage]');
    const labelElement = container.querySelector('[data-file-sync-admin-target-label]');
    if (!scope || !queryInput || !searchButton || !resultsContainer || !targetInput || !manageButton || !labelElement) {
        return;
    }

    let selectedLabel = '';

    const updateManageState = () => {
        const targetId = targetInput.value.trim();
        manageButton.disabled = !targetId;
        if (!targetId) {
            labelElement.textContent = 'No target selected.';
            return;
        }
        labelElement.textContent = selectedLabel ? selectedLabel : `Target ID: ${targetId}`;
    };

    const renderResultsMessage = (message, type = 'muted') => {
        resultsContainer.replaceChildren();
        resultsContainer.appendChild(createFileSyncTextElement('div', `list-group-item text-${type}`, message));
        resultsContainer.classList.remove('d-none');
    };

    const getResultValue = (item) => String(item?.[valueField] || item?.id || item?.email || item?.name || '').trim();

    const renderResults = (items) => {
        resultsContainer.replaceChildren();
        if (!Array.isArray(items) || items.length === 0) {
            renderResultsMessage('No matching targets found. You can still paste an ID manually.');
            return;
        }
        items.forEach(item => {
            const itemValue = getResultValue(item);
            if (!itemValue) {
                return;
            }
            const titleText = String(item?.[titleField] || itemValue);
            const subtitleText = String(item?.[subtitleField] || itemValue);
            const resultButton = document.createElement('button');
            resultButton.type = 'button';
            resultButton.className = 'list-group-item list-group-item-action';
            resultButton.appendChild(createFileSyncTextElement('div', 'fw-semibold', titleText));
            resultButton.appendChild(createFileSyncTextElement('div', 'text-muted', subtitleText));
            resultButton.addEventListener('click', () => {
                targetInput.value = itemValue;
                selectedLabel = subtitleText && subtitleText !== itemValue ? `${titleText} (${subtitleText})` : titleText;
                resultsContainer.classList.add('d-none');
                updateManageState();
            });
            resultsContainer.appendChild(resultButton);
        });
        resultsContainer.classList.remove('d-none');
    };

    const searchTargets = async () => {
        const query = queryInput.value.trim();
        if (query.length < 2) {
            renderResultsMessage('Type at least two characters to search.', 'muted');
            return;
        }
        searchButton.disabled = true;
        renderResultsMessage('Searching...', 'muted');
        try {
            const response = await fetch(`${searchEndpoint}?q=${encodeURIComponent(query)}`, {
                credentials: 'same-origin',
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(payload.error || `Search failed with ${response.status}`);
            }
            renderResults(payload[resultsKey] || []);
        } catch (error) {
            renderResultsMessage(error.message, 'danger');
        } finally {
            searchButton.disabled = false;
        }
    };

    searchButton.addEventListener('click', searchTargets);
    queryInput.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            event.preventDefault();
            searchTargets();
        }
    });
    targetInput.addEventListener('input', () => {
        selectedLabel = '';
        updateManageState();
    });
    manageButton.addEventListener('click', () => {
        openFileSyncAdminManager(scope, targetInput.value.trim(), selectedLabel || targetInput.value.trim());
    });
    updateManageState();
}

function openFileSyncAdminManager(scope, targetId, targetLabel) {
    if (!scope || !targetId) {
        return;
    }
    const modalElement = document.getElementById('file-sync-admin-manager-modal');
    const titleElement = document.getElementById('file-sync-admin-manager-title');
    const contextElement = document.getElementById('file-sync-admin-manager-context');
    const container = document.getElementById('file-sync-admin-manager-container');
    if (!modalElement || !titleElement || !contextElement || !container) {
        return;
    }

    const scopeLabels = {
        personal: 'User',
        group: 'Group',
        public: 'Public Workspace',
    };
    const recursiveAllowed = document.getElementById('file_sync_allow_recursive_sources')?.checked !== false;
    const visibleSourceTypes = getSelectedFileSyncVisibleSourceTypes();
    const root = document.createElement('div');
    root.dataset.fileSyncRoot = 'true';
    root.dataset.scope = scope;
    root.dataset.apiBase = `/api/admin/file-sync/${encodeURIComponent(scope)}/${encodeURIComponent(targetId)}`;
    root.dataset.recursiveAllowed = recursiveAllowed ? 'true' : 'false';
    root.dataset.visibleSourceTypes = visibleSourceTypes.join(',');

    titleElement.textContent = `Manage ${scopeLabels[scope] || 'Workspace'} Sync Sources`;
    contextElement.textContent = targetLabel ? `${targetLabel} (${targetId})` : targetId;
    container.replaceChildren(root);

    if (typeof window.initializeFileSyncRoot === 'function') {
        window.initializeFileSyncRoot(root);
    } else {
        root.appendChild(createFileSyncTextElement('div', 'alert alert-danger', 'File Sync source manager did not load.'));
    }

    if (window.bootstrap?.Modal) {
        window.bootstrap.Modal.getOrCreateInstance(modalElement).show();
    }
}

function getSelectedFileSyncVisibleSourceTypes() {
    const checkboxes = Array.from(document.querySelectorAll('input[name="file_sync_visible_source_types"]'));
    if (checkboxes.length === 0) {
        return ['smb', 'azure_files'];
    }
    return checkboxes
        .filter((checkbox) => checkbox.checked)
        .map((checkbox) => checkbox.value)
        .filter((value, index, values) => value && values.indexOf(value) === index);
}

function createFileSyncTextElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
        element.className = className;
    }
    element.textContent = text;
    return element;
}

/**
 * Set up validation for workspace dependencies
 */
function setupWorkspaceDependencyValidation() {
    const userWorkspaceToggle = document.getElementById('enable_user_workspace');
    const groupWorkspaceToggle = document.getElementById('enable_group_workspaces');
    const publicWorkspaceToggle = document.getElementById('enable_public_workspaces');
    
    // Create or find notification area for workspace dependencies
    let notificationArea = document.getElementById('workspace-dependency-notifications');
    if (!notificationArea) {
        notificationArea = document.createElement('div');
        notificationArea.id = 'workspace-dependency-notifications';
        notificationArea.className = 'mb-3';
        
        // Insert at the beginning of the workspaces tab content
        const workspacesTab = document.getElementById('workspaces');
        if (workspacesTab) {
            const firstCard = workspacesTab.querySelector('.card');
            if (firstCard) {
                workspacesTab.insertBefore(notificationArea, firstCard);
            } else {
                workspacesTab.appendChild(notificationArea);
            }
        }
    }
    
    /**
     * Check if workspace dependencies are configured
     */
    function checkWorkspaceDependencies() {
        const userEnabled = userWorkspaceToggle?.checked || false;
        const groupEnabled = groupWorkspaceToggle?.checked || false;
        const publicEnabled = publicWorkspaceToggle?.checked || false;
        const workspacesEnabled = userEnabled || groupEnabled || publicEnabled;
        
        if (!workspacesEnabled) {
            notificationArea.innerHTML = '';
            return;
        }
        
        const missingDependencies = [];
        
        // Check Embeddings configuration
        const embeddingConfigured = checkEmbeddingConfiguration();
        if (!embeddingConfigured) {
            missingDependencies.push('Embeddings');
        }
        
        // Check Azure AI Search configuration
        const searchConfigured = checkAzureSearchConfiguration();
        if (!searchConfigured) {
            missingDependencies.push('Azure AI Search');
        }
        
        // Check Document Intelligence configuration
        const docIntelConfigured = checkDocumentIntelligenceConfiguration();
        if (!docIntelConfigured) {
            missingDependencies.push('Document Intelligence');
        }
        
        // Display notification if dependencies are missing
        if (missingDependencies.length > 0) {
            const enabledWorkspaces = [];
            if (userEnabled) enabledWorkspaces.push('Personal Workspaces');
            if (groupEnabled) enabledWorkspaces.push('Group Workspaces');
            if (publicEnabled) enabledWorkspaces.push('Public Workspaces');
            
            notificationArea.innerHTML = `
                <div class="alert alert-warning" role="alert">
                    <div class="d-flex align-items-start">
                        <div class="me-3">
                            <i class="bi bi-exclamation-triangle-fill text-warning" style="font-size: 1.2rem;"></i>
                        </div>
                        <div class="flex-grow-1">
                            <h6 class="alert-heading mb-2">Missing Required Configuration</h6>
                            <p class="mb-2">
                                You have enabled <strong>${enabledWorkspaces.join(', ')}</strong> but some required services are not configured.
                            </p>
                            <p class="mb-2">
                                <strong>Missing configurations:</strong> ${missingDependencies.join(', ')}
                            </p>
                            <hr class="my-2">
                            <p class="mb-0 small">
                                <strong>To fix this:</strong> Please configure the missing services in their respective tabs:
                                ${missingDependencies.includes('Embeddings') ? '<a href="#ai-models" class="alert-link text-decoration-none" onclick="activateTab(\'#ai-models\')">AI Models</a>' : ''}
                                ${missingDependencies.includes('Azure AI Search') ? '<a href="#search-extract" class="alert-link text-decoration-none" onclick="activateTab(\'#search-extract\')">Search and Extract</a>' : ''}
                                ${missingDependencies.includes('Document Intelligence') ? '<a href="#search-extract" class="alert-link text-decoration-none" onclick="activateTab(\'#search-extract\')">Search and Extract</a>' : ''}
                            </p>
                        </div>
                    </div>
                </div>
            `;
        } else {
            notificationArea.innerHTML = `
                <div class="alert alert-success" role="alert">
                    <div class="d-flex align-items-center">
                        <i class="bi bi-check-circle-fill text-success me-2"></i>
                        <strong>Workspace Configuration Complete</strong> - All required dependencies are configured.
                    </div>
                </div>
            `;
        }
    }
    
    /**
     * Check if embeddings are properly configured
     */
    function checkEmbeddingConfiguration() {
        const useApim = document.getElementById('enable_embedding_apim')?.checked || false;
        
        if (useApim) {
            const endpoint = document.getElementById('azure_apim_embedding_endpoint')?.value;
            const key = document.getElementById('azure_apim_embedding_subscription_key')?.value;
            return endpoint && endpoint.trim() !== '' && key && key.trim() !== '';
        } else {
            const endpoint = document.getElementById('azure_openai_embedding_endpoint')?.value;
            const authType = document.getElementById('azure_openai_embedding_authentication_type')?.value;
            
            if (!endpoint || endpoint.trim() === '') return false;
            
            if (authType === 'key') {
                const key = document.getElementById('azure_openai_embedding_key')?.value;
                return key && key.trim() !== '';
            }
            
            return true; // Managed identity doesn't need key
        }
    }
    
    /**
     * Check if Azure AI Search is properly configured
     */
    function checkAzureSearchConfiguration() {
        const useApim = document.getElementById('enable_ai_search_apim')?.checked || false;
        
        if (useApim) {
            const endpoint = document.getElementById('azure_apim_ai_search_endpoint')?.value;
            const key = document.getElementById('azure_apim_ai_search_subscription_key')?.value;
            return endpoint && endpoint.trim() !== '' && key && key.trim() !== '';
        } else {
            const endpoint = document.getElementById('azure_ai_search_endpoint')?.value;
            const authType = document.getElementById('azure_ai_search_authentication_type')?.value;
            
            if (!endpoint || endpoint.trim() === '') return false;
            
            if (authType === 'key') {
                const key = document.getElementById('azure_ai_search_key')?.value;
                return key && key.trim() !== '';
            }
            
            return true; // Managed identity doesn't need key
        }
    }
    
    /**
     * Check if Document Intelligence is properly configured
     */
    function checkDocumentIntelligenceConfiguration() {
        const useApim = document.getElementById('enable_document_intelligence_apim')?.checked || false;
        
        if (useApim) {
            const endpoint = document.getElementById('azure_apim_document_intelligence_endpoint')?.value;
            const key = document.getElementById('azure_apim_document_intelligence_subscription_key')?.value;
            return endpoint && endpoint.trim() !== '' && key && key.trim() !== '';
        } else {
            const endpoint = document.getElementById('azure_document_intelligence_endpoint')?.value;
            const authType = document.getElementById('azure_document_intelligence_authentication_type')?.value;
            
            if (!endpoint || endpoint.trim() === '') return false;
            
            if (authType === 'key') {
                const key = document.getElementById('azure_document_intelligence_key')?.value;
                return key && key.trim() !== '';
            }
            
            return true; // Managed identity doesn't need key
        }
    }
    
    /**
     * Helper function to activate a tab
     */
    function activateTab(tabId) {
        const tabTrigger = document.querySelector(`[data-bs-target="${tabId}"]`);
        if (tabTrigger) {
            const tab = new bootstrap.Tab(tabTrigger);
            tab.show();
        }
    }
    
    // Make activateTab globally available for the alert links
    window.activateTab = activateTab;
    
    // Add event listeners to workspace toggles
    if (userWorkspaceToggle) {
        userWorkspaceToggle.addEventListener('change', checkWorkspaceDependencies);
    }
    if (groupWorkspaceToggle) {
        groupWorkspaceToggle.addEventListener('change', checkWorkspaceDependencies);
    }
    if (publicWorkspaceToggle) {
        publicWorkspaceToggle.addEventListener('change', checkWorkspaceDependencies);
    }
    
    // Initial check
    checkWorkspaceDependencies();
}

function setupTestButtons() {

    const buildWebSearchPayload = () => ({
        test_type: 'web_search',
        enabled: isFieldChecked('enable_web_search'),
        consent_accepted: getFieldValue('web_search_consent_accepted') === 'true',
        query: getFieldValue('web_search_test_query'),
        foundry: {
            endpoint: getFieldValue('web_search_foundry_endpoint'),
            api_version: getFieldValue('web_search_foundry_api_version'),
            agent_id: getFieldValue('web_search_foundry_agent_id'),
            authentication_type: getFieldValue('web_search_foundry_auth_type') || 'managed_identity',
            managed_identity_type: getFieldValue('web_search_foundry_managed_identity_type') || 'system_assigned',
            managed_identity_client_id: getFieldValue('web_search_foundry_managed_identity_client_id'),
            tenant_id: getFieldValue('web_search_foundry_tenant_id'),
            client_id: getFieldValue('web_search_foundry_client_id'),
            client_secret: getFieldValue('web_search_foundry_client_secret'),
            cloud: getFieldValue('web_search_foundry_cloud'),
            authority: getFieldValue('web_search_foundry_authority')
        }
    });

    const buildUrlAccessPolicyPayload = () => ({
        test_type: 'url_access_policy',
        enabled: isFieldChecked('enable_url_access'),
        url: getFieldValue('url_access_policy_test_url'),
        source_review_allow_internal_hosts: isFieldChecked('source_review_allow_internal_hosts'),
        url_access_allowed_domains: getFieldValue('url_access_allowed_domains'),
        url_access_blocked_domains: getFieldValue('url_access_blocked_domains')
    });

    const buildEnhancedCitationsStoragePayload = () => ({
        test_type: 'enhanced_citations_storage',
        enabled: isFieldChecked('enable_enhanced_citations'),
        authentication_type: getFieldValue('office_docs_authentication_type') || 'key',
        connection_string: getFieldValue('office_docs_storage_account_url'),
        blob_endpoint: getFieldValue('office_docs_storage_account_blob_endpoint')
    });

    const runAdminTestRequest = async (payload) => {
        const response = await fetch('/api/admin/settings/test_connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        let data = {};
        try {
            data = await response.json();
        } catch (error) {
            data = { error: error.message };
        }
        return { response, data };
    };

    const renderWebSearchTestData = (container, response, data) => {
        if (response.ok && data.success !== false) {
            const isWarning = data.status === 'warning';
            renderAdminTestResult(container, {
                variant: isWarning ? 'warning' : 'success',
                title: isWarning ? 'Web Search test completed with warnings' : 'Web Search test passed',
                message: data.message,
                preview: data.response_preview,
                details: data.details,
                guidance: data.guidance
            });
            return;
        }

        renderAdminTestResult(container, {
            variant: 'danger',
            title: 'Web Search test failed',
            message: data.message || data.error || 'Error testing Web Search.',
            details: data.details,
            guidance: data.guidance
        });
    };

    const renderUrlAccessPolicyTestData = (container, response, data) => {
        if (response.ok && data.success !== false) {
            renderAdminTestResult(container, {
                variant: data.allowed ? 'success' : 'warning',
                title: data.allowed ? 'URL Access policy allowed this URL' : 'URL Access policy blocked this URL',
                message: data.message,
                details: data.details,
                guidance: data.guidance
            });
            return;
        }

        renderAdminTestResult(container, {
            variant: 'danger',
            title: 'URL Access policy test failed',
            message: data.message || data.error || 'Error testing URL Access policy.',
            details: data.details,
            guidance: data.guidance
        });
    };

    const renderEnhancedCitationsStorageTestData = (container, response, data) => {
        if (response.ok && data.success !== false) {
            const isWarning = data.status === 'warning';
            renderAdminTestResult(container, {
                variant: isWarning ? 'warning' : 'success',
                title: isWarning ? 'Enhanced Citations storage is reachable with warnings' : 'Enhanced Citations storage test passed',
                message: data.message,
                details: data.details,
                guidance: data.guidance
            });
            return;
        }

        renderAdminTestResult(container, {
            variant: 'danger',
            title: 'Enhanced Citations storage test failed',
            message: data.message || data.error || 'Error testing Enhanced Citations storage.',
            details: data.details,
            guidance: data.guidance
        });
    };

    const runWebSearchTest = async (button) => {
        const resultDiv = document.getElementById('test_web_search_result');
        renderAdminTestLoading(resultDiv, 'Running Web Search test...');
        setButtonBusy(button, true, 'Testing...');

        try {
            const { response, data } = await runAdminTestRequest(buildWebSearchPayload());
            renderWebSearchTestData(resultDiv, response, data);
        } catch (error) {
            renderAdminTestResult(resultDiv, {
                variant: 'danger',
                title: 'Web Search test failed',
                message: error.message
            });
        } finally {
            setButtonBusy(button, false);
        }
    };

    const runUrlAccessPolicyTest = async (button) => {
        const resultDiv = document.getElementById('test_url_access_policy_result');
        renderAdminTestLoading(resultDiv, 'Checking URL Access policy...');
        setButtonBusy(button, true, 'Checking...');

        try {
            const { response, data } = await runAdminTestRequest(buildUrlAccessPolicyPayload());
            renderUrlAccessPolicyTestData(resultDiv, response, data);
        } catch (error) {
            renderAdminTestResult(resultDiv, {
                variant: 'danger',
                title: 'URL Access policy test failed',
                message: error.message
            });
        } finally {
            setButtonBusy(button, false);
        }
    };

    const runEnhancedCitationsStorageTest = async (button) => {
        const resultDiv = document.getElementById('test_enhanced_citations_storage_result');
        renderAdminTestLoading(resultDiv, 'Testing Enhanced Citations storage...');
        setButtonBusy(button, true, 'Testing...');

        try {
            const { response, data } = await runAdminTestRequest(buildEnhancedCitationsStoragePayload());
            renderEnhancedCitationsStorageTestData(resultDiv, response, data);
        } catch (error) {
            renderAdminTestResult(resultDiv, {
                variant: 'danger',
                title: 'Enhanced Citations storage test failed',
                message: error.message
            });
        } finally {
            setButtonBusy(button, false);
        }
    };

    const testWebSearchBtn = document.getElementById('test_web_search_button');
    if (testWebSearchBtn) {
        testWebSearchBtn.addEventListener('click', () => runWebSearchTest(testWebSearchBtn));
    }

    const rerunWebSearchBtn = document.getElementById('rerun_web_search_test_button');
    if (rerunWebSearchBtn) {
        rerunWebSearchBtn.addEventListener('click', () => runWebSearchTest(rerunWebSearchBtn));
    }

    const testUrlAccessPolicyBtn = document.getElementById('test_url_access_policy_button');
    if (testUrlAccessPolicyBtn) {
        testUrlAccessPolicyBtn.addEventListener('click', () => runUrlAccessPolicyTest(testUrlAccessPolicyBtn));
    }

    const testEnhancedCitationsStorageBtn = document.getElementById('test_enhanced_citations_storage_button');
    if (testEnhancedCitationsStorageBtn) {
        testEnhancedCitationsStorageBtn.addEventListener('click', () => runEnhancedCitationsStorageTest(testEnhancedCitationsStorageBtn));
    }

    const testGptBtn = document.getElementById('test_gpt_button');
    if (testGptBtn) {
        testGptBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_gpt_result');
            resultDiv.innerHTML = 'Testing GPT...';

            const enableApim = document.getElementById('enable_gpt_apim').checked;
            
            const payload = {
                test_type: 'gpt',
                enable_apim: enableApim,
                selected_model: gptSelected[0] || null
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_gpt_endpoint').value,
                    api_version: document.getElementById('azure_apim_gpt_api_version').value,
                    deployment: document.getElementById('azure_apim_gpt_deployment').value,
                    subscription_key: document.getElementById('azure_apim_gpt_subscription_key').value
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('azure_openai_gpt_endpoint').value,
                    auth_type: document.getElementById('azure_openai_gpt_authentication_type').value,
                    subscription_id: document.getElementById('azure_openai_gpt_subscription_id').value,
                    resource_group: document.getElementById('azure_openai_gpt_resource_group').value,
                    key: document.getElementById('azure_openai_gpt_key').value,
                    api_version: document.getElementById('azure_openai_gpt_api_version').value
                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing GPT'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
            }
        });
    }

    const testRedisBtn = document.getElementById('test_redis_button');
    if (testRedisBtn) {
        testRedisBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_redis_result');
            setRedisTestResult(resultDiv, 'Testing Redis...', 'muted');

            const payload = {
                test_type: 'redis',
                endpoint: document.getElementById('redis_url').value,
                key: document.getElementById('redis_key').value,
                auth_type: document.getElementById('redis_auth_type').value
            };

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    setRedisTestResult(resultDiv, data.message || 'Redis connection successful.', 'success');
                    loadRedisMonitoringStatus(null, { showLoading: false });
                } else {
                    setRedisTestResult(resultDiv, data.error || 'Error testing Redis', 'danger');
                }
            } catch (err) {
                setRedisTestResult(resultDiv, `Error: ${err.message}`, 'danger');
            }
        });
    }


    const testEmbeddingBtn = document.getElementById('test_embedding_button');
    if (testEmbeddingBtn) {
        testEmbeddingBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_embedding_result');
            resultDiv.innerHTML = 'Testing Embeddings...';

            const enableApim = document.getElementById('enable_embedding_apim').checked;

            const payload = {
                test_type: 'embedding',
                enable_apim: enableApim,
                selected_model: embeddingSelected[0] || null
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_embedding_endpoint').value,
                    api_version: document.getElementById('azure_apim_embedding_api_version').value,
                    deployment: document.getElementById('azure_apim_embedding_deployment').value,
                    subscription_key: document.getElementById('azure_apim_embedding_subscription_key').value
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('azure_openai_embedding_endpoint').value,
                    auth_type: document.getElementById('azure_openai_embedding_authentication_type').value,
                    subscription_id: document.getElementById('azure_openai_embedding_subscription_id').value,
                    resource_group: document.getElementById('azure_openai_embedding_resource_group').value,
                    key: document.getElementById('azure_openai_embedding_key').value,
                    api_version: document.getElementById('azure_openai_embedding_api_version').value                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing Embeddings'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
            }
        });
    }

    const testImageBtn = document.getElementById('test_image_button');
    if (testImageBtn) {
        testImageBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_image_result');
            resultDiv.innerHTML = 'Testing Image Generation...';

            const enableApim = document.getElementById('enable_image_gen_apim').checked;

            const payload = {
                test_type: 'image',
                enable_apim: enableApim,
                selected_model: imageSelected[0] || null
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_image_gen_endpoint').value,
                    api_version: document.getElementById('azure_apim_image_gen_api_version').value,
                    deployment: document.getElementById('azure_apim_image_gen_deployment').value,
                    subscription_key: document.getElementById('azure_apim_image_gen_subscription_key').value
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('azure_openai_image_gen_endpoint').value,
                    auth_type: document.getElementById('azure_openai_image_gen_authentication_type').value,
                    subscription_id: document.getElementById('azure_openai_image_gen_subscription_id').value,
                    resource_group: document.getElementById('azure_openai_image_gen_resource_group').value,
                    key: document.getElementById('azure_openai_image_gen_key').value,
                    api_version: document.getElementById('azure_openai_image_gen_api_version').value
                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing Image Gen'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
            }
        });
    }

    const testSafetyBtn = document.getElementById('test_safety_button');
    if (testSafetyBtn) {
        testSafetyBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_safety_result');
            resultDiv.innerHTML = 'Testing Safety...';

            const contentSafetyEnabled = document.getElementById('enable_content_safety').checked;
            const enableApim = document.getElementById('enable_content_safety_apim').checked;

            const payload = {
                test_type: 'safety',
                enabled: contentSafetyEnabled,
                enable_apim: enableApim
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_content_safety_endpoint').value,
                    subscription_key: document.getElementById('azure_apim_content_safety_subscription_key').value,
                    deployment: document.getElementById('azure_apim_content_safety_deployment').value,
                    api_version: document.getElementById('azure_apim_content_safety_api_version').value
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('content_safety_endpoint').value,
                    auth_type: document.getElementById('content_safety_authentication_type').value,
                    key: document.getElementById('content_safety_key').value
                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing Safety'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
            }
        });
    }
    const testAzureSearchBtn = document.getElementById('test_azure_ai_search_button');
    if (testAzureSearchBtn) {
        testAzureSearchBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_azure_ai_search_result');
            resultDiv.innerHTML = 'Testing Azure AI Search...';

            const enableApim = document.getElementById('enable_ai_search_apim').checked;

            const payload = {
                test_type: 'azure_ai_search',
                enable_apim: enableApim
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_ai_search_endpoint').value,
                    subscription_key: document.getElementById('azure_apim_ai_search_subscription_key').value,
                    deployment: document.getElementById('azure_apim_ai_search_deployment').value,
                    api_version: document.getElementById('azure_apim_ai_search_api_version').value
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('azure_ai_search_endpoint').value,
                    auth_type: document.getElementById('azure_ai_search_authentication_type').value,
                    key: document.getElementById('azure_ai_search_key').value
                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing Azure AI Search'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
            }
        });
    }

    const testDocIntelBtn = document.getElementById('test_azure_doc_intelligence_button');
    if (testDocIntelBtn) {
        testDocIntelBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_azure_doc_intelligence_result');
            resultDiv.className = 'mt-2';
            resultDiv.textContent = 'Testing Document Intelligence...';

            const enableApim = document.getElementById('enable_document_intelligence_apim').checked;
            const extractionMode = document.getElementById('document_intelligence_pdf_image_extraction_mode')?.value || 'read';
            const autoSamplePages = document.getElementById('document_intelligence_auto_sample_pages')?.value || '3';

            const payload = {
                test_type: 'azure_doc_intelligence',
                enable_apim: enableApim,
                document_intelligence_pdf_image_extraction_mode: extractionMode,
                document_intelligence_auto_sample_pages: autoSamplePages
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_document_intelligence_endpoint')?.value || '',
                    subscription_key: document.getElementById('azure_apim_document_intelligence_subscription_key')?.value || ''
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('azure_document_intelligence_endpoint')?.value || '',
                    auth_type: document.getElementById('azure_document_intelligence_authentication_type')?.value || 'key',
                    key: document.getElementById('azure_document_intelligence_key')?.value || ''
                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.className = 'mt-2 text-success';
                    resultDiv.textContent = data.message;
                } else {
                    resultDiv.className = 'mt-2 text-danger';
                    resultDiv.textContent = data.error || 'Error testing Doc Intelligence';
                }
            } catch (err) {
                resultDiv.className = 'mt-2 text-danger';
                resultDiv.textContent = `Error: ${err.message}`;
            }
        });
    }

    const testContentUnderstandingBtn = document.getElementById('test_content_understanding_button');
    if (testContentUnderstandingBtn) {
        testContentUnderstandingBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_content_understanding_result');
            resultDiv.className = 'mt-2';
            resultDiv.textContent = 'Testing Content Understanding...';

            const payload = {
                test_type: 'content_understanding',
                endpoint: document.getElementById('azure_content_understanding_endpoint')?.value || '',
                authentication_type: document.getElementById('azure_content_understanding_authentication_type')?.value || 'key',
                key: document.getElementById('azure_content_understanding_key')?.value || '',
                api_version: document.getElementById('azure_content_understanding_api_version')?.value || '',
                analyzer_id: document.getElementById('azure_content_understanding_analyzer_id')?.value || '',
                image_analyzer_id: document.getElementById('azure_content_understanding_image_analyzer_id')?.value || ''
            };

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.className = 'mt-2 text-success';
                    resultDiv.textContent = data.message;
                } else {
                    resultDiv.className = 'mt-2 text-danger';
                    resultDiv.textContent = data.error || 'Error testing Content Understanding';
                }
            } catch (err) {
                resultDiv.className = 'mt-2 text-danger';
                resultDiv.textContent = `Error: ${err.message}`;
            }
        });
    }

    const testKeyVaultBtn = document.getElementById('test_key_vault_button');
    if (testKeyVaultBtn) {
        testKeyVaultBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_key_vault_result');
            resultDiv.innerHTML = 'Testing Key Vault...';

            const payload = {
                test_type: 'key_vault',
                vault_name: document.getElementById('key_vault_name').value,
                client_id: document.getElementById('key_vault_identity').value
            };

             try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing Key Vault'}</span>`;                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;            }
        });
    }

    const testVisionBtn = document.getElementById('test_multimodal_vision_button');
    if (testVisionBtn) {
        testVisionBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_multimodal_vision_result');
            resultDiv.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Testing Vision Analysis...';

            const visionModel = document.getElementById('multimodal_vision_model').value;
            
            if (!visionModel) {
                resultDiv.innerHTML = '<span class="text-danger">Please select a vision model first</span>';
                return;
            }

            const enableApim = document.getElementById('enable_gpt_apim').checked;
            const selectedVisionOption = getSelectedVisionModelOption();

            const payload = {
                test_type: 'multimodal_vision',
                enable_apim: enableApim,
                vision_model: visionModel
            };

            if (!enableApim && selectedVisionOption?.dataset?.endpointId && selectedVisionOption?.dataset?.modelId) {
                payload.multi_endpoint = {
                    endpoint_id: selectedVisionOption.dataset.endpointId,
                    model_id: selectedVisionOption.dataset.modelId,
                    provider: selectedVisionOption.dataset.provider || '',
                    model_name: selectedVisionOption.dataset.modelName || '',
                    deployment_name: visionModel
                };
            }

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_gpt_endpoint').value,
                    subscription_key: document.getElementById('azure_apim_gpt_subscription_key').value,
                    api_version: document.getElementById('azure_apim_gpt_api_version').value,
                    deployment: visionModel
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('azure_openai_gpt_endpoint').value,
                    auth_type: document.getElementById('azure_openai_gpt_authentication_type').value,
                    key: document.getElementById('azure_openai_gpt_key').value,
                    api_version: document.getElementById('azure_openai_gpt_api_version').value,
                    deployment: visionModel
                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<div class="alert alert-success mb-0">
                        <strong><i class="bi bi-check-circle me-1"></i>Success!</strong><br>
                        ${data.message}<br>
                        <small class="text-muted">${data.details || ''}</small>
                    </div>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger"><i class="bi bi-x-circle me-1"></i>${data.error || 'Error testing Vision Analysis'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger"><i class="bi bi-x-circle me-1"></i>Error: ${err.message}</span>`;
            }
        });
    }
}

function setupLatestFeaturesMirrors() {
    const canonicalThoughts = document.getElementById('enable_thoughts');
    const mirroredThoughts = document.getElementById('latest_features_enable_thoughts');

    if (canonicalThoughts && mirroredThoughts) {
        mirroredThoughts.checked = canonicalThoughts.checked;

        canonicalThoughts.addEventListener('change', () => {
            mirroredThoughts.checked = canonicalThoughts.checked;
        });

        mirroredThoughts.addEventListener('change', () => {
            canonicalThoughts.checked = mirroredThoughts.checked;
            markFormAsModified();
        });
    }

    const canonicalEnhancedCitations = document.getElementById('enable_enhanced_citations');
    const mirroredEnhancedCitations = document.getElementById('latest_features_enable_enhanced_citations');
    const canonicalOfficeAuthType = document.getElementById('office_docs_authentication_type');
    const mirroredOfficeAuthType = document.getElementById('latest_features_office_docs_authentication_type');
    const canonicalOfficeConnString = document.getElementById('office_docs_storage_account_url');
    const mirroredOfficeConnString = document.getElementById('latest_features_office_docs_storage_account_url');
    const canonicalOfficeBlobEndpoint = document.getElementById('office_docs_storage_account_blob_endpoint');
    const mirroredOfficeBlobEndpoint = document.getElementById('latest_features_office_docs_storage_account_blob_endpoint');
    const canonicalTabularPreviewLimit = document.getElementById('tabular_preview_max_blob_size_mb');
    const mirroredTabularPreviewLimit = document.getElementById('latest_features_tabular_preview_max_blob_size_mb');
    const canonicalRedisToggle = document.getElementById('enable_redis_cache');
    const mirroredRedisToggle = document.getElementById('latest_features_enable_redis_cache');
    const canonicalRedisUrl = document.getElementById('redis_url');
    const mirroredRedisUrl = document.getElementById('latest_features_redis_url');
    const canonicalRedisAuthType = document.getElementById('redis_auth_type');
    const mirroredRedisAuthType = document.getElementById('latest_features_redis_auth_type');
    const canonicalRedisKey = document.getElementById('redis_key');
    const mirroredRedisKey = document.getElementById('latest_features_redis_key');

    if (canonicalEnhancedCitations && mirroredEnhancedCitations) {
        mirroredEnhancedCitations.checked = canonicalEnhancedCitations.checked;
        updateLatestFeaturesEnhancedCitationMirror();

        canonicalEnhancedCitations.addEventListener('change', () => {
            mirroredEnhancedCitations.checked = canonicalEnhancedCitations.checked;
            updateLatestFeaturesEnhancedCitationMirror();
        });

        mirroredEnhancedCitations.addEventListener('change', () => {
            canonicalEnhancedCitations.checked = mirroredEnhancedCitations.checked;
            toggleEnhancedCitation(mirroredEnhancedCitations.checked);
            updateLatestFeaturesEnhancedCitationMirror();
            markFormAsModified();
        });
    }

    if (canonicalOfficeAuthType && mirroredOfficeAuthType) {
        mirroredOfficeAuthType.value = canonicalOfficeAuthType.value;
        updateOfficeStorageMirrorVisibility(canonicalOfficeAuthType.value);

        canonicalOfficeAuthType.addEventListener('change', () => {
            mirroredOfficeAuthType.value = canonicalOfficeAuthType.value;
            updateOfficeStorageMirrorVisibility(canonicalOfficeAuthType.value);
        });

        mirroredOfficeAuthType.addEventListener('change', () => {
            canonicalOfficeAuthType.value = mirroredOfficeAuthType.value;
            updateOfficeStorageCanonicalVisibility(mirroredOfficeAuthType.value);
            updateOfficeStorageMirrorVisibility(mirroredOfficeAuthType.value);
            markFormAsModified();
        });
    }

    syncMirroredField(canonicalOfficeConnString, mirroredOfficeConnString);
    syncMirroredField(canonicalOfficeBlobEndpoint, mirroredOfficeBlobEndpoint);
    syncMirroredField(canonicalTabularPreviewLimit, mirroredTabularPreviewLimit);

    if (canonicalRedisToggle && mirroredRedisToggle) {
        mirroredRedisToggle.checked = canonicalRedisToggle.checked;
        updateLatestFeaturesRedisMirror();

        canonicalRedisToggle.addEventListener('change', () => {
            mirroredRedisToggle.checked = canonicalRedisToggle.checked;
            updateLatestFeaturesRedisMirror();
        });

        mirroredRedisToggle.addEventListener('change', () => {
            canonicalRedisToggle.checked = mirroredRedisToggle.checked;
            updateRedisCanonicalCacheVisibility(mirroredRedisToggle.checked);
            updateLatestFeaturesRedisMirror();
            markFormAsModified();
        });
    }

    if (canonicalRedisAuthType && mirroredRedisAuthType) {
        mirroredRedisAuthType.value = canonicalRedisAuthType.value;
        updateRedisCanonicalAuthVisibility(canonicalRedisAuthType.value);
        updateRedisMirrorVisibility(canonicalRedisAuthType.value);

        canonicalRedisAuthType.addEventListener('change', () => {
            mirroredRedisAuthType.value = canonicalRedisAuthType.value;
            updateRedisMirrorVisibility(canonicalRedisAuthType.value);
        });

        mirroredRedisAuthType.addEventListener('change', () => {
            canonicalRedisAuthType.value = mirroredRedisAuthType.value;
            updateRedisCanonicalAuthVisibility(mirroredRedisAuthType.value);
            updateRedisMirrorVisibility(mirroredRedisAuthType.value);
            markFormAsModified();
        });
    }

    syncMirroredField(canonicalRedisUrl, mirroredRedisUrl);
    syncMirroredField(canonicalRedisKey, mirroredRedisKey);
}

function syncMirroredField(canonicalField, mirroredField, eventName = 'input') {
    if (!canonicalField || !mirroredField) {
        return;
    }

    mirroredField.value = canonicalField.value;

    canonicalField.addEventListener(eventName, () => {
        mirroredField.value = canonicalField.value;
    });

    mirroredField.addEventListener(eventName, () => {
        canonicalField.value = mirroredField.value;
        markFormAsModified();
    });
}

function updateLatestFeaturesEnhancedCitationMirror() {
    const canonicalEnhancedCitations = document.getElementById('enable_enhanced_citations');
    const mirroredEnhancedCitations = document.getElementById('latest_features_enable_enhanced_citations');
    const mirroredContainer = document.getElementById('latest_features_enhanced_citation_settings');
    const canonicalOfficeAuthType = document.getElementById('office_docs_authentication_type');
    const mirroredOfficeAuthType = document.getElementById('latest_features_office_docs_authentication_type');

    if (!canonicalEnhancedCitations || !mirroredEnhancedCitations || !mirroredContainer) {
        return;
    }

    mirroredEnhancedCitations.checked = canonicalEnhancedCitations.checked;
    mirroredContainer.classList.toggle('d-none', !canonicalEnhancedCitations.checked);

    if (canonicalOfficeAuthType && mirroredOfficeAuthType) {
        mirroredOfficeAuthType.value = canonicalOfficeAuthType.value;
        updateOfficeStorageMirrorVisibility(canonicalOfficeAuthType.value);
    }
}

function updateLatestFeaturesRedisMirror() {
    const canonicalRedisToggle = document.getElementById('enable_redis_cache');
    const mirroredRedisToggle = document.getElementById('latest_features_enable_redis_cache');
    const mirroredContainer = document.getElementById('latest_features_redis_settings');
    const canonicalRedisAuthType = document.getElementById('redis_auth_type');
    const mirroredRedisAuthType = document.getElementById('latest_features_redis_auth_type');

    if (!canonicalRedisToggle || !mirroredRedisToggle || !mirroredContainer) {
        return;
    }

    mirroredRedisToggle.checked = canonicalRedisToggle.checked;
    mirroredContainer.classList.toggle('d-none', !canonicalRedisToggle.checked);

    if (canonicalRedisAuthType && mirroredRedisAuthType) {
        mirroredRedisAuthType.value = canonicalRedisAuthType.value;
        updateRedisMirrorVisibility(canonicalRedisAuthType.value);
    }
}

function updateOfficeStorageCanonicalVisibility(authTypeValue) {
    const connStrGroup = document.getElementById('office_docs_storage_conn_str_group');
    const urlGroup = document.getElementById('office_docs_storage_url_group');

    if (connStrGroup) {
        connStrGroup.style.display = authTypeValue === 'managed_identity' ? 'none' : '';
    }

    if (urlGroup) {
        urlGroup.style.display = authTypeValue === 'managed_identity' ? '' : 'none';
    }
}

function updateOfficeStorageMirrorVisibility(authTypeValue) {
    const connStrGroup = document.getElementById('latest_features_office_docs_storage_conn_str_group');
    const urlGroup = document.getElementById('latest_features_office_docs_storage_url_group');

    if (connStrGroup) {
        connStrGroup.classList.toggle('d-none', authTypeValue === 'managed_identity');
    }

    if (urlGroup) {
        urlGroup.classList.toggle('d-none', authTypeValue !== 'managed_identity');
    }
}

function getRedisKeyLabelText(authTypeValue) {
    return authTypeValue === 'key_vault' ? 'Key Vault Secret Name' : 'Redis Access Key';
}

function updateRedisCanonicalCacheVisibility(isEnabled) {
    const redisSettingsDiv = document.getElementById('redis_cache_settings');

    if (redisSettingsDiv) {
        redisSettingsDiv.classList.toggle('d-none', !isEnabled);
    }
}

function updateRedisCanonicalAuthVisibility(authTypeValue) {
    const redisKeyContainer = document.getElementById('redis_key_container');
    const redisKeyLabel = document.getElementById('redis_key_label');
    const redisKeyVaultHint = document.getElementById('redis_key_vault_hint');

    if (redisKeyContainer) {
        redisKeyContainer.classList.toggle('d-none', !(authTypeValue === 'key' || authTypeValue === 'key_vault'));
    }

    if (redisKeyLabel) {
        redisKeyLabel.textContent = getRedisKeyLabelText(authTypeValue);
    }

    if (redisKeyVaultHint) {
        redisKeyVaultHint.classList.toggle('d-none', authTypeValue !== 'key_vault');
    }
}

function updateRedisMirrorVisibility(authTypeValue) {
    const redisKeyContainer = document.getElementById('latest_features_redis_key_container');
    const redisKeyLabel = document.getElementById('latest_features_redis_key_label');
    const redisKeyVaultHint = document.getElementById('latest_features_redis_key_vault_hint');

    if (redisKeyContainer) {
        redisKeyContainer.classList.toggle('d-none', !(authTypeValue === 'key' || authTypeValue === 'key_vault'));
    }

    if (redisKeyLabel) {
        redisKeyLabel.textContent = getRedisKeyLabelText(authTypeValue);
    }

    if (redisKeyVaultHint) {
        redisKeyVaultHint.classList.toggle('d-none', authTypeValue !== 'key_vault');
    }
}

function toggleEnhancedCitation(isEnabled) {
    const container = document.getElementById('enhanced_citation_settings');
    if (container) {
        container.style.display = isEnabled ? 'block' : 'none';
    }

    const mirroredContainer = document.getElementById('latest_features_enhanced_citation_settings');
    if (mirroredContainer) {
        mirroredContainer.classList.toggle('d-none', !isEnabled);
    }
}


function setupSendFeedbackForms() {
    const feedbackForms = document.querySelectorAll('.admin-send-feedback-form');
    feedbackForms.forEach(form => {
        const submitButton = form.querySelector('.admin-send-feedback-submit');
        if (!submitButton) {
            return;
        }

        submitButton.addEventListener('click', event => {
            event.preventDefault();
            submitAdminFeedbackForm(form);
        });
    });
}


function setupReleaseNotificationsRegistration() {
    const statusBadge = document.getElementById('release-notifications-status-badge');
    const modalElement = document.getElementById('releaseNotificationsModal');
    const readView = document.getElementById('release-notifications-read-view');
    const editView = document.getElementById('release-notifications-edit-view');
    const editButton = document.getElementById('release-notifications-edit-btn');
    const cancelEditButton = document.getElementById('release-notifications-cancel-edit-btn');
    const submitButton = document.getElementById('release-notifications-submit-btn');

    if (!statusBadge || !modalElement || !readView || !editView || !editButton || !cancelEditButton || !submitButton) {
        return;
    }

    modalElement.addEventListener('show.bs.modal', () => {
        clearStatusAlert(document.getElementById('release-notifications-status'));
        populateReleaseNotificationsModal();
        if (releaseNotificationsRegistration.registered) {
            showReleaseNotificationsReadView();
        } else {
            showReleaseNotificationsEditView();
        }
    });

    editButton.addEventListener('click', () => {
        clearStatusAlert(document.getElementById('release-notifications-status'));
        showReleaseNotificationsEditView();
    });

    cancelEditButton.addEventListener('click', () => {
        clearStatusAlert(document.getElementById('release-notifications-status'));
        populateReleaseNotificationsModal();
        if (releaseNotificationsRegistration.registered) {
            showReleaseNotificationsReadView();
        } else {
            showReleaseNotificationsEditView();
        }
    });

    submitButton.addEventListener('click', submitReleaseNotificationsRegistration);
}


function populateReleaseNotificationsModal() {
    const nameInput = document.getElementById('release_notifications_modal_name');
    const emailInput = document.getElementById('release_notifications_modal_email');
    const orgInput = document.getElementById('release_notifications_modal_org');

    if (nameInput) {
        nameInput.value = releaseNotificationsRegistration.name || '';
    }
    if (emailInput) {
        emailInput.value = releaseNotificationsRegistration.email || '';
    }
    if (orgInput) {
        orgInput.value = releaseNotificationsRegistration.organization || '';
    }

    const readName = document.getElementById('release-notifications-read-name');
    const readEmail = document.getElementById('release-notifications-read-email');
    const readOrg = document.getElementById('release-notifications-read-org');
    const readRegisteredAt = document.getElementById('release-notifications-read-registered-at');
    const readUpdatedAt = document.getElementById('release-notifications-read-updated-at');

    if (readName) {
        readName.textContent = releaseNotificationsRegistration.name || '-';
    }
    if (readEmail) {
        readEmail.textContent = releaseNotificationsRegistration.email || '-';
    }
    if (readOrg) {
        readOrg.textContent = releaseNotificationsRegistration.organization || '-';
    }
    if (readRegisteredAt) {
        readRegisteredAt.textContent = formatIsoDateTime(releaseNotificationsRegistration.registeredAt);
    }
    if (readUpdatedAt) {
        readUpdatedAt.textContent = formatIsoDateTime(releaseNotificationsRegistration.updatedAt);
    }
}


function showReleaseNotificationsReadView() {
    const readView = document.getElementById('release-notifications-read-view');
    const editView = document.getElementById('release-notifications-edit-view');
    const editButton = document.getElementById('release-notifications-edit-btn');
    const cancelEditButton = document.getElementById('release-notifications-cancel-edit-btn');
    const submitButton = document.getElementById('release-notifications-submit-btn');

    readView.classList.remove('d-none');
    editView.classList.add('d-none');
    editButton.classList.remove('d-none');
    cancelEditButton.classList.add('d-none');
    submitButton.classList.add('d-none');
}


function showReleaseNotificationsEditView() {
    const readView = document.getElementById('release-notifications-read-view');
    const editView = document.getElementById('release-notifications-edit-view');
    const editButton = document.getElementById('release-notifications-edit-btn');
    const cancelEditButton = document.getElementById('release-notifications-cancel-edit-btn');
    const submitButton = document.getElementById('release-notifications-submit-btn');

    readView.classList.add('d-none');
    editView.classList.remove('d-none');
    editButton.classList.add('d-none');
    cancelEditButton.classList.toggle('d-none', !releaseNotificationsRegistration.registered);
    submitButton.classList.remove('d-none');
}


async function submitReleaseNotificationsRegistration() {
    const statusAlert = document.getElementById('release-notifications-status');
    const submitButton = document.getElementById('release-notifications-submit-btn');
    const nameInput = document.getElementById('release_notifications_modal_name');
    const emailInput = document.getElementById('release_notifications_modal_email');
    const orgInput = document.getElementById('release_notifications_modal_org');

    const name = nameInput?.value.trim() || '';
    const email = emailInput?.value.trim() || '';
    const organization = orgInput?.value.trim() || '';

    if (!name || !email || !organization) {
        setStatusAlert(statusAlert, 'Please complete name, email, and organization before submitting registration.', 'danger');
        showToast('Please complete the registration form first.', 'warning');
        return;
    }

    if (!email.includes('@')) {
        setStatusAlert(statusAlert, 'Please enter a valid email address.', 'danger');
        showToast('Please enter a valid email address.', 'warning');
        return;
    }

    submitButton.disabled = true;

    try {
        const response = await fetch('/api/admin/settings/release_notifications_registration', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                name,
                email,
                organization
            })
        });

        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || 'Unable to prepare the registration email draft.');
        }

        releaseNotificationsRegistration = {
            ...releaseNotificationsRegistration,
            registered: true,
            name,
            email,
            organization,
            registeredAt: result.registeredAt || releaseNotificationsRegistration.registeredAt,
            updatedAt: result.updatedAt || releaseNotificationsRegistration.updatedAt
        };
        syncReleaseNotificationsHiddenInputs();
        updateReleaseNotificationsBadge();
        populateReleaseNotificationsModal();
        showReleaseNotificationsReadView();

        const mailtoUrl = buildReleaseNotificationsMailtoUrl({
            recipientEmail: result.recipientEmail || releaseNotificationsRegistration.recipientEmail,
            subjectLine: result.subjectLine || '[SimpleChat Registration] Release and Community Call Notifications',
            name,
            email,
            organization,
            registeredAt: releaseNotificationsRegistration.registeredAt,
            updatedAt: releaseNotificationsRegistration.updatedAt
        });

        setStatusAlert(statusAlert, 'Registration saved. Your local email client should open next.', 'success');
        showToast('Release notifications registration prepared.', 'success');
        window.location.href = mailtoUrl;
    } catch (error) {
        setStatusAlert(statusAlert, error.message || 'Unable to prepare the registration email draft.', 'danger');
        showToast(error.message || 'Unable to prepare the registration email draft.', 'danger');
    } finally {
        submitButton.disabled = false;
    }
}


function buildReleaseNotificationsMailtoUrl({
    recipientEmail,
    subjectLine,
    name,
    email,
    organization,
    registeredAt,
    updatedAt
}) {
    const bodyLines = [
        'Registration submission to receive the latest release updates and community call notifications.',
        '',
        `Name: ${name}`,
        `Email: ${email}`,
        `Organization: ${organization}`,
        `App Version: ${releaseNotificationsRegistration.appVersion || 'Unknown'}`,
        `Registered At: ${registeredAt || 'Pending'}`,
    ];

    return `mailto:${recipientEmail}?subject=${encodeURIComponent(subjectLine)}&body=${encodeURIComponent(bodyLines.join('\n'))}`;
}


function syncReleaseNotificationsHiddenInputs() {
    const registeredInput = document.getElementById('release_notifications_registered');
    const nameInput = document.getElementById('release_notifications_name');
    const emailInput = document.getElementById('release_notifications_email');
    const orgInput = document.getElementById('release_notifications_org');
    const registeredAtInput = document.getElementById('release_notifications_registered_at');
    const updatedAtInput = document.getElementById('release_notifications_updated_at');

    if (registeredInput) {
        registeredInput.value = releaseNotificationsRegistration.registered ? 'true' : 'false';
    }
    if (nameInput) {
        nameInput.value = releaseNotificationsRegistration.name || '';
    }
    if (emailInput) {
        emailInput.value = releaseNotificationsRegistration.email || '';
    }
    if (orgInput) {
        orgInput.value = releaseNotificationsRegistration.organization || '';
    }
    if (registeredAtInput) {
        registeredAtInput.value = releaseNotificationsRegistration.registeredAt || '';
    }
    if (updatedAtInput) {
        updatedAtInput.value = releaseNotificationsRegistration.updatedAt || '';
    }
}


function updateReleaseNotificationsBadge() {
    const statusBadge = document.getElementById('release-notifications-status-badge');
    if (!statusBadge) {
        return;
    }

    statusBadge.dataset.registered = releaseNotificationsRegistration.registered ? 'true' : 'false';
    statusBadge.textContent = releaseNotificationsRegistration.registered ? 'Registered' : 'Unregistered';
    statusBadge.classList.toggle('bg-success', releaseNotificationsRegistration.registered);
    statusBadge.classList.toggle('bg-secondary', !releaseNotificationsRegistration.registered);
}


function formatIsoDateTime(value) {
    if (!value) {
        return '-';
    }

    const parsedDate = new Date(value);
    if (Number.isNaN(parsedDate.getTime())) {
        return value;
    }

    return parsedDate.toLocaleString();
}


async function submitAdminFeedbackForm(form) {
    const feedbackType = form.dataset.feedbackType;
    const feedbackLabel = form.dataset.feedbackLabel || 'Feedback';
    const inputs = form.querySelectorAll('input[type="text"], input[type="email"], textarea');
    const nameInput = inputs[0];
    const emailInput = inputs[1];
    const organizationInput = inputs[2];
    const detailsInput = inputs[3];
    const statusAlert = form.querySelector('.admin-send-feedback-status');
    const submitButton = form.querySelector('.admin-send-feedback-submit');

    const reporterName = nameInput?.value.trim() || '';
    const reporterEmail = emailInput?.value.trim() || '';
    const organization = organizationInput?.value.trim() || '';
    const details = detailsInput?.value.trim() || '';

    if (!reporterName || !reporterEmail || !organization || !details) {
        setStatusAlert(statusAlert, 'Please complete name, email, organization, and details before opening the email draft.', 'danger');
        showToast('Please complete the Send Feedback form first.', 'warning');
        return;
    }

    if (!reporterEmail.includes('@')) {
        setStatusAlert(statusAlert, 'Please enter a valid email address.', 'danger');
        showToast('Please enter a valid email address.', 'warning');
        return;
    }

    submitButton.disabled = true;

    try {
        const response = await fetch('/api/admin/settings/send_feedback_email', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                feedbackType,
                reporterName,
                reporterEmail,
                organization,
                details
            })
        });

        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || 'Unable to prepare the feedback email draft.');
        }

        const mailtoUrl = buildAdminFeedbackMailtoUrl({
            recipientEmail: result.recipientEmail,
            subjectLine: result.subjectLine,
            feedbackLabel,
            reporterName,
            reporterEmail,
            organization,
            details
        });

        setStatusAlert(
            statusAlert,
            'Email draft prepared. Your local email client should open next.',
            'success'
        );
        showToast(`${feedbackLabel} email draft prepared.`, 'success');
        window.location.href = mailtoUrl;
    } catch (error) {
        setStatusAlert(statusAlert, error.message || 'Unable to prepare the feedback email draft.', 'danger');
        showToast(error.message || 'Unable to prepare the feedback email draft.', 'danger');
    } finally {
        submitButton.disabled = false;
    }
}


function buildAdminFeedbackMailtoUrl({
    recipientEmail,
    subjectLine,
    feedbackLabel,
    reporterName,
    reporterEmail,
    organization,
    details
}) {
    const sendFeedbackPane = document.getElementById('send-feedback');
    const appVersion = sendFeedbackPane?.dataset.appVersion || '';
    const bodyLines = [
        `Feedback Type: ${feedbackLabel}`,
        `Name: ${reporterName}`,
        `Email: ${reporterEmail}`,
        `Organization: ${organization}`,
        `App Version: ${appVersion || 'Unknown'}`,
        ''
    ];

    bodyLines.push('Details:');
    bodyLines.push(details);

    return `mailto:${recipientEmail}?subject=${encodeURIComponent(subjectLine)}&body=${encodeURIComponent(bodyLines.join('\n'))}`;
}


function setStatusAlert(statusAlert, message, variant) {
    if (!statusAlert) {
        return;
    }

    statusAlert.className = `alert alert-${variant} admin-send-feedback-status`;
    statusAlert.textContent = message;
    statusAlert.classList.remove('d-none');
}


function updateSendFeedbackStatus(statusAlert, message, variant) {
    setStatusAlert(statusAlert, message, variant);
}


function clearStatusAlert(statusAlert) {
    if (!statusAlert) {
        return;
    }

    statusAlert.className = 'alert d-none admin-send-feedback-status';
    statusAlert.textContent = '';
}


function switchTab(event, tabButtonId) {
    event.preventDefault();
    const triggerEl = document.getElementById(tabButtonId);
    if (triggerEl) {
        const tabObj = new bootstrap.Tab(triggerEl);
        tabObj.show();
        return;
    }

    const inferredTabId = tabButtonId.replace(/-tab$/, '');
    if (typeof window.showAdminTab === 'function') {
        window.showAdminTab(inferredTabId);

        const navLink = document.querySelector(`.admin-nav-tab[data-tab="${inferredTabId}"]`);
        if (navLink) {
            document.querySelectorAll('.admin-nav-tab, .admin-nav-section').forEach(link => {
                link.classList.remove('active');
            });
            navLink.classList.add('active');
        }
    }
}

window.switchTab = switchTab;

function togglePassword(btnId, inputId) {
    const btn = document.getElementById(btnId);
    const inp = document.getElementById(inputId);
    if (btn && inp) {
        btn.addEventListener('click', function () {
            if (inp.type === 'password') {
                inp.type = 'text';
                this.textContent = 'Hide';
            } else {
                inp.type = 'password';
                this.textContent = 'Show';
            }
        });
    }
}

function setSectionVisibility(element, visible) {
    if (!element) {
        return;
    }

    element.classList.toggle('d-none', !visible);
}

// --- Video Indexer Settings toggle ---
const videoSupportToggle = document.getElementById('enable_video_file_support');
const videoIndexerDiv = document.getElementById('video_indexer_settings');
const videoIndexerCloudSelect = document.getElementById('video_indexer_cloud');
const videoIndexerEndpointInput = document.getElementById('video_indexer_endpoint');
const videoIndexerEndpointDisplay = document.getElementById('video_indexer_endpoint_display');
const videoIndexerCustomEndpointGroup = document.getElementById('video_indexer_custom_endpoint_group');
const videoIndexerCustomEndpointInput = document.getElementById('video_indexer_custom_endpoint');
const videoIndexerCloudMismatchAlert = document.getElementById('video_indexer_cloud_mismatch_alert');

function updateVideoIndexerEndpointSelection() {
    if (!videoIndexerCloudSelect || !videoIndexerEndpointInput) {
        return;
    }

    const selectedCloud = videoIndexerCloudSelect.value;
    const publicEndpoint = videoIndexerCloudSelect.dataset.publicEndpoint || 'https://api.videoindexer.ai';
    const governmentEndpoint = videoIndexerCloudSelect.dataset.governmentEndpoint || 'https://api.videoindexer.ai.azure.us';
    const runtimeCloud = videoIndexerCloudSelect.dataset.runtimeCloud || 'public';

    let endpointValue = publicEndpoint;
    if (selectedCloud === 'usgovernment') {
        endpointValue = governmentEndpoint;
    } else if (selectedCloud === 'custom') {
        endpointValue = videoIndexerCustomEndpointInput?.value?.trim() || '';
    }

    videoIndexerEndpointInput.value = endpointValue;

    if (videoIndexerEndpointDisplay) {
        videoIndexerEndpointDisplay.value = endpointValue;
    }

    setSectionVisibility(videoIndexerCustomEndpointGroup, selectedCloud === 'custom');
    setSectionVisibility(videoIndexerCloudMismatchAlert, selectedCloud !== runtimeCloud);

    if (typeof updateVideoIndexerModalInfo === 'function') {
        updateVideoIndexerModalInfo();
    }
}

if (videoSupportToggle && videoIndexerDiv) {
    setSectionVisibility(videoIndexerDiv, videoSupportToggle.checked);
    videoSupportToggle.addEventListener('change', () => {
        setSectionVisibility(videoIndexerDiv, videoSupportToggle.checked);
        markFormAsModified();
    });
}

if (videoIndexerCloudSelect) {
    updateVideoIndexerEndpointSelection();
    videoIndexerCloudSelect.addEventListener('change', () => {
        updateVideoIndexerEndpointSelection();
        markFormAsModified();
    });
}

if (videoIndexerCustomEndpointInput) {
    videoIndexerCustomEndpointInput.addEventListener('input', () => {
        updateVideoIndexerEndpointSelection();
        markFormAsModified();
    });
}

// --- Speech Service Settings toggle ---
const audioSupportToggle = document.getElementById('enable_audio_file_support');
const speechToTextToggle = document.getElementById('enable_speech_to_text_input');
const textToSpeechToggle = document.getElementById('enable_text_to_speech');
const audioServiceDiv = document.getElementById('audio_service_settings');

function areAnySpeechFeaturesEnabled() {
    return [audioSupportToggle, speechToTextToggle, textToSpeechToggle].some((toggle) => Boolean(toggle?.checked));
}

function updateSpeechServiceSettingsVisibility() {
    setSectionVisibility(audioServiceDiv, areAnySpeechFeaturesEnabled());
}

if (audioServiceDiv) {
    updateSpeechServiceSettingsVisibility();
    [audioSupportToggle, speechToTextToggle, textToSpeechToggle].forEach((toggle) => {
        if (!toggle) {
            return;
        }

        toggle.addEventListener('change', () => {
            updateSpeechServiceSettingsVisibility();
            markFormAsModified();
        });
    });
}

// Metadata Extraction UI
const extractToggle = document.getElementById('enable_extract_meta_data');
const extractModelDiv = document.getElementById('metadata_extraction_model_settings');

if (extractToggle) {
    // show/hide the model dropdown
    extractModelDiv.style.display = extractToggle.checked ? 'block' : 'none';
    extractToggle.addEventListener('change', () => {
        extractModelDiv.style.display = extractToggle.checked ? 'block' : 'none';
        markFormAsModified();
    });
}

// Multi-Modal Vision UI
const visionToggle = document.getElementById('enable_multimodal_vision');
const visionModelDiv = document.getElementById('multimodal_vision_model_settings');
const visionSelect = document.getElementById('multimodal_vision_model');

function isVisionCapableModelName(...modelNames) {
    return modelNames.some(modelName => {
        const normalizedName = String(modelName || '')
            .trim()
            .toLowerCase()
            .replace(/[\s_.]+/g, '-');

        return (
            normalizedName.includes('vision') ||
            normalizedName.includes('gpt-4o') ||
            normalizedName.includes('gpt-4-1') ||
            normalizedName.includes('gpt-4-5') ||
            /(?:^|-)gpt-(?:[5-9]|\d{2,})(?:-|$)/.test(normalizedName) ||
            /(?:^|-)o\d+(?:-|$)/.test(normalizedName)
        );
    });
}

function getSelectedVisionModelOption() {
    if (!visionSelect) {
        return null;
    }

    return visionSelect.options[visionSelect.selectedIndex] || null;
}

function populateVisionModels() {
    if (!visionSelect) return;

    const prev = visionSelect.getAttribute('data-prev') || '';
    visionSelect.innerHTML = '<option value="">Select a vision-capable model...</option>';

    // Prefer multi-endpoint model list when available
    const multiEnabled = window.enableMultiModelEndpoints === true;
    const endpoints = Array.isArray(window.modelEndpoints) ? window.modelEndpoints : [];

    if (multiEnabled && endpoints.length > 0) {
        endpoints
            .filter(ep => ep && ep.enabled)
            .forEach(ep => {
                (ep.models || [])
                    .filter(m => m && m.enabled && isVisionCapableModelName(
                        m.modelName,
                        m.displayName,
                        m.deploymentName,
                        m.deployment,
                        m.name
                    ))
                    .forEach(m => {
                        const value = m.deploymentName;
                        const label = m.modelName
                            ? `${m.displayName || m.deploymentName} (${m.modelName})`
                            : (m.displayName || m.deploymentName);
                        const opt = new Option(label, value);
                        opt.dataset.endpointId = ep.id || '';
                        opt.dataset.modelId = m.id || '';
                        opt.dataset.provider = ep.provider || '';
                        opt.dataset.modelName = m.modelName || '';
                        visionSelect.add(opt);
                    });
            });
    } else if (document.getElementById('enable_gpt_apim') && document.getElementById('enable_gpt_apim').checked) {
        // Legacy APIM-based GPT configuration
        const text = (document.getElementById('azure_apim_gpt_deployment')?.value || '');
        text.split(',')
            .map(s => s.trim())
            .filter(s => s && isVisionCapableModelName(s))
            .forEach(d => {
                const opt = new Option(d, d);
                visionSelect.add(opt);
            });
    } else {
        // Legacy single-endpoint GPT configuration using window.gptSelected
        (window.gptSelected || [])
            .filter(m => isVisionCapableModelName(m.modelName))
            .forEach(m => {
                const label = `${m.deploymentName} (${m.modelName})`;
                const opt = new Option(label, m.deploymentName);
                visionSelect.add(opt);
            });
    }

    if (prev) {
        visionSelect.value = prev;
    }
}

if (visionToggle && visionModelDiv) {
    // show/hide the model dropdown
    visionModelDiv.style.display = visionToggle.checked ? 'block' : 'none';
    visionToggle.addEventListener('change', () => {
        visionModelDiv.style.display = visionToggle.checked ? 'block' : 'none';
        markFormAsModified();
    });
}

// Listen for vision model selection changes
if (visionSelect) {
    visionSelect.addEventListener('change', () => {
        // Update data-prev to remember the selection
        visionSelect.setAttribute('data-prev', visionSelect.value);
        markFormAsModified();
    });
}

// when APIM-toggle flips, repopulate
const apimToggle = document.getElementById('enable_gpt_apim');
if (apimToggle) {
    apimToggle.addEventListener('change', () => {
        populateVisionModels();
    });
}

// on load, stash previous & populate
document.addEventListener('DOMContentLoaded', () => {
    if (visionSelect) {
        visionSelect.setAttribute('data-prev', visionSelect.value);
        populateVisionModels();
    }
});


document.addEventListener('DOMContentLoaded', () => {
        ['user','group','public'].forEach(type => {
            const warnDiv = document.getElementById(`index-warning-${type}`);
            const missingSpan = document.getElementById(`missing-fields-${type}`);
            const fixBtn = document.getElementById(`fix-${type}-index-btn`);
  
            // 1) check for missing fields
            fetch('/api/admin/settings/check_index_fields', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify({ indexType: type })
            })
            .then(r => {
                if (!r.ok) {
                    return r.json().then(errorData => {
                        throw new Error(errorData.error || `HTTP ${r.status}: ${r.statusText}`);
                    });
                }
                return r.json();
            })
            .then(response => {
                if (response.autoFixed) {
                    // Fields were automatically fixed
                    console.log(`✅ Auto-fixed ${type} index: added ${response.fieldsAdded.length} field(s):`, response.fieldsAdded.join(', '));
                    if (warnDiv) {
                        warnDiv.className = 'alert alert-success';
                        missingSpan.textContent = `Automatically added ${response.fieldsAdded.length} field(s): ${response.fieldsAdded.join(', ')}`;
                        warnDiv.style.display = 'block';
                        if (fixBtn) fixBtn.style.display = 'none';

                        // Hide success message after 5 seconds
                        setTimeout(() => {
                            warnDiv.style.display = 'none';
                        }, 5000);
                    }
                } else if (response.autoFixFailed) {
                    // Auto-fix failed, show manual button
                    console.warn(`Auto-fix failed for ${type} index:`, response.error);
                    missingSpan.textContent = response.missingFields.join(', ') + ' (Auto-fix failed - please fix manually)';
                    warnDiv.className = 'alert alert-warning';
                    warnDiv.style.display = 'block';
                    if (fixBtn) {
                        fixBtn.textContent = `Fix ${type} Index Fields`;
                        fixBtn.style.display = 'inline-block';
                    }
                } else if (response.missingFields && response.missingFields.length > 0) {
                    // Missing fields but auto-fix was disabled
                    missingSpan.textContent = response.missingFields.join(', ');
                    warnDiv.className = 'alert alert-warning';
                    warnDiv.style.display = 'block';
                    if (fixBtn) {
                        fixBtn.textContent = `Fix ${type} Index Fields`;
                        fixBtn.style.display = 'inline-block';
                    }
                } else if (response.indexExists) {
                    // Index exists and is complete
                    if (warnDiv) warnDiv.style.display = 'none';
                    console.log(`${type} index is properly configured`);
                }
            })
            .catch(err => {
                console.warn(`Checking ${type} index fields:`, err.message);
        
                // Check if this is an index not found error
                if (err.message.includes('does not exist yet') || err.message.includes('not found')) {
                    // Show a different message for missing index
                    if (warnDiv && missingSpan && fixBtn) {
                        missingSpan.textContent = `Index "${type}" does not exist yet`;
                        warnDiv.style.display = 'block';
                        fixBtn.textContent = `Create ${type} Index`;
                        fixBtn.style.display = 'inline-block';
                        fixBtn.dataset.action = 'create';
                    }
                } else if (err.message.includes('not configured')) {
                    // Azure AI Search not configured
                    if (warnDiv && missingSpan) {
                        missingSpan.textContent = 'Azure AI Search not configured';
                        warnDiv.style.display = 'block';
                        if (fixBtn) fixBtn.style.display = 'none';
                    }
                } else {
                    // Hide the warning div for other errors
                    if (warnDiv) warnDiv.style.display = 'none';
                }
            });
  
            // 2) wire up the fix button
            fixBtn.addEventListener('click', () => {
                fixBtn.disabled = true;
                const action = fixBtn.dataset.action || 'fix';
                const endpoint = action === 'create' ? '/api/admin/settings/create_index' : '/api/admin/settings/fix_index_fields';
                const actionText = action === 'create' ? 'Creating' : 'Fixing';
        
                fixBtn.textContent = `${actionText}...`;
        
                fetch(endpoint, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    credentials: 'same-origin',
                    body: JSON.stringify({ indexType: type })
                })
                .then(r => {
                    if (!r.ok) {
                        return r.json().then(errorData => {
                            throw new Error(errorData.error || `HTTP ${r.status}: ${r.statusText}`);
                        });
                    }
                    return r.json();
                })
                .then(resp => {
                    if (resp.status === 'success') {
                        showToast(
                            resp.message || `Successfully ${action === 'create' ? 'created' : 'fixed'} ${type} index!`,
                            'success',
                            { persist: true }
                        );
                        window.location.reload();
                    } else {
                        showToast(`Failed to ${action} ${type} index: ${resp.error}`, 'danger');
                        fixBtn.disabled = false;
                        fixBtn.textContent = `${action === 'create' ? 'Create' : 'Fix'} ${type} Index`;
                    }
                })
                .catch(err => {
                    showToast(`Error ${action === 'create' ? 'creating' : 'fixing'} ${type} index: ${err.message || err}`, 'danger');
                    fixBtn.disabled = false;
                    fixBtn.textContent = `${action === 'create' ? 'Create' : 'Fix'} ${type} Index`;
                });
            });
        });
    });
  

togglePassword('toggle_gpt_key', 'azure_openai_gpt_key');
togglePassword('toggle_embedding_key', 'azure_openai_embedding_key');
togglePassword('toggle_image_gen_key', 'azure_openai_image_gen_key');
togglePassword('toggle_content_safety_key', 'content_safety_key');
togglePassword('toggle_search_key', 'azure_ai_search_key');
togglePassword('toggle_docintel_key', 'azure_document_intelligence_key');
togglePassword('toggle_content_understanding_key', 'azure_content_understanding_key');
togglePassword('toggle_azure_apim_gpt_subscription_key', 'azure_apim_gpt_subscription_key');
togglePassword('toggle_azure_apim_embedding_subscription_key', 'azure_apim_embedding_subscription_key');
togglePassword('toggle_azure_apim_image_gen_subscription_key', 'azure_apim_image_gen_subscription_key');
togglePassword('toggle_azure_apim_content_safety_subscription_key', 'azure_apim_content_safety_subscription_key');
togglePassword('toggle_azure_apim_web_search_subscription_key', 'azure_apim_web_search_subscription_key');
togglePassword('toggle_azure_apim_ai_search_subscription_key', 'azure_apim_ai_search_subscription_key');
togglePassword('toggle_azure_apim_document_intelligence_subscription_key', 'azure_apim_document_intelligence_subscription_key');
togglePassword('toggle_office_docs_key', 'office_docs_key');
togglePassword('toggle_video_files_key', 'video_files_key');
togglePassword('toggle_audio_files_key', 'audio_files_key');
togglePassword('toggle_office_conn_str', 'office_docs_storage_account_blob_endpoint');
togglePassword('toggle_video_conn_str', 'video_files_storage_account_url');
togglePassword('toggle_audio_conn_str', 'audio_files_storage_account_url');
togglePassword('toggle_speech_service_key', 'speech_service_key');
togglePassword('toggle_redis_key', 'redis_key');
togglePassword('toggle_azure_apim_redis_subscription_key', 'azure_apim_redis_subscription_key');
togglePassword('toggle_latest_features_office_conn_str', 'latest_features_office_docs_storage_account_url');
togglePassword('toggle_latest_features_office_url', 'latest_features_office_docs_storage_account_blob_endpoint');
togglePassword('toggle_latest_features_redis_key', 'latest_features_redis_key');

/**
 * Checks if this is a first-time setup based on critical settings
 * @returns {boolean} True if this appears to be a first-time setup
 */
function isFirstTimeSetup() {
    // Check for critical settings that would indicate a first-time setup
    
    // 1. No GPT models selected
    if (!gptSelected || gptSelected.length === 0) {
        return true;
    }
    
    // 2. No embedding models selected but workspaces enabled
    const workspaceEnabled = document.getElementById('enable_user_workspace')?.checked || false;
    const groupsEnabled = document.getElementById('enable_group_workspaces')?.checked || false;
    
    if ((workspaceEnabled || groupsEnabled) && 
        (!embeddingSelected || embeddingSelected.length === 0)) {
        return true;
    }
    
    // 3. Check if GPT endpoint is empty
    const useGptApim = document.getElementById('enable_gpt_apim')?.checked || false;
    
    if (!useGptApim) {
        const gptEndpoint = document.getElementById('azure_openai_gpt_endpoint')?.value;
        if (!gptEndpoint) {
            return true;
        }
    } else {
        const apimEndpoint = document.getElementById('azure_apim_gpt_endpoint')?.value;
        if (!apimEndpoint) {
            return true;
        }
    }
    
    // Not first time setup
    return false;
}

/**
 * Setup the walkthrough for first-time configuration
 */
function setupSettingsWalkthrough() {
    console.log("Setting up walkthrough...");
    
    // Setup the walkthrough buttons first thing
    setupWalkthroughButtons();
    
    // Check if this is a first-time setup
    if (isFirstTimeSetup()) {
        // Auto-show the walkthrough for first-time setup
        setTimeout(() => {
            showWalkthrough();
        }, 500); // Small delay to ensure DOM is ready
    }
    
    // Setup the manual walkthrough button
    const walkthroughBtn = document.getElementById('launch-walkthrough-btn');
    if (walkthroughBtn) {
        // Remove any existing listeners to prevent duplicates
        const newWalkthroughBtn = walkthroughBtn.cloneNode(true);
        if (walkthroughBtn.parentNode) {
            walkthroughBtn.parentNode.replaceChild(newWalkthroughBtn, walkthroughBtn);
        }
        
        // Add new event listener
        newWalkthroughBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log("Walkthrough button clicked");
            showWalkthrough();
        });
    } else {
        console.error("Walkthrough button not found in the DOM");
    }
    
    // Setup the close button
    const closeBtn = document.getElementById('close-walkthrough-btn');
    if (closeBtn) {
        const newCloseBtn = closeBtn.cloneNode(true);
        if (closeBtn.parentNode) {
            closeBtn.parentNode.replaceChild(newCloseBtn, closeBtn);
        }
        newCloseBtn.addEventListener('click', hideWalkthrough);
    }
}

/**
 * Shows the walkthrough container and resets to the first step
 */
function showWalkthrough() {
    try {
        console.log("Showing walkthrough");
        const walkthroughContainer = document.getElementById('settings-walkthrough-container');
        if (!walkthroughContainer) {
            console.error("Walkthrough container not found!");
            return;
        }
        
        // Make sure walkthrough button events are working
        setupWalkthroughButtons();
        
        // Show the container
        walkthroughContainer.style.display = 'block';
        
        // Sync walkthrough toggles with actual form toggles
        syncWalkthroughToggles();
        
        // Check if GPT APIM is enabled and update the model note visibility
        const enableGptApim = document.getElementById('enable_gpt_apim');
        if (enableGptApim) {
            const apimModelNote = document.getElementById('apim-model-note');
            const fetchModelsStep = document.getElementById('fetch-models-step');
            if (apimModelNote && fetchModelsStep) {
                apimModelNote.style.display = enableGptApim.checked ? 'block' : 'none';
                fetchModelsStep.style.display = enableGptApim.checked ? 'none' : 'block';
            }
        }
        
        // Reset to first step when launched
        setTimeout(() => {
            try {
                navigateToWalkthroughStep(1);
            } catch (err) {
                console.error("Error navigating to first walkthrough step:", err);
            }
        }, 100);
        
        // Setup field change listeners for automatic validation
        setupWalkthroughFieldListeners();
    } catch (err) {
        console.error("Error showing walkthrough:", err);
    }
}

/**
 * Make sure walkthrough navigation buttons are properly set up
 */
function setupWalkthroughButtons() {
    const nextButton = document.getElementById('walkthrough-next-btn');
    if (nextButton) {
        nextButton.onclick = function() {
            const currentStep = getCurrentWalkthroughStep();
            console.log("Next button clicked, current step:", currentStep);
            validateAndMoveToNextStep(currentStep);
        };
    }
    
    const prevButton = document.getElementById('walkthrough-prev-btn');
    if (prevButton) {
        prevButton.onclick = navigatePreviousStep;
    }
    
    const finishButton = document.getElementById('walkthrough-finish-btn');
    if (finishButton) {
        finishButton.onclick = finishSetupAndSave;
    }
}

/**
 * Synchronizes toggle states between the walkthrough and the main form
 */
function syncWalkthroughToggles() {
    const syncToggles = [
        // Content safety toggle removed from walkthrough
    ];
    
    syncToggles.forEach(pair => {
        const walkthroughToggle = document.getElementById(pair.walkthrough);
        const formToggle = document.getElementById(pair.form);
        if (walkthroughToggle && formToggle) {
            // Set walkthrough toggle to match form toggle
            walkthroughToggle.checked = formToggle.checked;
        }
    });
}

/**
 * Hides the walkthrough container
 */
function hideWalkthrough() {
    const walkthroughContainer = document.getElementById('settings-walkthrough-container');
    if (walkthroughContainer) {
        walkthroughContainer.style.display = 'none';
    }
}

/**
 * Navigate to the specified step in the walkthrough
 * @param {number} stepNumber - The step number to navigate to
 */
function navigateToWalkthroughStep(stepNumber) {
    // Get all steps and total count
    const steps = document.querySelectorAll('.walkthrough-step');
    const totalSteps = steps.length;
    
    // Validate step number
    if (stepNumber < 1) stepNumber = 1;
    if (stepNumber > totalSteps) stepNumber = totalSteps;
    
    // Check if we should skip this step (based on workspace and feature enablement)
    const shouldSkipStep = shouldSkipWalkthroughStep(stepNumber);
    if (shouldSkipStep && stepNumber < totalSteps && stepNumber > 1) {
        // Recursively navigate to next applicable step
        if (stepNumber > getCurrentWalkthroughStep()) {
            // Moving forward - go to next applicable step
            navigateToWalkthroughStep(findNextApplicableStep(stepNumber));
            return;
        } else {
            // Moving backward - go to previous applicable step
            navigateToWalkthroughStep(findPreviousApplicableStep(stepNumber));
            return;
        }
    }
    
    // Hide all steps
    steps.forEach(step => {
        step.style.display = 'none';
    });
    
    // Show the requested step
    const stepElement = document.getElementById(`walkthrough-step-${stepNumber}`);
    if (stepElement) {
        stepElement.style.display = 'block';
    }
    
    // Update the progress indicator - calculate visible steps
    const availableSteps = calculateAvailableWalkthroughSteps();
    const stepPosition = availableSteps.indexOf(stepNumber) + 1;
    const totalAvailableSteps = availableSteps.length;
    
    const progressBar = document.getElementById('walkthrough-progress');
    if (progressBar) {
        progressBar.style.width = `${(stepPosition / totalAvailableSteps) * 100}%`;
        progressBar.setAttribute('aria-valuenow', stepPosition);
    }
    
    // Handle special tab navigation based on step
    handleTabNavigation(stepNumber);
    
    // Update prev/next buttons
    const prevBtn = document.getElementById('walkthrough-prev-btn');
    const nextBtn = document.getElementById('walkthrough-next-btn');
    const finishBtn = document.getElementById('walkthrough-finish-btn');
    
    if (prevBtn) prevBtn.style.display = stepNumber === 1 ? 'none' : 'inline-block';
    
    if (nextBtn && finishBtn) {
        nextBtn.style.display = stepNumber === totalSteps ? 'none' : 'inline-block';
        finishBtn.style.display = stepNumber === totalSteps ? 'inline-block' : 'none';
    }
    
    // Update completion status for this step
    updateStepCompletionStatus(stepNumber);
    
    // Dispatch a custom event to notify that the step has changed
    const event = new CustomEvent('walkthroughStepChanged', { 
        detail: { step: stepNumber, totalSteps: totalSteps } 
    });
    document.getElementById('settings-walkthrough-container')?.dispatchEvent(event);
}

/**
 * Get the current step displayed in the walkthrough
 * @returns {number} Current step number or 1 if none found
 */
function getCurrentWalkthroughStep() {
    const currentStepElem = document.querySelector('.walkthrough-step:not([style*=\'display: none\'])');
    if (currentStepElem) {
        return parseInt(currentStepElem.id?.split('-')[2]) || 1;
    }
    return 1;
}

/**
 * Calculate which walkthrough steps should be available based on current settings
 * @returns {number[]} Array of step numbers that should be available
 */
function calculateAvailableWalkthroughSteps() {
    const workspaceEnabled = document.getElementById('enable_user_workspace')?.checked || false;
    const groupsEnabled = document.getElementById('enable_group_workspaces')?.checked || false;
    const workspacesEnabled = workspaceEnabled || groupsEnabled;
    
    const videoEnabled = document.getElementById('enable_video_file_support')?.checked || false;
    const audioEnabled = document.getElementById('enable_audio_file_support')?.checked || false;
    const speechToTextEnabled = document.getElementById('enable_speech_to_text_input')?.checked || false;
    const textToSpeechEnabled = document.getElementById('enable_text_to_speech')?.checked || false;
    const speechFeaturesEnabled = audioEnabled || speechToTextEnabled || textToSpeechEnabled;
    
    const availableSteps = [1, 2, 3, 4]; // Base steps always available
    
    // Include workspace-dependent steps if workspaces enabled
    if (workspacesEnabled) {
        availableSteps.push(5, 6, 7); // Embedding, AI Search, Doc Intelligence
        
        if (videoEnabled) {
            availableSteps.push(8); // Video support
        }
    }

    if (speechFeaturesEnabled) {
        availableSteps.push(9); // Shared Speech Service
    }
    
    // Optional steps always available
    availableSteps.push(10, 11, 12); // Safety, Feedback, Enhanced Citations
    
    return availableSteps.sort((a, b) => a - b); // Ensure steps are in order
}

/**
 * Determine if we should skip a particular walkthrough step
 * @param {number} stepNumber - The step to check
 * @returns {boolean} True if the step should be skipped, false otherwise
 */
function shouldSkipWalkthroughStep(stepNumber) {
    const availableSteps = calculateAvailableWalkthroughSteps();
    return !availableSteps.includes(stepNumber);
}

/**
 * Find the next applicable step based on enabled features
 * @param {number} currentStep - The current step number
 * @returns {number} The next applicable step number or -1 if none found
 */

function findNextApplicableStep(currentStep) {
    const workspaceEnabled = document.getElementById('enable_user_workspace')?.checked || false;
    const groupsEnabled = document.getElementById('enable_group_workspaces')?.checked || false;
    const workspacesEnabled = workspaceEnabled || groupsEnabled;
    
    // Start checking from the next step
    let nextStep = currentStep + 1;
    
    // Maximum step to avoid infinite loop
    const maxSteps = 12;
    
    while (nextStep <= maxSteps) {
        // Check if this step is applicable based on conditions
        switch (nextStep) {
            case 5: // Embedding settings
            case 6: // AI Search settings 
            case 7: // Document Intelligence settings
                if (!workspacesEnabled) {
                    // Skip these steps if workspaces not enabled
                    nextStep++;
                    continue;
                }
                return nextStep;
                
            case 8: // Video support
                const videoEnabled = document.getElementById('enable_video_file_support')?.checked || false;
                if (!workspacesEnabled || !videoEnabled) {
                    // Skip this step if workspaces not enabled or video not enabled
                    nextStep++;
                    continue;
                }
                return nextStep;
                
            case 9: // Audio support
                const audioEnabled = document.getElementById('enable_audio_file_support')?.checked || false;
                const speechToTextEnabled = document.getElementById('enable_speech_to_text_input')?.checked || false;
                const textToSpeechEnabled = document.getElementById('enable_text_to_speech')?.checked || false;
                if (!(audioEnabled || speechToTextEnabled || textToSpeechEnabled)) {
                    // Skip this step if no speech features are enabled
                    nextStep++;
                    continue;
                }
                return nextStep;
                
            default:
                // All other steps are always applicable
                return nextStep;
        }
    }
    
    // If we've gone past all steps, return -1
    return -1;
}

/**
 * Find the previous applicable step before a given step
 * @param {number} currentStep - Current step number
 * @returns {number} Previous applicable step number or 1 (first step) if none found
 */
function findPreviousApplicableStep(currentStep) {
    const availableSteps = calculateAvailableWalkthroughSteps();
    
    // Find the first available step before the current one (in reverse)
    for (let i = availableSteps.length - 1; i >= 0; i--) {
        if (availableSteps[i] < currentStep) {
            return availableSteps[i];
        }
    }
    
    return 1; // Default to first step if no previous step found
}

/**
 * Navigate to the appropriate tab based on the walkthrough step
 * @param {number} stepNumber - The current step number
 */
function handleTabNavigation(stepNumber) {
    // Map steps to tabs that need to be activated
    const stepToTab = {
        1: 'general-tab',     // App title and logo (General tab)
        2: 'ai-models-tab',   // GPT settings (now in AI Models tab)
        3: 'ai-models-tab',   // GPT model selection (now in AI Models tab)
        4: 'workspaces-tab',  // Workspace and groups settings
        5: 'ai-models-tab',   // Embedding settings (now in AI Models tab)
        6: 'search-extract-tab', // AI Search settings
        7: 'search-extract-tab', // Document Intelligence settings
        8: 'search-extract-tab',  // Video support
        9: 'search-extract-tab',  // Audio support
        10: 'safety-tab',     // Content safety
        11: 'safety-tab',     // User feedback and archiving (changed from system-tab)
        12: 'citation-tab'    // Enhanced Citations and Image Generation
    };
    
    // Activate the appropriate tab
    const tabId = stepToTab[stepNumber];
    if (tabId) {
        // Check if we're using sidebar navigation or tab navigation
        const sidebarToggle = document.getElementById('admin-settings-toggle');
        
        if (sidebarToggle) {
            // Using sidebar navigation - call showAdminTab function
            const tabName = tabId.replace('-tab', ''); // Remove '-tab' suffix
            if (typeof showAdminTab === 'function') {
                showAdminTab(tabName);
            } else if (typeof window.showAdminTab === 'function') {
                window.showAdminTab(tabName);
            }
        } else {
            // Using Bootstrap tabs
            const tab = document.getElementById(tabId);
            if (tab) {
                // Use bootstrap Tab to show the tab
                const bootstrapTab = new bootstrap.Tab(tab);
                bootstrapTab.show();
            }
        }
        
        // Scroll to the relevant section after a small delay to allow tab to switch
        setTimeout(() => {
            scrollToRelevantSection(stepNumber, tabId);
        }, 300);
    }
}

/**
 * Scroll to relevant section within a tab based on the step
 * @param {number} stepNumber - The current step number
 * @param {string} tabId - The ID of the tab that was activated
 */
function scrollToRelevantSection(stepNumber, tabId) {
    // Define which sections to scroll to for each step
    let targetElement = null;
    
    switch (stepNumber) {
        case 1: // App title and logo
            targetElement = document.getElementById('branding-section');
            break;
        case 2: // GPT settings
            targetElement = document.getElementById('gpt-configuration');
            break;
        case 3: // GPT model selection
            targetElement = document.getElementById('gpt_models_list')?.closest('.mb-3');
            break;
        case 4: // Workspaces toggle section
            targetElement = document.getElementById('personal-workspaces-section');
            break;
        case 5: // Embedding settings
            targetElement = document.getElementById('embeddings-configuration');
            break;
        case 6: // AI Search settings
            targetElement = document.getElementById('azure-ai-search-section');
            break;
        case 7: // Document Intelligence settings
            targetElement = document.getElementById('document-intelligence-section');
            break;
        case 8: // Video file support
            targetElement = document.getElementById('enable_video_file_support')?.closest('.form-group');
            break;
        case 9: // Audio file support
            targetElement = document.getElementById('enable_audio_file_support')?.closest('.form-group');
            break;
        case 10: // Content safety
            targetElement = document.getElementById('content-safety-section');
            break;
        case 11: // User feedback and archiving
            targetElement = document.getElementById('user-feedback-section');
            break;
        case 12: // Enhanced citations and image generation
            targetElement = document.getElementById('enhanced-citations-section');
            break;
        default:
            // For other steps, no specific scrolling
            break;
    }
    
    // If we found a target element, scroll to it
    if (targetElement) {
        targetElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

/**
 * Check if a step is complete by validating its required fields
 * @param {number} stepNumber - The step number to validate
 * @returns {boolean} True if the step is complete, false otherwise
 */
function isStepComplete(stepNumber) {
    const workspaceEnabled = document.getElementById('enable_user_workspace')?.checked || false;
    const groupsEnabled = document.getElementById('enable_group_workspaces')?.checked || false;
    const workspacesEnabled = workspaceEnabled || groupsEnabled;
    
    switch (stepNumber) {
        case 1: // App title and logo - always complete (optional)
            return true;
            
        case 2: // GPT settings
            // Check if GPT endpoint is configured when required
            if (!document.getElementById('enable_gpt_apim').checked) {
                const endpoint = document.getElementById('azure_openai_gpt_endpoint').value;
                const authType = document.getElementById('azure_openai_gpt_authentication_type').value;
                const key = document.getElementById('azure_openai_gpt_key').value;
                
                if (!endpoint) return false;
                if (authType === 'key' && !key) return false;
            } else {
                const apimEndpoint = document.getElementById('azure_apim_gpt_endpoint').value;
                const apimKey = document.getElementById('azure_apim_gpt_subscription_key').value;
                
                if (!apimEndpoint) return false;
                if (!apimKey) return false;
            }
            return true;
            
        case 3: // GPT model selection
            if (!document.getElementById('enable_gpt_apim').checked) {
                // For direct Azure OpenAI, check if models are selected
                return gptSelected && gptSelected.length > 0;
            } else {
                // For APIM, check if deployment field is filled
                const apimDeployment = document.getElementById('azure_apim_gpt_deployment')?.value;
                return apimDeployment && apimDeployment.trim() !== '';
            }
            
        case 4: // Workspace and groups settings - always complete (optional)
            return true;
            
        case 5: // Embedding settings (if workspace or groups enabled)
            if (!workspacesEnabled) return true; // Not required if workspaces not enabled
            
            if (!document.getElementById('enable_embedding_apim').checked) {
                const endpoint = document.getElementById('azure_openai_embedding_endpoint').value;
                const authType = document.getElementById('azure_openai_embedding_authentication_type').value;
                const key = document.getElementById('azure_openai_embedding_key').value;
                
                if (!endpoint) return false;
                if (authType === 'key' && !key) return false;
            } else {
                const apimEndpoint = document.getElementById('azure_apim_embedding_endpoint').value;
                const apimKey = document.getElementById('azure_apim_embedding_subscription_key').value;
                
                if (!apimEndpoint) return false;
                if (!apimKey) return false;
            }
            
            // Also check if embedding models are selected or APIM deployment is specified
            if (!document.getElementById('enable_embedding_apim').checked) {
                // For direct Azure OpenAI, check models
                if (embeddingSelected.length === 0) return false;
            } else {
                // For APIM, check deployment field
                const apimDeployment = document.getElementById('azure_apim_embedding_deployment')?.value;
                if (!apimDeployment || apimDeployment.trim() === '') return false;
            }
            
            return true;
            
        case 6: // AI Search settings
            if (!workspacesEnabled) return true; // Not required if workspaces not enabled
            
            if (!document.getElementById('enable_ai_search_apim').checked) {
                const endpoint = document.getElementById('azure_ai_search_endpoint').value;
                const authType = document.getElementById('azure_ai_search_authentication_type').value;
                const key = document.getElementById('azure_ai_search_key').value;
                
                if (!endpoint) return false;
                if (authType === 'key' && !key) return false;
            } else {
                const apimEndpoint = document.getElementById('azure_apim_ai_search_endpoint').value;
                const apimKey = document.getElementById('azure_apim_ai_search_subscription_key').value;
                
                if (!apimEndpoint) return false;
                if (!apimKey) return false;
            }
            return true;
            
        case 7: // Document Intelligence settings
            if (!workspacesEnabled) return true; // Not required if workspaces not enabled
            
            if (!document.getElementById('enable_document_intelligence_apim').checked) {
                const endpoint = document.getElementById('azure_document_intelligence_endpoint').value;
                const authType = document.getElementById('azure_document_intelligence_authentication_type').value;
                const key = document.getElementById('azure_document_intelligence_key').value;
                
                if (!endpoint) return false;
                if (authType === 'key' && !key) return false;
            } else {
                const apimEndpoint = document.getElementById('azure_apim_document_intelligence_endpoint').value;
                const apimKey = document.getElementById('azure_apim_document_intelligence_subscription_key').value;
                
                if (!apimEndpoint) return false;
                if (!apimKey) return false;
            }
            return true;
            
        case 8: // Video support
            const videoEnabled = document.getElementById('enable_video_file_support').checked || false;
            
            // If workspaces not enabled or video not enabled, it's always complete
            if (!workspacesEnabled || !videoEnabled) return true;
            
            // Otherwise check settings
            const videoEndpoint = document.getElementById('video_indexer_endpoint')?.value;
            const videoLocation = document.getElementById('video_indexer_location')?.value;
            const videoAccountId = document.getElementById('video_indexer_account_id')?.value;
            const videoResourceGroup = document.getElementById('video_indexer_resource_group')?.value;
            const videoSubscriptionId = document.getElementById('video_indexer_subscription_id')?.value;
            const videoAccountName = document.getElementById('video_indexer_account_name')?.value;

            return Boolean(
                videoLocation &&
                videoAccountId &&
                videoEndpoint &&
                videoResourceGroup &&
                videoSubscriptionId &&
                videoAccountName
            );
            
        case 9: // Audio support
            const audioEnabled = document.getElementById('enable_audio_file_support').checked || false;
            const speechToTextEnabled = document.getElementById('enable_speech_to_text_input')?.checked || false;
            const textToSpeechEnabled = document.getElementById('enable_text_to_speech')?.checked || false;
            const speechFeaturesEnabled = audioEnabled || speechToTextEnabled || textToSpeechEnabled;
            
            // If no speech features are enabled, it's always complete
            if (!speechFeaturesEnabled) return true;
            
            // Otherwise check settings
            const speechEndpoint = document.getElementById('speech_service_endpoint')?.value;
            const authType = document.getElementById('speech_service_authentication_type').value;
            const key = document.getElementById('speech_service_key').value;
            const speechLocation = document.getElementById('speech_service_location')?.value;
            const speechResourceId = document.getElementById('speech_service_resource_id')?.value;

            if (!speechEndpoint) {
                return false;
            }

            if (authType === 'key') {
                return Boolean(key);
            }

            if (textToSpeechEnabled) {
                return Boolean(speechLocation && speechResourceId);
            }

            return true;
            
        case 10: // Content safety - always complete (optional)
        case 11: // User feedback and archiving - always complete (optional)
        case 12: // Enhanced Citations and Image Generation - always complete (optional)
            return true;
            
        default:
            return true; // Default to true for any unknown steps
    }
}

/**
 * Update UI to show completion status for a step
 * @param {number} stepNumber - The step number to update
 */
function updateStepCompletionStatus(stepNumber) {
    const isComplete = isStepComplete(stepNumber);
    const stepElement = document.getElementById(`walkthrough-step-${stepNumber}`);
    if (!stepElement) return;
    
    // Find badge elements in this step
    const badges = stepElement.querySelectorAll('.badge.bg-danger');
    const optionalBadges = stepElement.querySelectorAll('.badge.bg-secondary');
    const requirementAlert = stepElement.querySelector('.alert-danger');
    const optionalAlert = stepElement.querySelector('.alert-info');
    
    // Update next button state
    const nextButton = document.getElementById('walkthrough-next-btn');
    if (nextButton) {
        if (isComplete) {
            nextButton.classList.remove('btn-secondary');
            nextButton.classList.add('btn-primary');
            nextButton.disabled = false;
        } else {
            nextButton.classList.remove('btn-primary');
            nextButton.classList.add('btn-secondary');
            nextButton.disabled = true;
        }
    }
    
    // Check if optional features are enabled/configured for this step
    const optionalFeaturesEnabled = checkOptionalFeaturesEnabled(stepNumber);
    
    // Update required badges and alerts if step is complete
    if (isComplete) {
        // Update badge status for required items
        badges.forEach(badge => {
            badge.classList.remove('bg-danger');
            badge.classList.add('bg-success');
            badge.textContent = 'Complete';
        });
        
        // Update or hide the requirement alert
        if (requirementAlert) {
            requirementAlert.classList.remove('alert-danger');
            requirementAlert.classList.add('alert-success');
            requirementAlert.innerHTML = '<strong>Complete:</strong> Configuration finished for this step.';
        }
    } else {
        // Ensure badges show required status
        badges.forEach(badge => {
            badge.classList.remove('bg-success');
            badge.classList.add('bg-danger');
            badge.textContent = 'Required';
        });
        
        // Reset requirement alert if needed
        if (requirementAlert && requirementAlert.classList.contains('alert-success')) {
            requirementAlert.classList.remove('alert-success');
            requirementAlert.classList.add('alert-danger');
            
            // Reset alert text based on step number
            switch (stepNumber) {
                case 2:
                    requirementAlert.innerHTML = '<strong>Required:</strong> GPT API configuration is required for Simple Chat to function.';
                    break;
                case 3:
                    requirementAlert.innerHTML = '<strong>Required:</strong> Select at least one GPT model for users to use.';
                    break;
                case 5:
                    requirementAlert.innerHTML = '<strong>Required:</strong> Embedding API configuration is required if workspaces are enabled.';
                    break;
                case 6:
                    requirementAlert.innerHTML = '<strong>Required:</strong> Azure AI Search is required if workspaces are enabled.';
                    break;
                case 7:
                    requirementAlert.innerHTML = '<strong>Required:</strong> Document Intelligence is required if workspaces are enabled.';
                    break;
                case 8:
                    requirementAlert.innerHTML = '<strong>Required:</strong> Video support configuration is required if workspaces are enabled.';
                    break;
                case 9:
                    requirementAlert.innerHTML = '<strong>Required:</strong> Audio support configuration is required if workspaces are enabled.';
                    break;
            }
        }
    }
    
    // Update optional features status if they're enabled/configured
    if (optionalFeaturesEnabled) {
        // Update optional badges to show as complete
        optionalBadges.forEach(badge => {
            badge.classList.remove('bg-secondary');
            badge.classList.add('bg-success');
            badge.textContent = 'Complete';
        });
        
        // Update optional alert if present
        if (optionalAlert) {
            optionalAlert.classList.remove('alert-info');
            optionalAlert.classList.add('alert-success');
            optionalAlert.innerHTML = '<strong>Complete:</strong> Optional features configured successfully.';
        }
    } else {
        // Keep optional badges as is
        optionalBadges.forEach(badge => {
            badge.classList.remove('bg-success');
            badge.classList.add('bg-secondary');
            badge.textContent = 'Optional';
        });
        
        // Reset optional alert if it was changed
        if (optionalAlert && optionalAlert.classList.contains('alert-success')) {
            optionalAlert.classList.remove('alert-success');
            optionalAlert.classList.add('alert-info');
            
            // Reset optional alert text based on step number
            switch (stepNumber) {
                case 1:
                    optionalAlert.innerHTML = '<strong>Optional:</strong> Configure your application title and logo.';
                    break;
                case 4:
                    optionalAlert.innerHTML = '<strong>Optional:</strong> Enable personal and group workspaces for document management.';
                    break;
                case 10:
                    optionalAlert.innerHTML = '<strong>Optional:</strong> Enable content safety features to filter inappropriate content.';
                    break;
                case 11:
                    optionalAlert.innerHTML = '<strong>Optional:</strong> Enable user feedback and conversation archiving.';
                    break;
                case 12:
                    optionalAlert.innerHTML = '<strong>Optional:</strong> Enable enhanced citations and image generation features.';
                    break;
                default:
                    optionalAlert.innerHTML = '<strong>Optional:</strong> This configuration is optional.';
            }
        }
    }
}

/**
 * Setup field change listeners for real-time validation during walkthrough
 */
function setupWalkthroughFieldListeners() {
    // Define field groups by step number
    const fieldGroups = {
        2: [ // GPT settings
            {selector: '#azure_openai_gpt_endpoint', event: 'input'},
            {selector: '#azure_openai_gpt_key', event: 'input'},
            {selector: '#azure_openai_gpt_authentication_type', event: 'change'},
            {selector: '#azure_apim_gpt_endpoint', event: 'input'},
            {selector: '#azure_apim_gpt_subscription_key', event: 'input'},
            {selector: '#azure_apim_gpt_deployment', event: 'input'},
            {selector: '#enable_gpt_apim', event: 'change'}
        ],
        3: [ // GPT Models
            {selector: '#fetch_gpt_models_btn', event: 'click', delay: 1000}
        ],
        4: [ // Workspace toggles
            {selector: '#enable_user_workspace', event: 'change'},
            {selector: '#enable_group_workspaces', event: 'change'}
        ],
        5: [ // Embedding settings
            {selector: '#azure_openai_embedding_endpoint', event: 'input'},
            {selector: '#azure_openai_embedding_key', event: 'input'},
            {selector: '#azure_openai_embedding_authentication_type', event: 'change'},
            {selector: '#azure_apim_embedding_endpoint', event: 'input'},
            {selector: '#azure_apim_embedding_subscription_key', event: 'input'},
            {selector: '#enable_embedding_apim', event: 'change'},
            {selector: '#fetch_embedding_models_btn', event: 'click', delay: 1000}
        ],
        6: [ // AI Search settings
            {selector: '#azure_ai_search_endpoint', event: 'input'},
            {selector: '#azure_ai_search_key', event: 'input'},
            {selector: '#azure_ai_search_authentication_type', event: 'change'},
            {selector: '#azure_apim_ai_search_endpoint', event: 'input'},
            {selector: '#azure_apim_ai_search_subscription_key', event: 'input'},
            {selector: '#enable_ai_search_apim', event: 'change'}
        ],
        7: [ // Document Intelligence settings
            {selector: '#azure_document_intelligence_endpoint', event: 'input'},
            {selector: '#azure_document_intelligence_key', event: 'input'},
            {selector: '#azure_document_intelligence_authentication_type', event: 'change'},
            {selector: '#document_intelligence_pdf_image_extraction_mode', event: 'change'},
            {selector: '#document_intelligence_auto_sample_pages', event: 'input'},
            {selector: '#azure_apim_document_intelligence_endpoint', event: 'input'},
            {selector: '#azure_apim_document_intelligence_subscription_key', event: 'input'},
            {selector: '#enable_document_intelligence_apim', event: 'change'},
            {selector: '#enable_enhanced_extraction', event: 'change'},
            {selector: '#azure_content_understanding_endpoint', event: 'input'},
            {selector: '#azure_content_understanding_key', event: 'input'},
            {selector: '#azure_content_understanding_authentication_type', event: 'change'},
            {selector: '#azure_content_understanding_api_version', event: 'input'},
            {selector: '#azure_content_understanding_analyzer_id', event: 'input'},
            {selector: '#azure_content_understanding_image_analyzer_id', event: 'input'},
            {selector: '#enable_office_embedded_image_analysis', event: 'change'},
            {selector: '#enable_document_intelligence_formula_extraction', event: 'change'},
            {selector: '#office_embedded_image_min_pixels', event: 'input'},
            {selector: '#office_embedded_image_max_per_document', event: 'input'}
        ],
        8: [ // Video settings
            {selector: '#enable_video_file_support', event: 'change'},
            {selector: '#video_indexer_cloud', event: 'change'},
            {selector: '#video_indexer_custom_endpoint', event: 'input'},
            {selector: '#video_indexer_location', event: 'input'},
            {selector: '#video_indexer_account_id', event: 'input'},
            {selector: '#video_indexer_resource_group', event: 'input'},
            {selector: '#video_indexer_subscription_id', event: 'input'},
            {selector: '#video_indexer_account_name', event: 'input'}
        ],
        9: [ // Audio settings
            {selector: '#enable_audio_file_support', event: 'change'},
            {selector: '#enable_speech_to_text_input', event: 'change'},
            {selector: '#enable_text_to_speech', event: 'change'},
            {selector: '#speech_service_endpoint', event: 'input'},
            {selector: '#speech_service_authentication_type', event: 'change'},
            {selector: '#speech_service_subscription_id', event: 'input'},
            {selector: '#speech_service_resource_group', event: 'input'},
            {selector: '#speech_service_resource_name', event: 'input'},
            {selector: '#speech_service_key', event: 'input'},
            {selector: '#speech_service_location', event: 'input'},
            {selector: '#speech_service_resource_id', event: 'input'}
        ]
    };
    
    // Add listeners to each group of fields
    for (const [stepNumber, fields] of Object.entries(fieldGroups)) {
        const step = parseInt(stepNumber, 10);
        fields.forEach(field => {
            const element = document.querySelector(field.selector);
            if (element) {
                // Create the handler function, using any delay specified
                const handler = () => {
                    if (field.delay) {
                        setTimeout(() => updateStepCompletionStatus(step), field.delay);
                    } else {
                        updateStepCompletionStatus(step);
                    }
                };
                
                // Remove any existing listeners (to prevent duplicates)
                element.removeEventListener(field.event, handler);
                
                // Add the new listener
                element.addEventListener(field.event, handler);
            }
        });
    }
    
    // Special case for model selection buttons which are dynamically created
    // We'll use event delegation for these
    document.addEventListener('click', event => {
        if (event.target.matches('button') && event.target.onclick && 
            event.target.onclick.toString().includes('selectGptModel')) {
            setTimeout(() => updateStepCompletionStatus(3), 100);
        } else if (event.target.matches('button') && event.target.onclick && 
            event.target.onclick.toString().includes('selectEmbeddingModel')) {
            setTimeout(() => updateStepCompletionStatus(5), 100);
        }
    });
}

/**
 * Initialize Bootstrap tooltips for any elements with data-bs-toggle="tooltip"
 */
function initializeTooltips() {
    // Find all tooltip elements
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    
    // Initialize Bootstrap tooltips
    if (tooltipTriggerList.length > 0) {
        const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
    }
}

function setupLandingPageLogoScaleControl() {
    const slider = document.getElementById('landing_page_logo_scale_percent');
    const valueDisplay = document.getElementById('landing-page-logo-scale-value');

    if (!slider || !valueDisplay) {
        return;
    }

    const updateValue = () => {
        valueDisplay.textContent = `${slider.value}%`;
    };

    slider.addEventListener('input', updateValue);
    slider.addEventListener('change', updateValue);
    updateValue();
}

function setupDocumentActionCapabilityControls() {
    const rangeInputs = document.querySelectorAll('.document-action-capability-range');
    if (!rangeInputs.length) {
        return;
    }

    rangeInputs.forEach(rangeInput => {
        const numberInputId = rangeInput.getAttribute('data-range-sync');
        const valueDisplayId = rangeInput.getAttribute('data-range-display');
        const numberInput = numberInputId ? document.getElementById(numberInputId) : null;
        const valueDisplay = valueDisplayId ? document.getElementById(valueDisplayId) : null;

        if (!numberInput) {
            return;
        }

        const minValue = Number.parseInt(rangeInput.min || numberInput.min || '0', 10);
        const maxValue = Number.parseInt(rangeInput.max || numberInput.max || '0', 10);

        const clampValue = rawValue => {
            const parsedValue = Number.parseInt(rawValue, 10);
            if (Number.isNaN(parsedValue)) {
                return null;
            }

            return Math.min(maxValue, Math.max(minValue, parsedValue));
        };

        const updateValueDisplay = value => {
            if (valueDisplay) {
                valueDisplay.textContent = `${value}`;
            }
        };

        const syncFromRange = () => {
            const clampedValue = clampValue(rangeInput.value);
            if (clampedValue === null) {
                return;
            }

            rangeInput.value = `${clampedValue}`;
            numberInput.value = `${clampedValue}`;
            updateValueDisplay(clampedValue);
        };

        const syncFromNumber = forceClamp => {
            const clampedValue = clampValue(numberInput.value);
            if (clampedValue === null) {
                if (forceClamp) {
                    syncFromRange();
                }
                return;
            }

            if (forceClamp || numberInput.value !== '') {
                rangeInput.value = `${clampedValue}`;
                numberInput.value = `${clampedValue}`;
                updateValueDisplay(clampedValue);
            }
        };

        rangeInput.addEventListener('input', syncFromRange);
        rangeInput.addEventListener('change', syncFromRange);
        numberInput.addEventListener('input', () => syncFromNumber(false));
        numberInput.addEventListener('change', () => syncFromNumber(true));

        syncFromNumber(true);
    });
}

/**
 * Check if optional features are enabled and configured for a specific step
 * @param {number} stepNumber - The step to check
 * @returns {boolean} True if optional features are enabled/configured
 */
function checkOptionalFeaturesEnabled(stepNumber) {
    switch (stepNumber) {
        case 1: // App title and logo
            // Check if title or logo is configured
            const appTitle = document.getElementById('app_title')?.value;
            const logoFile = document.getElementById('app_logo_file')?.files?.length > 0;
            const currentLogo = document.getElementById('current_logo_img');
            return appTitle || logoFile || (currentLogo && currentLogo.src && !currentLogo.src.includes('default_logo.png'));
        
        case 4: // Workspaces
            // Check if workspaces are enabled
            const userWorkspace = document.getElementById('enable_user_workspace')?.checked;
            const groupWorkspace = document.getElementById('enable_group_workspaces')?.checked;
            return userWorkspace || groupWorkspace;
            
        case 10: // Content Safety
            // Check if content safety is enabled and configured
            const safetyEnabled = document.getElementById('enable_content_safety')?.checked;
            if (!safetyEnabled) return false;
            
            // Check configuration based on APIM or direct
            const safetyApim = document.getElementById('enable_content_safety_apim')?.checked;
            if (safetyApim) {
                const apimEndpoint = document.getElementById('azure_apim_content_safety_endpoint')?.value;
                const apimKey = document.getElementById('azure_apim_content_safety_subscription_key')?.value;
                return apimEndpoint && apimKey;
            } else {
                const endpoint = document.getElementById('content_safety_endpoint')?.value;
                const key = document.getElementById('content_safety_key')?.value;
                return endpoint && key;
            }
        
        case 11: // User feedback, archiving, and thoughts
            // Check if feedback, archiving, or thoughts is enabled
            const feedbackEnabled = document.getElementById('enable_user_feedback')?.checked;
            const archivingEnabled = document.getElementById('enable_conversation_archiving')?.checked;
            const thoughtsEnabled = document.getElementById('enable_thoughts')?.checked;
            return feedbackEnabled || archivingEnabled || thoughtsEnabled;
            
        case 12: // Enhanced citations and image generation
            // Check if enhanced citations or image generation is enabled
            const citationsEnabled = document.getElementById('enable_enhanced_citations')?.checked;
            const imageGenEnabled = document.getElementById('enable_image_generation')?.checked;
            
            // For image generation, check if it's properly configured when enabled
            if (imageGenEnabled) {
                const imageApim = document.getElementById('enable_image_gen_apim')?.checked;
                if (imageApim) {
                    const apimEndpoint = document.getElementById('azure_apim_image_gen_endpoint')?.value;
                    const apimKey = document.getElementById('azure_apim_image_gen_subscription_key')?.value;
                    return citationsEnabled || (apimEndpoint && apimKey);
                } else {
                    const endpoint = document.getElementById('azure_openai_image_gen_endpoint')?.value;
                    const key = document.getElementById('azure_openai_image_gen_key')?.value;
                    return citationsEnabled || (endpoint && key);
                }
            }
            
            return citationsEnabled;
            
        default:
            // For steps not specifically handled (like required steps), return false
            return false;
    }
}
function validateAndMoveToNextStep(currentStep) {
    // Synchronize walkthrough toggles with form before validation
    syncWalkthroughToggles();
    
    // Initialize tooltips for APIM help
    initializeTooltips();
    
    // Check if the current step is complete
    const complete = isStepComplete(currentStep);
    
    // If step is complete, we can proceed
    if (complete) {
        // Find next applicable step that should be shown
        const nextStep = findNextApplicableStep(currentStep);
        if (nextStep > 0) {
            navigateToWalkthroughStep(nextStep);
        } else {
            // If no more applicable steps, we're at the end
            navigateToWalkthroughStep(12); // Go to final step
        }
    } else {
        // Highlight missing fields with validation (handled by updateStepCompletionStatus)
        updateStepCompletionStatus(currentStep);
        
        // Show alert for what's missing (this is now handled through the UI indicators)
        // No need for individual alerts as the button is disabled and visual cues are present
    }
}

/**
 * Navigate to the previous step in the walkthrough
 */
function navigatePreviousStep() {
    // Get the current step
    const currentStep = getCurrentWalkthroughStep();
    
    // Find the previous applicable step
    const prevStep = findPreviousApplicableStep(currentStep);
    
    // Navigate to the previous step if one is found
    if (prevStep > 0) {
        navigateToWalkthroughStep(prevStep);
    } else {
        // If no previous step found, go to first step
        navigateToWalkthroughStep(1);
    }
}

/**
 * Sets up event listeners to track form changes
 */
function setupFormChangeTracking() {
    if (!adminForm || !saveButton) return;
    
    // Initialize button state
    updateSaveButtonState();
    
    // Add event listeners to all form inputs, selects, and textareas
    const formElements = Array.from(adminForm.querySelectorAll('input, select, textarea')).filter(element => !isIgnoredSettingsChangeElement(element));
    formElements.forEach(element => {
        // For checkboxes and radios, listen for change event
        if (element.type === 'checkbox' || element.type === 'radio') {
            element.addEventListener('change', markFormAsModified);
        } 
        // For other inputs, listen for input event
        else {
            element.addEventListener('input', markFormAsModified);
        }
    });
    
    // Reset form state when form is submitted
    adminForm.addEventListener('submit', event => {
        if (event.defaultPrevented) {
            return;
        }
        formModified = false;
        updateSaveButtonState();
    });

    document.querySelectorAll('button[data-bs-toggle="tab"]').forEach(tabButton => {
        tabButton.addEventListener('shown.bs.tab', updateSaveButtonState);
    });
}

function isIgnoredSettingsChangeElement(element) {
    return Boolean(element?.closest('[data-ignore-settings-change="true"]'));
}

/**
 * Mark the form as modified and update the save button
 */
function markFormAsModified() {
    formModified = true;
    updateSaveButtonState();
}

window.markFormAsModified = markFormAsModified;
window.isAdminSettingsFormModified = () => formModified;

/**
 * Update the save button appearance based on form state
 */
function updateSaveButtonState() {
    if (!saveButton) return;

    const dataManagementPane = document.getElementById('data-management');
    const isDataManagementActive = Boolean(dataManagementPane?.classList.contains('active'));
    saveButton.classList.toggle('d-none', isDataManagementActive);
    if (isDataManagementActive) {
        return;
    }
    
    if (formModified) {
        // Enable button, make it blue, and update text
        saveButton.disabled = false;
        saveButton.classList.remove('btn-secondary');
        saveButton.classList.add('btn-primary');
        saveButton.innerHTML = '<i class="bi bi-floppy"></i> Save Pending';
    } else {
        // Disable button, make it grey, and reset text
        saveButton.disabled = true;
        saveButton.classList.remove('btn-primary');
        saveButton.classList.add('btn-secondary');
        saveButton.innerHTML = '<i class="bi bi-floppy"></i> Save Settings';
    }
}

window.updateAdminSettingsSaveButtonState = updateSaveButtonState;

function setupLatestFeatureImageModal() {
    const modalElement = document.getElementById('latestFeatureImageModal');
    const modalImage = document.getElementById('latestFeatureImageModalImage');
    const modalTitle = document.getElementById('latestFeatureImageModalLabel');
    const modalCaption = document.getElementById('latestFeatureImageModalCaption');
    const imageTriggers = document.querySelectorAll('[data-latest-feature-image-src]');

    if (!modalElement || !modalImage || !modalTitle || !modalCaption || imageTriggers.length === 0) {
        return;
    }

    const imageModal = bootstrap.Modal.getOrCreateInstance(modalElement);

    imageTriggers.forEach(trigger => {
        trigger.addEventListener('click', () => {
            const imageSrc = trigger.dataset.latestFeatureImageSrc;
            const imageTitle = trigger.dataset.latestFeatureImageTitle || 'Latest Feature Preview';
            const imageCaption = trigger.dataset.latestFeatureImageCaption || 'Click outside the popup to close it.';
            const imageAlt = trigger.querySelector('img')?.getAttribute('alt') || imageTitle;

            if (!imageSrc) {
                return;
            }

            modalImage.src = imageSrc;
            modalImage.alt = imageAlt;
            modalTitle.textContent = imageTitle;
            modalCaption.textContent = imageCaption;
            imageModal.show();
        });
    });

    modalElement.addEventListener('hidden.bs.modal', () => {
        modalImage.src = '';
        modalImage.alt = 'Latest feature preview';
    });
}

function openAdminSettingsTab(targetHash, sectionId = '') {
    if (!targetHash) {
        return;
    }

    const normalizedHash = targetHash.startsWith('#') ? targetHash : `#${targetHash}`;
    history.pushState(null, null, normalizedHash);
    activateTabFromHash();

    if (sectionId) {
        setTimeout(() => {
            document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 150);
    }
}

window.openAdminSettingsTab = openAdminSettingsTab;