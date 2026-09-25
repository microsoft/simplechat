# SimpleChat Logging Tags

This reference lists the bracketed logging tags currently used in Python logging-style calls under `application/single_app`.

Logging tags must use the normalized `[UPPERCASE_WITH_UNDERSCORES]` format. Prefer static tags and move dynamic values into the message body or `extra` metadata.

When adding or renaming a tag in `log_event`, `debug_print`, `print`, or `logger.*` messages, update this list in the same change. Prefer reusing an existing tag when it describes the same component or workflow.

Last inventoried: 2026-08-10

## Current tag inventory

- `[ACTION_TEST]`
- `[AGENT_DOCUMENT_CITATIONS]`
- `[AUTH_CALLBACK]`
- `[CONTENT_UNDERSTANDING]`
- `[CUSTOM_MODEL_ENDPOINT]`
- `[EXTRACTION_ENGINE]`
- `[FACT_MEMORY_AUTOSAVE]`
- `[GENERATED_FILE_APPROVALS]`
- `[MIXED_SOURCE_ANALYZE]`
- `[OFFICE_EMBEDDED_IMAGES]`
- `[RATE_LIMIT]`
- `[WORKFLOW_ALERTS]`
- `[YAMCS_PLUGIN]`
- `[ACTIVITY_LOGGING]`
- `[ADMIN_FEEDBACK]`
- `[ADMIN_RELEASE_NOTIFICATIONS]`
- `[AGENTS_CATALOG]`
- `[AGENT_CATALOG]`
- `[AGENT_CITATIONS]`
- `[AGENT_DELEGATION]`
- `[AGENT_INSTRUCTIONS]`
- `[AGENT_LOGGING]`
- `[AGENT_RESPONSE_CALLBACK]`
- `[AGENT_STREAMING]`
- `[AGENT_STREAMING_TOKENS]`
- `[AI_CONNECTIONS]`
- `[ANALYSIS_DELIVERABLE_CONTRACT]`
- `[AKV_TEST]`
- `[APPROVALS]`
- `[APP_INSIGHTS]`
- `[APP_MAINTENANCE]`
- `[APP_UPDATES]`
- `[ASC]`
- `[ASSIGNED_KNOWLEDGE]`
- `[ASSISTANT_FILE_EXPORT]`
- `[AUTH]`
- `[AZURE_MAPS]`
- `[AZURE_MAPS_PLUGIN]`
- `[AZURE_MONITOR]`
- `[BACKEND_SEARCH]`
- `[BLOB_STORAGE_PLUGIN]`
- `[BULK_TAG]`
- `[CHART_PLUGIN]`
- `[CHAT_API]`
- `[CHAT_API_ERROR]`
- `[CHAT_BOOTSTRAP_CACHE]`
- `[CHAT_CONTENT_CHECKS]`
- `[CHAT_DOCUMENT_ACTION]`
- `[CHAT_DOCUMENT_ANALYSIS]`
- `[CHAT_TABULAR_SK]`
- `[CHAT_TYPE]`
- `[CHAT_UPLOAD]`
- `[CHAT_UPLOAD_COLLABORATION_SHARING]`
- `[CHAT_UPLOAD_WORKSPACE_CONTEXT]`
- `[CITATION_EXTRACTION]`
- `[CI_AUTH]`
- `[CLAIMS]`
- `[COLLABORATION]`
- `[COLLABORATION_EVENTS]`
- `[COLLABORATION_MASKING]`
- `[COLLABORATION_NOTIFICATIONS]`
- `[COLLABORATION_RETENTION]`
- `[CONTENT_SAFETY]`
- `[CONTENT_SAFETY_ERROR]`
- `[CONTENT_SAFETY_ERROR_STREAMING]`
- `[CONTENT_SAFETY_STREAMING]`
- `[CONTENT_SCREENING]`
- `[THOUGHTS]`
- `[CONTROL_CENTER]`
- `[CONTROL_CENTER_AUTO_REFRESH]`
- `[CONVERSATION_CACHE]`
- `[CONVERSATION_DELETE]`
- `[CONVERSATION_FEED]`
- `[CONVERSATION_FORK]`
- `[CONVERSATION_METADATA]`
- `[CONVERSATION_SEARCH]`
- `[CONVERSATION_TASK_DOCUMENTS]`
- `[COSMOS_INDEXING]`
- `[COSMOS_QUERY_PLUGIN]`
- `[COSMOS_STALE_CLEANUP]`
- `[COSMOS_THROUGHPUT]`
- `[CREATE_TAG]`
- `[CSRF]`
- `[CUSTOM_PAGES]`
- `[DATABRICKS_PLUGIN]`
- `[DATA_MANAGEMENT]`
- `[DEBUG]`
- `[DEEP_RESEARCH]`
- `[DELETE_DOCUMENT]`
- `[DELETE_GROUP_DOCS]`
- `[DELETE_TAG]`
- `[DELETE_WORKSPACE]`
- `[DELETE_WORKSPACE_DOCS]`
- `[DOCUMENTS]`
- `[DOCUMENT_ACCESS_INDEX]`
- `[DOCUMENT_ACCESS_INDEX_CACHE]`
- `[DOCUMENT_ACTION_STREAM]`
- `[DOCUMENT_ANALYSIS]`
- `[DOCUMENT_ANALYSIS_STREAM]`
- `[DOCUMENT_BLOB_DELETE]`
- `[DOCUMENT_COMPARISON]`
- `[DOCUMENT_DOWNLOAD]`
- `[DOCUMENT_INTELLIGENCE_AUTO]`
- `[DOCUMENT_METADATA_EXTRACTION]`
- `[EMBEDDING]`
- `[EMBEDDING_BATCH]`
- `[ENHANCED_AGENT_CITATIONS]`
- `[ENHANCED_CITATIONS]`
- `[ERROR]`
- `[EXTERNAL_PUBLIC_DOCUMENTS]`
- `[FACTORY]`
- `[FACT_MEMORY]`
- `[FACT_MEMORY_PLUGIN]`
- `[FALLBACK_FAILURE]`
- `[FEEDBACK_LIFECYCLE]`
- `[FILE_PROCESSING_LOGS]`
- `[FILE_SYNC]`
- `[FOUNDRY_AGENT]`
- `[FOUNDRY_WORKFLOW_AGENT]`
- `[GENERATED_FILE_EXPORT]`
- `[GET_FILE_CONTENT]`
- `[GPT_CLIENT]`
- `[GROUP_ACTIVITY]`
- `[GROUP_STATS]`
- `[GROUP_WORKFLOW_STORE]`
- `[HISTORY_CONTEXT]`
- `[HISTORY_FALLBACK]`
- `[IMAGE_CONTEXT]`
- `[IMAGE_GENERATION]`
- `[INBOUND_MCP]`
- `[INFO]`
- `[KEY_VAULT]`
- `[KEY_VAULT_REMINDERS]`
- `[LA]`
- `[LOG]`
- `[LOGGED_PLUGIN_LOADER]`
- `[LOGGING_AGENT_REQUEST]`
- `[LOGGING_AGENT_RESPONSE]`
- `[MAGENTIC_AGENT_RESPONSE_CALLBACK]`
- `[MAGENTIC_STREAMING_AGENT_RESPONSE_CALLBACK]`
- `[MASK]`
- `[MASK_API_ERROR]`
- `[MASK_MESSAGE]`
- `[MCP_DESTINATION_POLICY]`
- `[MCP_DISCOVERY]`
- `[MCP_OUTBOUND]`
- `[MCP_PLUGIN]`
- `[MCP_PLUGIN_FACTORY]`
- `[MCP_PRECONFIGURATIONS]`
- `[MCP_PRESETS]`
- `[MIXED_SOURCE_CHAT_SEARCH]`
- `[MIXED_SOURCE_LIFECYCLE]`
- `[MIXED_SOURCE_MANIFEST]`
- `[MIXED_SOURCE_TELEMETRY]`
- `[MODELS]`
- `[MODEL_ENDPOINT]`
- `[MS_GRAPH_PENDING_ACTIONS]`
- `[MS_GRAPH_PENDING_ACTION_ROUTES]`
- `[MS_GRAPH_PLUGIN]`
- `[NEW_FOUNDRY_AGENT]`
- `[NOTIFICATIONS]`
- `[OPEN_API_PLUGIN]`
- `[ORCHESTRATOR_AGENT_EVENT]`
- `[ORCHESTRATOR_EVENT]`
- `[PLUGIN]`
- `[PLUGINS]`
- `[PLUGIN_CREATION]`
- `[PLUGIN_DISCOVERY_DEBUG]`
- `[PLUGIN_FUNCTION_LOGGER]`
- `[PLUGIN_HEALTH]`
- `[PLUGIN_INVOCATION]`
- `[PLUGIN_LOGGING_API]`
- `[PLUGIN_RECOVERY]`
- `[PLUGIN_REPAIR]`
- `[PLUGIN_TEST]`
- `[PLUGIN_VALIDATION]`
- `[PROCESS_TABULAR]`
- `[PROCESS_VISIO]`
- `[PROFILE_FACT_MEMORY]`
- `[PROMPT_KNOWLEDGE_FILL]`
- `[PUBLIC_DOCUMENTS]`
- `[PUBLIC_WORKSPACE_ACTIVITY]`
- `[PUBLIC_WORKSPACE_STATS]`
- `[RBEP]`
- `[REDIS_EXPLORER]`
- `[REDIS_MONITORING]`
- `[REDIS_TEST]`
- `[RESULT_REQUIRES_MESSAGE_RELOAD]`
- `[RETENTION_POLICY]`
- `[ROCKSDB_PLUGIN]`
- `[SAFETY_LIFECYCLE]`
- `[SAFETY_REMEDIATION]`
- `[SAFETY_VIOLATIONS]`
- `[SAVE_CHUNKS]`
- `[SAVE_CHUNKS_BATCH]`
- `[SEARCH_CACHE_DEBUG]`
- `[SEARCH_SERVICE]`
- `[SERVICE_HEALTH]`
- `[SHARED_CACHE]`
- `[SIMPLE_CHAT]`
- `[SIMPLE_CHAT_DEBUG_TRACE]`
- `[SIMPLE_CHAT_EXTERNAL_EVENT]`
- `[SIMPLE_CHAT_LOG_EVENT]`
- `[SIMPLE_CHAT_LOG_FALLBACK]`
- `[SIMPLE_CHAT_PLUGIN]`
- `[SK_CHAT]`
- `[SK_LOADER]`
- `[SMART_HTTP_PLUGIN]`
- `[SNOWFLAKE_PLUGIN]`
- `[SORT]`
- `[SOURCE_REVIEW]`
- `[SPEECH]`
- `[SQL_ODBC]`
- `[SQL_QUERY_PLUGIN]`
- `[SQL_SCHEMA_PLUGIN]`
- `[STREAMING]`
- `[STREAMING_AGENT_RESPONSE_CALLBACK]`
- `[STREAMING_CLIENT]`
- `[STREAMING_TOKENS]`
- `[STREAM_API_ERROR]`
- `[STREAM_BACKGROUND]`
- `[SUMMARY]`
- `[SUPPORT_FEEDBACK]`
- `[TABLEAU_PLUGIN]`
- `[TABULAR_CHARTS]`
- `[TABULAR_GENERATED_OUTPUT]`
- `[TABULAR_GENERATION_PLAN]`
- `[TABULAR_MULTI_FILE]`
- `[TABULAR_PARITY_CONTRACT]`
- `[TABULAR_PROCESSING_PLUGIN]`
- `[TABULAR_RELATED_DOCUMENTS]`
- `[TABULAR_SHARED_PREFLIGHT]`
- `[TABULAR_SK_ANALYSIS]`
- `[TABULAR_SK_CITATIONS]`
- `[TEAMS_SSO]`
- `[TERMS_OF_USE]`
- `[THREAD]`
- `[THREADING]`
- `[TOKENS]`
- `[TOKEN_FILTERS]`
- `[TTS]`
- `[UPDATE_TAG]`
- `[URL_ACCESS_POLICY_TEST]`
- `[USERS]`
- `[USER_AGREEMENT]`
- `[USER_PROFILE]`
- `[USER_SETTINGS]`
- `[USER_SETTINGS_CACHE]`
- `[XSD_GENERATION]`
- `[XSD_INGESTION]`
- `[VIDEO]`
- `[VIDEO_CHUNK]`
- `[VIDEO_INDEXER]`
- `[VIDEO_INDEXER_AUTH]`
- `[VISION_ANALYSIS]`
- `[VISION_ANALYSIS_V2]`
- `[WARNING]`
- `[WEB_SEARCH]`
- `[WEB_SEARCH_TEST]`
- `[WORKFLOW_DOCUMENT_ACTION]`
- `[WORKFLOW_DOCUMENT_ANALYSIS]`
- `[WORKFLOW_DOCUMENT_COMPARISON]`
- `[WORKFLOW_GENERATED_FILE_EXPORT]`
- `[WORKFLOW_INSTRUCTIONS]`
- `[WORKFLOW_ROUTES]`
- `[WORKFLOW_RUNNER]`
- `[WORKFLOW_SCHEDULER]`
- `[WORKFLOW_STORE]`
- `[WORKSPACE_ACTIVITY]`
- `[WORKSPACE_IDENTITY]`
- `[WORKSPACE_ROUTE]`

## Orchestration failure diagnostics

Implemented in version **0.261.140**, recorded in
`application/single_app/config.py`.

The `[ORCHESTRATION_CONTEXT]`, `[ORCHESTRATION_PLANNER]`, `[ORCHESTRATION_RUNS]`, and `[ORCHESTRATION]`
failure events distinguish planning validation, execution admission, saved-status
projection, and scheduler recovery. Their safe properties appear in Application
Insights `customDimensions` or Log Analytics `AppTraces.Properties`.

| Property | Meaning |
| --- | --- |
| `sc_conversation_id_hash`, `sc_turn_id_hash`, `sc_run_id_hash` | SHA-256 of the exact workflow identifier encoded as UTF-8. Only applicable identifiers are present; these hashes do not grant access to the underlying records. |
| `sc_stage` | The failing boundary, such as `plan_normalization`, `claim_validation`, `settings`, `context`, `identity`, `result_binding`, `model_binding`, `run_detail`, or `scheduler_item`. |
| `sc_validation_code` | Validation category, including `deliverables_invalid`, `source_kind_invalid`, or `source_binding_required`. |
| `sc_validation_rule` | Specific application-owned rejection, such as `invalid_quantity`, `non_file_format`, `answer_producer_mismatch`, `missing_final_response`, `file_format_mismatch`, `narrative_source_required`, or `document_sources_required`. |
| `sc_response_failure` | A missing, incomplete, or refused planner completion, when applicable. |
| `sc_attempt` | Planner proposal number: 1 for the initial proposal and 2 for its single correction. Present on deliverables correction/failure events. |
| `sc_execution_code`, `sc_output_code` | Safe execution or output-store failure category, where available. |
| `sc_error_type`, `sc_response_type` | Exception class and, on runner admission/preparation failures, the record's Python type. |
| `sc_durable_status` | The terminal status confirmed by execution preparation, if one was recorded. Absence is not proof that the run stopped. |

These fields preserve categorical diagnostics, not raw exception text, model
responses, prompts, document content, or user identity. Hash fields accept only
64-character lowercase hexadecimal strings; diagnostic code fields accept bounded
lowercase identifiers. Unrecognized strings are not retained as text.

### Find a conversation's planning and execution failures

Use the conversation ID from the chat URL. The query hashes it locally in KQL;
there is no need to search for the prompt text or enable verbose debug logging.

```kusto
let conversationHash = hash_sha256("<conversation-id>");
traces
| where timestamp > ago(2h)
| where tostring(customDimensions.sc_conversation_id_hash) == conversationHash
| project timestamp,
    message = tostring(customDimensions.sc_message),
    stage = tostring(customDimensions.sc_stage),
    validationCode = tostring(customDimensions.sc_validation_code),
    rule = tostring(customDimensions.sc_validation_rule),
    attempt = toint(customDimensions.sc_attempt),
    executionCode = tostring(customDimensions.sc_execution_code),
    outputCode = tostring(customDimensions.sc_output_code),
    errorType = tostring(customDimensions.sc_error_type),
    responseType = tostring(customDimensions.sc_response_type),
    durableStatus = tostring(customDimensions.sc_durable_status)
| order by timestamp asc
| take 200
```

For an individual saved run in Log Analytics:

```kusto
let runHash = hash_sha256("<run-id>");
AppTraces
| where TimeGenerated > ago(2h)
| where tostring(Properties.sc_run_id_hash) == runHash
| project TimeGenerated,
    message = tostring(Properties.sc_message),
    stage = tostring(Properties.sc_stage),
    executionCode = tostring(Properties.sc_execution_code),
    outputCode = tostring(Properties.sc_output_code),
    errorType = tostring(Properties.sc_error_type),
    durableStatus = tostring(Properties.sc_durable_status)
| order by TimeGenerated asc
| take 200
```

Planning may fail inside a successful HTTP streaming response. Correlate these
events with request outcomes instead of interpreting HTTP 200 as a valid plan or
HTTP 503 as proof that no execution claim exists. Historical events before this
version may contain only string-length metadata and cannot be used to reconstruct
the exact rejected proposal.
