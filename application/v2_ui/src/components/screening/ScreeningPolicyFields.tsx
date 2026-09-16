// ScreeningPolicyFields.tsx
// Controlled policy editing; no raw settings, connection credentials, or HTTP calls.

import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import type { DefaultModelChoice } from '../../lib/modelConnections';
import {
    screeningModelCatalog,
    screeningModelIndex,
    type ScreeningAiPolicy,
    type ScreeningPolicy,
    type ScreeningPolicyTemplates,
    type ScreeningRule,
} from '../../lib/contentScreeningPolicy';
import { ModelPicker } from '../admin/ModelPicker';
import { GlassButton, Toggle } from '../ui/primitives';
import { ScreeningField, ScreeningNumberField, screeningInputClass } from './ScreeningFields';

function RuleFields({
    rule,
    templates,
    disabled,
    onChange,
    onRemove,
}: {
    rule: ScreeningRule;
    templates: ScreeningPolicyTemplates;
    disabled: boolean;
    onChange: (rule: ScreeningRule) => void;
    onRemove: () => void;
}) {
    const update = (change: Partial<ScreeningRule>) => onChange({ ...rule, ...change });
    return (
        <fieldset disabled={disabled} className="min-w-0 space-y-3 rounded-xl border border-edge p-3">
            <legend className="max-w-full px-1 text-xs font-semibold text-text-2">
                {rule.name || 'New rule'} · {rule.type === 'pii' ? 'Built-in PII' : rule.type}
            </legend>
            <div className="grid gap-3 sm:grid-cols-2">
                <ScreeningField label="Rule name">
                    {(id) => <input id={id} className={screeningInputClass} value={rule.name}
                        onChange={(event) => update({ name: event.target.value })} />}
                </ScreeningField>
                <ScreeningField label="Category">
                    {(id) => <input id={id} className={screeningInputClass} value={rule.category}
                        onChange={(event) => update({ category: event.target.value })} />}
                </ScreeningField>
                <ScreeningField label="Severity">
                    {(id) => (
                        <select id={id} className={screeningInputClass} value={rule.severity}
                            onChange={(event) => update({ severity: event.target.value })}>
                            {[...new Set([rule.severity, ...templates.severities])].filter(Boolean).map((severity) => (
                                <option key={severity} value={severity}>{severity}</option>
                            ))}
                        </select>
                    )}
                </ScreeningField>
                <Toggle label="Rule enabled" checked={rule.enabled} disabled={disabled}
                    onChange={(enabled) => update({ enabled })} />
            </div>
            {rule.type === 'pii' ? (
                <ScreeningField label="Built-in PII detector"
                    help="Structured pattern checks are locale-dependent; they do not detect every name, address, or sensitive value.">
                    {(id) => (
                        <select id={id} className={screeningInputClass} value={rule.pii_type ?? ''}
                            onChange={(event) => update({ pii_type: event.target.value })}>
                            {!templates.piiTypes.some((item) => item.value === rule.pii_type) ? (
                                <option value={rule.pii_type ?? ''}>{rule.pii_type || 'Choose a detector'}</option>
                            ) : null}
                            {templates.piiTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                        </select>
                    )}
                </ScreeningField>
            ) : rule.type === 'regex' ? (
                <ScreeningField label="Regular expression"
                    help="Validated and time-bounded on the server. Use sample testing before saving; patterns are not executed by the browser.">
                    {(id) => <textarea id={id} rows={3} spellCheck={false} className={`${screeningInputClass} font-mono`}
                        value={rule.pattern ?? ''} onChange={(event) => update({ pattern: event.target.value })} />}
                </ScreeningField>
            ) : (
                <ScreeningField label="Literal values or phrases" help="One exact value per line. Whitespace inside each value is preserved.">
                    {(id) => <textarea id={id} rows={3} spellCheck={false} className={screeningInputClass}
                        value={(rule.values ?? []).join('\n')}
                        onChange={(event) => update({ values: event.target.value.split('\n') })} />}
                </ScreeningField>
            )}
            {rule.type !== 'pii' ? (
                <div className="flex flex-wrap gap-x-6">
                    <Toggle label="Case sensitive" checked={rule.case_sensitive === true} disabled={disabled}
                        onChange={(case_sensitive) => update({ case_sensitive })} />
                    {rule.type === 'literal' ? (
                        <Toggle label="Whole words only" checked={rule.whole_word === true} disabled={disabled}
                            onChange={(whole_word) => update({ whole_word })} />
                    ) : null}
                </div>
            ) : null}
            {!disabled ? (
                <GlassButton type="button" size="sm" variant="danger" onClick={onRemove}
                    aria-label={`Remove rule ${rule.name || 'New rule'}`}>
                    <Trash2 size={13} />Remove rule
                </GlassButton>
            ) : null}
        </fieldset>
    );
}

export function ScreeningPolicyFields({
    policy,
    templates,
    models,
    disabled = false,
    baseline = false,
    onChange,
}: {
    policy: ScreeningPolicy;
    templates: ScreeningPolicyTemplates;
    models: DefaultModelChoice[];
    disabled?: boolean;
    baseline?: boolean;
    onChange: (policy: ScreeningPolicy) => void;
}) {
    const [templateIndex, setTemplateIndex] = useState('');
    const [criteriaIndex, setCriteriaIndex] = useState('');
    const updateAi = (change: Partial<ScreeningAiPolicy>) =>
        onChange({ ...policy, ai: { ...policy.ai, ...change } });
    const approvedModels = models;
    const catalog = screeningModelCatalog(approvedModels);

    return (
        <div className="min-w-0 space-y-5">
            <Toggle label={baseline ? 'Baseline policy enabled' : 'Workspace additions enabled'}
                checked={policy.enabled} disabled={disabled}
                description={baseline
                    ? 'Applies required checks to enrolled workspace content. Enrollment is controlled by the separate administrative capability.'
                    : 'Adds checks to the mandatory baseline; disabling additions never disables baseline checks or releases a hold.'}
                onChange={(enabled) => onChange({ ...policy, enabled })} />

            <section className="min-w-0 space-y-3" aria-label="Deterministic screening rules">
                <h3 className="text-sm font-semibold text-text-1">Deterministic checks</h3>
                {policy.rules.map((rule, index) => (
                    <RuleFields key={rule.id} rule={rule} templates={templates} disabled={disabled}
                        onChange={(next) => onChange({ ...policy, rules: policy.rules.map((item, i) => i === index ? next : item) })}
                        onRemove={() => onChange({ ...policy, rules: policy.rules.filter((_, i) => i !== index) })} />
                ))}
                {!policy.rules.length ? <p className="text-xs text-text-3">No additional deterministic rules configured.</p> : null}
                {!disabled ? (
                    <div className="flex flex-wrap items-end gap-2">
                        <div className="min-w-0 flex-1">
                            <ScreeningField label="Starter rule">
                                {(id) => (
                                    <select id={id} className={screeningInputClass} value={templateIndex}
                                        onChange={(event) => setTemplateIndex(event.target.value)}>
                                        <option value="">Choose a server-provided starter</option>
                                        {templates.rules.map((rule, index) => (
                                            <option key={`${rule.id}-${index}`} value={index}>{rule.name} · {rule.type}</option>
                                        ))}
                                    </select>
                                )}
                            </ScreeningField>
                        </div>
                        <GlassButton type="button" size="sm" variant="subtle" disabled={templateIndex === ''}
                            onClick={() => {
                                const template = templates.rules[Number(templateIndex)];
                                if (template) {
                                    onChange({ ...policy, rules: [...policy.rules, {
                                        ...structuredClone(template), id: crypto.randomUUID(),
                                    }] });
                                    setTemplateIndex('');
                                }
                            }}>
                            <Plus size={14} />Add rule
                        </GlassButton>
                    </div>
                ) : null}
            </section>

            {baseline ? (
                <fieldset disabled={disabled} className="space-y-2 rounded-xl border border-edge p-3">
                    <legend className="px-1 text-sm font-semibold text-text-1">Approved scanner models</legend>
                    <p className="text-xs text-text-3">
                        Choose from configured AI Connections. Workspaces can select these models or the selected baseline scanner;
                        protected extracted content is sent to the explicitly selected model for required checks.
                    </p>
                    {models.length ? models.map((model, index) => {
                        const selected = policy.allowed_models?.some(
                            (item) => item.endpoint_id === model.endpointId && item.model_id === model.modelId,
                        ) ?? false;
                        return (
                            <label key={index} className="flex items-start gap-2 py-1 text-sm text-text-2">
                                <input type="checkbox" className="mt-1 accent-[var(--accent)]" checked={selected}
                                    onChange={(event) => {
                                        const others = (policy.allowed_models ?? []).filter(
                                            (item) => item.endpoint_id !== model.endpointId || item.model_id !== model.modelId,
                                        );
                                        onChange({ ...policy, allowed_models: event.target.checked
                                            ? [...others, { endpoint_id: model.endpointId, model_id: model.modelId }] : others });
                                    }} />
                                {model.modelLabel} · {screeningModelCatalog([model])[0].endpoint}
                            </label>
                        );
                    }) : <p className="text-xs text-warn">No configured scanner models are available.</p>}
                </fieldset>
            ) : null}

            <section className="space-y-3 border-t border-edge pt-4" aria-label="Model screening">
                <h3 className="text-sm font-semibold text-text-1">Optional model checks</h3>
                <Toggle label="Model screening enabled" checked={policy.ai.enabled} disabled={disabled}
                    description="Once enabled, model checks must complete as well as deterministic checks. Errors, refusals, and partial coverage keep content held."
                    onChange={(enabled) => updateAi({ enabled })} />
                <ModelPicker field={{
                    key: baseline ? 'screening-baseline-model' : 'screening-workspace-model',
                    type: 'component', label: 'Scanner model', placeholder: 'Select an approved configured model',
                    help: 'Uses saved model references, not a separately configured endpoint or credential.',
                }} models={catalog} value={screeningModelIndex(approvedModels, policy.ai.model_selection)}
                    disabled={disabled} onChange={(value) => {
                        const selected = value === '' ? undefined : approvedModels[Number(value)];
                        updateAi({ model_selection: selected
                            ? { endpoint_id: selected.endpointId, model_id: selected.modelId } : null });
                    }} />
                {!disabled && templates.ai.length ? (
                    <div className="flex flex-wrap items-end gap-2">
                        <div className="min-w-0 flex-1">
                            <ScreeningField label="AI starter criteria">
                                {(id) => (
                                    <select id={id} className={screeningInputClass} value={criteriaIndex}
                                        onChange={(event) => setCriteriaIndex(event.target.value)}>
                                        <option value="">Choose a server-provided criterion</option>
                                        {templates.ai.map((template, index) => <option key={template.id} value={index}>{template.name}</option>)}
                                    </select>
                                )}
                            </ScreeningField>
                        </div>
                        <GlassButton type="button" size="sm" variant="subtle" disabled={criteriaIndex === ''}
                            onClick={() => {
                                const template = templates.ai[Number(criteriaIndex)];
                                if (template) {
                                    updateAi({ instructions: template.instructions });
                                    setCriteriaIndex('');
                                }
                            }}>Use criteria</GlassButton>
                    </div>
                ) : null}
                <ScreeningField label="Model instructions"
                    help="Describe what to flag. The trusted evaluation scaffold stays server-owned; document text is untrusted data, not instructions.">
                    {(id) => <textarea id={id} rows={5} className={screeningInputClass}
                        disabled={disabled} value={policy.ai.instructions}
                        onChange={(event) => updateAi({ instructions: event.target.value })} />}
                </ScreeningField>
                <div className="grid gap-3 sm:grid-cols-2">
                    <ScreeningField label="Model finding severity">
                        {(id) => (
                            <select id={id} className={screeningInputClass} value={policy.ai.severity} disabled={disabled}
                                onChange={(event) => updateAi({ severity: event.target.value })}>
                                {[...new Set([policy.ai.severity, ...templates.severities])].filter(Boolean).map((severity) => (
                                    <option key={severity} value={severity}>{severity}</option>
                                ))}
                            </select>
                        )}
                    </ScreeningField>
                    <ScreeningField label="Model finding category">
                        {(id) => <input id={id} className={screeningInputClass} value={policy.ai.category} disabled={disabled}
                            onChange={(event) => updateAi({ category: event.target.value })} />}
                    </ScreeningField>
                    <ScreeningField label="Scan window unit">
                        {(id) => (
                            <select id={id} className={screeningInputClass} value={policy.ai.window_unit} disabled={disabled}
                                onChange={(event) => updateAi({ window_unit: event.target.value === 'pages' ? 'pages' : 'chunks' })}>
                                <option value="pages">Pages</option>
                                <option value="chunks">Chunks</option>
                            </select>
                        )}
                    </ScreeningField>
                    <ScreeningNumberField label="Pages or chunks per window" value={policy.ai.window_size}
                        min={1} disabled={disabled} onChange={(window_size) => updateAi({ window_size })}
                        help="Use 1 for a single page/chunk; larger values form bounded batches." />
                    <ScreeningNumberField label="Maximum characters per window" value={policy.ai.max_characters}
                        min={1} disabled={disabled} onChange={(max_characters) => updateAi({ max_characters })} />
                    <ScreeningNumberField label="Boundary overlap characters" value={policy.ai.overlap_characters}
                        disabled={disabled} onChange={(overlap_characters) => updateAi({ overlap_characters })} />
                </div>
                <p className="text-xs text-text-3">
                    Oversized units are split, not truncated. Every tail and required window must be covered.
                    Extracted segments without a physical-page mapping are never presented as PDF pages.
                </p>
            </section>
            <section className="space-y-3 border-t border-edge pt-4" aria-label="Screening execution limits">
                <h3 className="text-sm font-semibold text-text-1">Execution limits</h3>
                <p className="text-xs text-text-3">Server-defined budgets fail closed rather than treating skipped work as clean.</p>
                <div className="grid gap-3 sm:grid-cols-2">
                    {Object.entries(policy.limits).map(([key, value]) => (
                        <ScreeningNumberField key={key} label={key.replaceAll('_', ' ')} value={value}
                            step="any" disabled={disabled}
                            onChange={(next) => onChange({ ...policy, limits: { ...policy.limits, [key]: next } })} />
                    ))}
                </div>
            </section>
        </div>
    );
}
