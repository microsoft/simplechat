// WorkflowAlertEditor.tsx
// Native alert authoring for personal and group workflows: when to alert, and the rules that decide it.

import { useId } from 'react';
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react';
import { GlassButton, Toggle } from '../ui/primitives';
import { Pill } from '../workspace/primitives';
import {
    describeWorkflowAlertCondition,
    newWorkflowAlertRule,
    workflowAlertConditionForType,
    workflowAlertConfig,
    workflowAlertRuleEnabled,
    workflowAlertRuleErrors,
    workflowAlertsEdited,
    WORKFLOW_ALERT_MAX_RULES,
    WORKFLOW_ALERT_EVALUATION_PROMPT_MAX_LENGTH,
    WORKFLOW_ALERT_SCOPELESS_CONDITIONS,
    WORKFLOW_ALERT_SEVERITY_DELIVERY,
    type WorkflowAlertConditionType,
    type WorkflowAlertSettings,
    type WorkflowAlertSeverity,
} from '../../lib/workflowAlerts';
import { isRecord } from '../../lib/workspaceAuthoring';
import type { WorkflowDefinition } from '../../lib/workflowEditor';

const fieldClass = 'mt-1 w-full min-w-0 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none';
const checkboxClass = 'accent-[var(--accent)]';

type Option = { value: string; label: string };

// The classic editor's labels, so both editors describe a setting the same way.
const MODE_OPTIONS: Option[] = [
    { value: 'off', label: 'Never notify me' },
    { value: 'rules', label: 'Only when a condition is met' },
    { value: 'every_run', label: 'On every run' },
];
const PRIORITY_OPTIONS: Option[] = [
    { value: 'none', label: 'No notification' },
    { value: 'low', label: 'Low priority' },
    { value: 'medium', label: 'Medium priority' },
    { value: 'high', label: 'High priority' },
];
const CONDITION_OPTIONS: { value: WorkflowAlertConditionType; label: string }[] = [
    { value: 'run_status', label: 'Run finished with a status' },
    { value: 'task_status', label: 'A task finished with a status' },
    { value: 'text_match', label: 'Output text matches' },
    { value: 'file_sync', label: 'File Sync result' },
    { value: 'no_output', label: 'The run produced no output' },
    { value: 'model_evaluation', label: 'A model judges a condition' },
    { value: 'agent_signal', label: 'The agent raised an alert' },
];
const RUN_STATUS_OPTIONS: Option[] = [
    { value: 'failed', label: 'Failed' },
    { value: 'completed', label: 'Completed' },
    { value: 'completed_with_task_errors', label: 'Completed with task errors' },
    { value: 'cancelled', label: 'Cancelled' },
];
const TASK_STATUS_OPTIONS: Option[] = [
    { value: 'failed', label: 'Failed' },
    { value: 'succeeded', label: 'Succeeded' },
];
const MATCH_MODE_OPTIONS: Option[] = [
    { value: 'contains_any', label: 'Contains any of' },
    { value: 'contains_all', label: 'Contains all of' },
    { value: 'not_contains', label: 'Does not contain' },
    { value: 'regex', label: 'Matches regex' },
];
const FILE_SYNC_OPTIONS: Option[] = [
    { value: 'changes_found', label: 'Changed documents were found' },
    { value: 'no_changes', label: 'No changed documents were found' },
    { value: 'sync_failed', label: 'File Sync failed' },
];
const SCOPE_OPTIONS: Option[] = [
    { value: 'final', label: 'Final output' },
    { value: 'any_task', label: 'Any task output' },
    { value: 'task', label: 'A specific task' },
];
const SEVERITY_OPTIONS: { value: WorkflowAlertSeverity; label: string }[] = [
    { value: 'info', label: 'Info' },
    { value: 'low', label: 'Low' },
    { value: 'medium', label: 'Medium' },
    { value: 'high', label: 'High' },
    { value: 'critical', label: 'Critical' },
];
const DELIVERY_OPTIONS: Option[] = [
    { value: 'default', label: 'Default for severity' },
    { value: 'notify_only', label: 'Notification bell only' },
    { value: 'popup', label: 'Pop-up alert' },
];
const ON_ERROR_OPTIONS: Option[] = [
    { value: 'skip', label: 'Skip the rule and stay silent' },
    { value: 'alert', label: 'Alert anyway so it is not missed' },
];
const SEVERITY_TONES: Record<WorkflowAlertSeverity, 'neutral' | 'accent' | 'warn' | 'danger'> = {
    info: 'neutral', low: 'neutral', medium: 'accent', high: 'warn', critical: 'danger',
};

type Rule = Record<string, unknown>;

function record(value: unknown): Record<string, unknown> {
    return isRecord(value) ? value : {};
}

function stringValue(value: unknown, fallback: string): string {
    const text = typeof value === 'string' ? value.trim().toLowerCase() : '';
    return text || fallback;
}

/** A stored list as the server reads it: a bare string is one entry (`_normalize_*_list`). */
function listValue(value: unknown): string[] {
    if (typeof value === 'string') return [value];
    return Array.isArray(value) ? value.map((item) => String(item ?? '')) : [];
}

/** Stored statuses as the server compares them: trimmed, lower-cased and de-duplicated. */
function statusValues(value: unknown): string[] {
    return [...new Set(listValue(value).map((status) => status.trim().toLowerCase()).filter(Boolean))];
}

/** A saved value the editor does not offer stays selectable, so opening a rule never changes it. */
function withCurrent(options: Option[], value: string): Option[] {
    if (options.some((option) => option.value === value)) return options;
    return [...options, { value, label: value ? `${value} (unsupported, review)` : 'Choose an option' }];
}

/**
 * The value to show for a stored workflow-level choice: the stored text when the server would
 * refuse it (so it stays visible until replaced), otherwise the resolved value.
 */
function storedChoice(stored: unknown, options: Option[], resolved: string): string {
    const text = typeof stored === 'string' ? stored.trim().toLowerCase() : '';
    return text && !options.some((option) => option.value === text) ? text : resolved;
}

function Select({ label, value, options, onChange, disabled }: {
    label: string;
    value: string;
    options: Option[];
    onChange: (value: string) => void;
    disabled?: boolean;
}) {
    return (
        <select className={fieldClass} aria-label={label} value={value} disabled={disabled}
            onChange={(event) => onChange(event.target.value)}>
            {withCurrent(options, value).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
    );
}

function StatusChoices({ legend, statuses, options, onChange }: {
    legend: string;
    statuses: string[];
    options: Option[];
    onChange: (statuses: string[]) => void;
}) {
    const choices = [...options, ...statuses.filter((status) => !options.some((option) => option.value === status))
        .map((status) => ({ value: status, label: `${status} (unsupported, review)` }))];
    return (
        <fieldset className="min-w-0 sm:col-span-2">
            <legend className="text-sm text-text-2">{legend}</legend>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-2">
                {choices.map((option) => (
                    <label key={option.value} className="flex items-center gap-2 text-sm text-text-1">
                        <input type="checkbox" className={checkboxClass} aria-label={`${legend}: ${option.label}`}
                            checked={statuses.includes(option.value)}
                            onChange={(event) => onChange(event.target.checked
                                ? [...statuses, option.value]
                                : statuses.filter((status) => status !== option.value))} />
                        {option.label}
                    </label>
                ))}
            </div>
        </fieldset>
    );
}

function ConditionFields({ position, condition, onChange }: {
    position: number;
    condition: Record<string, unknown>;
    onChange: (condition: Record<string, unknown>) => void;
}) {
    const type = stringValue(condition.type, '');
    const set = (changes: Record<string, unknown>) => onChange({ ...condition, ...changes });
    const statuses = statusValues(condition.statuses);
    if (type === 'run_status' || type === 'task_status') {
        return <StatusChoices legend={`Alert rule ${position} ${type === 'run_status' ? 'run' : 'task'} statuses`}
            statuses={statuses} options={type === 'run_status' ? RUN_STATUS_OPTIONS : TASK_STATUS_OPTIONS}
            onChange={(next) => set({ statuses: next })} />;
    }
    if (type === 'text_match') {
        const mode = stringValue(condition.mode, 'contains_any');
        const values = listValue(condition.values);
        return <>
            <label className="min-w-0 text-sm text-text-2">
                Match type
                <Select label={`Alert rule ${position} match type`} value={mode} options={MATCH_MODE_OPTIONS}
                    onChange={(next) => set(next === 'regex'
                        ? { mode: next, pattern: typeof condition.pattern === 'string' ? condition.pattern : '' }
                        : { mode: next, values })} />
            </label>
            {mode === 'regex' ? (
                <label className="min-w-0 text-sm text-text-2">
                    Regex pattern
                    <input className={fieldClass} aria-label={`Alert rule ${position} regex pattern`}
                        value={typeof condition.pattern === 'string' ? condition.pattern : ''}
                        placeholder="expires in \d+ days" spellCheck={false}
                        onChange={(event) => set({ pattern: event.target.value })} />
                    <span className="mt-1 block text-xs text-text-3">Matches are case-insensitive, across every line of the output.</span>
                </label>
            ) : (
                <div className="min-w-0 space-y-2">
                    <label className="block text-sm text-text-2">
                        Text values, one per line
                        <textarea className={`${fieldClass} min-h-20`} aria-label={`Alert rule ${position} match values`}
                            value={values.join('\n')} placeholder={'EXPIRING\nCRITICAL'}
                            onChange={(event) => set({ values: event.target.value.split('\n') })} />
                    </label>
                    <label className="flex items-center gap-2 text-sm text-text-1">
                        <input type="checkbox" className={checkboxClass} aria-label={`Alert rule ${position} matches case exactly`}
                            checked={Boolean(condition.case_sensitive)}
                            onChange={(event) => set({ case_sensitive: event.target.checked })} />
                        Match upper and lower case exactly
                    </label>
                </div>
            )}
        </>;
    }
    if (type === 'file_sync') {
        return (
            <label className="min-w-0 text-sm text-text-2">
                File Sync result
                <Select label={`Alert rule ${position} File Sync result`} value={stringValue(condition.outcome, 'changes_found')}
                    options={FILE_SYNC_OPTIONS} onChange={(next) => set({ outcome: next })} />
            </label>
        );
    }
    if (type === 'model_evaluation') {
        const prompt = typeof condition.prompt === 'string' ? condition.prompt : '';
        return (
            <label className="min-w-0 text-sm text-text-2 sm:col-span-2">
                Condition for the model to judge
                <textarea className={`${fieldClass} min-h-20`} aria-label={`Alert rule ${position} model condition`}
                    value={prompt} placeholder="Any certificate expires within 14 days."
                    onChange={(event) => set({ prompt: event.target.value })} />
                <span className="mt-1 block text-xs text-text-3">
                    A model reads the run's output and decides whether this is true.
                    {' '}{[...prompt].length.toLocaleString()} / {WORKFLOW_ALERT_EVALUATION_PROMPT_MAX_LENGTH.toLocaleString()} characters
                </span>
            </label>
        );
    }
    if (type === 'agent_signal') {
        return <>
            <label className="min-w-0 text-sm text-text-2">
                Signal name (optional)
                <input className={fieldClass} aria-label={`Alert rule ${position} signal name`}
                    value={typeof condition.signal_name === 'string' ? condition.signal_name : ''}
                    placeholder="expiring-certificates" onChange={(event) => set({ signal_name: event.target.value })} />
                <span className="mt-1 block text-xs text-text-3">Leave empty to match any alert the agent raises.</span>
            </label>
            <label className="min-w-0 text-sm text-text-2">
                Minimum signal severity
                <Select label={`Alert rule ${position} minimum signal severity`}
                    value={stringValue(condition.min_severity, 'info')} options={SEVERITY_OPTIONS}
                    onChange={(next) => set({ min_severity: next })} />
            </label>
        </>;
    }
    return null;
}

function AlertRuleRow({ rule, position, count, tasks, error, onChange, onMove, onRemove }: {
    rule: Rule;
    position: number;
    count: number;
    tasks: { id: string; name: string }[];
    error?: string;
    onChange: (rule: Rule) => void;
    onMove: (direction: -1 | 1) => void;
    onRemove: () => void;
}) {
    const headingId = useId();
    const condition = record(rule.condition);
    const scope = record(rule.scope);
    const type = stringValue(condition.type, '');
    const scopeType = stringValue(scope.type, 'final');
    const taskId = typeof scope.task_id === 'string' ? scope.task_id : '';
    const severity = stringValue(rule.severity, 'medium');
    const delivery = stringValue(rule.delivery, 'default');
    const knownSeverity = SEVERITY_OPTIONS.find((option) => option.value === severity);
    const described = describeWorkflowAlertCondition(condition);
    const name = typeof rule.name === 'string' ? rule.name : '';
    // Run-level conditions ignore the scope; it is still shown when saved with one, so it can be reset.
    const showScope = !WORKFLOW_ALERT_SCOPELESS_CONDITIONS.has(type) || scopeType !== 'final';
    const resolvedDelivery = delivery === 'default' && knownSeverity
        ? WORKFLOW_ALERT_SEVERITY_DELIVERY[knownSeverity.value] : delivery;
    const taskOptions: Option[] = [
        ...tasks.map((task, index) => ({ value: task.id, label: task.name || `Task ${index + 1}` })),
        ...(scopeType === 'task' && !tasks.some((task) => task.id === taskId)
            ? [{ value: taskId, label: taskId ? 'Removed task (review)' : 'Choose a task' }] : []),
    ];
    const set = (changes: Rule) => onChange({ ...rule, ...changes });
    return (
        <li aria-labelledby={headingId} className="space-y-3 border-t border-edge pt-4 first:border-t-0 first:pt-0">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                    <h5 id={headingId} className="break-words text-sm font-semibold text-text-1">
                        Rule {position}: {name.trim() || described}
                    </h5>
                    <p className="text-xs text-text-3">
                        {resolvedDelivery === 'popup' ? 'Opens the pop-up alert' : resolvedDelivery === 'notify_only'
                            ? 'Goes to the notification bell' : 'Delivery needs review'}
                        {workflowAlertRuleEnabled(rule) ? '' : ' · Disabled'}
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Pill tone={knownSeverity ? SEVERITY_TONES[knownSeverity.value] : 'warn'}>
                        {knownSeverity?.label ?? 'Review severity'}
                    </Pill>
                    <GlassButton type="button" size="sm" disabled={position === 1} onClick={() => onMove(-1)}
                        aria-label={`Move alert rule ${position} up`}><ArrowUp size={14} /> Up</GlassButton>
                    <GlassButton type="button" size="sm" disabled={position === count} onClick={() => onMove(1)}
                        aria-label={`Move alert rule ${position} down`}><ArrowDown size={14} /> Down</GlassButton>
                    <GlassButton type="button" size="sm" variant="danger" onClick={onRemove}
                        aria-label={`Remove alert rule ${position}`}><Trash2 size={14} /> Remove</GlassButton>
                </div>
            </div>
            {error ? <p role="alert" className="rounded-lg bg-danger-soft p-2 text-xs text-danger">{error}</p> : null}
            <div className="grid gap-3 sm:grid-cols-2">
                <label className="min-w-0 text-sm text-text-2">
                    Name
                    <input className={fieldClass} aria-label={`Alert rule ${position} name`} value={name}
                        placeholder={described} onChange={(event) => set({ name: event.target.value })} />
                </label>
                <label className="min-w-0 text-sm text-text-2">
                    Condition
                    <Select label={`Alert rule ${position} condition`} value={type}
                        options={CONDITION_OPTIONS} onChange={(next) => {
                            const nextType = next as WorkflowAlertConditionType;
                            set({
                                condition: workflowAlertConditionForType(condition, nextType),
                                ...(WORKFLOW_ALERT_SCOPELESS_CONDITIONS.has(nextType) ? { scope: { ...scope, type: 'final', task_id: '' } } : {}),
                            });
                        }} />
                </label>
                <ConditionFields position={position} condition={condition} onChange={(next) => set({ condition: next })} />
                {showScope ? (
                    <label className="min-w-0 text-sm text-text-2">
                        Look at
                        <Select label={`Alert rule ${position} looks at`} value={scopeType} options={SCOPE_OPTIONS}
                            onChange={(next) => set({ scope: {
                                ...scope, type: next, task_id: next === 'task' ? taskId || tasks[0]?.id || '' : '',
                            } })} />
                    </label>
                ) : null}
                {showScope && scopeType === 'task' ? (
                    <label className="min-w-0 text-sm text-text-2">
                        Task
                        <Select label={`Alert rule ${position} task`} value={taskId} options={taskOptions}
                            onChange={(next) => set({ scope: { ...scope, type: 'task', task_id: next } })} />
                    </label>
                ) : null}
                <label className="min-w-0 text-sm text-text-2">
                    Severity
                    <Select label={`Alert rule ${position} severity`} value={severity} options={SEVERITY_OPTIONS}
                        onChange={(next) => set({ severity: next })} />
                </label>
                <label className="min-w-0 text-sm text-text-2">
                    Delivery
                    <Select label={`Alert rule ${position} delivery`} value={delivery} options={DELIVERY_OPTIONS}
                        onChange={(next) => set({ delivery: next })} />
                </label>
            </div>
            <Toggle label={`Rule ${position} enabled`} checked={workflowAlertRuleEnabled(rule)}
                onChange={(checked) => set({ enabled: checked })} />
        </li>
    );
}

/** The Alerts section for a workflow the viewer can manage. Read-only viewers get WorkflowAlertSummary. */
export function WorkflowAlertEditor({
    workflow,
    onChange,
}: {
    workflow: WorkflowDefinition;
    onChange: (update: (workflow: WorkflowDefinition) => WorkflowDefinition) => void;
}) {
    const titleId = useId();
    const config = workflowAlertConfig(workflow);
    const rules = config.alert_rules.map((rule) => record(rule));
    const tasks = workflow.tasks.map((task) => ({ id: task.id, name: task.name }));
    const errors = new Map(workflowAlertRuleErrors(config.alert_rules, tasks.map((task) => task.id))
        .map((error) => [error.position, error.message]));
    // A stored value the server refuses stays visible, so the author can see and replace it.
    const mode = storedChoice(workflow.alert_mode, MODE_OPTIONS, config.alert_mode);
    const priority = storedChoice(workflow.alert_priority, PRIORITY_OPTIONS, config.alert_priority);
    const onError = storedChoice(record(workflow.alert_evaluation).on_error, ON_ERROR_OPTIONS,
        stringValue(record(config.alert_evaluation).on_error, 'skip'));
    const usesModel = rules.some((rule) => stringValue(record(rule.condition).type, '') === 'model_evaluation');
    const edit = (update: (settings: WorkflowAlertSettings) => WorkflowAlertSettings) =>
        onChange((current) => workflowAlertsEdited(current, update));
    const editRules = (update: (rules: unknown[]) => unknown[]) =>
        edit((settings) => ({ ...settings, alert_rules: update(settings.alert_rules) }));
    const moveRule = (index: number, direction: -1 | 1) => editRules((current) => {
        const next = [...current];
        const target = index + direction;
        if (target < 0 || target >= next.length) return current;
        [next[index], next[target]] = [next[target], next[index]];
        return next;
    });
    // Rule IDs keep each row's controls in place while rules move; a repeated stored ID gets a suffix.
    const seenKeys = new Set<string>();
    const ruleKeys = rules.map((rule, index) => {
        const id = typeof rule.id === 'string' && rule.id ? rule.id : `rule-${index}`;
        const key = seenKeys.has(id) ? `${id}-${index}` : id;
        seenKeys.add(key);
        return key;
    });
    const atLimit = rules.length >= WORKFLOW_ALERT_MAX_RULES;

    return (
        <section aria-labelledby={titleId} className="space-y-4 rounded-2xl border border-edge p-4">
            <div>
                <h3 id={titleId} className="text-base font-semibold text-text-1">Alerts</h3>
                <p className="mt-0.5 max-w-prose text-xs text-text-3">
                    Alerts notify you when a run meets a condition you define. A run that matches nothing stays silent.
                </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <label className="min-w-0 text-sm text-text-2">
                    When to alert
                    <Select label="When to alert" value={mode} options={MODE_OPTIONS}
                        onChange={(next) => edit((settings) => ({ ...settings, alert_mode: next }))} />
                </label>
                {mode === 'every_run' ? (
                    <label className="min-w-0 text-sm text-text-2">
                        Pop-up alert priority
                        <Select label="Pop-up alert priority" value={priority} options={PRIORITY_OPTIONS}
                            onChange={(next) => edit((settings) => ({ ...settings, alert_priority: next }))} />
                    </label>
                ) : null}
            </div>
            {mode === 'rules' || rules.length ? (
                <div className="space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <h4 className="text-sm font-semibold text-text-1">Alert rules</h4>
                        {mode === 'rules' ? (
                            <GlassButton type="button" size="sm" disabled={atLimit}
                                onClick={() => editRules((current) => [...current, newWorkflowAlertRule()])}>
                                <Plus size={14} /> Add alert rule
                            </GlassButton>
                        ) : null}
                    </div>
                    {mode !== 'rules' ? (
                        <p className="max-w-prose text-xs text-text-3">
                            These saved rules send alerts only when you choose “Only when a condition is met”. They are kept, and still checked, when you save.
                        </p>
                    ) : null}
                    {mode === 'rules' && !rules.length ? (
                        <p className="text-sm text-text-3">No alert rules yet. Add a rule to choose what should notify you.</p>
                    ) : null}
                    {mode === 'rules' && atLimit ? (
                        <p role="status" className="text-xs text-text-3">A workflow can have up to {WORKFLOW_ALERT_MAX_RULES} alert rules.</p>
                    ) : null}
                    {rules.length ? (
                        <ol aria-label="Alert rules" className="list-none space-y-4">
                            {rules.map((rule, index) => (
                                <AlertRuleRow key={ruleKeys[index]}
                                    rule={rule} position={index + 1} count={rules.length} tasks={tasks}
                                    error={errors.get(index + 1)}
                                    onChange={(next) => editRules((current) => current.map((item, itemIndex) => itemIndex === index ? next : item))}
                                    onMove={(direction) => moveRule(index, direction)}
                                    onRemove={() => editRules((current) => current.filter((_, itemIndex) => itemIndex !== index))} />
                            ))}
                        </ol>
                    ) : null}
                    {mode === 'rules' && rules.length ? (
                        <p className="max-w-prose text-xs text-text-3">
                            When several rules match the same run, the highest severity wins and every matched rule is listed in the alert.
                            Info and low severities go to the notification bell only. Medium and above open the pop-up alert.
                        </p>
                    ) : null}
                </div>
            ) : null}
            {usesModel ? (
                <label className="block max-w-md text-sm text-text-2">
                    If a model evaluated condition cannot be judged
                    <Select label="If a model evaluated condition cannot be judged" value={onError} options={ON_ERROR_OPTIONS}
                        onChange={(next) => edit((settings) => ({
                            ...settings, alert_evaluation: { ...record(settings.alert_evaluation), on_error: next },
                        }))} />
                </label>
            ) : null}
        </section>
    );
}
