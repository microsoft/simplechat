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

import { clsx } from 'clsx';
import { ShieldCheck } from 'lucide-react';
import type { AppRoleEntry } from '../../lib/adminFields';
import { Toggle } from '../ui/primitives';

export function AppRoleRoster({
    entries,
    values,
    help,
    disabled,
    onChange,
}: {
    entries: AppRoleEntry[];
    values: Record<string, boolean>;
    help?: string;
    disabled?: boolean;
    onChange: (key: string, next: boolean) => void;
}) {
    if (entries.length === 0) {
        return (
            <p className="py-3 text-xs leading-relaxed text-text-3">
                No app role requirements are declared yet.
            </p>
        );
    }

    const enforced = entries.filter((entry) => values[entry.key]).length;

    return (
        <div className="py-3">
            {help ? (
                <p className="mb-3 text-xs leading-relaxed text-text-3">{help}</p>
            ) : null}

            <p className="mb-3 flex items-center gap-1.5 text-xs text-text-3">
                <ShieldCheck size={13} className="shrink-0" />
                {enforced} of {entries.length} requirements are being enforced.
            </p>

            <ul className="space-y-1">
                {entries.map((entry) => (
                    <li
                        key={entry.key}
                        className={clsx('rounded-lg border border-edge px-3 py-1.5')}
                    >
                        <Toggle
                            label={entry.label}
                            description={`${entry.groupLabel} › ${entry.tabLabel} › ${entry.sectionLabel}`}
                            checked={Boolean(values[entry.key])}
                            disabled={disabled}
                            onChange={(next) => onChange(entry.key, next)}
                        />
                    </li>
                ))}
            </ul>
        </div>
    );
}
