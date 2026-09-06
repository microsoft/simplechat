// workspaceActionRegistry.ts

import { EDITOR_SECRET_MASK, type ActionConfiguration } from './workspaceAuthoring';
import type { ActionCapability, ActionFieldDescriptor, ActionNativeDefinition } from './workspaceActionTypes';

const options = (values: (string | [string, string])[]) => values.map((value) =>
    typeof value === 'string' ? { value, label: value } : { value: value[0], label: value[1] });
const field = (key: string, label: string, extra: Partial<ActionFieldDescriptor> = {}): ActionFieldDescriptor =>
    ({ path: `/additionalFields/${key}`, label, ...extra });
const endpoint = (label = 'Endpoint', help?: string): ActionFieldDescriptor =>
    ({ path: '/endpoint', label, required: true, help });
const number = (key: string, label: string, min: number, max?: number): ActionFieldDescriptor =>
    field(key, label, { kind: 'number', min, max, step: 1 });
const flag = (key: string, label: string, help?: string): ActionFieldDescriptor =>
    field(key, label, { kind: 'boolean', help });
const choice = (key: string, label: string, values: (string | [string, string])[], extra: Partial<ActionFieldDescriptor> = {}) =>
    field(key, label, { kind: 'select', options: options(values), ...extra });

export const SIMPLECHAT_ACTION_CAPABILITIES: ActionCapability[] = [
    { key: 'create_group', label: 'Create groups', description: 'Create group workspaces with the current user’s permissions.' },
    { key: 'add_group_member', label: 'Add group members', description: 'Add people directly to groups the user can manage.' },
    { key: 'make_group_inactive', label: 'Make groups inactive', description: 'Mark a group inactive when the user has Control Center admin access.' },
    { key: 'create_group_conversation', label: 'Create group conversations', description: 'Create invite-managed group conversations and add current group members.' },
    { key: 'invite_group_conversation_members', label: 'Invite group conversation members', description: 'Invite current group members into an existing group conversation.' },
    { key: 'create_personal_conversation', label: 'Create personal conversations', description: 'Create standard, one-user personal conversations.' },
    { key: 'create_personal_workflow', label: 'Create personal workflows', description: 'Create workflows using the current user’s workflow permissions.' },
    { key: 'add_conversation_message', label: 'Add conversation messages', description: 'Add a user-authored message to a permitted conversation.' },
    { key: 'upload_markdown_document', label: 'Upload Markdown documents', description: 'Create Markdown documents in personal or permitted group workspaces.' },
    { key: 'upload_word_document', label: 'Upload Word documents', description: 'Create Word documents in personal or permitted group workspaces.' },
    { key: 'upload_powerpoint_document', label: 'Upload PowerPoint documents', description: 'Create presentations in personal or permitted group workspaces.' },
    { key: 'create_personal_collaboration_conversation', label: 'Create collaborative conversations', description: 'Create personal collaborative conversations and invite participants.' },
    { key: 'raise_workflow_alert', label: 'Raise workflow alerts', description: 'Raise an alert signal for the owner during a workflow run.', defaultEnabled: false },
];

export const MSGRAPH_ACTION_CAPABILITIES: ActionCapability[] = [
    { key: 'get_my_profile', label: 'Read my profile', description: 'Read the signed-in user’s Microsoft 365 profile.' },
    { key: 'get_my_timezone', label: 'Read my mailbox timezone', description: 'Read mailbox time zone and time-format settings.' },
    { key: 'get_my_events', label: 'Read my calendar events', description: 'Read upcoming events for the signed-in user.' },
    { key: 'create_calendar_invite', label: 'Create calendar invites', description: 'Create events, invite group members, and create Teams meetings.' },
    { key: 'get_my_messages', label: 'Read my mail', description: 'Read recent mail for the signed-in user.' },
    { key: 'mark_message_as_read', label: 'Update message read state', description: 'Mark mail messages as read or unread.' },
    { key: 'send_mail', label: 'Send mail', description: 'Create manual drafts, delayed-delivery drafts, or send mail.' },
    { key: 'search_users', label: 'Search directory users', description: 'Find Microsoft 365 users by name or email prefix.' },
    { key: 'get_user_by_email', label: 'Look up users by email', description: 'Look up a directory user by exact email or UPN.' },
    { key: 'list_drive_items', label: 'List OneDrive items', description: 'List items from the signed-in user’s OneDrive.' },
    { key: 'get_my_security_alerts', label: 'Read security alerts', description: 'Read security alerts available to the signed-in user.' },
];

export const CHART_ACTION_CAPABILITIES: ActionCapability[] = [
    ['line', 'Line charts', 'Compare trends with one or more series.'],
    ['bar', 'Bar charts', 'Compare categories, including grouped series.'],
    ['pie', 'Pie charts', 'Show proportions of a whole.'],
    ['doughnut', 'Doughnut charts', 'Show proportions with a center cutout.'],
    ['scatter', 'Scatter plots', 'Compare pairs of numerical values.'],
    ['area', 'Area charts', 'Show trends with filled areas.'],
    ['bubble', 'Bubble charts', 'Compare x, y, and size dimensions.'],
    ['radar', 'Radar charts', 'Compare values across multiple axes.'],
    ['stacked_bar', 'Stacked bar charts', 'Show cumulative category comparisons.'],
    ['stacked_line', 'Stacked line charts', 'Show cumulative multi-series trends.'],
].map(([key, label, description]) => ({ key, label, description }));

export const BLOB_ACTION_CAPABILITIES: ActionCapability[] = [
    { key: 'list_container_contents', label: 'List container contents', description: 'List blobs in this container and optional prefix.' },
    { key: 'read_file_content', label: 'Read file content', description: 'Read supported file types from this container.' },
    { key: 'upload_file_to_container', label: 'Upload files', description: 'Upload supported file types into this container.', defaultEnabled: false },
];

export function sqlConnectionMethod(draft: ActionConfiguration): 'parameters' | 'connection_string' {
    if (draft.additionalFields.identity_uses_connection_string === true) return 'connection_string';
    if (draft._sqlConnectionMethod === 'parameters' || draft._sqlConnectionMethod === 'connection_string') {
        return draft._sqlConnectionMethod;
    }
    return draft.additionalFields.connection_string ? 'connection_string' : 'parameters';
}

export function usesDirectBlobConnectionString(draft: ActionConfiguration): boolean {
    return draft.type === 'blob_storage' && draft.auth.type === 'connection_string' && !draft.identity_id;
}

const sqlParameters = (draft: ActionConfiguration) => sqlConnectionMethod(draft) === 'parameters';
const sqlServer = (draft: ActionConfiguration) => sqlParameters(draft) && draft.additionalFields.database_type !== 'sqlite';
const sqlFields: ActionFieldDescriptor[] = [
    choice('database_type', 'Database engine', [
        ['sqlserver', 'SQL Server'], ['azure_sql', 'Azure SQL'], ['postgresql', 'PostgreSQL'],
        ['mysql', 'MySQL'], ['sqlite', 'SQLite'],
    ], { required: true }),
    field('connection_string', 'Database connection string', {
        kind: 'secret', visible: (draft) => !sqlParameters(draft) && !draft.identity_id,
        help: 'The connection string takes precedence over individual parameters. Keep a stored value, replace it, or explicitly clear it.',
    }),
    field('server', 'Database server', { visible: sqlServer, required: true }),
    field('database', 'Database name or SQLite path', { visible: sqlParameters, required: true }),
    { ...number('port', 'Port', 1, 65535), visible: sqlServer },
    field('driver', 'ODBC driver', {
        visible: (draft) => sqlServer(draft) && ['sqlserver', 'azure_sql'].includes(String(draft.additionalFields.database_type)),
        placeholder: 'ODBC Driver 18 for SQL Server',
        help: 'Use a driver installed on the application server. Driver 18 is the supported default.',
    }),
];
const queryLimits: ActionFieldDescriptor[] = [
    flag('read_only', 'Read-only queries', 'Restrict statements to retrieving data.'),
    number('max_rows', 'Maximum rows', 1, 10000),
    number('timeout', 'Query timeout (seconds)', 1, 300),
];
const databricksFields: ActionFieldDescriptor[] = [
    endpoint('Databricks workspace URL', 'Use the workspace URL, not the SQL statements API path.'),
    choice('cloud', 'Databricks cloud', [['azure_commercial', 'Azure Commercial']], { required: true }),
    field('warehouse_id', 'SQL Warehouse ID', { required: true }),
    field('catalog', 'Default catalog'),
    field('schema', 'Default schema'),
    ...queryLimits.map((descriptor) => descriptor.path === '/additionalFields/read_only'
        ? { ...descriptor, readOnly: true } : descriptor),
    number('wait_timeout', 'Statement wait timeout (seconds)', 1, 50),
    number('byte_limit', 'Result size limit (bytes)', 1000, 2000000),
];
const documentSearchFields: ActionFieldDescriptor[] = [
    choice('default_doc_scope', 'Default document scope', [
        ['all', 'All permitted workspaces'], ['personal', 'My workspace'], ['group', 'Group workspaces'], ['public', 'Public workspaces'],
    ]),
    number('default_top_n', 'Default search result limit', 1, 500),
    choice('default_window_unit', 'Preferred window unit', [['pages', 'Pages'], ['chunks', 'Chunks']]),
    number('default_window_size', 'Preferred window size', 1, 100),
    number('default_window_percent', 'Preferred window percent', 1, 100),
    field('default_focus_instructions', 'Default focus instructions', { kind: 'textarea' }),
    field('default_window_target_length', 'Window summary target length'),
    field('default_final_target_length', 'Final summary target length'),
];
const searchDefaults = {
    default_doc_scope: 'all', default_top_n: 50, default_window_unit: 'pages',
    default_window_target_length: '2 pages', default_final_target_length: '2 pages',
};
const internalUtility = (type: string, help: string): ActionNativeDefinition => ({
    fields: [endpoint('Endpoint', 'An internal marker required by the action manifest; it does not select a remote server. The agent supplies operation inputs at invocation time.')],
    internal: true, defaults: { endpoint: `internal://${type}`, auth: { type: 'NoAuth' } }, help,
});

/** Native controls supplement, never replace, the governed catalogue and its schemas. */
export const NATIVE_ACTION_TYPES: Record<string, ActionNativeDefinition> = {
    openapi: { fields: [], identityTypes: ['api_key', 'bearer_token', 'username_password'], defaults: {
        auth: { type: 'key', key: '' }, additionalFields: { auth_method: 'none', openapi_source_type: 'content' },
    } },
    mcp: { fields: [], identityTypes: ['api_key', 'bearer_token', 'managed_identity', 'username_password'], defaults: {
        auth: { type: 'NoAuth' }, additionalFields: {
            transport: 'streamable_http', server_profile: 'generic', auth_method: 'none', load_tools: true,
            load_prompts: false, request_timeout: 30, connect_timeout: 10, sse_read_timeout: 300,
            retry_count: 0, retry_backoff_seconds: 1, validate_tool_arguments: false,
            tool_result_policy: 'truncate', allowed_tool_names: [], custom_headers: {},
        },
    } },
    sql_query: {
        fields: [...sqlFields, ...queryLimits],
        defaults: { endpoint: '', auth: { type: 'user' }, additionalFields: {
            auth_type: 'username_password', read_only: true, max_rows: 1000, timeout: 30,
        } },
        identityTypes: ['connection_string', 'managed_identity', 'username_password'],
        testPath: '/api/plugins/test-sql-connection',
        help: 'Query a database using a connection string or individual connection parameters. The query action can expose schema information as well as execute permitted statements.',
    },
    sql_schema: {
        fields: [
            ...sqlFields,
            flag('include_system_tables', 'Include system tables', 'Include database system objects in schema discovery.'),
            field('table_filter', 'Table name filter', { help: 'Optional wildcard pattern, for example sales_* or *_log.' }),
        ],
        defaults: { endpoint: '', auth: { type: 'user' }, additionalFields: {
            auth_type: 'username_password', include_system_tables: false,
        } },
        identityTypes: ['connection_string', 'managed_identity', 'username_password'],
        testPath: '/api/plugins/test-sql-connection',
        help: 'Expose database schema discovery without the SQL query action’s execution controls.',
    },
    cosmos_query: {
        fields: [
            endpoint('Cosmos DB account endpoint'),
            field('database_name', 'Database name', { required: true }),
            field('container_name', 'Container name', { required: true }),
            field('partition_key_path', 'Partition key path', { required: true, placeholder: '/tenantId' }),
            field('field_hints', 'Preferred document fields', { kind: 'lines', help: 'One field or document property per line.' }),
            number('max_items', 'Maximum items', 1, 1000),
            number('timeout', 'Request timeout (seconds)', 1, 120),
        ],
        defaults: { auth: { type: 'identity', identity: 'managed_identity' }, additionalFields: {
            field_hints: [], max_items: 100, timeout: 30,
        } },
        identityTypes: [],
        testPath: '/api/plugins/test-cosmos-connection',
        help: 'Query Azure Cosmos DB for NoSQL. Managed identity needs a Cosmos DB data-reader role on the target account.',
    },
    rocksdb: {
        fields: [
            endpoint('RocksDB service URL', 'Connect to an HTTP service exposing the RocksDB health, scan, and get contract.'),
            field('column_family', 'Column family'),
            choice('key_encoding', 'Key encoding', [['utf8', 'UTF-8'], ['base64', 'Base64']]),
            choice('value_encoding', 'Value encoding', [['utf8', 'UTF-8'], ['json', 'JSON'], ['base64', 'Base64']]),
            field('key_prefix_hints', 'Key prefix hints', { kind: 'lines', help: 'One prefix per line; helps the model choose narrower scans.' }),
            flag('read_only', 'Read-only access', 'Disable writes to the RocksDB service.'),
            number('max_results', 'Maximum results', 1, 1000),
            number('max_value_bytes', 'Maximum value size (bytes)', 1, 1048576),
            number('timeout', 'Request timeout (seconds)', 1, 300),
        ],
        defaults: { auth: { type: 'NoAuth' }, additionalFields: {
            auth_scheme: 'none', column_family: 'default', key_encoding: 'utf8', value_encoding: 'utf8',
            key_prefix_hints: [], read_only: true, max_results: 100, max_value_bytes: 32768, timeout: 30,
        } },
        identityTypes: [],
        testPath: '/api/plugins/test-rocksdb-connection',
    },
    databricks: {
        fields: databricksFields,
        defaults: { auth: { type: 'key', key: '' }, additionalFields: {
            cloud: 'azure_commercial', auth_method: 'pat', read_only: true,
            max_rows: 1000, timeout: 30, wait_timeout: 30, byte_limit: 250000,
        } },
        identityTypes: ['api_key', 'bearer_token', 'managed_identity'],
        testPath: '/api/plugins/test-databricks-connection',
        help: 'Run read-only queries through an Azure Databricks SQL Warehouse. Use a PAT, bearer token, service principal, or managed identity.',
    },
    databricks_table: {
        fields: [
            ...databricksFields,
            field('httpPath', 'Legacy warehouse HTTP path', { help: 'Retained for older Databricks table configurations.' }),
            number('port', 'Legacy ODBC port', 1, 65535),
            field('database', 'Legacy default database'),
            field('table_name', 'Legacy catalog table'),
        ],
        defaults: { auth: { type: 'key', key: '' }, additionalFields: {
            cloud: 'azure_commercial', auth_method: 'pat', read_only: true, max_rows: 1000, timeout: 30, wait_timeout: 30,
        } },
        identityTypes: ['api_key', 'bearer_token', 'managed_identity'],
        testPath: '/api/plugins/test-databricks-connection',
        help: 'A compatible Databricks table action uses the SQL Warehouse connector. Existing table-specific settings remain available.',
    },
    snowflake: {
        fields: [
            field('account', 'Snowflake account', { required: true, help: 'Account identifier without the snowflakecomputing.com suffix.' }),
            field('user', 'Snowflake user', { help: 'Required for key-pair or OAuth identities. A username/password identity can provide its username.' }),
            field('warehouse', 'Warehouse', { required: true }),
            field('database', 'Default database'),
            field('schema', 'Default schema'),
            field('role', 'Role'),
            ...queryLimits.map((descriptor) => descriptor.path === '/additionalFields/read_only'
                ? { ...descriptor, readOnly: true } : descriptor),
            number('login_timeout', 'Login timeout (seconds)', 1, 300),
            number('byte_limit', 'Result size limit (bytes)', 1000, 2000000),
        ],
        defaults: { endpoint: 'snowflake://query', auth: { type: 'username_password' }, additionalFields: {
            auth_method: 'password', read_only: true, max_rows: 1000, timeout: 30, login_timeout: 30, byte_limit: 250000,
        } },
        identityTypes: ['api_key', 'bearer_token', 'username_password'],
        testPath: '/api/plugins/test-snowflake-connection',
        help: 'Run read-only Snowflake queries with a password, PEM key pair, or OAuth access token.',
    },
    tableau: {
        fields: [
            endpoint('Tableau server URL'),
            field('site_content_url', 'Site content URL', { help: 'Leave blank for the default Tableau Server site.' }),
            number('page_size', 'Page size', 1, 1000),
            number('max_results', 'Maximum results', 1, 1000),
            number('timeout', 'Request timeout (seconds)', 1, 300),
            flag('use_server_version', 'Negotiate server API version', 'Let Tableau Server Client select a supported REST API version.'),
        ],
        defaults: { auth: { type: 'key' }, additionalFields: {
            auth_method: 'personal_access_token', page_size: 100, max_results: 100, timeout: 30, use_server_version: true,
        } },
        identityTypes: ['api_key', 'username_password'],
        testPath: '/api/plugins/test-tableau-connection',
        help: 'Read Tableau content using a personal access token or username/password. The token name is required with a PAT.',
    },
    yamcs: {
        fields: [
            endpoint('Yamcs server URL'),
            field('instance', 'Yamcs instance', { required: true }),
            field('processor', 'Processor'),
            flag('tls_verify', 'Verify TLS certificates', 'Disable only for an internal ground segment using a self-signed certificate.'),
            { ...flag('read_only', 'Read-only access', 'Yamcs actions never issue commands or change parameter/link state.'), readOnly: true },
            flag('enable_archive_sql', 'Allow read-only archive SQL', 'Permit queries against Yamcs archive tables.'),
            number('max_rows', 'Maximum rows', 1, 5000),
            number('timeout', 'Request timeout (seconds)', 1, 300),
            number('byte_limit', 'Result size limit (bytes)', 1000, 2000000),
        ],
        defaults: { auth: { type: 'username_password' }, additionalFields: {
            processor: 'realtime', auth_method: 'username_password', tls_verify: true, read_only: true,
            enable_archive_sql: false, max_rows: 500, timeout: 30, byte_limit: 250000,
        } },
        identityTypes: ['api_key', 'bearer_token', 'username_password'],
        testPath: '/api/plugins/test-yamcs-connection',
        help: 'Retrieve live telemetry and archive data from a Yamcs instance. No commanding capabilities are exposed.',
    },
    blob_storage: {
        fields: [
            {
                ...endpoint('Blob service endpoint', 'Azure commercial, US Government, China, and Germany storage endpoints are supported.'),
                visible: (draft) => !usesDirectBlobConnectionString(draft) ||
                    (draft.auth.key === EDITOR_SECRET_MASK && !draft.endpoint),
            },
            field('container_name', 'Container name', { required: true }),
            field('blob_prefix', 'Blob prefix', { help: 'Optional path prefix that narrows the files this action can access.' }),
            flag('blob_storage_read_file_types/markdown', 'Read Markdown files', 'Supports UTF-8 .md and .markdown files.'),
            flag('blob_storage_upload_file_types/markdown', 'Upload Markdown files', 'Permit Markdown uploads when the upload capability is enabled.'),
        ],
        defaults: { auth: { type: 'connection_string', key: '' }, additionalFields: {
            blob_storage_read_file_types: { markdown: true }, blob_storage_upload_file_types: { markdown: true },
        } },
        capabilities: { path: '/additionalFields/blob_storage_capabilities', options: BLOB_ACTION_CAPABILITIES },
        identityTypes: ['connection_string', 'api_key', 'managed_identity'],
        testPath: '/api/plugins/test-blob-storage-connection',
        help: 'Scope file access to one container and optional prefix. Choose listing, reading, and upload permissions separately.',
    },
    queue_storage: {
        fields: [endpoint('Queue service endpoint'), field('queue_name', 'Queue name', { required: true })],
        defaults: { auth: { type: 'identity', identity: 'managed_identity' } },
        identityTypes: ['api_key', 'managed_identity'],
        help: 'Send and receive messages from the configured Azure Storage Queue. Use the queue service endpoint, not the blob endpoint.',
    },
    azure_maps_openlayers: {
        fields: [],
        defaults: { endpoint: 'https://atlas.microsoft.com', auth: { type: 'key', key: '' } },
        identityTypes: [],
        testPath: '/api/plugins/test-azure-maps-connection',
        help: 'Geocode locations, plan routes, and render maps with Azure Maps. The API endpoint is https://atlas.microsoft.com.',
    },
    document_search: {
        fields: documentSearchFields,
        internal: true,
        defaults: { endpoint: 'internal://document-search', auth: { type: 'NoAuth' }, additionalFields: searchDefaults },
        help: 'Search and summarize documents the current user is allowed to read. Agent-assigned knowledge and workspace permissions still apply.',
    },
    search: {
        fields: documentSearchFields,
        internal: true,
        defaults: { endpoint: 'internal://document-search', auth: { type: 'NoAuth' }, additionalFields: { ...searchDefaults, default_top_n: 12 } },
        help: 'Search permitted workspace documents using the existing document-search defaults.',
    },
    log_analytics: {
        fields: [
            field('workspaceId', 'Log Analytics workspace ID', { required: true, help: 'The workspace GUID, not the Azure resource ID.' }),
            choice('cloud', 'Azure cloud', [['public', 'Azure Commercial'], ['usgovernment', 'Azure US Government'], ['custom', 'Custom cloud']], { required: true }),
            { ...endpoint('Log Analytics API endpoint', 'The public endpoint is https://api.loganalytics.io; government uses https://api.loganalytics.us.'), required: false },
            field('authorityHost', 'Custom authority host', { required: true, visible: (draft) => draft.additionalFields.cloud === 'custom' }),
            field('endpointOverride', 'Custom API endpoint override', { required: true, visible: (draft) => draft.additionalFields.cloud === 'custom' }),
            { path: '/metadata/name', label: 'Resource name', help: 'The name of the Log Analytics resource.', required: true },
        ],
        defaults: { endpoint: 'https://api.loganalytics.io', auth: { type: 'identity', identity: 'managed_identity' },
            additionalFields: { cloud: 'public', query_history: [] } },
        identityTypes: ['client_secret', 'managed_identity'],
        testPath: '/api/plugins/test-log-analytics-connection',
        help: 'Run KQL queries against a Log Analytics workspace. The selected identity needs Log Analytics Reader access.',
    },
    simplechat: {
        fields: [], internal: true, defaults: { endpoint: '', auth: { type: 'user' } },
        capabilities: { path: '/additionalFields/simplechat_capabilities', options: SIMPLECHAT_ACTION_CAPABILITIES },
        help: 'Use workspace, conversation, and document tools as the signed-in user. Capabilities never bypass the user’s permissions.',
    },
    msgraph: {
        fields: [
            choice('msgraph_mail_send_mode', 'Mail delivery mode', [
                ['draft_manual', 'Create a draft for manual review'], ['draft_delayed', 'Create a delayed-delivery draft'], ['auto_send', 'Send immediately'],
            ]),
            { ...number('msgraph_mail_delay_seconds', 'Mail delivery delay (seconds)', 5, 600),
                visible: (draft) => draft.additionalFields.msgraph_mail_send_mode === 'draft_delayed' },
            choice('msgraph_calendar_send_mode', 'Calendar invite delivery mode', [
                ['draft_manual', 'Create a draft for manual review'], ['draft_delayed', 'Create a delayed-delivery draft'], ['auto_send', 'Send immediately'],
            ]),
            { ...number('msgraph_calendar_delay_seconds', 'Calendar delivery delay (seconds)', 5, 600),
                visible: (draft) => draft.additionalFields.msgraph_calendar_send_mode === 'draft_delayed' },
        ],
        internal: true,
        defaults: { endpoint: 'https://graph.microsoft.com', auth: { type: 'user' }, additionalFields: {
            msgraph_mail_send_mode: 'draft_manual', msgraph_mail_delay_seconds: 60,
            msgraph_calendar_send_mode: 'auto_send', msgraph_calendar_delay_seconds: 60,
        } },
        capabilities: { path: '/additionalFields/msgraph_capabilities', options: MSGRAPH_ACTION_CAPABILITIES },
        help: 'Use Microsoft 365 as the signed-in user. Mail and calendar delivery policies determine when changes are sent.',
    },
    chart: {
        fields: [], internal: true, defaults: { endpoint: 'chart://internal', auth: { type: 'user' } },
        capabilities: { path: '/additionalFields/chart_capabilities', options: CHART_ACTION_CAPABILITIES },
        help: 'Render interactive charts in chat. Permit the chart types the agent should be able to produce.',
    },
    agent: {
        fields: [], internal: true, defaults: { endpoint: 'internal://agent', auth: { type: 'user' } },
        help: 'Call one explicitly selected agent using the signed-in user’s permissions. Only the task and explicit context are passed.',
    },
    embedding_model: {
        fields: [
            endpoint('Embedding endpoint'),
            { path: '/deployment', label: 'Embedding deployment', required: true },
            { path: '/api_version', label: 'Embedding API version', required: true },
        ],
        defaults: { auth: { type: 'key', key: '' } },
        identityTypes: ['api_key'],
        help: 'Create text embeddings with the configured Azure OpenAI deployment and an API key. The current embedding action does not support managed identity. Endpoint, deployment, and API version are preserved in the runtime’s manifest locations.',
    },
    smart_http: internalUtility('smart_http', 'Retrieve and extract content from URLs supplied by the agent. Content limits and document processing are managed by the application; no connector credential is required.'),
    http: internalUtility('http', 'Send HTTP requests for URLs supplied at invocation time. Use an OpenAPI action when an API needs a saved specification or connector-specific credentials.'),
    text: internalUtility('text', 'Transform text using the built-in text operations. Inputs are supplied when an agent invokes the tool; there are no connection settings.'),
    math: internalUtility('math', 'Calculate with the built-in arithmetic tools. Numbers are supplied at invocation time; no external connection is required.'),
    time: internalUtility('time', 'Use the built-in date, time, and timezone tools. Their arguments are supplied during an agent call.'),
    wait: internalUtility('wait', 'Allow an agent to pause using the built-in wait tool. Wait duration is supplied at invocation time.'),
    fact_memory: internalUtility('fact_memory', 'Read and maintain facts in the authorized conversation/workspace context. Storage and scope are determined by the application, not a personal credential.'),
    tabular_processing: internalUtility('tabular_processing', 'Analyze and transform permitted workspace spreadsheets and tables. Sources and operations are chosen during the agent call; workspace authorization remains enforced.'),
    ui_test: {
        fields: [endpoint()],
        defaults: { auth: { type: 'NoAuth' } },
        help: 'Configure the fields from the installed UI-test plugin schema. This type is shown only when permitted by the governed catalogue.',
    },
};

export function nativeActionDefinition(type: string): ActionNativeDefinition {
    return Object.hasOwn(NATIVE_ACTION_TYPES, type) ? NATIVE_ACTION_TYPES[type] : {
        fields: [endpoint('Endpoint', 'Use the endpoint required by this installed connector.')],
        help: 'Configure this installed action using its published schema. Custom fields remain available below and in Advanced.',
    };
}
