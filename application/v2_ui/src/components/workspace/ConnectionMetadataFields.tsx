// ConnectionMetadataFields.tsx

import { useEffect, useId, useRef, useState } from 'react';
import {
    CAPACITY_FIELDS, CAPACITY_IDENTITY_FIELDS, TOKEN_ACCOUNTING_OPTIONS, TOKEN_PROVIDER_OPTIONS,
    type ConnectionCapacity,
} from '../../lib/connectionMetadata';
import type { ConnectionModel } from '../../lib/modelConnections';
import { isResourceIconImage, loadResourceIconNames, resizeResourceIcon } from '../../lib/resourceIcons';
import { GlassButton } from '../ui/primitives';

const inputClass = 'w-full min-w-0 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none disabled:opacity-60';
const defaultIcons = ['bi-stars', 'bi-robot', 'bi-lightbulb', 'bi-code-square', 'bi-search', 'bi-database', 'bi-globe'];

export function ConnectionCapacityFields({ record, model = false, disabled, errors, onChange }: {
    record: ConnectionCapacity;
    model?: boolean;
    disabled: boolean;
    errors: Record<string, string>;
    onChange: (key: keyof ConnectionCapacity, value: string | null) => void;
}) {
    const id = useId();
    const fields = [...(model ? CAPACITY_IDENTITY_FIELDS : []), ...CAPACITY_FIELDS];
    const hasError = [...fields.map(({ key }) => key), 'tokenLimitProvider', 'outputTokenAccounting']
        .some((key) => errors[key]);
    return (
        <details className="mt-3 border-t border-edge pt-3 text-xs text-text-3" open={hasError ? true : undefined}>
            <summary className="cursor-pointer py-1 font-medium text-text-2">
                Advanced {model ? 'model' : 'endpoint'} capacity
            </summary>
            <p className="mt-2 mb-3 leading-relaxed">
                {model ? 'Each blank value inherits independently from the endpoint, then the exact catalog model.'
                    : 'Defaults for models on this endpoint. Blank values inherit from the exact catalog model; model overrides take precedence.'}
                {' '}Use verified specifications, not a guessed capacity. Independent input and output maxima do not have to fit simultaneously in the context window.
            </p>
            <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                {fields.map(({ key, label, help }) => (
                    <div key={key} className="min-w-0">
                        <label htmlFor={`${id}-${key}`} className="mb-1 block text-text-2">{label}</label>
                        <input
                            id={`${id}-${key}`} className={inputClass} type="text"
                            inputMode={CAPACITY_FIELDS.some((field) => field.key === key) ? 'numeric' : 'text'}
                            autoComplete="off" placeholder="Inherit" disabled={disabled}
                            value={record[key] ?? ''} aria-invalid={Boolean(errors[key])}
                            aria-describedby={`${id}-${key}-help ${id}-${key}-error`}
                            onChange={(event) => onChange(key, event.target.value || null)}
                        />
                        <p id={`${id}-${key}-help`} className="mt-1">{help}</p>
                        <p id={`${id}-${key}-error`} role={errors[key] ? 'alert' : undefined} className="mt-1 text-danger">{errors[key]}</p>
                    </div>
                ))}
                {([
                    ['tokenLimitProvider', 'Token limit provider', TOKEN_PROVIDER_OPTIONS],
                    ['outputTokenAccounting', 'Output token accounting', TOKEN_ACCOUNTING_OPTIONS],
                ] as const).map(([key, label, options]) => (
                    <div key={key}>
                        <label htmlFor={`${id}-${key}`} className="mb-1 block text-text-2">{label}</label>
                        <select id={`${id}-${key}`} className={inputClass} value={record[key] ?? ''}
                            disabled={disabled} aria-invalid={Boolean(errors[key])}
                            aria-describedby={`${id}-${key}-error`}
                            onChange={(event) => onChange(key, event.target.value || null)}>
                            {record[key] && !options.some((option) => option === record[key]) ? <option value={record[key] ?? ''}>Invalid saved value - choose an option</option> : null}
                            {options.map((option) => (
                                <option key={option} value={option}>
                                    {option === '' ? 'Inherit' : option === 'total_generation' ? 'Total generation (including reasoning)'
                                        : option === 'visible_only' ? 'Visible output only' : option.replaceAll('_', ' ')}
                                </option>
                            ))}
                        </select>
                        <p id={`${id}-${key}-error`} role={errors[key] ? 'alert' : undefined} className="mt-1 text-danger">{errors[key]}</p>
                    </div>
                ))}
            </div>
        </details>
    );
}

export function ConnectionModelMetadata({ model, disabled, errors, onChange, onIconBusyChange }: {
    model: ConnectionModel;
    disabled: boolean;
    errors: Record<string, string>;
    onChange: (model: ConnectionModel) => void;
    onIconBusyChange: (busy: boolean) => void;
}) {
    const id = useId();
    const [icons, setIcons] = useState(defaultIcons);
    const [search, setSearch] = useState('');
    const [iconError, setIconError] = useState<string | null>(null);
    const [loadingIcons, setLoadingIcons] = useState(false);
    const uploadSequence = useRef(0);
    useEffect(() => () => { uploadSequence.current += 1; }, []);
    const icon = model.icon;
    const selected = icon?.kind === 'bootstrap' ? icon.value : '';
    const visible = icons.filter((name) => name.includes(search.toLowerCase()));

    const loadIcons = async () => {
        setIconError(null);
        setLoadingIcons(true);
        try { setIcons(await loadResourceIconNames()); } catch (cause) {
            setIconError(cause instanceof Error ? cause.message : 'Could not load the local icon catalogue.');
        } finally { setLoadingIcons(false); }
    };
    const upload = async (file: File) => {
        const sequence = ++uploadSequence.current;
        setIconError(null);
        onIconBusyChange(true);
        try {
            const value = await resizeResourceIcon(file);
            if (sequence === uploadSequence.current) onChange({ ...model, icon: { kind: 'image', value, mime_type: 'image/png' } });
        } catch (cause) {
            if (sequence === uploadSequence.current) setIconError(cause instanceof Error ? cause.message : 'Could not load the icon image.');
        } finally {
            if (sequence === uploadSequence.current) onIconBusyChange(false);
        }
    };

    return (
        <div className="mt-3 space-y-3">
            <div>
                <label htmlFor={`${id}-description`} className="mb-1 block text-xs text-text-2">Model description</label>
                <textarea id={`${id}-description`} className={inputClass} rows={2} disabled={disabled}
                    value={model.description ?? ''} onChange={(event) => onChange({ ...model, description: event.target.value })} />
            </div>
            <div>
                <label htmlFor={`${id}-response-length`} className="mb-1 block text-xs text-text-2">Response length</label>
                <input id={`${id}-response-length`} className={inputClass} type="text" inputMode="numeric"
                    placeholder="Inherit" value={model.responseLength ?? ''} disabled={disabled}
                    aria-invalid={Boolean(errors.responseLength)}
                    aria-describedby={`${id}-response-help ${id}-response-error`}
                    onChange={(event) => onChange({ ...model, responseLength: event.target.value || null })} />
                <p id={`${id}-response-help`} className="mt-1 text-xs text-text-3">Optional per-request generation allowance for standard chat, not model capacity.</p>
                <p id={`${id}-response-error`} role={errors.responseLength ? 'alert' : undefined} className="mt-1 text-xs text-danger">{errors.responseLength}</p>
            </div>
            <ConnectionCapacityFields record={model} model disabled={disabled} errors={errors}
                onChange={(key, value) => onChange({ ...model, [key]: value })} />
            <details className="border-t border-edge pt-3 text-xs text-text-3" open={errors.icon ? true : undefined}>
                <summary className="cursor-pointer py-1 font-medium text-text-2">Model icon</summary>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                    {icon?.kind === 'image' && isResourceIconImage(icon.value) ? <img src={icon.value} alt="Model icon preview" className="h-10 w-10 rounded-lg object-contain" /> : null}
                    {selected && /^bi-[a-z0-9][a-z0-9-]{0,80}$/.test(selected) ? <i aria-hidden="true" className={`bi ${selected} text-xl text-accent`} /> : null}
                    <GlassButton type="button" size="sm" disabled={disabled} onClick={() => onChange({ ...model, icon: {} })}>Use default icon</GlassButton>
                </div>
                <label htmlFor={`${id}-icon-search`} className="mt-2 mb-1 block">Search Bootstrap icons</label>
                <input id={`${id}-icon-search`} className={inputClass} type="search" value={search}
                    disabled={disabled} onChange={(event) => setSearch(event.target.value)} />
                <label htmlFor={`${id}-icon`} className="mt-2 mb-1 block">Bootstrap icon</label>
                <select id={`${id}-icon`} className={inputClass} value={selected} disabled={disabled}
                    onChange={(event) => onChange({ ...model, icon: event.target.value ? { kind: 'bootstrap', value: event.target.value } : {} })}>
                    <option value="">Default icon</option>
                    {selected && !visible.includes(selected) ? <option value={selected}>{selected}</option> : null}
                    {visible.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
                <GlassButton type="button" size="sm" disabled={disabled || loadingIcons} onClick={() => void loadIcons()}>
                    {loadingIcons ? 'Loading icons...' : 'Load all local icons'}
                </GlassButton>
                <label htmlFor={`${id}-upload`} className="mt-2 mb-1 block">Upload model icon</label>
                <input id={`${id}-upload`} type="file" accept="image/png,image/jpeg" disabled={disabled}
                    className={inputClass} onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void upload(file);
                        event.target.value = '';
                    }} />
                <p className="mt-1">PNG or JPEG, resized to at most 128 by 128 pixels and a 350000-character PNG payload.</p>
                {iconError || errors.icon ? <p role="alert" className="mt-2 text-danger">{iconError || errors.icon}</p> : null}
            </details>
        </div>
    );
}
