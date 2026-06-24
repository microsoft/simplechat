// plugin_modal_stepper.js
// Multi-step modal functionality for action/plugin creation
import { showToast } from "./chat/chat-toast.js";
import { getTypeIcon } from "./workspace/view-utils.js";

// Action types hidden from the creation UI (backend plugins remain intact)
const HIDDEN_ACTION_TYPES = ['sql_schema', 'ui_test', 'queue_storage', 'embedding_model', 'databricks_table'];
const ACTION_IDENTITY_AUTH_TYPES = ['api_key', 'bearer_token', 'client_secret', 'connection_string', 'managed_identity', 'username_password'];
const SQL_ACTION_IDENTITY_AUTH_TYPES = ['connection_string', 'managed_identity', 'username_password'];
const OPENAPI_ACTION_IDENTITY_AUTH_TYPES = ['api_key', 'bearer_token', 'username_password'];
const MCP_ACTION_IDENTITY_AUTH_TYPES = ['api_key', 'bearer_token', 'managed_identity', 'username_password'];
const DATABRICKS_ACTION_IDENTITY_AUTH_TYPES = ['api_key', 'bearer_token', 'managed_identity'];
const SNOWFLAKE_ACTION_IDENTITY_AUTH_TYPES = ['api_key', 'bearer_token', 'username_password'];
const TABLEAU_ACTION_IDENTITY_AUTH_TYPES = ['api_key', 'username_password'];
const BLOB_STORAGE_PLUGIN_TYPE = 'blob_storage';
const DATABRICKS_PLUGIN_TYPE = 'databricks';
const DATABRICKS_DEFAULT_CLOUD = 'azure_commercial';
const SNOWFLAKE_PLUGIN_TYPE = 'snowflake';
const SNOWFLAKE_DEFAULT_ENDPOINT = 'snowflake://query';
const SNOWFLAKE_AUTH_METHOD_PASSWORD = 'password';
const SNOWFLAKE_AUTH_METHOD_KEY_PAIR = 'key_pair';
const SNOWFLAKE_AUTH_METHOD_OAUTH = 'oauth';
const TABLEAU_PLUGIN_TYPE = 'tableau';
const TABLEAU_AUTH_METHOD_PAT = 'personal_access_token';
const TABLEAU_AUTH_METHOD_USERNAME_PASSWORD = 'username_password';
const MCP_PLUGIN_TYPE = 'mcp';
const AZURE_MAPS_PLUGIN_TYPE = 'azure_maps_openlayers';
const AZURE_MAPS_DEFAULT_ENDPOINT = 'https://atlas.microsoft.com';
const CHART_DEFAULT_ENDPOINT = 'chart://internal';
const INTERNAL_DOCUMENT_SEARCH_ENDPOINT = 'internal://document-search';
const MSGRAPH_DEFAULT_ENDPOINT = 'https://graph.microsoft.com';
const MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL = 'draft_manual';
const MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED = 'draft_delayed';
const MSGRAPH_MAIL_SEND_MODE_AUTO_SEND = 'auto_send';
const MSGRAPH_DEFAULT_MAIL_SEND_MODE = MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL;
const MSGRAPH_DEFAULT_CALENDAR_SEND_MODE = MSGRAPH_MAIL_SEND_MODE_AUTO_SEND;
const MSGRAPH_DEFAULT_MAIL_DELAY_SECONDS = 60;
const MSGRAPH_MIN_MAIL_DELAY_SECONDS = 5;
const MSGRAPH_MAX_MAIL_DELAY_SECONDS = 600;
const MSGRAPH_DEFAULT_CALENDAR_DELAY_SECONDS = 60;
const MSGRAPH_MIN_CALENDAR_DELAY_SECONDS = 5;
const MSGRAPH_MAX_CALENDAR_DELAY_SECONDS = 600;
const MCP_STDIO_ENDPOINT = 'stdio://local';
const BLOB_STORAGE_CAPABILITY_DEFINITIONS = [
  {
    key: 'list_container_contents',
    label: 'List container contents',
    description: 'List blobs in the configured container and optional prefix.'
  },
  {
    key: 'read_file_content',
    label: 'Read file content',
    description: 'Read supported files from the configured container.'
  },
  {
    key: 'upload_file_to_container',
    label: 'Upload file to container',
    description: 'Upload supported files into the configured container.'
  }
];
const BLOB_STORAGE_FILE_TYPE_DEFINITIONS = [
  {
    key: 'markdown',
    label: 'Markdown',
    description: 'Supports .md and .markdown files stored as UTF-8 text.'
  }
];
const SIMPLECHAT_CAPABILITY_DEFINITIONS = [
  {
    key: 'create_group',
    label: 'Create groups',
    description: 'Allow this action to create new group workspaces as the current user.'
  },
  {
    key: 'add_group_member',
    label: 'Add users to groups',
    description: 'Allow this action to add members directly to groups using the current user\'s permissions.'
  },
  {
    key: 'make_group_inactive',
    label: 'Make groups inactive',
    description: 'Allow this action to mark a group inactive when the current user has Control Center admin access.'
  },
  {
    key: 'create_group_conversation',
    label: 'Create group multi-user conversations',
    description: 'Allow this action to create invite-managed group multi-user conversations and then add current group members as participants.'
  },
  {
    key: 'invite_group_conversation_members',
    label: 'Invite group conversation members',
    description: 'Allow this action to invite current group members into an existing invite-managed group multi-user conversation.'
  },
  {
    key: 'create_personal_conversation',
    label: 'Create personal conversations',
    description: 'Allow this action to create standard one-user personal conversations.'
  },
  {
    key: 'create_personal_workflow',
    label: 'Create personal workflows',
    description: 'Allow this action to create personal workflows using the current user\'s own workflow permissions.'
  },
  {
    key: 'add_conversation_message',
    label: 'Add conversation messages',
    description: 'Allow this action to add a user-authored message to an existing personal or collaborative conversation.'
  },
  {
    key: 'upload_markdown_document',
    label: 'Upload markdown documents',
    description: 'Allow this action to create and upload Markdown documents into the current user\'s personal or allowed group workspaces.'
  },
  {
    key: 'upload_word_document',
    label: 'Upload Word documents',
    description: 'Allow this action to create and upload Word documents into the current user\'s personal or allowed group workspaces.'
  },
  {
    key: 'upload_powerpoint_document',
    label: 'Upload PowerPoint documents',
    description: 'Allow this action to create and upload PowerPoint presentations into the current user\'s personal or allowed group workspaces.'
  },
  {
    key: 'create_personal_collaboration_conversation',
    label: 'Create personal collaborative conversations',
    description: 'Allow this action to create personal collaborative conversations and invite participants.'
  }
];
const MSGRAPH_CAPABILITY_DEFINITIONS = [
  {
    key: 'get_my_profile',
    label: 'Read my profile',
    description: 'Allow this action to read the signed-in user\'s Microsoft 365 profile details.'
  },
  {
    key: 'get_my_timezone',
    label: 'Read my mailbox timezone',
    description: 'Allow this action to read mailbox time zone and time formatting settings.'
  },
  {
    key: 'get_my_events',
    label: 'Read my calendar events',
    description: 'Allow this action to read upcoming calendar events for the signed-in user.'
  },
  {
    key: 'create_calendar_invite',
    label: 'Create calendar invites',
    description: 'Allow this action to create calendar invites, add current group members as attendees, and create Microsoft Teams meetings.'
  },
  {
    key: 'get_my_messages',
    label: 'Read my mail',
    description: 'Allow this action to read recent mail messages for the signed-in user.'
  },
  {
    key: 'mark_message_as_read',
    label: 'Update message read state',
    description: 'Allow this action to mark mail messages as read or unread.'
  },
  {
    key: 'send_mail',
    label: 'Send mail',
    description: 'Allow this action to create manual drafts, delayed-delivery drafts, or send mail.'
  },
  {
    key: 'search_users',
    label: 'Search directory users',
    description: 'Allow this action to search Microsoft 365 directory users by name or email prefix.'
  },
  {
    key: 'get_user_by_email',
    label: 'Lookup user by email',
    description: 'Allow this action to look up a directory user by exact email address or UPN.'
  },
  {
    key: 'list_drive_items',
    label: 'List OneDrive items',
    description: 'Allow this action to list items from the signed-in user\'s OneDrive.'
  },
  {
    key: 'get_my_security_alerts',
    label: 'Read my security alerts',
    description: 'Allow this action to read recent security alerts available to the signed-in user.'
  }
];
const CHART_CAPABILITY_DEFINITIONS = [
  {
    key: 'line',
    label: 'Line charts',
    description: 'Render single-series and multi-series line charts.'
  },
  {
    key: 'bar',
    label: 'Bar charts',
    description: 'Render categorical bar charts, including grouped multi-series bars.'
  },
  {
    key: 'pie',
    label: 'Pie charts',
    description: 'Render proportional pie charts for part-to-whole comparisons.'
  },
  {
    key: 'doughnut',
    label: 'Doughnut charts',
    description: 'Render doughnut charts for part-to-whole comparisons with a center cutout.'
  },
  {
    key: 'scatter',
    label: 'Scatter plots',
    description: 'Render XY scatter plots with optional grouped series.'
  },
  {
    key: 'area',
    label: 'Area charts',
    description: 'Render filled line charts for trend visualization.'
  },
  {
    key: 'bubble',
    label: 'Bubble charts',
    description: 'Render bubble charts with x, y, and size dimensions.'
  },
  {
    key: 'radar',
    label: 'Radar charts',
    description: 'Render radar charts for multi-axis comparisons.'
  },
  {
    key: 'stacked_bar',
    label: 'Stacked bar charts',
    description: 'Render stacked bar charts for cumulative category comparisons.'
  },
  {
    key: 'stacked_line',
    label: 'Stacked line charts',
    description: 'Render stacked line charts for cumulative multi-series trends.'
  }
];

export class PluginModalStepper {


  constructor() {
    this.currentStep = 1;
    this.maxSteps = 5;
    this.selectedType = null;
    this.availableTypes = [];
    this.isEditMode = false;
    this.currentPage = 1;
    this.itemsPerPage = 12;
    this.filteredTypes = [];
    this.originalPlugin = null; // Store original state for change tracking
    this.pluginSchemaCache = null; // Will hold plugin.schema.json
    this.pluginDefinitionCache = {}; // Cache for per-type definition schemas
    this.additionalSettingsSchemaCache = {}; // Cache for additional settings schemas
    this.lastAdditionalFieldsType = null; // Track last type to avoid unnecessary redraws
    this.defaultAuthTypes = ["NoAuth", "key", "identity", "user", "servicePrincipal", "connection_string", "basic", "username_password"];
    this.currentAllowedAuthTypes = null; // Active allowed auth types derived from definition
    this.actionIdentityScope = {
      scope: 'personal',
      apiBase: '/api/workspace-identities/personal'
    };
    this.actionIdentities = [];
    this.actionIdentitiesLoaded = false;
    this.simpleChatCapabilityState = this.getDefaultSimpleChatCapabilities();
    this.msGraphCapabilityState = this.getDefaultMsGraphCapabilities();
    this.chartCapabilityState = this.getDefaultChartCapabilities();
    this.blobStorageCapabilityState = this.getDefaultBlobStorageCapabilities();
    this.blobStorageReadFileTypeState = this.getDefaultBlobStorageReadFileTypes();
    this.blobStorageUploadFileTypeState = this.getDefaultBlobStorageUploadFileTypes();

    this._loadPluginSchema().then(() => { // Load schema on initialization
      this._populateGenericAuthTypeDropdown(); // Dynamically populate generic auth type dropdown after schema loads (will be called again after schema loads)
    });
    this.bindEvents();
  }

  async _loadPluginSchema() {
    try {
      const res = await fetch('/static/json/schemas/plugin.schema.json');
      if (!res.ok) throw new Error('Failed to load plugin.schema.json');
      this.pluginSchemaCache = await res.json();
    } catch (err) {
      console.error('Error loading plugin.schema.json:', err);
      this.pluginSchemaCache = null;
    }
  }

  getAuthTypeEnumFromSchema() {
    const authEnum = this.pluginSchemaCache?.definitions?.AuthType?.enum;
    return Array.isArray(authEnum) && authEnum.length ? authEnum : null;
  }

  async loadPluginDefinition(type) {
    const safeType = this.getSafeType(type);
    if (!safeType) return null;

    if (Object.prototype.hasOwnProperty.call(this.pluginDefinitionCache, safeType)) {
      return this.pluginDefinitionCache[safeType];
    }

    try {
      const res = await fetch(`/api/plugins/${encodeURIComponent(type)}/auth-types`);
      if (!res.ok) throw new Error(`Auth types fetch failed with status ${res.status}`);
      const json = await res.json();
      this.pluginDefinitionCache[safeType] = json;
      return json;
    } catch (err) {
      console.warn(`Failed to load auth types for type '${safeType}':`, err.message || err);
      this.pluginDefinitionCache[safeType] = null;
      return null;
    }
  }

  async applyDefinitionForSelectedType(type = this.selectedType) {
    this.currentAllowedAuthTypes = null;

    if (type) {
      const definition = await this.loadPluginDefinition(type);
      const allowed = definition?.allowedAuthTypes;
      if (Array.isArray(allowed) && allowed.length) {
        this.currentAllowedAuthTypes = allowed;
      }
    }

    this._populateGenericAuthTypeDropdown();
  }

  _populateGenericAuthTypeDropdown() {
    // Only run if dropdown exists
    const dropdown = document.getElementById('plugin-auth-type-generic');
    if (!dropdown) return;
    const fullAuthEnum = this.getAuthTypeEnumFromSchema() || this.defaultAuthTypes;
    const allowedList = this.currentAllowedAuthTypes && this.currentAllowedAuthTypes.length
      ? this.currentAllowedAuthTypes
      : fullAuthEnum;

    // Clear existing options
    dropdown.innerHTML = '';
    allowedList.forEach(type => {
      const option = document.createElement('option');
      option.value = type;
      option.textContent = this.formatAuthType(type);
      dropdown.appendChild(option);
    });
  }

  setActionScope(scopeConfig = {}) {
    const scope = scopeConfig.scope || 'personal';
    const apiBase = scopeConfig.apiBase || '/api/workspace-identities/personal';
    if (this.actionIdentityScope.scope === scope && this.actionIdentityScope.apiBase === apiBase) {
      return;
    }

    this.actionIdentityScope = { scope, apiBase };
    this.actionIdentities = [];
    this.actionIdentitiesLoaded = false;
  }

  async loadActionIdentities() {
    if (this.actionIdentitiesLoaded) {
      this.updateActionIdentitySelectors();
      return this.actionIdentities;
    }

    const apiBase = this.actionIdentityScope?.apiBase;
    if (!apiBase) {
      this.actionIdentities = [];
      this.actionIdentitiesLoaded = true;
      this.updateActionIdentitySelectors();
      return this.actionIdentities;
    }

    try {
      const response = await fetch(`${apiBase}/identities`);
      if (!response.ok) {
        throw new Error('Failed to load reusable identities');
      }
      const payload = await response.json();
      const identities = Array.isArray(payload?.identities) ? payload.identities : [];
      this.actionIdentities = identities.filter(identity => this.isActionIdentityCapable(identity));
    } catch (error) {
      console.warn('Unable to load action identities:', error);
      this.actionIdentities = [];
    }

    this.actionIdentitiesLoaded = true;
    this.updateActionIdentitySelectors();
    return this.actionIdentities;
  }

  isActionIdentityCapable(identity) {
    const authType = this.getIdentityAuthType(identity);
    if (!ACTION_IDENTITY_AUTH_TYPES.includes(authType)) {
      return false;
    }

    const contexts = Array.isArray(identity?.usage_contexts) ? identity.usage_contexts : [];
    const normalizedContexts = contexts.map(context => String(context || '').toLowerCase());
    const supportsActionContext = normalizedContexts.some(context => ['action', 'agent', 'plugin', 'general'].includes(context));
    if (!supportsActionContext) {
      return false;
    }

    const sourceTypes = Array.isArray(identity?.supported_source_types) ? identity.supported_source_types : [];
    if (!sourceTypes.length) {
      return true;
    }
    const normalizedSourceTypes = sourceTypes.map(sourceType => String(sourceType || '').toLowerCase());
    return normalizedSourceTypes.includes('action') || normalizedSourceTypes.includes('generic');
  }

  getIdentityAuthType(identity) {
    return String(identity?.credentials?.auth_type || identity?.auth_type || '').toLowerCase();
  }

  getActionIdentitiesForKind(kind) {
    if (kind === 'sql') {
      return this.actionIdentities.filter(identity => SQL_ACTION_IDENTITY_AUTH_TYPES.includes(this.getIdentityAuthType(identity)));
    }
    if (kind === 'openapi') {
      return this.actionIdentities.filter(identity => OPENAPI_ACTION_IDENTITY_AUTH_TYPES.includes(this.getIdentityAuthType(identity)));
    }
    if (kind === 'mcp') {
      return this.actionIdentities.filter(identity => MCP_ACTION_IDENTITY_AUTH_TYPES.includes(this.getIdentityAuthType(identity)));
    }
    if (kind === 'databricks') {
      return this.actionIdentities.filter(identity => DATABRICKS_ACTION_IDENTITY_AUTH_TYPES.includes(this.getIdentityAuthType(identity)));
    }
    if (kind === 'snowflake') {
      return this.actionIdentities.filter(identity => SNOWFLAKE_ACTION_IDENTITY_AUTH_TYPES.includes(this.getIdentityAuthType(identity)));
    }
    if (kind === 'tableau') {
      return this.actionIdentities.filter(identity => TABLEAU_ACTION_IDENTITY_AUTH_TYPES.includes(this.getIdentityAuthType(identity)));
    }
    return this.actionIdentities;
  }

  updateActionIdentitySelectors() {
    this.populateActionIdentitySelector('openapi', 'plugin-auth-identity-select', 'openapi-action-identity-group', 'plugin-auth-identity-status');
    this.populateActionIdentitySelector('mcp', 'mcp-identity-select', 'mcp-action-identity-group', 'mcp-identity-status');
    this.populateActionIdentitySelector('databricks', 'databricks-identity-select', 'databricks-action-identity-group', 'databricks-identity-status');
    this.populateActionIdentitySelector('snowflake', 'snowflake-identity-select', 'snowflake-action-identity-group', 'snowflake-identity-status');
    this.populateActionIdentitySelector('tableau', 'tableau-identity-select', 'tableau-action-identity-group', 'tableau-identity-status');
    this.populateActionIdentitySelector('generic', 'plugin-auth-identity-select-generic', 'generic-action-identity-group', 'plugin-auth-identity-status-generic');
    this.populateActionIdentitySelector('sql', 'sql-identity-select', 'sql-action-identity-group', 'sql-identity-status');
  }

  populateActionIdentitySelector(kind, selectId, groupId, statusId) {
    const select = document.getElementById(selectId);
    const group = document.getElementById(groupId);
    const status = document.getElementById(statusId);
    if (!select || !group) return;

    const previousValue = select.value || this.originalPlugin?.identity_id || '';
    const identities = this.getActionIdentitiesForKind(kind);
    select.replaceChildren();

    const emptyOption = document.createElement('option');
    emptyOption.value = '';
    emptyOption.textContent = 'Use action-specific credentials';
    select.appendChild(emptyOption);

    identities.forEach(identity => {
      const option = document.createElement('option');
      option.value = identity.id || identity.identity_id || '';
      option.textContent = `${identity.name || 'Workspace identity'} (${this.formatIdentityAuthType(this.getIdentityAuthType(identity))})`;
      select.appendChild(option);
    });

    if (previousValue && identities.some(identity => (identity.id || identity.identity_id) === previousValue)) {
      select.value = previousValue;
    }

    if (identities.length) {
      group.classList.remove('d-none');
      if (status) {
        status.textContent = '';
      }
    } else {
      group.classList.add('d-none');
      if (status) {
        status.textContent = 'No action-capable reusable identities are available for this scope.';
      }
    }
  }

  formatIdentityAuthType(authType) {
    const labels = {
      api_key: 'API key',
      bearer_token: 'Bearer token',
      client_secret: 'Client secret',
      connection_string: 'Connection string',
      managed_identity: 'Managed identity',
      username_password: 'Username and password'
    };
    return labels[authType] || this.formatLabel(authType || 'identity');
  }

  getSelectedActionIdentity(kind) {
    const selectIds = {
      openapi: 'plugin-auth-identity-select',
      mcp: 'mcp-identity-select',
      databricks: 'databricks-identity-select',
      snowflake: 'snowflake-identity-select',
      tableau: 'tableau-identity-select',
      generic: 'plugin-auth-identity-select-generic',
      sql: 'sql-identity-select'
    };
    const selectedId = document.getElementById(selectIds[kind])?.value || '';
    if (!selectedId) {
      return null;
    }
    return this.actionIdentities.find(identity => (identity.id || identity.identity_id) === selectedId) || null;
  }

  setSelectedActionIdentity(kind, identityId) {
    const selectIds = {
      openapi: 'plugin-auth-identity-select',
      mcp: 'mcp-identity-select',
      databricks: 'databricks-identity-select',
      snowflake: 'snowflake-identity-select',
      tableau: 'tableau-identity-select',
      generic: 'plugin-auth-identity-select-generic',
      sql: 'sql-identity-select'
    };
    const select = document.getElementById(selectIds[kind]);
    if (!select) return;
    select.value = identityId || '';
  }

  getSqlAuthTypeForIdentity(identity) {
    const authType = this.getIdentityAuthType(identity);
    if (authType === 'managed_identity') return 'managed_identity';
    if (authType === 'client_secret') return 'service_principal';
    if (authType === 'connection_string') return 'connection_string_only';
    return 'username_password';
  }

  handleActionIdentityChange(kind) {
    const selectedIdentity = this.getSelectedActionIdentity(kind);
    if (kind === 'sql') {
      const authSelect = document.getElementById('sql-auth-type');
      if (authSelect) {
        authSelect.disabled = !!selectedIdentity;
        if (selectedIdentity) {
          const sqlAuthType = this.getSqlAuthTypeForIdentity(selectedIdentity);
          if ([...authSelect.options].some(option => option.value === sqlAuthType)) {
            authSelect.value = sqlAuthType;
          }
        }
      }
      this.handleSqlConnectionMethodChange();
      this.handleSqlAuthTypeChange();
      return;
    }

    const authSelect = document.getElementById(kind === 'openapi'
      ? 'plugin-auth-type'
      : (kind === 'mcp' ? 'mcp-auth-method' : (kind === 'databricks' ? 'databricks-auth-method' : (kind === 'snowflake' ? 'snowflake-auth-method' : (kind === 'tableau' ? 'tableau-auth-method' : 'plugin-auth-type-generic')))));
    if (authSelect) {
      authSelect.disabled = !!selectedIdentity;
    }
    if (kind === 'openapi') {
      this.toggleOpenApiAuthFields();
    } else if (kind === 'mcp') {
      this.toggleMcpAuthFields();
    } else if (kind === 'databricks') {
      this.toggleDatabricksAuthFields();
    } else if (kind === 'snowflake') {
      this.toggleSnowflakeAuthFields();
    } else if (kind === 'tableau') {
      this.toggleTableauAuthFields();
    } else {
      this.toggleGenericAuthFields();
    }
  }

  bindEvents() {
    // Step navigation buttons
    document.getElementById('plugin-modal-next').addEventListener('click', () => this.nextStep());
    document.getElementById('plugin-modal-prev').addEventListener('click', () => this.prevStep());
    document.getElementById('plugin-modal-skip').addEventListener('click', () => this.skipToEnd());

    // Search functionality
    document.getElementById('action-type-search').addEventListener('input', (e) => this.filterActionTypes(e.target.value));

    // Auth type change handlers for both sections
    document.getElementById('plugin-auth-type').addEventListener('change', () => this.toggleOpenApiAuthFields());
    document.getElementById('plugin-auth-type-generic').addEventListener('change', () => this.toggleGenericAuthFields());
    document.getElementById('plugin-auth-identity-select').addEventListener('change', () => this.handleActionIdentityChange('openapi'));
    document.getElementById('mcp-transport').addEventListener('change', () => this.toggleMcpTransportFields());
    document.getElementById('mcp-auth-method').addEventListener('change', () => this.toggleMcpAuthFields());
    document.getElementById('mcp-identity-select').addEventListener('change', () => this.handleActionIdentityChange('mcp'));
    document.getElementById('mcp-discover-tools-btn').addEventListener('click', () => this.discoverMcpTools());
    document.getElementById('databricks-auth-method').addEventListener('change', () => this.toggleDatabricksAuthFields());
    document.getElementById('databricks-identity-select').addEventListener('change', () => this.handleActionIdentityChange('databricks'));
    document.getElementById('snowflake-auth-method').addEventListener('change', () => this.toggleSnowflakeAuthFields());
    document.getElementById('snowflake-identity-select').addEventListener('change', () => this.handleActionIdentityChange('snowflake'));
    document.getElementById('tableau-auth-method').addEventListener('change', () => this.toggleTableauAuthFields());
    document.getElementById('tableau-identity-select').addEventListener('change', () => this.handleActionIdentityChange('tableau'));
    document.getElementById('plugin-auth-identity-select-generic').addEventListener('change', () => this.handleActionIdentityChange('generic'));
    const msGraphMailSendMode = document.getElementById('msgraph-mail-send-mode');
    if (msGraphMailSendMode) {
      msGraphMailSendMode.addEventListener('change', () => this.updateMsGraphMailDelayVisibility());
    }
    const msGraphCalendarSendMode = document.getElementById('msgraph-calendar-send-mode');
    if (msGraphCalendarSendMode) {
      msGraphCalendarSendMode.addEventListener('change', () => this.updateMsGraphCalendarDelayVisibility());
    }

    // File upload handler
    document.getElementById('plugin-openapi-file').addEventListener('change', (e) => this.handleFileUpload(e));

    // SQL Plugin event handlers
    document.querySelectorAll('input[name="sql-database-type"]').forEach(radio => {
      radio.addEventListener('change', () => this.handleSqlDatabaseTypeChange());
    });

    document.querySelectorAll('input[name="sql-plugin-type"]').forEach(radio => {
      radio.addEventListener('change', () => this.handleSqlPluginTypeChange());
    });

    document.querySelectorAll('input[name="sql-connection-method"]').forEach(radio => {
      radio.addEventListener('change', () => this.handleSqlConnectionMethodChange());
    });

    document.getElementById('sql-auth-type').addEventListener('change', () => this.handleSqlAuthTypeChange());
    document.getElementById('sql-identity-select').addEventListener('change', () => this.handleActionIdentityChange('sql'));
    document.getElementById('cosmos-auth-type').addEventListener('change', () => this.handleCosmosAuthTypeChange());

    // Test SQL connection button
    const testConnBtn = document.getElementById('sql-test-connection-btn');
    if (testConnBtn) {
      testConnBtn.addEventListener('click', () => this.testSqlConnection());
    }

    const testCosmosBtn = document.getElementById('cosmos-test-connection-btn');
    if (testCosmosBtn) {
      testCosmosBtn.addEventListener('click', () => this.testCosmosConnection());
    }

    // Set up display name to generated name conversion
    this.setupNameGeneration();

    // Auto-generate action name when display name changes
    document.getElementById('plugin-display-name').addEventListener('input', (e) => {
      const displayName = e.target.value.trim();
      if (displayName) {
        const actionName = this.generateActionName(displayName);
        document.getElementById('plugin-name').value = actionName;
      }
    });
  }

  async showModal(plugin = null) {
    this.isEditMode = !!plugin;
    this.selectedType = plugin?.type || null;

    // Store original plugin state for change tracking
    this.originalPlugin = plugin ? JSON.parse(JSON.stringify(plugin)) : null;

    // Reset modal state
    this.currentStep = 1;
    this.updateStepIndicator();
    this.showStep(1);
    this.updateNavigationButtons();

    // Set modal title
    const title = this.isEditMode ? 'Edit Action' : 'Add Action';
    document.getElementById('plugin-modal-title').textContent = title;

    // Clear error messages
    document.getElementById('plugin-modal-error').classList.add('d-none');

    // Load available types and populate
    await this.loadAvailableTypes();
    await this.applyDefinitionForSelectedType(this.selectedType);
    await this.loadActionIdentities();

    if (this.isEditMode) {
      this.populateFormFromPlugin(plugin);
      // Skip to step 2 for editing
      this.goToStep(2);
    } else {
      // Clear form for new action
      this.clearForm();
      this.populateActionTypeCards();
    }

    // Show the modal
    const modal = new bootstrap.Modal(document.getElementById('plugin-modal'));
    modal.show();

    return modal;
  }

  async loadAvailableTypes() {
    try {
      // Determine the endpoint based on context (admin vs user)
      const endpoint = window.location.pathname.includes('admin') ?
        '/api/admin/plugins/types' : '/api/user/plugins/types';

      const res = await fetch(endpoint);
      if (!res.ok) throw new Error('Failed to load action types');

      this.availableTypes = await res.json();
      // Hide deprecated/internal action types from the creation UI
      this.availableTypes = this.availableTypes.filter(t => !HIDDEN_ACTION_TYPES.includes(t.type));
      // Sort action types alphabetically by display name
      this.availableTypes.sort((a, b) => {
        const nameA = (a.display || a.displayName || a.type || a.name || '').toLowerCase();
        const nameB = (b.display || b.displayName || b.type || b.name || '').toLowerCase();
        return nameA.localeCompare(nameB);
      });
      this.filteredTypes = [...this.availableTypes]; // Initialize filtered types
    } catch (error) {
      console.error('Error loading action types:', error);
      showToast('Failed to load action types', 'danger');
      this.availableTypes = [];
      this.filteredTypes = [];
    }
  }

  setupNameGeneration() {
    const displayNameInput = document.getElementById('plugin-display-name');
    const generatedNameInput = document.getElementById('plugin-name');

    if (displayNameInput && generatedNameInput) {
      displayNameInput.addEventListener('input', () => {
        const displayName = displayNameInput.value.trim();
        const generatedName = this.generatePluginName(displayName);
        generatedNameInput.value = generatedName;
      });
    }
  }

  generatePluginName(displayName) {
    if (!displayName) return '';

    // Convert to lowercase, replace spaces with underscores, remove invalid characters
    return displayName
      .toLowerCase()
      .replace(/\s+/g, '_')           // Replace spaces with underscores
      .replace(/[^a-z0-9_-]/g, '')    // Remove invalid characters (keep only letters, numbers, underscores, hyphens)
      .replace(/_{2,}/g, '_')         // Replace multiple underscores with single
      .replace(/^_+|_+$/g, '');       // Remove leading/trailing underscores
  }

  populateActionTypeCards() {
    const container = document.getElementById('action-types-container');
    container.innerHTML = '';

    if (this.availableTypes.length === 0) {
      container.innerHTML = '<div class="col-12"><p class="text-muted">No action types available.</p></div>';
      return;
    }

    // Calculate pagination
    const startIndex = (this.currentPage - 1) * this.itemsPerPage;
    const endIndex = startIndex + this.itemsPerPage;
    const paginatedTypes = this.filteredTypes.slice(startIndex, endIndex);

    // Create cards for current page
    paginatedTypes.forEach(type => {
      const card = this.createActionTypeCard(type);
      container.appendChild(card);
    });

    // Add pagination controls
    this.addPaginationControls(container);
  }

  createActionTypeCard(type) {
    const col = document.createElement('div');
    col.className = 'col-md-6 col-lg-4';

    // Use backend-provided display and description
    const displayName = type.display || type.displayName || type.type || type.name;
    const description = type.description || `${displayName} action type`;

    // Truncate description if too long
    const maxLength = 120;
    const truncatedDescription = description.length > maxLength ?
      description.substring(0, maxLength) + '...' : description;
    const needsTruncation = description.length > maxLength;

    const iconClass = getTypeIcon(type.type || type.name);

    col.innerHTML = `
      <div class="card action-type-card h-100" data-type="${type.type || type.name}">
        <div class="card-body">
          <div class="d-flex align-items-center mb-2">
            <i class="bi ${iconClass} me-2" style="font-size: 1.25rem; color: #0d6efd;"></i>
            <h6 class="card-title mb-0">${this.escapeHtml(displayName)}</h6>
          </div>
          <p class="card-text">
            <span class="description-short">${this.escapeHtml(truncatedDescription)}</span>
            ${needsTruncation ? `
              <span class="description-full d-none">${this.escapeHtml(description)}</span>
              <button type="button" class="btn btn-link btn-sm p-0 text-decoration-none view-more-btn">
                <small>View More</small>
              </button>
            ` : ''}
          </p>
        </div>
      </div>
    `;

    // Add click handler for card selection
    col.querySelector('.action-type-card').addEventListener('click', (e) => {
      // Don't trigger selection if clicking the "View More" button
      if (!e.target.classList.contains('view-more-btn')) {
        this.selectActionType(type.type || type.name);
      }
    });

    // Add view more/less functionality
    if (needsTruncation) {
      const viewMoreBtn = col.querySelector('.view-more-btn');
      viewMoreBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggleDescription(col);
      });
    }

    return col;
  }

  selectActionType(typeName) {
    // Remove previous selection
    document.querySelectorAll('.action-type-card').forEach(card => {
      card.classList.remove('selected');
    });

    // Select new type
    const selectedCard = document.querySelector(`[data-type="${typeName}"]`);
    if (selectedCard) {
      selectedCard.classList.add('selected');
      this.selectedType = typeName;

      // Update hidden field
      document.getElementById('plugin-type').value = typeName;

      // Auto-populate description from type if available
      const typeData = this.availableTypes.find(t => (t.type || t.name) === typeName);
      if (typeData && typeData.description) {
        document.getElementById('plugin-description').value = typeData.description;
      }

      // Apply auth definition overrides for this type
      this.applyDefinitionForSelectedType(typeName).catch(err => console.error('Definition apply failed:', err));

      // Pre-configure for step 3 if needed
      this.showConfigSectionForType();
    }
  }

  filterActionTypes(searchTerm) {
    searchTerm = searchTerm.toLowerCase();

    // Filter types based on search term
    this.filteredTypes = this.availableTypes.filter(type => {
      const displayName = (type.display || type.displayName || type.type || type.name).toLowerCase();
      const description = (type.description || '').toLowerCase();
      return displayName.includes(searchTerm) || description.includes(searchTerm);
    });

    // Sort filtered types alphabetically by display name
    this.filteredTypes.sort((a, b) => {
      const nameA = (a.display || a.displayName || a.type || a.name || '').toLowerCase();
      const nameB = (b.display || b.displayName || b.type || b.name || '').toLowerCase();
      return nameA.localeCompare(nameB);
    });

    // Reset to first page when filtering
    this.currentPage = 1;

    // Repopulate cards with filtered results
    this.populateActionTypeCards();
  }

  toggleDescription(cardElement) {
    const shortDesc = cardElement.querySelector('.description-short');
    const fullDesc = cardElement.querySelector('.description-full');
    const btn = cardElement.querySelector('.view-more-btn');

    if (fullDesc.classList.contains('d-none')) {
      shortDesc.classList.add('d-none');
      fullDesc.classList.remove('d-none');
      btn.innerHTML = '<small>View Less</small>';
    } else {
      shortDesc.classList.remove('d-none');
      fullDesc.classList.add('d-none');
      btn.innerHTML = '<small>View More</small>';
    }
  }

  addPaginationControls(container) {
    const totalPages = Math.ceil(this.filteredTypes.length / this.itemsPerPage);

    if (totalPages <= 1) return; // No pagination needed

    const paginationRow = document.createElement('div');
    paginationRow.className = 'col-12 mt-3';

    paginationRow.innerHTML = `
      <nav aria-label="Action types pagination">
        <ul class="pagination justify-content-center mb-0">
          <li class="page-item ${this.currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" id="prev-page" aria-label="Previous">
              <span aria-hidden="true">&laquo;</span>
            </a>
          </li>
          <li class="page-item active">
            <span class="page-link">
              Page ${this.currentPage} of ${totalPages}
            </span>
          </li>
          <li class="page-item ${this.currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" id="next-page" aria-label="Next">
              <span aria-hidden="true">&raquo;</span>
            </a>
          </li>
        </ul>
      </nav>
    `;

    container.appendChild(paginationRow);

    // Add event listeners for pagination
    const prevBtn = paginationRow.querySelector('#prev-page');
    const nextBtn = paginationRow.querySelector('#next-page');

    prevBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (this.currentPage > 1) {
        this.currentPage--;
        this.populateActionTypeCards();
      }
    });

    nextBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (this.currentPage < totalPages) {
        this.currentPage++;
        this.populateActionTypeCards();
      }
    });
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

  skipToEnd() {
    // Skip to the last step (configuration)
    this.goToStep(this.maxSteps);
  }

  goToStep(stepNumber) {
    if (stepNumber < 1 || stepNumber > this.maxSteps) return;

    this.currentStep = stepNumber;
    this.showStep(stepNumber);
    this.updateStepIndicator();
    this.updateNavigationButtons();

    // Handle step-specific logic
    if (stepNumber === 3) {
      this.showConfigSectionForType();
      this.toggleOpenApiAuthFields();
      this.toggleMcpTransportFields();
      this.toggleMcpAuthFields();
      this.toggleDatabricksAuthFields();
      this.toggleGenericAuthFields();
    } else if (stepNumber === 5) {
      // Populate summary when reaching the summary step
      this.populateSummary();
    }
  }

  isOpenApiType(type = this.selectedType) {
    return !!(type && type.toLowerCase().includes('openapi'));
  }

  isSqlType(type = this.selectedType) {
    return !!(
      type && (
        type.toLowerCase().includes('sql') ||
        type.toLowerCase() === 'sql_schema' ||
        type.toLowerCase() === 'sql_query'
      )
    );
  }

  isCosmosType(type = this.selectedType) {
    return !!(type && type.toLowerCase() === 'cosmos_query');
  }

  isDocumentSearchType(type = this.selectedType) {
    return !!(type && ['search', 'document_search'].includes(type.toLowerCase()));
  }

  isBlobStorageType(type = this.selectedType) {
    return !!(type && type.toLowerCase() === BLOB_STORAGE_PLUGIN_TYPE);
  }

  isDatabricksType(type = this.selectedType) {
    return !!(type && [DATABRICKS_PLUGIN_TYPE, 'databricks_table'].includes(type.toLowerCase()));
  }

  isSnowflakeType(type = this.selectedType) {
    return !!(type && type.toLowerCase() === SNOWFLAKE_PLUGIN_TYPE);
  }

  isTableauType(type = this.selectedType) {
    return !!(type && type.toLowerCase() === TABLEAU_PLUGIN_TYPE);
  }

  isMcpType(type = this.selectedType) {
    return !!(type && type.toLowerCase() === MCP_PLUGIN_TYPE);
  }

  isSimpleChatType(type = this.selectedType) {
    return !!(type && type.toLowerCase() === 'simplechat');
  }

  isMsGraphType(type = this.selectedType) {
    return !!(type && type.toLowerCase() === 'msgraph');
  }

  isAzureMapsType(type = this.selectedType) {
    return !!(type && type.toLowerCase() === AZURE_MAPS_PLUGIN_TYPE);
  }

  isChartType(type = this.selectedType) {
    return !!(type && type.toLowerCase() === 'chart');
  }

  getDefaultSimpleChatCapabilities() {
    const defaults = {};
    SIMPLECHAT_CAPABILITY_DEFINITIONS.forEach(definition => {
      defaults[definition.key] = true;
    });
    return defaults;
  }

  normalizeSimpleChatCapabilities(rawCapabilities = null) {
    const defaults = this.getDefaultSimpleChatCapabilities();
    if (!rawCapabilities || typeof rawCapabilities !== 'object' || Array.isArray(rawCapabilities)) {
      return defaults;
    }

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

    return defaults;
  }

  renderSimpleChatConfiguration() {
    const list = document.getElementById('simplechat-capabilities-list');
    if (!list) {
      return;
    }

    list.innerHTML = '';
    SIMPLECHAT_CAPABILITY_DEFINITIONS.forEach(definition => {
      const wrapper = document.createElement('div');
      wrapper.className = 'form-check mb-3';

      const checkbox = document.createElement('input');
      checkbox.className = 'form-check-input';
      checkbox.type = 'checkbox';
      checkbox.id = `simplechat-capability-${definition.key}`;
      checkbox.checked = Boolean(this.simpleChatCapabilityState?.[definition.key]);

      const label = document.createElement('label');
      label.className = 'form-check-label';
      label.setAttribute('for', checkbox.id);
      label.innerHTML = `<span class="fw-medium">${this.escapeHtml(definition.label)}</span><br><span class="text-muted small">${this.escapeHtml(definition.description)}</span>`;

      checkbox.addEventListener('change', () => {
        this.simpleChatCapabilityState = {
          ...this.simpleChatCapabilityState,
          [definition.key]: checkbox.checked
        };
      });

      wrapper.appendChild(checkbox);
      wrapper.appendChild(label);
      list.appendChild(wrapper);
    });
  }

  setSimpleChatCapabilities(rawCapabilities = null) {
    this.simpleChatCapabilityState = this.normalizeSimpleChatCapabilities(rawCapabilities);
    this.renderSimpleChatConfiguration();
  }

  getSelectedSimpleChatCapabilities() {
    return this.normalizeSimpleChatCapabilities(this.simpleChatCapabilityState);
  }

  getDefaultMsGraphCapabilities() {
    const defaults = {};
    MSGRAPH_CAPABILITY_DEFINITIONS.forEach(definition => {
      defaults[definition.key] = true;
    });
    return defaults;
  }

  normalizeMsGraphCapabilities(rawCapabilities = null) {
    const defaults = this.getDefaultMsGraphCapabilities();
    if (!rawCapabilities || typeof rawCapabilities !== 'object' || Array.isArray(rawCapabilities)) {
      return defaults;
    }

    MSGRAPH_CAPABILITY_DEFINITIONS.forEach(definition => {
      if (Object.prototype.hasOwnProperty.call(rawCapabilities, definition.key)) {
        defaults[definition.key] = Boolean(rawCapabilities[definition.key]);
      }
    });

    return defaults;
  }

  renderMsGraphConfiguration() {
    const list = document.getElementById('msgraph-capabilities-list');
    if (!list) {
      return;
    }

    list.innerHTML = '';
    MSGRAPH_CAPABILITY_DEFINITIONS.forEach(definition => {
      const wrapper = document.createElement('div');
      wrapper.className = 'form-check mb-3';

      const checkbox = document.createElement('input');
      checkbox.className = 'form-check-input';
      checkbox.type = 'checkbox';
      checkbox.id = `msgraph-capability-${definition.key}`;
      checkbox.checked = Boolean(this.msGraphCapabilityState?.[definition.key]);

      const label = document.createElement('label');
      label.className = 'form-check-label';
      label.setAttribute('for', checkbox.id);
      label.innerHTML = `<span class="fw-medium">${this.escapeHtml(definition.label)}</span><br><span class="text-muted small">${this.escapeHtml(definition.description)}</span>`;

      let deliveryOptions = null;
      if (definition.key === 'send_mail') {
        deliveryOptions = this.createMsGraphDeliveryConfiguration('mail');
        deliveryOptions.classList.toggle('d-none', !checkbox.checked);
      } else if (definition.key === 'create_calendar_invite') {
        deliveryOptions = this.createMsGraphDeliveryConfiguration('calendar');
        deliveryOptions.classList.toggle('d-none', !checkbox.checked);
      }

      checkbox.addEventListener('change', () => {
        this.msGraphCapabilityState = {
          ...this.msGraphCapabilityState,
          [definition.key]: checkbox.checked
        };
        if (deliveryOptions) {
          deliveryOptions.classList.toggle('d-none', !checkbox.checked);
        }
      });

      wrapper.appendChild(checkbox);
      wrapper.appendChild(label);
      if (deliveryOptions) {
        wrapper.appendChild(deliveryOptions);
      }
      list.appendChild(wrapper);
    });

    this.updateMsGraphMailDelayVisibility();
    this.updateMsGraphCalendarDelayVisibility();
  }

  setMsGraphCapabilities(rawCapabilities = null) {
    this.msGraphCapabilityState = this.normalizeMsGraphCapabilities(rawCapabilities);
    this.renderMsGraphConfiguration();
  }

  getSelectedMsGraphCapabilities() {
    return this.normalizeMsGraphCapabilities(this.msGraphCapabilityState);
  }

  createMsGraphDeliveryConfiguration(kind) {
    const isMail = kind === 'mail';
    const modeId = isMail ? 'msgraph-mail-send-mode' : 'msgraph-calendar-send-mode';
    const delayGroupId = isMail ? 'msgraph-mail-delay-group' : 'msgraph-calendar-delay-group';
    const delayInputId = isMail ? 'msgraph-mail-delay-seconds' : 'msgraph-calendar-delay-seconds';
    const delayValueId = isMail ? 'msgraph-mail-delay-seconds-value' : 'msgraph-calendar-delay-seconds-value';
    const defaultMode = isMail ? MSGRAPH_DEFAULT_MAIL_SEND_MODE : MSGRAPH_DEFAULT_CALENDAR_SEND_MODE;
    const defaultDelay = isMail ? MSGRAPH_DEFAULT_MAIL_DELAY_SECONDS : MSGRAPH_DEFAULT_CALENDAR_DELAY_SECONDS;
    const updateVisibility = isMail
      ? () => this.updateMsGraphMailDelayVisibility()
      : () => this.updateMsGraphCalendarDelayVisibility();

    const optionsWrapper = document.createElement('div');
    optionsWrapper.className = 'msgraph-capability-options border-start ps-3 ms-4 mt-2';
    optionsWrapper.id = isMail ? 'msgraph-delivery-send_mail-options' : 'msgraph-delivery-create_calendar_invite-options';

    const row = document.createElement('div');
    row.className = 'row g-3 align-items-end';

    const modeColumn = document.createElement('div');
    modeColumn.className = 'col-md-7';

    const modeLabel = document.createElement('label');
    modeLabel.className = 'form-label small mb-1';
    modeLabel.setAttribute('for', modeId);
    modeLabel.textContent = isMail ? 'Email delivery' : 'Calendar invite delivery';

    const modeSelect = document.createElement('select');
    modeSelect.className = 'form-select form-select-sm';
    modeSelect.id = modeId;
    [
      [MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL, 'Draft with manual send'],
      [MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED, 'Draft with delayed send'],
      [MSGRAPH_MAIL_SEND_MODE_AUTO_SEND, 'Auto send']
    ].forEach(([value, label]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      modeSelect.appendChild(option);
    });
    modeSelect.value = defaultMode;
    modeSelect.addEventListener('change', updateVisibility);

    modeColumn.appendChild(modeLabel);
    modeColumn.appendChild(modeSelect);
    row.appendChild(modeColumn);

    const delayColumn = document.createElement('div');
    delayColumn.className = 'col-md-5';
    delayColumn.id = delayGroupId;

    const delayHeader = document.createElement('div');
    delayHeader.className = 'd-flex align-items-center justify-content-between gap-2';

    const delayLabel = document.createElement('label');
    delayLabel.className = 'form-label small mb-1';
    delayLabel.setAttribute('for', delayInputId);
    delayLabel.textContent = 'Delay';

    const delayValue = document.createElement('span');
    delayValue.className = 'badge text-bg-light';
    delayValue.id = delayValueId;
    delayValue.textContent = `${defaultDelay} seconds`;

    delayHeader.appendChild(delayLabel);
    delayHeader.appendChild(delayValue);

    const delayInput = document.createElement('input');
    delayInput.type = 'range';
    delayInput.className = 'form-range';
    delayInput.id = delayInputId;
    delayInput.min = String(isMail ? MSGRAPH_MIN_MAIL_DELAY_SECONDS : MSGRAPH_MIN_CALENDAR_DELAY_SECONDS);
    delayInput.max = String(isMail ? MSGRAPH_MAX_MAIL_DELAY_SECONDS : MSGRAPH_MAX_CALENDAR_DELAY_SECONDS);
    delayInput.step = '5';
    delayInput.value = String(defaultDelay);
    delayInput.addEventListener('input', updateVisibility);
    delayInput.addEventListener('change', updateVisibility);

    delayColumn.appendChild(delayHeader);
    delayColumn.appendChild(delayInput);
    row.appendChild(delayColumn);
    optionsWrapper.appendChild(row);

    return optionsWrapper;
  }

  normalizeMsGraphMailSendMode(rawMode = '') {
    const normalizedMode = String(rawMode || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    const aliases = {
      draft: MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
      manual: MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
      draft_manual: MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
      manual_draft: MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
      delayed: MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
      delay: MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
      draft_delayed: MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
      delayed_delivery: MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
      auto: MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
      autosend: MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
      auto_send: MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
      send: MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
      send_now: MSGRAPH_MAIL_SEND_MODE_AUTO_SEND
    };
    return aliases[normalizedMode] || MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL;
  }

  normalizeMsGraphCalendarSendMode(rawMode = '') {
    const normalizedMode = String(rawMode || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    const aliases = {
      draft: MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
      manual: MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
      draft_manual: MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
      manual_review: MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL,
      delayed: MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
      delay: MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
      draft_delayed: MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
      delayed_delivery: MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED,
      auto: MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
      autosend: MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
      auto_send: MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
      send: MSGRAPH_MAIL_SEND_MODE_AUTO_SEND,
      send_now: MSGRAPH_MAIL_SEND_MODE_AUTO_SEND
    };
    return aliases[normalizedMode] || MSGRAPH_MAIL_SEND_MODE_AUTO_SEND;
  }

  normalizeMsGraphMailDelaySeconds(rawDelay = null) {
    const parsedDelay = parseInt(rawDelay, 10);
    if (Number.isNaN(parsedDelay)) {
      return MSGRAPH_DEFAULT_MAIL_DELAY_SECONDS;
    }
    return Math.max(MSGRAPH_MIN_MAIL_DELAY_SECONDS, Math.min(parsedDelay, MSGRAPH_MAX_MAIL_DELAY_SECONDS));
  }

  normalizeMsGraphCalendarDelaySeconds(rawDelay = null) {
    const parsedDelay = parseInt(rawDelay, 10);
    if (Number.isNaN(parsedDelay)) {
      return MSGRAPH_DEFAULT_CALENDAR_DELAY_SECONDS;
    }
    return Math.max(MSGRAPH_MIN_CALENDAR_DELAY_SECONDS, Math.min(parsedDelay, MSGRAPH_MAX_CALENDAR_DELAY_SECONDS));
  }

  getMsGraphMailSendConfiguration() {
    const mode = this.normalizeMsGraphMailSendMode(document.getElementById('msgraph-mail-send-mode')?.value);
    const delaySeconds = this.normalizeMsGraphMailDelaySeconds(document.getElementById('msgraph-mail-delay-seconds')?.value);
    return {
      msgraph_mail_send_mode: mode,
      msgraph_mail_delay_seconds: delaySeconds
    };
  }

  getMsGraphCalendarSendConfiguration() {
    const mode = this.normalizeMsGraphCalendarSendMode(document.getElementById('msgraph-calendar-send-mode')?.value);
    const delaySeconds = this.normalizeMsGraphCalendarDelaySeconds(document.getElementById('msgraph-calendar-delay-seconds')?.value);
    return {
      msgraph_calendar_send_mode: mode,
      msgraph_calendar_delay_seconds: delaySeconds
    };
  }

  setMsGraphMailSendConfiguration(additionalFields = {}) {
    const modeSelect = document.getElementById('msgraph-mail-send-mode');
    const delayInput = document.getElementById('msgraph-mail-delay-seconds');
    if (modeSelect) {
      modeSelect.value = this.normalizeMsGraphMailSendMode(additionalFields.msgraph_mail_send_mode || additionalFields.mail_send_mode);
    }
    if (delayInput) {
      delayInput.value = String(this.normalizeMsGraphMailDelaySeconds(additionalFields.msgraph_mail_delay_seconds || additionalFields.mail_delay_seconds));
    }
    this.updateMsGraphMailDelayVisibility();
  }

  setMsGraphCalendarSendConfiguration(additionalFields = {}) {
    const modeSelect = document.getElementById('msgraph-calendar-send-mode');
    const delayInput = document.getElementById('msgraph-calendar-delay-seconds');
    if (modeSelect) {
      modeSelect.value = this.normalizeMsGraphCalendarSendMode(additionalFields.msgraph_calendar_send_mode || additionalFields.calendar_send_mode);
    }
    if (delayInput) {
      delayInput.value = String(this.normalizeMsGraphCalendarDelaySeconds(additionalFields.msgraph_calendar_delay_seconds || additionalFields.calendar_delay_seconds));
    }
    this.updateMsGraphCalendarDelayVisibility();
  }

  updateMsGraphMailDelayVisibility() {
    const delayGroup = document.getElementById('msgraph-mail-delay-group');
    const mode = this.normalizeMsGraphMailSendMode(document.getElementById('msgraph-mail-send-mode')?.value);
    const delayInput = document.getElementById('msgraph-mail-delay-seconds');
    const delayValue = document.getElementById('msgraph-mail-delay-seconds-value');
    if (delayInput) {
      delayInput.value = String(this.normalizeMsGraphMailDelaySeconds(delayInput.value));
    }
    if (delayValue) {
      delayValue.textContent = `${this.normalizeMsGraphMailDelaySeconds(delayInput?.value)} seconds`;
    }
    if (delayGroup) {
      delayGroup.classList.toggle('d-none', mode !== MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED);
    }
  }

  updateMsGraphCalendarDelayVisibility() {
    const delayGroup = document.getElementById('msgraph-calendar-delay-group');
    const mode = this.normalizeMsGraphCalendarSendMode(document.getElementById('msgraph-calendar-send-mode')?.value);
    const delayInput = document.getElementById('msgraph-calendar-delay-seconds');
    const delayValue = document.getElementById('msgraph-calendar-delay-seconds-value');
    if (delayInput) {
      delayInput.value = String(this.normalizeMsGraphCalendarDelaySeconds(delayInput.value));
    }
    if (delayValue) {
      delayValue.textContent = `${this.normalizeMsGraphCalendarDelaySeconds(delayInput?.value)} seconds`;
    }
    if (delayGroup) {
      delayGroup.classList.toggle('d-none', mode !== MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED);
    }
  }

  formatMsGraphMailSendMode(mode) {
    const labels = {
      [MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL]: 'Draft with manual send',
      [MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED]: 'Draft with delayed send',
      [MSGRAPH_MAIL_SEND_MODE_AUTO_SEND]: 'Auto send'
    };
    return labels[this.normalizeMsGraphMailSendMode(mode)] || labels[MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL];
  }

  formatMsGraphCalendarSendMode(mode) {
    const labels = {
      [MSGRAPH_MAIL_SEND_MODE_DRAFT_MANUAL]: 'Draft with manual send',
      [MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED]: 'Draft with delayed send',
      [MSGRAPH_MAIL_SEND_MODE_AUTO_SEND]: 'Auto send'
    };
    return labels[this.normalizeMsGraphCalendarSendMode(mode)] || labels[MSGRAPH_MAIL_SEND_MODE_AUTO_SEND];
  }

  getDefaultChartCapabilities() {
    const defaults = {};
    CHART_CAPABILITY_DEFINITIONS.forEach(definition => {
      defaults[definition.key] = true;
    });
    return defaults;
  }

  normalizeChartCapabilities(rawCapabilities = null) {
    const defaults = this.getDefaultChartCapabilities();
    if (!rawCapabilities || typeof rawCapabilities !== 'object' || Array.isArray(rawCapabilities)) {
      return defaults;
    }

    CHART_CAPABILITY_DEFINITIONS.forEach(definition => {
      if (Object.prototype.hasOwnProperty.call(rawCapabilities, definition.key)) {
        defaults[definition.key] = Boolean(rawCapabilities[definition.key]);
      }
    });

    return defaults;
  }

  renderChartConfiguration() {
    const list = document.getElementById('chart-capabilities-list');
    if (!list) {
      return;
    }

    list.innerHTML = '';
    CHART_CAPABILITY_DEFINITIONS.forEach(definition => {
      const wrapper = document.createElement('div');
      wrapper.className = 'form-check mb-3';

      const checkbox = document.createElement('input');
      checkbox.className = 'form-check-input';
      checkbox.type = 'checkbox';
      checkbox.id = `chart-capability-${definition.key}`;
      checkbox.checked = Boolean(this.chartCapabilityState?.[definition.key]);

      const label = document.createElement('label');
      label.className = 'form-check-label';
      label.setAttribute('for', checkbox.id);
      label.innerHTML = `<span class="fw-medium">${this.escapeHtml(definition.label)}</span><br><span class="text-muted small">${this.escapeHtml(definition.description)}</span>`;

      checkbox.addEventListener('change', () => {
        this.chartCapabilityState = {
          ...this.chartCapabilityState,
          [definition.key]: checkbox.checked
        };
      });

      wrapper.appendChild(checkbox);
      wrapper.appendChild(label);
      list.appendChild(wrapper);
    });
  }

  setChartCapabilities(rawCapabilities = null) {
    this.chartCapabilityState = this.normalizeChartCapabilities(rawCapabilities);
    this.renderChartConfiguration();
  }

  getSelectedChartCapabilities() {
    return this.normalizeChartCapabilities(this.chartCapabilityState);
  }

  getDefaultBlobStorageCapabilities() {
    return {
      list_container_contents: true,
      read_file_content: true,
      upload_file_to_container: false
    };
  }

  normalizeBlobStorageCapabilities(rawCapabilities = null) {
    const defaults = this.getDefaultBlobStorageCapabilities();
    if (!rawCapabilities || typeof rawCapabilities !== 'object' || Array.isArray(rawCapabilities)) {
      return defaults;
    }

    BLOB_STORAGE_CAPABILITY_DEFINITIONS.forEach(definition => {
      if (Object.prototype.hasOwnProperty.call(rawCapabilities, definition.key)) {
        defaults[definition.key] = Boolean(rawCapabilities[definition.key]);
      }
    });

    return defaults;
  }

  getDefaultBlobStorageReadFileTypes() {
    const defaults = {};
    BLOB_STORAGE_FILE_TYPE_DEFINITIONS.forEach(definition => {
      defaults[definition.key] = true;
    });
    return defaults;
  }

  getDefaultBlobStorageUploadFileTypes() {
    const defaults = {};
    BLOB_STORAGE_FILE_TYPE_DEFINITIONS.forEach(definition => {
      defaults[definition.key] = true;
    });
    return defaults;
  }

  normalizeBlobStorageReadFileTypes(rawFileTypes = null) {
    const defaults = this.getDefaultBlobStorageReadFileTypes();
    if (!rawFileTypes || typeof rawFileTypes !== 'object' || Array.isArray(rawFileTypes)) {
      return defaults;
    }

    BLOB_STORAGE_FILE_TYPE_DEFINITIONS.forEach(definition => {
      if (Object.prototype.hasOwnProperty.call(rawFileTypes, definition.key)) {
        defaults[definition.key] = Boolean(rawFileTypes[definition.key]);
      }
    });

    return defaults;
  }

  normalizeBlobStorageUploadFileTypes(rawFileTypes = null) {
    const defaults = this.getDefaultBlobStorageUploadFileTypes();
    if (!rawFileTypes || typeof rawFileTypes !== 'object' || Array.isArray(rawFileTypes)) {
      return defaults;
    }

    BLOB_STORAGE_FILE_TYPE_DEFINITIONS.forEach(definition => {
      if (Object.prototype.hasOwnProperty.call(rawFileTypes, definition.key)) {
        defaults[definition.key] = Boolean(rawFileTypes[definition.key]);
      }
    });

    return defaults;
  }

  renderBlobStorageFileTypes(listId, state, stateKey) {
    const list = document.getElementById(listId);
    if (!list) {
      return;
    }

    list.innerHTML = '';
    BLOB_STORAGE_FILE_TYPE_DEFINITIONS.forEach(definition => {
      const wrapper = document.createElement('div');
      wrapper.className = 'form-check mb-2';

      const checkbox = document.createElement('input');
      checkbox.className = 'form-check-input';
      checkbox.type = 'checkbox';
      checkbox.id = `${stateKey}-${definition.key}`;
      checkbox.checked = Boolean(state?.[definition.key]);

      const label = document.createElement('label');
      label.className = 'form-check-label';
      label.setAttribute('for', checkbox.id);
      label.innerHTML = `<span class="fw-medium">${this.escapeHtml(definition.label)}</span><br><span class="text-muted small">${this.escapeHtml(definition.description)}</span>`;

      checkbox.addEventListener('change', () => {
        if (stateKey === 'blob-storage-read-file-type') {
          this.blobStorageReadFileTypeState = {
            ...this.blobStorageReadFileTypeState,
            [definition.key]: checkbox.checked
          };
          return;
        }

        this.blobStorageUploadFileTypeState = {
          ...this.blobStorageUploadFileTypeState,
          [definition.key]: checkbox.checked
        };
      });

      wrapper.appendChild(checkbox);
      wrapper.appendChild(label);
      list.appendChild(wrapper);
    });
  }

  updateBlobStorageFileTypeVisibility() {
    const readSection = document.getElementById('blob-storage-read-file-types-section');
    const uploadSection = document.getElementById('blob-storage-upload-file-types-section');
    if (readSection) {
      if (this.blobStorageCapabilityState?.read_file_content) {
        readSection.classList.remove('d-none');
      } else {
        readSection.classList.add('d-none');
      }
    }

    if (uploadSection) {
      if (this.blobStorageCapabilityState?.upload_file_to_container) {
        uploadSection.classList.remove('d-none');
      } else {
        uploadSection.classList.add('d-none');
      }
    }
  }

  renderBlobStorageConfiguration() {
    const capabilityList = document.getElementById('blob-storage-capabilities-list');
    if (!capabilityList) {
      return;
    }

    capabilityList.innerHTML = '';
    BLOB_STORAGE_CAPABILITY_DEFINITIONS.forEach(definition => {
      const wrapper = document.createElement('div');
      wrapper.className = 'form-check mb-3';

      const checkbox = document.createElement('input');
      checkbox.className = 'form-check-input';
      checkbox.type = 'checkbox';
      checkbox.id = `blob-storage-capability-${definition.key}`;
      checkbox.checked = Boolean(this.blobStorageCapabilityState?.[definition.key]);

      const label = document.createElement('label');
      label.className = 'form-check-label';
      label.setAttribute('for', checkbox.id);
      label.innerHTML = `<span class="fw-medium">${this.escapeHtml(definition.label)}</span><br><span class="text-muted small">${this.escapeHtml(definition.description)}</span>`;

      checkbox.addEventListener('change', () => {
        this.blobStorageCapabilityState = {
          ...this.blobStorageCapabilityState,
          [definition.key]: checkbox.checked
        };
        this.updateBlobStorageFileTypeVisibility();
      });

      wrapper.appendChild(checkbox);
      wrapper.appendChild(label);
      capabilityList.appendChild(wrapper);
    });

    this.renderBlobStorageFileTypes(
      'blob-storage-read-file-types-list',
      this.blobStorageReadFileTypeState,
      'blob-storage-read-file-type'
    );
    this.renderBlobStorageFileTypes(
      'blob-storage-upload-file-types-list',
      this.blobStorageUploadFileTypeState,
      'blob-storage-upload-file-type'
    );
    this.updateBlobStorageFileTypeVisibility();
  }

  setBlobStorageConfiguration(additionalFields = {}) {
    const normalizedAdditionalFields = additionalFields || {};
    this.blobStorageCapabilityState = this.normalizeBlobStorageCapabilities(
      normalizedAdditionalFields.blob_storage_capabilities || null
    );
    this.blobStorageReadFileTypeState = this.normalizeBlobStorageReadFileTypes(
      normalizedAdditionalFields.blob_storage_read_file_types || null
    );
    this.blobStorageUploadFileTypeState = this.normalizeBlobStorageUploadFileTypes(
      normalizedAdditionalFields.blob_storage_upload_file_types || null
    );
    this.renderBlobStorageConfiguration();
  }

  getSelectedBlobStorageCapabilities() {
    return this.normalizeBlobStorageCapabilities(this.blobStorageCapabilityState);
  }

  getSelectedBlobStorageReadFileTypes() {
    return this.normalizeBlobStorageReadFileTypes(this.blobStorageReadFileTypeState);
  }

  getSelectedBlobStorageUploadFileTypes() {
    return this.normalizeBlobStorageUploadFileTypes(this.blobStorageUploadFileTypeState);
  }

  normalizeBlobStoragePrefix(prefix = '') {
    return String(prefix || '').trim().replace(/^\/+|\/+$/g, '');
  }

  deriveBlobStorageEndpointFromConnectionString(connectionString = '') {
    const normalizedConnectionString = String(connectionString || '').trim();
    if (!normalizedConnectionString || normalizedConnectionString === 'Stored_In_KeyVault') {
      return '';
    }

    const parsed = {};
    normalizedConnectionString.split(';').forEach(segment => {
      const normalizedSegment = segment.trim();
      if (!normalizedSegment || !normalizedSegment.includes('=')) {
        return;
      }
      const separatorIndex = normalizedSegment.indexOf('=');
      const key = normalizedSegment.slice(0, separatorIndex).trim();
      const value = normalizedSegment.slice(separatorIndex + 1).trim();
      if (key) {
        parsed[key] = value;
      }
    });

    if ((parsed.UseDevelopmentStorage || '').toLowerCase() === 'true') {
      return 'http://127.0.0.1:10000/devstoreaccount1';
    }

    if (parsed.BlobEndpoint) {
      return String(parsed.BlobEndpoint).replace(/\/+$/, '');
    }

    if (!parsed.AccountName) {
      return '';
    }

    const protocol = parsed.DefaultEndpointsProtocol || 'https';
    const suffix = parsed.EndpointSuffix || 'core.windows.net';
    return `${protocol}://${parsed.AccountName}.blob.${suffix}`.replace(/\/+$/, '');
  }

  normalizeDatabricksWorkspaceUrl(workspaceUrl = '') {
    return String(workspaceUrl || '').trim().replace(/\/+$/, '').replace(/\/api\/2\.0\/sql\/statements$/i, '');
  }

  getDatabricksIdentityAuthMethod(identity) {
    const authType = this.getIdentityAuthType(identity);
    if (authType === 'managed_identity') {
      return 'managed_identity';
    }
    if (authType === 'bearer_token') {
      return 'bearer';
    }
    return 'pat';
  }

  toggleDatabricksAuthFields() {
    const selectedIdentity = this.getSelectedActionIdentity('databricks');
    const authMethodSelect = document.getElementById('databricks-auth-method');
    const groups = {
      token: document.getElementById('databricks-token-group'),
      servicePrincipal: document.getElementById('databricks-service-principal-group'),
      managedIdentity: document.getElementById('databricks-managed-identity-info')
    };

    if (authMethodSelect) {
      authMethodSelect.disabled = Boolean(selectedIdentity);
    }

    Object.values(groups).forEach(group => {
      if (group) {
        group.classList.add('d-none');
      }
    });

    if (selectedIdentity) {
      return;
    }

    const authMethod = authMethodSelect?.value || 'pat';
    if (authMethod === 'pat' || authMethod === 'bearer') {
      groups.token?.classList.remove('d-none');
    } else if (authMethod === 'service_principal') {
      groups.servicePrincipal?.classList.remove('d-none');
    } else if (authMethod === 'managed_identity') {
      groups.managedIdentity?.classList.remove('d-none');
    }
  }

  populateDatabricksForm(plugin) {
    const additionalFields = plugin.additionalFields || plugin.additional_fields || {};
    const auth = plugin.auth || {};
    const workspaceUrl = this.normalizeDatabricksWorkspaceUrl(plugin.endpoint || additionalFields.workspace_url || '');

    document.getElementById('databricks-workspace-url').value = workspaceUrl;
    document.getElementById('databricks-cloud').value = additionalFields.cloud || DATABRICKS_DEFAULT_CLOUD;
    document.getElementById('databricks-warehouse-id').value = additionalFields.warehouse_id || '';
    document.getElementById('databricks-catalog').value = additionalFields.catalog || '';
    document.getElementById('databricks-schema').value = additionalFields.schema || additionalFields.database || '';
    document.getElementById('databricks-max-rows').value = additionalFields.max_rows || 1000;
    document.getElementById('databricks-timeout').value = additionalFields.timeout || 30;
    document.getElementById('databricks-wait-timeout').value = additionalFields.wait_timeout || 30;

    let authMethod = additionalFields.auth_method || 'pat';
    if (auth.type === 'servicePrincipal') {
      authMethod = 'service_principal';
      document.getElementById('databricks-client-id').value = auth.identity || '';
      document.getElementById('databricks-client-secret').value = auth.key || '';
      document.getElementById('databricks-tenant-id').value = auth.tenantId || '';
    } else if (auth.type === 'identity' && auth.identity === 'managed_identity') {
      authMethod = 'managed_identity';
    } else if (auth.type === 'key') {
      document.getElementById('databricks-token').value = auth.key || '';
    }

    document.getElementById('databricks-auth-method').value = authMethod;
    this.setSelectedActionIdentity('databricks', plugin.identity_id || '');
    this.handleActionIdentityChange('databricks');
  }

  getDatabricksConfiguration() {
    const workspaceUrl = this.normalizeDatabricksWorkspaceUrl(document.getElementById('databricks-workspace-url')?.value || '');
    const warehouseId = document.getElementById('databricks-warehouse-id')?.value.trim() || '';
    const selectedIdentity = this.getSelectedActionIdentity('databricks');
    const authMethod = document.getElementById('databricks-auth-method')?.value || 'pat';
    const additionalFields = {
      cloud: DATABRICKS_DEFAULT_CLOUD,
      workspace_url: workspaceUrl,
      auth_method: selectedIdentity ? this.getDatabricksIdentityAuthMethod(selectedIdentity) : authMethod,
      warehouse_id: warehouseId,
      catalog: document.getElementById('databricks-catalog')?.value.trim() || '',
      schema: document.getElementById('databricks-schema')?.value.trim() || '',
      read_only: true,
      max_rows: parseInt(document.getElementById('databricks-max-rows')?.value, 10) || 1000,
      timeout: parseInt(document.getElementById('databricks-timeout')?.value, 10) || 30,
      wait_timeout: parseInt(document.getElementById('databricks-wait-timeout')?.value, 10) || 30
    };
    const auth = {};
    let identityId = '';

    if (selectedIdentity) {
      identityId = selectedIdentity.id || selectedIdentity.identity_id || '';
      auth.type = 'identity';
      auth.identity = identityId;
      additionalFields.identity_auth_type = this.getIdentityAuthType(selectedIdentity);
    } else if (authMethod === 'service_principal') {
      auth.type = 'servicePrincipal';
      auth.identity = document.getElementById('databricks-client-id')?.value.trim() || '';
      auth.key = document.getElementById('databricks-client-secret')?.value.trim() || '';
      auth.tenantId = document.getElementById('databricks-tenant-id')?.value.trim() || '';
    } else if (authMethod === 'managed_identity') {
      auth.type = 'identity';
      auth.identity = 'managed_identity';
    } else {
      auth.type = 'key';
      auth.key = document.getElementById('databricks-token')?.value.trim() || '';
    }

    return {
      endpoint: workspaceUrl,
      auth,
      additionalFields,
      identityId
    };
  }

  normalizeSnowflakeAccount(account = '') {
    return String(account || '')
      .trim()
      .replace(/^https?:\/\//i, '')
      .replace(/\.snowflakecomputing\.com.*$/i, '')
      .replace(/\/+$/, '');
  }

  getSnowflakeIdentityAuthMethod(identity) {
    const authType = this.getIdentityAuthType(identity);
    if (authType === 'api_key') {
      return SNOWFLAKE_AUTH_METHOD_KEY_PAIR;
    }
    if (authType === 'bearer_token') {
      return SNOWFLAKE_AUTH_METHOD_OAUTH;
    }
    return SNOWFLAKE_AUTH_METHOD_PASSWORD;
  }

  toggleSnowflakeAuthFields() {
    const selectedIdentity = this.getSelectedActionIdentity('snowflake');
    const authMethodSelect = document.getElementById('snowflake-auth-method');
    const groups = {
      password: document.getElementById('snowflake-password-group'),
      privateKey: document.getElementById('snowflake-private-key-group'),
      oauth: document.getElementById('snowflake-oauth-token-group')
    };

    if (authMethodSelect) {
      authMethodSelect.disabled = Boolean(selectedIdentity);
    }

    Object.values(groups).forEach(group => {
      if (group) {
        group.classList.add('d-none');
      }
    });

    if (selectedIdentity) {
      return;
    }

    const authMethod = authMethodSelect?.value || SNOWFLAKE_AUTH_METHOD_PASSWORD;
    if (authMethod === SNOWFLAKE_AUTH_METHOD_PASSWORD) {
      groups.password?.classList.remove('d-none');
    } else if (authMethod === SNOWFLAKE_AUTH_METHOD_KEY_PAIR) {
      groups.privateKey?.classList.remove('d-none');
    } else if (authMethod === SNOWFLAKE_AUTH_METHOD_OAUTH) {
      groups.oauth?.classList.remove('d-none');
    }
  }

  populateSnowflakeForm(plugin) {
    const additionalFields = plugin.additionalFields || plugin.additional_fields || {};
    const auth = plugin.auth || {};

    document.getElementById('snowflake-account').value = this.normalizeSnowflakeAccount(additionalFields.account || '');
    document.getElementById('snowflake-user').value = additionalFields.user || auth.identity || '';
    document.getElementById('snowflake-warehouse').value = additionalFields.warehouse || '';
    document.getElementById('snowflake-database').value = additionalFields.database || '';
    document.getElementById('snowflake-schema').value = additionalFields.schema || '';
    document.getElementById('snowflake-role').value = additionalFields.role || '';
    document.getElementById('snowflake-max-rows').value = additionalFields.max_rows || 1000;
    document.getElementById('snowflake-timeout').value = additionalFields.timeout || 30;
    document.getElementById('snowflake-login-timeout').value = additionalFields.login_timeout || 30;

    let authMethod = additionalFields.auth_method || SNOWFLAKE_AUTH_METHOD_PASSWORD;
    if (auth.type === 'username_password') {
      authMethod = SNOWFLAKE_AUTH_METHOD_PASSWORD;
      document.getElementById('snowflake-password').value = auth.key || '';
    } else if (auth.type === 'key' && authMethod === SNOWFLAKE_AUTH_METHOD_KEY_PAIR) {
      document.getElementById('snowflake-private-key').value = auth.key || '';
      document.getElementById('snowflake-private-key-passphrase').value = additionalFields.private_key_passphrase || '';
    } else if (auth.type === 'key' && authMethod === SNOWFLAKE_AUTH_METHOD_OAUTH) {
      document.getElementById('snowflake-oauth-token').value = auth.key || '';
    }

    document.getElementById('snowflake-auth-method').value = authMethod;
    this.setSelectedActionIdentity('snowflake', plugin.identity_id || '');
    this.handleActionIdentityChange('snowflake');
  }

  getSnowflakeConfiguration() {
    const account = this.normalizeSnowflakeAccount(document.getElementById('snowflake-account')?.value || '');
    const snowflakeUser = document.getElementById('snowflake-user')?.value.trim() || '';
    const selectedIdentity = this.getSelectedActionIdentity('snowflake');
    const authMethod = document.getElementById('snowflake-auth-method')?.value || SNOWFLAKE_AUTH_METHOD_PASSWORD;
    const additionalFields = {
      account,
      user: snowflakeUser,
      auth_method: selectedIdentity ? this.getSnowflakeIdentityAuthMethod(selectedIdentity) : authMethod,
      warehouse: document.getElementById('snowflake-warehouse')?.value.trim() || '',
      database: document.getElementById('snowflake-database')?.value.trim() || '',
      schema: document.getElementById('snowflake-schema')?.value.trim() || '',
      role: document.getElementById('snowflake-role')?.value.trim() || '',
      read_only: true,
      max_rows: parseInt(document.getElementById('snowflake-max-rows')?.value, 10) || 1000,
      timeout: parseInt(document.getElementById('snowflake-timeout')?.value, 10) || 30,
      login_timeout: parseInt(document.getElementById('snowflake-login-timeout')?.value, 10) || 30
    };
    const auth = {};
    let identityId = '';

    if (selectedIdentity) {
      identityId = selectedIdentity.id || selectedIdentity.identity_id || '';
      auth.type = 'identity';
      auth.identity = identityId;
      additionalFields.identity_auth_type = this.getIdentityAuthType(selectedIdentity);
    } else if (authMethod === SNOWFLAKE_AUTH_METHOD_PASSWORD) {
      auth.type = 'username_password';
      auth.identity = snowflakeUser;
      auth.key = document.getElementById('snowflake-password')?.value.trim() || '';
    } else if (authMethod === SNOWFLAKE_AUTH_METHOD_KEY_PAIR) {
      auth.type = 'key';
      auth.key = document.getElementById('snowflake-private-key')?.value.trim() || '';
      const passphrase = document.getElementById('snowflake-private-key-passphrase')?.value.trim() || '';
      if (passphrase) {
        additionalFields.private_key_passphrase = passphrase;
      }
    } else if (authMethod === SNOWFLAKE_AUTH_METHOD_OAUTH) {
      auth.type = 'key';
      auth.key = document.getElementById('snowflake-oauth-token')?.value.trim() || '';
    }

    return {
      endpoint: SNOWFLAKE_DEFAULT_ENDPOINT,
      auth,
      additionalFields,
      identityId
    };
  }

  normalizeTableauServerUrl(serverUrl = '') {
    const value = String(serverUrl || '').trim().replace(/\/+$/, '');
    if (!value) {
      return '';
    }
    if (!/^https?:\/\//i.test(value)) {
      return `https://${value}`;
    }
    return value;
  }

  getTableauIdentityAuthMethod(identity) {
    const authType = this.getIdentityAuthType(identity);
    return authType === 'username_password' ? TABLEAU_AUTH_METHOD_USERNAME_PASSWORD : TABLEAU_AUTH_METHOD_PAT;
  }

  formatTableauAuthMethod(authMethod) {
    return authMethod === TABLEAU_AUTH_METHOD_USERNAME_PASSWORD ? 'Username and Password' : 'Personal Access Token';
  }

  toggleTableauAuthFields() {
    const selectedIdentity = this.getSelectedActionIdentity('tableau');
    const selectedIdentityAuthType = this.getIdentityAuthType(selectedIdentity);
    const authMethodSelect = document.getElementById('tableau-auth-method');
    const patGroup = document.getElementById('tableau-pat-group');
    const patSecretGroup = document.getElementById('tableau-pat-secret-group');
    const usernamePasswordGroup = document.getElementById('tableau-username-password-group');

    if (authMethodSelect) {
      authMethodSelect.disabled = Boolean(selectedIdentity);
      if (selectedIdentity) {
        authMethodSelect.value = this.getTableauIdentityAuthMethod(selectedIdentity);
      }
    }

    [patGroup, patSecretGroup, usernamePasswordGroup].forEach(group => {
      if (group) {
        group.classList.add('d-none');
      }
    });

    if (selectedIdentity) {
      if (selectedIdentityAuthType === 'api_key') {
        patGroup?.classList.remove('d-none');
      }
      return;
    }

    const authMethod = authMethodSelect?.value || TABLEAU_AUTH_METHOD_PAT;
    if (authMethod === TABLEAU_AUTH_METHOD_PAT) {
      patGroup?.classList.remove('d-none');
      patSecretGroup?.classList.remove('d-none');
    } else if (authMethod === TABLEAU_AUTH_METHOD_USERNAME_PASSWORD) {
      usernamePasswordGroup?.classList.remove('d-none');
    }
  }

  populateTableauForm(plugin) {
    const additionalFields = plugin.additionalFields || plugin.additional_fields || {};
    const auth = plugin.auth || {};
    const serverUrl = this.normalizeTableauServerUrl(plugin.endpoint || additionalFields.server_url || '');

    document.getElementById('tableau-server-url').value = serverUrl;
    document.getElementById('tableau-site-content-url').value = additionalFields.site_content_url || '';
    document.getElementById('tableau-pat-name').value = auth.identity || additionalFields.pat_name || '';
    document.getElementById('tableau-page-size').value = additionalFields.page_size || 100;
    document.getElementById('tableau-max-results').value = additionalFields.max_results || 100;
    document.getElementById('tableau-timeout').value = additionalFields.timeout || 30;
    document.getElementById('tableau-use-server-version').checked = additionalFields.use_server_version !== false;

    let authMethod = additionalFields.auth_method || TABLEAU_AUTH_METHOD_PAT;
    if (auth.type === 'username_password') {
      authMethod = TABLEAU_AUTH_METHOD_USERNAME_PASSWORD;
      document.getElementById('tableau-username').value = auth.identity || '';
      document.getElementById('tableau-password').value = auth.key || '';
    } else if (auth.type === 'key') {
      document.getElementById('tableau-pat-secret').value = auth.key || '';
    }

    document.getElementById('tableau-auth-method').value = authMethod;
    this.setSelectedActionIdentity('tableau', plugin.identity_id || '');
    this.handleActionIdentityChange('tableau');
  }

  getTableauConfiguration() {
    const serverUrl = this.normalizeTableauServerUrl(document.getElementById('tableau-server-url')?.value || '');
    const selectedIdentity = this.getSelectedActionIdentity('tableau');
    const authMethod = selectedIdentity
      ? this.getTableauIdentityAuthMethod(selectedIdentity)
      : (document.getElementById('tableau-auth-method')?.value || TABLEAU_AUTH_METHOD_PAT);
    const patName = document.getElementById('tableau-pat-name')?.value.trim() || '';
    const additionalFields = {
      server_url: serverUrl,
      site_content_url: String(document.getElementById('tableau-site-content-url')?.value || '').trim().replace(/^\/+|\/+$/g, ''),
      auth_method: authMethod,
      page_size: parseInt(document.getElementById('tableau-page-size')?.value, 10) || 100,
      max_results: parseInt(document.getElementById('tableau-max-results')?.value, 10) || 100,
      timeout: parseInt(document.getElementById('tableau-timeout')?.value, 10) || 30,
      use_server_version: document.getElementById('tableau-use-server-version')?.checked !== false
    };
    const auth = {};
    let identityId = '';

    if (authMethod === TABLEAU_AUTH_METHOD_PAT && patName) {
      additionalFields.pat_name = patName;
    }

    if (selectedIdentity) {
      identityId = selectedIdentity.id || selectedIdentity.identity_id || '';
      auth.type = 'identity';
      auth.identity = identityId;
      additionalFields.identity_auth_type = this.getIdentityAuthType(selectedIdentity);
    } else if (authMethod === TABLEAU_AUTH_METHOD_USERNAME_PASSWORD) {
      auth.type = 'username_password';
      auth.identity = document.getElementById('tableau-username')?.value.trim() || '';
      auth.key = document.getElementById('tableau-password')?.value.trim() || '';
    } else {
      auth.type = 'key';
      auth.identity = patName;
      auth.key = document.getElementById('tableau-pat-secret')?.value.trim() || '';
    }

    return {
      endpoint: serverUrl,
      auth,
      additionalFields,
      identityId
    };
  }

  initializeDocumentSearchConfiguration() {
    const defaults = {
      'document-search-scope': 'all',
      'document-search-top-n': '12',
      'document-search-window-unit': 'pages',
      'document-search-window-target-length': '2 pages',
      'document-search-final-target-length': '2 pages'
    };

    Object.entries(defaults).forEach(([id, value]) => {
      const element = document.getElementById(id);
      if (element && !String(element.value || '').trim()) {
        element.value = value;
      }
    });
  }

  getDocumentSearchAdditionalFields() {
    const topNValue = parseInt(document.getElementById('document-search-top-n')?.value, 10);
    const windowSizeValue = parseInt(document.getElementById('document-search-window-size')?.value, 10);
    const windowPercentValue = parseInt(document.getElementById('document-search-window-percent')?.value, 10);
    const focusInstructions = document.getElementById('document-search-focus-instructions')?.value.trim() || '';
    const windowTargetLength = document.getElementById('document-search-window-target-length')?.value.trim() || '2 pages';
    const finalTargetLength = document.getElementById('document-search-final-target-length')?.value.trim() || '2 pages';

    const additionalFields = {
      default_doc_scope: document.getElementById('document-search-scope')?.value || 'all',
      default_top_n: !Number.isNaN(topNValue) && topNValue > 0 ? topNValue : 12,
      default_window_unit: document.getElementById('document-search-window-unit')?.value || 'pages',
      default_window_target_length: windowTargetLength,
      default_final_target_length: finalTargetLength
    };

    if (focusInstructions) {
      additionalFields.default_focus_instructions = focusInstructions;
    }
    if (!Number.isNaN(windowSizeValue) && windowSizeValue > 0) {
      additionalFields.default_window_size = windowSizeValue;
    }
    if (!Number.isNaN(windowPercentValue) && windowPercentValue > 0) {
      additionalFields.default_window_percent = windowPercentValue;
    }

    return additionalFields;
  }

  populateDocumentSearchForm(additionalFields = {}) {
    document.getElementById('document-search-scope').value = additionalFields.default_doc_scope || 'all';
    document.getElementById('document-search-top-n').value = additionalFields.default_top_n || 12;
    document.getElementById('document-search-window-unit').value = additionalFields.default_window_unit || 'pages';
    document.getElementById('document-search-window-size').value = additionalFields.default_window_size || '';
    document.getElementById('document-search-window-percent').value = additionalFields.default_window_percent || '';
    document.getElementById('document-search-focus-instructions').value = additionalFields.default_focus_instructions || '';
    document.getElementById('document-search-window-target-length').value = additionalFields.default_window_target_length || '2 pages';
    document.getElementById('document-search-final-target-length').value = additionalFields.default_final_target_length || '2 pages';
  }

  formatDocumentScope(scope) {
    const scopeMap = {
      all: 'All Accessible Content',
      personal: 'Personal Workspace',
      group: 'Group Workspaces',
      public: 'Public Workspaces'
    };

    return scopeMap[scope] || scope || '-';
  }

  formatDocumentSearchWindowing(config = {}) {
    const unit = config.default_window_unit === 'chunks' ? 'Chunks' : 'Pages';
    if (config.default_window_size) {
      return `${unit} (${config.default_window_size} per window)`;
    }
    if (config.default_window_percent) {
      return `${unit} (${config.default_window_percent}% of document)`;
    }
    return `${unit} (automatic sizing)`;
  }

  parseTextareaLines(fieldId) {
    const value = document.getElementById(fieldId)?.value || '';
    return value
      .replace(/,/g, '\n')
      .split('\n')
      .map(item => item.trim())
      .filter(Boolean);
  }

  parseJsonObjectField(fieldId, fieldName, defaultValue = {}) {
    const value = document.getElementById(fieldId)?.value.trim() || '';
    if (!value) {
      return defaultValue;
    }

    const parsed = JSON.parse(value);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error(`${fieldName} must be a JSON object.`);
    }
    return parsed;
  }

  parseJsonArrayField(fieldId, fieldName, defaultValue = []) {
    const value = document.getElementById(fieldId)?.value.trim() || '';
    if (!value) {
      return defaultValue;
    }

    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) {
      throw new Error(`${fieldName} must be a JSON array.`);
    }
    return parsed;
  }

  getIntegerFieldValue(fieldId, defaultValue) {
    const value = parseInt(document.getElementById(fieldId)?.value, 10);
    return Number.isNaN(value) ? defaultValue : value;
  }

  formatMcpTransport(transport) {
    const labels = {
      streamable_http: 'Streamable HTTP',
      sse: 'Server-Sent Events',
      websocket: 'WebSocket',
      stdio: 'Stdio'
    };
    return labels[transport] || transport || '-';
  }

  initializeMcpConfiguration() {
    const defaults = {
      'mcp-transport': 'streamable_http',
      'mcp-auth-method': 'none',
      'mcp-api-key-header-name': 'X-API-Key',
      'mcp-request-timeout': '30',
      'mcp-connect-timeout': '10',
      'mcp-sse-read-timeout': '300',
      'mcp-tool-metadata': '[]',
      'mcp-env': '{}'
    };

    Object.entries(defaults).forEach(([id, value]) => {
      const element = document.getElementById(id);
      if (element && !String(element.value || '').trim()) {
        element.value = value;
      }
    });

    this.updateMcpTransportOptions();
    this.toggleMcpTransportFields();
    this.toggleMcpAuthFields();
  }

  isAdminActionScope() {
    return window.location.pathname.includes('/admin') || this.actionIdentityScope?.scope === 'global';
  }

  updateMcpTransportOptions() {
    const transportSelect = document.getElementById('mcp-transport');
    if (!transportSelect) {
      return;
    }

    const stdioOption = Array.from(transportSelect.options).find(option => option.value === 'stdio');
    if (!stdioOption) {
      return;
    }

    const allowStdio = this.isAdminActionScope();
    stdioOption.disabled = !allowStdio;
    if (!allowStdio && transportSelect.value === 'stdio') {
      transportSelect.value = 'streamable_http';
      this.setMcpDiscoveryStatus('Stdio transport is only available for admin-managed global actions.', 'warning');
    }
  }

  toggleMcpTransportFields() {
    this.updateMcpTransportOptions();
    const transport = document.getElementById('mcp-transport')?.value || 'streamable_http';
    const endpointGroup = document.getElementById('mcp-endpoint-group');
    const stdioGroup = document.getElementById('mcp-stdio-group');
    const endpointInput = document.getElementById('mcp-endpoint');

    const isStdio = transport === 'stdio';
    if (endpointGroup) {
      endpointGroup.classList.toggle('d-none', isStdio);
    }
    if (stdioGroup) {
      stdioGroup.classList.toggle('d-none', !isStdio);
    }
    if (!isStdio && endpointInput && !endpointInput.value.trim()) {
      endpointInput.placeholder = transport === 'websocket' ? 'wss://example.com/mcp' : 'https://example.com/mcp';
    }
  }

  toggleMcpAuthFields() {
    const authMethod = document.getElementById('mcp-auth-method')?.value || 'none';
    const selectedIdentity = this.getSelectedActionIdentity('mcp');
    const groups = {
      bearer: document.getElementById('mcp-bearer-token-group'),
      apiKey: document.getElementById('mcp-api-key-group'),
      basic: document.getElementById('mcp-basic-auth-group')
    };

    Object.values(groups).forEach(group => {
      if (group) {
        group.classList.add('d-none');
      }
    });

    if (selectedIdentity) {
      return;
    }

    if (authMethod === 'bearer' && groups.bearer) {
      groups.bearer.classList.remove('d-none');
    } else if (authMethod === 'api_key' && groups.apiKey) {
      groups.apiKey.classList.remove('d-none');
    } else if (authMethod === 'basic' && groups.basic) {
      groups.basic.classList.remove('d-none');
    }
  }

  populateMcpForm(plugin) {
    const additionalFields = plugin.additionalFields || plugin.additional_fields || {};
    const auth = plugin.auth || {};
    const transport = additionalFields.transport || 'streamable_http';

    document.getElementById('mcp-transport').value = transport;
    document.getElementById('mcp-endpoint').value = transport === 'stdio' ? '' : (plugin.endpoint || '');
    document.getElementById('mcp-command').value = additionalFields.command || '';
    document.getElementById('mcp-args').value = Array.isArray(additionalFields.args) ? additionalFields.args.join('\n') : '';
    document.getElementById('mcp-env').value = JSON.stringify(additionalFields.env || {}, null, 2);
    document.getElementById('mcp-load-tools').checked = additionalFields.load_tools !== false;
    document.getElementById('mcp-load-prompts').checked = Boolean(additionalFields.load_prompts);
    document.getElementById('mcp-request-timeout').value = additionalFields.request_timeout || 30;
    document.getElementById('mcp-connect-timeout').value = additionalFields.connect_timeout || 10;
    document.getElementById('mcp-sse-read-timeout').value = additionalFields.sse_read_timeout || 300;
    document.getElementById('mcp-tool-names').value = Array.isArray(additionalFields.allowed_tool_names)
      ? additionalFields.allowed_tool_names.join('\n')
      : '';
    document.getElementById('mcp-tool-metadata').value = JSON.stringify(additionalFields.mcp_tools || [], null, 2);

    let authMethod = additionalFields.auth_method || 'none';
    if (auth.type === 'key' && !additionalFields.auth_method) {
      authMethod = 'bearer';
    }
    document.getElementById('mcp-auth-method').value = authMethod === 'identity' ? 'none' : authMethod;

    if (authMethod === 'bearer') {
      document.getElementById('mcp-bearer-token').value = auth.key || '';
    } else if (authMethod === 'api_key') {
      document.getElementById('mcp-api-key-header-name').value = additionalFields.api_key_header_name || 'X-API-Key';
      document.getElementById('mcp-api-key-value').value = auth.key || '';
    } else if (authMethod === 'basic') {
      document.getElementById('mcp-basic-username').value = auth.identity || '';
      document.getElementById('mcp-basic-password').value = auth.key || '';
    }

    this.setSelectedActionIdentity('mcp', plugin.identity_id || '');
    this.handleActionIdentityChange('mcp');
    this.toggleMcpTransportFields();
    this.toggleMcpAuthFields();
  }

  getMcpConfiguration() {
    const transport = document.getElementById('mcp-transport')?.value || 'streamable_http';
    const selectedIdentity = this.getSelectedActionIdentity('mcp');
    const authMethod = selectedIdentity ? 'identity' : (document.getElementById('mcp-auth-method')?.value || 'none');
    const additionalFields = {
      transport,
      auth_method: authMethod,
      load_tools: document.getElementById('mcp-load-tools')?.checked !== false,
      load_prompts: Boolean(document.getElementById('mcp-load-prompts')?.checked),
      request_timeout: this.getIntegerFieldValue('mcp-request-timeout', 30),
      connect_timeout: this.getIntegerFieldValue('mcp-connect-timeout', 10),
      sse_read_timeout: this.getIntegerFieldValue('mcp-sse-read-timeout', 300),
      allowed_tool_names: this.parseTextareaLines('mcp-tool-names'),
      mcp_tools: this.parseJsonArrayField('mcp-tool-metadata', 'Discovered Tool Metadata', [])
    };

    let endpoint = document.getElementById('mcp-endpoint')?.value.trim() || '';
    if (transport === 'stdio') {
      endpoint = MCP_STDIO_ENDPOINT;
      additionalFields.command = document.getElementById('mcp-command')?.value.trim() || '';
      additionalFields.args = this.parseTextareaLines('mcp-args');
      additionalFields.env = this.parseJsonObjectField('mcp-env', 'Environment', {});
    }

    const auth = {};
    let identityId = '';
    if (selectedIdentity) {
      identityId = selectedIdentity.id || selectedIdentity.identity_id || '';
      auth.type = 'identity';
      auth.identity = identityId;
      additionalFields.identity_auth_type = this.getIdentityAuthType(selectedIdentity);
    } else if (authMethod === 'none') {
      auth.type = 'NoAuth';
    } else if (authMethod === 'bearer') {
      auth.type = 'key';
      auth.key = document.getElementById('mcp-bearer-token')?.value.trim() || '';
    } else if (authMethod === 'api_key') {
      auth.type = 'key';
      auth.key = document.getElementById('mcp-api-key-value')?.value.trim() || '';
      additionalFields.api_key_header_name = document.getElementById('mcp-api-key-header-name')?.value.trim() || 'X-API-Key';
    } else if (authMethod === 'basic') {
      auth.type = 'key';
      auth.identity = document.getElementById('mcp-basic-username')?.value.trim() || '';
      auth.key = document.getElementById('mcp-basic-password')?.value.trim() || '';
    }

    return {
      endpoint,
      auth,
      additionalFields,
      identityId
    };
  }

  setMcpDiscoveryStatus(message, variant = 'muted') {
    const status = document.getElementById('mcp-discover-status');
    if (!status) {
      return;
    }
    status.textContent = message || '';
    status.className = `small text-${variant}`;
  }

  async discoverMcpTools() {
    const button = document.getElementById('mcp-discover-tools-btn');
    const spinner = document.getElementById('mcp-discover-spinner');
    if (!button) {
      return;
    }

    try {
      const mcpConfig = this.getMcpConfiguration();
      const payload = {
        name: document.getElementById('plugin-name')?.value.trim() || 'mcp_discovery',
        displayName: document.getElementById('plugin-display-name')?.value.trim() || 'MCP Discovery',
        type: MCP_PLUGIN_TYPE,
        description: document.getElementById('plugin-description')?.value.trim() || 'MCP discovery request',
        endpoint: mcpConfig.endpoint,
        auth: mcpConfig.auth,
        metadata: {},
        additionalFields: mcpConfig.additionalFields,
        action_scope: this.actionIdentityScope?.scope || 'personal'
      };

      if (mcpConfig.identityId) {
        payload.identity_id = mcpConfig.identityId;
      }
      if (this.originalPlugin) {
        payload.plugin_context = {
          scope: this.originalPlugin.scope || this.actionIdentityScope?.scope || 'personal',
          id: this.originalPlugin.id || '',
          name: this.originalPlugin.name || ''
        };
      }

      button.disabled = true;
      if (spinner) {
        spinner.classList.remove('d-none');
      }
      this.setMcpDiscoveryStatus('Discovering tools...', 'muted');

      const response = await fetch('/api/plugins/mcp/discover', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      if (!response.ok || result.success === false) {
        const message = result.error || (Array.isArray(result.errors) ? result.errors.join('; ') : 'Tool discovery failed.');
        throw new Error(message);
      }

      const tools = Array.isArray(result.tools) ? result.tools : [];
      document.getElementById('mcp-tool-metadata').value = JSON.stringify(tools, null, 2);
      this.setMcpDiscoveryStatus(`Discovered ${tools.length} tool${tools.length === 1 ? '' : 's'}.`, 'success');
    } catch (error) {
      this.setMcpDiscoveryStatus(error.message || 'Tool discovery failed.', 'danger');
    } finally {
      button.disabled = false;
      if (spinner) {
        spinner.classList.add('d-none');
      }
    }
  }

  isStructuredConfigType(type = this.selectedType) {
    return this.isSqlType(type) || this.isCosmosType(type) || this.isDocumentSearchType(type) || this.isBlobStorageType(type) || this.isDatabricksType(type) || this.isSnowflakeType(type) || this.isTableauType(type) || this.isMcpType(type) || this.isSimpleChatType(type) || this.isMsGraphType(type) || this.isAzureMapsType(type) || this.isChartType(type);
  }

  showConfigSectionForType() {
    const sections = {
      openapi: document.getElementById('openapi-config-section'),
      generic: document.getElementById('generic-config-section'),
      sql: document.getElementById('sql-config-section'),
      cosmos: document.getElementById('cosmos-config-section'),
      documentSearch: document.getElementById('document-search-config-section'),
      blobStorage: document.getElementById('blob-storage-config-section'),
      databricks: document.getElementById('databricks-config-section'),
      snowflake: document.getElementById('snowflake-config-section'),
      tableau: document.getElementById('tableau-config-section'),
      simpleChat: document.getElementById('simplechat-config-section'),
      msGraph: document.getElementById('msgraph-config-section'),
      mcp: document.getElementById('mcp-config-section'),
      azureMaps: document.getElementById('azure-maps-config-section'),
      chart: document.getElementById('chart-config-section')
    };

    const showOnly = (sectionKey) => {
      Object.entries(sections).forEach(([key, section]) => {
        if (!section) {
          return;
        }
        section.classList.toggle('d-none', key !== sectionKey);
      });
    };

    if (this.isOpenApiType()) {
      showOnly('openapi');
    } else if (this.isSqlType()) {
      showOnly('sql');
      this.initializeSqlConfiguration();
    } else if (this.isCosmosType()) {
      showOnly('cosmos');
      this.initializeCosmosConfiguration();
    } else if (this.isDocumentSearchType()) {
      showOnly('documentSearch');
      this.initializeDocumentSearchConfiguration();
    } else if (this.isBlobStorageType()) {
      showOnly('blobStorage');
      this.renderBlobStorageConfiguration();
    } else if (this.isDatabricksType()) {
      showOnly('databricks');
      this.toggleDatabricksAuthFields();
    } else if (this.isSnowflakeType()) {
      showOnly('snowflake');
      this.toggleSnowflakeAuthFields();
    } else if (this.isTableauType()) {
      showOnly('tableau');
      this.toggleTableauAuthFields();
    } else if (this.isMcpType()) {
      showOnly('mcp');
      this.initializeMcpConfiguration();
    } else if (this.isSimpleChatType()) {
      showOnly('simpleChat');
      this.renderSimpleChatConfiguration();
    } else if (this.isMsGraphType()) {
      showOnly('msGraph');
      this.renderMsGraphConfiguration();
      this.updateMsGraphMailDelayVisibility();
      this.updateMsGraphCalendarDelayVisibility();
    } else if (this.isAzureMapsType()) {
      showOnly('azureMaps');
    } else if (this.isChartType()) {
      showOnly('chart');
      this.renderChartConfiguration();
    } else {
      showOnly('generic');
    }
  }

  showStep(stepNumber) {
    // Hide all steps
    document.querySelectorAll('.plugin-step').forEach(step => {
      step.classList.add('d-none');
    });

    // Show current step
    const currentStepEl = document.getElementById(`plugin-step-${stepNumber}`);
    if (currentStepEl) {
      currentStepEl.classList.remove('d-none');
    }

    if (stepNumber === 2) {

    }

    // Update step 3 title based on plugin type
    if (stepNumber === 3) {
      const titleEl = document.getElementById('step-3-title');
      if (titleEl) {
        const isOpenApiType = this.isOpenApiType();
        const isSqlType = this.isSqlType();
        const isCosmosType = this.isCosmosType();
        const isDocumentSearchType = this.isDocumentSearchType();
        const isBlobStorageType = this.isBlobStorageType();
        const isDatabricksType = this.isDatabricksType();
        const isSnowflakeType = this.isSnowflakeType();
        const isTableauType = this.isTableauType();
        const isMcpType = this.isMcpType();
        const isAzureMapsType = this.isAzureMapsType();
        const isChartType = this.isChartType();

        if (isOpenApiType) {
          titleEl.textContent = 'API Configuration';
        } else if (isSqlType) {
          titleEl.textContent = 'Database Configuration';
        } else if (isCosmosType) {
          titleEl.textContent = 'Cosmos Configuration';
        } else if (isDocumentSearchType) {
          titleEl.textContent = 'Document Search Configuration';
        } else if (isBlobStorageType) {
          titleEl.textContent = 'Blob Storage Configuration';
        } else if (isDatabricksType) {
          titleEl.textContent = 'Databricks Configuration';
        } else if (isSnowflakeType) {
          titleEl.textContent = 'Snowflake Configuration';
        } else if (isTableauType) {
          titleEl.textContent = 'Tableau Configuration';
        } else if (isMcpType) {
          titleEl.textContent = 'MCP Server Configuration';
        } else if (this.isSimpleChatType()) {
          titleEl.textContent = 'SimpleChat Configuration';
        } else if (this.isMsGraphType()) {
          titleEl.textContent = 'Microsoft Graph Configuration';
        } else if (isAzureMapsType) {
          titleEl.textContent = 'Azure Maps Configuration';
        } else if (isChartType) {
          titleEl.textContent = 'Chart Configuration';
        } else {
          titleEl.textContent = 'Configuration';
        }
      }
    }

    if (stepNumber === 4) {
      const isStructuredConfigType = this.isStructuredConfigType();
      const additionalFieldsDiv = document.getElementById('plugin-additional-fields-div');

      // For SQL and Cosmos types, hide additional fields entirely since Step 3 covers config.
      if (isStructuredConfigType && additionalFieldsDiv) {
        additionalFieldsDiv.innerHTML = '';
        additionalFieldsDiv.classList.add('d-none');
        this.lastAdditionalFieldsType = this.selectedType;
      } else {
        // Load additional settings schema for selected type
        let options = {forceReload: true};
        this.getAdditionalSettingsSchema(this.selectedType, options);
        if (additionalFieldsDiv) {
          // Only clear and rebuild if type changes
          if (this.selectedType !== this.lastAdditionalFieldsType) {
            additionalFieldsDiv.innerHTML = '';
            additionalFieldsDiv.classList.remove('d-none');
            if (this.selectedType) {
              this.getAdditionalSettingsSchema(this.selectedType)
                .then(schema => {
                  if (schema) {
                    this.buildAdditionalFieldsUI(schema, additionalFieldsDiv);
                    try {
                      if (this.isEditMode && this.originalPlugin && this.originalPlugin.additionalFields) {
                        this.populateDynamicAdditionalFields(this.originalPlugin.additionalFields);
                      }
                    } catch (error) {
                      console.error('Error populating dynamic additional fields:', error);
                    }
                  } else {
                    console.log('No additional settings schema found');
                    additionalFieldsDiv.classList.add('d-none');
                  }
                })
                .catch(error => {
                  console.error(`Error fetching additional settings schema for type: ${this.selectedType} -- ${error}`);
                  additionalFieldsDiv.classList.add('d-none');
                });
            } else {
              console.warn('No plugin type selected');
              additionalFieldsDiv.classList.add('d-none');
            }
            this.lastAdditionalFieldsType = this.selectedType;
          }
          // Otherwise, preserve user data and do not redraw
        }
      }

      if (!this.isEditMode) {
        const typeField = document.getElementById('plugin-type');
        const selectedType = typeField && typeField.value ? typeField.value : null;
        if (selectedType) {
          // Dynamically import fetchAndMergePluginSettings from plugin_common.js
          import('./plugin_common.js').then(module => {
            module.fetchAndMergePluginSettings(selectedType, {}).then(merged => {
              document.getElementById('plugin-metadata').value = merged.metadata ? JSON.stringify(merged.metadata, null, 2) : '{}';
              //document.getElementById('plugin-additional-fields').value = merged.additionalFields ? JSON.stringify(merged.additionalFields, null, 2) : '{}';
            });
          });
        } else {
          // Fallback to empty objects if no type selected
          document.getElementById('plugin-metadata').value = '{}';
          //document.getElementById('plugin-additional-fields').value = '{}';
        }
      }
    }
  }

  updateStepIndicator() {
    // Scope to the plugin modal specifically
    const modal = document.getElementById('plugin-modal');
    if (!modal) {
      console.warn('Plugin modal not found');
      return;
    }

    const indicators = modal.querySelectorAll('.step-indicator');
    console.log('Updating step indicator. Current step:', this.currentStep, 'Found indicators:', indicators.length);

    indicators.forEach((indicator, index) => {
      const stepNum = index + 1;
      const circle = indicator.querySelector('.step-circle');

      if (!circle) {
        console.warn('No step-circle found for indicator', index);
        return;
      }

      // Reset classes
      indicator.classList.remove('active', 'completed');
      circle.classList.remove('active', 'completed');

      if (stepNum < this.currentStep) {
        indicator.classList.add('completed');
        circle.classList.add('completed');
        console.log('Step', stepNum, 'marked as completed');
      } else if (stepNum === this.currentStep) {
        indicator.classList.add('active');
        circle.classList.add('active');
        console.log('Step', stepNum, 'marked as active');
      }
    });
  }

  updateNavigationButtons() {
    const nextBtn = document.getElementById('plugin-modal-next');
    const prevBtn = document.getElementById('plugin-modal-prev');
    const skipBtn = document.getElementById('plugin-modal-skip');
    const saveBtn = document.getElementById('save-plugin-btn');

    // Previous button
    if (this.currentStep === 1) {
      prevBtn.classList.add('d-none');
    } else {
      prevBtn.classList.remove('d-none');
    }

    // Next/Save button
    if (this.currentStep === this.maxSteps) {
      nextBtn.classList.add('d-none');
      saveBtn.classList.remove('d-none');
    } else {
      nextBtn.classList.remove('d-none');
      saveBtn.classList.add('d-none');
    }

    // Skip button (show on steps 2 and 3, hide on 1 and 4)
    if (this.currentStep === 2 || this.currentStep === 3) {
      skipBtn.classList.remove('d-none');
    } else {
      skipBtn.classList.add('d-none');
    }
  }

  validateCurrentStep() {
    const errorDiv = document.getElementById('plugin-modal-error');
    errorDiv.classList.add('d-none');

    switch (this.currentStep) {
      case 1:
        if (!this.selectedType) {
          this.showError('Please select an action type.');
          return false;
        }
        break;

      case 2:
        const displayName = document.getElementById('plugin-display-name').value.trim();
        if (!displayName) {
          this.showError('Display name is required.');
          return false;
        }

        // Auto-generate action name from display name
        const actionName = this.generateActionName(displayName);
        document.getElementById('plugin-name').value = actionName;

        if (!/^[^\s]+$/.test(actionName)) {
          this.showError('Generated action name cannot contain spaces. Please use a simpler display name.');
          return false;
        }
        break;

      case 3:
        // Validate based on which config section is visible
        const openApiSection = document.getElementById('openapi-config-section');
        const sqlSection = document.getElementById('sql-config-section');
        const cosmosSection = document.getElementById('cosmos-config-section');
        const documentSearchSection = document.getElementById('document-search-config-section');
        const blobStorageSection = document.getElementById('blob-storage-config-section');
        const databricksSection = document.getElementById('databricks-config-section');
        const snowflakeSection = document.getElementById('snowflake-config-section');
        const tableauSection = document.getElementById('tableau-config-section');
        const mcpSection = document.getElementById('mcp-config-section');
        const simpleChatSection = document.getElementById('simplechat-config-section');
        const msGraphSection = document.getElementById('msgraph-config-section');
        const azureMapsSection = document.getElementById('azure-maps-config-section');
        const chartSection = document.getElementById('chart-config-section');
        const isOpenApiVisible = !openApiSection.classList.contains('d-none');
        const isSqlVisible = !sqlSection.classList.contains('d-none');
        const isCosmosVisible = !cosmosSection.classList.contains('d-none');
        const isDocumentSearchVisible = !documentSearchSection.classList.contains('d-none');
        const isBlobStorageVisible = !blobStorageSection.classList.contains('d-none');
        const isDatabricksVisible = !databricksSection.classList.contains('d-none');
        const isSnowflakeVisible = !snowflakeSection.classList.contains('d-none');
        const isTableauVisible = !tableauSection.classList.contains('d-none');
        const isMcpVisible = !mcpSection.classList.contains('d-none');
        const isSimpleChatVisible = !simpleChatSection.classList.contains('d-none');
        const isMsGraphVisible = !msGraphSection.classList.contains('d-none');
        const isAzureMapsVisible = !azureMapsSection.classList.contains('d-none');
        const isChartVisible = !chartSection.classList.contains('d-none');

        if (isOpenApiVisible) {
          // Validate OpenAPI fields
          const fileInput = document.getElementById('plugin-openapi-file');
          const endpoint = document.getElementById('plugin-endpoint').value.trim();

          // Validate OpenAPI specification - allow either uploaded file or existing spec content
          const hasUploadedFile = fileInput.files && fileInput.files.length > 0;
          const hasExistingSpec = fileInput.dataset.fileId && fileInput.dataset.specContent;

          if (!hasUploadedFile && !hasExistingSpec) {
            this.showError('OpenAPI specification file is required.');
            return false;
          }

          if (!endpoint) {
            this.showError('Base URL is required.');
            return false;
          }

          // Validate auth fields for OpenAPI
          const authType = document.getElementById('plugin-auth-type').value;
          if (authType === 'api_key') {
            const keyName = document.getElementById('plugin-auth-api-key-name').value.trim();
            const keyValue = document.getElementById('plugin-auth-api-key-value').value.trim();
            if (!keyName || !keyValue) {
              this.showError('API key name and value are required.');
              return false;
            }
          } else if (authType === 'bearer') {
            const token = document.getElementById('plugin-auth-bearer-token').value.trim();
            if (!token) {
              this.showError('Bearer token is required.');
              return false;
            }
          } else if (authType === 'basic') {
            const username = document.getElementById('plugin-auth-basic-username').value.trim();
            const password = document.getElementById('plugin-auth-basic-password').value.trim();
            if (!username || !password) {
              this.showError('Username and password are required for basic auth.');
              return false;
            }
          } else if (authType === 'oauth2') {
            const token = document.getElementById('plugin-auth-oauth2-token').value.trim();
            if (!token) {
              this.showError('OAuth2 access token is required.');
              return false;
            }
          }
        } else if (isSqlVisible) {
          // Validate SQL configuration
          const selectedDbType = document.querySelector('input[name="sql-database-type"]:checked');
          if (!selectedDbType) {
            this.showError('Database type is required.');
            return false;
          }

          // Plugin type should be auto-selected based on initial choice, but check as fallback
          const selectedPluginType = document.querySelector('input[name="sql-plugin-type"]:checked');
          if (!selectedPluginType) {
            // Auto-select based on selectedType if not already selected
            if (this.selectedType && this.selectedType.toLowerCase() === 'sql_schema') {
              document.getElementById('sql-plugin-schema').checked = true;
            } else if (this.selectedType && this.selectedType.toLowerCase() === 'sql_query') {
              document.getElementById('sql-plugin-query').checked = true;
            } else {
              this.showError('Plugin type is required.');
              return false;
            }
          }

          const selectedConnectionMethod = document.querySelector('input[name="sql-connection-method"]:checked');
          if (!selectedConnectionMethod) {
            this.showError('Connection method is required.');
            return false;
          }

          // Validate connection method specific fields
          if (selectedConnectionMethod.value === 'connection-string') {
            // No additional validation needed for connection string method
          } else if (selectedConnectionMethod.value === 'individual-parameters') {
            const server = document.getElementById('sql-server').value.trim();
            const database = document.getElementById('sql-database').value.trim();

            if (!server) {
              this.showError('Server is required.');
              return false;
            }

            if (!database) {
              this.showError('Database is required.');
              return false;
            }

            // Validate authentication for individual parameters
            const sqlAuthType = document.getElementById('sql-auth-type').value;
            if (sqlAuthType === 'username-password') {
              const username = document.getElementById('sql-username').value.trim();
              const password = document.getElementById('sql-password').value.trim();

              if (!username) {
                this.showError('Username is required.');
                return false;
              }

              if (!password) {
                this.showError('Password is required.');
                return false;
              }
            }
          }
        } else if (isCosmosVisible) {
          const endpoint = document.getElementById('cosmos-endpoint').value.trim();
          const databaseName = document.getElementById('cosmos-database-name').value.trim();
          const containerName = document.getElementById('cosmos-container-name').value.trim();
          const partitionKeyPath = document.getElementById('cosmos-partition-key-path').value.trim();
          const authType = document.getElementById('cosmos-auth-type').value;
          const authKey = document.getElementById('cosmos-auth-key').value.trim();
          const maxItems = parseInt(document.getElementById('cosmos-max-items').value, 10);
          const timeout = parseInt(document.getElementById('cosmos-timeout').value, 10);

          if (!endpoint) {
            this.showError('Cosmos DB account endpoint is required.');
            return false;
          }
          if (!databaseName) {
            this.showError('Cosmos DB database name is required.');
            return false;
          }
          if (!containerName) {
            this.showError('Cosmos DB container name is required.');
            return false;
          }
          if (!partitionKeyPath || !partitionKeyPath.startsWith('/')) {
            this.showError('Partition key path is required and must start with /.');
            return false;
          }
          if (authType === 'key' && !authKey) {
            this.showError('Cosmos DB account key is required when using account key authentication.');
            return false;
          }
          if (Number.isNaN(maxItems) || maxItems < 1 || maxItems > 1000) {
            this.showError('Max items must be between 1 and 1000.');
            return false;
          }
          if (Number.isNaN(timeout) || timeout < 1 || timeout > 120) {
            this.showError('Timeout must be between 1 and 120 seconds.');
            return false;
          }
        } else if (isBlobStorageVisible) {
          const connectionString = document.getElementById('blob-storage-connection-string').value.trim();
          const containerName = document.getElementById('blob-storage-container-name').value.trim();
          const capabilityValues = Object.values(this.getSelectedBlobStorageCapabilities());
          const readTypeValues = Object.values(this.getSelectedBlobStorageReadFileTypes());
          const uploadTypeValues = Object.values(this.getSelectedBlobStorageUploadFileTypes());

          if (!connectionString) {
            this.showError('Blob storage connection string is required.');
            return false;
          }
          if (!containerName) {
            this.showError('Blob storage container name is required.');
            return false;
          }
          if (!capabilityValues.some(Boolean)) {
            this.showError('Enable at least one blob storage capability before continuing.');
            return false;
          }
          if (this.getSelectedBlobStorageCapabilities().read_file_content && !readTypeValues.some(Boolean)) {
            this.showError('Enable at least one supported file type for blob reads before continuing.');
            return false;
          }
          if (this.getSelectedBlobStorageCapabilities().upload_file_to_container && !uploadTypeValues.some(Boolean)) {
            this.showError('Enable at least one supported file type for blob uploads before continuing.');
            return false;
          }
        } else if (isDatabricksVisible) {
          const workspaceUrl = this.normalizeDatabricksWorkspaceUrl(document.getElementById('databricks-workspace-url').value);
          const warehouseId = document.getElementById('databricks-warehouse-id').value.trim();
          const authMethod = document.getElementById('databricks-auth-method').value;
          const selectedIdentity = this.getSelectedActionIdentity('databricks');
          const maxRows = parseInt(document.getElementById('databricks-max-rows').value, 10);
          const timeout = parseInt(document.getElementById('databricks-timeout').value, 10);
          const waitTimeout = parseInt(document.getElementById('databricks-wait-timeout').value, 10);

          if (!workspaceUrl || !workspaceUrl.startsWith('https://')) {
            this.showError('Databricks workspace URL must be an HTTPS URL.');
            return false;
          }
          if (!warehouseId) {
            this.showError('Databricks SQL Warehouse ID is required.');
            return false;
          }
          if (!['pat', 'bearer', 'service_principal', 'managed_identity'].includes(authMethod)) {
            this.showError('Select a supported Databricks authentication method.');
            return false;
          }
          if (!selectedIdentity && (authMethod === 'pat' || authMethod === 'bearer') && !document.getElementById('databricks-token').value.trim()) {
            this.showError('Databricks token is required for token authentication.');
            return false;
          }
          if (!selectedIdentity && authMethod === 'service_principal') {
            if (!document.getElementById('databricks-client-id').value.trim() || !document.getElementById('databricks-client-secret').value.trim() || !document.getElementById('databricks-tenant-id').value.trim()) {
              this.showError('Client ID, client secret, and tenant ID are required for Databricks service principal authentication.');
              return false;
            }
          }
          if (Number.isNaN(maxRows) || maxRows < 1 || maxRows > 10000) {
            this.showError('Databricks max rows must be between 1 and 10000.');
            return false;
          }
          if (Number.isNaN(timeout) || timeout < 1 || timeout > 300) {
            this.showError('Databricks timeout must be between 1 and 300 seconds.');
            return false;
          }
          if (Number.isNaN(waitTimeout) || waitTimeout < 1 || waitTimeout > 50) {
            this.showError('Databricks wait timeout must be between 1 and 50 seconds.');
            return false;
          }
        } else if (isSnowflakeVisible) {
          const account = this.normalizeSnowflakeAccount(document.getElementById('snowflake-account').value);
          const snowflakeUser = document.getElementById('snowflake-user').value.trim();
          const warehouse = document.getElementById('snowflake-warehouse').value.trim();
          const authMethod = document.getElementById('snowflake-auth-method').value;
          const selectedIdentity = this.getSelectedActionIdentity('snowflake');
          const maxRows = parseInt(document.getElementById('snowflake-max-rows').value, 10);
          const timeout = parseInt(document.getElementById('snowflake-timeout').value, 10);
          const loginTimeout = parseInt(document.getElementById('snowflake-login-timeout').value, 10);

          if (!account) {
            this.showError('Snowflake account identifier is required.');
            return false;
          }
          if (!warehouse) {
            this.showError('Snowflake warehouse is required.');
            return false;
          }
          if (!snowflakeUser && (!selectedIdentity || this.getIdentityAuthType(selectedIdentity) !== 'username_password')) {
            this.showError('Snowflake user is required for key-pair and OAuth authentication.');
            return false;
          }
          if (![SNOWFLAKE_AUTH_METHOD_PASSWORD, SNOWFLAKE_AUTH_METHOD_KEY_PAIR, SNOWFLAKE_AUTH_METHOD_OAUTH].includes(authMethod)) {
            this.showError('Select a supported Snowflake authentication method.');
            return false;
          }
          if (!selectedIdentity && authMethod === SNOWFLAKE_AUTH_METHOD_PASSWORD && !document.getElementById('snowflake-password').value.trim()) {
            this.showError('Snowflake password is required for password authentication.');
            return false;
          }
          if (!selectedIdentity && authMethod === SNOWFLAKE_AUTH_METHOD_KEY_PAIR && !document.getElementById('snowflake-private-key').value.trim()) {
            this.showError('Snowflake private key is required for key-pair authentication.');
            return false;
          }
          if (!selectedIdentity && authMethod === SNOWFLAKE_AUTH_METHOD_OAUTH && !document.getElementById('snowflake-oauth-token').value.trim()) {
            this.showError('Snowflake OAuth token is required for OAuth authentication.');
            return false;
          }
          if (Number.isNaN(maxRows) || maxRows < 1 || maxRows > 10000) {
            this.showError('Snowflake max rows must be between 1 and 10000.');
            return false;
          }
          if (Number.isNaN(timeout) || timeout < 1 || timeout > 300) {
            this.showError('Snowflake timeout must be between 1 and 300 seconds.');
            return false;
          }
          if (Number.isNaN(loginTimeout) || loginTimeout < 1 || loginTimeout > 300) {
            this.showError('Snowflake login timeout must be between 1 and 300 seconds.');
            return false;
          }
        } else if (isTableauVisible) {
          const serverUrl = this.normalizeTableauServerUrl(document.getElementById('tableau-server-url').value);
          const selectedIdentity = this.getSelectedActionIdentity('tableau');
          const selectedIdentityAuthType = this.getIdentityAuthType(selectedIdentity);
          const authMethod = document.getElementById('tableau-auth-method').value;
          const patName = document.getElementById('tableau-pat-name').value.trim();
          const patSecret = document.getElementById('tableau-pat-secret').value.trim();
          const username = document.getElementById('tableau-username').value.trim();
          const password = document.getElementById('tableau-password').value.trim();
          const pageSize = parseInt(document.getElementById('tableau-page-size').value, 10);
          const maxResults = parseInt(document.getElementById('tableau-max-results').value, 10);
          const timeout = parseInt(document.getElementById('tableau-timeout').value, 10);

          if (!serverUrl || !serverUrl.startsWith('https://')) {
            this.showError('Tableau Server URL must be an HTTPS URL.');
            return false;
          }
          if (![TABLEAU_AUTH_METHOD_PAT, TABLEAU_AUTH_METHOD_USERNAME_PASSWORD].includes(authMethod)) {
            this.showError('Select a supported Tableau authentication method.');
            return false;
          }
          if (selectedIdentity && selectedIdentityAuthType === 'api_key' && !patName) {
            this.showError('Tableau PAT name is required when using an API key reusable identity.');
            return false;
          }
          if (!selectedIdentity && authMethod === TABLEAU_AUTH_METHOD_PAT && (!patName || !patSecret)) {
            this.showError('Tableau PAT name and secret are required for personal access token authentication.');
            return false;
          }
          if (!selectedIdentity && authMethod === TABLEAU_AUTH_METHOD_USERNAME_PASSWORD && (!username || !password)) {
            this.showError('Tableau username and password are required for username/password authentication.');
            return false;
          }
          if (Number.isNaN(pageSize) || pageSize < 1 || pageSize > 1000) {
            this.showError('Tableau page size must be between 1 and 1000.');
            return false;
          }
          if (Number.isNaN(maxResults) || maxResults < 1 || maxResults > 1000) {
            this.showError('Tableau max results must be between 1 and 1000.');
            return false;
          }
          if (Number.isNaN(timeout) || timeout < 1 || timeout > 300) {
            this.showError('Tableau timeout must be between 1 and 300 seconds.');
            return false;
          }
        } else if (isMcpVisible) {
          const transport = document.getElementById('mcp-transport').value;
          const endpoint = document.getElementById('mcp-endpoint').value.trim();
          const command = document.getElementById('mcp-command').value.trim();
          const authMethod = document.getElementById('mcp-auth-method').value;
          const selectedIdentity = this.getSelectedActionIdentity('mcp');
          const requestTimeout = parseInt(document.getElementById('mcp-request-timeout').value, 10);
          const connectTimeout = parseInt(document.getElementById('mcp-connect-timeout').value, 10);
          const sseReadTimeout = parseInt(document.getElementById('mcp-sse-read-timeout').value, 10);

          if (!['streamable_http', 'sse', 'websocket', 'stdio'].includes(transport)) {
            this.showError('Select a supported MCP transport.');
            return false;
          }
          if (transport === 'stdio') {
            if (!command) {
              this.showError('Command is required for MCP stdio transport.');
              return false;
            }
            try {
              this.parseJsonObjectField('mcp-env', 'Environment', {});
            } catch (error) {
              this.showError(error.message);
              return false;
            }
          } else if (!endpoint) {
            this.showError('Endpoint is required for MCP remote transports.');
            return false;
          }

          if (!document.getElementById('mcp-load-tools').checked && !document.getElementById('mcp-load-prompts').checked) {
            this.showError('Enable tools or prompts before continuing.');
            return false;
          }

          if (!selectedIdentity && authMethod === 'bearer' && !document.getElementById('mcp-bearer-token').value.trim()) {
            this.showError('Bearer token is required for MCP bearer authentication.');
            return false;
          }
          if (!selectedIdentity && authMethod === 'api_key') {
            if (!document.getElementById('mcp-api-key-header-name').value.trim() || !document.getElementById('mcp-api-key-value').value.trim()) {
              this.showError('API key header name and value are required for MCP API key authentication.');
              return false;
            }
          }
          if (!selectedIdentity && authMethod === 'basic') {
            if (!document.getElementById('mcp-basic-username').value.trim() || !document.getElementById('mcp-basic-password').value.trim()) {
              this.showError('Username and password are required for MCP basic authentication.');
              return false;
            }
          }
          if ([requestTimeout, connectTimeout, sseReadTimeout].some(value => Number.isNaN(value) || value < 1 || value > 300)) {
            this.showError('MCP timeout values must be between 1 and 300 seconds.');
            return false;
          }
          try {
            this.parseJsonArrayField('mcp-tool-metadata', 'Discovered Tool Metadata', []);
          } catch (error) {
            this.showError(error.message);
            return false;
          }
        } else if (isSimpleChatVisible) {
          const capabilityValues = Object.values(this.getSelectedSimpleChatCapabilities());
          if (!capabilityValues.some(Boolean)) {
            this.showError('Enable at least one SimpleChat capability before continuing.');
            return false;
          }
        } else if (isMsGraphVisible) {
          const selectedMsGraphCapabilities = this.getSelectedMsGraphCapabilities();
          const capabilityValues = Object.values(selectedMsGraphCapabilities);
          if (!capabilityValues.some(Boolean)) {
            this.showError('Enable at least one Microsoft Graph capability before continuing.');
            return false;
          }
          const mailConfig = this.getMsGraphMailSendConfiguration();
          const rawDelaySeconds = parseInt(document.getElementById('msgraph-mail-delay-seconds')?.value, 10);
          if (selectedMsGraphCapabilities.send_mail && mailConfig.msgraph_mail_send_mode === MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED) {
            if (Number.isNaN(rawDelaySeconds) || rawDelaySeconds < MSGRAPH_MIN_MAIL_DELAY_SECONDS || rawDelaySeconds > MSGRAPH_MAX_MAIL_DELAY_SECONDS) {
              this.showError('Microsoft Graph delayed mail delivery must be between 5 and 600 seconds.');
              return false;
            }
          }
          const calendarConfig = this.getMsGraphCalendarSendConfiguration();
          const rawCalendarDelaySeconds = parseInt(document.getElementById('msgraph-calendar-delay-seconds')?.value, 10);
          if (selectedMsGraphCapabilities.create_calendar_invite && calendarConfig.msgraph_calendar_send_mode === MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED) {
            if (Number.isNaN(rawCalendarDelaySeconds) || rawCalendarDelaySeconds < MSGRAPH_MIN_CALENDAR_DELAY_SECONDS || rawCalendarDelaySeconds > MSGRAPH_MAX_CALENDAR_DELAY_SECONDS) {
              this.showError('Microsoft Graph delayed calendar invite delivery must be between 5 and 600 seconds.');
              return false;
            }
          }
        } else if (isAzureMapsVisible) {
          const azureMapsKey = document.getElementById('azure-maps-key').value.trim();
          if (!azureMapsKey) {
            this.showError('Azure Maps subscription key is required.');
            return false;
          }
        } else if (isChartVisible) {
          const capabilityValues = Object.values(this.getSelectedChartCapabilities());
          if (!capabilityValues.some(Boolean)) {
            this.showError('Enable at least one chart type before continuing.');
            return false;
          }
        } else if (isDocumentSearchVisible) {
          const topN = parseInt(document.getElementById('document-search-top-n').value, 10);
          const windowSizeValue = document.getElementById('document-search-window-size').value.trim();
          const windowPercentValue = document.getElementById('document-search-window-percent').value.trim();

          if (Number.isNaN(topN) || topN < 1 || topN > 500) {
            this.showError('Default search result limit must be between 1 and 500.');
            return false;
          }
          if (windowSizeValue) {
            const windowSize = parseInt(windowSizeValue, 10);
            if (Number.isNaN(windowSize) || windowSize < 1 || windowSize > 100) {
              this.showError('Preferred window size must be between 1 and 100.');
              return false;
            }
          }
          if (windowPercentValue) {
            const windowPercent = parseInt(windowPercentValue, 10);
            if (Number.isNaN(windowPercent) || windowPercent < 1 || windowPercent > 100) {
              this.showError('Preferred window percent must be between 1 and 100.');
              return false;
            }
          }
        } else {
          // Validate generic endpoint field
          const endpoint = document.getElementById('plugin-endpoint-generic').value.trim();
          if (!endpoint) {
            this.showError('Endpoint is required.');
            return false;
          }
        }
        break;

      case 4:
        // Validate JSON fields
        if (!this.validateJSONField('plugin-metadata', 'Metadata')) return false;
        //if (!this.validateJSONField('plugin-additional-fields', 'Additional Fields')) return false;
        break;
    }

    return true;
  }

  validateJSONField(fieldId, fieldName) {
    const field = document.getElementById(fieldId);
    const value = field.value.trim();

    if (value && value !== '{}') {
      try {
        const parsed = JSON.parse(value);
        if (typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error(`${fieldName} must be a JSON object`);
        }
      } catch (e) {
        this.showError(`${fieldName}: ${e.message}`);
        return false;
      }
    }

    return true;
  }

  showError(message) {
    const errorDiv = document.getElementById('plugin-modal-error');
    errorDiv.textContent = message;
    errorDiv.classList.remove('d-none');
  }

  toggleOpenApiAuthFields() {
    const authType = document.getElementById('plugin-auth-type').value;
    const selectedIdentity = this.getSelectedActionIdentity('openapi');
    const groups = {
      apiKeyLocation: document.getElementById('auth-api-key-location-group'),
      apiKeyName: document.getElementById('auth-api-key-name-group'),
      apiKeyValue: document.getElementById('auth-api-key-value-group'),
      bearer: document.getElementById('auth-bearer-group'),
      basicUsername: document.getElementById('auth-basic-username-group'),
      basicPassword: document.getElementById('auth-basic-password-group'),
      oauth2: document.getElementById('auth-oauth2-group')
    };

    // Hide all groups first
    Object.values(groups).forEach(group => {
      if (group) group.style.display = 'none';
    });

    if (selectedIdentity) {
      return;
    }

    // Show relevant groups based on auth type
    switch (authType) {
      case 'api_key':
        if (groups.apiKeyLocation) groups.apiKeyLocation.style.display = 'flex';
        if (groups.apiKeyName) groups.apiKeyName.style.display = 'flex';
        if (groups.apiKeyValue) groups.apiKeyValue.style.display = 'flex';
        break;
      case 'bearer':
        if (groups.bearer) groups.bearer.style.display = 'flex';
        break;
      case 'basic':
        if (groups.basicUsername) groups.basicUsername.style.display = 'flex';
        if (groups.basicPassword) groups.basicPassword.style.display = 'flex';
        break;
      case 'oauth2':
        if (groups.oauth2) groups.oauth2.style.display = 'flex';
        break;
      case 'none':
        // No additional fields needed
        break;
    }
  }

  async handleFileUpload(event) {
    const file = event.target.files[0];
    const statusDiv = document.getElementById('openapi-file-status');

    if (!file) {
      // Clear any existing status when no file is selected
      statusDiv.innerHTML = '';
      const fileInput = document.getElementById('plugin-openapi-file');
      delete fileInput.dataset.fileId;
      delete fileInput.dataset.specContent;
      return;
    }

    // Clear previous status
    statusDiv.innerHTML = '<div class="spinner-border spinner-border-sm me-2" role="status"></div>Uploading and validating...';
    statusDiv.className = 'mt-2 text-info';

    // Create FormData for upload
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('/api/openapi/upload', {
        method: 'POST',
        body: formData
      });

      const result = await response.json();

      if (response.ok) {
        statusDiv.innerHTML = `
          <i class="bi bi-check-circle me-2"></i>
          File uploaded and validated successfully!
          <br><small class="text-muted">File ID: ${result.file_id}</small>
        `;
        statusDiv.className = 'mt-2 text-success';

        // Store the file ID and spec content for later use
        const fileElement = document.getElementById('plugin-openapi-file');
        fileElement.dataset.fileId = result.file_id;
        fileElement.dataset.specContent = JSON.stringify(result.spec_content);

        // Display API info if available
        if (result.spec_info) {
          this.displayOpenApiInfo(result.spec_info);
        }
      } else {
        statusDiv.innerHTML = `<i class="bi bi-exclamation-triangle me-2"></i>${result.error || 'Upload failed'}`;
        statusDiv.className = 'mt-2 text-danger';
      }
    } catch (error) {
      console.error('Upload error:', error);
      statusDiv.innerHTML = `<i class="bi bi-exclamation-triangle me-2"></i>Upload failed: ${error.message}`;
      statusDiv.className = 'mt-2 text-danger';
    }
  }

  displayOpenApiInfo(apiInfo) {
    const infoDisplay = document.getElementById('openapi-info-display');
    const infoContent = document.getElementById('openapi-info-content');
    const endpointInput = document.getElementById('plugin-endpoint');

    let infoHtml = '';
    if (apiInfo.title) {
      infoHtml += `<strong>Title:</strong> ${this.escapeHtml(apiInfo.title)}<br>`;
    }
    if (apiInfo.version) {
      infoHtml += `<strong>Version:</strong> ${this.escapeHtml(apiInfo.version)}<br>`;
    }
    if (apiInfo.description) {
      infoHtml += `<strong>Description:</strong> ${this.escapeHtml(apiInfo.description)}<br>`;
    }
    if (apiInfo.servers && apiInfo.servers.length > 0) {
      infoHtml += `<strong>Servers:</strong><br>`;
      apiInfo.servers.forEach(server => {
        infoHtml += `&nbsp;&nbsp;• ${this.escapeHtml(server.url)}`;
        if (server.description) {
          infoHtml += ` - ${this.escapeHtml(server.description)}`;
        }
        infoHtml += '<br>';
      });

      // Auto-populate Base URL from the first server if endpoint is empty
      if (endpointInput && !endpointInput.value.trim()) {
        const firstServerUrl = apiInfo.servers[0].url;
        endpointInput.value = firstServerUrl;

        // Add a visual indication that the URL was auto-populated
        endpointInput.classList.add('border-success');
        setTimeout(() => {
          endpointInput.classList.remove('border-success');
        }, 2000);

        // Show a small notification
        const notification = document.createElement('div');
        notification.className = 'text-success small mt-1';
        notification.innerHTML = '<i class="bi bi-check-circle me-1"></i>Base URL auto-populated from OpenAPI spec';
        endpointInput.parentNode.appendChild(notification);
        setTimeout(() => {
          if (notification.parentNode) {
            notification.parentNode.removeChild(notification);
          }
        }, 3000);
      }
    }
    if (apiInfo.endpoints_count) {
      infoHtml += `<strong>Endpoints:</strong> ${apiInfo.endpoints_count}<br>`;
    }

    infoContent.innerHTML = infoHtml;
    infoDisplay.classList.remove('d-none');
  }

  toggleAuthFields() {
    this.toggleGenericAuthFields();
  }

  toggleGenericAuthFields() {
    const dropdown = document.getElementById('plugin-auth-type-generic');
    if (!dropdown) return;
    const authType = dropdown.value;
    const selectedIdentity = this.getSelectedActionIdentity('generic');

    // Get required fields for selected auth type from schema
    let requiredFields = [];
    // Defensive: find the correct schema location
    const pluginDef = this.pluginSchemaCache?.definitions?.Plugin;
    const authSchema = pluginDef?.properties?.auth;
    if (authSchema && Array.isArray(authSchema.allOf)) {
      for (const cond of authSchema.allOf) {
        // Check if this allOf block matches the selected type
        if (cond.if && cond.if.properties && cond.if.properties.type && cond.if.properties.type.const === authType) {
          // Use the required array from then
          if (cond.then && Array.isArray(cond.then.required)) {
            requiredFields = cond.then.required.filter(f => f !== 'type');
          }
          break;
        }
      }
    }

    // Map field keys to DOM groups
    const fieldMap = {
      identity: document.getElementById('auth-identity-group'),
      key: document.getElementById('auth-key-group'),
      tenantId: document.getElementById('auth-tenantid-group')
    };

    // Hide all groups first using d-none
    Object.values(fieldMap).forEach(group => { if (group) group.classList.add('d-none'); });

    if (selectedIdentity) {
      return;
    }

    // Show only required fields for selected auth type using d-none
    requiredFields.forEach(field => {
      if (fieldMap[field]) {
        fieldMap[field].classList.remove('d-none');
        // Update label using mapping or schema description
        const label = fieldMap[field].querySelector('span.input-group-text');
        console.log('Updating label for field:', field, 'Auth type:', authType, 'label:', label);
        if (label) {
          if (authType === 'username_password') {
            if (field === 'key') label.textContent = 'Password';
            else if (field === 'identity') label.textContent = 'Username';
          } else if (authType === 'connection_string') {
            if (field === 'key') label.textContent = 'Connection String';
          } else if (authType === 'servicePrincipal') {
            if (field === 'key') label.textContent = 'Client Secret';
            else if (field === 'identity') label.textContent = 'Client ID';
            else if (field === 'tenantId') label.textContent = 'Tenant ID';
          } else {
            if (field === 'key') label.textContent = 'Key';
            else if (field === 'identity') label.textContent = 'Identity';
            else if (field === 'tenantId') label.textContent = 'Tenant ID';
          }
        }
      }
    });
  }

  // SQL Plugin Configuration Methods
  initializeCosmosConfiguration() {
    const authTypeField = document.getElementById('cosmos-auth-type');
    const maxItemsField = document.getElementById('cosmos-max-items');
    const timeoutField = document.getElementById('cosmos-timeout');
    if (authTypeField && !authTypeField.value) {
      authTypeField.value = 'identity';
    }
    if (maxItemsField && !maxItemsField.value) {
      maxItemsField.value = '100';
    }
    if (timeoutField && !timeoutField.value) {
      timeoutField.value = '30';
    }

    const resultDiv = document.getElementById('cosmos-test-connection-result');
    if (resultDiv) {
      resultDiv.classList.add('d-none');
    }

    this.handleCosmosAuthTypeChange();
  }

  handleCosmosAuthTypeChange() {
    const authType = document.getElementById('cosmos-auth-type')?.value || 'identity';
    const keyGroup = document.getElementById('cosmos-auth-key-group');
    const keyInput = document.getElementById('cosmos-auth-key');

    if (keyGroup) {
      keyGroup.classList.toggle('d-none', authType !== 'key');
    }

    if (keyInput) {
      keyInput.required = authType === 'key';
    }

    this.updateCosmosAuthInfo(authType);
  }

  updateCosmosAuthInfo(authType = document.getElementById('cosmos-auth-type')?.value || 'identity') {
    const infoDiv = document.getElementById('cosmos-auth-info');
    const infoText = document.getElementById('cosmos-auth-info-text');

    if (!infoDiv || !infoText) {
      return;
    }

    let message = 'Managed Identity uses Azure AD authentication without storing credentials. Assign an Azure Cosmos DB built-in data reader role to the application identity for the target account.';
    if (authType === 'key') {
      message = 'Account Key uses a primary or secondary Azure Cosmos DB account key. When Key Vault secret storage is enabled, the key is stored in Key Vault and edit forms preserve the stored secret if you leave the masked value unchanged.';
    }

    infoText.textContent = message;
    infoDiv.classList.remove('d-none');
  }

  getCosmosFieldHints() {
    const rawValue = document.getElementById('cosmos-field-hints')?.value || '';
    return rawValue
      .split(/[,\n]/)
      .map(value => value.trim())
      .filter(Boolean);
  }

  async testCosmosConnection() {
    const btn = document.getElementById('cosmos-test-connection-btn');
    const resultDiv = document.getElementById('cosmos-test-connection-result');
    const alertDiv = document.getElementById('cosmos-test-connection-alert');
    if (!btn || !resultDiv || !alertDiv) return;

    const endpoint = document.getElementById('cosmos-endpoint')?.value?.trim() || '';
    const databaseName = document.getElementById('cosmos-database-name')?.value?.trim() || '';
    const containerName = document.getElementById('cosmos-container-name')?.value?.trim() || '';
    const authType = document.getElementById('cosmos-auth-type')?.value || 'identity';
    const authKey = document.getElementById('cosmos-auth-key')?.value?.trim() || '';
    const timeout = parseInt(document.getElementById('cosmos-timeout')?.value, 10) || 10;

    if (!endpoint || !databaseName || !containerName) {
      resultDiv.classList.remove('d-none');
      alertDiv.className = 'alert alert-warning mb-0 py-2 px-3 small';
      alertDiv.textContent = 'Endpoint, database name, and container name are required before testing the Cosmos connection.';
      return;
    }
    if (authType === 'key' && !authKey) {
      resultDiv.classList.remove('d-none');
      alertDiv.className = 'alert alert-warning mb-0 py-2 px-3 small';
      alertDiv.textContent = 'Account key is required before testing a key-based Cosmos connection.';
      return;
    }

    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Testing...';
    btn.disabled = true;
    resultDiv.classList.add('d-none');

    try {
      const payload = {
        endpoint,
        database_name: databaseName,
        container_name: containerName,
        auth_type: authType,
        timeout
      };

      if (authType === 'key') {
        payload.auth_key = authKey;
      }

      const existingPluginContext = this.getTestPluginContext();
      if (existingPluginContext) {
        payload.existing_plugin = existingPluginContext;
      }

      const response = await fetch('/api/plugins/test-cosmos-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await response.json();

      resultDiv.classList.remove('d-none');
      if (data.success) {
        alertDiv.className = 'alert alert-success mb-0 py-2 px-3 small';
        alertDiv.innerHTML = '<i class="bi bi-check-circle me-2"></i>' + this.escapeHtml(data.message || 'Connection successful!');
      } else {
        alertDiv.className = 'alert alert-danger mb-0 py-2 px-3 small';
        alertDiv.innerHTML = '<i class="bi bi-x-circle me-2"></i>' + this.escapeHtml(data.error || 'Connection failed.');
      }
    } catch (error) {
      resultDiv.classList.remove('d-none');
      alertDiv.className = 'alert alert-danger mb-0 py-2 px-3 small';
      alertDiv.innerHTML = '<i class="bi bi-x-circle me-2"></i>Test failed: ' + this.escapeHtml(error.message || 'Network error');
    } finally {
      btn.innerHTML = originalText;
      btn.disabled = false;
    }
  }

  initializeSqlConfiguration() {
    // Set default values
    document.getElementById('sql-read-only').value = 'true';
    document.getElementById('sql-max-rows').value = '1000';
    document.getElementById('sql-timeout').value = '30';
    document.getElementById('sql-include-system-tables').value = 'false';

    // Auto-select plugin type based on initial selection and hide the redundant selection
    if (this.selectedType) {
      const pluginTypeSection = document.querySelector('.sql-plugin-type-selection');
      if (this.selectedType.toLowerCase() === 'sql_schema') {
        document.getElementById('sql-plugin-schema').checked = true;
        if (pluginTypeSection) pluginTypeSection.style.display = 'none';
      } else if (this.selectedType.toLowerCase() === 'sql_query') {
        document.getElementById('sql-plugin-query').checked = true;
        if (pluginTypeSection) pluginTypeSection.style.display = 'none';
      }
    }

    // Initialize connection examples
    this.updateSqlConnectionExamples();

    // Initialize auth info
    this.updateSqlAuthInfo();

    // Show/hide relevant sections
    this.handleSqlPluginTypeChange();
    this.handleSqlDatabaseTypeChange();
    this.handleSqlConnectionMethodChange();
    this.handleSqlAuthTypeChange();
  }

  handleSqlDatabaseTypeChange() {
    const selectedType = document.querySelector('input[name="sql-database-type"]:checked')?.value;

    if (!selectedType) return;

    // Update connection examples
    this.updateSqlConnectionExamples();

    // Show/hide fields based on database type
    const serverField = document.getElementById('sql-server-field');
    const portField = document.getElementById('sql-port-field');
    const driverField = document.getElementById('sql-driver-field');
    const databaseField = document.getElementById('sql-database-field');
    const authTypeSelect = document.getElementById('sql-auth-type');

    if (selectedType === 'sqlite') {
      serverField.style.display = 'none';
      portField.style.display = 'none';
      driverField.style.display = 'none';
      databaseField.querySelector('label').textContent = 'Database File Path';
      databaseField.querySelector('input').placeholder = '/path/to/database.db';
      databaseField.querySelector('.form-text').textContent = 'Full path to the SQLite database file';

      // Limit auth options for SQLite
      authTypeSelect.innerHTML = `
        <option value="connection_string_only">File Path Only</option>
      `;
    } else {
      serverField.style.display = 'block';
      portField.style.display = 'block';
      databaseField.querySelector('label').textContent = 'Database';
      databaseField.querySelector('input').placeholder = 'database_name';
      databaseField.querySelector('.form-text').textContent = 'Database name';

      // Show/hide driver field for SQL Server
      if (selectedType === 'sqlserver' || selectedType === 'azure_sql') {
        driverField.style.display = 'block';
      } else {
        driverField.style.display = 'none';
      }

      // Set auth options based on database type
      if (selectedType === 'azure_sql') {
        authTypeSelect.innerHTML = `
          <option value="managed_identity">Managed Identity (Recommended)</option>
          <option value="username_password">Username & Password</option>
          <option value="service_principal">Service Principal</option>
          <option value="connection_string_only">Connection String Only</option>
        `;
      } else {
        authTypeSelect.innerHTML = `
          <option value="username_password">Username & Password</option>
          <option value="integrated">Integrated Authentication</option>
          <option value="connection_string_only">Connection String Only</option>
        `;
      }
    }

    // Update port placeholder
    this.updatePortPlaceholder(selectedType);
    this.updateActionIdentitySelectors();
    this.handleActionIdentityChange('sql');

    // Trigger auth type change to update fields
    this.handleSqlAuthTypeChange();
  }

  handleSqlPluginTypeChange() {
    const selectedType = document.querySelector('input[name="sql-plugin-type"]:checked')?.value;

    const querySettings = document.getElementById('sql-query-settings');
    const schemaSettings = document.getElementById('sql-schema-settings');

    if (selectedType === 'query') {
      querySettings.classList.remove('d-none');
      schemaSettings.classList.add('d-none');
    } else if (selectedType === 'schema') {
      querySettings.classList.add('d-none');
      schemaSettings.classList.remove('d-none');
    } else {
      querySettings.classList.add('d-none');
      schemaSettings.classList.add('d-none');
    }
  }

  handleSqlConnectionMethodChange() {
    const selectedMethod = document.querySelector('input[name="sql-connection-method"]:checked')?.value;
    const selectedIdentity = this.getSelectedActionIdentity('sql');
    const identityAuthType = this.getIdentityAuthType(selectedIdentity);

    const stringSection = document.getElementById('sql-connection-string-section');
    const paramsSection = document.getElementById('sql-connection-params-section');

    if (selectedIdentity && identityAuthType === 'connection_string') {
      stringSection.classList.add('d-none');
      paramsSection.classList.add('d-none');
      return;
    }

    if (selectedMethod === 'connection_string') {
      stringSection.classList.remove('d-none');
      paramsSection.classList.add('d-none');
    } else {
      stringSection.classList.add('d-none');
      paramsSection.classList.remove('d-none');
    }
  }

  handleSqlAuthTypeChange() {
    const authType = document.getElementById('sql-auth-type').value;
    const selectedIdentity = this.getSelectedActionIdentity('sql');
    const credentialsDiv = document.getElementById('sql-auth-credentials');
    const servicePrincipalDiv = document.getElementById('sql-auth-service-principal');

    // Hide all auth sections first
    credentialsDiv.style.display = 'none';
    servicePrincipalDiv.style.display = 'none';

    if (selectedIdentity) {
      this.updateSqlAuthInfo();
      return;
    }

    // Show relevant sections
    switch (authType) {
      case 'username_password':
        credentialsDiv.style.display = 'block';
        break;
      case 'service_principal':
        servicePrincipalDiv.style.display = 'block';
        break;
      case 'integrated':
      case 'managed_identity':
      case 'connection_string_only':
        // No additional fields needed
        break;
    }

    // Update auth info
    this.updateSqlAuthInfo();
  }

  getTestPluginContext() {
    if (!this.isEditMode || !this.originalPlugin) {
      return null;
    }

    const originalPlugin = this.originalPlugin;
    let scope = originalPlugin.scope;

    if (!scope) {
      if (originalPlugin.is_group) {
        scope = 'group';
      } else if (originalPlugin.is_global || window.location.pathname.includes('admin')) {
        scope = 'global';
      } else {
        scope = 'user';
      }
    }

    return {
      id: originalPlugin.id || '',
      name: originalPlugin.name || '',
      scope
    };
  }

  async testSqlConnection() {
    const btn = document.getElementById('sql-test-connection-btn');
    const resultDiv = document.getElementById('sql-test-connection-result');
    const alertDiv = document.getElementById('sql-test-connection-alert');
    if (!btn || !resultDiv || !alertDiv) return;

    // Collect current SQL config from Step 3
    const databaseType = document.querySelector('input[name="sql-database-type"]:checked')?.value;
    const connectionMethod = document.querySelector('input[name="sql-connection-method"]:checked')?.value || 'parameters';
    const authType = document.getElementById('sql-auth-type')?.value || 'username_password';
    const selectedIdentity = this.getSelectedActionIdentity('sql');

    if (!databaseType) {
      resultDiv.classList.remove('d-none');
      alertDiv.className = 'alert alert-warning mb-0 py-2 px-3 small';
      alertDiv.textContent = 'Please select a database type first.';
      return;
    }

    const payload = {
      database_type: databaseType,
      connection_method: connectionMethod,
      auth_type: authType
    };

    if (selectedIdentity) {
      payload.identity_id = selectedIdentity.id || selectedIdentity.identity_id || '';
      payload.action_scope = this.actionIdentityScope?.scope || 'personal';
      payload.auth_type = this.getSqlAuthTypeForIdentity(selectedIdentity);
      if (this.getIdentityAuthType(selectedIdentity) === 'connection_string') {
        payload.connection_method = 'connection_string';
      }
    }

    if (connectionMethod === 'connection_string') {
      payload.connection_string = document.getElementById('sql-connection-string')?.value?.trim() || '';
    } else {
      payload.server = document.getElementById('sql-server')?.value?.trim() || '';
      payload.database = document.getElementById('sql-database')?.value?.trim() || '';
      payload.port = document.getElementById('sql-port')?.value?.trim() || '';
      if (databaseType === 'sqlserver' || databaseType === 'azure_sql') {
        payload.driver = document.getElementById('sql-driver')?.value || '';
      }
    }

    if (authType === 'username_password') {
      payload.username = document.getElementById('sql-username')?.value?.trim() || '';
      payload.password = document.getElementById('sql-password')?.value?.trim() || '';
    }

    payload.timeout = parseInt(document.getElementById('sql-timeout')?.value) || 10;

    const existingPluginContext = this.getTestPluginContext();
    if (existingPluginContext) {
      payload.existing_plugin = existingPluginContext;
    }

    // Show loading state
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Testing...';
    btn.disabled = true;
    resultDiv.classList.add('d-none');

    try {
      const response = await fetch('/api/plugins/test-sql-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await response.json();

      resultDiv.classList.remove('d-none');
      if (data.success) {
        alertDiv.className = 'alert alert-success mb-0 py-2 px-3 small';
        alertDiv.innerHTML = '<i class="bi bi-check-circle me-2"></i>' + (data.message || 'Connection successful!');
      } else {
        alertDiv.className = 'alert alert-danger mb-0 py-2 px-3 small';
        alertDiv.innerHTML = '<i class="bi bi-x-circle me-2"></i>' + (data.error || 'Connection failed.');
      }
    } catch (error) {
      resultDiv.classList.remove('d-none');
      alertDiv.className = 'alert alert-danger mb-0 py-2 px-3 small';
      alertDiv.innerHTML = '<i class="bi bi-x-circle me-2"></i>Test failed: ' + (error.message || 'Network error');
    } finally {
      btn.innerHTML = originalText;
      btn.disabled = false;
    }
  }

  updateSqlConnectionExamples() {
    const selectedType = document.querySelector('input[name="sql-database-type"]:checked')?.value;
    const examplesDiv = document.getElementById('sql-connection-examples');

    if (!selectedType || !examplesDiv) return;

    const examples = this.getSqlConnectionExamples(selectedType);
    examplesDiv.innerHTML = examples;
  }

  getSqlConnectionExamples(dbType) {
    const examples = {
      sqlserver: `
        <div class="example"><strong>SQL Server:</strong> DRIVER={ODBC Driver 18 for SQL Server};SERVER=server.com;DATABASE=mydb;UID=user;PWD=pass</div>
        <div class="example"><strong>Integrated Auth:</strong> DRIVER={ODBC Driver 18 for SQL Server};SERVER=server.com;DATABASE=mydb;Trusted_Connection=yes</div>
      `,
      azure_sql: `
        <div class="example"><strong>Managed Identity:</strong> DRIVER={ODBC Driver 18 for SQL Server};SERVER=server.database.windows.net;DATABASE=mydb;Authentication=ActiveDirectoryMsi</div>
        <div class="example"><strong>Username/Password:</strong> DRIVER={ODBC Driver 18 for SQL Server};SERVER=server.database.windows.net;DATABASE=mydb;UID=user;PWD=pass</div>
      `,
      postgresql: `
        <div class="example"><strong>PostgreSQL:</strong> host=localhost dbname=mydb user=username password=password port=5432</div>
        <div class="example"><strong>With SSL:</strong> host=server.com dbname=mydb user=username password=password sslmode=require</div>
      `,
      mysql: `
        <div class="example"><strong>MySQL:</strong> mysql://username:password@localhost:3306/database_name</div>
        <div class="example"><strong>With SSL:</strong> mysql://username:password@server.com:3306/database_name?ssl=true</div>
      `,
      sqlite: `
        <div class="example"><strong>SQLite:</strong> /path/to/your/database.db</div>
        <div class="example"><strong>Relative path:</strong> ./data/database.db</div>
      `
    };

    return examples[dbType] || '';
  }

  updatePortPlaceholder(dbType) {
    const portInput = document.getElementById('sql-port');
    if (!portInput) return;

    const defaultPorts = {
      sqlserver: '1433',
      azure_sql: '1433',
      postgresql: '5432',
      mysql: '3306'
    };

    portInput.placeholder = defaultPorts[dbType] || 'Auto-detect';
  }

  updateSqlAuthInfo() {
    const authType = document.getElementById('sql-auth-type').value;
    const dbType = document.querySelector('input[name="sql-database-type"]:checked')?.value;
    const infoDiv = document.getElementById('sql-auth-info');
    const infoText = document.getElementById('sql-auth-info-text');

    if (!infoDiv || !infoText) return;

    let message = '';

    switch (authType) {
      case 'managed_identity':
        message = 'Managed Identity uses Azure AD authentication without storing credentials. Ensure your application has the appropriate database permissions assigned.';
        break;
      case 'service_principal':
        message = 'Service Principal authentication uses Azure AD application credentials. Store client secrets securely and rotate them regularly.';
        break;
      case 'integrated':
        message = 'Integrated Authentication uses Windows credentials of the running application. Ensure the application service account has database access.';
        break;
      case 'username_password':
        message = 'Username and password authentication stores credentials in the configuration. Consider using more secure authentication methods for production.';
        break;
      case 'connection_string_only':
        message = 'Connection string contains all authentication details. Ensure the string is properly secured and not logged in plain text.';
        break;
    }

    if (message) {
      infoText.textContent = message;
      infoDiv.classList.remove('d-none');
    } else {
      infoDiv.classList.add('d-none');
    }
  }

  populateFormFromPlugin(plugin) {
    // Step 2 fields
    document.getElementById('plugin-name').value = plugin.name || '';
    document.getElementById('plugin-display-name').value = plugin.displayName || '';
    document.getElementById('plugin-description').value = plugin.description || '';
    document.getElementById('plugin-type').value = plugin.type || '';

    // Step 3 fields - populate based on plugin type
    const isOpenApiType = plugin.type && plugin.type.toLowerCase().includes('openapi');

    if (isOpenApiType) {
      // Populate OpenAPI fields
      const additionalFields = plugin.additionalFields || {};
      document.getElementById('plugin-endpoint').value = plugin.endpoint || additionalFields.base_url || '';

      // Handle existing OpenAPI specification content
      if (additionalFields.openapi_spec_content) {
        const fileInput = document.getElementById('plugin-openapi-file');
        const statusDiv = document.getElementById('openapi-file-status');
        const helpDiv = document.getElementById('openapi-file-help');

        // Store the existing spec data in the file input's dataset
        fileInput.dataset.fileId = 'existing_' + plugin.name; // Generate a unique ID for existing content
        fileInput.dataset.specContent = JSON.stringify(additionalFields.openapi_spec_content);

        // Update help text for editing mode
        if (helpDiv) {
          helpDiv.innerHTML = `
            <strong>Editing mode:</strong> This action already has an OpenAPI specification. You can:
            <br>• Keep the existing specification (no need to upload again)
            <br>• Upload a new file to replace the existing specification
            <br><strong>Security:</strong> Files are automatically scanned for malicious content.
          `;
        }

        // Show status that existing specification is loaded
        statusDiv.innerHTML = `
          <i class="bi bi-file-earmark-check me-2"></i>
          Using existing OpenAPI specification
          <br><small class="text-muted">You can upload a new file to replace it, or keep the existing one</small>
        `;
        statusDiv.className = 'mt-2 text-success';

        // If we have spec info, try to extract and display it
        const specContent = additionalFields.openapi_spec_content;
        if (specContent && specContent.info) {
          this.displayOpenApiInfo({
            title: specContent.info.title,
            version: specContent.info.version,
            description: specContent.info.description,
            servers: specContent.servers || []
          });
        }
      }

      const auth = plugin.auth || {};
      let authType = 'none';

      // Map from our schema format to modal format
      if (auth.type === 'key') {
        // Determine the actual auth method from additionalFields
        const authMethod = additionalFields.auth_method;

        if (authMethod === 'none' || !auth.key) {
          authType = 'none';
        } else if (additionalFields.api_key_location && additionalFields.api_key_name) {
          // This is API key authentication
          authType = 'api_key';
          document.getElementById('plugin-auth-api-key-location').value = additionalFields.api_key_location || 'header';
          document.getElementById('plugin-auth-api-key-name').value = additionalFields.api_key_name || '';
          document.getElementById('plugin-auth-api-key-value').value = auth.key || '';
        } else if (authMethod === 'bearer') {
          authType = 'bearer';
          document.getElementById('plugin-auth-bearer-token').value = auth.key || '';
        } else if (authMethod === 'basic') {
          authType = 'basic';
          // Split the combined username:password format
          const credentials = auth.key ? auth.key.split(':') : ['', ''];
          document.getElementById('plugin-auth-basic-username').value = credentials[0] || '';
          document.getElementById('plugin-auth-basic-password').value = credentials[1] || '';
        } else if (authMethod === 'oauth2') {
          authType = 'oauth2';
          document.getElementById('plugin-auth-oauth2-token').value = auth.key || '';
        } else {
          // Default to API key if we have a key but no clear method
          authType = 'api_key';
          document.getElementById('plugin-auth-api-key-location').value = 'header';
          document.getElementById('plugin-auth-api-key-name').value = 'X-API-Key';
          document.getElementById('plugin-auth-api-key-value').value = auth.key || '';
        }
      } else if (auth.type === 'api_key') {
        // Legacy format - still support it
        authType = 'api_key';
        document.getElementById('plugin-auth-api-key-location').value = auth.location || 'header';
        document.getElementById('plugin-auth-api-key-name').value = auth.name || '';
        document.getElementById('plugin-auth-api-key-value').value = auth.value || '';
      } else if (auth.type === 'bearer') {
        // Legacy format - still support it
        authType = 'bearer';
        document.getElementById('plugin-auth-bearer-token').value = auth.token || '';
      } else if (auth.type === 'basic') {
        // Legacy format - still support it
        authType = 'basic';
        document.getElementById('plugin-auth-basic-username').value = auth.username || '';
        document.getElementById('plugin-auth-basic-password').value = auth.password || '';
      } else if (auth.type === 'oauth2') {
        // Legacy format - still support it
        authType = 'oauth2';
        document.getElementById('plugin-auth-oauth2-token').value = auth.access_token || '';
      }

      document.getElementById('plugin-auth-type').value = authType;
      this.setSelectedActionIdentity('openapi', plugin.identity_id || '');
      this.handleActionIdentityChange('openapi');
    } else if (this.isSqlType(plugin.type)) {
      // Populate SQL fields
      const additionalFields = plugin.additionalFields || {};
      const auth = plugin.auth || {};

      const pluginVariant = plugin.type.toLowerCase() === 'sql_schema' ? 'schema' : 'query';
      const pluginTypeRadio = document.querySelector(`input[name="sql-plugin-type"][value="${pluginVariant}"]`);
      if (pluginTypeRadio) {
        pluginTypeRadio.checked = true;
      }

      // Database type - select the appropriate radio button
      const databaseType = additionalFields.database_type || 'sqlserver';
      const dbTypeRadio = document.getElementById(`sql-db-${databaseType}`);
      if (dbTypeRadio) {
        dbTypeRadio.checked = true;
      }

      const hasConnectionString = typeof additionalFields.connection_string === 'string' && additionalFields.connection_string.length > 0;
      const connectionMethodValue = hasConnectionString ? 'connection_string' : 'parameters';
      const connectionMethodRadio = document.querySelector(`input[name="sql-connection-method"][value="${connectionMethodValue}"]`);
      if (connectionMethodRadio) {
        connectionMethodRadio.checked = true;
      }

      document.getElementById('sql-connection-string').value = additionalFields.connection_string || '';
      document.getElementById('sql-server').value = additionalFields.server || '';
      document.getElementById('sql-database').value = additionalFields.database || '';
      document.getElementById('sql-port').value = additionalFields.port || '';
      document.getElementById('sql-driver').value = additionalFields.driver || 'ODBC Driver 18 for SQL Server';

      let sqlAuthType = hasConnectionString ? 'connection_string_only' : 'username_password';

      if (auth.type === 'servicePrincipal') {
        sqlAuthType = 'service_principal';
        document.getElementById('sql-client-id').value = auth.identity || auth.client_id || '';
        document.getElementById('sql-client-secret').value = auth.key || auth.client_secret || '';
        document.getElementById('sql-tenant-id').value = auth.tenantId || auth.tenant_id || '';
      } else if (auth.type === 'user' || auth.type === 'username_password' || additionalFields.username || additionalFields.password) {
        sqlAuthType = 'username_password';
        document.getElementById('sql-username').value = additionalFields.username || '';
        document.getElementById('sql-password').value = additionalFields.password || '';
      } else if (auth.type === 'integrated' || auth.type === 'windows') {
        sqlAuthType = 'integrated';
      } else if (auth.type === 'identity') {
        sqlAuthType = databaseType === 'azure_sql' ? 'managed_identity' : 'integrated';
      }

      document.getElementById('sql-auth-type').value = sqlAuthType;
      this.handleSqlDatabaseTypeChange();
      this.handleSqlConnectionMethodChange();
      this.handleSqlAuthTypeChange();
      this.setSelectedActionIdentity('sql', plugin.identity_id || '');
      this.handleActionIdentityChange('sql');
    } else if (this.isCosmosType(plugin.type)) {
      const additionalFields = plugin.additionalFields || {};
      const auth = plugin.auth || {};

      document.getElementById('cosmos-endpoint').value = plugin.endpoint || '';
      document.getElementById('cosmos-database-name').value = additionalFields.database_name || '';
      document.getElementById('cosmos-container-name').value = additionalFields.container_name || '';
      document.getElementById('cosmos-partition-key-path').value = additionalFields.partition_key_path || '';
      document.getElementById('cosmos-field-hints').value = Array.isArray(additionalFields.field_hints)
        ? additionalFields.field_hints.join('\n')
        : '';
      document.getElementById('cosmos-max-items').value = additionalFields.max_items || 100;
      document.getElementById('cosmos-timeout').value = additionalFields.timeout || 30;
      document.getElementById('cosmos-auth-type').value = auth.type || 'identity';
      document.getElementById('cosmos-auth-key').value = auth.key || '';
      this.initializeCosmosConfiguration();
    } else if (this.isDocumentSearchType(plugin.type)) {
      this.populateDocumentSearchForm(plugin.additionalFields || {});
      this.initializeDocumentSearchConfiguration();
    } else if (this.isBlobStorageType(plugin.type)) {
      const additionalFields = plugin.additionalFields || plugin.additional_fields || {};
      const auth = plugin.auth || {};

      document.getElementById('blob-storage-connection-string').value = auth.key || '';
      document.getElementById('blob-storage-container-name').value = additionalFields.container_name || '';
      document.getElementById('blob-storage-blob-prefix').value = additionalFields.blob_prefix || '';
      this.setBlobStorageConfiguration({
        blob_storage_capabilities: additionalFields.blob_storage_capabilities || plugin.blob_storage_capabilities || null,
        blob_storage_read_file_types: additionalFields.blob_storage_read_file_types || plugin.blob_storage_read_file_types || null,
        blob_storage_upload_file_types: additionalFields.blob_storage_upload_file_types || plugin.blob_storage_upload_file_types || null
      });
    } else if (this.isDatabricksType(plugin.type)) {
      this.populateDatabricksForm(plugin);
    } else if (this.isSnowflakeType(plugin.type)) {
      this.populateSnowflakeForm(plugin);
    } else if (this.isTableauType(plugin.type)) {
      this.populateTableauForm(plugin);
    } else if (this.isMcpType(plugin.type)) {
      this.populateMcpForm(plugin);
    } else if (this.isSimpleChatType(plugin.type)) {
      const additionalFields = plugin.additionalFields || plugin.additional_fields || {};
      this.setSimpleChatCapabilities(additionalFields.simplechat_capabilities || plugin.simplechat_capabilities || null);
    } else if (this.isMsGraphType(plugin.type)) {
      const additionalFields = plugin.additionalFields || plugin.additional_fields || {};
      this.setMsGraphCapabilities(additionalFields.msgraph_capabilities || plugin.msgraph_capabilities || null);
      this.setMsGraphMailSendConfiguration(additionalFields);
      this.setMsGraphCalendarSendConfiguration(additionalFields);
    } else if (this.isAzureMapsType(plugin.type)) {
      const auth = plugin.auth || {};
      document.getElementById('azure-maps-key').value = auth.key || '';
    } else if (this.isChartType(plugin.type)) {
      const additionalFields = plugin.additionalFields || plugin.additional_fields || {};
      this.setChartCapabilities(additionalFields.chart_capabilities || plugin.chart_capabilities || null);
    } else {
      // Populate generic fields
      document.getElementById('plugin-endpoint-generic').value = plugin.endpoint || '';

      const auth = plugin.auth || {};
      let authType = auth.type || 'key';
      if (authType === 'managedIdentity') authType = 'identity'; // Legacy support

      document.getElementById('plugin-auth-type-generic').value = authType;
      document.getElementById('plugin-auth-key').value = auth.key || '';
      document.getElementById('plugin-auth-identity').value = auth.identity || auth.managedIdentity || '';
      document.getElementById('plugin-auth-tenant-id').value = auth.tenantId || '';
      this.setSelectedActionIdentity('generic', plugin.identity_id || '');
      this.handleActionIdentityChange('generic');
    }

    // Step 4 fields
    const metadata = plugin.metadata && Object.keys(plugin.metadata).length > 0 ?
      JSON.stringify(plugin.metadata, null, 2) : '{}';
    const additionalFields = plugin.additionalFields && Object.keys(plugin.additionalFields).length > 0 ?
      JSON.stringify(plugin.additionalFields, null, 2) : '{}';

    document.getElementById('plugin-metadata').value = metadata;
    try {
      document.getElementById('plugin-additional-fields').value = additionalFields;
    } catch (e) {
      console.warn('Legacy additional fields accessed:', e);
    }
  }

  getFormData() {
    // Determine which configuration section is active
    const openApiSection = document.getElementById('openapi-config-section');
    const sqlSection = document.getElementById('sql-config-section');
    const cosmosSection = document.getElementById('cosmos-config-section');
    const documentSearchSection = document.getElementById('document-search-config-section');
    const blobStorageSection = document.getElementById('blob-storage-config-section');
    const databricksSection = document.getElementById('databricks-config-section');
    const snowflakeSection = document.getElementById('snowflake-config-section');
    const tableauSection = document.getElementById('tableau-config-section');
    const mcpSection = document.getElementById('mcp-config-section');
    const azureMapsSection = document.getElementById('azure-maps-config-section');
    const isOpenApiVisible = !openApiSection.classList.contains('d-none');
    const isSqlVisible = !sqlSection.classList.contains('d-none');
    const isCosmosVisible = !cosmosSection.classList.contains('d-none');
    const isDocumentSearchVisible = !documentSearchSection.classList.contains('d-none');
    const isBlobStorageVisible = !blobStorageSection.classList.contains('d-none');
    const isDatabricksVisible = !databricksSection.classList.contains('d-none');
    const isSnowflakeVisible = !snowflakeSection.classList.contains('d-none');
    const isTableauVisible = !tableauSection.classList.contains('d-none');
    const isMcpVisible = !mcpSection.classList.contains('d-none');
    const isAzureMapsVisible = !azureMapsSection.classList.contains('d-none');

    let auth = {};
    let endpoint = '';
    let additionalFields = {};
    let identityId = '';

    if (isOpenApiVisible) {
      // Collect OpenAPI-specific data
      endpoint = document.getElementById('plugin-endpoint').value.trim();

      // Handle OpenAPI file upload or existing spec
      const fileInput = document.getElementById('plugin-openapi-file');
      const fileId = fileInput.dataset.fileId;
      const specContent = fileInput.dataset.specContent;

      // Check if we have either uploaded file data or existing spec content
      if (!fileId || !specContent) {
        throw new Error('Please upload an OpenAPI specification file');
      }

      // Store the OpenAPI spec content directly in the plugin config
      // IMPORTANT: Set these BEFORE collecting additional fields so they don't get overwritten
      additionalFields.openapi_spec_content = JSON.parse(specContent);
      additionalFields.openapi_source_type = 'content';  // Changed from 'file'
      additionalFields.base_url = endpoint;

      const selectedIdentity = this.getSelectedActionIdentity('openapi');
      const authType = document.getElementById('plugin-auth-type').value;

      if (selectedIdentity) {
        identityId = selectedIdentity.id || selectedIdentity.identity_id || '';
        auth.type = 'identity';
        auth.identity = identityId;
        additionalFields.identity_auth_type = this.getIdentityAuthType(selectedIdentity);
        additionalFields.auth_method = 'identity';
      } else if (authType === 'api_key') {
        // Map api_key to 'key' type for schema compliance
        auth.type = 'key';
        const apiKeyValue = document.getElementById('plugin-auth-api-key-value').value.trim();
        auth.key = apiKeyValue;

        // Store API key configuration details in additionalFields instead of auth object
        const apiKeyLocation = document.getElementById('plugin-auth-api-key-location').value;
        const apiKeyName = document.getElementById('plugin-auth-api-key-name').value.trim();
        additionalFields.api_key_location = apiKeyLocation;
        additionalFields.api_key_name = apiKeyName;
      } else if (authType === 'bearer') {
        auth.type = 'key';  // Bearer tokens are also 'key' type in the schema
        auth.key = document.getElementById('plugin-auth-bearer-token').value.trim();
        additionalFields.auth_method = 'bearer';
      } else if (authType === 'basic') {
        auth.type = 'key';  // Basic auth is also 'key' type in the schema
        const username = document.getElementById('plugin-auth-basic-username').value.trim();
        const password = document.getElementById('plugin-auth-basic-password').value.trim();
        auth.key = `${username}:${password}`;  // Store as combined string
        additionalFields.auth_method = 'basic';
      } else if (authType === 'oauth2') {
        auth.type = 'key';  // OAuth2 is also 'key' type in the schema
        auth.key = document.getElementById('plugin-auth-oauth2-token').value.trim();
        additionalFields.auth_method = 'oauth2';
      } else if (authType === 'none') {
        auth.type = 'key';
        auth.key = '';  // Empty key for no auth
        additionalFields.auth_method = 'none';
      }
    } else if (isSqlVisible) {
      // Collect SQL plugin data
      const databaseType = document.querySelector('input[name="sql-database-type"]:checked')?.value;
      const pluginType = document.querySelector('input[name="sql-plugin-type"]:checked')?.value;
      const connectionMethod = document.querySelector('input[name="sql-connection-method"]:checked')?.value;
      const authType = document.getElementById('sql-auth-type').value;
      const selectedIdentity = this.getSelectedActionIdentity('sql');
      const selectedIdentityAuthType = this.getIdentityAuthType(selectedIdentity);

      if (!databaseType) {
        throw new Error('Please select a database type');
      }
      if (!pluginType) {
        throw new Error('Please select a plugin type (Schema or Query)');
      }

      // Set the actual plugin type based on selection
      this.selectedType = pluginType === 'schema' ? 'sql_schema' : 'sql_query';

      // Database configuration
      additionalFields.database_type = databaseType;

      if (selectedIdentity && selectedIdentityAuthType === 'connection_string') {
        additionalFields.identity_uses_connection_string = true;
      } else if (connectionMethod === 'connection_string') {
        const connectionString = document.getElementById('sql-connection-string').value.trim();
        if (!connectionString) {
          throw new Error('Please enter a connection string');
        }
        additionalFields.connection_string = connectionString;
      } else {
        // Individual parameters
        if (databaseType !== 'sqlite') {
          const server = document.getElementById('sql-server').value.trim();
          if (!server) {
            throw new Error('Please enter the server name');
          }
          additionalFields.server = server;

          const port = document.getElementById('sql-port').value.trim();
          if (port) {
            additionalFields.port = parseInt(port);
          }

          if (databaseType === 'sqlserver' || databaseType === 'azure_sql') {
            additionalFields.driver = document.getElementById('sql-driver').value;
          }
        }

        const database = document.getElementById('sql-database').value.trim();
        if (!database) {
          throw new Error('Please enter the database name/path');
        }
        additionalFields.database = database;
      }

      // Authentication configuration
      // Map SQL auth types to schema-compliant auth types
      let schemaAuthType;
      if (selectedIdentity) {
        identityId = selectedIdentity.id || selectedIdentity.identity_id || '';
        auth.type = 'identity';
        auth.identity = identityId;
        additionalFields.identity_auth_type = selectedIdentityAuthType;
        additionalFields.auth_type = selectedIdentityAuthType;
      } else {
        switch (authType) {
          case 'username_password':
            schemaAuthType = 'user';
            break;
          case 'service_principal':
            schemaAuthType = 'servicePrincipal';
            break;
          case 'managed_identity':
            schemaAuthType = 'identity';
            break;
          case 'integrated':
          case 'connection_string_only':
          default:
            schemaAuthType = 'identity';
            break;
        }
        auth.type = schemaAuthType;
        additionalFields.auth_type = authType;

        switch (authType) {
          case 'username_password':
            const username = document.getElementById('sql-username').value.trim();
            const password = document.getElementById('sql-password').value.trim();
            if (!username || !password) {
              throw new Error('Please enter both username and password');
            }
            additionalFields.username = username;
            additionalFields.password = password;
            break;

          case 'service_principal':
            const clientId = document.getElementById('sql-client-id').value.trim();
            const clientSecret = document.getElementById('sql-client-secret').value.trim();
            const tenantId = document.getElementById('sql-tenant-id').value.trim();
            if (!clientId || !clientSecret || !tenantId) {
              throw new Error('Please enter client ID, client secret, and tenant ID');
            }
            auth.identity = clientId;
            auth.key = clientSecret;
            auth.tenantId = tenantId;
            break;

          case 'integrated':
          case 'managed_identity':
          case 'connection_string_only':
            // No additional fields needed
            break;
        }
      }

      // Plugin-specific settings
      if (pluginType === 'query') {
        additionalFields.read_only = document.getElementById('sql-read-only').value === 'true';
        additionalFields.max_rows = parseInt(document.getElementById('sql-max-rows').value) || 1000;
        additionalFields.timeout = parseInt(document.getElementById('sql-timeout').value) || 30;
      } else if (pluginType === 'schema') {
        additionalFields.include_system_tables = document.getElementById('sql-include-system-tables').value === 'true';
        const tableFilter = document.getElementById('sql-table-filter').value.trim();
        if (tableFilter) {
          additionalFields.table_filter = tableFilter;
        }
      }

      // For SQL plugins, endpoint is not applicable
      endpoint = '';
    } else if (isCosmosVisible) {
      endpoint = document.getElementById('cosmos-endpoint').value.trim();
      const databaseName = document.getElementById('cosmos-database-name').value.trim();
      const containerName = document.getElementById('cosmos-container-name').value.trim();
      const partitionKeyPath = document.getElementById('cosmos-partition-key-path').value.trim();
      const authType = document.getElementById('cosmos-auth-type').value;

      if (!endpoint || !databaseName || !containerName || !partitionKeyPath) {
        throw new Error('Please complete the Cosmos DB endpoint, database, container, and partition key path.');
      }

      auth.type = authType;
      if (authType === 'key') {
        const authKey = document.getElementById('cosmos-auth-key').value.trim();
        if (!authKey) {
          throw new Error('Please enter the Cosmos DB account key.');
        }
        auth.key = authKey;
      } else {
        auth.identity = 'managed_identity';
      }
      additionalFields.database_name = databaseName;
      additionalFields.container_name = containerName;
      additionalFields.partition_key_path = partitionKeyPath;
      additionalFields.field_hints = this.getCosmosFieldHints();
      additionalFields.max_items = parseInt(document.getElementById('cosmos-max-items').value, 10) || 100;
      additionalFields.timeout = parseInt(document.getElementById('cosmos-timeout').value, 10) || 30;
    } else if (isDocumentSearchVisible) {
      endpoint = INTERNAL_DOCUMENT_SEARCH_ENDPOINT;
      auth.type = 'NoAuth';
      additionalFields = this.getDocumentSearchAdditionalFields();
    } else if (isBlobStorageVisible) {
      const connectionString = document.getElementById('blob-storage-connection-string').value.trim();
      const containerName = document.getElementById('blob-storage-container-name').value.trim();
      const blobPrefix = this.normalizeBlobStoragePrefix(document.getElementById('blob-storage-blob-prefix').value);

      auth.type = 'connection_string';
      auth.key = connectionString;
      endpoint = this.deriveBlobStorageEndpointFromConnectionString(connectionString) || this.originalPlugin?.endpoint || '';
      additionalFields.container_name = containerName;
      if (blobPrefix) {
        additionalFields.blob_prefix = blobPrefix;
      }
      additionalFields.blob_storage_capabilities = this.getSelectedBlobStorageCapabilities();
      additionalFields.blob_storage_read_file_types = this.getSelectedBlobStorageReadFileTypes();
      additionalFields.blob_storage_upload_file_types = this.getSelectedBlobStorageUploadFileTypes();
    } else if (isDatabricksVisible) {
      const databricksConfig = this.getDatabricksConfiguration();
      endpoint = databricksConfig.endpoint;
      auth = databricksConfig.auth;
      additionalFields = databricksConfig.additionalFields;
      identityId = databricksConfig.identityId;
    } else if (isSnowflakeVisible) {
      const snowflakeConfig = this.getSnowflakeConfiguration();
      endpoint = snowflakeConfig.endpoint;
      auth = snowflakeConfig.auth;
      additionalFields = snowflakeConfig.additionalFields;
      identityId = snowflakeConfig.identityId;
    } else if (isTableauVisible) {
      const tableauConfig = this.getTableauConfiguration();
      endpoint = tableauConfig.endpoint;
      auth = tableauConfig.auth;
      additionalFields = tableauConfig.additionalFields;
      identityId = tableauConfig.identityId;
    } else if (isMcpVisible) {
      const mcpConfig = this.getMcpConfiguration();
      endpoint = mcpConfig.endpoint;
      auth = mcpConfig.auth;
      additionalFields = mcpConfig.additionalFields;
      identityId = mcpConfig.identityId;
    } else if (this.isSimpleChatType()) {
      endpoint = '';
      auth.type = 'user';
      additionalFields.simplechat_capabilities = this.getSelectedSimpleChatCapabilities();
    } else if (this.isMsGraphType()) {
      endpoint = MSGRAPH_DEFAULT_ENDPOINT;
      auth.type = 'user';
      additionalFields.msgraph_capabilities = this.getSelectedMsGraphCapabilities();
      Object.assign(additionalFields, this.getMsGraphMailSendConfiguration());
      Object.assign(additionalFields, this.getMsGraphCalendarSendConfiguration());
    } else if (isAzureMapsVisible) {
      endpoint = AZURE_MAPS_DEFAULT_ENDPOINT;
      auth.type = 'key';
      auth.key = document.getElementById('azure-maps-key').value.trim();
    } else if (this.isChartType()) {
      endpoint = CHART_DEFAULT_ENDPOINT;
      auth.type = 'user';
      additionalFields.chart_capabilities = this.getSelectedChartCapabilities();
    } else {
      // Collect generic plugin data
      console.log("Collecting generic plugin data");
      endpoint = document.getElementById('plugin-endpoint-generic').value.trim();

      const selectedIdentity = this.getSelectedActionIdentity('generic');
      const authType = document.getElementById('plugin-auth-type-generic').value;
      if (selectedIdentity) {
        identityId = selectedIdentity.id || selectedIdentity.identity_id || '';
        auth.type = 'identity';
        auth.identity = identityId;
        additionalFields.identity_auth_type = this.getIdentityAuthType(selectedIdentity);
      } else {
        auth.type = authType;

        if (authType === 'key') {
          auth.key = document.getElementById('plugin-auth-key').value.trim();
        } else if (authType === 'identity') {
          auth.identity = document.getElementById('plugin-auth-identity').value.trim();
        } else if (authType === 'servicePrincipal') {
          auth.identity = document.getElementById('plugin-auth-identity').value.trim();
          auth.key = document.getElementById('plugin-auth-key').value.trim();
          auth.tenantId = document.getElementById('plugin-auth-tenant-id').value.trim();
        }
      }
    }

    // Collect additional fields from the dynamic UI and MERGE with existing additionalFields
    // This preserves OpenAPI spec content and other auto-populated fields
    // For SQL types, Step 3 already provides all necessary config — skip dynamic field merge
    // to prevent empty Step 4 fields from overwriting populated Step 3 values
    if (!this.isStructuredConfigType()) {
      try {
        const dynamicFields = this.collectAdditionalFields();
        // Merge dynamicFields into additionalFields (preserving existing values)
        additionalFields = { ...additionalFields, ...dynamicFields };
      } catch (e) {
        throw new Error('Invalid additional fields input');
      }
    }

    let metadata = {};
    try {
      const metadataValue = document.getElementById('plugin-metadata').value.trim();
      metadata = metadataValue ? JSON.parse(metadataValue) : {};
    } catch (e) {
      throw new Error('Invalid metadata JSON');
    }

    const formData = {
      name: document.getElementById('plugin-name').value.trim(),
      displayName: document.getElementById('plugin-display-name').value.trim(),
      type: this.selectedType,
      description: document.getElementById('plugin-description').value.trim(),
      endpoint,
      auth,
      metadata,
      additionalFields
    };

    if (identityId) {
      formData.identity_id = identityId;
    }

    return formData;
  }

  generateActionName(displayName) {
    // Convert display name to a valid action name
    return displayName
      .toLowerCase()                 // Convert to lowercase
      .replace(/[^a-z0-9\s]/g, '')  // Remove special characters except spaces
      .replace(/\s+/g, '_')         // Replace spaces with underscores
      .replace(/_+/g, '_')          // Replace multiple underscores with single
      .replace(/^_|_$/g, '');       // Remove leading and trailing underscores
  }

  populateSummary() {
    // Get all form values
    const displayName = document.getElementById('plugin-display-name').value.trim();
    const generatedName = document.getElementById('plugin-name').value.trim();
    const description = document.getElementById('plugin-description').value.trim();
    const type = this.selectedType || '-';

    // Basic Information Section
    document.getElementById('summary-plugin-display-name').textContent = displayName || '-';
    document.getElementById('summary-plugin-name').textContent = generatedName || '-';
    document.getElementById('summary-plugin-type').textContent = type;
    document.getElementById('summary-plugin-description').textContent = description || '-';

    // Configuration Section - Handle endpoint vs SQL/Cosmos configuration
    const isSqlType = this.isSqlType();
    const isCosmosType = this.isCosmosType();
    const isDocumentSearchType = this.isDocumentSearchType();
    const isBlobStorageType = this.isBlobStorageType();
    const isDatabricksType = this.isDatabricksType();
    const isSnowflakeType = this.isSnowflakeType();
    const isTableauType = this.isTableauType();
    const isMcpType = this.isMcpType();
    const isSimpleChatType = this.isSimpleChatType();
    const isMsGraphType = this.isMsGraphType();
    const isAzureMapsType = this.isAzureMapsType();
    const isChartType = this.isChartType();

    const endpointRow = document.getElementById('summary-plugin-endpoint-row');
    const databaseTypeRow = document.getElementById('summary-plugin-database-type-row');

    if (isSqlType) {
      // Hide endpoint for SQL plugins since they don't use endpoints
      endpointRow.style.display = 'none';
      document.getElementById('summary-plugin-database-type').textContent = this.getSqlDatabaseType() || '-';
      databaseTypeRow.style.display = '';
    } else if (isCosmosType) {
      const endpoint = this.getEndpointValue();
      document.getElementById('summary-plugin-endpoint').textContent = endpoint || '-';
      endpointRow.style.display = '';
      document.getElementById('summary-plugin-database-type').textContent = 'Cosmos DB for NoSQL';
      databaseTypeRow.style.display = '';
    } else if (isDocumentSearchType) {
      endpointRow.style.display = 'none';
      document.getElementById('summary-plugin-database-type').textContent = 'Internal document search';
      databaseTypeRow.style.display = '';
    } else if (isBlobStorageType) {
      const endpoint = this.getEndpointValue();
      document.getElementById('summary-plugin-endpoint').textContent = endpoint || '-';
      endpointRow.style.display = '';
      document.getElementById('summary-plugin-database-type').textContent = 'Azure Blob Storage container';
      databaseTypeRow.style.display = '';
    } else if (isDatabricksType) {
      const endpoint = this.getEndpointValue();
      document.getElementById('summary-plugin-endpoint').textContent = endpoint || '-';
      endpointRow.style.display = '';
      document.getElementById('summary-plugin-database-type').textContent = 'Azure Commercial Databricks SQL Warehouse';
      databaseTypeRow.style.display = '';
    } else if (isSnowflakeType) {
      endpointRow.style.display = 'none';
      document.getElementById('summary-plugin-database-type').textContent = 'Snowflake data warehouse';
      databaseTypeRow.style.display = '';
    } else if (isTableauType) {
      const endpoint = this.getEndpointValue();
      document.getElementById('summary-plugin-endpoint').textContent = endpoint || '-';
      endpointRow.style.display = '';
      document.getElementById('summary-plugin-database-type').textContent = 'Tableau Server or Tableau Cloud';
      databaseTypeRow.style.display = '';
    } else if (isMcpType) {
      const endpoint = this.getEndpointValue();
      document.getElementById('summary-plugin-endpoint').textContent = endpoint || '-';
      endpointRow.style.display = '';
      document.getElementById('summary-plugin-database-type').textContent = 'Model Context Protocol server';
      databaseTypeRow.style.display = '';
    } else if (isSimpleChatType) {
      endpointRow.style.display = 'none';
      document.getElementById('summary-plugin-database-type').textContent = 'Built-in SimpleChat action';
      databaseTypeRow.style.display = '';
    } else if (isMsGraphType) {
      endpointRow.style.display = 'none';
      document.getElementById('summary-plugin-database-type').textContent = 'Built-in Microsoft Graph action';
      databaseTypeRow.style.display = '';
    } else if (isAzureMapsType) {
      endpointRow.style.display = 'none';
      document.getElementById('summary-plugin-database-type').textContent = 'Azure Maps tile proxy';
      databaseTypeRow.style.display = '';
    } else if (isChartType) {
      endpointRow.style.display = 'none';
      document.getElementById('summary-plugin-database-type').textContent = 'Built-in chart action';
      databaseTypeRow.style.display = '';
    } else {
      // Show endpoint for non-SQL plugins (OpenAPI, generic, etc.)
      const endpoint = this.getEndpointValue();
      document.getElementById('summary-plugin-endpoint').textContent = endpoint || '-';
      endpointRow.style.display = '';
      databaseTypeRow.style.display = 'none';
    }

    const authType = this.getAuthTypeValue();
    document.getElementById('summary-plugin-auth').textContent = authType || 'None';

    // Connection method and database type (for SQL plugins)
    const connectionMethod = this.getSqlConnectionMethod();
    const connectionMethodRow = document.getElementById('summary-plugin-connection-method-row');
    if (connectionMethod) {
      document.getElementById('summary-plugin-connection-method').textContent = connectionMethod;
      connectionMethodRow.style.display = '';
    } else {
      connectionMethodRow.style.display = 'none';
    }

    const databaseType = this.getSqlDatabaseType();
    if (!isSqlType && !isCosmosType && !isDocumentSearchType && !isBlobStorageType && !isDatabricksType && !isSnowflakeType && !isTableauType && !isMcpType && !isSimpleChatType && !isMsGraphType && !isAzureMapsType && !isChartType && databaseType) {
      document.getElementById('summary-plugin-database-type').textContent = databaseType;
      databaseTypeRow.style.display = '';
    } else if (!isSqlType && !isCosmosType && !isDocumentSearchType && !isBlobStorageType && !isDatabricksType && !isSnowflakeType && !isTableauType && !isMcpType && !isSimpleChatType && !isMsGraphType && !isAzureMapsType && !isChartType) {
      databaseTypeRow.style.display = 'none';
    }

    // Show/hide type-specific sections
    this.populateOpenApiSummary();
    this.populateSqlSummary();
    this.populateCosmosSummary();
    this.populateDocumentSearchSummary();
    this.populateBlobStorageSummary();
    this.populateDatabricksSummary();
    this.populateSnowflakeSummary();
    this.populateTableauSummary();
    this.populateMcpSummary();
    this.populateSimpleChatSummary();
    this.populateMsGraphSummary();
    this.populateChartSummary();
    this.populateAdvancedSummary();
    this.populateChangesSummary();
  }

  getEndpointValue() {
    // Check different endpoint fields based on plugin type
    const isOpenApiType = this.isOpenApiType();
    const isSqlType = this.isSqlType();
    const isCosmosType = this.isCosmosType();
    const isDocumentSearchType = this.isDocumentSearchType();
    const isBlobStorageType = this.isBlobStorageType();
    const isDatabricksType = this.isDatabricksType();
    const isSnowflakeType = this.isSnowflakeType();
    const isTableauType = this.isTableauType();
    const isMcpType = this.isMcpType();
    const isSimpleChatType = this.isSimpleChatType();
    const isMsGraphType = this.isMsGraphType();
    const isAzureMapsType = this.isAzureMapsType();
    const isChartType = this.isChartType();

    if (isOpenApiType) {
      return document.getElementById('plugin-endpoint').value.trim();
    } else if (isSqlType) {
      return document.getElementById('sql-connection-string').value.trim();
    } else if (isCosmosType) {
      return document.getElementById('cosmos-endpoint').value.trim();
    } else if (isDocumentSearchType) {
      return INTERNAL_DOCUMENT_SEARCH_ENDPOINT;
    } else if (isBlobStorageType) {
      const connectionString = document.getElementById('blob-storage-connection-string').value.trim();
      return this.deriveBlobStorageEndpointFromConnectionString(connectionString) || this.originalPlugin?.endpoint || '';
    } else if (isDatabricksType) {
      return this.normalizeDatabricksWorkspaceUrl(document.getElementById('databricks-workspace-url')?.value || '');
    } else if (isSnowflakeType) {
      return SNOWFLAKE_DEFAULT_ENDPOINT;
    } else if (isTableauType) {
      return this.normalizeTableauServerUrl(document.getElementById('tableau-server-url')?.value || '');
    } else if (isMcpType) {
      const transport = document.getElementById('mcp-transport')?.value || 'streamable_http';
      return transport === 'stdio' ? MCP_STDIO_ENDPOINT : document.getElementById('mcp-endpoint').value.trim();
    } else if (isAzureMapsType) {
      return AZURE_MAPS_DEFAULT_ENDPOINT;
    } else if (isMsGraphType) {
      return MSGRAPH_DEFAULT_ENDPOINT;
    } else if (isChartType) {
      return CHART_DEFAULT_ENDPOINT;
    } else {
      return document.getElementById('plugin-endpoint-generic').value.trim();
    }
  }

  getAuthTypeValue() {
    // Check different auth fields based on plugin type
    const isOpenApiType = this.isOpenApiType();
    const isSqlType = this.isSqlType();
    const isCosmosType = this.isCosmosType();
    const isDocumentSearchType = this.isDocumentSearchType();
    const isBlobStorageType = this.isBlobStorageType();
    const isDatabricksType = this.isDatabricksType();
    const isSnowflakeType = this.isSnowflakeType();
    const isTableauType = this.isTableauType();
    const isMcpType = this.isMcpType();
    const isSimpleChatType = this.isSimpleChatType();
    const isMsGraphType = this.isMsGraphType();
    const isAzureMapsType = this.isAzureMapsType();
    const isChartType = this.isChartType();

    if (isOpenApiType) {
      const authType = document.getElementById('plugin-auth-type').value;
      return this.formatAuthType(authType);
    } else if (isSqlType) {
      const authType = document.getElementById('sql-auth-type').value;
      return this.formatAuthType(authType);
    } else if (isCosmosType) {
      const authType = document.getElementById('cosmos-auth-type')?.value || 'identity';
      return authType === 'key' ? 'Account Key' : 'Managed Identity';
    } else if (isDocumentSearchType) {
      return 'Internal user context';
    } else if (isBlobStorageType) {
      return 'Connection String';
    } else if (isDatabricksType) {
      if (this.getSelectedActionIdentity('databricks')) {
        return 'Reusable Identity';
      }
      return this.formatAuthType(document.getElementById('databricks-auth-method')?.value || 'pat');
    } else if (isSnowflakeType) {
      if (this.getSelectedActionIdentity('snowflake')) {
        return 'Reusable Identity';
      }
      return this.formatAuthType(document.getElementById('snowflake-auth-method')?.value || SNOWFLAKE_AUTH_METHOD_PASSWORD);
    } else if (isTableauType) {
      if (this.getSelectedActionIdentity('tableau')) {
        return 'Reusable Identity';
      }
      return this.formatTableauAuthMethod(document.getElementById('tableau-auth-method')?.value || TABLEAU_AUTH_METHOD_PAT);
    } else if (isMcpType) {
      if (this.getSelectedActionIdentity('mcp')) {
        return 'Reusable Identity';
      }
      return this.formatAuthType(document.getElementById('mcp-auth-method')?.value || 'none');
    } else if (isSimpleChatType) {
      return 'User';
    } else if (isMsGraphType) {
      return 'User';
    } else if (isAzureMapsType) {
      return 'Subscription Key';
    } else if (isChartType) {
      return 'User';
    } else {
      const authType = document.getElementById('plugin-auth-type-generic').value;
      return this.formatAuthType(authType);
    }
  }

  formatAuthType(authType) {
    const authTypeMap = {
      'none': 'No Authentication',
      'api_key': 'API Key',
      'bearer': 'Bearer Token',
      'oauth2': 'OAuth2',
      'windows': 'Windows Authentication',
      'sql': 'SQL Authentication',
      'username_password': 'Username/Password',
      'key': 'Key',
      'identity': 'Identity',
      'user': 'User',
      'servicePrincipal': 'Service Principal',
      'connection_string': 'Connection String',
      'connection_string_only': 'Connection String Only',
      'managed_identity': 'Managed Identity',
      'integrated': 'Integrated Authentication',
      'basic': 'Basic',
      'NoAuth': 'No Authentication',
      'pat': 'Personal Access Token',
      'personal_access_token': 'Personal Access Token',
      'bearer': 'Bearer Token',
      'service_principal': 'Service Principal',
      'password': 'Password',
      'key_pair': 'Key Pair',
      'oauth': 'OAuth Token'
    };
    return authTypeMap[authType] || authType;
  }

  getSqlConnectionMethod() {
    const methodRadio = document.querySelector('input[name="sql-connection-method"]:checked');
    return methodRadio ? methodRadio.value : null;
  }

  getSqlDatabaseType() {
    const typeRadio = document.querySelector('input[name="sql-database-type"]:checked');
    return typeRadio ? typeRadio.value : null;
  }

  populateOpenApiSummary() {
    const isOpenApiType = this.selectedType && this.selectedType.toLowerCase().includes('openapi');
    const openApiSection = document.getElementById('summary-openapi-section');

    if (isOpenApiType) {
      const fileInput = document.getElementById('plugin-openapi-file');
      let fileName;

      if (fileInput.files.length > 0) {
        // New file uploaded
        fileName = fileInput.files[0].name;
      } else if (fileInput.dataset.fileId && fileInput.dataset.specContent) {
        // Using existing specification (editing mode)
        fileName = 'No changes (using existing specification)';
      } else {
        // No file at all
        fileName = '-';
      }

      document.getElementById('summary-openapi-file').textContent = fileName;

      // Show API info if available
      const infoElement = document.getElementById('openapi-info-content');
      if (infoElement && infoElement.textContent.trim()) {
        document.getElementById('summary-openapi-info').textContent = infoElement.textContent;
        document.getElementById('summary-openapi-info-row').style.display = '';
      } else {
        document.getElementById('summary-openapi-info-row').style.display = 'none';
      }

      openApiSection.style.display = '';
    } else {
      openApiSection.style.display = 'none';
    }
  }

  populateSqlSummary() {
    const isSqlType = this.isSqlType();
    const sqlSection = document.getElementById('summary-sql-section');

    if (isSqlType) {
      // SQL Plugin Type
      const pluginTypeRadio = document.querySelector('input[name="sql-plugin-type"]:checked');
      const pluginType = pluginTypeRadio ? pluginTypeRadio.value : '-';
      document.getElementById('summary-sql-plugin-type').textContent = pluginType;

      // Optional SQL settings
      this.populateSqlOptionalSetting('sql-read-only-checkbox', 'summary-sql-read-only', 'summary-sql-read-only-row');
      this.populateSqlOptionalSetting('sql-max-rows', 'summary-sql-max-rows', 'summary-sql-max-rows-row');
      this.populateSqlOptionalSetting('sql-timeout', 'summary-sql-timeout', 'summary-sql-timeout-row');
      this.populateSqlOptionalSetting('sql-include-system-checkbox', 'summary-sql-include-system', 'summary-sql-include-system-row');

      sqlSection.style.display = '';
    } else {
      sqlSection.style.display = 'none';
    }
  }

  populateCosmosSummary() {
    const cosmosSection = document.getElementById('summary-cosmos-section');
    if (!cosmosSection) {
      return;
    }

    if (this.isCosmosType()) {
      const fieldHints = this.getCosmosFieldHints();
      document.getElementById('summary-cosmos-auth-type').textContent = this.getAuthTypeValue() || '-';
      document.getElementById('summary-cosmos-database-name').textContent = document.getElementById('cosmos-database-name').value.trim() || '-';
      document.getElementById('summary-cosmos-container-name').textContent = document.getElementById('cosmos-container-name').value.trim() || '-';
      document.getElementById('summary-cosmos-partition-key-path').textContent = document.getElementById('cosmos-partition-key-path').value.trim() || '-';
      document.getElementById('summary-cosmos-max-items').textContent = document.getElementById('cosmos-max-items').value.trim() || '-';

      const timeoutValue = document.getElementById('cosmos-timeout').value.trim();
      document.getElementById('summary-cosmos-timeout').textContent = timeoutValue ? `${timeoutValue} seconds` : '-';
      document.getElementById('summary-cosmos-field-hints').textContent = fieldHints.length ? fieldHints.join(', ') : 'None configured';
      cosmosSection.style.display = '';
    } else {
      cosmosSection.style.display = 'none';
    }
  }

  populateDocumentSearchSummary() {
    const searchSection = document.getElementById('summary-document-search-section');
    if (!searchSection) {
      return;
    }

    if (!this.isDocumentSearchType()) {
      searchSection.style.display = 'none';
      return;
    }

    const config = this.getDocumentSearchAdditionalFields();
    document.getElementById('summary-search-scope').textContent = this.formatDocumentScope(config.default_doc_scope);
    document.getElementById('summary-search-top-n').textContent = String(config.default_top_n || 12);
    document.getElementById('summary-search-chunk-behavior').textContent = 'Returns all chunks by default';
    document.getElementById('summary-search-windowing').textContent = this.formatDocumentSearchWindowing(config);
    document.getElementById('summary-search-window-target-length').textContent = config.default_window_target_length || '2 pages';
    document.getElementById('summary-search-final-target-length').textContent = config.default_final_target_length || '2 pages';
    document.getElementById('summary-search-focus-instructions').textContent = config.default_focus_instructions || 'Uses caller-provided focus instructions';
    searchSection.style.display = '';
  }

  populateBlobStorageSummary() {
    const blobSection = document.getElementById('summary-blob-storage-section');
    if (!blobSection) {
      return;
    }

    if (!this.isBlobStorageType()) {
      blobSection.style.display = 'none';
      return;
    }

    const capabilities = this.getSelectedBlobStorageCapabilities();
    const readFileTypes = this.getSelectedBlobStorageReadFileTypes();
    const uploadFileTypes = this.getSelectedBlobStorageUploadFileTypes();
    const enabledLabels = [];
    const disabledLabels = [];
    const enabledReadTypes = [];
    const enabledUploadTypes = [];

    BLOB_STORAGE_CAPABILITY_DEFINITIONS.forEach(definition => {
      if (capabilities[definition.key]) {
        enabledLabels.push(definition.label);
      } else {
        disabledLabels.push(definition.label);
      }
    });

    BLOB_STORAGE_FILE_TYPE_DEFINITIONS.forEach(definition => {
      if (readFileTypes[definition.key]) {
        enabledReadTypes.push(definition.label);
      }
      if (uploadFileTypes[definition.key]) {
        enabledUploadTypes.push(definition.label);
      }
    });

    document.getElementById('summary-blob-storage-container-name').textContent = document.getElementById('blob-storage-container-name').value.trim() || '-';
    document.getElementById('summary-blob-storage-blob-prefix').textContent = this.normalizeBlobStoragePrefix(document.getElementById('blob-storage-blob-prefix').value) || 'None';
    document.getElementById('summary-blob-storage-enabled-list').textContent = enabledLabels.length ? enabledLabels.join(', ') : 'None';
    document.getElementById('summary-blob-storage-disabled-list').textContent = disabledLabels.length ? disabledLabels.join(', ') : 'None';
    document.getElementById('summary-blob-storage-read-file-types').textContent = capabilities.read_file_content
      ? (enabledReadTypes.length ? enabledReadTypes.join(', ') : 'None')
      : 'Read capability disabled';
    document.getElementById('summary-blob-storage-upload-file-types').textContent = capabilities.upload_file_to_container
      ? (enabledUploadTypes.length ? enabledUploadTypes.join(', ') : 'None')
      : 'Upload capability disabled';
    blobSection.style.display = '';
  }

  populateDatabricksSummary() {
    const databricksSection = document.getElementById('summary-databricks-section');
    if (!databricksSection) {
      return;
    }

    if (!this.isDatabricksType()) {
      databricksSection.classList.add('d-none');
      return;
    }

    const catalog = document.getElementById('databricks-catalog')?.value.trim() || '';
    const schema = document.getElementById('databricks-schema')?.value.trim() || '';
    const namespace = [catalog, schema].filter(Boolean).join('.') || 'No default catalog/schema';

    document.getElementById('summary-databricks-cloud').textContent = 'Azure Commercial';
    document.getElementById('summary-databricks-warehouse-id').textContent = document.getElementById('databricks-warehouse-id')?.value.trim() || '-';
    document.getElementById('summary-databricks-namespace').textContent = namespace;
    document.getElementById('summary-databricks-max-rows').textContent = document.getElementById('databricks-max-rows')?.value.trim() || '1000';
    document.getElementById('summary-databricks-timeout').textContent = `${document.getElementById('databricks-timeout')?.value || '30'} seconds`;
    document.getElementById('summary-databricks-wait-timeout').textContent = `${document.getElementById('databricks-wait-timeout')?.value || '30'} seconds`;
    databricksSection.classList.remove('d-none');
  }

  populateSnowflakeSummary() {
    const snowflakeSection = document.getElementById('summary-snowflake-section');
    if (!snowflakeSection) {
      return;
    }

    if (!this.isSnowflakeType()) {
      snowflakeSection.classList.add('d-none');
      return;
    }

    const database = document.getElementById('snowflake-database')?.value.trim() || '';
    const schema = document.getElementById('snowflake-schema')?.value.trim() || '';
    const namespace = [database, schema].filter(Boolean).join('.') || 'No default database/schema';
    const selectedIdentity = this.getSelectedActionIdentity('snowflake');
    const authMethod = selectedIdentity
      ? this.getSnowflakeIdentityAuthMethod(selectedIdentity)
      : (document.getElementById('snowflake-auth-method')?.value || SNOWFLAKE_AUTH_METHOD_PASSWORD);

    document.getElementById('summary-snowflake-account').textContent = this.normalizeSnowflakeAccount(document.getElementById('snowflake-account')?.value || '') || '-';
    document.getElementById('summary-snowflake-user').textContent = document.getElementById('snowflake-user')?.value.trim() || (selectedIdentity ? 'From reusable identity' : '-');
    document.getElementById('summary-snowflake-auth-method').textContent = selectedIdentity
      ? `Reusable Identity (${this.formatAuthType(authMethod)})`
      : this.formatAuthType(authMethod);
    document.getElementById('summary-snowflake-warehouse').textContent = document.getElementById('snowflake-warehouse')?.value.trim() || '-';
    document.getElementById('summary-snowflake-namespace').textContent = namespace;
    document.getElementById('summary-snowflake-role').textContent = document.getElementById('snowflake-role')?.value.trim() || 'Default role';
    document.getElementById('summary-snowflake-max-rows').textContent = document.getElementById('snowflake-max-rows')?.value.trim() || '1000';
    document.getElementById('summary-snowflake-timeout').textContent = `${document.getElementById('snowflake-timeout')?.value || '30'} seconds`;
    document.getElementById('summary-snowflake-login-timeout').textContent = `${document.getElementById('snowflake-login-timeout')?.value || '30'} seconds`;
    snowflakeSection.classList.remove('d-none');
  }

  populateTableauSummary() {
    const tableauSection = document.getElementById('summary-tableau-section');
    if (!tableauSection) {
      return;
    }

    if (!this.isTableauType()) {
      tableauSection.classList.add('d-none');
      return;
    }

    const siteContentUrl = document.getElementById('tableau-site-content-url')?.value.trim() || 'Default site';
    const selectedIdentity = this.getSelectedActionIdentity('tableau');
    const authMethod = selectedIdentity
      ? this.getTableauIdentityAuthMethod(selectedIdentity)
      : (document.getElementById('tableau-auth-method')?.value || TABLEAU_AUTH_METHOD_PAT);

    document.getElementById('summary-tableau-site-content-url').textContent = siteContentUrl;
    document.getElementById('summary-tableau-auth-method').textContent = selectedIdentity
      ? `Reusable Identity (${this.formatTableauAuthMethod(authMethod)})`
      : this.formatTableauAuthMethod(authMethod);
    document.getElementById('summary-tableau-page-size').textContent = document.getElementById('tableau-page-size')?.value.trim() || '100';
    document.getElementById('summary-tableau-max-results').textContent = document.getElementById('tableau-max-results')?.value.trim() || '100';
    document.getElementById('summary-tableau-timeout').textContent = `${document.getElementById('tableau-timeout')?.value || '30'} seconds`;
    document.getElementById('summary-tableau-use-server-version').textContent = document.getElementById('tableau-use-server-version')?.checked === false ? 'No' : 'Yes';
    tableauSection.classList.remove('d-none');
  }

  populateMcpSummary() {
    const mcpSection = document.getElementById('summary-mcp-section');
    if (!mcpSection) {
      return;
    }

    if (!this.isMcpType()) {
      mcpSection.classList.add('d-none');
      return;
    }

    const transport = document.getElementById('mcp-transport')?.value || 'streamable_http';
    const loadTools = Boolean(document.getElementById('mcp-load-tools')?.checked);
    const loadPrompts = Boolean(document.getElementById('mcp-load-prompts')?.checked);
    const loadModes = [];
    if (loadTools) {
      loadModes.push('Tools');
    }
    if (loadPrompts) {
      loadModes.push('Prompts');
    }

    const allowedToolNames = this.parseTextareaLines('mcp-tool-names');
    let toolMetadataCount = 0;
    try {
      toolMetadataCount = this.parseJsonArrayField('mcp-tool-metadata', 'Discovered Tool Metadata', []).length;
    } catch (error) {
      toolMetadataCount = 0;
    }

    document.getElementById('summary-mcp-transport').textContent = this.formatMcpTransport(transport);
    document.getElementById('summary-mcp-load-mode').textContent = loadModes.length ? loadModes.join(', ') : 'None';
    document.getElementById('summary-mcp-request-timeout').textContent = `${document.getElementById('mcp-request-timeout')?.value || '30'} seconds`;
    document.getElementById('summary-mcp-connect-timeout').textContent = `${document.getElementById('mcp-connect-timeout')?.value || '10'} seconds`;
    document.getElementById('summary-mcp-tool-names').textContent = allowedToolNames.length ? allowedToolNames.join(', ') : 'All discovered tools';
    document.getElementById('summary-mcp-tool-metadata').textContent = `${toolMetadataCount} cached tool${toolMetadataCount === 1 ? '' : 's'}`;
    mcpSection.classList.remove('d-none');
  }

  populateSimpleChatSummary() {
    const simpleChatSection = document.getElementById('summary-simplechat-section');
    const enabledList = document.getElementById('summary-simplechat-enabled-list');
    const disabledList = document.getElementById('summary-simplechat-disabled-list');
    if (!simpleChatSection || !enabledList || !disabledList) {
      return;
    }

    if (!this.isSimpleChatType()) {
      simpleChatSection.style.display = 'none';
      return;
    }

    const capabilities = this.getSelectedSimpleChatCapabilities();
    const enabledLabels = [];
    const disabledLabels = [];

    SIMPLECHAT_CAPABILITY_DEFINITIONS.forEach(definition => {
      if (capabilities[definition.key]) {
        enabledLabels.push(definition.label);
      } else {
        disabledLabels.push(definition.label);
      }
    });

    enabledList.textContent = enabledLabels.length ? enabledLabels.join(', ') : 'None';
    disabledList.textContent = disabledLabels.length ? disabledLabels.join(', ') : 'None';
    simpleChatSection.style.display = '';
  }

  populateMsGraphSummary() {
    const msGraphSection = document.getElementById('summary-msgraph-section');
    const enabledList = document.getElementById('summary-msgraph-enabled-list');
    const disabledList = document.getElementById('summary-msgraph-disabled-list');
    if (!msGraphSection || !enabledList || !disabledList) {
      return;
    }

    if (!this.isMsGraphType()) {
      msGraphSection.style.display = 'none';
      return;
    }

    const capabilities = this.getSelectedMsGraphCapabilities();
    const enabledLabels = [];
    const disabledLabels = [];

    MSGRAPH_CAPABILITY_DEFINITIONS.forEach(definition => {
      if (capabilities[definition.key]) {
        enabledLabels.push(definition.label);
      } else {
        disabledLabels.push(definition.label);
      }
    });

    enabledList.textContent = enabledLabels.length ? enabledLabels.join(', ') : 'None';
    disabledList.textContent = disabledLabels.length ? disabledLabels.join(', ') : 'None';

    const mailConfig = this.getMsGraphMailSendConfiguration();
    const mailModeRow = document.getElementById('summary-msgraph-mail-mode-row');
    const modeElement = document.getElementById('summary-msgraph-mail-send-mode');
    const delayElement = document.getElementById('summary-msgraph-mail-delay-seconds');
    const delayRow = document.getElementById('summary-msgraph-mail-delay-row');
    const mailEnabled = Boolean(capabilities.send_mail);
    if (mailModeRow) {
      mailModeRow.classList.toggle('d-none', !mailEnabled);
    }
    if (modeElement) {
      modeElement.textContent = this.formatMsGraphMailSendMode(mailConfig.msgraph_mail_send_mode);
    }
    if (delayElement) {
      delayElement.textContent = `${mailConfig.msgraph_mail_delay_seconds} seconds`;
    }
    if (delayRow) {
      delayRow.classList.toggle('d-none', !mailEnabled || mailConfig.msgraph_mail_send_mode !== MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED);
    }

    const calendarConfig = this.getMsGraphCalendarSendConfiguration();
    const calendarModeRow = document.getElementById('summary-msgraph-calendar-mode-row');
    const calendarModeElement = document.getElementById('summary-msgraph-calendar-send-mode');
    const calendarDelayElement = document.getElementById('summary-msgraph-calendar-delay-seconds');
    const calendarDelayRow = document.getElementById('summary-msgraph-calendar-delay-row');
    const calendarEnabled = Boolean(capabilities.create_calendar_invite);
    if (calendarModeRow) {
      calendarModeRow.classList.toggle('d-none', !calendarEnabled);
    }
    if (calendarModeElement) {
      calendarModeElement.textContent = this.formatMsGraphCalendarSendMode(calendarConfig.msgraph_calendar_send_mode);
    }
    if (calendarDelayElement) {
      calendarDelayElement.textContent = `${calendarConfig.msgraph_calendar_delay_seconds} seconds`;
    }
    if (calendarDelayRow) {
      calendarDelayRow.classList.toggle('d-none', !calendarEnabled || calendarConfig.msgraph_calendar_send_mode !== MSGRAPH_MAIL_SEND_MODE_DRAFT_DELAYED);
    }
    msGraphSection.style.display = '';
  }

  populateChartSummary() {
    const chartSection = document.getElementById('summary-chart-section');
    const enabledList = document.getElementById('summary-chart-enabled-list');
    const disabledList = document.getElementById('summary-chart-disabled-list');
    if (!chartSection || !enabledList || !disabledList) {
      return;
    }

    if (!this.isChartType()) {
      chartSection.style.display = 'none';
      return;
    }

    const capabilities = this.getSelectedChartCapabilities();
    const enabledLabels = [];
    const disabledLabels = [];

    CHART_CAPABILITY_DEFINITIONS.forEach(definition => {
      if (capabilities[definition.key]) {
        enabledLabels.push(definition.label);
      } else {
        disabledLabels.push(definition.label);
      }
    });

    enabledList.textContent = enabledLabels.length ? enabledLabels.join(', ') : 'None';
    disabledList.textContent = disabledLabels.length ? disabledLabels.join(', ') : 'None';
    chartSection.style.display = '';
  }

  populateSqlOptionalSetting(inputId, summaryId, rowId) {
    const input = document.getElementById(inputId);
    const summaryElement = document.getElementById(summaryId);
    const rowElement = document.getElementById(rowId);

    if (input && summaryElement && rowElement) {
      let value = '';
      if (input.type === 'checkbox') {
        value = input.checked ? 'Yes' : 'No';
        if (input.checked) {
          summaryElement.textContent = value;
          rowElement.style.display = '';
        } else {
          rowElement.style.display = 'none';
        }
      } else {
        value = input.value.trim();
        if (value) {
          summaryElement.textContent = value + (inputId.includes('timeout') ? ' seconds' : '');
          rowElement.style.display = '';
        } else {
          rowElement.style.display = 'none';
        }
      }
    }
  }

  detectChanges() {
    if (!this.isEditMode || !this.originalPlugin) {
      return null;
    }

    const changes = {};

    try {
      // Get current form values directly instead of using getFormData()
      // which might fail due to validation requirements
      const currentDisplayName = document.getElementById('plugin-display-name')?.value || '';
      const currentName = document.getElementById('plugin-name')?.value || '';
      const currentDescription = document.getElementById('plugin-description')?.value || '';

      // Get endpoint from the appropriate field based on plugin type
      let currentEndpoint = '';
      const isOpenApiType = this.isOpenApiType();
      const isSqlType = this.isSqlType();
      const isCosmosType = this.isCosmosType();
      const isDocumentSearchType = this.isDocumentSearchType();
      const isDatabricksType = this.isDatabricksType();
      const isTableauType = this.isTableauType();
      const isMcpType = this.isMcpType();
      const isSimpleChatType = this.isSimpleChatType();
      const isMsGraphType = this.isMsGraphType();
      const isAzureMapsType = this.isAzureMapsType();
      const isChartType = this.isChartType();

      if (isOpenApiType) {
        currentEndpoint = document.getElementById('plugin-endpoint')?.value || '';
      } else if (isSqlType) {
        currentEndpoint = document.getElementById('sql-connection-string')?.value || '';
      } else if (isCosmosType) {
        currentEndpoint = document.getElementById('cosmos-endpoint')?.value || '';
      } else if (isDocumentSearchType) {
        currentEndpoint = INTERNAL_DOCUMENT_SEARCH_ENDPOINT;
      } else if (isDatabricksType) {
        currentEndpoint = this.normalizeDatabricksWorkspaceUrl(document.getElementById('databricks-workspace-url')?.value || '');
      } else if (isTableauType) {
        currentEndpoint = this.normalizeTableauServerUrl(document.getElementById('tableau-server-url')?.value || '');
      } else if (isMcpType) {
        currentEndpoint = this.getEndpointValue();
      } else if (isSimpleChatType) {
        currentEndpoint = '';
      } else if (isMsGraphType) {
        currentEndpoint = MSGRAPH_DEFAULT_ENDPOINT;
      } else if (isAzureMapsType) {
        currentEndpoint = AZURE_MAPS_DEFAULT_ENDPOINT;
      } else if (isChartType) {
        currentEndpoint = CHART_DEFAULT_ENDPOINT;
      } else {
        currentEndpoint = document.getElementById('plugin-endpoint-generic')?.value || '';
      }

      // Get authentication information
      let currentAuthKey = '';
      let currentAuthType = '';
      if (isOpenApiType) {
        const authType = document.getElementById('plugin-auth-type')?.value || 'none';
        currentAuthType = authType;
        if (authType === 'api_key') {
          currentAuthKey = document.getElementById('plugin-auth-api-key-value')?.value || '';
        } else if (authType === 'bearer') {
          currentAuthKey = document.getElementById('plugin-auth-bearer-token')?.value || '';
        } else if (authType === 'basic') {
          const username = document.getElementById('plugin-auth-basic-username')?.value || '';
          const password = document.getElementById('plugin-auth-basic-password')?.value || '';
          currentAuthKey = username || password ? `${username}:${password}` : '';
        } else if (authType === 'oauth2') {
          currentAuthKey = document.getElementById('plugin-auth-oauth2-token')?.value || '';
        }
      } else if (isCosmosType) {
        currentAuthType = document.getElementById('cosmos-auth-type')?.value || 'identity';
        if (currentAuthType === 'key') {
          currentAuthKey = document.getElementById('cosmos-auth-key')?.value || '';
        }
      } else if (isDocumentSearchType) {
        currentAuthType = 'NoAuth';
      } else if (isTableauType) {
        const selectedIdentity = this.getSelectedActionIdentity('tableau');
        currentAuthType = selectedIdentity ? 'identity' : (document.getElementById('tableau-auth-method')?.value || TABLEAU_AUTH_METHOD_PAT);
        if (!selectedIdentity && currentAuthType === TABLEAU_AUTH_METHOD_PAT) {
          currentAuthKey = document.getElementById('tableau-pat-secret')?.value || '';
        } else if (!selectedIdentity && currentAuthType === TABLEAU_AUTH_METHOD_USERNAME_PASSWORD) {
          currentAuthKey = document.getElementById('tableau-password')?.value || '';
        }
      } else if (isMcpType) {
        const selectedIdentity = this.getSelectedActionIdentity('mcp');
        currentAuthType = selectedIdentity ? 'identity' : (document.getElementById('mcp-auth-method')?.value || 'none');
        if (!selectedIdentity && currentAuthType === 'bearer') {
          currentAuthKey = document.getElementById('mcp-bearer-token')?.value || '';
        } else if (!selectedIdentity && currentAuthType === 'api_key') {
          currentAuthKey = document.getElementById('mcp-api-key-value')?.value || '';
        } else if (!selectedIdentity && currentAuthType === 'basic') {
          currentAuthKey = document.getElementById('mcp-basic-password')?.value || '';
        }
      } else if (isSimpleChatType) {
        currentAuthType = 'user';
      } else if (isMsGraphType) {
        currentAuthType = 'user';
      } else if (isAzureMapsType) {
        currentAuthType = 'key';
        currentAuthKey = document.getElementById('azure-maps-key')?.value || '';
      } else if (isChartType) {
        currentAuthType = 'user';
      } else {
        currentAuthType = document.getElementById('plugin-auth-type-generic')?.value || '';
        currentAuthKey = document.getElementById('plugin-auth-key')?.value || '';
      }

      // Get metadata and additional fields
      const currentMetadata = document.getElementById('plugin-metadata')?.value || '{}';
      let currentAdditionalFields = document.getElementById('plugin-additional-fields')?.value || '{}';

      if (isCosmosType) {
        currentAdditionalFields = JSON.stringify({
          database_name: document.getElementById('cosmos-database-name')?.value?.trim() || '',
          container_name: document.getElementById('cosmos-container-name')?.value?.trim() || '',
          partition_key_path: document.getElementById('cosmos-partition-key-path')?.value?.trim() || '',
          field_hints: this.getCosmosFieldHints(),
          max_items: parseInt(document.getElementById('cosmos-max-items')?.value, 10) || 100,
          timeout: parseInt(document.getElementById('cosmos-timeout')?.value, 10) || 30
        }, null, 2);
      } else if (isDocumentSearchType) {
        currentAdditionalFields = JSON.stringify(this.getDocumentSearchAdditionalFields(), null, 2);
      } else if (isTableauType) {
        currentAdditionalFields = JSON.stringify(this.getTableauConfiguration().additionalFields, null, 2);
      } else if (isMcpType) {
        currentAdditionalFields = JSON.stringify(this.getMcpConfiguration().additionalFields, null, 2);
      } else if (isSimpleChatType) {
        currentAdditionalFields = JSON.stringify({
          simplechat_capabilities: this.getSelectedSimpleChatCapabilities()
        }, null, 2);
      } else if (isMsGraphType) {
        currentAdditionalFields = JSON.stringify({
          msgraph_capabilities: this.getSelectedMsGraphCapabilities(),
          ...this.getMsGraphMailSendConfiguration(),
          ...this.getMsGraphCalendarSendConfiguration()
        }, null, 2);
      } else if (isAzureMapsType) {
        currentAdditionalFields = '{}';
      } else if (isChartType) {
        currentAdditionalFields = JSON.stringify({
          chart_capabilities: this.getSelectedChartCapabilities()
        }, null, 2);
      }

      // Compare basic fields
      if (currentDisplayName !== (this.originalPlugin.displayName || '')) {
        changes.displayName = {
          before: this.originalPlugin.displayName || '',
          after: currentDisplayName
        };
      }

      if (currentName !== (this.originalPlugin.name || '')) {
        changes.name = {
          before: this.originalPlugin.name || '',
          after: currentName
        };
      }

      if (currentDescription !== (this.originalPlugin.description || '')) {
        changes.description = {
          before: this.originalPlugin.description || '',
          after: currentDescription
        };
      }

      if (currentEndpoint !== (this.originalPlugin.endpoint || '')) {
        changes.endpoint = {
          before: this.originalPlugin.endpoint || '',
          after: currentEndpoint
        };
      }

      // Compare authentication key (mask for security)
      const originalAuthKey = (this.originalPlugin.auth && this.originalPlugin.auth.key) || '';
      if (currentAuthKey !== originalAuthKey) {
        changes.authKey = {
          before: originalAuthKey ? '***' + originalAuthKey.slice(-4) : '(empty)',
          after: currentAuthKey ? '***' + currentAuthKey.slice(-4) : '(empty)'
        };
      }

      const originalAuthType = (this.originalPlugin.auth && this.originalPlugin.auth.type) || '';
      if (currentAuthType !== originalAuthType) {
        changes.authType = {
          before: originalAuthType || '(empty)',
          after: currentAuthType || '(empty)'
        };
      }

      // Compare metadata
      try {
        const originalMetadataStr = this.originalPlugin.metadata && Object.keys(this.originalPlugin.metadata).length > 0 ?
          JSON.stringify(this.originalPlugin.metadata, null, 2) : '{}';
        if (currentMetadata !== originalMetadataStr) {
          changes.metadata = {
            before: originalMetadataStr,
            after: currentMetadata
          };
        }
      } catch (e) {
        console.log('Metadata comparison error:', e);
      }

      // Compare additional fields
      try {
        const originalAdditionalFieldsStr = this.originalPlugin.additionalFields && Object.keys(this.originalPlugin.additionalFields).length > 0 ?
          JSON.stringify(this.originalPlugin.additionalFields, null, 2) : '{}';
        if (currentAdditionalFields !== originalAdditionalFieldsStr) {
          changes.additionalFields = {
            before: originalAdditionalFieldsStr,
            after: currentAdditionalFields
          };
        }
      } catch (e) {
        console.log('Additional fields comparison error:', e);
      }

      return Object.keys(changes).length > 0 ? changes : null;
    } catch (error) {
      console.error('Error detecting changes:', error);
      return null;
    }
  }

  populateAdvancedSummary() {
    const advancedSection = document.getElementById('summary-advanced-section');
    const isStructuredConfigType = this.isStructuredConfigType();

    // Check if there's any metadata or additional fields
    const metadata = document.getElementById('plugin-metadata').value.trim();
    //const additionalFields = document.getElementById('plugin-additional-fields').value.trim();

    // Check if metadata/additional fields actually contain meaningful data (not just empty objects)
    let hasMetadata = false;
    let hasAdditionalFields = false;

    try {
      const metadataObj = JSON.parse(metadata || '{}');
      hasMetadata = Object.keys(metadataObj).length > 0;
    } catch (e) {
      // If it's not valid JSON, consider it as having content if it's not empty
      hasMetadata = metadata.length > 0 && metadata !== '{}';
    }

    // For SQL and Cosmos types, additional fields are already shown in dedicated configuration
    // summary section, so skip showing them again in Advanced to avoid redundancy
    if (!isStructuredConfigType) {
      // DRY: Use private helper to collect additional fields
      let additionalFieldsObj = this.collectAdditionalFields();
      hasAdditionalFields = Object.keys(additionalFieldsObj).length > 0;

      // Show/hide additional fields preview
      const additionalFieldsPreview = document.getElementById('summary-additional-fields-preview');
      if (hasAdditionalFields) {
        let previewContent = '';
        if (typeof additionalFieldsObj === 'object' && additionalFieldsObj !== null) {
          previewContent = JSON.stringify(additionalFieldsObj, null, 2);
        } else {
          previewContent = '';
        }
        document.getElementById('summary-additional-fields-content').textContent = previewContent;
        additionalFieldsPreview.style.display = '';
      } else {
        additionalFieldsPreview.style.display = 'none';
      }
    } else {
      // Hide additional fields for structured config types
      const additionalFieldsPreview = document.getElementById('summary-additional-fields-preview');
      if (additionalFieldsPreview) additionalFieldsPreview.style.display = 'none';
      hasAdditionalFields = false;
    }

    // Update has metadata/additional fields indicators
    document.getElementById('summary-has-metadata').textContent = hasMetadata ? 'Yes' : 'No';
    document.getElementById('summary-has-additional-fields').textContent = hasAdditionalFields ? 'Yes' : 'No';

    // Show/hide metadata preview
    const metadataPreview = document.getElementById('summary-metadata-preview');
    if (hasMetadata) {
      document.getElementById('summary-metadata-content').textContent = metadata;
      metadataPreview.style.display = '';
    } else {
      metadataPreview.style.display = 'none';
    }

    // Show advanced section if there's any advanced content
    if (hasMetadata || hasAdditionalFields) {
      advancedSection.style.display = '';
    } else {
      advancedSection.style.display = 'none';
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
      endpoint: 'Endpoint/Connection',
      authType: 'Authentication Type',
      apiKey: 'API Key',
      username: 'Username',
      password: 'Password',
      connectionMethod: 'Connection Method',
      databaseType: 'Database Type',
      openApiFile: 'OpenAPI Specification',
      metadata: 'Metadata',
      additionalFields: 'Additional Fields'
    };
    return labels[field] || field;
  }

  clearForm() {
    // Clear all form fields for new action creation
    // Use safe setting to avoid errors with missing elements

    const safeSetValue = (id, value = '') => {
      const element = document.getElementById(id);
      if (element) {
        element.value = value;
      }
    };

    const safeSetDataset = (id, key, value = '') => {
      const element = document.getElementById(id);
      if (element && element.dataset) {
        element.dataset[key] = value;
      }
    };

    // Step 2 fields - Basic Info
    safeSetValue('plugin-name');
    safeSetValue('plugin-display-name');
    safeSetValue('plugin-description');
    safeSetValue('plugin-type');

    // Step 3 fields - OpenAPI
    safeSetValue('plugin-endpoint');
    safeSetValue('plugin-openapi-file');
    safeSetDataset('plugin-openapi-file', 'fileId');
    safeSetDataset('plugin-openapi-file', 'specContent');

    // Clear OpenAPI auth fields
    safeSetValue('plugin-auth-type', 'none');
    safeSetValue('plugin-auth-identity-select');
    safeSetValue('plugin-auth-api-key');
    safeSetValue('plugin-auth-bearer-token');
    safeSetValue('plugin-auth-basic-username');
    safeSetValue('plugin-auth-basic-password');
    safeSetValue('plugin-auth-oauth2-token');

    // Clear OpenAPI status displays
    const statusElements = [
      'openapi-file-status',
      'openapi-file-help'
    ];
    statusElements.forEach(id => {
      const element = document.getElementById(id);
      if (element) {
        element.innerHTML = '';
        element.className = '';
      }
    });

    // Step 3 fields - Generic Plugin
    safeSetValue('plugin-endpoint-generic');
    safeSetValue('plugin-auth-type-generic', 'none');
    safeSetValue('plugin-auth-identity-select-generic');
    safeSetValue('plugin-auth-api-key-generic');
    safeSetValue('plugin-auth-bearer-token-generic');
    safeSetValue('plugin-auth-basic-username-generic');
    safeSetValue('plugin-auth-basic-password-generic');
    safeSetValue('plugin-auth-oauth2-token-generic');
    safeSetValue('azure-maps-key');

    // Step 3 fields - MCP Plugin
    safeSetValue('mcp-transport', 'streamable_http');
    safeSetValue('mcp-endpoint');
    safeSetValue('mcp-command');
    safeSetValue('mcp-args');
    safeSetValue('mcp-env', '{}');
    safeSetValue('mcp-auth-method', 'none');
    safeSetValue('mcp-identity-select');
    safeSetValue('mcp-bearer-token');
    safeSetValue('mcp-api-key-header-name', 'X-API-Key');
    safeSetValue('mcp-api-key-value');
    safeSetValue('mcp-basic-username');
    safeSetValue('mcp-basic-password');
    safeSetValue('mcp-tool-names');
    safeSetValue('mcp-tool-metadata', '[]');
    safeSetValue('mcp-request-timeout', '30');
    safeSetValue('mcp-connect-timeout', '10');
    safeSetValue('mcp-sse-read-timeout', '300');
    const loadTools = document.getElementById('mcp-load-tools');
    if (loadTools) {
      loadTools.checked = true;
    }
    const loadPrompts = document.getElementById('mcp-load-prompts');
    if (loadPrompts) {
      loadPrompts.checked = false;
    }

    // Step 3 fields - Databricks Plugin
    safeSetValue('databricks-workspace-url');
    safeSetValue('databricks-cloud', DATABRICKS_DEFAULT_CLOUD);
    safeSetValue('databricks-warehouse-id');
    safeSetValue('databricks-catalog');
    safeSetValue('databricks-schema');
    safeSetValue('databricks-auth-method', 'pat');
    safeSetValue('databricks-identity-select');
    safeSetValue('databricks-token');
    safeSetValue('databricks-client-id');
    safeSetValue('databricks-client-secret');
    safeSetValue('databricks-tenant-id');
    safeSetValue('databricks-max-rows', '1000');
    safeSetValue('databricks-timeout', '30');
    safeSetValue('databricks-wait-timeout', '30');

    // Step 3 fields - Tableau Plugin
    safeSetValue('tableau-server-url');
    safeSetValue('tableau-site-content-url');
    safeSetValue('tableau-auth-method', TABLEAU_AUTH_METHOD_PAT);
    safeSetValue('tableau-identity-select');
    safeSetValue('tableau-pat-name');
    safeSetValue('tableau-pat-secret');
    safeSetValue('tableau-username');
    safeSetValue('tableau-password');
    safeSetValue('tableau-page-size', '100');
    safeSetValue('tableau-max-results', '100');
    safeSetValue('tableau-timeout', '30');
    const tableauUseServerVersion = document.getElementById('tableau-use-server-version');
    if (tableauUseServerVersion) {
      tableauUseServerVersion.checked = true;
    }

    // Step 3 fields - SQL Plugin
    safeSetValue('sql-connection-method', 'connection_string');
    safeSetValue('sql-connection-string');
    safeSetValue('sql-server');
    safeSetValue('sql-database');
    safeSetValue('sql-username');
    safeSetValue('sql-password');
    safeSetValue('sql-auth-type', 'username_password');
    safeSetValue('sql-identity-select');
    safeSetValue('sql-database-type', 'sql_server');

    ['plugin-auth-type', 'plugin-auth-type-generic', 'mcp-auth-method', 'databricks-auth-method', 'tableau-auth-method', 'sql-auth-type'].forEach(id => {
      const element = document.getElementById(id);
      if (element) {
        element.disabled = false;
      }
    });

    // Step 3 fields - Cosmos Plugin
    safeSetValue('cosmos-endpoint');
    safeSetValue('cosmos-database-name');
    safeSetValue('cosmos-container-name');
    safeSetValue('cosmos-partition-key-path');
    safeSetValue('cosmos-field-hints');
    safeSetValue('cosmos-max-items', '100');
    safeSetValue('cosmos-timeout', '30');
    safeSetValue('cosmos-auth-type', 'identity');
    safeSetValue('cosmos-auth-key');

    // Step 3 fields - Document Search Plugin
    safeSetValue('document-search-scope', 'all');
    safeSetValue('document-search-top-n', '12');
    safeSetValue('document-search-window-unit', 'pages');
    safeSetValue('document-search-window-size');
    safeSetValue('document-search-window-percent');
    safeSetValue('document-search-focus-instructions');
    safeSetValue('document-search-window-target-length', '2 pages');
    safeSetValue('document-search-final-target-length', '2 pages');

    // Step 3 fields - Blob Storage Plugin
    safeSetValue('blob-storage-connection-string');
    safeSetValue('blob-storage-container-name');
    safeSetValue('blob-storage-blob-prefix');

    this.simpleChatCapabilityState = this.getDefaultSimpleChatCapabilities();
    this.renderSimpleChatConfiguration();
    this.msGraphCapabilityState = this.getDefaultMsGraphCapabilities();
    this.renderMsGraphConfiguration();
    this.setMsGraphMailSendConfiguration({});
    this.setMsGraphCalendarSendConfiguration({});
    this.chartCapabilityState = this.getDefaultChartCapabilities();
    this.renderChartConfiguration();
    this.blobStorageCapabilityState = this.getDefaultBlobStorageCapabilities();
    this.blobStorageReadFileTypeState = this.getDefaultBlobStorageReadFileTypes();
    this.blobStorageUploadFileTypeState = this.getDefaultBlobStorageUploadFileTypes();
    this.renderBlobStorageConfiguration();

    // Clear any type selection
    this.selectedType = null;
    this.currentAllowedAuthTypes = null;

    // Hide all auth field sections (with safe calls)
    try {
      this.toggleOpenApiAuthFields();
      this.toggleMcpTransportFields();
      this.toggleMcpAuthFields();
      this.toggleDatabricksAuthFields();
      this.toggleTableauAuthFields();
      this.toggleGenericAuthFields();
      this.handleSqlAuthTypeChange();
      this.handleCosmosAuthTypeChange();
    } catch (e) {
      console.log('Some auth field toggles not available:', e.message);
    }

    // Reset action type selection
    const actionTypeCards = document.querySelectorAll('.action-type-card.selected');
    actionTypeCards.forEach(card => card.classList.remove('selected'));

    console.log('Form cleared for new action');
  }

  escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  formatLabel(str) {
    // Convert snake_case, camelCase, PascalCase to spaced words
    return str
      .replace(/([a-z])([A-Z])/g, '$1 $2') // camelCase, PascalCase
      .replace(/_/g, ' ') // snake_case
      .replace(/\b([A-Z]+)\b/g, match => match.charAt(0) + match.slice(1).toLowerCase()) // ALLCAPS to Capitalized
      .replace(/^\w/, c => c.toUpperCase());
  }

  // Build the additional fields UI from a JSON schema
  buildAdditionalFieldsUI(schema, parentDiv) {
    // Utility to create a labeled field
    const self = this;
    // Render title and description
    const title = document.createElement('h6');
    title.textContent = schema.title || 'Additional Settings';
    parentDiv.appendChild(title);
    if (schema.description) {
      const desc = document.createElement('p');
      desc.className = 'text-muted';
      desc.textContent = schema.description;
      parentDiv.appendChild(desc);
    }
    // Render all top-level properties
    if (schema.properties) {
      Object.entries(schema.properties).forEach(([key, prop]) => {
        if (prop.type === 'array') {
          this.addArrayFieldUI(prop, key, parentDiv, prop.default || []);
        } else if (prop.type === 'object') {
          const wrapper = document.createElement('div');
          wrapper.className = 'additional-field-object';
          // Create a fieldset for the object
          const fieldset = document.createElement('fieldset');
          fieldset.dataset.schemaKey = key;
          // Optionally add a legend for the object
          const legend = document.createElement('legend');
          legend.textContent = this.formatLabel(key);
          fieldset.appendChild(legend);
          // Render all sub-properties inside the fieldset
          if (prop.properties) {
            Object.entries(prop.properties).forEach(([subKey, subProp]) => {
              this.createField(subKey, subProp, fieldset);
            });
          }
          wrapper.appendChild(fieldset);
          parentDiv.appendChild(wrapper);
        } else {
          const wrapper = document.createElement('div');
          wrapper.className = 'additional-field-primitive';
          this.createField(key, prop, wrapper);
          parentDiv.appendChild(wrapper);
        }
      });
    }
  }

  // Recursively populate dynamic additional fields UI
  populateDynamicAdditionalFields(fields, parentKey = '') {
    if (!fields || typeof fields !== 'object') return;
    if (this.additionalSettingsSchemaCache && this.selectedType && !this.additionalSettingsSchemaCache[this.getSafeType(this.selectedType)]) {
      this.getAdditionalSettingsSchema(this.selectedType);
    }
    const schema = this.additionalSettingsSchemaCache && this.selectedType ? this.additionalSettingsSchemaCache[this.getSafeType(this.selectedType)] : null;
    Object.entries(fields).forEach(([key, value]) => {
      console.log('Processing field:', key, 'with value:', value, 'under parentKey:', parentKey);
      let fieldName = key;
      if (Array.isArray(value)) {
        // Find array wrapper, add items if needed
        let arrayWrapper = document.querySelector(`#plugin-additional-fields-div [data-schema-key="${fieldName}"]`);
        if (!arrayWrapper) {
          // Try to find schema for this array (assume you have access to schema)
          if (this.additionalSettingsSchemaCache && this.selectedType) {
            if (schema && schema.properties && schema.properties[fieldName] && schema.properties[fieldName].type === 'array') {
              this.addArrayFieldUI(schema.properties[fieldName], fieldName, document.getElementById('plugin-additional-fields-div'), value);
              arrayWrapper = document.querySelector(`#plugin-additional-fields-div [data-schema-key="${fieldName}"]`);
            }
          }
        }
        // Now populate each item
        if (arrayWrapper) {
          const itemsContainer = arrayWrapper.querySelector('.array-group');
          // Remove existing items
          while (itemsContainer && itemsContainer.firstChild) itemsContainer.removeChild(itemsContainer.firstChild);
          value.forEach(item => {
            this.addArrayItemUI(
              (schema && schema.properties && schema.properties[fieldName] && schema.properties[fieldName].items) || {},
              fieldName,
              itemsContainer,
              item
            );
          });
        }
      } else if (value && typeof value === 'object') {
        this.populateDynamicAdditionalFields(value, fieldName);
      } else {
        let query = parentKey ? `#plugin-additional-fields-div [data-schema-key="${parentKey}"] [name="${fieldName}"]` : `#plugin-additional-fields-div [name="${fieldName}"]`;
        console.log('Querying elements with:', query);
        const elements = document.querySelectorAll(query);
        console.log('Found elements for field', fieldName, ':', elements);
        elements.forEach(el => {
          console.log('Setting field:', fieldName, 'with value:', value, 'on element:', el);
          if (el.type === 'checkbox') {
            el.checked = !!value;
          } else if (el.type === 'radio') {
            el.checked = el.value == value;
          } else if (el.tagName === 'SELECT') {
            el.value = value;
          } else if (el.tagName === 'TEXTAREA') {
            el.value = value;
          } else if (el.type === 'number') {
            el.value = value !== undefined && value !== null ? Number(value) : '';
          } else {
            el.value = value;
          }
        });
      }
    });
  }

  // Private deep merge utility
  deepMerge(target, source) {
    for (const key in source) {
      if (source[key] && typeof source[key] === 'object' &&
        !Array.isArray(source[key]) && target[key] && typeof target[key] === 'object' &&
        !Array.isArray(target[key])
      ) {
        target[key] = this.deepMerge(target[key], source[key]);
      } else {
        target[key] = source[key];
      }
    }
    return target;
  }

  // Private method to collect additional fields from both legacy textarea and dynamic UI
  collectAdditionalFields() {
    // 1. Get from textarea (legacy)
    const additionalFieldsValue = document.getElementById('plugin-additional-fields')?.value?.trim() || '';
    let legacyFields = {};
    if (additionalFieldsValue && additionalFieldsValue !== '{}') {
      try {
        legacyFields = JSON.parse(additionalFieldsValue);
      } catch {
        // If not valid JSON, skip
      }
    }

    // 2. Get from dynamic UI
    let uiFields = {};
    const additionalFieldsDiv = document.getElementById('plugin-additional-fields-div');
    if (additionalFieldsDiv) {
      // Arrays
      const arrayWrappers = additionalFieldsDiv.querySelectorAll('.additional-field-array');
      arrayWrappers.forEach(wrapper => {
        const arrayGroup = wrapper.querySelector('.array-group');
        if (arrayGroup) {
          const arrayKey = arrayGroup.dataset.schemaKey;
          const items = [];
          // Loop over each .array-item inside .array-group
          const arrayItems = arrayGroup.querySelectorAll('.array-item');
          arrayItems.forEach(itemDiv => {
            // Check for array of objects (fieldset present)
            const fieldset = itemDiv.querySelector('fieldset');
            if (fieldset) {
              let obj = {};
              const subInputs = fieldset.querySelectorAll('input, select, textarea');
              subInputs.forEach(subEl => {
                let subKey = subEl.name || subEl.id;
                if (!subKey) return;
                let subValue = subEl.type === 'checkbox' ? subEl.checked : (subEl.type === 'number' ? (subEl.value !== '' ? Number(subEl.value) : '') : subEl.value);
                obj[subKey] = subValue;
              });
              items.push(obj);
            } else {
              // Primitive array: find first input/select/textarea directly inside .array-item (not in fieldset or button)
              const possibleInputs = Array.from(itemDiv.querySelectorAll('input, select, textarea'));
              // Exclude those inside a fieldset or button
              const input = possibleInputs.find(el => {
                // Not inside a fieldset or button
                return !el.closest('fieldset') && !el.closest('button');
              });
              if (input) {
                let subValue = input.type === 'checkbox' ? input.checked : (input.type === 'number' ? (input.value !== '' ? Number(input.value) : '') : input.value);
                items.push(subValue);
              }
            }
          });
          if (arrayKey) {
            uiFields[arrayKey] = items;
          }
        }
      });
      // Objects
      const objectWrappers = additionalFieldsDiv.querySelectorAll('.additional-field-object');
      objectWrappers.forEach(wrapper => {
        const objFieldset = wrapper.querySelector('fieldset');
        const objKey = objFieldset.dataset.schemaKey;
        let obj = {};
        const subInputs = objFieldset.querySelectorAll('input, select, textarea');
        subInputs.forEach(subEl => {
          let subKey = subEl.name || subEl.id;
          if (!subKey) return;
          let subValue = subEl.type === 'checkbox' ? subEl.checked : (subEl.type === 'number' ? (subEl.value !== '' ? Number(subEl.value) : '') : subEl.value);
          obj[subKey] = subValue;
        });
        if (objKey) {
          uiFields[objKey] = obj;
        }
      });
      // Primitives
      const primitiveWrappers = additionalFieldsDiv.querySelectorAll('.additional-field-primitive');
      primitiveWrappers.forEach(wrapper => {
        const inputs = wrapper.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
          let key = input.name || input.id;
          let value = input.type === 'checkbox' ? input.checked : (input.type === 'number' ? (input.value !== '' ? Number(input.value) : '') : input.value);
          uiFields[key] = value;
        });
      });
    }

    // 3. Deep merge (UI fields take precedence)
    return this.deepMerge(legacyFields, uiFields);
  }

  getSafeType(type) {
    return type ? type.replace(/[^a-zA-Z0-9_]/g, '_').toLowerCase() : null;
  }

  async getAdditionalSettingsSchema(type, options = {}) {
    if (!type) return null;
    const { useLegacyPattern = false, forceReload = false } = options;
    // Normalize type for filename
    const safeType = this.getSafeType(type);
    // Choose filename pattern
    const schemaFile = `${safeType}_plugin.additional_settings.schema.json`;

    const schemaPath = `/static/json/schemas/${schemaFile}`;

    // Use cache unless forceReload
    if (!forceReload && this.additionalSettingsSchemaCache[safeType]) {
      return this.additionalSettingsSchemaCache[safeType];
    }
    try {
      console.log(`Fetching additional settings schema for type: ${safeType} (pattern: ${safeType})`);
      const res = await fetch(schemaPath);
      if (res.status === 404) {
        console.log(`No additional settings schema found for type: ${type} (404)`);
        this.additionalSettingsSchemaCache[safeType] = null;
        return null;
      }
      if (!res.ok) throw new Error(`Failed to load additional settings schema for type: ${type}`);
      const schema = await res.json();
      this.additionalSettingsSchemaCache[safeType] = schema;
      return schema;
    } catch (err) {
      console.error(`Error loading additional settings schema for type ${type}:`, err);
      this.additionalSettingsSchemaCache[safeType] = null;
      return null;
    }
  }

  // Utility to create a labeled field (refactored from buildAdditionalFieldsUI)
  createField(key, prop, parent, prefix = '') {
    // If prefix is a number, treat as array index for uniqueness
    let fieldId;
    if (typeof prefix === 'number') {
      fieldId = `${key}_${prefix}`;
    } else {
      fieldId = `${prefix}${key}`;
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'mb-3';
    // Label with tooltip if description exists
    const label = document.createElement('label');
    label.className = 'form-label';
    label.htmlFor = fieldId;
    label.textContent = this.formatLabel(key);
    if (prop.description) {
      label.title = prop.description;
      // Add help icon
      const helpIcon = document.createElement('span');
      helpIcon.className = 'ms-1 bi bi-question-circle-fill text-info';
      helpIcon.setAttribute('tabindex', '0');
      helpIcon.setAttribute('data-bs-toggle', 'tooltip');
      helpIcon.setAttribute('title', prop.description);
      label.appendChild(helpIcon);
    }
    wrapper.appendChild(label);

    let input;
    if (prop.enum) {
      input = document.createElement('select');
      input.className = 'form-select';
      input.id = fieldId;
      input.name = key;
      prop.enum.forEach(opt => {
        const option = document.createElement('option');
        option.value = opt;
        option.textContent = this.formatLabel(opt);
        option.title = opt;
        input.appendChild(option);
      });
      if (prop.default) input.value = prop.default;
    } else if (prop.type === 'boolean') {
      input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'form-check-input';
      input.id = fieldId;
      input.name = key;
      input.checked = !!prop.default;
      wrapper.className += ' form-check';
    } else if (prop.type === 'number' || prop.type === 'integer') {
      input = document.createElement('input');
      input.type = 'number';
      input.className = 'form-control';
      input.id = fieldId;
      input.name = key;
      if (prop.minimum !== undefined) input.min = prop.minimum;
      if (prop.maximum !== undefined) input.max = prop.maximum;
      if (prop.default !== undefined) input.value = prop.default;
      if (prop.pattern) input.pattern = prop.pattern;
    } else if (prop.type === 'string' && prop.format === 'email') {
      input = document.createElement('input');
      input.type = 'email';
      input.className = 'form-control';
      input.id = fieldId;
      input.name = key;
      if (prop.default) input.value = prop.default;
    } else if (prop.type === 'string') {
      input = document.createElement('input');
      input.type = 'text';
      input.className = 'form-control';
      input.id = fieldId;
      input.name = key;
      if (prop.minLength !== undefined) input.minLength = prop.minLength;
      if (prop.maxLength !== undefined) input.maxLength = prop.maxLength;
      if (prop.default) input.value = prop.default;
      if (prop.pattern) input.pattern = prop.pattern;
    }
    if (input) wrapper.appendChild(input);
    parent.appendChild(wrapper);
  }

  // New: Array field builder for both initial render and dynamic population
  addArrayFieldUI(arraySchema, arrayKey, parentDiv, initialValues = []) {
    // Create array wrapper
    const wrapper = document.createElement('div');
    wrapper.className = 'additional-field-array';
    wrapper.dataset.schemaKey = arrayKey;

    // Title
    const label = document.createElement('label');
    label.className = 'form-label';
    label.textContent = this.formatLabel(arrayKey);
    wrapper.appendChild(label);

    // Items container
    const itemsContainer = document.createElement('div');
    itemsContainer.className = 'array-group';
    itemsContainer.dataset.schemaKey = arrayKey;
    wrapper.appendChild(itemsContainer);

    // Add button
    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn btn-sm btn-outline-primary mb-2';
    addBtn.textContent = 'Add Item';
    addBtn.onclick = () => {
      this.addArrayItemUI(arraySchema.items, arrayKey, itemsContainer);
    };
    wrapper.appendChild(addBtn);

    // Initial values
    if (Array.isArray(initialValues)) {
      initialValues.forEach(val => {
        this.addArrayItemUI(arraySchema.items, arrayKey, itemsContainer, val);
      });
    }

    parentDiv.appendChild(wrapper);
    return wrapper;
  }

  // Helper to add a single array item
  addArrayItemUI(itemSchema, arrayKey, itemsContainer, initialValue = undefined) {
    const itemDiv = document.createElement('div');
    itemDiv.className = 'array-item mb-2 p-2 border rounded';
    // Remove button
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'btn btn-sm btn-outline-danger float-end';
    removeBtn.textContent = 'Remove';
    removeBtn.onclick = () => {
      itemsContainer.removeChild(itemDiv);
    };
    itemDiv.appendChild(removeBtn);
    // Determine index for uniqueness
    let index = itemsContainer.childNodes.length;
    // Render item fields
    if (itemSchema.type === 'object' && itemSchema.properties) {
      // Create a fieldset for the object item
      const fieldset = document.createElement('fieldset');
      fieldset.dataset.schemaKey = arrayKey;
      // Optionally add a legend for the object item
      const legend = document.createElement('legend');
      legend.textContent = this.formatLabel(arrayKey);
      fieldset.appendChild(legend);
      Object.entries(itemSchema.properties).forEach(([subKey, subProp]) => {
        this.createField(subKey, subProp, fieldset, index);
        // Set initial value if provided
        if (initialValue && initialValue[subKey] !== undefined) {
          const input = fieldset.querySelector(`[name="${subKey}"]`);
          if (input) input.value = initialValue[subKey];
        }
      });
      itemDiv.appendChild(fieldset);
    } else {
      // Primitive array
      this.createField(arrayKey, itemSchema, itemDiv, index);
      if (initialValue !== undefined) {
        const input = itemDiv.querySelector(`[name="${arrayKey}"]`);
        if (input) input.value = initialValue;
      }
    }
    itemsContainer.appendChild(itemDiv);
  }
}

// Create global instance only on pages that render the shared plugin modal.
if (document.getElementById('plugin-modal')) {
  window.pluginModalStepper = new PluginModalStepper();
}
