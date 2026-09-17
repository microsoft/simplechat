// AppRoleRoster.tsx
// Every app role requirement in the deployment, gathered in one place.
//
// Each switch here is the same stored value as the one on the tab that owns the feature,
// not a copy of it: both write the same key into the page draft, so flipping a role here
// and flipping it there are the same edit. That is deliberate. Read individually, a role
// requirement tells you little; read together they are the access policy, and deciding
// whether it is coherent means seeing all of them at once.
//
// The roster is built from the field schema, so a role requirement that nobody has
// declared is absent here for the same reason it is absent everywhere else in this UI:
// the page's fallback scan only ever sees `enable_*` keys.
//
// What the schema cannot supply is what an administrator has to know before flipping one:
// the exact Entra role value to assign, and what changes in each direction. That comes
// from the server registry in `admin_app_roles.py`, merged in by settings key, so a
// requirement the registry does not describe still renders -- just without that detail.

import { useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { Check, Copy, Search, ShieldCheck } from 'lucide-react';
import type { AppRoleEntry } from '../../lib/adminFields';
import { Toggle } from '../ui/primitives';

/** The role value is typed into Entra by hand, so it is worth making copyable. */
function RoleChip({ role }: { role: string }) {
    const [copied, setCopied] = useState(false);

    const copy = async () => {
        try {
            await navigator.clipboard.writeText(role);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
        } catch {
            // Selectable on screen regardless; a refused clipboard is not worth
            // reporting as an error.
        }
    };

    return (
        <button
            type="button"
            onClick={() => void copy()}
            title={`Copy the ${role} role value`}
            aria-label={`Copy the ${role} app role value`}
            className={clsx(
                'inline-flex items-center gap-1.5 rounded-md bg-surface-2 px-2 py-0.5',
                'font-mono text-xs text-text-2 transition-colors hover:text-text-1',
            )}
        >
            {role}
            {copied ? (
                <Check size={11} className="text-ok" />
            ) : (
                <Copy size={11} className="opacity-60" />
            )}
        </button>
    );
}

export function AppRoleRoster({
    entries,
    values,
    help,
    disabled,
    onChange,
    onNavigate,
}: {
    entries: AppRoleEntry[];
    values: Record<string, boolean>;
    help?: string;
    disabled?: boolean;
    onChange: (key: string, next: boolean) => void;
    onNavigate?: (sectionId: string) => void;
}) {
    const [query, setQuery] = useState('');

    const rows = useMemo(
        () =>
            entries.map((entry) => ({
                entry,
                enforced: Boolean(values[entry.key]),
                // A requirement whose feature is off still saves and still shows, but it
                // is not currently restricting anything, and this is the only place an
                // administrator would find that out.
                inert: Boolean(entry.dependsOn && !values[entry.dependsOn]),
            })),
        [entries, values],
    );

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return rows;
        }
        return rows.filter((row) =>
            `${row.entry.role ?? ''} ${row.entry.label} ${row.entry.key} ${row.entry.grants ?? ''}`
                .toLowerCase()
                .includes(needle),
        );
    }, [rows, query]);

    if (entries.length === 0) {
        return (
            <p className="py-3 text-xs leading-relaxed text-text-3">
                No app role requirements are declared yet.
            </p>
        );
    }

    const enforced = rows.filter((row) => row.enforced).length;

    return (
        <div className="py-3">
            {help ? <p className="mb-3 text-xs leading-relaxed text-text-3">{help}</p> : null}

            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-xs text-text-3">
                    <ShieldCheck size={13} className="shrink-0" />
                    {enforced} of {entries.length} requirements are being enforced.
                </span>

                <div className="relative min-w-48 flex-1 sm:max-w-64">
                    <Search
                        size={13}
                        className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3"
                    />
                    <input
                        type="search"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="Filter roles…"
                        aria-label="Filter app role requirements"
                        className={clsx(
                            'w-full rounded-lg border border-edge bg-surface-1 py-1.5 pr-2 pl-7',
                            'text-xs text-text-1 placeholder:text-text-3',
                            'focus:border-accent focus:outline-none',
                        )}
                    />
                </div>
            </div>

            <ul className="space-y-1">
                {visible.map(({ entry, enforced: isEnforced, inert }) => (
                    <li key={entry.key} className="rounded-lg border border-edge px-3 py-2">
                        <Toggle
                            label={entry.label}
                            description={`${entry.groupLabel} › ${entry.tabLabel} › ${entry.sectionLabel}`}
                            checked={isEnforced}
                            disabled={disabled}
                            onChange={(next) => onChange(entry.key, next)}
                        />

                        <div className="mt-1.5 ml-14 space-y-1.5">
                            {entry.role || onNavigate ? (
                                <div className="flex flex-wrap items-center gap-2">
                                    {entry.role ? <RoleChip role={entry.role} /> : null}
                                    {onNavigate ? (
                                        <button
                                            type="button"
                                            onClick={() => onNavigate(entry.sectionId)}
                                            className="text-xs text-accent transition-colors hover:underline"
                                        >
                                            Go to setting
                                        </button>
                                    ) : null}
                                </div>
                            ) : null}

                            {isEnforced && entry.grants ? (
                                <p className="text-xs leading-relaxed text-text-2">
                                    <span className="font-medium">Restricted to the role:</span>{' '}
                                    {entry.grants}
                                </p>
                            ) : null}

                            {!isEnforced && entry.whenOff ? (
                                <p className="text-xs leading-relaxed text-text-2">
                                    <span className="font-medium">Not enforced:</span>{' '}
                                    {entry.whenOff}
                                </p>
                            ) : null}

                            {inert ? (
                                <p className="rounded-md bg-warn-soft px-2 py-1 text-xs text-warn">
                                    Has no effect right now, because the feature it guards is
                                    switched off.
                                </p>
                            ) : null}
                        </div>
                    </li>
                ))}

                {visible.length === 0 ? (
                    <li className="py-3 text-center text-xs text-text-3">
                        No role requirements match “{query}”.
                    </li>
                ) : null}
            </ul>
        </div>
    );
}
