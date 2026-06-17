// agent_modal_stepper.js
// Multi-step modal functionality for agent creation
import { showToast } from "./chat/chat-toast.js";
import * as agentsCommon from "./agents_common.js";
import { getModelSupportedLevels } from "./chat/chat-reasoning.js";

const ACTION_CAPABILITIES_KEY = 'action_capabilities';
const ASSIGNED_KNOWLEDGE_KEY = 'assigned_knowledge';
const ASSIGNED_KNOWLEDGE_USER_ACTIONS = Object.freeze(['search', 'analyze', 'compare']);
const ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODES = Object.freeze(['url_review', 'deep_research']);
const EMPTY_ASSIGNED_KNOWLEDGE = Object.freeze({
  enabled: false,
  scopes: {
    personal: false,
    group_ids: [],
    public_workspace_ids: []
  },
  document_ids: [],
  tags: [],
  web_sources: [],
  allow_user_workspace_context: false,
  allowed_user_workspace_actions: ASSIGNED_KNOWLEDGE_USER_ACTIONS
});

function normalizeHttpUrl(value) {
  const rawUrl = String(value || '').trim();
  if (!rawUrl) {
    return '';
  }
  try {
    const parsedUrl = new URL(rawUrl);
    if (!['http:', 'https:'].includes(parsedUrl.protocol) || !parsedUrl.hostname) {
      return '';
    }
    return parsedUrl.toString();
  } catch (error) {
    return '';
  }
}

const SIMPLECHAT_CAPABILITY_DEFINITIONS = [
  {
    key: 'create_group',
    label: 'Create groups',
    description: 'Allow the agent to create new group workspaces as the current user.'
  },
  {
    key: 'add_group_member',
    label: 'Add users to groups',
    description: 'Allow the agent to add members directly to groups using the current user\'s permissions.'
  },
  {
    key: 'make_group_inactive',
    label: 'Make groups inactive',
    description: 'Allow the agent to mark a group inactive when the current user has Control Center admin access.'
  },
  {
    key: 'create_group_conversation',
    label: 'Create group multi-user conversations',
    description: 'Allow the agent to create invite-managed group multi-user conversations and then add current group members as participants.'
  },
  {
    key: 'invite_group_conversation_members',
    label: 'Invite group conversation members',
    description: 'Allow the agent to invite current group members into an existing invite-managed group multi-user conversation.'
  },
  {
    key: 'create_personal_conversation',
    label: 'Create personal conversations',
    description: 'Allow the agent to create standard one-user personal conversations.'
  },
  {
    key: 'create_personal_workflow',
    label: 'Create personal workflows',
    description: 'Allow the agent to create personal workflows using the current user\'s own workflow permissions.'
  },
  {
    key: 'add_conversation_message',
    label: 'Add conversation messages',
    description: 'Allow the agent to add a user-authored message to an existing personal or collaborative conversation.'
  },
  {
    key: 'upload_markdown_document',
    label: 'Upload markdown documents',
    description: 'Allow the agent to create and upload Markdown documents into the current user\'s personal or allowed group workspaces.'
  },
  {
    key: 'upload_word_document',
    label: 'Upload Word documents',
    description: 'Allow the agent to create and upload Word documents into the current user\'s personal or allowed group workspaces.'
  },
  {
    key: 'upload_powerpoint_document',
    label: 'Upload PowerPoint documents',
    description: 'Allow the agent to create and upload PowerPoint presentations into the current user\'s personal or allowed group workspaces.'
  },
  {
    key: 'create_personal_collaboration_conversation',
    label: 'Create personal collaborative conversations',
    description: 'Allow the agent to create personal collaborative conversations and invite participants.'
  }
];
const MSGRAPH_CAPABILITY_DEFINITIONS = [
  {
    key: 'get_my_profile',
    label: 'Read my profile',
    description: 'Allow the agent to read the signed-in user\'s Microsoft 365 profile details.'
  },
  {
    key: 'get_my_timezone',
    label: 'Read my mailbox timezone',
    description: 'Allow the agent to read mailbox time zone and time formatting settings.'
  },
  {
    key: 'get_my_events',
    label: 'Read my calendar events',
    description: 'Allow the agent to read upcoming calendar events for the signed-in user.'
  },
  {
    key: 'create_calendar_invite',
    label: 'Create calendar invites',
    description: 'Allow the agent to create calendar invites, add current group members as attendees, and create Microsoft Teams meetings.'
  },
  {
    key: 'get_my_messages',
    label: 'Read my mail',
    description: 'Allow the agent to read recent mail messages for the signed-in user.'
  },
  {
    key: 'mark_message_as_read',
    label: 'Update message read state',
    description: 'Allow the agent to mark mail messages as read or unread.'
  },
  {
    key: 'send_mail',
    label: 'Send mail',
    description: 'Allow the agent to create manual drafts, delayed-delivery drafts, or send mail.'
  },
  {
    key: 'search_users',
    label: 'Search directory users',
    description: 'Allow the agent to search Microsoft 365 directory users by name or email prefix.'
  },
  {
    key: 'get_user_by_email',
    label: 'Lookup user by email',
    description: 'Allow the agent to look up a directory user by exact email address or UPN.'
  },
  {
    key: 'list_drive_items',
    label: 'List OneDrive items',
    description: 'Allow the agent to list items from the signed-in user\'s OneDrive.'
  },
  {
    key: 'get_my_security_alerts',
    label: 'Read my security alerts',
    description: 'Allow the agent to read recent security alerts available to the signed-in user.'
  }
];
const CHART_CAPABILITY_DEFINITIONS = [
  {
    key: 'line',
    label: 'Line charts',
    description: 'Allow the agent to generate line charts.'
  },
  {
    key: 'bar',
    label: 'Bar charts',
    description: 'Allow the agent to generate bar charts.'
  },
  {
    key: 'pie',
    label: 'Pie charts',
    description: 'Allow the agent to generate pie charts.'
  },
  {
    key: 'doughnut',
    label: 'Doughnut charts',
    description: 'Allow the agent to generate doughnut charts.'
  },
  {
    key: 'scatter',
    label: 'Scatter plots',
    description: 'Allow the agent to generate scatter plots.'
  },
  {
    key: 'area',
    label: 'Area charts',
    description: 'Allow the agent to generate area charts.'
  },
  {
    key: 'bubble',
    label: 'Bubble charts',
    description: 'Allow the agent to generate bubble charts.'
  },
  {
    key: 'radar',
    label: 'Radar charts',
    description: 'Allow the agent to generate radar charts.'
  },
  {
    key: 'stacked_bar',
    label: 'Stacked bar charts',
    description: 'Allow the agent to generate stacked bar charts.'
  },
  {
    key: 'stacked_line',
    label: 'Stacked line charts',
    description: 'Allow the agent to generate stacked line charts.'
  }
];

export class AgentModalStepper {
  constructor(isAdmin = false, options = {}) {
    this.currentStep = 1;
    this.maxSteps = 7;
    this.isEditMode = false;
    this.isAdmin = isAdmin; // Track if this is admin context
    this.workspaceScope = options.workspaceScope || (isAdmin ? 'admin' : 'user');
    this.settingsEndpoint = options.settingsEndpoint || (isAdmin ? '/api/admin/agent/settings' : '/api/user/agent/settings');
    this.currentAgentType = 'local';
    this.originalAgent = null;  // Track original state for change detection
    this.actionsToSelect = null; // Store actions to select when they're loaded
    this.availableActions = [];
    this.updateStepIndicatorTimeout = null; // For debouncing step indicator updates
    this.templateSubmitButton = document.getElementById('agent-modal-submit-template-btn');
    this.foundryPlaceholderInstructions = 'Placeholder instructions: Azure AI Foundry agent manages its own prompt.';
    this.instructionsEditor = null;
    this.foundryEndpoints = [];
    this.foundryAgents = [];
    this.assignedKnowledgeCatalog = { sources: [], documents: [], tags: [] };
    this.assignedKnowledgeCatalogLoaded = false;
    this.pendingAssignedKnowledge = this.cloneAssignedKnowledge(EMPTY_ASSIGNED_KNOWLEDGE);
    
    this.bindEvents();

    if (this.templateSubmitButton) {
      this.templateSubmitButton.addEventListener('click', () => this.submitTemplate());
    }
  }

  bindEvents() {
    // Step navigation buttons
    const nextBtn = document.getElementById('agent-modal-next');
    const prevBtn = document.getElementById('agent-modal-prev');
    const saveBtn = document.getElementById('agent-modal-save-btn');
    const skipBtn = document.getElementById('agent-modal-skip');
    const powerUserToggle = document.getElementById('agent-power-user-toggle');
    const agentTypeRadios = document.querySelectorAll('input[name="agent-type"]');
    const draftInstructionsBtn = document.getElementById('agent-draft-instructions-btn');
    
    if (nextBtn) {
      nextBtn.addEventListener('click', () => this.nextStep());
    }
    if (prevBtn) {
      prevBtn.addEventListener('click', () => this.prevStep());
    }
    if (saveBtn) {
      saveBtn.addEventListener('click', () => this.saveAgent());
    }
    if (skipBtn) {
      skipBtn.addEventListener('click', () => this.skipToEnd());
    }
    if (powerUserToggle) {
      powerUserToggle.addEventListener('change', (e) => this.togglePowerUserMode(e.target.checked));
    }
    if (draftInstructionsBtn) {
      draftInstructionsBtn.addEventListener('click', () => this.draftInstructions());
    }

    if (agentTypeRadios && agentTypeRadios.length) {
      agentTypeRadios.forEach(r => {
        r.addEventListener('change', (e) => this.handleAgentTypeChange(e.target.value));
      });
    }

    const agentModal = document.getElementById('agentModal');
    if (agentModal) {
      agentModal.addEventListener('shown.bs.modal', () => {
        this.initializeInstructionsEditor();
        this.initializeVoiceControls();
        this.refreshInstructionsEditor(this.currentStep === 3 && !this.isAnyFoundryType());
      });
    }

    const foundryEndpointSelect = document.getElementById('agent-foundry-endpoint-select');
    const foundryFetchBtn = document.getElementById('agent-foundry-fetch-btn');
    const foundryAgentSelect = document.getElementById('agent-foundry-agent-select');
    if (foundryEndpointSelect) {
      foundryEndpointSelect.addEventListener('change', () => this.applyFoundryEndpointSelection());
    }
    if (foundryFetchBtn) {
      foundryFetchBtn.addEventListener('click', () => this.fetchFoundryAgents());
    }
    if (foundryAgentSelect) {
      foundryAgentSelect.addEventListener('change', () => this.applyFoundryAgentSelection());
    }

    const assignedKnowledgeToggle = document.getElementById('agent-assigned-knowledge-enabled');
    const assignedKnowledgeRefresh = document.getElementById('agent-assigned-knowledge-refresh');
    const assignedKnowledgeUserContextToggle = document.getElementById('agent-assigned-knowledge-user-context-enabled');
    const assignedKnowledgeWebSourceAdd = document.getElementById('agent-assigned-knowledge-web-source-add');
    const assignedKnowledgeWebSourceInput = document.getElementById('agent-assigned-knowledge-web-source-input');
    if (assignedKnowledgeToggle) {
      assignedKnowledgeToggle.addEventListener('change', () => this.handleAssignedKnowledgeToggle());
    }
    if (assignedKnowledgeRefresh) {
      assignedKnowledgeRefresh.addEventListener('click', () => this.loadAssignedKnowledgeCatalog({ force: true }));
    }
    if (assignedKnowledgeUserContextToggle) {
      assignedKnowledgeUserContextToggle.addEventListener('change', () => this.handleAssignedKnowledgeUserContextToggle());
    }
    document.querySelectorAll('.agent-assigned-knowledge-user-action').forEach(actionCheckbox => {
      actionCheckbox.addEventListener('change', () => this.handleAssignedKnowledgeUserActionChange());
    });
    if (assignedKnowledgeWebSourceAdd) {
      assignedKnowledgeWebSourceAdd.addEventListener('click', () => this.handleAssignedKnowledgeWebSourceAdd());
    }
    if (assignedKnowledgeWebSourceInput) {
      assignedKnowledgeWebSourceInput.addEventListener('keydown', event => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          this.handleAssignedKnowledgeWebSourceAdd();
        }
      });
    }

    [
      'agent-assigned-knowledge-source-available-search',
      'agent-assigned-knowledge-source-selected-search',
      'agent-assigned-knowledge-tag-available-search',
      'agent-assigned-knowledge-tag-selected-search',
      'agent-assigned-knowledge-document-available-search',
      'agent-assigned-knowledge-document-selected-search'
    ].forEach(inputId => {
      const input = document.getElementById(inputId);
      if (input) {
        input.addEventListener('input', () => this.renderAssignedKnowledgeCatalog());
      }
    });

    this.initializeAssignedKnowledgeDropZones();
    
    // Set up display name to generated name conversion
    this.setupNameGeneration();
    
    // Set up model change listener for reasoning effort
    this.setupModelChangeListener();
  }

  cloneAssignedKnowledge(value) {
    return JSON.parse(JSON.stringify(value || EMPTY_ASSIGNED_KNOWLEDGE));
  }

  getAssignedKnowledgeAgentScope() {
    if (this.isAdmin) {
      return 'global';
    }
    if (this.workspaceScope === 'group') {
      return 'group';
    }
    return 'personal';
  }

  normalizeAssignedKnowledge(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return this.cloneAssignedKnowledge(EMPTY_ASSIGNED_KNOWLEDGE);
    }

    const scopes = value.scopes && typeof value.scopes === 'object' && !Array.isArray(value.scopes)
      ? value.scopes
      : {};
    return {
      enabled: Boolean(value.enabled),
      scopes: {
        personal: Boolean(scopes.personal || value.personal),
        group_ids: this.normalizeStringArray(scopes.group_ids || value.group_ids),
        public_workspace_ids: this.normalizeStringArray(scopes.public_workspace_ids || value.public_workspace_ids)
      },
      document_ids: this.normalizeStringArray(value.document_ids || value.selected_document_ids),
      tags: this.normalizeStringArray(value.tags),
      web_sources: this.normalizeAssignedKnowledgeWebSources(value.web_sources),
      allow_user_workspace_context: Boolean(value.allow_user_workspace_context),
      allowed_user_workspace_actions: this.normalizeAssignedKnowledgeUserActions(
        value.allowed_user_workspace_actions ?? value.allowed_user_context_actions
      )
    };
  }

  normalizeAssignedKnowledgeWebSourceMode(value) {
    const mode = String(value || '').trim().toLowerCase();
    if (mode === 'deep' || mode === 'deep-research' || mode === 'research') {
      return 'deep_research';
    }
    return ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODES.includes(mode) ? mode : 'url_review';
  }

  normalizeAssignedKnowledgeUrl(value) {
    const rawUrl = String(value || '').trim();
    if (!rawUrl) {
      return '';
    }
    try {
      const parsedUrl = new URL(rawUrl);
      if (!['http:', 'https:'].includes(parsedUrl.protocol) || !parsedUrl.hostname) {
        return '';
      }
      parsedUrl.hash = '';
      if (!parsedUrl.pathname) {
        parsedUrl.pathname = '/';
      }
      return parsedUrl.toString();
    } catch (error) {
      return '';
    }
  }

  normalizeAssignedKnowledgeWebSources(value) {
    let entries = [];
    let defaultMode = 'url_review';
    if (typeof value === 'string') {
      entries = value.replaceAll(',', '\n').split(/\s+/);
    } else if (Array.isArray(value)) {
      entries = value;
    } else if (value && typeof value === 'object') {
      entries = Array.isArray(value.sources) ? value.sources : value.urls;
      defaultMode = this.normalizeAssignedKnowledgeWebSourceMode(value.mode || (value.deep_research ? 'deep_research' : 'url_review'));
    }

    if (typeof entries === 'string') {
      entries = entries.replaceAll(',', '\n').split(/\s+/);
    }

    const webSourcesByUrl = new Map();
    (Array.isArray(entries) ? entries : []).forEach(entry => {
      let rawUrl = entry;
      let mode = defaultMode;
      if (entry && typeof entry === 'object') {
        rawUrl = entry.url || entry.href || entry.link;
        mode = entry.deep_research ? 'deep_research' : this.normalizeAssignedKnowledgeWebSourceMode(entry.mode || defaultMode);
      }
      const normalizedUrl = this.normalizeAssignedKnowledgeUrl(rawUrl);
      if (!normalizedUrl) {
        return;
      }
      const existing = webSourcesByUrl.get(normalizedUrl);
      if (!existing || mode === 'deep_research') {
        webSourcesByUrl.set(normalizedUrl, { url: normalizedUrl, mode });
      }
    });

    return Array.from(webSourcesByUrl.values());
  }

  normalizeAssignedKnowledgeUserActions(value) {
    if (value === null || value === undefined) {
      return [...ASSIGNED_KNOWLEDGE_USER_ACTIONS];
    }
    const actions = this.normalizeStringArray(value).map(action => {
      const normalizedAction = action.toLowerCase();
      return normalizedAction === 'comparison' ? 'compare' : normalizedAction;
    });
    return actions.filter(action => ASSIGNED_KNOWLEDGE_USER_ACTIONS.includes(action));
  }

  normalizeStringArray(value) {
    if (!value) {
      return [];
    }
    const candidates = Array.isArray(value) ? value : [value];
    const seen = new Set();
    const normalized = [];
    candidates.forEach(item => {
      const text = String(item || '').trim();
      if (!text || seen.has(text)) {
        return;
      }
      seen.add(text);
      normalized.push(text);
    });
    return normalized;
  }

  getAssignedKnowledgeSourceKey(scope, id) {
    return `${scope}:${id || scope}`;
  }

  getCatalogSourceKey(source) {
    const sourceScope = String(source?.scope || '').trim();
    const sourceId = String(source?.id || sourceScope || '').trim();
    return this.getAssignedKnowledgeSourceKey(sourceScope, sourceId);
  }

  getCatalogDocumentSourceKey(documentItem) {
    return this.getAssignedKnowledgeSourceKey(documentItem?.scope, documentItem?.source_id);
  }

  getAssignedKnowledgeSelectedSourceKeys(config = this.pendingAssignedKnowledge) {
    const scopes = config.scopes || {};
    const keys = new Set();
    if (scopes.personal) {
      keys.add(this.getAssignedKnowledgeSourceKey('personal', 'personal'));
    }
    (scopes.group_ids || []).forEach(groupId => keys.add(this.getAssignedKnowledgeSourceKey('group', groupId)));
    (scopes.public_workspace_ids || []).forEach(workspaceId => keys.add(this.getAssignedKnowledgeSourceKey('public', workspaceId)));
    return keys;
  }

  getAssignedKnowledgeSourceByKey(sourceKey) {
    const normalizedKey = String(sourceKey || '').trim();
    return (this.assignedKnowledgeCatalog.sources || []).find(source => this.getCatalogSourceKey(source) === normalizedKey) || null;
  }

  getAssignedKnowledgeDocumentById(documentId) {
    const normalizedId = String(documentId || '').trim();
    return (this.assignedKnowledgeCatalog.documents || []).find(documentItem => String(documentItem.id || '') === normalizedId) || null;
  }

  getAssignedKnowledgeSearchText(inputId) {
    return String(document.getElementById(inputId)?.value || '').trim().toLowerCase();
  }

  matchesAssignedKnowledgeSearch(values, searchText) {
    const query = String(searchText || '').trim().toLowerCase();
    if (!query) {
      return true;
    }
    const haystack = values.map(value => String(value || '').toLowerCase()).join(' ');
    return query.split(/\s+/).every(token => haystack.includes(token));
  }

  setAssignedKnowledgeControls(config) {
    this.pendingAssignedKnowledge = this.normalizeAssignedKnowledge(config);
    const toggle = document.getElementById('agent-assigned-knowledge-enabled');
    if (toggle) {
      toggle.checked = Boolean(this.pendingAssignedKnowledge.enabled);
    }
    this.syncAssignedKnowledgeUserContextControls();
    this.renderAssignedKnowledgeWebSources();
    this.toggleAssignedKnowledgeControls(Boolean(this.pendingAssignedKnowledge.enabled));
    if (this.assignedKnowledgeCatalogLoaded) {
      this.renderAssignedKnowledgeCatalog();
    }
  }

  resetAssignedKnowledgeControls() {
    this.assignedKnowledgeCatalogLoaded = false;
    this.assignedKnowledgeCatalog = { sources: [], documents: [], tags: [] };
    this.pendingAssignedKnowledge = this.cloneAssignedKnowledge(EMPTY_ASSIGNED_KNOWLEDGE);
    const toggle = document.getElementById('agent-assigned-knowledge-enabled');
    if (toggle) {
      toggle.checked = false;
    }
    this.syncAssignedKnowledgeUserContextControls();
    this.toggleAssignedKnowledgeControls(false);
    [
      'agent-assigned-knowledge-source-available',
      'agent-assigned-knowledge-source-selected',
      'agent-assigned-knowledge-tag-available',
      'agent-assigned-knowledge-tag-selected',
      'agent-assigned-knowledge-document-available',
      'agent-assigned-knowledge-document-selected',
      'agent-assigned-knowledge-resolved-documents'
    ].forEach(elementId => {
      const element = document.getElementById(elementId);
      if (element) {
        element.textContent = '';
      }
    });
    const webSourceInput = document.getElementById('agent-assigned-knowledge-web-source-input');
    if (webSourceInput) {
      webSourceInput.value = '';
    }
    [
      'agent-assigned-knowledge-source-available-search',
      'agent-assigned-knowledge-source-selected-search',
      'agent-assigned-knowledge-tag-available-search',
      'agent-assigned-knowledge-tag-selected-search',
      'agent-assigned-knowledge-document-available-search',
      'agent-assigned-knowledge-document-selected-search'
    ].forEach(inputId => {
      const input = document.getElementById(inputId);
      if (input) {
        input.value = '';
      }
    });
    const documentsSelect = document.getElementById('agent-assigned-knowledge-documents');
    if (documentsSelect) {
      documentsSelect.textContent = '';
    }
    this.renderAssignedKnowledgeWebSources();
    this.updateAssignedKnowledgeCounts();
  }

  syncAssignedKnowledgeUserContextControls() {
    const userContextToggle = document.getElementById('agent-assigned-knowledge-user-context-enabled');
    const userActionControls = document.getElementById('agent-assigned-knowledge-user-action-controls');
    const allowUserContext = Boolean(this.pendingAssignedKnowledge?.allow_user_workspace_context);
    const selectedActions = new Set(this.pendingAssignedKnowledge?.allowed_user_workspace_actions ?? ASSIGNED_KNOWLEDGE_USER_ACTIONS);

    if (userContextToggle) {
      userContextToggle.checked = allowUserContext;
    }
    if (userActionControls) {
      userActionControls.classList.toggle('d-none', !allowUserContext);
    }
    document.querySelectorAll('.agent-assigned-knowledge-user-action').forEach(actionCheckbox => {
      const action = String(actionCheckbox.value || '').trim().toLowerCase();
      actionCheckbox.checked = selectedActions.has(action);
      actionCheckbox.disabled = !allowUserContext;
    });
  }

  getAssignedKnowledgeSelectedUserActions() {
    const selectedActions = Array.from(document.querySelectorAll('.agent-assigned-knowledge-user-action:checked'))
      .map(actionCheckbox => String(actionCheckbox.value || '').trim().toLowerCase())
      .filter(action => ASSIGNED_KNOWLEDGE_USER_ACTIONS.includes(action));
    return selectedActions;
  }

  handleAssignedKnowledgeUserContextToggle() {
    const allowUserContext = Boolean(document.getElementById('agent-assigned-knowledge-user-context-enabled')?.checked);
    this.pendingAssignedKnowledge = this.normalizeAssignedKnowledge({
      ...this.pendingAssignedKnowledge,
      allow_user_workspace_context: allowUserContext,
      allowed_user_workspace_actions: this.getAssignedKnowledgeSelectedUserActions()
    });
    this.syncAssignedKnowledgeUserContextControls();
    this.syncAssignedKnowledgeToAdditionalSettings();
  }

  handleAssignedKnowledgeUserActionChange() {
    this.pendingAssignedKnowledge = this.normalizeAssignedKnowledge({
      ...this.pendingAssignedKnowledge,
      allowed_user_workspace_actions: this.getAssignedKnowledgeSelectedUserActions()
    });
    this.syncAssignedKnowledgeUserContextControls();
    this.syncAssignedKnowledgeToAdditionalSettings();
  }

  getAssignedKnowledgeWebSourceModeLabel(mode) {
    return this.normalizeAssignedKnowledgeWebSourceMode(mode) === 'deep_research'
      ? 'Deep Research'
      : 'Review URL';
  }

  getAssignedKnowledgeWebSourceInputUrls() {
    const input = document.getElementById('agent-assigned-knowledge-web-source-input');
    const text = String(input?.value || '').trim();
    if (!text) {
      return [];
    }
    return text
      .replaceAll(',', '\n')
      .split(/\s+/)
      .map(candidate => this.normalizeAssignedKnowledgeUrl(candidate))
      .filter(Boolean);
  }

  handleAssignedKnowledgeWebSourceAdd() {
    const urls = this.getAssignedKnowledgeWebSourceInputUrls();
    if (!urls.length) {
      showToast('Enter at least one valid http or https URL.', 'warning');
      return;
    }
    const mode = this.normalizeAssignedKnowledgeWebSourceMode(
      document.getElementById('agent-assigned-knowledge-web-source-mode')?.value
    );
    const webSources = this.normalizeAssignedKnowledgeWebSources([
      ...(this.pendingAssignedKnowledge.web_sources || []),
      ...urls.map(url => ({ url, mode }))
    ]);
    this.pendingAssignedKnowledge = this.normalizeAssignedKnowledge({
      ...this.pendingAssignedKnowledge,
      web_sources: webSources
    });
    const input = document.getElementById('agent-assigned-knowledge-web-source-input');
    if (input) {
      input.value = '';
    }
    this.renderAssignedKnowledgeWebSources();
    this.syncAssignedKnowledgeToAdditionalSettings();
  }

  removeAssignedKnowledgeWebSource(url) {
    const normalizedUrl = this.normalizeAssignedKnowledgeUrl(url);
    const webSources = (this.pendingAssignedKnowledge.web_sources || [])
      .filter(source => source.url !== normalizedUrl);
    this.pendingAssignedKnowledge = this.normalizeAssignedKnowledge({
      ...this.pendingAssignedKnowledge,
      web_sources: webSources
    });
    this.renderAssignedKnowledgeWebSources();
    this.syncAssignedKnowledgeToAdditionalSettings();
  }

  updateAssignedKnowledgeWebSourceMode(url, mode) {
    const normalizedUrl = this.normalizeAssignedKnowledgeUrl(url);
    const normalizedMode = this.normalizeAssignedKnowledgeWebSourceMode(mode);
    const webSources = (this.pendingAssignedKnowledge.web_sources || []).map(source => ({
      ...source,
      mode: source.url === normalizedUrl ? normalizedMode : source.mode
    }));
    this.pendingAssignedKnowledge = this.normalizeAssignedKnowledge({
      ...this.pendingAssignedKnowledge,
      web_sources: webSources
    });
    this.renderAssignedKnowledgeWebSources();
    this.syncAssignedKnowledgeToAdditionalSettings();
  }

  renderAssignedKnowledgeWebSources() {
    const container = document.getElementById('agent-assigned-knowledge-web-source-list');
    if (!container) {
      return;
    }
    container.textContent = '';
    const webSources = this.pendingAssignedKnowledge.web_sources || [];
    if (!webSources.length) {
      const empty = document.createElement('div');
      empty.className = 'agent-assigned-knowledge-empty-list';
      empty.textContent = 'No assigned URLs selected';
      container.appendChild(empty);
      this.updateAssignedKnowledgeCounts();
      return;
    }

    webSources.forEach(source => {
      const row = document.createElement('div');
      row.className = 'agent-assigned-knowledge-web-source-item';

      const content = document.createElement('div');
      content.className = 'agent-assigned-knowledge-item-content flex-grow-1';
      const title = document.createElement('div');
      title.className = 'agent-assigned-knowledge-item-title fw-semibold';
      title.textContent = source.url;
      const meta = document.createElement('div');
      meta.className = 'agent-assigned-knowledge-item-meta';
      meta.textContent = this.getAssignedKnowledgeWebSourceModeLabel(source.mode);
      content.appendChild(title);
      content.appendChild(meta);

      const controls = document.createElement('div');
      controls.className = 'd-flex align-items-center gap-2 flex-shrink-0';
      const modeSelect = document.createElement('select');
      modeSelect.className = 'form-select form-select-sm';
      modeSelect.setAttribute('aria-label', 'Assigned web source review mode');
      ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODES.forEach(mode => {
        const option = document.createElement('option');
        option.value = mode;
        option.textContent = this.getAssignedKnowledgeWebSourceModeLabel(mode);
        option.selected = this.normalizeAssignedKnowledgeWebSourceMode(source.mode) === mode;
        modeSelect.appendChild(option);
      });
      modeSelect.addEventListener('change', () => this.updateAssignedKnowledgeWebSourceMode(source.url, modeSelect.value));

      const removeButton = document.createElement('button');
      removeButton.type = 'button';
      removeButton.className = 'btn btn-outline-danger btn-sm';
      removeButton.title = 'Remove assigned URL';
      removeButton.setAttribute('aria-label', 'Remove assigned URL');
      const removeIcon = document.createElement('i');
      removeIcon.className = 'bi bi-x-lg';
      removeButton.appendChild(removeIcon);
      removeButton.addEventListener('click', () => this.removeAssignedKnowledgeWebSource(source.url));

      controls.appendChild(modeSelect);
      controls.appendChild(removeButton);
      row.appendChild(content);
      row.appendChild(controls);
      container.appendChild(row);
    });
    this.updateAssignedKnowledgeCounts();
  }

  handleAssignedKnowledgeToggle() {
    const enabled = Boolean(document.getElementById('agent-assigned-knowledge-enabled')?.checked);
    this.pendingAssignedKnowledge = this.normalizeAssignedKnowledge({
      ...this.pendingAssignedKnowledge,
      enabled
    });
    this.toggleAssignedKnowledgeControls(enabled);
    if (enabled) {
      this.loadAssignedKnowledgeCatalog();
    } else {
      this.renderAssignedKnowledgeCatalog();
    }
    this.syncAssignedKnowledgeUserContextControls();
    this.renderAssignedKnowledgeWebSources();
    this.syncAssignedKnowledgeToAdditionalSettings();
  }

  toggleAssignedKnowledgeControls(enabled) {
    const controls = document.getElementById('agent-assigned-knowledge-controls');
    if (controls) {
      controls.classList.toggle('d-none', !enabled);
    }
  }

  async loadAssignedKnowledgeCatalog({ force = false } = {}) {
    if (this.assignedKnowledgeCatalogLoaded && !force) {
      this.renderAssignedKnowledgeCatalog();
      return;
    }

    const loading = document.getElementById('agent-assigned-knowledge-loading');
    if (loading) {
      loading.classList.remove('d-none');
    }

    try {
      const scope = this.getAssignedKnowledgeAgentScope();
      const response = await fetch(`/api/agents/assigned-knowledge/catalog?agent_scope=${encodeURIComponent(scope)}`);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || 'Unable to load assigned knowledge sources.');
      }
      this.assignedKnowledgeCatalog = {
        sources: Array.isArray(payload.sources) ? payload.sources : [],
        documents: Array.isArray(payload.documents) ? payload.documents : [],
        tags: Array.isArray(payload.tags) ? payload.tags : []
      };
      this.assignedKnowledgeCatalogLoaded = true;
      this.renderAssignedKnowledgeCatalog();
    } catch (error) {
      console.error('Failed to load assigned knowledge catalog:', error);
      this.showError(error.message || 'Unable to load assigned knowledge sources.');
    } finally {
      if (loading) {
        loading.classList.add('d-none');
      }
    }
  }

  renderAssignedKnowledgeCatalog() {
    this.ensureSourcesForSelectedAssignedDocuments();
    this.ensureDefaultAssignedKnowledgeSource();
    this.pruneAssignedKnowledgeSelections();
    this.renderAssignedKnowledgeSources();
    this.renderAssignedKnowledgeDocuments();
    this.renderAssignedKnowledgeTags();
    this.renderAssignedKnowledgeWebSources();
    this.renderAssignedKnowledgeResolvedDocuments();
    this.updateAssignedKnowledgeCounts();
    const empty = document.getElementById('agent-assigned-knowledge-empty');
    if (empty) {
      empty.classList.toggle('d-none', (this.assignedKnowledgeCatalog.sources || []).length > 0);
    }
  }

  renderAssignedKnowledgeSources() {
    const selectedKeys = this.getAssignedKnowledgeSelectedSourceKeys(this.pendingAssignedKnowledge);
    const availableSearch = this.getAssignedKnowledgeSearchText('agent-assigned-knowledge-source-available-search');
    const selectedSearch = this.getAssignedKnowledgeSearchText('agent-assigned-knowledge-source-selected-search');
    const sources = this.assignedKnowledgeCatalog.sources || [];
    const availableSources = sources.filter(source => {
      const sourceKey = this.getCatalogSourceKey(source);
      return !selectedKeys.has(sourceKey) && this.matchesAssignedKnowledgeSearch([
        source.label,
        source.id,
        source.scope
      ], availableSearch);
    });
    const selectedSources = sources.filter(source => {
      const sourceKey = this.getCatalogSourceKey(source);
      return selectedKeys.has(sourceKey) && this.matchesAssignedKnowledgeSearch([
        source.label,
        source.id,
        source.scope
      ], selectedSearch);
    });

    this.renderAssignedKnowledgeTransferItems('agent-assigned-knowledge-source-available', availableSources, {
      category: 'source',
      listRole: 'available',
      emptyText: 'No available source workspaces',
      getKey: source => this.getCatalogSourceKey(source),
      renderContent: source => this.createAssignedKnowledgeSourceContent(source)
    });
    this.renderAssignedKnowledgeTransferItems('agent-assigned-knowledge-source-selected', selectedSources, {
      category: 'source',
      listRole: 'selected',
      emptyText: 'No selected source workspaces',
      getKey: source => this.getCatalogSourceKey(source),
      renderContent: source => this.createAssignedKnowledgeSourceContent(source)
    });
  }

  createAssignedKnowledgeSourceContent(source) {
    const content = document.createElement('div');
    content.className = 'agent-assigned-knowledge-item-content flex-grow-1';

    const title = document.createElement('div');
    title.className = 'agent-assigned-knowledge-item-title fw-medium';
    title.textContent = source.label || source.id || source.scope || 'Knowledge source';

    const meta = document.createElement('div');
    meta.className = 'agent-assigned-knowledge-item-meta';
    meta.textContent = source.scope || 'source';

    content.appendChild(title);
    content.appendChild(meta);
    return content;
  }

  ensureDefaultAssignedKnowledgeSource() {
    const toggle = document.getElementById('agent-assigned-knowledge-enabled');
    const selectedKeys = this.getAssignedKnowledgeSelectedSourceKeys(this.pendingAssignedKnowledge);
    const sources = this.assignedKnowledgeCatalog.sources || [];
    if (!toggle?.checked || selectedKeys.size || this.workspaceScope !== 'group' || sources.length !== 1) {
      return;
    }
    this.updateAssignedKnowledgeSourceSelection(this.getCatalogSourceKey(sources[0]), true, { skipRender: true });
  }

  renderAssignedKnowledgeDocuments() {
    const selectedIds = new Set(this.pendingAssignedKnowledge.document_ids || []);
    const selectedSourceKeys = this.getCheckedAssignedKnowledgeSourceKeys();
    const availableSearch = this.getAssignedKnowledgeSearchText('agent-assigned-knowledge-document-available-search');
    const selectedSearch = this.getAssignedKnowledgeSearchText('agent-assigned-knowledge-document-selected-search');
    const documents = this.assignedKnowledgeCatalog.documents || [];
    const selectableDocuments = documents.filter(documentItem => {
      const sourceKey = this.getCatalogDocumentSourceKey(documentItem);
      return !selectedSourceKeys.size || selectedSourceKeys.has(sourceKey) || selectedIds.has(documentItem.id);
    });
    const availableDocuments = selectableDocuments.filter(documentItem => {
      return !selectedIds.has(documentItem.id) && this.matchesAssignedKnowledgeSearch([
        documentItem.title,
        documentItem.file_name,
        documentItem.source_name,
        documentItem.scope,
        ...(documentItem.tags || [])
      ], availableSearch);
    });
    const selectedDocuments = documents.filter(documentItem => {
      return selectedIds.has(documentItem.id) && this.matchesAssignedKnowledgeSearch([
        documentItem.title,
        documentItem.file_name,
        documentItem.source_name,
        documentItem.scope,
        ...(documentItem.tags || [])
      ], selectedSearch);
    });

    this.renderAssignedKnowledgeDocumentsSelect(selectableDocuments);
    this.renderAssignedKnowledgeTransferItems('agent-assigned-knowledge-document-available', availableDocuments, {
      category: 'document',
      listRole: 'available',
      emptyText: 'No available documents',
      getKey: documentItem => documentItem.id || '',
      renderContent: documentItem => this.createAssignedKnowledgeDocumentContent(documentItem)
    });
    this.renderAssignedKnowledgeTransferItems('agent-assigned-knowledge-document-selected', selectedDocuments, {
      category: 'document',
      listRole: 'selected',
      emptyText: 'No specific documents',
      getKey: documentItem => documentItem.id || '',
      renderContent: documentItem => this.createAssignedKnowledgeDocumentContent(documentItem)
    });
  }

  renderAssignedKnowledgeDocumentsSelect(documents) {
    const select = document.getElementById('agent-assigned-knowledge-documents');
    if (!select) {
      return;
    }
    const selectedIds = new Set(this.pendingAssignedKnowledge.document_ids || []);
    select.textContent = '';

    (documents || []).forEach(documentItem => {
      const option = document.createElement('option');
      option.value = documentItem.id || '';
      option.dataset.scope = documentItem.scope || '';
      option.dataset.sourceId = documentItem.source_id || '';
      option.dataset.sourceKey = this.getCatalogDocumentSourceKey(documentItem);
      option.textContent = `${documentItem.title || documentItem.file_name || 'Untitled document'} (${documentItem.source_name || documentItem.scope || 'source'})`;
      option.selected = selectedIds.has(option.value);
      select.appendChild(option);
    });
  }

  createAssignedKnowledgeDocumentContent(documentItem) {
    const content = document.createElement('div');
    content.className = 'agent-assigned-knowledge-item-content flex-grow-1';

    const title = document.createElement('div');
    title.className = 'agent-assigned-knowledge-item-title fw-medium';
    title.textContent = documentItem.title || documentItem.file_name || 'Untitled document';

    const meta = document.createElement('div');
    meta.className = 'agent-assigned-knowledge-item-meta';
    meta.textContent = documentItem.source_name || documentItem.scope || 'source';

    content.appendChild(title);
    content.appendChild(meta);
    this.appendAssignedKnowledgeTagBadges(content, documentItem.tags || []);
    return content;
  }

  appendAssignedKnowledgeTagBadges(container, tags, badgeClass = 'text-bg-light') {
    const visibleTags = (tags || []).slice(0, 3);
    if (!visibleTags.length) {
      return;
    }
    const badgeRow = document.createElement('div');
    badgeRow.className = 'd-flex flex-wrap gap-1 mt-1';
    visibleTags.forEach(tag => {
      const badge = document.createElement('span');
      badge.className = `badge ${badgeClass}`;
      badge.textContent = tag;
      badgeRow.appendChild(badge);
    });
    if ((tags || []).length > visibleTags.length) {
      const more = document.createElement('span');
      more.className = `badge ${badgeClass}`;
      more.textContent = `+${tags.length - visibleTags.length}`;
      badgeRow.appendChild(more);
    }
    container.appendChild(badgeRow);
  }

  renderAssignedKnowledgeTags() {
    const selectedTags = new Set(this.pendingAssignedKnowledge.tags || []);
    const selectedSourceKeys = this.getAssignedKnowledgeSelectedSourceKeys(this.pendingAssignedKnowledge);
    const availableSearch = this.getAssignedKnowledgeSearchText('agent-assigned-knowledge-tag-available-search');
    const selectedSearch = this.getAssignedKnowledgeSearchText('agent-assigned-knowledge-tag-selected-search');
    const tagMap = new Map();
    (this.assignedKnowledgeCatalog.documents || []).forEach(documentItem => {
      const sourceKey = this.getCatalogDocumentSourceKey(documentItem);
      if (selectedSourceKeys.size && !selectedSourceKeys.has(sourceKey)) {
        return;
      }
      (documentItem.tags || []).forEach(tag => {
        const tagName = String(tag || '').trim();
        if (!tagName) {
          return;
        }
        const existing = tagMap.get(tagName) || { name: tagName, count: 0 };
        existing.count += 1;
        tagMap.set(tagName, existing);
      });
    });
    selectedTags.forEach(tagName => {
      if (tagName && !tagMap.has(tagName)) {
        tagMap.set(tagName, { name: tagName, count: 0 });
      }
    });
    const tags = Array.from(tagMap.values()).sort((left, right) => left.name.localeCompare(right.name));
    const availableTags = tags.filter(tag => !selectedTags.has(tag.name) && this.matchesAssignedKnowledgeSearch([tag.name], availableSearch));
    const selectedTagItems = tags.filter(tag => selectedTags.has(tag.name) && this.matchesAssignedKnowledgeSearch([tag.name], selectedSearch));

    this.renderAssignedKnowledgeTransferItems('agent-assigned-knowledge-tag-available', availableTags, {
      category: 'tag',
      listRole: 'available',
      emptyText: 'No available tags',
      getKey: tag => tag.name,
      renderContent: tag => this.createAssignedKnowledgeTagContent(tag)
    });
    this.renderAssignedKnowledgeTransferItems('agent-assigned-knowledge-tag-selected', selectedTagItems, {
      category: 'tag',
      listRole: 'selected',
      emptyText: 'No selected tag limits',
      getKey: tag => tag.name,
      renderContent: tag => this.createAssignedKnowledgeTagContent(tag)
    });
  }

  createAssignedKnowledgeTagContent(tag) {
    const content = document.createElement('div');
    content.className = 'agent-assigned-knowledge-item-content flex-grow-1';

    const title = document.createElement('div');
    title.className = 'agent-assigned-knowledge-item-title fw-medium';
    title.textContent = tag.name || 'Tag';

    const meta = document.createElement('div');
    meta.className = 'agent-assigned-knowledge-item-meta';
    meta.textContent = tag.count ? `${tag.count} document${tag.count === 1 ? '' : 's'}` : 'tag';

    content.appendChild(title);
    content.appendChild(meta);
    return content;
  }

  getCheckedAssignedKnowledgeSourceKeys() {
    return this.getAssignedKnowledgeSelectedSourceKeys(this.pendingAssignedKnowledge);
  }

  ensureSourcesForSelectedAssignedDocuments() {
    (this.pendingAssignedKnowledge.document_ids || []).forEach(documentId => {
      const documentItem = this.getAssignedKnowledgeDocumentById(documentId);
      if (documentItem) {
        this.updateAssignedKnowledgeSourceSelection(this.getCatalogDocumentSourceKey(documentItem), true, { skipRender: true });
      }
    });
  }

  pruneAssignedKnowledgeSelections() {
    const sourceKeys = new Set((this.assignedKnowledgeCatalog.sources || []).map(source => this.getCatalogSourceKey(source)));
    const selectedSourceKeys = this.getAssignedKnowledgeSelectedSourceKeys(this.pendingAssignedKnowledge);
    const validSelectedSourceKeys = new Set(Array.from(selectedSourceKeys).filter(sourceKey => sourceKeys.has(sourceKey)));
    this.pendingAssignedKnowledge.scopes = this.buildAssignedKnowledgeScopesFromSourceKeys(validSelectedSourceKeys);

    const availableDocumentIds = new Set((this.assignedKnowledgeCatalog.documents || []).map(documentItem => String(documentItem.id || '')));
    this.pendingAssignedKnowledge.document_ids = (this.pendingAssignedKnowledge.document_ids || []).filter(documentId => {
      if (!availableDocumentIds.has(documentId)) {
        return false;
      }
      const documentItem = this.getAssignedKnowledgeDocumentById(documentId);
      return !documentItem || validSelectedSourceKeys.has(this.getCatalogDocumentSourceKey(documentItem));
    });
    this.pendingAssignedKnowledge.tags = this.normalizeStringArray(this.pendingAssignedKnowledge.tags);
  }

  buildAssignedKnowledgeScopesFromSourceKeys(sourceKeys) {
    const scopes = {
      personal: false,
      group_ids: [],
      public_workspace_ids: []
    };
    Array.from(sourceKeys || []).forEach(sourceKey => {
      const source = this.getAssignedKnowledgeSourceByKey(sourceKey);
      if (!source) {
        return;
      }
      const sourceScope = String(source.scope || '').trim();
      const sourceId = String(source.id || sourceScope || '').trim();
      if (sourceScope === 'personal') {
        scopes.personal = true;
      } else if (sourceScope === 'group' && sourceId) {
        scopes.group_ids.push(sourceId);
      } else if (sourceScope === 'public' && sourceId) {
        scopes.public_workspace_ids.push(sourceId);
      }
    });
    scopes.group_ids = this.normalizeStringArray(scopes.group_ids);
    scopes.public_workspace_ids = this.normalizeStringArray(scopes.public_workspace_ids);
    return scopes;
  }

  updateAssignedKnowledgeSourceSelection(sourceKey, selected, { skipRender = false } = {}) {
    const selectedKeys = this.getAssignedKnowledgeSelectedSourceKeys(this.pendingAssignedKnowledge);
    if (selected) {
      selectedKeys.add(sourceKey);
    } else {
      selectedKeys.delete(sourceKey);
    }
    this.pendingAssignedKnowledge.scopes = this.buildAssignedKnowledgeScopesFromSourceKeys(selectedKeys);

    if (!selected) {
      this.pendingAssignedKnowledge.document_ids = (this.pendingAssignedKnowledge.document_ids || []).filter(documentId => {
        const documentItem = this.getAssignedKnowledgeDocumentById(documentId);
        return !documentItem || this.getCatalogDocumentSourceKey(documentItem) !== sourceKey;
      });
    }

    if (!skipRender) {
      this.renderAssignedKnowledgeCatalog();
      this.syncAssignedKnowledgeToAdditionalSettings();
    }
  }

  updateAssignedKnowledgeTagSelection(tagName, selected, { skipRender = false } = {}) {
    const tags = new Set(this.pendingAssignedKnowledge.tags || []);
    const normalizedTag = String(tagName || '').trim();
    if (!normalizedTag) {
      return;
    }
    if (selected) {
      tags.add(normalizedTag);
    } else {
      tags.delete(normalizedTag);
    }
    this.pendingAssignedKnowledge.tags = this.normalizeStringArray(Array.from(tags));

    if (!skipRender) {
      this.renderAssignedKnowledgeCatalog();
      this.syncAssignedKnowledgeToAdditionalSettings();
    }
  }

  updateAssignedKnowledgeDocumentSelection(documentId, selected, { skipRender = false } = {}) {
    const documentIds = new Set(this.pendingAssignedKnowledge.document_ids || []);
    const normalizedId = String(documentId || '').trim();
    if (!normalizedId) {
      return;
    }
    if (selected) {
      documentIds.add(normalizedId);
      const documentItem = this.getAssignedKnowledgeDocumentById(normalizedId);
      if (documentItem) {
        this.updateAssignedKnowledgeSourceSelection(this.getCatalogDocumentSourceKey(documentItem), true, { skipRender: true });
      }
    } else {
      documentIds.delete(normalizedId);
    }
    this.pendingAssignedKnowledge.document_ids = this.normalizeStringArray(Array.from(documentIds));

    if (!skipRender) {
      this.renderAssignedKnowledgeCatalog();
      this.syncAssignedKnowledgeToAdditionalSettings();
    }
  }

  moveAssignedKnowledgeItem(category, key, selected) {
    if (category === 'source') {
      this.updateAssignedKnowledgeSourceSelection(key, selected);
    } else if (category === 'tag') {
      this.updateAssignedKnowledgeTagSelection(key, selected);
    } else if (category === 'document') {
      this.updateAssignedKnowledgeDocumentSelection(key, selected);
    }
  }

  initializeAssignedKnowledgeDropZones() {
    document.querySelectorAll('.agent-assigned-knowledge-transfer-list').forEach(dropZone => {
      dropZone.addEventListener('dragover', event => {
        event.preventDefault();
        dropZone.classList.add('drag-over');
      });
      dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
      });
      dropZone.addEventListener('drop', event => {
        event.preventDefault();
        dropZone.classList.remove('drag-over');
        const category = event.dataTransfer?.getData('text/assigned-knowledge-category');
        const key = event.dataTransfer?.getData('text/assigned-knowledge-key');
        if (!category || !key || category !== dropZone.dataset.category) {
          return;
        }
        this.moveAssignedKnowledgeItem(category, key, dropZone.dataset.listRole === 'selected');
      });
    });
  }

  renderAssignedKnowledgeTransferItems(containerId, items, options) {
    const container = document.getElementById(containerId);
    if (!container) {
      return;
    }
    container.textContent = '';

    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'agent-assigned-knowledge-empty-list';
      empty.textContent = options.emptyText || 'No items';
      container.appendChild(empty);
      return;
    }

    items.forEach(item => {
      const key = String(options.getKey(item) || '').trim();
      if (!key) {
        return;
      }
      const row = document.createElement('div');
      row.className = 'agent-assigned-knowledge-transfer-item';
      row.draggable = true;
      row.dataset.category = options.category;
      row.dataset.assignedKnowledgeKey = key;
      row.dataset.listRole = options.listRole;
      row.addEventListener('dragstart', event => {
        row.classList.add('dragging');
        event.dataTransfer?.setData('text/assigned-knowledge-category', options.category);
        event.dataTransfer?.setData('text/assigned-knowledge-key', key);
      });
      row.addEventListener('dragend', () => row.classList.remove('dragging'));
      row.addEventListener('dblclick', () => {
        this.moveAssignedKnowledgeItem(options.category, key, options.listRole === 'available');
      });

      row.appendChild(options.renderContent(item));
      const button = this.createAssignedKnowledgeMoveButton(options.category, key, options.listRole === 'available');
      row.appendChild(button);
      container.appendChild(row);
    });
  }

  createAssignedKnowledgeMoveButton(category, key, addToSelected) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `btn btn-sm ${addToSelected ? 'btn-outline-primary' : 'btn-outline-secondary'} flex-shrink-0`;
    button.title = addToSelected ? 'Add' : 'Remove';
    button.setAttribute('aria-label', addToSelected ? 'Add item' : 'Remove item');
    const icon = document.createElement('i');
    icon.className = addToSelected ? 'bi bi-arrow-right' : 'bi bi-arrow-left';
    button.appendChild(icon);
    button.addEventListener('click', () => this.moveAssignedKnowledgeItem(category, key, addToSelected));
    return button;
  }

  getResolvedAssignedKnowledgeDocuments(config = this.pendingAssignedKnowledge) {
    const selectedSourceKeys = this.getAssignedKnowledgeSelectedSourceKeys(config);
    if (!selectedSourceKeys.size) {
      return [];
    }
    const explicitDocumentIds = new Set(config.document_ids || []);
    const selectedTags = this.normalizeStringArray(config.tags || []);
    const includeAllSourceDocuments = !explicitDocumentIds.size && !selectedTags.length;
    const resolved = [];

    (this.assignedKnowledgeCatalog.documents || []).forEach(documentItem => {
      const sourceKey = this.getCatalogDocumentSourceKey(documentItem);
      if (!selectedSourceKeys.has(sourceKey)) {
        return;
      }

      const documentTags = new Set(documentItem.tags || []);
      const matchesSelectedTags = selectedTags.length && selectedTags.every(tag => documentTags.has(tag));
      const reasons = [];
      if (includeAllSourceDocuments) {
        reasons.push('source');
      }
      if (explicitDocumentIds.has(documentItem.id)) {
        reasons.push('explicit');
      }
      if (matchesSelectedTags) {
        reasons.push(...selectedTags.map(tag => `tag:${tag}`));
      }
      if (!reasons.length) {
        return;
      }
      resolved.push({ documentItem, reasons });
    });

    return resolved;
  }

  renderAssignedKnowledgeResolvedDocuments() {
    const container = document.getElementById('agent-assigned-knowledge-resolved-documents');
    if (!container) {
      return;
    }
    container.textContent = '';
    const resolved = this.getResolvedAssignedKnowledgeDocuments(this.pendingAssignedKnowledge);
    const selectedSourceKeys = this.getAssignedKnowledgeSelectedSourceKeys(this.pendingAssignedKnowledge);

    if (!resolved.length) {
      const empty = document.createElement('div');
      empty.className = 'agent-assigned-knowledge-empty-list';
      empty.textContent = selectedSourceKeys.size ? 'No active documents match the current limits' : 'No source workspaces selected';
      container.appendChild(empty);
      return;
    }

    resolved.forEach(({ documentItem, reasons }) => {
      const row = document.createElement('div');
      row.className = 'agent-assigned-knowledge-resolved-item';
      const content = this.createAssignedKnowledgeDocumentContent(documentItem);
      const reasonBadges = document.createElement('div');
      reasonBadges.className = 'd-flex flex-wrap gap-1 flex-shrink-0 justify-content-end';
      reasons.forEach(reason => {
        const badge = document.createElement('span');
        badge.className = reason === 'explicit' ? 'badge text-bg-primary' : 'badge text-bg-info';
        badge.textContent = reason.startsWith('tag:') ? reason.slice(4) : reason;
        reasonBadges.appendChild(badge);
      });
      row.appendChild(content);
      row.appendChild(reasonBadges);
      container.appendChild(row);
    });
  }

  updateAssignedKnowledgeCounts() {
    const config = this.pendingAssignedKnowledge || EMPTY_ASSIGNED_KNOWLEDGE;
    const sourceCount = this.getAssignedKnowledgeSelectedSourceKeys(config).size;
    const tagCount = (config.tags || []).length;
    const documentCount = (config.document_ids || []).length;
    const webSourceCount = (config.web_sources || []).length;
    const resolvedCount = this.getResolvedAssignedKnowledgeDocuments(config).length;
    const counts = [
      ['agent-assigned-knowledge-source-count', `${sourceCount} selected`],
      ['agent-assigned-knowledge-tag-count', `${tagCount} tag limit${tagCount === 1 ? '' : 's'}`],
      ['agent-assigned-knowledge-document-count', `${documentCount} specific`],
      ['agent-assigned-knowledge-web-source-count', `${webSourceCount} selected`],
      ['agent-assigned-knowledge-resolved-count', `${resolvedCount} active document${resolvedCount === 1 ? '' : 's'}`]
    ];
    counts.forEach(([elementId, text]) => {
      const element = document.getElementById(elementId);
      if (element) {
        element.textContent = text;
      }
    });
    this.updateAssignedKnowledgeActiveSummary(config, resolvedCount);
  }

  formatAssignedKnowledgeCount(count, singular, plural = `${singular}s`) {
    return `${count} ${count === 1 ? singular : plural}`;
  }

  getAssignedKnowledgeActiveSummaryText(config = this.pendingAssignedKnowledge, resolvedCount = null) {
    const sourceCount = this.getAssignedKnowledgeSelectedSourceKeys(config).size;
    const tagCount = (config.tags || []).length;
    const documentCount = (config.document_ids || []).length;
    const activeCount = resolvedCount === null ? this.getResolvedAssignedKnowledgeDocuments(config).length : resolvedCount;
    if (!sourceCount) {
      return 'Choose at least one source workspace to set this agent\'s active documents.';
    }

    const sourceText = this.formatAssignedKnowledgeCount(sourceCount, 'source workspace');
    const activeText = this.formatAssignedKnowledgeCount(activeCount, 'active document');
    if (!tagCount && !documentCount) {
      if (!activeCount) {
        return `No documents are available from ${sourceText}.`;
      }
      return `Using all ${activeText} from ${sourceText}. Add tag limits or specific documents only when the agent should use a smaller set.`;
    }

    if (!activeCount) {
      return `No active documents match the selected limits in ${sourceText}. Clear tag limits or add specific documents to expand the active set.`;
    }

    const limitDescriptions = [];
    if (tagCount) {
      limitDescriptions.push(
        tagCount === 1
          ? 'documents matching the selected tag limit'
          : `documents matching all ${tagCount} selected tag limits`
      );
    }
    if (documentCount) {
      limitDescriptions.push(this.formatAssignedKnowledgeCount(documentCount, 'specific document'));
    }
    return `Using ${activeText} from ${sourceText}: ${limitDescriptions.join(' plus ')}. Clear tag limits and specific documents to use every document from the selected source workspaces.`;
  }

  updateAssignedKnowledgeActiveSummary(config = this.pendingAssignedKnowledge, resolvedCount = null) {
    const summary = document.getElementById('agent-assigned-knowledge-active-summary');
    if (summary) {
      summary.textContent = this.getAssignedKnowledgeActiveSummaryText(config, resolvedCount);
    }
  }

  getAssignedKnowledgeConfig() {
    const enabled = Boolean(document.getElementById('agent-assigned-knowledge-enabled')?.checked);
    if (!enabled) {
      return this.cloneAssignedKnowledge(EMPTY_ASSIGNED_KNOWLEDGE);
    }

    if (!this.assignedKnowledgeCatalogLoaded && this.pendingAssignedKnowledge?.enabled) {
      return this.normalizeAssignedKnowledge(this.pendingAssignedKnowledge);
    }

    return this.normalizeAssignedKnowledge({
      enabled: true,
      scopes: this.pendingAssignedKnowledge.scopes,
      document_ids: this.pendingAssignedKnowledge.document_ids,
      tags: this.pendingAssignedKnowledge.tags,
      web_sources: this.pendingAssignedKnowledge.web_sources,
      allow_user_workspace_context: Boolean(document.getElementById('agent-assigned-knowledge-user-context-enabled')?.checked),
      allowed_user_workspace_actions: this.getAssignedKnowledgeSelectedUserActions()
    });
  }

  syncAssignedKnowledgeToAdditionalSettings() {
    const otherSettings = this.getParsedAdditionalSettings();
    const assignedKnowledge = this.getAssignedKnowledgeConfig();
    otherSettings[ASSIGNED_KNOWLEDGE_KEY] = assignedKnowledge;
    this.pendingAssignedKnowledge = this.normalizeAssignedKnowledge(assignedKnowledge);
    this.setParsedAdditionalSettings(otherSettings);
  }

  validateAssignedKnowledgeStep() {
    const assignedKnowledge = this.getAssignedKnowledgeConfig();
    if (!assignedKnowledge.enabled) {
      return true;
    }
    const scopes = assignedKnowledge.scopes || {};
    const hasSource = Boolean(scopes.personal || scopes.group_ids?.length || scopes.public_workspace_ids?.length);
    const hasWebSource = Boolean(assignedKnowledge.web_sources?.length);
    if (!hasSource && !hasWebSource) {
      this.showError('Choose at least one source or web source for Assigned Knowledge.');
      return false;
    }
    this.syncAssignedKnowledgeToAdditionalSettings();
    return true;
  }

  initializeInstructionsEditor() {
    if (this.instructionsEditor || typeof window.SimpleMDE === 'undefined') {
      return;
    }

    const instructionsInput = document.getElementById('agent-instructions');
    if (!instructionsInput) {
      return;
    }

    try {
      this.instructionsEditor = new window.SimpleMDE({
        element: instructionsInput,
        spellChecker: false,
        autoDownloadFontAwesome: false
      });
    } catch (error) {
      console.error('Failed to initialize SimpleMDE for agent instructions:', error);
      this.instructionsEditor = null;
    }
  }

  initializeVoiceControls() {
    if (!window.SimpleChatVoiceInput) {
      return;
    }

    window.SimpleChatVoiceInput.initializeDefaultFields?.();
    window.SimpleChatVoiceInput.enhanceFieldById('agent-instructions', {
      label: 'Dictate instructions',
      getValue: () => this.getInstructionsValue(),
      setValue: value => this.setInstructionsValue(value),
      onValueChanged: () => this.refreshInstructionsEditor(true)
    });
  }

  getInstructionsValue() {
    if (this.instructionsEditor) {
      return this.instructionsEditor.value();
    }

    return document.getElementById('agent-instructions')?.value || '';
  }

  setInstructionsValue(value = '') {
    const instructionsInput = document.getElementById('agent-instructions');
    if (instructionsInput) {
      instructionsInput.value = value;
    }

    if (this.instructionsEditor) {
      this.instructionsEditor.value(value);
    }
  }

  refreshInstructionsEditor(shouldFocus = false) {
    if (!this.instructionsEditor?.codemirror) {
      return;
    }

    setTimeout(() => {
      this.instructionsEditor.codemirror.refresh();
      if (shouldFocus) {
        this.instructionsEditor.codemirror.focus();
      }
    }, 0);
  }

  isClassicFoundryType(agentType = this.currentAgentType) {
    return (agentType || '').toLowerCase() === 'aifoundry';
  }

  isNewFoundryType(agentType = this.currentAgentType) {
    return (agentType || '').toLowerCase() === 'new_foundry';
  }

  isFoundryWorkflowType(agentType = this.currentAgentType) {
    return (agentType || '').toLowerCase() === 'foundry_workflow';
  }

  isAnyFoundryType(agentType = this.currentAgentType) {
    return this.isClassicFoundryType(agentType) || this.isNewFoundryType(agentType) || this.isFoundryWorkflowType(agentType);
  }

  getCurrentFoundryProvider(agentType = this.currentAgentType) {
    if (this.isFoundryWorkflowType(agentType)) {
      return 'foundry_workflow';
    }
    return this.isNewFoundryType(agentType) ? 'new_foundry' : 'aifoundry';
  }

  matchesFoundryEndpointProvider(provider) {
    const normalizedProvider = (provider || '').toLowerCase();
    if (!normalizedProvider) {
      return false;
    }
    if (this.isFoundryWorkflowType()) {
      return ['foundry_workflow', 'new_foundry', 'aifoundry'].includes(normalizedProvider);
    }
    return normalizedProvider === this.getCurrentFoundryProvider();
  }

  getAgentTypeLabel(agentType = this.currentAgentType) {
    if (this.isFoundryWorkflowType(agentType)) {
      return 'Foundry Workflow';
    }
    if (this.isNewFoundryType(agentType)) {
      return 'New Foundry';
    }
    if (this.isClassicFoundryType(agentType)) {
      return 'Foundry (classic)';
    }
    return 'Local (Semantic Kernel)';
  }

  getCurrentFoundrySettings(agentType = this.currentAgentType) {
    const otherSettings = this.currentAgent?.other_settings || {};
    if (this.isNewFoundryType(agentType)) {
      return otherSettings.new_foundry || {};
    }
    if (this.isFoundryWorkflowType(agentType)) {
      return otherSettings.foundry_workflow || {};
    }
    if (this.isClassicFoundryType(agentType)) {
      return otherSettings.azure_ai_foundry || {};
    }
    return {};
  }

  shouldPreserveCurrentFoundrySelection(endpointId) {
    if (!endpointId || !this.currentAgent || !this.isAnyFoundryType()) {
      return false;
    }

    const currentFoundrySettings = this.getCurrentFoundrySettings();
    const currentEndpointId = this.currentAgent.model_endpoint_id || currentFoundrySettings.endpoint_id || '';
    return currentEndpointId === endpointId;
  }

  setupNameGeneration() {
    const displayNameInput = document.getElementById('agent-display-name');
    const generatedNameInput = document.getElementById('agent-name');
    
    if (displayNameInput && generatedNameInput) {
      displayNameInput.addEventListener('input', () => {
        const displayName = displayNameInput.value.trim();
        const generatedName = this.generateAgentName(displayName);
        generatedNameInput.value = generatedName;
      });
    }
  }

  setupModelChangeListener() {
    const globalModelSelect = document.getElementById('agent-global-model-select');
    if (globalModelSelect) {
      globalModelSelect.addEventListener('change', () => {
        this.updateModelEndpointSelection();
        this.updateReasoningEffortForModel();
      });
    }
  }

  updateModelEndpointSelection() {
    const globalModelSelect = document.getElementById('agent-global-model-select');
    const modelEndpointInput = document.getElementById('agent-model-endpoint-id');
    const modelIdInput = document.getElementById('agent-model-id');
    const modelProviderInput = document.getElementById('agent-model-provider');
    if (!globalModelSelect) {
      return;
    }

    const selectedOption = globalModelSelect.options[globalModelSelect.selectedIndex];
    if (modelEndpointInput) {
      modelEndpointInput.value = selectedOption?.dataset?.endpointId || '';
    }
    if (modelIdInput) {
      modelIdInput.value = selectedOption?.value || '';
    }
    if (modelProviderInput) {
      modelProviderInput.value = selectedOption?.dataset?.provider || '';
    }
  }

  handleAgentTypeChange(agentType) {
    this.currentAgentType = agentType || 'local';
    this.applyAgentTypeVisibility();
    // Clear actions if switching to foundry
    if (this.isAnyFoundryType()) {
      this.clearSelectedActions();
      this.loadFoundryEndpoints();
    }
    this.populateSummary();
  }

  applyAgentTypeVisibility() {
    const isFoundry = this.isAnyFoundryType();
    const isClassicFoundry = this.isClassicFoundryType();
    const isNewFoundry = this.isNewFoundryType();
    const isFoundryWorkflow = this.isFoundryWorkflowType();
    const foundryFields = document.getElementById('agent-foundry-fields');
    const modelGroup = document.getElementById('agent-global-model-group');
    const customToggle = document.getElementById('agent-custom-connection-toggle');
    const customFields = document.getElementById('agent-custom-connection-fields');
    const actionsSection = document.getElementById('agent-step-4');
    const actionsDisabled = document.getElementById('agent-actions-disabled');
    const actionsContainer = document.getElementById('agent-actions-container');
    const actionsHeader = actionsSection?.querySelector('.card');
    const summaryActionsSection = document.getElementById('summary-actions-section');
    const instructionsContainer = document.getElementById('agent-instructions-container');
    const instructionsDraftContainer = document.getElementById('agent-instructions-draft-container');
    const instructionsFoundryNote = document.getElementById('agent-instructions-foundry-note');
    const instructionsInput = document.getElementById('agent-instructions');
    const advancedFoundryNote = document.getElementById('agent-advanced-foundry-note');
    const localAgentAdvancedSettings = document.getElementById('local-agent-advanced-settings');
    const foundryModeNote = document.getElementById('agent-foundry-mode-note');
    const foundryFetchBtnLabel = document.getElementById('agent-foundry-fetch-btn-label');
    const foundrySelectLabel = document.getElementById('agent-foundry-select-label');
    const foundrySelectHelp = document.getElementById('agent-foundry-select-help');
    const classicOnly = document.getElementById('agent-classic-foundry-only');
    const classicOnlyFields = document.getElementById('agent-classic-foundry-fields');
    const classicApiVersionGroup = document.getElementById('agent-classic-foundry-api-version-group');
    const newFoundryOnly = document.getElementById('agent-new-foundry-only');
    const foundryWorkflowOnly = document.getElementById('agent-foundry-workflow-only');
    const foundryWorkflowResponsesApiVersionInput = document.getElementById('agent-foundry-workflow-responses-api-version');

    if (foundryFields) foundryFields.classList.toggle('d-none', !isFoundry);
    if (modelGroup) modelGroup.classList.toggle('d-none', isFoundry);
    if (customToggle) customToggle.classList.toggle('d-none', isFoundry);
    if (customFields) customFields.classList.toggle('d-none', isFoundry);
    if (classicOnly) classicOnly.classList.toggle('d-none', !isClassicFoundry);
    if (classicOnlyFields) classicOnlyFields.classList.toggle('d-none', !isClassicFoundry);
    if (classicApiVersionGroup) classicApiVersionGroup.classList.toggle('d-none', !isClassicFoundry);
    if (newFoundryOnly) newFoundryOnly.classList.toggle('d-none', !isNewFoundry);
    if (foundryWorkflowOnly) foundryWorkflowOnly.classList.toggle('d-none', !isFoundryWorkflow);
    if (isFoundryWorkflow && foundryWorkflowResponsesApiVersionInput && !foundryWorkflowResponsesApiVersionInput.value.trim()) {
      foundryWorkflowResponsesApiVersionInput.value = 'v1';
    }

    if (instructionsContainer) instructionsContainer.classList.toggle('d-none', isFoundry);
  if (instructionsDraftContainer) instructionsDraftContainer.classList.toggle('d-none', isFoundry);
    if (instructionsFoundryNote) instructionsFoundryNote.classList.toggle('d-none', !isFoundry);
    if (instructionsInput) {
      if (isFoundry) {
        this.setInstructionsValue(this.foundryPlaceholderInstructions);
      }
    }

    if (actionsSection) {
      // Hide interactive actions when foundry
      if (actionsDisabled) actionsDisabled.classList.toggle('d-none', !isFoundry);
      if (actionsHeader) actionsHeader.classList.toggle('d-none', isFoundry);
      if (actionsContainer) actionsContainer.classList.toggle('d-none', isFoundry);
      const noActionsMsg = document.getElementById('agent-no-actions-message');
      if (noActionsMsg) noActionsMsg.classList.toggle('d-none', isFoundry);
      const selectedSummary = document.getElementById('agent-selected-actions-summary');
      if (selectedSummary) selectedSummary.classList.toggle('d-none', isFoundry);
    }

    if (summaryActionsSection) {
      summaryActionsSection.classList.toggle('d-none', isFoundry);
    }

    if (advancedFoundryNote) {
      advancedFoundryNote.classList.toggle('d-none', !isFoundry);
    }
    if (localAgentAdvancedSettings) {
      localAgentAdvancedSettings.classList.toggle('d-none', isFoundry);
    }

    // Update helper text
    const helper = document.getElementById('agent-type-helper');
    if (helper) {
      if (isNewFoundry) {
        helper.textContent = 'New Foundry applications use the signed-in user\'s Foundry access. Actions are disabled.';
      } else if (isFoundryWorkflow) {
        helper.textContent = 'Foundry workflows use the signed-in user\'s Foundry access. Actions are disabled.';
      } else if (isClassicFoundry) {
        helper.textContent = 'Classic Foundry agents use the signed-in user\'s Foundry access. Actions are disabled.';
      } else {
        helper.textContent = 'Local agents can attach actions and use SK plugins.';
      }
    }

    if (foundryFetchBtnLabel) {
      foundryFetchBtnLabel.textContent = isFoundryWorkflow ? 'Fetch Workflows' : isNewFoundry ? 'Fetch Applications' : 'Fetch Agents';
    }

    if (foundrySelectLabel) {
      foundrySelectLabel.textContent = isFoundryWorkflow ? 'Discovered Foundry Workflow (optional)' : isNewFoundry ? 'New Foundry Application' : 'Foundry Agent';
    }

    if (foundrySelectHelp) {
      if (isFoundryWorkflow) {
        foundrySelectHelp.textContent = 'Fetch uses your signed-in user identity against the selected Foundry project. If you know the workflow name, type it below instead.';
      } else if (isNewFoundry) {
        foundrySelectHelp.textContent = 'Fetch uses your signed-in user identity to populate the application name, version, and identifier fields.';
      } else {
        foundrySelectHelp.textContent = 'Fetch uses your signed-in user identity. Select a classic Foundry agent to import its identity.';
      }
    }

    if (foundryModeNote) {
      if (isFoundryWorkflow) {
        foundryModeNote.textContent = 'Foundry workflows use Microsoft Entra access to the Foundry project. Select a saved connection for project details, or fill them in manually.';
      } else if (isNewFoundry) {
        foundryModeNote.textContent = 'New Foundry applications use Microsoft Entra access through the Responses endpoint.';
      } else if (isClassicFoundry) {
        foundryModeNote.textContent = 'Classic Foundry agents run as the signed-in user through the SDK-backed invocation path.';
      }
    }
  }

  updateAgentTypeLock() {
    const radios = document.querySelectorAll('input[name="agent-type"]');
    if (!radios || !radios.length) {
      return;
    }

    const shouldDisable = this.isEditMode || this.currentStep > 1;

    radios.forEach(radio => {
      radio.disabled = shouldDisable;
      const wrapper = radio.closest('.form-check');
      if (wrapper) {
        wrapper.classList.toggle('opacity-50', shouldDisable);
      }
    });

    const selector = document.getElementById('agent-type-selector');
    if (selector) {
      selector.classList.toggle('pe-none', shouldDisable);
    }
  }

  updateReasoningEffortForModel() {
    const globalModelSelect = document.getElementById('agent-global-model-select');
    const reasoningEffortSelect = document.getElementById('agent-reasoning-effort');
    const reasoningEffortGroup = reasoningEffortSelect?.closest('.mb-3');
    
    if (!globalModelSelect || !reasoningEffortSelect || !reasoningEffortGroup) {
      return;
    }
    
    const selectedModel = globalModelSelect.value;
    if (!selectedModel) {
      // No model selected, hide reasoning effort
      reasoningEffortGroup.style.display = 'none';
      return;
    }
    
    // Get supported levels for the selected model
    const supportedLevels = getModelSupportedLevels(selectedModel);
    
    // If model only supports 'none', hide the field
    if (supportedLevels.length === 1 && supportedLevels[0] === 'none') {
      reasoningEffortGroup.style.display = 'none';
      reasoningEffortSelect.value = ''; // Clear selection
      return;
    }
    
    // Show the field
    reasoningEffortGroup.style.display = 'block';
    
    // Update available options based on supported levels
    const currentValue = reasoningEffortSelect.value;
    const allOptions = reasoningEffortSelect.querySelectorAll('option');
    
    // Show/hide options based on supported levels
    allOptions.forEach(option => {
      const value = option.value;
      if (value === '') {
        // Always show the "inherit" option
        option.style.display = '';
        option.disabled = false;
      } else if (supportedLevels.includes(value)) {
        option.style.display = '';
        option.disabled = false;
      } else {
        option.style.display = 'none';
        option.disabled = true;
      }
    });
    
    // If current value is not supported, reset to inherit
    if (currentValue && currentValue !== '' && !supportedLevels.includes(currentValue)) {
      reasoningEffortSelect.value = '';
    }
  }

  togglePowerUserMode(isEnabled) {
    console.log('Toggling power user mode:', isEnabled);
    const powerUserSection = document.getElementById('agent-power-user-settings');
    if (powerUserSection) {
      powerUserSection.classList.toggle('d-none', !isEnabled);
    }
  }

  generateAgentName(displayName) {
    if (!displayName) return '';
    
    // Convert to lowercase, replace spaces with underscores, remove invalid characters
    return displayName
      .toLowerCase()
      .replace(/\s+/g, '_')           // Replace spaces with underscores
      .replace(/[^a-z0-9_-]/g, '')    // Remove invalid characters (keep only letters, numbers, underscores, hyphens)
      .replace(/_{2,}/g, '_')         // Replace multiple underscores with single
      .replace(/^_+|_+$/g, '');       // Remove leading/trailing underscores
  }

  showModal(agent = null) {
    this.isEditMode = !!agent;
    this.currentAgentType = (agent && agent.agent_type) || 'local';
    
    // Store original state for change detection
    this.originalAgent = agent ? JSON.parse(JSON.stringify(agent)) : null;
    
    // Reset modal state
    this.currentStep = 1;
    
    // Set modal title
    const title = this.isEditMode ? 'Edit Agent' : 'Add Agent';
    const titleElement = document.getElementById('agentModalLabel');
    if (titleElement) {
      titleElement.textContent = title;
    }
    
    // Clear error messages
    const errorDiv = document.getElementById('agent-modal-error');
    if (errorDiv) {
      errorDiv.classList.add('d-none');
    }

    const instructionBrief = document.getElementById('agent-instruction-brief');
    const draftStatus = document.getElementById('agent-draft-instructions-status');
    if (instructionBrief) instructionBrief.value = '';
    if (draftStatus) draftStatus.textContent = '';
    
    // If editing an existing agent, populate fields and generate name if missing
    if (agent) {
      this.currentAgent = agent;
      this.populateFields(agent);
    } else {
      this.currentAgent = null;
      this.actionsToSelect = null; // Clear any stored actions for new agent
      this.clearFields();
    }
    
    // Ensure generated name is populated for both new and existing agents
    this.updateGeneratedName();
    this.initializeInstructionsEditor();
    this.initializeVoiceControls();
    this.syncAgentTypeSelector();
    this.applyAgentTypeVisibility();
    this.updateAgentTypeLock();
    
    // Load models for the modal
    this.loadModelsForModal();
    this.loadFoundryEndpoints();
    this.updateModelEndpointSelection();
    
    // Show the Bootstrap modal
    const modalEl = document.getElementById('agentModal');
    if (modalEl) {
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      modal.show();
      
      // Use a more robust approach - wait for modal to be visible and DOM ready
      const initializeSteps = () => {
        if (modalEl.classList.contains('show')) {
          console.log('Modal is visible, initializing step indicators');
          this.currentStep = 1; // Ensure we're on step 1
          this.updateStepIndicator();
          this.showStep(1);
          this.updateNavigationButtons();
          this.updateTemplateButtonVisibility();
          console.log('Step indicators initialized');
        } else {
          // Modal not ready yet, try again
          setTimeout(initializeSteps, 50);
        }
      };
      
      // Start checking after a short delay
      setTimeout(initializeSteps, 100);
      
    } else {
      console.error('Agent modal element not found');
    }
  }

  updateGeneratedName() {
    const displayNameInput = document.getElementById('agent-display-name');
    const generatedNameInput = document.getElementById('agent-name');
    
    if (displayNameInput && generatedNameInput) {
      const displayName = displayNameInput.value.trim();
      if (displayName && !generatedNameInput.value) {
        const generatedName = this.generateAgentName(displayName);
        generatedNameInput.value = generatedName;
      }
    }
  }

  syncAgentTypeSelector() {
    const radios = document.querySelectorAll('input[name="agent-type"]');
    if (!radios || !radios.length) return;
    radios.forEach(r => {
      r.checked = r.value === this.currentAgentType;
    });
  }

  clearFields() {
    // Clear all form fields
    const displayName = document.getElementById('agent-display-name');
    const generatedName = document.getElementById('agent-name');
    const description = document.getElementById('agent-description');
    const instructions = document.getElementById('agent-instructions');
    const modelSelect = document.getElementById('agent-global-model-select');
    const customConnection = document.getElementById('agent-custom-connection');
    const modelEndpointId = document.getElementById('agent-model-endpoint-id');
    const modelId = document.getElementById('agent-model-id');
    const modelProvider = document.getElementById('agent-model-provider');
    const foundryEndpointSelect = document.getElementById('agent-foundry-endpoint-select');
    const foundryAgentSelect = document.getElementById('agent-foundry-agent-select');
    const foundryEndpointInput = document.getElementById('agent-foundry-endpoint');
    const foundryApiVersionInput = document.getElementById('agent-foundry-api-version');
    const foundryDeploymentInput = document.getElementById('agent-foundry-deployment');
    const foundryAgentIdInput = document.getElementById('agent-foundry-agent-id');
    const foundryResponsesApiVersionInput = document.getElementById('agent-new-foundry-responses-api-version');
    const foundryApplicationIdInput = document.getElementById('agent-new-foundry-application-id');
    const foundryApplicationNameInput = document.getElementById('agent-new-foundry-application-name');
    const foundryApplicationVersionInput = document.getElementById('agent-new-foundry-application-version');
    const foundryActivityApiVersionInput = document.getElementById('agent-new-foundry-activity-api-version');
    const foundryWorkflowNameInput = document.getElementById('agent-foundry-workflow-name');
    const foundryWorkflowResponsesApiVersionInput = document.getElementById('agent-foundry-workflow-responses-api-version');
    const foundryWorkflowIncludeContextInput = document.getElementById('agent-foundry-workflow-include-document-context');
    const foundryWorkflowMaxContextCharsInput = document.getElementById('agent-foundry-workflow-max-context-chars');
    const foundryNotesInput = document.getElementById('agent-foundry-notes');
    const foundryStatus = document.getElementById('agent-foundry-fetch-status');
    const additionalSettings = document.getElementById('agent-additional-settings');
    const instructionBrief = document.getElementById('agent-instruction-brief');
    const draftStatus = document.getElementById('agent-draft-instructions-status');
    
    if (displayName) displayName.value = '';
    if (generatedName) generatedName.value = '';
    if (description) description.value = '';
    if (instructions) this.setInstructionsValue('');
    if (modelSelect) modelSelect.selectedIndex = 0;
    if (customConnection) customConnection.checked = false;
    if (modelEndpointId) modelEndpointId.value = '';
    if (modelId) modelId.value = '';
    if (modelProvider) modelProvider.value = '';
    if (foundryEndpointSelect) foundryEndpointSelect.selectedIndex = 0;
    if (foundryAgentSelect) foundryAgentSelect.selectedIndex = 0;
    this.selectedFoundryWorkflowAgent = null;
    if (foundryEndpointInput) foundryEndpointInput.value = '';
    if (foundryApiVersionInput) foundryApiVersionInput.value = '';
    if (foundryDeploymentInput) foundryDeploymentInput.value = '';
    if (foundryAgentIdInput) foundryAgentIdInput.value = '';
    if (foundryResponsesApiVersionInput) foundryResponsesApiVersionInput.value = '';
    if (foundryApplicationIdInput) foundryApplicationIdInput.value = '';
    if (foundryApplicationNameInput) foundryApplicationNameInput.value = '';
    if (foundryApplicationVersionInput) foundryApplicationVersionInput.value = '';
    if (foundryActivityApiVersionInput) foundryActivityApiVersionInput.value = '';
    if (foundryWorkflowNameInput) foundryWorkflowNameInput.value = '';
    if (foundryWorkflowResponsesApiVersionInput) foundryWorkflowResponsesApiVersionInput.value = 'v1';
    if (foundryWorkflowIncludeContextInput) foundryWorkflowIncludeContextInput.checked = true;
    if (foundryWorkflowMaxContextCharsInput) foundryWorkflowMaxContextCharsInput.value = '';
    if (foundryNotesInput) foundryNotesInput.value = '';
    if (foundryStatus) foundryStatus.textContent = '';
    if (additionalSettings) additionalSettings.value = '{}';
    if (instructionBrief) instructionBrief.value = '';
    if (draftStatus) draftStatus.textContent = '';
    this.resetAssignedKnowledgeControls();
    
    // Clear any selected actions
    this.clearSelectedActions();
  }

  clearSelectedActions() {
    const actionCards = document.querySelectorAll('.action-card');
    actionCards.forEach(card => {
      card.classList.remove('border-primary', 'bg-light');
      const checkIcon = card.querySelector('.action-check-icon');
      if (checkIcon) {
        checkIcon.classList.add('d-none');
      }
    });
    this.updateSelectedActionsDisplay();
  }

  async loadModelsForModal() {
    try {
      const { models, selectedModel } = await agentsCommon.fetchAndGetAvailableModels(this.settingsEndpoint, this.currentAgent);
      const globalModelSelect = document.getElementById('agent-global-model-select');
      
      if (globalModelSelect) {
        agentsCommon.populateGlobalModelDropdown(globalModelSelect, models, selectedModel);
        this.updateModelEndpointSelection();
        
        // Update reasoning effort options based on selected model
        this.updateReasoningEffortForModel();
      }
    } catch (error) {
      console.error('Failed to load models for agent modal:', error);
      // Show fallback message if models fail to load
      const globalModelSelect = document.getElementById('agent-global-model-select');
      if (globalModelSelect) {
        globalModelSelect.innerHTML = '<option value="">Error loading models</option>';
      }
    }
  }

  async loadFoundryEndpoints() {
    const endpointSelect = document.getElementById('agent-foundry-endpoint-select');
    if (!endpointSelect) {
      return;
    }

    try {
      const resp = await fetch(this.settingsEndpoint);
      if (!resp.ok) {
        throw new Error('Failed to load Foundry endpoints');
      }
      const settings = await resp.json();
      const endpoints = Array.isArray(settings.model_endpoints) ? settings.model_endpoints : [];
      this.foundryEndpoints = endpoints.filter(endpoint => this.matchesFoundryEndpointProvider(endpoint.provider));

      endpointSelect.innerHTML = '<option value="">Optional: select a saved connection...</option>';
      this.foundryEndpoints.forEach(endpoint => {
        const opt = document.createElement('option');
        opt.value = endpoint.id || '';
        opt.textContent = endpoint.name || endpoint.connection?.endpoint || 'Foundry Endpoint';
        if (endpoint.scope) {
          opt.dataset.scope = endpoint.scope;
        }
        endpointSelect.appendChild(opt);
      });

      const existingEndpointId =
        (this.currentAgent && (
          this.currentAgent.model_endpoint_id
          || this.currentAgent.other_settings?.azure_ai_foundry?.endpoint_id
          || this.currentAgent.other_settings?.new_foundry?.endpoint_id
          || this.currentAgent.other_settings?.foundry_workflow?.endpoint_id
        )) || '';
      if (existingEndpointId) {
        endpointSelect.value = existingEndpointId;
      }
      this.applyFoundryEndpointSelection();
    } catch (error) {
      console.error('Failed to load Foundry endpoints:', error);
    }
  }

  applyFoundryEndpointSelection() {
    const endpointSelect = document.getElementById('agent-foundry-endpoint-select');
    const endpointInput = document.getElementById('agent-foundry-endpoint');
    const apiVersionInput = document.getElementById('agent-foundry-api-version');
    const deploymentInput = document.getElementById('agent-foundry-deployment');
    const endpointIdInput = document.getElementById('agent-model-endpoint-id');
    const providerInput = document.getElementById('agent-model-provider');
    const statusEl = document.getElementById('agent-foundry-fetch-status');
    const applicationIdInput = document.getElementById('agent-new-foundry-application-id');
    const applicationVersionInput = document.getElementById('agent-new-foundry-application-version');
    const applicationNameInput = document.getElementById('agent-new-foundry-application-name');
    const workflowResponsesApiVersionInput = document.getElementById('agent-foundry-workflow-responses-api-version');
    const workflowNameInput = document.getElementById('agent-foundry-workflow-name');

    if (!endpointSelect) {
      return;
    }

    const endpointId = endpointSelect.value || '';
    if (endpointIdInput) endpointIdInput.value = endpointId;
    if (providerInput) providerInput.value = endpointId ? this.getCurrentFoundryProvider() : '';

    const selected = this.foundryEndpoints.find(endpoint => endpoint.id === endpointId);
    if (selected) {
      const currentFoundrySettings = this.getCurrentFoundrySettings();
      const preserveCurrentSelection = this.shouldPreserveCurrentFoundrySelection(endpointId);
      if (endpointInput) {
        endpointInput.value = selected.connection?.endpoint || '';
      }
      if (apiVersionInput) {
        apiVersionInput.value = selected.connection?.project_api_version || selected.connection?.api_version || 'v1';
      }
      if (deploymentInput) {
        deploymentInput.value = selected.connection?.project_name || '';
      }
      const responsesApiVersionInput = document.getElementById('agent-new-foundry-responses-api-version');
      if (responsesApiVersionInput) {
        const endpointResponsesApiVersion = selected.connection?.openai_api_version || selected.connection?.api_version || '';
        const storedResponsesApiVersion = currentFoundrySettings.responses_api_version || '';
        responsesApiVersionInput.value = preserveCurrentSelection && storedResponsesApiVersion
          ? storedResponsesApiVersion
          : endpointResponsesApiVersion;
      }
      if (workflowResponsesApiVersionInput) {
        const endpointResponsesApiVersion = selected.connection?.openai_api_version || selected.connection?.api_version || '';
        const storedResponsesApiVersion = currentFoundrySettings.responses_api_version || '';
        workflowResponsesApiVersionInput.value = preserveCurrentSelection && storedResponsesApiVersion
          ? storedResponsesApiVersion
          : endpointResponsesApiVersion || 'v1';
      }
      const agentSelect = document.getElementById('agent-foundry-agent-select');
      if (agentSelect) {
        agentSelect.innerHTML = '<option value="">Select an agent...</option>';
      }
      if (applicationIdInput) applicationIdInput.value = preserveCurrentSelection ? (currentFoundrySettings.application_id || '') : '';
      if (applicationVersionInput) applicationVersionInput.value = preserveCurrentSelection ? (currentFoundrySettings.application_version || '') : '';
      if (applicationNameInput) {
        if (preserveCurrentSelection) {
          applicationNameInput.value = currentFoundrySettings.application_name || applicationNameInput.value || '';
        } else if (!this.currentAgent) {
          applicationNameInput.value = '';
        }
      }
      if (workflowNameInput) {
        workflowNameInput.value = preserveCurrentSelection ? (currentFoundrySettings.workflow_name || workflowNameInput.value || '') : '';
      }
      if (!preserveCurrentSelection) {
        this.selectedFoundryWorkflowAgent = null;
      }
      this.foundryAgents = [];
      if (statusEl) {
        statusEl.textContent = '';
      }
    } else if (workflowResponsesApiVersionInput && this.isFoundryWorkflowType() && !workflowResponsesApiVersionInput.value.trim()) {
      workflowResponsesApiVersionInput.value = 'v1';
    }
  }

  async fetchFoundryAgents() {
    const endpointSelect = document.getElementById('agent-foundry-endpoint-select');
    const agentSelect = document.getElementById('agent-foundry-agent-select');
    const statusEl = document.getElementById('agent-foundry-fetch-status');
    if (!endpointSelect || !agentSelect) {
      return;
    }

    const endpointId = endpointSelect.value || '';
    const scope = endpointSelect.options[endpointSelect.selectedIndex]?.dataset?.scope || 'global';
    if (!endpointId) {
      const runtimeLabel = this.isFoundryWorkflowType() ? 'Foundry Workflow' : this.isNewFoundryType() ? 'New Foundry' : 'Foundry';
      const resourceLabel = this.isFoundryWorkflowType() ? 'workflows' : this.isNewFoundryType() ? 'applications' : 'agents';
      showToast(`Select a ${runtimeLabel} endpoint before fetching ${resourceLabel}.`, 'warning');
      return;
    }

    try {
      if (statusEl) {
        statusEl.textContent = this.isFoundryWorkflowType()
          ? 'Fetching workflows...'
          : this.isNewFoundryType() ? 'Fetching applications...' : 'Fetching agents...';
      }
      const response = await fetch('/api/models/foundry/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          endpoint_id: endpointId,
          scope,
          resource_type: this.isFoundryWorkflowType() ? 'workflow' : ''
        })
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const fetchError = new Error(payload.error || 'Failed to fetch Foundry agents');
        fetchError.authRequired = payload.auth_required === true;
        fetchError.authUrl = payload.auth_url || payload.consent_url || '';
        throw fetchError;
      }
      this.foundryAgents = Array.isArray(payload.agents) ? payload.agents : [];
      const responsesApiVersionInput = document.getElementById('agent-new-foundry-responses-api-version');
      const fetchedResponsesApiVersion = payload.responses_api_version || '';
      if (this.isNewFoundryType() && responsesApiVersionInput && fetchedResponsesApiVersion) {
        responsesApiVersionInput.value = fetchedResponsesApiVersion;
      }
      const workflowResponsesApiVersionInput = document.getElementById('agent-foundry-workflow-responses-api-version');
      if (this.isFoundryWorkflowType() && workflowResponsesApiVersionInput && fetchedResponsesApiVersion) {
        workflowResponsesApiVersionInput.value = fetchedResponsesApiVersion;
      }
      agentSelect.innerHTML = '<option value="">Select an agent...</option>';
      this.foundryAgents.forEach(agent => {
        const opt = document.createElement('option');
        const applicationValue = agent.application_id || agent.id || '';
        const workflowValue = agent.workflow_name || agent.application_name || agent.name || applicationValue;
        const optionValue = this.isFoundryWorkflowType()
          ? workflowValue
          : this.isNewFoundryType() ? applicationValue : (agent.id || '');
        const versionSuffix = agent.application_version ? ` (v${agent.application_version})` : '';
        opt.value = optionValue;
        opt.textContent = this.isFoundryWorkflowType()
          ? (agent.display_name || agent.workflow_name || agent.application_name || agent.name || workflowValue)
          : this.isNewFoundryType()
          ? `${agent.display_name || agent.application_name || agent.name || applicationValue}${versionSuffix}`
          : (agent.display_name || agent.name || agent.id || '');
        agentSelect.appendChild(opt);
      });
      if (statusEl) {
        const foundLabel = this.isFoundryWorkflowType() ? 'workflow' : this.isNewFoundryType() ? 'application' : 'agent';
        statusEl.textContent = `${this.foundryAgents.length} ${foundLabel}(s) found.`;
      }
    } catch (error) {
      console.error('Failed to fetch Foundry agents:', error);
      if (statusEl) {
        statusEl.textContent = '';
        const authUrl = normalizeHttpUrl(error.authUrl);
        if (error.authRequired && authUrl) {
          const authLink = document.createElement('a');
          authLink.href = authUrl;
          authLink.target = '_blank';
          authLink.rel = 'noopener noreferrer';
          authLink.textContent = 'Sign in or grant Foundry access';
          statusEl.appendChild(document.createTextNode('Foundry access requires sign-in or consent. '));
          statusEl.appendChild(authLink);
        }
      }
      showToast(error.message || 'Failed to fetch Foundry agents.', 'danger');
    }
  }

  applyFoundryAgentSelection() {
    const agentSelect = document.getElementById('agent-foundry-agent-select');
    const agentIdInput = document.getElementById('agent-foundry-agent-id');
    if (!agentSelect) {
      return;
    }

    const selectedId = agentSelect.value || '';
    if (agentIdInput && this.isClassicFoundryType()) {
      agentIdInput.value = selectedId;
    }
    const selected = this.foundryAgents.find(agent => {
      if (this.isFoundryWorkflowType()) {
        return (agent.workflow_name || agent.application_name || agent.name || agent.application_id || agent.id || '') === selectedId;
      }
      if (this.isNewFoundryType()) {
        return (agent.application_id || agent.id || '') === selectedId;
      }
      return (agent.id || '') === selectedId;
    });
    if (!selected) {
      if (this.isFoundryWorkflowType()) {
        this.selectedFoundryWorkflowAgent = null;
      }
      return;
    }

    if (this.isNewFoundryType()) {
      const applicationIdInput = document.getElementById('agent-new-foundry-application-id');
      const applicationNameInput = document.getElementById('agent-new-foundry-application-name');
      const applicationVersionInput = document.getElementById('agent-new-foundry-application-version');
      const responsesApiVersionInput = document.getElementById('agent-new-foundry-responses-api-version');
      if (applicationIdInput) {
        applicationIdInput.value = selected.application_id || selected.id || '';
      }
      if (applicationNameInput) {
        applicationNameInput.value = selected.application_name || selected.name || '';
      }
      if (applicationVersionInput) {
        applicationVersionInput.value = selected.application_version || '';
      }
      if (responsesApiVersionInput && selected.responses_api_version) {
        responsesApiVersionInput.value = selected.responses_api_version;
      }
    }

    if (this.isFoundryWorkflowType()) {
      const workflowNameInput = document.getElementById('agent-foundry-workflow-name');
      const workflowResponsesApiVersionInput = document.getElementById('agent-foundry-workflow-responses-api-version');
      if (workflowNameInput) {
        workflowNameInput.value = selected.workflow_name || selected.application_name || selected.name || selectedId || '';
      }
      this.selectedFoundryWorkflowAgent = selected;
      if (workflowResponsesApiVersionInput && selected.responses_api_version) {
        workflowResponsesApiVersionInput.value = selected.responses_api_version;
      }
    }

    const displayNameInput = document.getElementById('agent-display-name');
    const descriptionInput = document.getElementById('agent-description');
    if (displayNameInput && !displayNameInput.value.trim()) {
      displayNameInput.value = selected.display_name || selected.application_name || selected.name || '';
      this.updateGeneratedName();
    }
    if (descriptionInput && !descriptionInput.value.trim()) {
      descriptionInput.value = selected.description || '';
    }
  }

  populateFields(agent) {
    // Use shared logic to determine if custom connection should be enabled
    const customConnection = document.getElementById('agent-custom-connection');
    if (customConnection) {
      // Use agentsCommon.shouldEnableCustomConnection to set toggle
      customConnection.checked = agentsCommon.shouldEnableCustomConnection(agent);
    }

    // Agent type selection
    this.currentAgentType = agent.agent_type || 'local';
    this.syncAgentTypeSelector();
    this.applyAgentTypeVisibility();

    // Use shared function to populate all fields
    if (agentsCommon && typeof agentsCommon.setAgentModalFields === 'function') {
      agentsCommon.setAgentModalFields(agent);
    }
    this.setInstructionsValue(agent.instructions || '');
    this.setAssignedKnowledgeControls(agent.other_settings?.[ASSIGNED_KNOWLEDGE_KEY]);

    // any agent advanced settings
    if (this.currentAgent 
        && this.currentAgent.max_completion_tokens != -1) {
      const powerUserToggle = document.getElementById('agent-power-user-toggle');
      if (powerUserToggle) {
        powerUserToggle.checked = true; // true/false from your agent data
        const agentPowerUserSettings = document.getElementById('agent-power-user-settings');
        if (agentPowerUserSettings) {
          agentPowerUserSettings.classList.remove('d-none');
        }
      }
    }

    // Show/hide custom connection fields as needed
    if (customConnection) {
      // Find the custom fields and global model group containers
      const customFields = document.getElementById('agent-custom-connection-fields');
      const globalModelGroup = document.getElementById('agent-global-model-group');
      // Use shared UI toggle logic if available
      if (agentsCommon && typeof agentsCommon.toggleCustomConnectionUI === 'function') {
        agentsCommon.toggleCustomConnectionUI(customConnection.checked, {
          customFields,
          globalModelGroup
        });
      } else if (customFields && globalModelGroup) {
        // Fallback: show/hide manually
        if (customConnection.checked) {
          customFields.classList.remove('d-none');
          globalModelGroup.classList.add('d-none');
        } else {
          customFields.classList.add('d-none');
          globalModelGroup.classList.remove('d-none');
        }
      }
    }

    // Store selected actions to be set when actions are loaded
    if (agent.actions_to_load && Array.isArray(agent.actions_to_load)) {
      this.actionsToSelect = agent.actions_to_load;
    }

    // Foundry-specific fields
    if (this.isAnyFoundryType(agent.agent_type)) {
      const other = agent.other_settings || {};
      const foundry = this.isFoundryWorkflowType(agent.agent_type)
        ? ((other && other.foundry_workflow) || {})
        : this.isNewFoundryType(agent.agent_type)
          ? ((other && other.new_foundry) || {})
          : ((other && other.azure_ai_foundry) || {});
      const endpointEl = document.getElementById('agent-foundry-endpoint');
      const apiEl = document.getElementById('agent-foundry-api-version');
      const depEl = document.getElementById('agent-foundry-deployment');
      const idEl = document.getElementById('agent-foundry-agent-id');
      const notesEl = document.getElementById('agent-foundry-notes');
      const responsesApiEl = document.getElementById('agent-new-foundry-responses-api-version');
      const applicationIdEl = document.getElementById('agent-new-foundry-application-id');
      const applicationNameEl = document.getElementById('agent-new-foundry-application-name');
      const applicationVersionEl = document.getElementById('agent-new-foundry-application-version');
      const activityVersionEl = document.getElementById('agent-new-foundry-activity-api-version');
      const workflowNameEl = document.getElementById('agent-foundry-workflow-name');
      const workflowResponsesApiEl = document.getElementById('agent-foundry-workflow-responses-api-version');
      const workflowIncludeContextEl = document.getElementById('agent-foundry-workflow-include-document-context');
      const workflowMaxContextCharsEl = document.getElementById('agent-foundry-workflow-max-context-chars');
      if (endpointEl) endpointEl.value = agent.azure_openai_gpt_endpoint || '';
      if (apiEl) apiEl.value = foundry.api_version || agent.azure_openai_gpt_api_version || '';
      if (depEl) depEl.value = agent.azure_openai_gpt_deployment || '';
      if (idEl) idEl.value = foundry.agent_id || '';
      if (responsesApiEl) responsesApiEl.value = foundry.responses_api_version || agent.azure_openai_gpt_api_version || '';
      if (applicationIdEl) applicationIdEl.value = foundry.application_id || '';
      if (applicationNameEl) applicationNameEl.value = foundry.application_name || '';
      if (applicationVersionEl) applicationVersionEl.value = foundry.application_version || '';
      if (activityVersionEl) activityVersionEl.value = foundry.activity_api_version || '';
      if (workflowNameEl) workflowNameEl.value = foundry.workflow_name || '';
      this.selectedFoundryWorkflowAgent = foundry.agent_reference ? {
        ...foundry.agent_reference,
        workflow_name: foundry.workflow_name || foundry.agent_reference.name || '',
        workflow_agent_id: foundry.workflow_agent_id || foundry.agent_reference.id || '',
        application_id: foundry.application_id || foundry.agent_reference.application_id || '',
        application_version: foundry.application_version || foundry.agent_reference.application_version || ''
      } : null;
      if (workflowResponsesApiEl) workflowResponsesApiEl.value = foundry.responses_api_version || agent.azure_openai_gpt_api_version || '';
      if (workflowIncludeContextEl) workflowIncludeContextEl.checked = foundry.include_document_context !== false;
      if (workflowMaxContextCharsEl) workflowMaxContextCharsEl.value = foundry.max_context_chars || '';
      if (notesEl) notesEl.value = foundry.notes || '';
      // ensure actions cleared for UI
      this.clearSelectedActions();
    }
  }

  nextStep() {
    if (!this.validateCurrentStep()) {
      return;
    }
    
    if (this.currentStep < this.maxSteps) {
      this.goToStep(this.currentStep + 1);
    }
  }

  prevStep() {
    if (this.currentStep > 1) {
      this.goToStep(this.currentStep - 1);
    }
  }

  async skipToEnd() {
    // Skip to the summary step (step 6)
    //if (this.actionsToSelect != null && this.actionsToSelect.length > 0) {
    //  this.setSelectedActions(this.actionsToSelect);
    //}
    const skipBtn = document.getElementById('agent-modal-skip');
    const originalText = skipBtn.innerHTML;
    if (skipBtn) {
      skipBtn.disabled = true;
      skipBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Skipping...`;
    }
    try {
      if (!this.isAnyFoundryType()) {
        await this.loadAvailableActions();
      }
      this.goToStep(this.maxSteps);
    } catch (error) {
      console.error('Error loading actions:', error);
      if (skipBtn) {
        skipBtn.disabled = false;
        skipBtn.innerHTML = originalText;
      }
    } finally {
      if (skipBtn) {
        skipBtn.disabled = false;
        skipBtn.innerHTML = originalText;
      }
    }
  }

  goToStep(stepNumber) {
    if (stepNumber < 1 || stepNumber > this.maxSteps) return;
    
    this.currentStep = stepNumber;
    this.showStep(stepNumber);
    this.updateStepIndicator();
    this.updateNavigationButtons();
    this.updateTemplateButtonVisibility();
    this.updateAgentTypeLock();
  }

  showStep(stepNumber) {
    // Hide all steps
    for (let i = 1; i <= this.maxSteps; i++) {
      const step = document.getElementById(`agent-step-${i}`);
      if (step) {
        step.classList.add('d-none');
      }
    }
    
    // Show current step
    const currentStep = document.getElementById(`agent-step-${stepNumber}`);
    if (currentStep) {
      currentStep.classList.remove('d-none');
    }

    if (stepNumber === 3) {
      this.initializeInstructionsEditor();
      this.refreshInstructionsEditor(!this.isAnyFoundryType());
    }

    if (stepNumber === 2) {
      const isFoundry = this.isAnyFoundryType();
      const customConnectionToggle = document.getElementById('agent-custom-connection-toggle');
      const modelGroup = document.getElementById('agent-global-model-group');

      if (customConnectionToggle) {
        if (isFoundry) {
          customConnectionToggle.classList.add('d-none');
        } else if (!this.isAdmin) {
          const allowCustomEndpoints = this.workspaceScope === 'group'
            ? appSettings?.allow_group_custom_endpoints
            : appSettings?.allow_user_custom_endpoints;
          customConnectionToggle.classList.toggle('d-none', !allowCustomEndpoints);
        } else {
          customConnectionToggle.classList.remove('d-none');
        }
      }

      if (modelGroup) {
        modelGroup.classList.toggle('d-none', isFoundry);
      }
    }
    
    // Load actions when reaching step 4
    if (stepNumber === 4) {
      if (!this.isAnyFoundryType()) {
        this.loadAvailableActions();
      }
    }
    
    if (stepNumber === 5) {
      if (document.getElementById('agent-assigned-knowledge-enabled')?.checked) {
        this.loadAssignedKnowledgeCatalog();
      }
    }

    // Populate summary when reaching step 7
    if (stepNumber === 7) {
      this.populateSummary();
    }
  }

  updateStepIndicator() {
    // Clear any pending updates to prevent rapid successive calls
    if (this.updateStepIndicatorTimeout) {
      clearTimeout(this.updateStepIndicatorTimeout);
    }
    
    // Debounce the actual update
    this.updateStepIndicatorTimeout = setTimeout(() => {
      this._doUpdateStepIndicator();
    }, 10); // Small delay to allow for batching
  }
  
  _doUpdateStepIndicator() {
    // Be very specific about which step indicators we're targeting - only those in the agent modal
    const agentModal = document.getElementById('agentModal');
    if (!agentModal) {
      console.warn('Agent modal not found');
      return;
    }
    
    const indicators = agentModal.querySelectorAll('.step-indicator');
    console.log(`Updating agent modal step indicator - Current step: ${this.currentStep}, Found ${indicators.length} indicators`);
    
    if (indicators.length === 0) {
      console.warn('No step indicators found in agent modal');
      return;
    }
    
    indicators.forEach((indicator, index) => {
      const stepNum = index + 1;
      const circle = indicator.querySelector('.step-circle');
      
      if (!circle) {
        console.warn(`No step-circle found for indicator ${stepNum}`);
        return;
      }
      
      // Reset classes
      indicator.classList.remove('active', 'completed');
      circle.classList.remove('active', 'completed');
      
      if (stepNum < this.currentStep) {
        indicator.classList.add('completed');
        circle.classList.add('completed');
        console.log(`Agent modal step ${stepNum}: marked as completed`);
      } else if (stepNum === this.currentStep) {
        indicator.classList.add('active');
        circle.classList.add('active');
        console.log(`Agent modal step ${stepNum}: marked as active`);
      } else {
        console.log(`Agent modal step ${stepNum}: unmarked (future step)`);
      }
    });
  }

  updateNavigationButtons() {
    const nextBtn = document.getElementById('agent-modal-next');
    const prevBtn = document.getElementById('agent-modal-prev');
    const saveBtn = document.getElementById('agent-modal-save-btn');
    const skipBtn = document.getElementById('agent-modal-skip');
    
    // Previous button
    if (prevBtn) {
      if (this.currentStep === 1) {
        prevBtn.classList.add('d-none');
      } else {
        prevBtn.classList.remove('d-none');
      }
    }
    
    // Skip button - show on steps 2-5, hide on first and last step
    if (skipBtn) {
      if (this.currentStep === 1 || this.currentStep === this.maxSteps) {
        skipBtn.classList.add('d-none');
      } else {
        skipBtn.classList.remove('d-none');
      }
    }
    
    // Next/Save button
    if (this.currentStep === this.maxSteps) {
      if (nextBtn) nextBtn.classList.add('d-none');
      if (saveBtn) saveBtn.classList.remove('d-none');
    } else {
      if (nextBtn) nextBtn.classList.remove('d-none');
      if (saveBtn) saveBtn.classList.add('d-none');
    }
  }

  canSubmitTemplate() {
    if (!window.appSettings || !window.appSettings.enable_agent_template_gallery) {
      return false;
    }
    if (this.isAdmin) {
      return true;
    }
    if (window.appSettings.allow_user_agents === false) {
      return false;
    }
    return window.appSettings.agent_templates_allow_user_submission !== false;
  }

  updateTemplateButtonVisibility() {
    if (!this.templateSubmitButton) {
      return;
    }
    const shouldShow = this.canSubmitTemplate() && this.currentStep === this.maxSteps;
    this.templateSubmitButton.classList.toggle('d-none', !shouldShow);
  }

  validateCurrentStep() {
    switch (this.currentStep) {
      case 1: // Basic Info
        const displayName = document.getElementById('agent-display-name');
        const description = document.getElementById('agent-description');
        
        if (!displayName || !displayName.value.trim()) {
          this.showError('Please enter a display name for the agent.');
          if (displayName) displayName.focus();
          return false;
        }
        
        if (!description || !description.value.trim()) {
          this.showError('Please enter a description for the agent.');
          if (description) description.focus();
          return false;
        }
        break;
        
      case 2: // Model & Connection
        if (this.isAnyFoundryType()) {
          const endpoint = document.getElementById('agent-foundry-endpoint');
          const deployment = document.getElementById('agent-foundry-deployment');
          if (!endpoint || !endpoint.value.trim()) {
            this.showError('A Foundry project endpoint is required.');
            endpoint?.focus();
            return false;
          }
          if (!deployment || !deployment.value.trim()) {
            this.showError('A Foundry project name is required.');
            deployment?.focus();
            return false;
          }
          if (this.isClassicFoundryType()) {
            const apiVersion = document.getElementById('agent-foundry-api-version');
            const agentId = document.getElementById('agent-foundry-agent-id');
            if (!apiVersion || !apiVersion.value.trim()) {
              this.showError('Classic Foundry API version is required.');
              apiVersion?.focus();
              return false;
            }
            if (!agentId || !agentId.value.trim()) {
              this.showError('Foundry agent ID is required.');
              agentId?.focus();
              return false;
            }
          } else if (this.isNewFoundryType()) {
            const responsesApiVersion = document.getElementById('agent-new-foundry-responses-api-version');
            const applicationName = document.getElementById('agent-new-foundry-application-name');
            if (!responsesApiVersion || !responsesApiVersion.value.trim()) {
              this.showError('Provide a New Foundry Responses API version before continuing.');
              return false;
            }
            if (!applicationName || !applicationName.value.trim()) {
              this.showError('Provide or fetch an application name for New Foundry.');
              applicationName?.focus();
              return false;
            }
          } else if (this.isFoundryWorkflowType()) {
            const responsesApiVersion = document.getElementById('agent-foundry-workflow-responses-api-version');
            const workflowName = document.getElementById('agent-foundry-workflow-name');
            if (!responsesApiVersion || !responsesApiVersion.value.trim()) {
              this.showError('Provide a Foundry workflow Responses API version before continuing.');
              responsesApiVersion?.focus();
              return false;
            }
            if (!workflowName || !workflowName.value.trim()) {
              this.showError('Provide or fetch a workflow name for Foundry Workflow.');
              workflowName?.focus();
              return false;
            }
          }
        }
        break;
        
      case 3: // Instructions
        const instructionsValue = this.getInstructionsValue();
          if (!this.isAnyFoundryType()) {
            if (!instructionsValue.trim()) {
              this.showError('Please provide instructions for the agent.');
              this.refreshInstructionsEditor(true);
              return false;
            }
          } else {
            // Ensure placeholder present
            if (!instructionsValue.trim()) {
              this.setInstructionsValue(this.foundryPlaceholderInstructions);
            }
          }
        break;
        
      case 4: // Actions
        if (!this.isAnyFoundryType()) {
          // Actions validation would go here if needed
        }
        break;
        
      case 5: // Assigned Knowledge
        if (!this.validateAssignedKnowledgeStep()) {
          return false;
        }
        break;

      case 6: // Advanced
        // Advanced settings validation would go here if needed
        break;
        
      case 7: // Summary
        // Final validation would go here
        break;
    }
    
    this.hideError();
    return true;
  }

  showError(message) {
    const errorDiv = document.getElementById('agent-modal-error');
    if (errorDiv) {
      errorDiv.textContent = message;
      errorDiv.classList.remove('d-none');
      errorDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  hideError() {
    const errorDiv = document.getElementById('agent-modal-error');
    if (errorDiv) {
      errorDiv.classList.add('d-none');
    }
  }

  async loadAvailableActions() {
    const container = document.getElementById('agent-actions-container');
    const noActionsMsg = document.getElementById('agent-no-actions-message');
    
    if (!container) return;
    
    try {
      // Show loading state
      container.innerHTML = '<div class="col-12 text-center"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div><p class="mt-2">Loading available actions...</p></div>';
      
      // Use appropriate endpoint based on context
      const endpoint = this.isAdmin ? '/api/admin/plugins' : '/api/user/plugins';
      const response = await fetch(endpoint);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const data = await response.json();
      const actions = data.actions || data || [];
      
      // Filter to only show global actions in admin context
      const filteredActions = this.isAdmin 
        ? actions.filter(action => action.is_global !== false) // Only global actions
        : actions; // All actions (personal + global when merged)
      
      // Sort actions alphabetically by display name
      filteredActions.sort((a, b) => {
        const nameA = (a.display_name || a.name || '').toLowerCase();
        const nameB = (b.display_name || b.name || '').toLowerCase();
        return nameA.localeCompare(nameB);
      });
      this.availableActions = filteredActions;
      
      // Clear container
      container.innerHTML = '';
      
      if (filteredActions.length === 0) {
        // Show no actions message
        container.style.display = 'none';
        if (noActionsMsg) {
          noActionsMsg.classList.remove('d-none');
        }
        return;
      }
      
      // Hide no actions message
      container.style.display = '';
      if (noActionsMsg) {
        noActionsMsg.classList.add('d-none');
      }
      
      // Populate action cards
      filteredActions.forEach(action => {
        const actionCard = this.createActionCard(action);
        container.appendChild(actionCard);
      });
      
      // Initialize search and filter functionality
      this.initializeActionSearch(actions);
      
      // Pre-select actions if editing an existing agent
      if (this.actionsToSelect && Array.isArray(this.actionsToSelect)) {
        this.setSelectedActions(this.actionsToSelect);
        this.actionsToSelect = null; // Clear after use
      }
      
    } catch (error) {
      console.error('Error loading actions:', error);
      container.innerHTML = '<div class="col-12"><div class="alert alert-warning">Unable to load actions. Please try again.</div></div>';
    }
  }

  getFormModelName() {
    if (this.isClassicFoundryType()) {
      const foundryDeployment = document.getElementById('agent-foundry-deployment');
      return foundryDeployment?.value?.trim() || '-';
    }
    if (this.isFoundryWorkflowType()) {
      const workflowName = document.getElementById('agent-foundry-workflow-name');
      return workflowName?.value?.trim() || '-';
    }
    if (this.isNewFoundryType()) {
      const applicationName = document.getElementById('agent-new-foundry-application-name');
      const applicationId = document.getElementById('agent-new-foundry-application-id');
      return applicationName?.value?.trim() || applicationId?.value?.trim() || '-';
    }
    const customConnection = document.getElementById('agent-custom-connection')?.checked || false;
    let modelName = '-';
    if (customConnection) {
      const apimToggle = document.getElementById('agent-enable-apim');
      if (apimToggle && apimToggle.checked) {
        const apimDeployment = document.getElementById('agent-apim-deployment');
        modelName = apimDeployment?.value?.trim() || '-';
      } else {
        const gptDeployment = document.getElementById('agent-gpt-deployment');
        modelName = gptDeployment?.value?.trim() || '-';
      }
    } else {
      const modelSelect = document.getElementById('agent-global-model-select');
      modelName = modelSelect?.options[modelSelect.selectedIndex]?.text || '-';
    }
    return modelName;
  }

  populateSummary() {
    // Basic Information
    const displayName = document.getElementById('agent-display-name')?.value || '-';
    const generatedName = document.getElementById('agent-name')?.value || '-';
    const description = document.getElementById('agent-description')?.value || '-';
    const agentType = this.currentAgentType || 'local';
    
    // Model & Connection
    const customConnection = document.getElementById('agent-custom-connection')?.checked ? 'Yes' : 'No';
    const modelName = this.getFormModelName();
    
    // Instructions
    const instructions = this.getInstructionsValue() || '-';
    
    // Selected Actions
    const selectedActions = this.getSelectedActions();
    const actionsCount = selectedActions.length;
    
    // Update basic information
    this.renderAgentSummaryIcon();
    document.getElementById('summary-display-name').textContent = displayName;
    document.getElementById('summary-name').textContent = generatedName;
    document.getElementById('summary-description').textContent = description;
    
    // Update configuration
    document.getElementById('summary-model').textContent = modelName;
    document.getElementById('summary-custom-connection').textContent = customConnection;
    const typeBadge = document.getElementById('summary-agent-type-badge');
    if (typeBadge) {
      typeBadge.textContent = this.getAgentTypeLabel(agentType);
      typeBadge.className = this.isFoundryWorkflowType(agentType)
        ? 'badge bg-success'
        : this.isNewFoundryType(agentType)
        ? 'badge bg-primary'
        : this.isClassicFoundryType(agentType)
          ? 'badge bg-warning text-dark'
          : 'badge bg-info';
    }
    
    // Update instructions
    document.getElementById('summary-instructions').textContent = instructions;
    
    // Update actions count badge
    const countBadge = document.getElementById('summary-actions-count-badge');
    if (countBadge) {
      countBadge.textContent = actionsCount;
    }
    
    // Update actions list
    const actionsListContainer = document.getElementById('summary-actions-list');
    const actionsEmptyContainer = document.getElementById('summary-actions-empty');
    
    if (this.isAnyFoundryType()) {
      // Hide actions entirely for Foundry
      const actionsSection = document.getElementById('summary-actions-section');
      if (actionsSection) actionsSection.style.display = 'none';
    } else if (actionsCount > 0) {
      // Show actions list, hide empty message
      actionsListContainer.style.display = 'block';
      actionsEmptyContainer.style.display = 'none';
      const actionsSection = document.getElementById('summary-actions-section');
      if (actionsSection) actionsSection.style.display = '';
      
      // Clear existing content
      actionsListContainer.innerHTML = '';
      
      // Create action cards
      selectedActions.forEach(action => {
        const col = document.createElement('div');
        col.className = 'col-md-6 col-lg-4';
        
        const actionCard = document.createElement('div');
        actionCard.className = 'summary-action-card';
        
        const actionTitle = document.createElement('div');
        actionTitle.className = 'action-title d-flex align-items-center justify-content-between';
        
        const titleText = document.createElement('span');
        titleText.textContent = action.display_name || action.name || 'Unknown Action';
        actionTitle.appendChild(titleText);
        
        // Add global tag if this is a global action
        if (action.is_global) {
          const globalTag = document.createElement('span');
          globalTag.className = 'badge bg-info text-dark ms-2';
          globalTag.style.fontSize = '0.65rem';
          globalTag.textContent = 'global';
          actionTitle.appendChild(globalTag);
        }
        
        const actionDescription = document.createElement('div');
        actionDescription.className = 'action-description';
        const desc = action.description || 'No description available';
        actionDescription.textContent = desc.length > 80 ? desc.substring(0, 80) + '...' : desc;
        
        actionCard.appendChild(actionTitle);
        actionCard.appendChild(actionDescription);
        col.appendChild(actionCard);
        actionsListContainer.appendChild(col);
      });
    } else {
      // Hide actions list, show empty message
      actionsListContainer.style.display = 'none';
      actionsEmptyContainer.style.display = 'block';
      const actionsSection = document.getElementById('summary-actions-section');
      if (actionsSection) actionsSection.style.display = '';
    }

    this.populateAssignedKnowledgeSummary();
    
    // Update creation date
    const createdDate = document.getElementById('summary-created-date');
    if (createdDate) {
      const now = new Date();
      createdDate.textContent = now.toLocaleDateString() + ' at ' + now.toLocaleTimeString();
    }
    
    // Populate changes summary
    this.populateChangesSummary();
  }

  populateAssignedKnowledgeSummary() {
    const container = document.getElementById('summary-assigned-knowledge');
    if (!container) {
      return;
    }
    container.textContent = '';
    const assignedKnowledge = this.getAssignedKnowledgeConfig();
    if (!assignedKnowledge.enabled) {
      container.className = 'text-muted';
      container.textContent = 'No assigned knowledge configured';
      return;
    }

    container.className = 'd-flex flex-wrap gap-2';
    const scopes = assignedKnowledge.scopes || {};
    const summaryItems = [];
    if (scopes.personal) {
      summaryItems.push('Personal workspace');
    }
    if (scopes.group_ids?.length) {
      summaryItems.push(`${scopes.group_ids.length} group source${scopes.group_ids.length === 1 ? '' : 's'}`);
    }
    if (scopes.public_workspace_ids?.length) {
      summaryItems.push(`${scopes.public_workspace_ids.length} public workspace${scopes.public_workspace_ids.length === 1 ? '' : 's'}`);
    }
    if (assignedKnowledge.document_ids?.length) {
      summaryItems.push(`${assignedKnowledge.document_ids.length} specific document${assignedKnowledge.document_ids.length === 1 ? '' : 's'}`);
    }
    if (assignedKnowledge.tags?.length) {
      summaryItems.push(`${assignedKnowledge.tags.length} tag limit${assignedKnowledge.tags.length === 1 ? '' : 's'}`);
    }
    if (assignedKnowledge.web_sources?.length) {
      const deepResearchCount = assignedKnowledge.web_sources
        .filter(source => this.normalizeAssignedKnowledgeWebSourceMode(source.mode) === 'deep_research')
        .length;
      summaryItems.push(`${assignedKnowledge.web_sources.length} assigned URL${assignedKnowledge.web_sources.length === 1 ? '' : 's'}`);
      if (deepResearchCount) {
        summaryItems.push(`${deepResearchCount} Deep Research URL${deepResearchCount === 1 ? '' : 's'}`);
      }
    }
    if (this.assignedKnowledgeCatalogLoaded) {
      const resolvedCount = this.getResolvedAssignedKnowledgeDocuments(assignedKnowledge).length;
      summaryItems.push(`${resolvedCount} current document match${resolvedCount === 1 ? '' : 'es'}`);
    }
    if (assignedKnowledge.allow_user_workspace_context) {
      const actionLabels = (assignedKnowledge.allowed_user_workspace_actions || ASSIGNED_KNOWLEDGE_USER_ACTIONS)
        .map(action => action === 'compare' ? 'Compare' : action.charAt(0).toUpperCase() + action.slice(1));
      summaryItems.push(`User context: ${actionLabels.join(', ')}`);
    }

    if (!summaryItems.length) {
      const badge = document.createElement('span');
      badge.className = 'badge bg-warning text-dark';
      badge.textContent = 'Enabled, no sources selected';
      container.appendChild(badge);
      return;
    }

    summaryItems.forEach(item => {
      const badge = document.createElement('span');
      badge.className = 'badge bg-primary';
      badge.textContent = item;
      container.appendChild(badge);
    });
  }

  createActionCard(action) {
    const col = document.createElement('div');
    col.className = 'col-md-6 col-lg-4';
    
    const card = document.createElement('div');
    card.className = 'card h-100 action-card';
    card.style.cursor = 'pointer';
    card.setAttribute('data-action-id', action.id || action.name);
    card.setAttribute('data-action-type', action.type || 'custom');
    card.setAttribute('data-action-name', action.name || action.display_name || '');
    card.setAttribute('data-action-description', action.description || '');
    card.setAttribute('data-action-is-global', action.is_global ? 'true' : 'false');
    
    const cardBody = document.createElement('div');
    cardBody.className = 'card-body d-flex flex-column';
    
    const title = document.createElement('h6');
    title.className = 'card-title mb-2 d-flex align-items-center justify-content-between';
    
    const titleText = document.createElement('span');
    titleText.textContent = action.display_name || action.name || 'Untitled Action';
    title.appendChild(titleText);
    
    // Add global tag if this is a global action
    if (action.is_global) {
      const globalTag = document.createElement('span');
      globalTag.className = 'badge bg-info text-dark ms-2';
      globalTag.style.fontSize = '0.65rem';
      globalTag.textContent = 'global';
      title.appendChild(globalTag);
    }
    
    const type = document.createElement('span');
    type.className = 'badge bg-secondary mb-2';
    type.textContent = action.type || 'Custom';
    
    // Create description with truncation functionality
    const descriptionContainer = document.createElement('div');
    descriptionContainer.className = 'card-text-container flex-grow-1';
    
    const description = document.createElement('p');
    description.className = 'card-text small text-muted mb-0';
    
    const fullDescription = action.description || 'No description available';
    const maxLength = 120; // Character limit for truncation
    
    if (fullDescription.length > maxLength) {
      const truncatedText = fullDescription.substring(0, maxLength) + '...';
      
      // Create truncated and full text spans
      const truncatedSpan = document.createElement('span');
      truncatedSpan.className = 'description-truncated';
      truncatedSpan.textContent = truncatedText;
      
      const fullSpan = document.createElement('span');
      fullSpan.className = 'description-full d-none';
      fullSpan.textContent = fullDescription;
      
      // Create toggle button
      const toggleBtn = document.createElement('button');
      toggleBtn.className = 'btn btn-link btn-sm p-0 ms-1 text-decoration-none';
      toggleBtn.style.fontSize = '0.75rem';
      toggleBtn.style.verticalAlign = 'baseline';
      toggleBtn.textContent = 'more';
      
      // Add click handler for toggle (prevent card selection)
      toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isExpanded = !fullSpan.classList.contains('d-none');
        
        if (isExpanded) {
          // Show truncated
          truncatedSpan.classList.remove('d-none');
          fullSpan.classList.add('d-none');
          toggleBtn.textContent = 'more';
        } else {
          // Show full
          truncatedSpan.classList.add('d-none');
          fullSpan.classList.remove('d-none');
          toggleBtn.textContent = 'less';
        }
      });
      
      description.appendChild(truncatedSpan);
      description.appendChild(fullSpan);
      description.appendChild(toggleBtn);
    } else {
      description.textContent = fullDescription;
    }
    
    descriptionContainer.appendChild(description);
    
    const checkIcon = document.createElement('div');
    checkIcon.className = 'action-check-icon d-none';
    checkIcon.innerHTML = '<i class="bi bi-check-circle-fill text-primary"></i>';
    
    cardBody.appendChild(title);
    cardBody.appendChild(type);
    cardBody.appendChild(descriptionContainer);
    cardBody.appendChild(checkIcon);
    
    card.appendChild(cardBody);
    col.appendChild(card);
    
    // Add click handler
    card.addEventListener('click', () => {
      this.toggleActionSelection(card);
    });
    
    return col;
  }

  toggleActionSelection(card) {
    const checkIcon = card.querySelector('.action-check-icon');
    const isSelected = !card.classList.contains('border-primary');
    
    if (isSelected) {
      card.classList.add('border-primary', 'bg-light');
      checkIcon.classList.remove('d-none');
    } else {
      card.classList.remove('border-primary', 'bg-light');
      checkIcon.classList.add('d-none');
    }
    
    this.updateSelectedActionsDisplay();
  }

  updateSelectedActionsDisplay() {
    const selectedCards = document.querySelectorAll('.action-card.border-primary');
    const summaryDiv = document.getElementById('agent-selected-actions-summary');
    const listDiv = document.getElementById('agent-selected-actions-list');
    
    if (selectedCards.length > 0) {
      if (summaryDiv) summaryDiv.classList.remove('d-none');
      if (listDiv) {
        listDiv.innerHTML = '';
        selectedCards.forEach(card => {
          const actionName = card.getAttribute('data-action-name');
          const isGlobal = card.getAttribute('data-action-is-global') === 'true';
          
          const badge = document.createElement('span');
          badge.className = 'badge bg-primary me-1 mb-1';
          
          // Create badge content with global tag if needed
          if (isGlobal) {
            badge.innerHTML = `${actionName} <small class="badge bg-info text-dark ms-1" style="font-size: 0.6em;">global</small>`;
          } else {
            badge.textContent = actionName;
          }
          
          listDiv.appendChild(badge);
        });
      }
    } else {
      if (summaryDiv) summaryDiv.classList.add('d-none');
    }

    this.renderSimpleChatCapabilitySections();
    this.renderMsGraphCapabilitySections();
    this.renderChartCapabilitySections();
  }

  getDefaultSimpleChatCapabilities(actionId = '', actionName = '') {
    const defaults = {};
    SIMPLECHAT_CAPABILITY_DEFINITIONS.forEach(definition => {
      defaults[definition.key] = true;
    });

    const action = (this.availableActions || []).find(candidate => {
      const candidateId = String(candidate?.id || candidate?.name || '').trim();
      const candidateName = String(candidate?.name || candidate?.display_name || '').trim();
      return (actionId && candidateId === actionId) || (actionName && candidateName === actionName);
    });

    const rawCapabilities = action?.additionalFields?.simplechat_capabilities
      || action?.additional_fields?.simplechat_capabilities
      || action?.simplechat_capabilities;

    if (rawCapabilities && typeof rawCapabilities === 'object' && !Array.isArray(rawCapabilities)) {
      SIMPLECHAT_CAPABILITY_DEFINITIONS.forEach(definition => {
        if (Object.prototype.hasOwnProperty.call(rawCapabilities, definition.key)) {
          defaults[definition.key] = Boolean(rawCapabilities[definition.key]);
        }
      });
      if (Object.prototype.hasOwnProperty.call(rawCapabilities, 'upload_markdown_document')) {
        const uploadEnabled = Boolean(rawCapabilities.upload_markdown_document);
        ['upload_word_document', 'upload_powerpoint_document'].forEach(capabilityKey => {
          if (!Object.prototype.hasOwnProperty.call(rawCapabilities, capabilityKey)) {
            defaults[capabilityKey] = uploadEnabled;
          }
        });
      }
    }

    return defaults;
  }

  getParsedAdditionalSettings() {
    const settingsField = document.getElementById('agent-additional-settings');
    const rawValue = settingsField?.value?.trim() || '{}';

    try {
      const parsed = JSON.parse(rawValue);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (error) {
      console.warn('Unable to parse agent additional settings while rendering capabilities:', error);
      return {};
    }
  }

  setParsedAdditionalSettings(settings) {
    const settingsField = document.getElementById('agent-additional-settings');
    if (!settingsField) {
      return;
    }
    settingsField.value = JSON.stringify(settings || {}, null, 2);
  }

  getActionCapabilityMap() {
    const otherSettings = this.getParsedAdditionalSettings();
    const capabilityMap = otherSettings[ACTION_CAPABILITIES_KEY];
    return capabilityMap && typeof capabilityMap === 'object' && !Array.isArray(capabilityMap)
      ? capabilityMap
      : {};
  }

  getSimpleChatCapabilitiesForAction(actionId, actionName) {
    const defaults = this.getDefaultSimpleChatCapabilities(actionId, actionName);
    const capabilityMap = this.getActionCapabilityMap();
    const storedCapabilities = capabilityMap[actionId] || capabilityMap[actionName] || {};

    SIMPLECHAT_CAPABILITY_DEFINITIONS.forEach(definition => {
      if (Object.prototype.hasOwnProperty.call(storedCapabilities, definition.key)) {
        defaults[definition.key] = Boolean(storedCapabilities[definition.key]);
      }
    });
    if (Object.prototype.hasOwnProperty.call(storedCapabilities, 'upload_markdown_document')) {
      const uploadEnabled = Boolean(storedCapabilities.upload_markdown_document);
      ['upload_word_document', 'upload_powerpoint_document'].forEach(capabilityKey => {
        if (!Object.prototype.hasOwnProperty.call(storedCapabilities, capabilityKey)) {
          defaults[capabilityKey] = uploadEnabled;
        }
      });
    }

    return defaults;
  }

  updateSimpleChatCapabilities(actionId, actionName, nextCapabilities) {
    const otherSettings = this.getParsedAdditionalSettings();
    const capabilityMap = this.getActionCapabilityMap();
    capabilityMap[actionId || actionName] = { ...nextCapabilities };
    otherSettings[ACTION_CAPABILITIES_KEY] = capabilityMap;
    this.setParsedAdditionalSettings(otherSettings);
  }

  renderSimpleChatCapabilitySections() {
    const container = document.getElementById('agent-simplechat-capabilities');
    const list = document.getElementById('agent-simplechat-capabilities-list');
    if (!container || !list) {
      return;
    }

    const selectedSimpleChatCards = Array.from(document.querySelectorAll('.action-card.border-primary')).filter(card => {
      return (card.getAttribute('data-action-type') || '').toLowerCase() === 'simplechat';
    });

    if (!selectedSimpleChatCards.length || this.isAnyFoundryType()) {
      container.classList.add('d-none');
      list.innerHTML = '';
      return;
    }

    container.classList.remove('d-none');
    list.innerHTML = '';

    selectedSimpleChatCards.forEach(card => {
      const actionId = card.getAttribute('data-action-id') || card.getAttribute('data-action-name') || '';
      const actionName = card.getAttribute('data-action-name') || actionId;
      const capabilities = this.getSimpleChatCapabilitiesForAction(actionId, actionName);

      const section = document.createElement('div');
      section.className = 'border rounded p-3 bg-light';

      const heading = document.createElement('div');
      heading.className = 'fw-semibold mb-1';
      heading.textContent = actionName;
      section.appendChild(heading);

      const helperText = document.createElement('div');
      helperText.className = 'text-muted small mb-3';
      helperText.textContent = 'These capability toggles apply only to this agent assignment.';
      section.appendChild(helperText);

      SIMPLECHAT_CAPABILITY_DEFINITIONS.forEach(definition => {
        const wrapper = document.createElement('div');
        wrapper.className = 'form-check mb-2';

        const checkbox = document.createElement('input');
        checkbox.className = 'form-check-input';
        checkbox.type = 'checkbox';
        checkbox.id = `simplechat-capability-${actionId}-${definition.key}`;
        checkbox.checked = Boolean(capabilities[definition.key]);

        const label = document.createElement('label');
        label.className = 'form-check-label';
        label.setAttribute('for', checkbox.id);
        label.innerHTML = `<span class="fw-medium">${this.escapeHtml(definition.label)}</span><br><span class="text-muted small">${this.escapeHtml(definition.description)}</span>`;

        checkbox.addEventListener('change', () => {
          const updatedCapabilities = this.getSimpleChatCapabilitiesForAction(actionId, actionName);
          updatedCapabilities[definition.key] = checkbox.checked;
          this.updateSimpleChatCapabilities(actionId, actionName, updatedCapabilities);
        });

        wrapper.appendChild(checkbox);
        wrapper.appendChild(label);
        section.appendChild(wrapper);
      });

      list.appendChild(section);
    });
  }

  getDefaultMsGraphCapabilities(actionId = '', actionName = '') {
    const defaults = {};
    MSGRAPH_CAPABILITY_DEFINITIONS.forEach(definition => {
      defaults[definition.key] = true;
    });

    const action = (this.availableActions || []).find(candidate => {
      const candidateId = String(candidate?.id || candidate?.name || '').trim();
      const candidateName = String(candidate?.name || candidate?.display_name || '').trim();
      return (actionId && candidateId === actionId) || (actionName && candidateName === actionName);
    });

    const rawCapabilities = action?.additionalFields?.msgraph_capabilities
      || action?.additional_fields?.msgraph_capabilities
      || action?.msgraph_capabilities;

    if (rawCapabilities && typeof rawCapabilities === 'object' && !Array.isArray(rawCapabilities)) {
      MSGRAPH_CAPABILITY_DEFINITIONS.forEach(definition => {
        if (Object.prototype.hasOwnProperty.call(rawCapabilities, definition.key)) {
          defaults[definition.key] = Boolean(rawCapabilities[definition.key]);
        }
      });
    }

    return defaults;
  }

  getMsGraphCapabilitiesForAction(actionId, actionName) {
    const defaults = this.getDefaultMsGraphCapabilities(actionId, actionName);
    const capabilityMap = this.getActionCapabilityMap();
    const storedCapabilities = capabilityMap[actionId] || capabilityMap[actionName] || {};

    MSGRAPH_CAPABILITY_DEFINITIONS.forEach(definition => {
      if (Object.prototype.hasOwnProperty.call(storedCapabilities, definition.key)) {
        defaults[definition.key] = Boolean(storedCapabilities[definition.key]);
      }
    });

    return defaults;
  }

  updateMsGraphCapabilities(actionId, actionName, nextCapabilities) {
    const otherSettings = this.getParsedAdditionalSettings();
    const capabilityMap = this.getActionCapabilityMap();
    capabilityMap[actionId || actionName] = { ...nextCapabilities };
    otherSettings[ACTION_CAPABILITIES_KEY] = capabilityMap;
    this.setParsedAdditionalSettings(otherSettings);
  }

  renderMsGraphCapabilitySections() {
    const container = document.getElementById('agent-msgraph-capabilities');
    const list = document.getElementById('agent-msgraph-capabilities-list');
    if (!container || !list) {
      return;
    }

    const selectedMsGraphCards = Array.from(document.querySelectorAll('.action-card.border-primary')).filter(card => {
      return (card.getAttribute('data-action-type') || '').toLowerCase() === 'msgraph';
    });

    if (!selectedMsGraphCards.length || this.isAnyFoundryType()) {
      container.classList.add('d-none');
      list.innerHTML = '';
      return;
    }

    container.classList.remove('d-none');
    list.innerHTML = '';

    selectedMsGraphCards.forEach(card => {
      const actionId = card.getAttribute('data-action-id') || card.getAttribute('data-action-name') || '';
      const actionName = card.getAttribute('data-action-name') || actionId;
      const capabilities = this.getMsGraphCapabilitiesForAction(actionId, actionName);

      const section = document.createElement('div');
      section.className = 'border rounded p-3 bg-light';

      const heading = document.createElement('div');
      heading.className = 'fw-semibold mb-1';
      heading.textContent = actionName;
      section.appendChild(heading);

      const helperText = document.createElement('div');
      helperText.className = 'text-muted small mb-3';
      helperText.textContent = 'These capability toggles apply only to this agent assignment.';
      section.appendChild(helperText);

      MSGRAPH_CAPABILITY_DEFINITIONS.forEach(definition => {
        const wrapper = document.createElement('div');
        wrapper.className = 'form-check mb-2';

        const checkbox = document.createElement('input');
        checkbox.className = 'form-check-input';
        checkbox.type = 'checkbox';
        checkbox.id = `msgraph-capability-${actionId}-${definition.key}`;
        checkbox.checked = Boolean(capabilities[definition.key]);

        const label = document.createElement('label');
        label.className = 'form-check-label';
        label.setAttribute('for', checkbox.id);
        label.innerHTML = `<span class="fw-medium">${this.escapeHtml(definition.label)}</span><br><span class="text-muted small">${this.escapeHtml(definition.description)}</span>`;

        checkbox.addEventListener('change', () => {
          const updatedCapabilities = this.getMsGraphCapabilitiesForAction(actionId, actionName);
          updatedCapabilities[definition.key] = checkbox.checked;
          this.updateMsGraphCapabilities(actionId, actionName, updatedCapabilities);
        });

        wrapper.appendChild(checkbox);
        wrapper.appendChild(label);
        section.appendChild(wrapper);
      });

      list.appendChild(section);
    });
  }

  getDefaultChartCapabilities(actionId = '', actionName = '') {
    const defaults = {};
    CHART_CAPABILITY_DEFINITIONS.forEach(definition => {
      defaults[definition.key] = true;
    });

    const action = (this.availableActions || []).find(candidate => {
      const candidateId = String(candidate?.id || candidate?.name || '').trim();
      const candidateName = String(candidate?.name || candidate?.display_name || '').trim();
      return (actionId && candidateId === actionId) || (actionName && candidateName === actionName);
    });

    const rawCapabilities = action?.additionalFields?.chart_capabilities
      || action?.additional_fields?.chart_capabilities
      || action?.chart_capabilities;

    if (rawCapabilities && typeof rawCapabilities === 'object' && !Array.isArray(rawCapabilities)) {
      CHART_CAPABILITY_DEFINITIONS.forEach(definition => {
        if (Object.prototype.hasOwnProperty.call(rawCapabilities, definition.key)) {
          defaults[definition.key] = Boolean(rawCapabilities[definition.key]);
        }
      });
    }

    return defaults;
  }

  getChartCapabilitiesForAction(actionId, actionName) {
    const defaults = this.getDefaultChartCapabilities(actionId, actionName);
    const capabilityMap = this.getActionCapabilityMap();
    const storedCapabilities = capabilityMap[actionId] || capabilityMap[actionName] || {};

    CHART_CAPABILITY_DEFINITIONS.forEach(definition => {
      if (Object.prototype.hasOwnProperty.call(storedCapabilities, definition.key)) {
        defaults[definition.key] = Boolean(storedCapabilities[definition.key]);
      }
    });

    return defaults;
  }

  updateChartCapabilities(actionId, actionName, nextCapabilities) {
    const otherSettings = this.getParsedAdditionalSettings();
    const capabilityMap = this.getActionCapabilityMap();
    capabilityMap[actionId || actionName] = { ...nextCapabilities };
    otherSettings[ACTION_CAPABILITIES_KEY] = capabilityMap;
    this.setParsedAdditionalSettings(otherSettings);
  }

  renderChartCapabilitySections() {
    const container = document.getElementById('agent-chart-capabilities');
    const list = document.getElementById('agent-chart-capabilities-list');
    if (!container || !list) {
      return;
    }

    const selectedChartCards = Array.from(document.querySelectorAll('.action-card.border-primary')).filter(card => {
      return (card.getAttribute('data-action-type') || '').toLowerCase() === 'chart';
    });

    if (!selectedChartCards.length || this.isAnyFoundryType()) {
      container.classList.add('d-none');
      list.innerHTML = '';
      return;
    }

    container.classList.remove('d-none');
    list.innerHTML = '';

    selectedChartCards.forEach(card => {
      const actionId = card.getAttribute('data-action-id') || card.getAttribute('data-action-name') || '';
      const actionName = card.getAttribute('data-action-name') || actionId;
      const capabilities = this.getChartCapabilitiesForAction(actionId, actionName);

      const section = document.createElement('div');
      section.className = 'border rounded p-3 bg-light';

      const heading = document.createElement('div');
      heading.className = 'fw-semibold mb-1';
      heading.textContent = actionName;
      section.appendChild(heading);

      const helperText = document.createElement('div');
      helperText.className = 'text-muted small mb-3';
      helperText.textContent = 'These chart type toggles apply only to this agent assignment.';
      section.appendChild(helperText);

      CHART_CAPABILITY_DEFINITIONS.forEach(definition => {
        const wrapper = document.createElement('div');
        wrapper.className = 'form-check mb-2';

        const checkbox = document.createElement('input');
        checkbox.className = 'form-check-input';
        checkbox.type = 'checkbox';
        checkbox.id = `chart-capability-${actionId}-${definition.key}`;
        checkbox.checked = Boolean(capabilities[definition.key]);

        const label = document.createElement('label');
        label.className = 'form-check-label';
        label.setAttribute('for', checkbox.id);
        label.innerHTML = `<span class="fw-medium">${this.escapeHtml(definition.label)}</span><br><span class="text-muted small">${this.escapeHtml(definition.description)}</span>`;

        checkbox.addEventListener('change', () => {
          const updatedCapabilities = this.getChartCapabilitiesForAction(actionId, actionName);
          updatedCapabilities[definition.key] = checkbox.checked;
          this.updateChartCapabilities(actionId, actionName, updatedCapabilities);
        });

        wrapper.appendChild(checkbox);
        wrapper.appendChild(label);
        section.appendChild(wrapper);
      });

      list.appendChild(section);
    });
  }

  initializeActionSearch(actions) {
    const searchInput = document.getElementById('agent-action-search');
    const typeFilter = document.getElementById('agent-action-type-filter');
    const clearBtn = document.getElementById('agent-action-clear-search');
    const selectAllBtn = document.getElementById('agent-select-all-visible');
    const deselectAllBtn = document.getElementById('agent-deselect-all');
    const showSelectedBtn = document.getElementById('agent-toggle-selected-only');
    
    // Populate type filter
    if (typeFilter) {
      const types = [...new Set(actions.map(a => a.type || 'custom'))];
      typeFilter.innerHTML = '<option value="">All Types</option>';
      types.forEach(type => {
        const option = document.createElement('option');
        option.value = type;
        option.textContent = type.charAt(0).toUpperCase() + type.slice(1);
        typeFilter.appendChild(option);
      });
    }
    
    // Search and filter functionality
    const performFilter = () => {
      const searchTerm = searchInput ? searchInput.value.toLowerCase() : '';
      const selectedType = typeFilter ? typeFilter.value : '';
      const cards = document.querySelectorAll('.action-card');
      let visibleCount = 0;
      
      cards.forEach(card => {
        const name = card.getAttribute('data-action-name').toLowerCase();
        const description = card.getAttribute('data-action-description').toLowerCase();
        const type = card.getAttribute('data-action-type');
        
        const matchesSearch = searchTerm === '' || name.includes(searchTerm) || description.includes(searchTerm);
        const matchesType = selectedType === '' || type === selectedType;
        
        if (matchesSearch && matchesType) {
          card.parentElement.style.display = '';
          visibleCount++;
        } else {
          card.parentElement.style.display = 'none';
        }
      });
      
      // Update results count
      const resultsSpan = document.getElementById('agent-action-results-count');
      if (resultsSpan) {
        resultsSpan.textContent = `${visibleCount} action${visibleCount !== 1 ? 's' : ''} found`;
      }
    };
    
    if (searchInput) {
      searchInput.addEventListener('input', performFilter);
    }
    if (typeFilter) {
      typeFilter.addEventListener('change', performFilter);
    }
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        if (searchInput) searchInput.value = '';
        if (typeFilter) typeFilter.value = '';
        performFilter();
      });
    }
    
    // Button handlers
    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', () => {
        const visibleCards = document.querySelectorAll('.action-card[style=""], .action-card:not([style*="display: none"])');
        visibleCards.forEach(card => {
          if (!card.classList.contains('border-primary')) {
            this.toggleActionSelection(card);
          }
        });
      });
    }
    
    if (deselectAllBtn) {
      deselectAllBtn.addEventListener('click', () => {
        const selectedCards = document.querySelectorAll('.action-card.border-primary');
        selectedCards.forEach(card => {
          this.toggleActionSelection(card);
        });
      });
    }
    
    // Initial filter
    performFilter();
  }

  getSelectedActions() {
    const selectedCards = document.querySelectorAll('.action-card.border-primary');
    return Array.from(selectedCards).map(card => {
      const actionId = card.getAttribute('data-action-id');
      const actionName = card.getAttribute('data-action-name');
      const actionDescription = card.getAttribute('data-action-description');
      
      return {
        id: actionId,
        name: actionName,
        display_name: actionName,
        description: actionDescription
      };
    });
  }

  getSelectedActionIds() {
    const selectedCards = document.querySelectorAll('.action-card.border-primary');
    return Array.from(selectedCards).map(card => card.getAttribute('data-action-id'));
  }

  setSelectedActions(actionIds) {
    if (!Array.isArray(actionIds)) return;
    
    console.log('setSelectedActions called with:', actionIds);
    
    const allCards = document.querySelectorAll('.action-card');
    console.log('Found action cards:', allCards.length);
    
    allCards.forEach(card => {
      const actionId = card.getAttribute('data-action-id');
      const actionName = card.getAttribute('data-action-name');
      
      console.log('Checking card - ID:', actionId, 'Name:', actionName);
      
      // Check if either the UUID (actionId) or name (actionName) matches
      const isMatch = actionIds.includes(actionId) || actionIds.includes(actionName);
      
      if (isMatch) {
        console.log('Matching action found, selecting:', { actionId, actionName });
        if (!card.classList.contains('border-primary')) {
          this.toggleActionSelection(card);
        }
      } else {
        if (card.classList.contains('border-primary')) {
          this.toggleActionSelection(card);
        }
      }
    });
  }

  detectChanges() {
    if (!this.originalAgent) {
      return null; // No original to compare against
    }

    try {
      const changes = {};
      
      // Get current values
      const currentDisplayName = document.getElementById('agent-display-name')?.value || '';
      const currentName = document.getElementById('agent-name')?.value || '';
      const currentDescription = document.getElementById('agent-description')?.value || '';
      const currentInstructions = this.getInstructionsValue() || '';
      
      // Custom connection
      const currentCustomConnection = document.getElementById('agent-custom-connection')?.checked || false;

      // Model selection
      const currentModel = this.getFormModelName();
      
      // Selected actions
      const currentActions = this.getSelectedActionIds();
      const originalActions = this.originalAgent.actions_to_load || [];
      const currentAssignedKnowledge = this.normalizeAssignedKnowledge(this.getAssignedKnowledgeConfig());
      const originalAssignedKnowledge = this.normalizeAssignedKnowledge(this.originalAgent.other_settings?.[ASSIGNED_KNOWLEDGE_KEY]);
      
      // Compare fields
      if (currentDisplayName !== (this.originalAgent.display_name || '')) {
        changes.displayName = {
          before: this.originalAgent.display_name || '',
          after: currentDisplayName
        };
      }
      
      if (currentName !== (this.originalAgent.name || '')) {
        changes.name = {
          before: this.originalAgent.name || '',
          after: currentName
        };
      }
      
      if (currentDescription !== (this.originalAgent.description || '')) {
        changes.description = {
          before: this.originalAgent.description || '',
          after: currentDescription
        };
      }
      
      if (currentInstructions !== (this.originalAgent.instructions || '')) {
        changes.instructions = {
          before: this.originalAgent.instructions || '',
          after: currentInstructions
        };
      }
      
      if (currentModel !== (this.originalAgent.model || '')) {
        changes.model = {
          before: this.originalAgent.model || '',
          after: currentModel
        };
      }
      
      if (currentCustomConnection !== (this.originalAgent.custom_connection || false)) {
        changes.customConnection = {
          before: this.originalAgent.custom_connection ? 'Yes' : 'No',
          after: currentCustomConnection ? 'Yes' : 'No'
        };
      }
      
      // Compare actions (check if arrays are different)
      const actionsChanged = JSON.stringify(currentActions.sort()) !== JSON.stringify(originalActions.sort());
      if (actionsChanged) {
        changes.actions = {
          before: originalActions.join(', ') || '(none)',
          after: currentActions.join(', ') || '(none)'
        };
      }

      if (JSON.stringify(currentAssignedKnowledge) !== JSON.stringify(originalAssignedKnowledge)) {
        changes.assignedKnowledge = {
          before: originalAssignedKnowledge.enabled ? 'Enabled' : 'Disabled',
          after: currentAssignedKnowledge.enabled ? 'Enabled' : 'Disabled'
        };
      }
      
      return Object.keys(changes).length > 0 ? changes : null;
    } catch (error) {
      console.error('Error detecting changes:', error);
      return null;
    }
  }

  populateChangesSummary() {
    const changesSection = document.getElementById('summary-changes-section');
    const changesContent = document.getElementById('summary-changes-content');
    
    // Detect changes
    const changes = this.detectChanges();
    
    if (changes && Object.keys(changes).length > 0) {
      // Show changes section
      changesSection.style.display = '';
      
      // Build changes HTML
      let changesHtml = '';
      
      for (const [field, change] of Object.entries(changes)) {
        const fieldLabel = this.getFieldLabel(field);
        changesHtml += `
          <div class="mb-3">
            <div class="fw-medium text-primary mb-1">${this.escapeHtml(fieldLabel)}</div>
            <div class="row g-2">
              <div class="col-md-6">
                <div class="small text-muted mb-1">Before:</div>
                <div class="border rounded p-2 bg-light">
                  <code class="small">${this.escapeHtml(change.before || '(empty)')}</code>
                </div>
              </div>
              <div class="col-md-6">
                <div class="small text-muted mb-1">After:</div>
                <div class="border rounded p-2 bg-success-subtle">
                  <code class="small">${this.escapeHtml(change.after || '(empty)')}</code>
                </div>
              </div>
            </div>
          </div>
        `;
      }
      
      changesContent.innerHTML = changesHtml;
    } else {
      // Hide changes section if no changes
      changesSection.style.display = 'none';
    }
  }

  getFieldLabel(field) {
    const labels = {
      displayName: 'Display Name',
      name: 'Generated Name',
      description: 'Description',
      instructions: 'Instructions',
      model: 'Model',
      customConnection: 'Custom Connection',
      actions: 'Selected Actions',
      assignedKnowledge: 'Assigned Knowledge'
    };
    return labels[field] || field;
  }

  escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  normalizeAgentIconPayload(iconPayload) {
    if (!iconPayload || typeof iconPayload !== 'object' || Array.isArray(iconPayload)) {
      return null;
    }

    const kind = String(iconPayload.kind || '').trim().toLowerCase();
    const value = String(iconPayload.value || '').trim();
    if (kind === 'bootstrap' && /^bi-[a-z0-9][a-z0-9-]{0,80}$/.test(value)) {
      return { kind, value };
    }
    if (kind === 'image' && /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(value) && value.length <= 350000) {
      return { kind, value };
    }
    return null;
  }

  renderAgentSummaryIcon() {
    const container = document.getElementById('summary-agent-icon');
    if (!container) {
      return;
    }

    container.textContent = '';
    const icon = this.normalizeAgentIconPayload(agentsCommon.getAgentIconPayload(document));
    if (icon?.kind === 'image') {
      const image = document.createElement('img');
      image.src = icon.value;
      image.alt = '';
      container.appendChild(image);
      return;
    }

    const iconElement = document.createElement('i');
    iconElement.className = `bi ${icon?.kind === 'bootstrap' ? icon.value : 'bi-robot'}`;
    iconElement.setAttribute('aria-hidden', 'true');
    container.appendChild(iconElement);
  }

  async saveAgent() {
    try {
      // Get agent data from form
      const agentData = this.getAgentFormData();
      agentData.agent_type = (this.originalAgent?.agent_type) || agentData.agent_type || 'local';
      
      // Validate required fields
      if (!agentData.display_name || !agentData.name) {
        throw new Error('Display name and generated name are required');
      }
      
      // If editing, preserve the original ID
      if (this.isEditMode && this.originalAgent && this.originalAgent.id) {
        agentData.id = this.originalAgent.id;
      }
      else {
        // Generate ID if needed for new agents
        if (!agentData.id) {
          if (this.isAdmin) {
            try {
              const guidResp = await fetch('/api/agents/generate_id');
              if (guidResp.ok) {
                const guidData = await guidResp.json();
                agentData.id = guidData.id;
              } else {
                agentData.id = crypto.randomUUID();
              }
            } catch (guidErr) {
              agentData.id = crypto.randomUUID();
            }
          }
          else {
            agentData.id = `${current_user_id}_${agentData.name}`;
          }
        }
      }
      
      // Add selected actions (skip for Foundry)
      if (this.isAnyFoundryType(agentData.agent_type)) {
        agentData.actions_to_load = [];
      } else {
        agentData.actions_to_load = this.getSelectedActionIds();
      }
      agentData.is_global = this.isAdmin; // Set based on admin context
      
      // Ensure required schema fields are present
      if (!agentData.other_settings) {
        agentData.other_settings = {};
      }
      else {
        agentData.other_settings = JSON.parse(agentData.other_settings) || {};
      }
      agentData.other_settings[ASSIGNED_KNOWLEDGE_KEY] = this.getAssignedKnowledgeConfig();
      
      // Clean up empty reasoning_effort (inherit from model default)
      if (!agentData.reasoning_effort || agentData.reasoning_effort === '') {
        delete agentData.reasoning_effort;
      }
      
      // Clean up form-specific fields that shouldn't be sent to backend
      const formOnlyFields = ['custom_connection', 'model'];
      formOnlyFields.forEach(field => {
        if (agentData.hasOwnProperty(field)) {
          delete agentData[field];
        }
      });
      
      // Use appropriate endpoint and save method based on context
      let saveBtn = document.getElementById('agent-modal-save-btn');
      const originalText = saveBtn.innerHTML;
      saveBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Saving...`;
      saveBtn.disabled = true;
      try {
        if (this.isAdmin) {
          // Admin context - save to global agents
          await this.saveGlobalAgent(agentData);
        } else {
          // User context - save to personal agents
          await this.savePersonalAgent(agentData);
        }
      //No catch to allow outer catch to handle errors
      } finally {
        saveBtn.innerHTML = originalText;
        saveBtn.disabled = false;
      }
      
    } catch (error) {
      console.error('Error saving agent:', error);
      this.showError(error.message || 'Failed to save agent.');
      if (window.showToast) {
        window.showToast('Agent could not be saved. Review the error shown in the modal.', 'danger');
      }
    }
  }

  async draftInstructions() {
    if (this.isAnyFoundryType()) {
      return;
    }

    const draftButton = document.getElementById('agent-draft-instructions-btn');
    const draftStatus = document.getElementById('agent-draft-instructions-status');
    const briefInput = document.getElementById('agent-instruction-brief');
    const brief = briefInput?.value.trim() || '';
    const displayName = document.getElementById('agent-display-name')?.value.trim() || '';
    const description = document.getElementById('agent-description')?.value.trim() || '';
    const existingInstructions = this.getInstructionsValue().trim();

    if (!brief && !displayName && !description && !existingInstructions) {
      this.showError('Add a brief, display name, description, or existing instructions before drafting.');
      briefInput?.focus();
      return;
    }

    const originalButtonHtml = draftButton?.innerHTML || '';
    if (draftButton) {
      draftButton.disabled = true;
      draftButton.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Drafting';
    }
    if (draftStatus) {
      draftStatus.textContent = 'Drafting...';
    }

    try {
      const response = await fetch('/api/agents/draft-instructions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_scope: this.workspaceScope,
          display_name: displayName,
          description,
          brief,
          existing_instructions: existingInstructions
        })
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.success) {
        throw new Error(result.error || 'Failed to draft instructions.');
      }

      this.setInstructionsValue(result.instructions || '');
      this.refreshInstructionsEditor(true);
      this.hideError();
      if (draftStatus) {
        draftStatus.textContent = 'Draft inserted.';
      }
      if (window.showToast) {
        window.showToast('Draft instructions inserted.', 'success');
      }
    } catch (error) {
      console.error('Error drafting instructions:', error);
      this.showError(error.message || 'Failed to draft instructions.');
      if (draftStatus) {
        draftStatus.textContent = '';
      }
    } finally {
      if (draftButton) {
        draftButton.disabled = false;
        draftButton.innerHTML = originalButtonHtml;
      }
    }
  }

  getAgentFormData() {
    const agentTypeInput = document.querySelector('input[name="agent-type"]:checked');
    const selectedAgentType = agentTypeInput ? agentTypeInput.value : 'local';

    const modelSelect = document.getElementById('agent-global-model-select');
    const selectedModelOption = modelSelect ? modelSelect.options[modelSelect.selectedIndex] : null;
    const modelEndpointInput = document.getElementById('agent-model-endpoint-id');
    const modelIdInput = document.getElementById('agent-model-id');
    const modelProviderInput = document.getElementById('agent-model-provider');
    const modelEndpointId = modelEndpointInput?.value || selectedModelOption?.dataset?.endpointId || '';
    const modelId = modelIdInput?.value || selectedModelOption?.value || '';
    const modelProvider = modelProviderInput?.value || selectedModelOption?.dataset?.provider || '';
    const foundryAuthenticationType = 'delegated_user';

    const formData = {
      display_name: document.getElementById('agent-display-name')?.value || '',
      name: document.getElementById('agent-name')?.value || '',
      description: document.getElementById('agent-description')?.value || '',
      tags: (document.getElementById('agent-tags')?.value || '')
        .split(',')
        .map(tag => tag.trim())
        .filter(Boolean),
      icon: agentsCommon.getAgentIconPayload(document),
      instructions: this.getInstructionsValue() || '',
      model: modelSelect?.value || '',
      instructions: this.getInstructionsValue() || '',
      custom_connection: document.getElementById('agent-custom-connection')?.checked || false,
      other_settings: document.getElementById('agent-additional-settings')?.value || '{}',
      max_completion_tokens: parseInt(document.getElementById('agent-max-completion-tokens')?.value.trim()) || null,
      reasoning_effort: document.getElementById('agent-reasoning-effort')?.value || '',
      agent_type: selectedAgentType,
      model_endpoint_id: modelEndpointId,
      model_id: modelId,
      model_provider: modelProvider
    };

    if (selectedAgentType === 'aifoundry') {
      // Foundry required fields
      formData.azure_openai_gpt_endpoint = document.getElementById('agent-foundry-endpoint')?.value?.trim() || '';
      formData.azure_openai_gpt_deployment = document.getElementById('agent-foundry-deployment')?.value?.trim() || '';
      formData.azure_openai_gpt_api_version = document.getElementById('agent-foundry-api-version')?.value?.trim() || '';
      formData.instructions = this.getInstructionsValue().trim() || this.foundryPlaceholderInstructions;

      // other_settings for foundry
      let otherSettingsObj = {};
      try {
        otherSettingsObj = JSON.parse(formData.other_settings || '{}');
      } catch (e) {
        otherSettingsObj = {};
      }
      otherSettingsObj = otherSettingsObj || {};
      const notesVal = document.getElementById('agent-foundry-notes')?.value || '';
      otherSettingsObj.azure_ai_foundry = {
        ...(otherSettingsObj.azure_ai_foundry || {}),
        agent_id: document.getElementById('agent-foundry-agent-id')?.value?.trim() || '',
        endpoint_id: modelEndpointId || '',
        authentication_type: 'delegated_user',
        ...(notesVal ? { notes: notesVal } : {})
      };
      formData.other_settings = JSON.stringify(otherSettingsObj);

      // Foundry agents cannot have actions
      formData.actions_to_load = [];
      formData.enable_agent_gpt_apim = false;
      formData.model_endpoint_id = modelEndpointId;
      formData.model_id = '';
      formData.model_provider = 'aifoundry';
      return formData;
    }

    if (selectedAgentType === 'new_foundry') {
      formData.azure_openai_gpt_endpoint = document.getElementById('agent-foundry-endpoint')?.value?.trim() || '';
      formData.azure_openai_gpt_deployment = document.getElementById('agent-foundry-deployment')?.value?.trim() || '';
      formData.azure_openai_gpt_api_version = document.getElementById('agent-new-foundry-responses-api-version')?.value?.trim() || '';
      formData.instructions = this.getInstructionsValue().trim() || this.foundryPlaceholderInstructions;

      let otherSettingsObj = {};
      try {
        otherSettingsObj = JSON.parse(formData.other_settings || '{}');
      } catch (e) {
        otherSettingsObj = {};
      }
      otherSettingsObj = otherSettingsObj || {};

      const notesVal = document.getElementById('agent-foundry-notes')?.value || '';
      const applicationId = document.getElementById('agent-new-foundry-application-id')?.value?.trim() || '';
      const applicationName = document.getElementById('agent-new-foundry-application-name')?.value?.trim() || '';
      const applicationVersion = document.getElementById('agent-new-foundry-application-version')?.value?.trim() || '';
      const activityApiVersion = document.getElementById('agent-new-foundry-activity-api-version')?.value?.trim() || '';

      otherSettingsObj.new_foundry = {
        ...(otherSettingsObj.new_foundry || {}),
        application_id: applicationId,
        application_name: applicationName,
        application_version: applicationVersion,
        endpoint_id: modelEndpointId || '',
        authentication_type: foundryAuthenticationType,
        responses_api_version: formData.azure_openai_gpt_api_version,
        ...(activityApiVersion ? { activity_api_version: activityApiVersion } : {}),
        ...(notesVal ? { notes: notesVal } : {}),
      };
      formData.other_settings = JSON.stringify(otherSettingsObj);

      formData.actions_to_load = [];
      formData.enable_agent_gpt_apim = false;
      formData.model_endpoint_id = modelEndpointId;
      formData.model_id = '';
      formData.model_provider = 'new_foundry';
      return formData;
    }

    if (selectedAgentType === 'foundry_workflow') {
      formData.azure_openai_gpt_endpoint = document.getElementById('agent-foundry-endpoint')?.value?.trim() || '';
      formData.azure_openai_gpt_deployment = document.getElementById('agent-foundry-deployment')?.value?.trim() || '';
      formData.azure_openai_gpt_api_version = document.getElementById('agent-foundry-workflow-responses-api-version')?.value?.trim() || '';
      formData.instructions = this.getInstructionsValue().trim() || this.foundryPlaceholderInstructions;

      let otherSettingsObj = {};
      try {
        otherSettingsObj = JSON.parse(formData.other_settings || '{}');
      } catch (e) {
        otherSettingsObj = {};
      }
      otherSettingsObj = otherSettingsObj || {};

      const notesVal = document.getElementById('agent-foundry-notes')?.value || '';
      const workflowName = document.getElementById('agent-foundry-workflow-name')?.value?.trim() || '';
      const includeDocumentContext = document.getElementById('agent-foundry-workflow-include-document-context')?.checked !== false;
      const maxContextChars = document.getElementById('agent-foundry-workflow-max-context-chars')?.value?.trim() || '';
      const selectedWorkflowAgent = this.selectedFoundryWorkflowAgent || {};
      const workflowAgentReference = selectedWorkflowAgent.agent_reference || selectedWorkflowAgent;
      const workflowAgentId = selectedWorkflowAgent.workflow_agent_id || workflowAgentReference.id || selectedWorkflowAgent.id || '';
      const workflowApplicationId = selectedWorkflowAgent.application_id || workflowAgentReference.application_id || '';
      const workflowApplicationVersion = selectedWorkflowAgent.application_version || workflowAgentReference.application_version || '';
      const normalizedAgentReference = {
        ...workflowAgentReference,
        type: workflowAgentReference.type || 'agent_reference',
        name: workflowName || workflowAgentReference.name || selectedWorkflowAgent.workflow_name || selectedWorkflowAgent.name || ''
      };
      if (workflowAgentId) {
        normalizedAgentReference.id = workflowAgentId;
      }
      if (workflowApplicationId) {
        normalizedAgentReference.application_id = workflowApplicationId;
      }
      if (workflowApplicationVersion) {
        normalizedAgentReference.application_version = workflowApplicationVersion;
      }

      otherSettingsObj.foundry_workflow = {
        ...(otherSettingsObj.foundry_workflow || {}),
        workflow_name: workflowName,
        ...(workflowAgentId ? { workflow_agent_id: workflowAgentId } : {}),
        ...(workflowApplicationId ? { application_id: workflowApplicationId } : {}),
        ...(workflowApplicationVersion ? { application_version: workflowApplicationVersion } : {}),
        ...(normalizedAgentReference.name ? { agent_reference: normalizedAgentReference } : {}),
        endpoint_id: modelEndpointId || '',
        authentication_type: foundryAuthenticationType,
        responses_api_version: formData.azure_openai_gpt_api_version,
        include_document_context: includeDocumentContext,
        ...(maxContextChars ? { max_context_chars: Number.parseInt(maxContextChars, 10) } : {}),
        ...(notesVal ? { notes: notesVal } : {}),
      };
      formData.other_settings = JSON.stringify(otherSettingsObj);

      formData.actions_to_load = [];
      formData.enable_agent_gpt_apim = false;
      formData.model_endpoint_id = modelEndpointId;
      formData.model_id = '';
      formData.model_provider = 'foundry_workflow';
      return formData;
    }
    
    // Handle model and deployment configuration
    if (formData.custom_connection) {
      // Custom connection - get values from custom fields
      const enableApim = document.getElementById('agent-enable-apim')?.checked || false;
      
      if (enableApim) {
        // APIM deployment fields - only include if they have values
        const apimEndpoint = document.getElementById('agent-apim-endpoint')?.value || '';
        const apimKey = document.getElementById('agent-apim-subscription-key')?.value || '';
        const apimDeployment = document.getElementById('agent-apim-deployment')?.value || '';
        const apimApiVersion = document.getElementById('agent-apim-api-version')?.value || '';
        
        if (apimEndpoint) formData.azure_agent_apim_gpt_endpoint = apimEndpoint;
        if (apimKey) formData.azure_agent_apim_gpt_subscription_key = apimKey;
        if (apimDeployment) formData.azure_agent_apim_gpt_deployment = apimDeployment;
        if (apimApiVersion) formData.azure_agent_apim_gpt_api_version = apimApiVersion;
        formData.enable_agent_gpt_apim = true;
      } else {
        // Non-APIM deployment fields - only include if they have values
        const gptEndpoint = document.getElementById('agent-gpt-endpoint')?.value || '';
        const gptKey = document.getElementById('agent-gpt-key')?.value || '';
        const gptDeployment = document.getElementById('agent-gpt-deployment')?.value || '';
        const gptApiVersion = document.getElementById('agent-gpt-api-version')?.value || '';
        
        if (gptEndpoint) formData.azure_openai_gpt_endpoint = gptEndpoint;
        if (gptKey) formData.azure_openai_gpt_key = gptKey;
        if (gptDeployment) formData.azure_openai_gpt_deployment = gptDeployment;
        if (gptApiVersion) formData.azure_openai_gpt_api_version = gptApiVersion;
        formData.enable_agent_gpt_apim = false;
      }
      formData.model_endpoint_id = '';
      formData.model_id = '';
      formData.model_provider = '';
    } else {
      // Using global model - need to set at least one deployment field
      // We'll use the selected model as the deployment name for now
      if (formData.model) {
        const deploymentName = selectedModelOption?.dataset?.deploymentName || formData.model;
        formData.azure_openai_gpt_deployment = deploymentName;
      }
    }
    
    return formData;
  }

  async saveGlobalAgent(agentData) {
    // For global agents, use the admin API endpoints
    if (this.isEditMode && this.originalAgent?.name) {
      // Update existing global agent
      const saveRes = await fetch(`/api/admin/agents/${encodeURIComponent(this.originalAgent.name)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agentData)
      });
      
      if (!saveRes.ok) {
        let errorMessage = 'Failed to save agent';
        try {
          const errorData = await saveRes.json();
          if (errorData.error) {
            errorMessage = errorData.error;
          }
        } catch (e) {
          // Fall back to status text if JSON parsing fails
          errorMessage = `Failed to save agent: ${saveRes.status} ${saveRes.statusText}`;
        }
        throw new Error(errorMessage);
      }
    } else {
      // Create new global agent
      const saveRes = await fetch('/api/admin/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agentData)
      });
      
      if (!saveRes.ok) {
        let errorMessage = 'Failed to save agent';
        try {
          const errorData = await saveRes.json();
          if (errorData.error) {
            errorMessage = errorData.error;
          }
        } catch (e) {
          // Fall back to status text if JSON parsing fails
          errorMessage = `Failed to save agent: ${saveRes.status} ${saveRes.statusText}`;
        }
        throw new Error(errorMessage);
      }
    }

    // Show success message and refresh
    this.handleSaveSuccess();
    
    // Refresh admin agents list if available
    if (window.loadAllAdminAgentData) {
      await window.loadAllAdminAgentData();
    }
  }

  async savePersonalAgent(agentData) {
    // For personal agents, use the user API endpoints
    const res = await fetch('/api/user/agents');
    let agents = [];
    if (res.ok) {
      agents = await res.json();
    }
    
    // If editing, replace; else, add
    const idx = this.isEditMode && this.originalAgent ? 
      agents.findIndex(a => a.id === this.originalAgent.id) : -1;
    
    if (idx >= 0) {
      agents[idx] = agentData;
    } else {
      agents.push(agentData);
    }
    
    const saveRes = await fetch('/api/user/agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(agents)
    });
    
    if (!saveRes.ok) {
      let errorMessage = 'Failed to save agent';
      try {
        const errorData = await saveRes.json();
        if (errorData.error) {
          errorMessage = errorData.error;
        }
      } catch (e) {
        // Fall back to status text if JSON parsing fails
        errorMessage = `Failed to save agent: ${saveRes.status} ${saveRes.statusText}`;
      }
      throw new Error(errorMessage);
    }

    // Show success message and refresh
    this.handleSaveSuccess();
    
    // Refresh workspace agents list if available
    if (window.fetchAgents) {
      await window.fetchAgents();
    }
  }

  handleSaveSuccess() {
    // Hide modal
    const modal = bootstrap.Modal.getInstance(document.getElementById('agentModal'));
    if (modal) {
      modal.hide();
    }
    
    // Show success message
    if (window.showToast) {
      window.showToast(`Agent ${this.isEditMode ? 'updated' : 'created'} successfully!`, 'success');
    }
  }

  validateTemplateRequirements() {
    const displayName = document.getElementById('agent-display-name');
    const description = document.getElementById('agent-description');
    const instructions = this.getInstructionsValue();

    if (!displayName || !displayName.value.trim()) {
      this.showError('Please add a display name before submitting a template.');
      displayName?.focus();
      return false;
    }

    if (!description || !description.value.trim()) {
      this.showError('Please add a description before submitting a template.');
      description?.focus();
      return false;
    }

    if (!instructions.trim()) {
      this.showError('Instructions are required before submitting a template.');
      this.refreshInstructionsEditor(true);
      return false;
    }

    this.hideError();
    return true;
  }

  buildTemplatePayload() {
    const displayName = document.getElementById('agent-display-name')?.value?.trim() || '';
    const description = document.getElementById('agent-description')?.value?.trim() || '';
    const instructions = this.getInstructionsValue() || '';
    const additionalSettings = document.getElementById('agent-additional-settings')?.value || '';

    return {
      title: displayName || 'Agent Template',
      display_name: displayName || 'Agent Template',
      description,
      helper_text: description,
      instructions,
      additional_settings: additionalSettings,
      actions_to_load: this.getSelectedActionIds(),
      source_agent_id: this.originalAgent?.id,
      source_scope: this.isAdmin ? 'global' : 'personal'
    };
  }

  async submitTemplate() {
    if (!this.canSubmitTemplate()) {
      showToast('Template submissions are disabled right now.', 'warning');
      return;
    }

    if (!this.validateTemplateRequirements()) {
      return;
    }

    const button = this.templateSubmitButton;
    if (!button) {
      return;
    }

    const originalHtml = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Submitting...';

    try {
      const payload = { template: this.buildTemplatePayload() };
      const response = await fetch('/api/agent-templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || 'Failed to submit agent template.');
      }

      const status = data.template?.status;
      const successMessage = (this.isAdmin && status === 'approved')
        ? 'Template published to the gallery!'
        : 'Template submitted for review.';
      showToast(successMessage, 'success');
      this.hideError();
    } catch (error) {
      console.error('Template submission failed:', error);
      this.showError(error.message || 'Failed to submit template.');
      showToast(error.message || 'Failed to submit template.', 'error');
    } finally {
      button.disabled = false;
      button.innerHTML = originalHtml;
    }
  }
}

// Global instance will be created contextually by the calling code
// Do not create a default instance here to avoid conflicts between admin and user contexts
