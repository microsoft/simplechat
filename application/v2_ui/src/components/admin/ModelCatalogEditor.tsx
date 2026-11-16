// ModelCatalogEditor.tsx
// The form for a custom catalog profile.
//
// Field labels match the classic editor so the two interfaces describe a profile in the
// same words. On a wide pane the description lists, task ratings, and capability ratings
// lay out in columns, which keeps the whole profile on roughly one screen.

import { useId, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { Save } from 'lucide-react';
import {
    CATALOG_CAPABILITIES,
    type CatalogProfileForm,
    type TaskSuitability,
} from '../../lib/modelCatalog';
import { GlassButton } from '../ui/primitives';
import { inputClass } from './fields';

const SUITABILITY_CHOICES: ReadonlyArray<[TaskSuitability, string]> = [
    ['unknown', 'Unknown'],
    ['suitable', 'Suitable'],
    ['strong', 'Strong'],
    ['unsuitable', 'Unsuitable'],
];

const CAPABILITY_CHOICES: ReadonlyArray<[string, string]> = [
    ['unknown', 'Unknown'],
    ['true', 'Supported'],
    ['false', 'Not supported'],
];

function Labelled({ id, label, children }: { id: string; label: string; children: ReactNode }) {
    return (
        <div className="flex min-w-0 flex-col gap-1.5">
            <label htmlFor={id} className="text-sm font-medium text-text-1">
                {label}
            </label>
            {children}
        </div>
    );
}

function Group({ legend, hint, children }: { legend: string; hint?: string; children: ReactNode }) {
    return (
        <fieldset className="min-w-0">
            <legend className="text-sm font-semibold text-text-1">{legend}</legend>
            {hint ? <p className="mt-1 text-xs text-text-3">{hint}</p> : null}
            <div className="mt-3">{children}</div>
        </fieldset>
    );
}

export function ModelCatalogEditor({
    form,
    tasks,
    isNew,
    onChange,
    onSave,
    onCancel,
}: {
    form: CatalogProfileForm;
    tasks: Record<string, string>;
    isNew: boolean;
    onChange: (next: CatalogProfileForm) => void;
    onSave: () => void;
    onCancel: () => void;
}) {
    const baseId = useId();
    const id = (name: string) => `${baseId}-${name}`;
    const set = <K extends keyof CatalogProfileForm>(key: K, value: CatalogProfileForm[K]) =>
        onChange({ ...form, [key]: value });

    const textArea = (key: 'strengths' | 'limitations' | 'aliases' | 'sources', label: string) => (
        <Labelled id={id(key)} label={label}>
            <textarea
                id={id(key)}
                rows={4}
                maxLength={6000}
                className={clsx(inputClass, 'resize-y leading-relaxed')}
                value={form[key]}
                onChange={(event) => set(key, event.target.value)}
            />
        </Labelled>
    );

    return (
        <div className="flex min-h-full flex-col">
            <div className="border-b border-edge-strong px-4 py-4 sm:px-5">
                <h3 className="text-xl leading-snug font-semibold text-text-1">
                    {isNew ? 'New custom profile' : 'Edit custom profile'}
                </h3>
                <p className="mt-1 max-w-[72ch] text-[0.8125rem] leading-relaxed text-text-3">
                    This saves a reusable profile, not a connection. Changes affect linked
                    models. Unknown capabilities do not qualify a model for constrained Auto
                    steps.
                </p>
            </div>

            <div className="flex-1 space-y-7 px-4 py-5 sm:px-5">
                <Group legend="Identity">
                    <div className="grid gap-4 @2xl:grid-cols-2">
                        <Labelled id={id('name')} label="Name">
                            <input
                                id={id('name')}
                                type="text"
                                maxLength={160}
                                className={inputClass}
                                value={form.displayName}
                                onChange={(event) => set('displayName', event.target.value)}
                            />
                        </Labelled>
                        <Labelled id={id('publisher')} label="Publisher">
                            <input
                                id={id('publisher')}
                                type="text"
                                maxLength={120}
                                className={inputClass}
                                value={form.publisher}
                                onChange={(event) => set('publisher', event.target.value)}
                            />
                        </Labelled>
                    </div>
                </Group>

                <Group legend="Description" hint="Each list takes one entry per line, up to 12 entries.">
                    <div className="space-y-4">
                        <Labelled id={id('summary')} label="What this model is good at">
                            <textarea
                                id={id('summary')}
                                rows={3}
                                maxLength={1200}
                                className={clsx(inputClass, 'resize-y leading-relaxed')}
                                value={form.summary}
                                onChange={(event) => set('summary', event.target.value)}
                            />
                        </Labelled>
                        <div className="grid gap-4 @2xl:grid-cols-2">
                            {textArea('strengths', 'Strengths (one per line)')}
                            {textArea('limitations', 'Limitations (one per line)')}
                            {textArea('aliases', 'Aliases (one per line)')}
                            {textArea('sources', 'Evidence HTTPS links (one per line)')}
                        </div>
                    </div>
                </Group>

                <Group legend="Task suitability (administrator-declared)">
                    <div className="grid gap-4 @xl:grid-cols-2 @4xl:grid-cols-3">
                        {Object.entries(tasks).map(([key, label]) => (
                            <Labelled key={key} id={id(`task-${key}`)} label={label}>
                                <select
                                    id={id(`task-${key}`)}
                                    className={inputClass}
                                    value={form.tasks[key] ?? 'unknown'}
                                    onChange={(event) =>
                                        set('tasks', { ...form.tasks, [key]: event.target.value as TaskSuitability })
                                    }
                                >
                                    {SUITABILITY_CHOICES.map(([value, text]) => (
                                        <option key={value} value={value}>
                                            {text}
                                        </option>
                                    ))}
                                </select>
                            </Labelled>
                        ))}
                    </div>
                </Group>

                <Group
                    legend="Technical capabilities (administrator-declared)"
                    hint="Leave a capability Unknown unless you have evidence for it."
                >
                    <div className="grid gap-4 @xl:grid-cols-2 @4xl:grid-cols-3">
                        {CATALOG_CAPABILITIES.map((capability) => (
                            <Labelled key={capability.key} id={id(`cap-${capability.key}`)} label={capability.label}>
                                <select
                                    id={id(`cap-${capability.key}`)}
                                    className={inputClass}
                                    value={
                                        capability.key in form.capabilities
                                            ? String(form.capabilities[capability.key])
                                            : 'unknown'
                                    }
                                    onChange={(event) => {
                                        const next = { ...form.capabilities };
                                        if (event.target.value === 'unknown') {
                                            delete next[capability.key];
                                        } else {
                                            next[capability.key] = event.target.value === 'true';
                                        }
                                        set('capabilities', next);
                                    }}
                                >
                                    {CAPABILITY_CHOICES.map(([value, text]) => (
                                        <option key={value} value={value}>
                                            {text}
                                        </option>
                                    ))}
                                </select>
                            </Labelled>
                        ))}
                    </div>
                </Group>
            </div>

            <div className="sticky bottom-0 flex flex-wrap gap-2 border-t border-edge-strong bg-surface-solid px-4 py-3 sm:px-5">
                <GlassButton type="button" variant="primary" onClick={onSave}>
                    <Save size={15} aria-hidden="true" />
                    Save profile
                </GlassButton>
                <GlassButton type="button" variant="ghost" onClick={onCancel}>
                    Cancel editing
                </GlassButton>
            </div>
        </div>
    );
}
