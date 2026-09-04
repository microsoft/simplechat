// AppRoleRequirements.tsx
// The whole access policy, readable in one place.
//
// Role requirements are decided on the tab that owns each feature, which is right, but it
// means "who can do what in this deployment" is spread across seven tabs and cannot be
// answered without visiting all of them. This is that answer: every requirement, the
// Entra role value to assign, what enforcing it restricts, and what happens when it is
// left off.
//
// Two things it deliberately does that the server-rendered roster could not. It is built
// from a server-declared registry rather than by scanning the page for checkboxes, so it
// includes requirements whose settings key does not follow the `require_member_of_`
// naming the old selector matched. And it says, per row, when a requirement is currently
// inert because the feature it guards is switched off — enforcing a role for a disabled
// feature is not harmful, but believing it is doing something is.

import { useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { Check, Copy, Search, ShieldCheck } from 'lucide-react';
import { asBoolean, type AppRoleRequirement } from '../../lib/adminFields';
import { Toggle } from '../ui/primitives';
import type { Json } from '../../lib/types';

function RoleChip({ role }: { role: string }) {
    const [copied, setCopied] = useState(false);

    const copy = async () => {
        try {
            await navigator.clipboard.writeText(role);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
        } catch {
            // Selectable on screen regardless; a refused clipboard is not an error
            // worth reporting.
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

export function AppRoleRequirements({
    requirements,
    help,
    settings,
    draft,
    disabled,
    onChange,
    onNavigate,
}: {
    requirements: AppRoleRequirement[];
    help?: string;
    settings: Json;
    draft: Json;
    disabled?: boolean;
    onChange: (key: string, next: boolean) => void;
    onNavigate: (sectionId: string) => void;
}) {
    const [query, setQuery] = useState('');

    const read = (key: string): unknown =>
        Object.prototype.hasOwnProperty.call(draft, key) ? draft[key] : settings[key];

    const rows = useMemo(
        () =>
            requirements.map((requirement) => ({
                requirement,
                enforced: asBoolean(read(requirement.key)),
                // A requirement whose feature is off still saves and still shows, but it
                // is not currently restricting anything, and saying so here is the only
                // place an administrator would find that out.
                inert: Boolean(
                    requirement.depends_on && !asBoolean(read(requirement.depends_on)),
                ),
            })),
        // `settings` and `draft` are read through the closure above, so both belong here.
        [requirements, settings, draft],
    );

    const enforcedCount = rows.filter((row) => row.enforced).length;

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return rows;
        }
        return rows.filter((row) =>
            `${row.requirement.role} ${row.requirement.label} ${row.requirement.key} ${row.requirement.grants}`
                .toLowerCase()
                .includes(needle),
        );
    }, [rows, query]);

    return (
        <div className="py-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 text-sm font-medium text-text-1">
                    <ShieldCheck size={15} className="text-text-3" />
                    {enforcedCount} of {rows.length} enforced
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

            {help ? <p className="mb-2 text-xs leading-relaxed text-text-3">{help}</p> : null}

            <div className="divide-y divide-edge rounded-lg border border-edge">
                {visible.map(({ requirement, enforced, inert }) => (
                    <div key={requirement.key} className="p-3">
                        <Toggle
                            label={requirement.label}
                            checked={enforced}
                            disabled={disabled}
                            onChange={(next) => onChange(requirement.key, next)}
                        />

                        <div className="mt-2 ml-14 space-y-1.5">
                            <div className="flex flex-wrap items-center gap-2">
                                <RoleChip role={requirement.role} />
                                <button
                                    type="button"
                                    onClick={() => onNavigate(requirement.section_id)}
                                    className="text-xs text-accent transition-colors hover:underline"
                                >
                                    Go to setting
                                </button>
                            </div>

                            <p className="text-xs leading-relaxed text-text-2">
                                {enforced ? (
                                    <>
                                        <span className="font-medium">Restricted to the role:</span>{' '}
                                        {requirement.grants}
                                    </>
                                ) : (
                                    <>
                                        <span className="font-medium">Not enforced:</span>{' '}
                                        {requirement.when_off}
                                    </>
                                )}
                            </p>

                            {inert ? (
                                <p className="rounded-md bg-warn-soft px-2 py-1 text-xs text-warn">
                                    Has no effect right now, because the feature it guards is
                                    switched off.
                                </p>
                            ) : null}
                        </div>
                    </div>
                ))}

                {visible.length === 0 ? (
                    <p className="p-4 text-center text-xs text-text-3">
                        No role requirements match “{query}”.
                    </p>
                ) : null}
            </div>
        </div>
    );
}
