// workflowRunAsFingerprint.ts
// Client mirror of the server's Microsoft 365 Run as execution fingerprint keys.
//
// The server hashes these workflow fields in workflow_execution_fingerprint
// (application/single_app/functions_m365_workflow_binding.py). When the hash changes,
// saving clears the stored Run as approval, so the owner must approve Run as again.
// functional_tests/test_workflow_run_as_fingerprint_parity.py fails when these lists drift.

/** Mirrors M365_WORKFLOW_FIELDS: always part of the fingerprint. */
export const WORKFLOW_RUN_AS_FINGERPRINT_BASE_FIELDS = [
    'id',
    'user_id',
    'group_id',
    'task_prompt',
    'tasks',
    'runner_type',
    'selected_agent',
    'conversation_id',
    'schedule',
    'trigger_type',
    'document_action',
    'file_sync',
    'chat_capabilities_enabled',
    'url_access_enabled',
    'model_endpoint_id',
    'model_id',
] as const;

/** Mirrors the extra keys workflow_execution_fingerprint adds when the workflow has them. */
export const WORKFLOW_RUN_AS_FINGERPRINT_OPTIONAL_FIELDS = [
    'definition_version',
    'reference_inputs',
    'durable_execution',
    'flow',
    'limits',
] as const;

/** The Run as account itself is always hashed; action bindings are fingerprinted separately at run time. */
export const WORKFLOW_RUN_AS_FINGERPRINT_ACCOUNT_FIELD = 'm365_run_as_user_id';

export const WORKFLOW_RUN_AS_FINGERPRINT_FIELDS: ReadonlySet<string> = new Set<string>([
    ...WORKFLOW_RUN_AS_FINGERPRINT_BASE_FIELDS,
    ...WORKFLOW_RUN_AS_FINGERPRINT_OPTIONAL_FIELDS,
    WORKFLOW_RUN_AS_FINGERPRINT_ACCOUNT_FIELD,
]);

export function isWorkflowRunAsFingerprintField(field: string): boolean {
    return WORKFLOW_RUN_AS_FINGERPRINT_FIELDS.has(field);
}
