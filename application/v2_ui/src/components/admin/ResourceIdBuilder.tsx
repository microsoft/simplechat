// ResourceIdBuilder.tsx
// A text field that can also assemble its value from sibling fields.
//
// An ARM resource id is long, exact, and built from three values the administrator has
// already typed elsewhere in the same section. Asking them to retype it as one string is
// how a typo gets stored and a managed identity mysteriously fails to authenticate.
//
// It stays editable, because a resource id can legitimately come from somewhere the
// template does not cover, and a built value is never silently overwritten once the
// administrator has edited it by hand.

import { useState } from 'react';
import { clsx } from 'clsx';
import { Wand2 } from 'lucide-react';
import { asString, type AdminField } from '../../lib/adminFields';
import { FieldShell } from './fields';

/**
 * Fill a template from its declared sources.
 *
 * Returns an empty string when any source is blank, because a partially built id is
 * worse than none: it looks configured and cannot work.
 */
export function buildResourceId(
    template: string,
    sources: Record<string, string>,
    read: (key: string) => string,
): string {
    const values: Record<string, string> = {};

    for (const [placeholder, key] of Object.entries(sources)) {
        const value = read(key).trim();
        if (!value) {
            return '';
        }
        values[placeholder] = value;
    }

    return template.replace(/\{(\w+)\}/g, (_match, name: string) => values[name] ?? '');
}

export function ResourceIdBuilder({
    field,
    value,
    error,
    warning,
    disabled,
    readSibling,
    onChange,
}: {
    field: AdminField;
    value: unknown;
    error?: string;
    warning?: string;
    disabled?: boolean;
    readSibling: (key: string) => string;
    onChange: (next: string) => void;
}) {
    const id = `admin-field-${field.key}`;
    const current = asString(value);

    // Tracks whether the value on screen was produced here. An administrator's own
    // text is never replaced by a rebuild unless they ask for it.
    const [generated, setGenerated] = useState(false);

    const template = field.builder_template ?? '';
    const sources = field.builder_sources ?? {};
    const candidate = buildResourceId(template, sources, readSibling);

    const missing = Object.entries(sources)
        .filter(([, key]) => !readSibling(key).trim())
        .map(([placeholder]) => placeholder.replace(/_/g, ' '));

    return (
        <FieldShell field={field} error={error} warning={warning} htmlFor={id}>
            <div className="flex items-center gap-2">
                <input
                    id={id}
                    type="text"
                    className={clsx(
                        'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2',
                        'font-mono text-xs text-text-1 placeholder:text-text-3',
                        'focus:border-accent focus:outline-none',
                        'disabled:cursor-not-allowed disabled:opacity-60',
                    )}
                    value={current}
                    placeholder={field.placeholder}
                    disabled={disabled}
                    spellCheck={false}
                    onChange={(event) => {
                        setGenerated(false);
                        onChange(event.target.value);
                    }}
                />
                <button
                    type="button"
                    className={clsx(
                        'flex shrink-0 items-center gap-1.5 rounded-lg border border-edge px-3 py-2',
                        'text-xs text-text-2 hover:bg-surface-2',
                        'disabled:cursor-not-allowed disabled:opacity-60',
                    )}
                    disabled={disabled || !candidate}
                    onClick={() => {
                        setGenerated(true);
                        onChange(candidate);
                    }}
                >
                    <Wand2 size={13} />
                    Build
                </button>
            </div>

            {missing.length ? (
                <p className="mt-1.5 text-xs text-text-3">
                    Fill in {missing.join(', ')} above to build this automatically.
                </p>
            ) : null}

            {candidate && current && candidate !== current && !generated ? (
                <p className="mt-1.5 text-xs text-warn">
                    This does not match the fields above. Build to replace it, or leave it
                    if it is deliberate.
                </p>
            ) : null}
        </FieldShell>
    );
}
