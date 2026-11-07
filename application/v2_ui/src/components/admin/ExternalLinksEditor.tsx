// ExternalLinksEditor.tsx
// Repeatable label/URL editor for the navigation links.
//
// The server-rendered form keeps this list in a hidden JSON field maintained by script.
// Here it is ordinary state that flows into the page's draft like any other field, so the
// list is saved by the same save bar as everything else in the section.
//
// Order is meaningful: navigation renders the links in array order, so rows can be moved.

import { clsx } from 'clsx';
import { ArrowDown, ArrowUp, Link2, Plus, Trash2 } from 'lucide-react';
import { AlertCircle } from 'lucide-react';
import type { AdminField } from '../../lib/adminFields';
import { GlassButton } from '../ui/primitives';

export interface ExternalLink {
    label: string;
    url: string;
}

/** Read the stored value defensively; it is administrator data from the database. */
export function readExternalLinks(value: unknown): ExternalLink[] {
    if (!Array.isArray(value)) {
        return [];
    }
    return value
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
        .map((item) => ({
            label: typeof item.label === 'string' ? item.label : '',
            url: typeof item.url === 'string' ? item.url : '',
        }));
}

/**
 * Local mirror of the server's link check, so a bad row is flagged while typing rather
 * than only when the save is rejected. The server check remains authoritative.
 */
function describeRowProblem(link: ExternalLink): string | null {
    if (!link.label.trim() && !link.url.trim()) {
        return null;
    }
    if (!link.label.trim()) {
        return 'Label is required.';
    }
    const url = link.url.trim();
    if (!url) {
        return 'URL is required.';
    }
    if (url.startsWith('/') && !url.startsWith('//')) {
        return null;
    }
    if (!/^https?:\/\/[^/]/i.test(url)) {
        return 'Use a local path, or an http or https address.';
    }
    return null;
}

const inputClass = clsx(
    'w-full rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5',
    'text-sm text-text-1 placeholder:text-text-3',
    'focus:border-accent focus:outline-none',
);

export function ExternalLinksEditor({
    field,
    value,
    error,
    onChange,
}: {
    field: AdminField;
    value: unknown;
    error?: string;
    onChange: (next: ExternalLink[]) => void;
}) {
    const links = readExternalLinks(value);

    const replace = (index: number, patch: Partial<ExternalLink>) => {
        onChange(links.map((link, i) => (i === index ? { ...link, ...patch } : link)));
    };

    const move = (index: number, delta: number) => {
        const target = index + delta;
        if (target < 0 || target >= links.length) {
            return;
        }
        const next = [...links];
        [next[index], next[target]] = [next[target], next[index]];
        onChange(next);
    };

    return (
        <div className="py-3">
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
                <span className="text-sm font-medium text-text-1">{field.label}</span>
                <span className="text-xs text-text-3">
                    {links.length} link{links.length === 1 ? '' : 's'}
                </span>
            </div>

            {links.length === 0 ? (
                <div className="flex items-center gap-2 rounded-lg border border-dashed border-edge px-3 py-4 text-sm text-text-3">
                    <Link2 size={15} aria-hidden="true" />
                    No links yet.
                </div>
            ) : (
                <ul className="space-y-2">
                    {links.map((link, index) => {
                        const problem = describeRowProblem(link);
                        return (
                            <li
                                key={index}
                                className="rounded-lg border border-edge bg-surface-1 p-2"
                            >
                                <div className="flex items-start gap-2">
                                    <div className="grid min-w-0 flex-1 gap-2 sm:grid-cols-2">
                                        <input
                                            type="text"
                                            className={inputClass}
                                            placeholder="Label"
                                            aria-label={`Link ${index + 1} label`}
                                            maxLength={80}
                                            value={link.label}
                                            onChange={(event) =>
                                                replace(index, { label: event.target.value })
                                            }
                                        />
                                        <input
                                            type="text"
                                            className={clsx(inputClass, 'font-mono text-xs')}
                                            placeholder="https://example.com"
                                            aria-label={`Link ${index + 1} URL`}
                                            maxLength={2000}
                                            spellCheck={false}
                                            value={link.url}
                                            onChange={(event) =>
                                                replace(index, { url: event.target.value })
                                            }
                                        />
                                    </div>

                                    <div className="flex shrink-0 items-center">
                                        <button
                                            type="button"
                                            title="Move up"
                                            aria-label={`Move link ${index + 1} up`}
                                            disabled={index === 0}
                                            onClick={() => move(index, -1)}
                                            className="rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-40"
                                        >
                                            <ArrowUp size={14} />
                                        </button>
                                        <button
                                            type="button"
                                            title="Move down"
                                            aria-label={`Move link ${index + 1} down`}
                                            disabled={index === links.length - 1}
                                            onClick={() => move(index, 1)}
                                            className="rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-40"
                                        >
                                            <ArrowDown size={14} />
                                        </button>
                                        <button
                                            type="button"
                                            title="Remove"
                                            aria-label={`Remove link ${index + 1}`}
                                            onClick={() =>
                                                onChange(links.filter((_, i) => i !== index))
                                            }
                                            className="rounded-lg p-1.5 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger"
                                        >
                                            <Trash2 size={14} />
                                        </button>
                                    </div>
                                </div>

                                {problem ? (
                                    <p className="mt-1.5 flex items-center gap-1.5 text-xs text-warn">
                                        <AlertCircle size={12} className="shrink-0" />
                                        {problem}
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
                onClick={() => onChange([...links, { label: '', url: '' }])}
            >
                <Plus size={14} />
                Add link
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
