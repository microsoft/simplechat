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
import { asString, type AdminField, type AdminModelCatalogEntry } from '../../lib/adminFields';
import { FieldShell } from './fields';

export function ModelPicker({
    field,
    value,
    error,
    warning,
    disabled,
    models,
    onChange,
}: {
    field: AdminField;
    value: unknown;
    error?: string;
    warning?: string;
    disabled?: boolean;
    models: AdminModelCatalogEntry[];
    onChange: (next: string) => void;
}) {
    const id = `admin-field-${field.key}`;
    const current = asString(value);

    const eligible = field.requires_vision
        ? models.filter((model) => model.supports_vision)
        : models;

    const selected = eligible.find((model) => model.deployment === current);

    // A previously chosen model can drop out of the list: an endpoint was removed, or a
    // capability was corrected. Silently showing nothing selected would look like the
    // setting had never been configured, so the stale value is kept and named.
    const staleSelection = Boolean(current) && !selected;

    return (
        <FieldShell field={field} error={error} warning={warning} htmlFor={id}>
            <select
                id={id}
                className={clsx(
                    'w-full appearance-none rounded-lg border border-edge bg-surface-1 px-3 py-2 pr-8',
                    'text-sm text-text-1 focus:border-accent focus:outline-none',
                    'disabled:cursor-not-allowed disabled:opacity-60',
                )}
                value={current}
                disabled={disabled}
                onChange={(event) => onChange(event.target.value)}
            >
                <option value="">{field.placeholder ?? 'No model selected'}</option>
                {staleSelection ? (
                    <option value={current}>{current} — no longer available</option>
                ) : null}
                {eligible.map((model) => (
                    <option key={model.deployment} value={model.deployment}>
                        {model.label}
                        {model.endpoint ? ` · ${model.endpoint}` : ''}
                    </option>
                ))}
            </select>

            {!eligible.length ? (
                <p className="mt-1.5 text-xs text-warn">
                    {field.requires_vision
                        ? 'No deployed model reports image support. Check the models on your endpoints under AI Models.'
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
