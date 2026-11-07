// ModelPicker.tsx
// Choose a deployed model for a setting that needs one.
//
// The list comes from the server with capabilities already resolved, so the browser does
// not carry a second copy of the rules for deciding what a model can do. That mattered
// here: whether a model can read images used to be worked out by matching its name
// against a pattern, in two places, and the pattern was wrong in both directions --
// admitting text-only chat variants and saying nothing at all about a self-hosted
// deployment.
//
// A model whose capability was inferred rather than known is marked as such. The answer
// is still a guess for anything the catalog has not heard of, and presenting a guess as
// fact is how an administrator ends up picking a model that fails at upload time.

import { clsx } from 'clsx';
import { Info } from 'lucide-react';
import {
    asString,
    type AdminField,
    type AdminModelCatalogEntry,
    type AdminModelSelection,
} from '../../lib/adminFields';
import { FieldShell } from './fields';

export function ModelPicker({
    field,
    value,
    selection,
    error,
    warning,
    disabled,
    models,
    onChange,
}: {
    field: AdminField;
    value: unknown;
    selection?: AdminModelSelection | null;
    error?: string;
    warning?: string;
    disabled?: boolean;
    models: AdminModelCatalogEntry[];
    onChange: (next: string, selectedModel?: AdminModelCatalogEntry) => void;
}) {
    const id = `admin-field-${field.key}`;
    const current = asString(value);

    const eligible = models.filter((model) =>
        model.supports_chat !== false &&
        model.capability_status?.chat?.supported !== false &&
        model.capability_status?.chat?.available !== false &&
        (!field.requires_vision || model.supports_vision),
    );

    const deploymentCounts = new Map<string, number>();
    for (const model of eligible) {
        deploymentCounts.set(model.deployment, (deploymentCounts.get(model.deployment) ?? 0) + 1);
    }

    const optionValue = (model: AdminModelCatalogEntry): string => {
        if (
            (deploymentCounts.get(model.deployment) ?? 0) > 1 &&
            (model.endpoint_id || model.model_id)
        ) {
            return `${model.endpoint_id ?? ''}::${model.model_id ?? ''}::${model.deployment}`;
        }
        return model.deployment;
    };

    const hasExplicitSelection = Boolean(
        selection && (selection.endpoint_id || selection.model_id),
    );

    const selected = hasExplicitSelection
        ? eligible.find(
              (model) =>
                  String(model.endpoint_id ?? '') === selection?.endpoint_id &&
                  (model.model_id
                      ? String(model.model_id) === selection?.model_id
                      : model.deployment === current),
          )
        : eligible.find(
              (model) =>
                  model.deployment === current ||
                  (Boolean(current) && model.model_name === current),
          );

    // A previously chosen model can drop out of the list: an endpoint was removed, or a
    // capability was corrected. Silently showing nothing selected would look like the
    // setting had never been configured, so the stale value is kept and named.
    const staleLabel =
        current ||
        (hasExplicitSelection
            ? `${selection?.model_id || 'model'} (${selection?.endpoint_id || 'endpoint'})`
            : '');
    const staleSelection = Boolean(staleLabel) && !selected;
    const staleOptionValue = current || '__stale__';
    const selectValue = selected
        ? optionValue(selected)
        : staleSelection
          ? staleOptionValue
          : '';

    return (
        <FieldShell field={field} error={error} warning={warning} htmlFor={id}>
            <select
                id={id}
                className={clsx(
                    'w-full appearance-none rounded-lg border border-edge bg-surface-1 px-3 py-2 pr-8',
                    'text-sm text-text-1 focus:border-accent focus:outline-none',
                    'disabled:cursor-not-allowed disabled:opacity-60',
                )}
                value={selectValue}
                disabled={disabled}
                onChange={(event) => {
                    const raw = event.target.value;
                    if (!raw) {
                        onChange('', undefined);
                        return;
                    }
                    const chosen = eligible.find((model) => optionValue(model) === raw);
                    onChange(chosen ? chosen.deployment : raw, chosen);
                }}
            >
                <option value="">{field.placeholder ?? 'No model selected'}</option>
                {staleSelection ? (
                    <option value={staleOptionValue}>{staleLabel} — no longer available</option>
                ) : null}
                {eligible.map((model) => {
                    const valueKey = optionValue(model);
                    return (
                        <option
                            key={`${model.endpoint_id ?? ''}:${model.model_id ?? model.deployment}`}
                            value={valueKey}
                        >
                            {model.label}
                            {model.endpoint ? ` · ${model.endpoint}` : ''}
                        </option>
                    );
                })}
            </select>

            {!eligible.length ? (
                <p className="mt-1.5 text-xs text-warn">
                    {field.requires_vision
                        ? 'No available chat model reports image input support. Check AI Connections under AI Models.'
                        : 'No models are deployed yet. Add one under AI Models.'}
                </p>
            ) : null}

            {selected?.vision_source === 'inferred' && field.requires_vision ? (
                <p className="mt-1.5 flex items-start gap-1.5 text-xs text-text-3">
                    <Info size={12} className="mt-0.5 shrink-0" />
                    Image support for this model was inferred from its name. If that is
                    wrong, set it explicitly on the model under AI Models.
                </p>
            ) : null}
        </FieldShell>
    );
}
