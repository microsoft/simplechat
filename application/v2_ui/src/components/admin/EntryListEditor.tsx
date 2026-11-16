// EntryListEditor.tsx
// A repeatable allowlist of `{ value, description }` rows.
//
// The inbound MCP allowlists are not free text. Each row is an identifier the runtime
// matches a request against -- a client application id, a tenant id, a source value -- and
// a description saying who it belongs to. The description is there because an allowlist of
// bare GUIDs becomes unauditable within weeks: nobody can say which entry may safely be
// removed.
//
// The list flows into the page draft like any other field, so it is saved by the same save
// bar. The server re-normalizes it and derives the flat id list the runtime actually reads.

import { clsx } from 'clsx';
import { AlertCircle, ListChecks, Plus, Trash2 } from 'lucide-react';
import type { AdminField } from '../../lib/adminFields';
import { readEntryList, type AllowlistEntry } from '../../lib/adminEntries';
import { GlassButton } from '../ui/primitives';

const inputClass = clsx(
    'w-full rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5',
    'text-sm text-text-1 placeholder:text-text-3',
    'focus:border-accent focus:outline-none',
    'disabled:cursor-not-allowed disabled:opacity-60',
);

export function EntryListEditor({
    field,
    value,
    error,
    disabled,
    onChange,
}: {
    field: AdminField;
    value: unknown;
    error?: string;
    disabled?: boolean;
    onChange: (next: AllowlistEntry[]) => void;
}) {
    const entries = readEntryList(value);
    const valueLabel = field.value_label ?? 'Value';
    const duplicates = new Set(
        entries
            .map((entry) => entry.value.trim().toLowerCase())
            .filter((entry, index, all) => entry && all.indexOf(entry) !== index),
    );

    const replace = (index: number, patch: Partial<AllowlistEntry>) => {
        onChange(entries.map((entry, i) => (i === index ? { ...entry, ...patch } : entry)));
    };

    return (
        <div className="py-3">
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
                <span className="text-sm font-medium text-text-1">{field.label}</span>
                <span className="text-xs text-text-3">
                    {entries.length} {entries.length === 1 ? 'entry' : 'entries'}
                </span>
            </div>

            {entries.length === 0 ? (
                <div className="flex items-center gap-2 rounded-lg border border-dashed border-edge px-3 py-4 text-sm text-text-3">
                    <ListChecks size={15} aria-hidden="true" />
                    {field.empty_text ?? 'No entries yet.'}
                </div>
            ) : (
                <ul className="space-y-2">
                    {entries.map((entry, index) => {
                        const duplicated =
                            entry.value.trim() !== '' &&
                            duplicates.has(entry.value.trim().toLowerCase());
                        return (
                            <li
                                key={index}
                                className="rounded-lg border border-edge bg-surface-1 p-2"
                            >
                                <div className="flex items-start gap-2">
                                    <div className="grid min-w-0 flex-1 gap-2 sm:grid-cols-2">
                                        <input
                                            type="text"
                                            className={clsx(inputClass, 'font-mono text-xs')}
                                            placeholder={field.placeholder ?? valueLabel}
                                            aria-label={`${valueLabel} ${index + 1}`}
                                            maxLength={256}
                                            spellCheck={false}
                                            disabled={disabled}
                                            value={entry.value}
                                            onChange={(event) =>
                                                replace(index, { value: event.target.value })
                                            }
                                        />
                                        <input
                                            type="text"
                                            className={inputClass}
                                            placeholder="Who this belongs to"
                                            aria-label={`Description for entry ${index + 1}`}
                                            maxLength={256}
                                            disabled={disabled}
                                            value={entry.description}
                                            onChange={(event) =>
                                                replace(index, {
                                                    description: event.target.value,
                                                })
                                            }
                                        />
                                    </div>

                                    <button
                                        type="button"
                                        title="Remove"
                                        aria-label={`Remove entry ${index + 1}`}
                                        disabled={disabled}
                                        onClick={() =>
                                            onChange(entries.filter((_, i) => i !== index))
                                        }
                                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
                                    >
                                        <Trash2 size={14} />
                                    </button>
                                </div>

                                {duplicated ? (
                                    <p className="mt-1.5 flex items-center gap-1.5 text-xs text-warn">
                                        <AlertCircle size={12} className="shrink-0" />
                                        Repeated value. Only the first is kept on save.
                                    </p>
                                ) : null}
                            </li>
                        );
                    })}
                </ul>
            )}

            <GlassButton
                type="button"
                variant="subtle"
                size="sm"
                className="mt-2"
                disabled={disabled}
                onClick={() => onChange([...entries, { value: '', description: '' }])}
            >
                <Plus size={14} />
                Add {valueLabel.toLowerCase()}
            </GlassButton>

            {field.help ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">{field.help}</p>
            ) : null}

            {error ? (
                <p role="alert" className="mt-1.5 flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            ) : null}
        </div>
    );
}
