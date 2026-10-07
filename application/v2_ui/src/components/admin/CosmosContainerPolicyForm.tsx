// CosmosContainerPolicyForm.tsx
// One container's throughput policy, edited in place in the Cosmos Metrics workbench.
//
// Edits go straight into the page draft like every other setting, and the save bar
// persists them; there is no separate staging step to forget. A value the policy leaves
// out inherits the global one, so the form always starts from what governs the container
// now. Rule breaks -- Scale Up At not above Scale Down At, an interval shorter than the
// metrics window -- are shown beside the value, the same rules the server checks on save.

import { useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { Toggle } from '../ui/primitives';
import { inputClass } from './fields';
import {
    COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU,
    type ContainerPolicyField,
    type CosmosContainerPolicy,
} from '../../lib/cosmosThroughput';
import { formatTimestamp } from '../../lib/scaleFormat';

/** Container names are Cosmos ids; keep only what is safe in an element id. */
function idPart(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9_-]/g, '-');
}

function PolicyNumber({
    id,
    label,
    value,
    min,
    max,
    step = 1,
    suffix,
    error,
    disabled,
    onChange,
}: {
    id: string;
    label: string;
    value: number | undefined;
    min: number;
    max?: number;
    step?: number;
    suffix: string;
    error?: string;
    disabled?: boolean;
    onChange: (next: number) => void;
}) {
    const errorId = `${id}-error`;
    // While the field has focus its text is what it shows, so clearing it to type another
    // number does not commit 0 on the way, and nothing rewrites a half-typed value.
    const [text, setText] = useState<string | null>(null);
    return (
        <div className="min-w-0">
            <label htmlFor={id} className="mb-1 block text-xs text-text-2">
                {label}
            </label>
            <div className="flex items-center gap-2">
                <input
                    id={id}
                    type="number"
                    className={clsx(inputClass, 'max-w-36', error && 'border-danger')}
                    value={text ?? value ?? ''}
                    min={min}
                    max={max}
                    step={step}
                    disabled={disabled}
                    aria-invalid={error ? true : undefined}
                    aria-describedby={error ? errorId : undefined}
                    onFocus={() => setText(value === undefined ? '' : String(value))}
                    onBlur={() => setText(null)}
                    onChange={(event) => {
                        const next = event.target.value;
                        setText(next);
                        const parsed = Number(next);
                        if (next.trim() !== '' && Number.isFinite(parsed)) {
                            onChange(parsed);
                        }
                    }}
                />
                <span className="shrink-0 text-xs text-text-3">{suffix}</span>
            </div>
            {error ? (
                <p id={errorId} role="alert" className="mt-1 text-xs text-danger">
                    {error}
                </p>
            ) : null}
        </div>
    );
}

function PolicyCluster({ title, children }: { title: string; children: ReactNode }) {
    return (
        <fieldset className="min-w-0 space-y-2 border-t border-edge pt-3">
            <legend className="pr-2 text-xs font-semibold text-text-1">{title}</legend>
            {children}
        </fieldset>
    );
}

export function CosmosContainerPolicyForm({
    containerName,
    policy,
    errors,
    disabled,
    onChange,
}: {
    containerName: string;
    policy: CosmosContainerPolicy;
    errors: Partial<Record<ContainerPolicyField, string>>;
    disabled?: boolean;
    onChange: (patch: Partial<CosmosContainerPolicy>) => void;
}) {
    const base = `cosmos-policy-${idPart(containerName)}`;
    const enabled = policy.enabled !== false;
    const fieldsDisabled = disabled || !enabled;

    return (
        <div className="space-y-3" data-testid="cosmos-container-policy-form">
            <Toggle
                label="Automate this container"
                description="Off leaves its throughput alone, whatever the global policy says."
                checked={enabled}
                disabled={disabled}
                onChange={(next) => onChange({ enabled: next })}
            />

            <PolicyCluster title="Scale up">
                <Toggle
                    label="Auto scale up"
                    checked={policy.auto_scale_up_enabled !== false}
                    disabled={fieldsDisabled}
                    onChange={(next) => onChange({ auto_scale_up_enabled: next })}
                />
                <div className="grid gap-3 @lg:grid-cols-3">
                    <PolicyNumber
                        id={`${base}-scale-up-at`}
                        label="Scale up at"
                        value={policy.scale_up_threshold_percent}
                        min={1}
                        max={100}
                        suffix="%"
                        error={errors.scale_up_threshold_percent}
                        disabled={fieldsDisabled}
                        onChange={(next) => onChange({ scale_up_threshold_percent: next })}
                    />
                    <PolicyNumber
                        id={`${base}-scale-up-step`}
                        label="Step"
                        value={policy.scale_up_step_ru}
                        min={1000}
                        step={1000}
                        suffix="RU/s"
                        disabled={fieldsDisabled}
                        onChange={(next) => onChange({ scale_up_step_ru: next })}
                    />
                    <PolicyNumber
                        id={`${base}-scale-up-interval`}
                        label="Interval"
                        value={policy.scale_up_cooldown_minutes}
                        min={1}
                        max={1440}
                        suffix="min"
                        error={errors.scale_up_cooldown_minutes}
                        disabled={fieldsDisabled}
                        onChange={(next) => onChange({ scale_up_cooldown_minutes: next })}
                    />
                </div>
            </PolicyCluster>

            <PolicyCluster title="Scale down">
                <Toggle
                    label="Auto scale down"
                    checked={policy.auto_scale_down_enabled !== false}
                    disabled={fieldsDisabled}
                    onChange={(next) => onChange({ auto_scale_down_enabled: next })}
                />
                <div className="grid gap-3 @lg:grid-cols-3">
                    <PolicyNumber
                        id={`${base}-scale-down-at`}
                        label="Scale down at"
                        value={policy.scale_down_threshold_percent}
                        min={0}
                        max={99}
                        suffix="%"
                        error={errors.scale_down_threshold_percent}
                        disabled={fieldsDisabled}
                        onChange={(next) => onChange({ scale_down_threshold_percent: next })}
                    />
                    <PolicyNumber
                        id={`${base}-scale-down-step`}
                        label="Step"
                        value={policy.scale_down_step_ru}
                        min={1000}
                        step={1000}
                        suffix="RU/s"
                        disabled={fieldsDisabled}
                        onChange={(next) => onChange({ scale_down_step_ru: next })}
                    />
                    <PolicyNumber
                        id={`${base}-scale-down-interval`}
                        label="Interval"
                        value={policy.scale_down_cooldown_minutes}
                        min={1}
                        max={1440}
                        suffix="min"
                        error={errors.scale_down_cooldown_minutes}
                        disabled={fieldsDisabled}
                        onChange={(next) => onChange({ scale_down_cooldown_minutes: next })}
                    />
                </div>
            </PolicyCluster>

            <PolicyCluster title="Guardrails">
                <div className="grid gap-3 @lg:grid-cols-2">
                    <div className="space-y-1">
                        <PolicyNumber
                            id={`${base}-min-ru`}
                            label="Minimum"
                            value={policy.min_ru}
                            min={1000}
                            step={1000}
                            suffix="RU/s"
                            disabled={fieldsDisabled}
                            onChange={(next) => onChange({ min_ru: next })}
                        />
                        <Toggle
                            label="Ignore minimum"
                            checked={Boolean(policy.ignore_min_limit)}
                            disabled={fieldsDisabled}
                            onChange={(next) => onChange({ ignore_min_limit: next })}
                        />
                    </div>
                    <div className="space-y-1">
                        <PolicyNumber
                            id={`${base}-max-ru`}
                            label="Maximum"
                            value={policy.max_ru}
                            min={1000}
                            max={COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU}
                            step={1000}
                            suffix="RU/s"
                            disabled={fieldsDisabled}
                            onChange={(next) => onChange({ max_ru: next })}
                        />
                        <Toggle
                            label="Ignore maximum"
                            description="The 10,000 RU/s SimpleChat ceiling still applies."
                            checked={Boolean(policy.ignore_max_limit)}
                            disabled={fieldsDisabled}
                            onChange={(next) => onChange({ ignore_max_limit: next })}
                        />
                    </div>
                </div>
            </PolicyCluster>

            <PolicyCluster title="Autoscale">
                <Toggle
                    label="Convert manual throughput to Cosmos autoscale"
                    description={
                        policy.last_mode_conversion_at
                            ? `Last converted ${formatTimestamp(policy.last_mode_conversion_at)}.`
                            : 'Automation converts it before applying the guardrails.'
                    }
                    checked={Boolean(policy.convert_manual_to_autoscale_enabled)}
                    disabled={fieldsDisabled}
                    onChange={(next) => onChange({ convert_manual_to_autoscale_enabled: next })}
                />
            </PolicyCluster>
        </div>
    );
}
