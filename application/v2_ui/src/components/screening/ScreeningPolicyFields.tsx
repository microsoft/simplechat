// ScreeningPolicyFields.tsx
// Controlled policy editing; no raw settings, connection credentials, or HTTP calls.

import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import type { DefaultModelChoice } from '../../lib/modelConnections';
import {
    addScreeningStarterPack,
    newCustomScreeningRule,
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
                    <Toggle label="Whole words only" checked={rule.whole_word === true} disabled={disabled}
                        onChange={(whole_word) => update({ whole_word })} />
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
    const [packIndex, setPackIndex] = useState('');
    const [criteriaIndex, setCriteriaIndex] = useState('');
    const updateAi = (change: Partial<ScreeningAiPolicy>) =>
        onChange({ ...policy, ai: { ...policy.ai, ...change } });
    const approvedModels = models;
    const catalog = screeningModelCatalog(approvedModels);
    const aiDisabled = disabled || !policy.ai.enabled;

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
                <p className="text-xs text-text-3">
                    PII patterns, regular expressions, and literal values are checked in code. They do not call an AI model.
                </p>
                {policy.rules.map((rule, index) => (
                    <RuleFields key={rule.id} rule={rule} templates={templates} disabled={disabled}
                        onChange={(next) => onChange({ ...policy, rules: policy.rules.map((item, i) => i === index ? next : item) })}
                        onRemove={() => onChange({ ...policy, rules: policy.rules.filter((_, i) => i !== index) })} />
                ))}
                {!policy.rules.length ? <p className="text-xs text-text-3">No additional deterministic rules configured.</p> : null}
                {!disabled ? (
                    <div className="flex flex-wrap items-end gap-2">
                        <div className="min-w-0 flex-1">
                            <ScreeningField label="Starter rule pack">
                                {(id) => (
                                    <select id={id} className={screeningInputClass} value={packIndex}
                                        onChange={(event) => setPackIndex(event.target.value)}>
                                        <option value="">Choose a starter pack</option>
                                        {templates.packs.map((pack, index) => (
                                            <option key={pack.id} value={index}>{pack.name}</option>
                                        ))}
                                    </select>
                                )}
                            </ScreeningField>
                        </div>
                        <GlassButton type="button" size="sm" variant="subtle" disabled={packIndex === ''}
                            onClick={() => {
                                const pack = templates.packs[Number(packIndex)];
                                if (pack) {
                                    onChange(addScreeningStarterPack(policy, pack.rules));
                                    setPackIndex('');
                                }
                            }}>
                            <Plus size={14} />Add starter pack
                        </GlassButton>
                    </div>
                ) : null}
                {!disabled ? <div className="flex flex-wrap gap-2">
                    {(['literal', 'regex', 'pii'] as const).map((type) => (
                        <GlassButton key={type} type="button" size="sm" variant="subtle"
                            disabled={!templates.rules.some((rule) => rule.type === type)}
                            onClick={() => onChange({
                                ...policy, rules: [...policy.rules, newCustomScreeningRule(type, templates)],
                            })}>
                            <Plus size={14} />Add {type === 'pii' ? 'PII' : type} rule
                        </GlassButton>
                    ))}
                </div> : null}
            </section>

            <section className="space-y-3 border-t border-edge pt-4" aria-label="Model screening">
                <h3 className="text-sm font-semibold text-text-1">AI checks (optional)</h3>
                <Toggle label="Enable AI checks" checked={policy.ai.enabled} disabled={disabled}
                    description="Send content to one selected model for this policy's additional criteria. AI findings cannot override deterministic findings."
                    onChange={(enabled) => updateAi({ enabled })} />
                {!policy.ai.enabled ? <p className="text-xs text-text-3">
                    AI checks for this policy are off. Saved model settings are retained but are not used.
                    Required administrator AI checks still apply to workspace additions.
                </p> : null}
                <fieldset disabled={aiDisabled} className={`min-w-0 space-y-3 ${aiDisabled ? 'opacity-60' : ''}`}>
                    <legend className="sr-only">AI check configuration</legend>
                    <ModelPicker field={{
                        key: baseline ? 'screening-baseline-model' : 'screening-workspace-model',
                        type: 'component', label: 'Scanner model', placeholder: 'Select an approved configured model',
                        help: 'Uses saved model references, not a separately configured endpoint or credential.',
                    }} models={catalog} value={screeningModelIndex(approvedModels, policy.ai.model_selection)}
                        disabled={aiDisabled} onChange={(value) => {
                            const selected = value === '' ? undefined : approvedModels[Number(value)];
                            updateAi({ model_selection: selected
                                ? { endpoint_id: selected.endpointId, model_id: selected.modelId }
                                : { endpoint_id: '', model_id: '' } });
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
                            <GlassButton type="button" size="sm" variant="subtle" disabled={aiDisabled || criteriaIndex === ''}
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
                            disabled={aiDisabled} value={policy.ai.instructions}
                            onChange={(event) => updateAi({ instructions: event.target.value })} />}
                    </ScreeningField>
                    <div className="grid gap-3 sm:grid-cols-2">
                        <ScreeningField label="Model finding severity">
                            {(id) => (
                                <select id={id} className={screeningInputClass} value={policy.ai.severity} disabled={aiDisabled}
                                    onChange={(event) => updateAi({ severity: event.target.value })}>
                                    {[...new Set([policy.ai.severity, ...templates.severities])].filter(Boolean).map((severity) => (
                                        <option key={severity} value={severity}>{severity}</option>
                                    ))}
                                </select>
                            )}
                        </ScreeningField>
                        <ScreeningField label="Model finding category">
                            {(id) => <input id={id} className={screeningInputClass} value={policy.ai.category} disabled={aiDisabled}
                                onChange={(event) => updateAi({ category: event.target.value })} />}
                        </ScreeningField>
                        <ScreeningField label="Scan window unit">
                            {(id) => (
                                <select id={id} className={screeningInputClass} value={policy.ai.window_unit} disabled={aiDisabled}
                                    onChange={(event) => updateAi({ window_unit: event.target.value === 'pages' ? 'pages' : 'chunks' })}>
                                    <option value="pages">Pages</option>
                                    <option value="chunks">Chunks</option>
                                </select>
                            )}
                        </ScreeningField>
                        <ScreeningNumberField label="Pages or chunks per window" value={policy.ai.window_size}
                            min={1} disabled={aiDisabled} onChange={(window_size) => updateAi({ window_size })}
                            help="Use 1 for a single page/chunk; larger values form bounded batches." />
                        <ScreeningNumberField label="Maximum characters per window" value={policy.ai.max_characters}
                            min={256} disabled={aiDisabled} onChange={(max_characters) => updateAi({ max_characters })} />
                        <ScreeningNumberField label="Boundary overlap characters" value={policy.ai.overlap_characters}
                            disabled={aiDisabled} onChange={(overlap_characters) => updateAi({ overlap_characters })} />
                    </div>
                </fieldset>
                <p className="text-xs text-text-3">
                    Oversized units are split, not truncated. Every tail and required window must be covered.
                    Extracted segments without a physical-page mapping are never presented as PDF pages.
                </p>
            </section>
            {baseline ? <details className="space-y-3 rounded-xl border border-edge p-3">
                <summary className="cursor-pointer text-sm font-semibold text-text-1">Models workspaces may use</summary>
                <p className="text-xs text-text-3">
                    This is a permission list, not a list of models to run. It can be configured while this policy's AI checks are off.
                    A workspace must enable its own AI check to use one of these models. The saved baseline scanner is also permitted automatically.
                </p>
                <fieldset disabled={disabled} className="space-y-2">
                    <legend className="sr-only">Workspace model permissions</legend>
                    {models.length ? models.map((model, index) => {
                        const implicit = policy.ai.model_selection?.endpoint_id === model.endpointId
                            && policy.ai.model_selection.model_id === model.modelId;
                        const selected = implicit || policy.allowed_models?.some(
                            (item) => item.endpoint_id === model.endpointId && item.model_id === model.modelId,
                        ) || false;
                        return <label key={index} className="flex items-start gap-2 py-1 text-sm text-text-2">
                            <input type="checkbox" className="mt-1 accent-[var(--accent)]" checked={selected}
                                disabled={disabled || implicit} onChange={(event) => {
                                    const others = (policy.allowed_models ?? []).filter(
                                        (item) => item.endpoint_id !== model.endpointId || item.model_id !== model.modelId,
                                    );
                                    onChange({ ...policy, allowed_models: event.target.checked
                                        ? [...others, { endpoint_id: model.endpointId, model_id: model.modelId }] : others });
                                }} />
                            {model.modelLabel} · {screeningModelCatalog([model])[0].endpoint}
                            {implicit ? ' (included by baseline scanner selection)' : ''}
                        </label>;
                    }) : <p className="text-xs text-warn">No configured scanner models are available.</p>}
                </fieldset>
            </details> : null}
            <details className="space-y-3 border-t border-edge pt-4">
                <summary className="cursor-pointer text-sm font-semibold text-text-1">Execution limits</summary>
                <p className="text-xs text-text-3">Server-defined budgets fail closed rather than treating skipped work as clean.</p>
                <div className="grid gap-3 sm:grid-cols-2">
                    {Object.entries(policy.limits).map(([key, value]) => (
                        <ScreeningNumberField key={key} label={key.replaceAll('_', ' ')} value={value}
                            step="any" disabled={disabled}
                            onChange={(next) => onChange({ ...policy, limits: { ...policy.limits, [key]: next } })} />
                    ))}
                </div>
            </details>
        </div>
    );
}
