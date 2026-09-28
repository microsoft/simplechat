// workflowAlerts.ts
// Workflow alert rules for the native V2 editor: the stored model, the server's resolution and
// validation, and the save overlay. Validation mirrors normalize_workflow_alert_settings in
// functions_workflow_alerts.py and returns its reviewed messages word for word, so the editor
// allows a save exactly when the server accepts it. The one exception is regex syntax: Python
// and JavaScript regular expressions differ, so a pattern Python cannot compile is left to the
// server's reviewed 400. test_workflow_alert_client_parity.py pins both.

import { isRecord, sameEditorValue } from './workspaceAuthoring';
import type { WorkflowDefinition } from './workflowEditor';

export const WORKFLOW_ALERT_FIELDS = ['alert_priority', 'alert_mode', 'alert_rules', 'alert_evaluation'] as const;
export const WORKFLOW_ALERT_MODES = ['off', 'every_run', 'rules'] as const;
export const WORKFLOW_ALERT_PRIORITIES = ['none', 'low', 'medium', 'high'] as const;
export const WORKFLOW_ALERT_SEVERITIES = ['info', 'low', 'medium', 'high', 'critical'] as const;
export const WORKFLOW_ALERT_DELIVERIES = ['default', 'notify_only', 'popup'] as const;
export const WORKFLOW_ALERT_SCOPE_TYPES = ['final', 'any_task', 'task'] as const;
export const WORKFLOW_ALERT_CONDITION_TYPES = [
    'run_status', 'task_status', 'text_match', 'file_sync', 'no_output', 'model_evaluation', 'agent_signal',
] as const;
export const WORKFLOW_ALERT_RUN_STATUSES = ['failed', 'completed', 'completed_with_task_errors', 'cancelled'] as const;
export const WORKFLOW_ALERT_TASK_STATUSES = ['failed', 'succeeded'] as const;
export const WORKFLOW_ALERT_TEXT_MATCH_MODES = ['contains_any', 'contains_all', 'not_contains', 'regex'] as const;
export const WORKFLOW_ALERT_FILE_SYNC_OUTCOMES = ['changes_found', 'no_changes', 'sync_failed'] as const;
export const WORKFLOW_ALERT_EVALUATION_ERROR_MODES = ['skip', 'alert'] as const;
/** Conditions that read run-level facts, so a rule scope does not apply (classic hides it too). */
export const WORKFLOW_ALERT_SCOPELESS_CONDITIONS = new Set<string>(['run_status', 'file_sync', 'agent_signal']);
export const WORKFLOW_ALERT_MAX_RULES = 20;
export const WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH = 120;
export const WORKFLOW_ALERT_MAX_TEXT_VALUES = 25;
export const WORKFLOW_ALERT_TEXT_VALUE_MAX_LENGTH = 400;
export const WORKFLOW_ALERT_REGEX_MAX_LENGTH = 200;
export const WORKFLOW_ALERT_EVALUATION_PROMPT_MAX_LENGTH = 2000;
/** Where a rule's alert goes when its delivery is `default` (WORKFLOW_ALERT_SEVERITY_DELIVERY). */
export const WORKFLOW_ALERT_SEVERITY_DELIVERY: Record<WorkflowAlertSeverity, 'notify_only' | 'popup'> = {
    info: 'notify_only', low: 'notify_only', medium: 'popup', high: 'popup', critical: 'popup',
};
// Python's `str.strip()` and the `\s` of a `str` pattern both use `str.isspace()`, which differs from
// JavaScript's `trim()` and `\s`: Python includes U+001C-U+001F and U+0085, and excludes U+FEFF.
const PY_WHITESPACE = '\\t\\n\\x0b\\x0c\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const PY_STRIP = new RegExp(`^[${PY_WHITESPACE}]+|[${PY_WHITESPACE}]+$`, 'g');
// The server's backtracking guard, `_NESTED_QUANTIFIER_PATTERN`, with Python's whitespace class.
const NESTED_QUANTIFIER_PATTERN = new RegExp(`\\([^)]*[*+][^)]*\\)[${PY_WHITESPACE}]*[*+]`);
const CONDITION_LABELS: Record<string, string> = {
    run_status: 'Run status',
    task_status: 'Task status',
    text_match: 'Output text',
    file_sync: 'File Sync result',
    no_output: 'No output produced',
    model_evaluation: 'Model evaluated condition',
    agent_signal: 'Agent raised alert',
};

export type WorkflowAlertMode = typeof WORKFLOW_ALERT_MODES[number];
export type WorkflowAlertPriority = typeof WORKFLOW_ALERT_PRIORITIES[number];
export type WorkflowAlertSeverity = typeof WORKFLOW_ALERT_SEVERITIES[number];
export type WorkflowAlertConditionType = typeof WORKFLOW_ALERT_CONDITION_TYPES[number];
export type WorkflowAlertField = typeof WORKFLOW_ALERT_FIELDS[number];

/** A stored rule. Fields the editor does not know are kept on the object and sent back. */
export interface WorkflowAlertRule {
    id?: string;
    name?: string;
    enabled?: unknown;
    severity?: string;
    delivery?: string;
    scope?: Record<string, unknown>;
    condition?: Record<string, unknown>;
    order?: number;
    [key: string]: unknown;
}

/** The four stored alert fields the editor writes, in the server's shape. */
export interface WorkflowAlertSettings {
    alert_mode: string;
    alert_priority: string;
    alert_rules: unknown[];
    alert_evaluation: Record<string, unknown>;
}

export interface WorkflowAlertSummary {
    mode: WorkflowAlertMode;
    priority: WorkflowAlertPriority;
    ruleCount: number;
}

/** Python's `str(value or fallback)`: falsy values take the fallback, and other values never match a keyword. */
export function pyText(value: unknown, fallback = ''): string {
    if (value === null || value === undefined || value === false || value === 0 || value === '' ||
        Array.isArray(value) && value.length === 0 || isRecord(value) && Object.keys(value).length === 0) {
        return fallback;
    }
    if (value === true) return 'True';
    if (typeof value === 'string') return value;
    // Python renders containers as their repr, which can never equal a status, mode or type keyword.
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

/** Python measures text in code points; JavaScript `length` counts UTF-16 units. */
function textLength(text: string): number {
    return [...text].length;
}

/** Python's `str.strip()` with no arguments, which removes Unicode whitespace from both ends. */
export function pyStrip(text: string): string {
    return text.replace(PY_STRIP, '');
}

function includes<T extends string>(values: readonly T[], value: string): value is T {
    return (values as readonly string[]).includes(value);
}

export function workflowLegacyAlertRules(priority: string): WorkflowAlertRule[] {
    if (!includes(WORKFLOW_ALERT_PRIORITIES, priority) || priority === 'none') return [];
    // Mirrors build_legacy_alert_rules: a priority-only record kept alerting on every finished run.
    return [
        {
            id: 'legacy-run-failed', name: 'Run failed', enabled: true, severity: 'high', delivery: 'popup',
            scope: { type: 'final', task_id: '' }, condition: { type: 'run_status', statuses: ['failed'] }, order: 1,
        },
        {
            id: 'legacy-run-completed', name: 'Run completed', enabled: true, severity: priority, delivery: 'popup',
            scope: { type: 'final', task_id: '' }, condition: { type: 'run_status', statuses: ['completed'] }, order: 2,
        },
    ];
}

/** The configuration the server evaluates for a stored record (`resolve_workflow_alert_config`). */
export function workflowAlertConfig(workflow: Record<string, unknown> | null): WorkflowAlertSettings & { legacy: boolean } {
    const record = workflow ?? {};
    const storedRules = Array.isArray(record.alert_rules) ? record.alert_rules : null;
    const storedMode = pyStrip(pyText(record.alert_mode)).toLowerCase();
    const storedPriority = pyStrip(pyText(record.alert_priority, 'none')).toLowerCase();
    const priority = includes(WORKFLOW_ALERT_PRIORITIES, storedPriority) ? storedPriority : 'none';
    const evaluation = isRecord(record.alert_evaluation) ? record.alert_evaluation : {};
    const onError = pyStrip(pyText(evaluation.on_error, 'skip')).toLowerCase() || 'skip';
    const settings = (mode: string, rules: unknown[], legacy = false) => ({
        alert_mode: mode, alert_priority: priority, alert_rules: rules,
        alert_evaluation: { ...evaluation, on_error: onError }, legacy,
    });
    if (includes(WORKFLOW_ALERT_MODES, storedMode)) return settings(storedMode, storedRules ?? []);
    if (storedRules?.length) return settings('rules', storedRules);
    if (priority !== 'none') return settings('rules', workflowLegacyAlertRules(priority), true);
    return settings('off', []);
}

export function workflowAlertSummary(workflow: Record<string, unknown> | null): WorkflowAlertSummary {
    const config = workflowAlertConfig(workflow);
    return {
        mode: config.alert_mode as WorkflowAlertMode,
        priority: config.alert_priority as WorkflowAlertPriority,
        ruleCount: config.alert_rules.length,
    };
}

/** The alert fields exactly as stored on a record, for comparison and for the save payload. */
function storedAlertFields(workflow: Record<string, unknown> | null): Partial<Record<WorkflowAlertField, unknown>> {
    const record = workflow ?? {};
    return Object.fromEntries(WORKFLOW_ALERT_FIELDS
        .filter((field) => Object.hasOwn(record, field))
        .map((field) => [field, record[field]]));
}

/** The alert fields a save sends: the loaded ones unless the editor changed any of them. */
export function workflowAlertsForSave(
    draft: WorkflowDefinition,
    original: WorkflowDefinition | null,
): Partial<Record<WorkflowAlertField, unknown>> {
    const loaded = storedAlertFields(original);
    const drafted = storedAlertFields(draft);
    if (sameEditorValue(loaded, drafted)) return {};
    return structuredClone(drafted);
}

/** Apply an editor change. The first edit writes all four fields explicitly, as classic does. */
export function workflowAlertsEdited(
    draft: WorkflowDefinition,
    update: (settings: WorkflowAlertSettings) => WorkflowAlertSettings,
): WorkflowDefinition {
    const config = workflowAlertConfig(draft);
    const current: WorkflowAlertSettings = structuredClone({
        alert_mode: config.alert_mode,
        alert_priority: config.alert_priority,
        alert_rules: config.alert_rules,
        alert_evaluation: config.alert_evaluation,
    });
    return { ...draft, ...update(current) };
}

function newRuleId(): string {
    const cryptoApi = globalThis.crypto;
    if (cryptoApi?.randomUUID) return cryptoApi.randomUUID();
    return `alert-rule-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Classic's default rule, notifying loudly when a run fails. It has no name, so its heading and the
 * name the server stores (`describe_alert_condition`) follow the condition as the author changes it.
 */
export function newWorkflowAlertRule(): WorkflowAlertRule {
    return {
        id: newRuleId(), name: '', enabled: true, severity: 'high', delivery: 'default',
        scope: { type: 'final', task_id: '' }, condition: { type: 'run_status', statuses: ['failed'] },
    };
}

/** Whether the server treats a stored rule as enabled (`normalize_alert_rule`). */
export function workflowAlertRuleEnabled(rule: Record<string, unknown>): boolean {
    if (!Object.hasOwn(rule, 'enabled')) return true;
    const value = rule.enabled;
    if (typeof value === 'string') return ['1', 'true', 'yes', 'on'].includes(pyStrip(value).toLowerCase());
    return pyText(value) !== '';
}

// Condition fields some condition type uses; any other key on a condition is carried across a type change.
const WORKFLOW_ALERT_CONDITION_KEYS = new Set([
    'type', 'statuses', 'mode', 'pattern', 'values', 'case_sensitive', 'outcome', 'prompt', 'signal_name', 'min_severity',
]);

/** The condition for a new type, keeping any field the editor does not model. */
export function workflowAlertConditionForType(
    current: Record<string, unknown>,
    type: WorkflowAlertConditionType,
): Record<string, unknown> {
    const kept = Object.fromEntries(Object.entries(current).filter(([key]) => !WORKFLOW_ALERT_CONDITION_KEYS.has(key)));
    return { ...kept, ...newWorkflowAlertCondition(type) };
}

/** A fresh condition for a changed type; the server rebuilds conditions per type, so old fields go. */
export function newWorkflowAlertCondition(type: WorkflowAlertConditionType): Record<string, unknown> {
    switch (type) {
        case 'run_status':
        case 'task_status':
            return { type, statuses: ['failed'] };
        case 'text_match':
            return { type, mode: 'contains_any', values: [], case_sensitive: false };
        case 'file_sync':
            return { type, outcome: 'changes_found' };
        case 'model_evaluation':
            return { type, prompt: '' };
        case 'agent_signal':
            return { type, signal_name: '', min_severity: 'info' };
        default:
            return { type };
    }
}

class AlertRuleRefused extends Error {}

function refuse(message: string): never {
    throw new AlertRuleRefused(message);
}

function statusList(values: unknown, allowed: readonly string[], position: number, kind: 'run' | 'task'): string[] {
    const list = typeof values === 'string' ? [values] : values;
    if (!Array.isArray(list)) refuse(`Alert rule ${position} ${kind} statuses must be a list.`);
    const normalized: string[] = [];
    for (const raw of list) {
        const value = pyStrip(pyText(raw)).toLowerCase();
        if (!value) continue;
        if (!allowed.includes(value)) refuse(`Alert rule ${position} has an unsupported ${kind} status.`);
        if (!normalized.includes(value)) normalized.push(value);
    }
    if (!normalized.length) refuse(`Alert rule ${position} needs at least one ${kind} status.`);
    return normalized;
}

function matchValues(values: unknown, position: number): string[] {
    const list = typeof values === 'string' ? [values] : values;
    if (!Array.isArray(list)) refuse(`Alert rule ${position} match values must be a list of text.`);
    const normalized: string[] = [];
    for (const raw of list) {
        const value = pyStrip(pyText(raw));
        if (!value) continue;
        if (textLength(value) > WORKFLOW_ALERT_TEXT_VALUE_MAX_LENGTH) {
            refuse(`Alert rule ${position} match values must each be ${WORKFLOW_ALERT_TEXT_VALUE_MAX_LENGTH} characters or fewer.`);
        }
        if (!normalized.includes(value)) normalized.push(value);
    }
    if (!normalized.length) refuse(`Alert rule ${position} needs at least one match value.`);
    if (normalized.length > WORKFLOW_ALERT_MAX_TEXT_VALUES) {
        refuse(`Alert rule ${position} can match up to ${WORKFLOW_ALERT_MAX_TEXT_VALUES} values.`);
    }
    return normalized;
}

/** The condition as the server normalizes it (`_normalize_alert_condition`). */
function normalizedCondition(raw: unknown, position: number): Record<string, unknown> {
    const condition = isRecord(raw) ? raw : {};
    const type = pyStrip(pyText(condition.type)).toLowerCase();
    if (!includes(WORKFLOW_ALERT_CONDITION_TYPES, type)) refuse(`Alert rule ${position} has an unsupported condition type.`);
    if (type === 'run_status') return { type, statuses: statusList(condition.statuses, WORKFLOW_ALERT_RUN_STATUSES, position, 'run') };
    if (type === 'task_status') return { type, statuses: statusList(condition.statuses, WORKFLOW_ALERT_TASK_STATUSES, position, 'task') };
    if (type === 'text_match') {
        const mode = pyStrip(pyText(condition.mode, 'contains_any')).toLowerCase() || 'contains_any';
        if (!includes(WORKFLOW_ALERT_TEXT_MATCH_MODES, mode)) {
            refuse(`Alert rule ${position} text match must be contains_any, contains_all, not_contains or regex.`);
        }
        if (mode === 'regex') {
            const pattern = pyStrip(pyText(condition.pattern));
            if (!pattern) refuse(`Alert rule ${position} needs a regex pattern.`);
            if (textLength(pattern) > WORKFLOW_ALERT_REGEX_MAX_LENGTH) {
                refuse(`Alert rule ${position} regex pattern must be ${WORKFLOW_ALERT_REGEX_MAX_LENGTH} characters or fewer.`);
            }
            if (NESTED_QUANTIFIER_PATTERN.test(pattern)) {
                refuse(`Alert rule ${position} regex pattern uses nested quantifiers, which are not allowed.`);
            }
            return { type, mode, pattern, values: [], case_sensitive: false };
        }
        return { type, mode, pattern: '', values: matchValues(condition.values, position), case_sensitive: Boolean(condition.case_sensitive) };
    }
    if (type === 'file_sync') {
        const outcome = pyStrip(pyText(condition.outcome)).toLowerCase();
        if (!includes(WORKFLOW_ALERT_FILE_SYNC_OUTCOMES, outcome)) {
            refuse(`Alert rule ${position} File Sync result must be changes_found, no_changes or sync_failed.`);
        }
        return { type, outcome };
    }
    if (type === 'no_output') return { type };
    if (type === 'model_evaluation') {
        const prompt = pyStrip(pyText(condition.prompt));
        if (!prompt) refuse(`Alert rule ${position} needs a condition for the model to judge.`);
        if (textLength(prompt) > WORKFLOW_ALERT_EVALUATION_PROMPT_MAX_LENGTH) {
            refuse(`Alert rule ${position} model condition must be ${WORKFLOW_ALERT_EVALUATION_PROMPT_MAX_LENGTH} characters or fewer.`);
        }
        return { type, prompt };
    }
    const signalName = pyStrip(pyText(condition.signal_name));
    if (textLength(signalName) > WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH) {
        refuse(`Alert rule ${position} signal name must be ${WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH} characters or fewer.`);
    }
    const minimum = pyStrip(pyText(condition.min_severity)).toLowerCase();
    return { type, signal_name: signalName, min_severity: includes(WORKFLOW_ALERT_SEVERITIES, minimum) ? minimum : 'info' };
}

function normalizedScope(raw: unknown, taskIds: string[] | null, position: number): { type: string; task_id: string } {
    const scope = isRecord(raw) ? raw : {};
    const type = pyStrip(pyText(scope.type, 'final')).toLowerCase() || 'final';
    if (!includes(WORKFLOW_ALERT_SCOPE_TYPES, type)) {
        refuse(`Alert rule ${position} must look at the final output, any task output, or a specific task.`);
    }
    if (type !== 'task') return { type, task_id: '' };
    const taskId = pyStrip(pyText(scope.task_id));
    if (!taskId) refuse(`Alert rule ${position} needs a task to watch.`);
    if (taskIds && !taskIds.includes(taskId)) refuse(`Alert rule ${position} watches a task that is no longer in this workflow.`);
    return { type, task_id: taskId };
}

/** The name the server gives a rule saved without one (`describe_alert_condition`). */
export function describeWorkflowAlertCondition(raw: unknown): string {
    const condition = isRecord(raw) ? raw : {};
    const type = pyStrip(pyText(condition.type)).toLowerCase();
    const label = CONDITION_LABELS[type] ?? 'Condition';
    // An f-string prints a missing value as None, and ', '.join treats a missing list as empty.
    const format = (value: unknown) => (value === null || value === undefined ? 'None'
        : value === true ? 'True' : value === false ? 'False' : String(value));
    const list = (value: unknown) => (Array.isArray(value) && value.length ? value.map(format) : []).join(', ');
    if (type === 'run_status' || type === 'task_status') return `${label} is ${list(condition.statuses)}`;
    if (type === 'text_match') {
        if (condition.mode === 'regex') return `${label} matches /${format(condition.pattern)}/`;
        const modes: Record<string, string> = {
            contains_any: 'contains any of', contains_all: 'contains all of', not_contains: 'does not contain',
        };
        return `${label} ${modes[String(condition.mode)] ?? 'contains'} ${list(condition.values)}`;
    }
    if (type === 'file_sync') return `${label} is ${format(condition.outcome)}`;
    if (type === 'model_evaluation') return `${label}: ${format(condition.prompt)}`;
    if (type === 'agent_signal') return pyText(condition.signal_name) ? `${label} named ${format(condition.signal_name)}` : label;
    return label;
}

/** Validate one rule the way `normalize_alert_rule` does, returning its normalized condition. */
function checkRule(raw: unknown, taskIds: string[] | null, position: number): void {
    if (!isRecord(raw)) refuse(`Alert rule ${position} is invalid.`);
    const condition = normalizedCondition(raw.condition, position);
    normalizedScope(raw.scope, taskIds, position);
    const name = pyStrip(pyText(raw.name)) || describeWorkflowAlertCondition(condition);
    if (textLength(name) > WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH) {
        refuse(`Alert rule ${position} name must be ${WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH} characters or fewer.`);
    }
    const delivery = pyStrip(pyText(raw.delivery, 'default')).toLowerCase() || 'default';
    if (!includes(WORKFLOW_ALERT_DELIVERIES, delivery)) refuse(`Alert rule ${position} delivery must be default, notify_only or popup.`);
    const severity = pyStrip(pyText(raw.severity, 'medium')).toLowerCase();
    if (!includes(WORKFLOW_ALERT_SEVERITIES, severity)) {
        refuse(`Alert rule ${position} severity must be info, low, medium, high or critical.`);
    }
}

function refusal(check: () => void): string | null {
    try {
        check();
        return null;
    } catch (cause: unknown) {
        if (cause instanceof AlertRuleRefused) return cause.message;
        throw cause;
    }
}

/** Every rule's first problem, in rule order, as `{position, message}` so a row can show its own. */
export function workflowAlertRuleErrors(rules: unknown, taskIds: string[] | null): { position: number; message: string }[] {
    if (rules === null || rules === undefined) return [];
    if (!Array.isArray(rules)) return [{ position: 0, message: 'Alert rules must be a list.' }];
    const errors: { position: number; message: string }[] = [];
    if (rules.length > WORKFLOW_ALERT_MAX_RULES) {
        errors.push({ position: 0, message: `A workflow can have up to ${WORKFLOW_ALERT_MAX_RULES} alert rules.` });
    }
    rules.forEach((rule, index) => {
        const message = refusal(() => checkRule(rule, taskIds, index + 1));
        if (message) errors.push({ position: index + 1, message });
    });
    return errors;
}

/**
 * What the server would refuse in this save, mirroring `normalize_workflow_alert_settings` over the
 * alert fields actually sent. The first entry is the message the server returns.
 */
export function workflowAlertErrors(
    sent: Partial<Record<WorkflowAlertField, unknown>>,
    existing: Record<string, unknown> | null,
    taskIds: string[],
): string[] {
    const errors: string[] = [];
    const stored = workflowAlertConfig(existing);
    const priority = pyStrip(pyText(Object.hasOwn(sent, 'alert_priority') ? sent.alert_priority : stored.alert_priority, 'none'))
        .toLowerCase() || 'none';
    const priorityValid = includes(WORKFLOW_ALERT_PRIORITIES, priority);
    if (!priorityValid) errors.push('Alert priority must be none, low, medium or high.');

    const sendsRules = Object.hasOwn(sent, 'alert_rules');
    const rules = sendsRules ? sent.alert_rules : stored.alert_rules;
    // The server checks task scopes only for rules the request sends, not for stored ones.
    const ruleErrors = workflowAlertRuleErrors(rules, sendsRules ? taskIds : null);
    errors.push(...ruleErrors.map((error) => error.message));
    let ruleCount = Array.isArray(rules) ? rules.length : 0;

    let mode: string;
    if (Object.hasOwn(sent, 'alert_mode')) {
        mode = pyStrip(pyText(sent.alert_mode)).toLowerCase();
        if (!includes(WORKFLOW_ALERT_MODES, mode)) errors.push('Alert mode must be off, every_run or rules.');
    } else if (sendsRules) {
        mode = ruleCount ? 'rules' : 'off';
    } else {
        mode = stored.alert_mode || 'off';
        // The server materializes legacy rules only from a valid priority; an invalid one has already failed.
        if (mode === 'off' && priorityValid && priority !== 'none' && !ruleCount) {
            mode = 'rules';
            ruleCount = workflowLegacyAlertRules(priority).length;
        }
    }
    if (mode === 'rules' && !ruleCount) errors.push('Add at least one alert rule, or choose a different alert mode.');
    if (mode === 'every_run' && priority === 'none') {
        errors.push('Choose a pop-up priority for alerts on every run, or choose a different alert mode.');
    }

    const evaluation = Object.hasOwn(sent, 'alert_evaluation') ? sent.alert_evaluation : stored.alert_evaluation;
    const onError = pyStrip(pyText(isRecord(evaluation) ? evaluation.on_error : undefined, 'skip')).toLowerCase() || 'skip';
    if (!includes(WORKFLOW_ALERT_EVALUATION_ERROR_MODES, onError)) {
        errors.push('Choose skip or alert for model-evaluated conditions that cannot be judged.');
    }
    return errors;
}

/** The problems in the alert fields this draft would save, checked against its current tasks. */
export function workflowAlertDraftErrors(draft: WorkflowDefinition, original: WorkflowDefinition | null): string[] {
    const sent = { ...storedAlertFields(original), ...workflowAlertsForSave(draft, original) };
    return workflowAlertErrors(sent, original, draft.tasks.map((task) => task.id));
}
