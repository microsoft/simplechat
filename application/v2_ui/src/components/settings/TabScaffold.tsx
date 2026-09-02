// TabScaffold.tsx
// Shared pieces for the settings tabs: section framing, and the notice a tab shows before
// it has been built.

import type { ReactNode } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { GlassPanel } from '../ui/primitives';

/**
 * One titled group of controls.
 *
 * The description is not decoration: several of these settings are only meaningful if you
 * know what they affect, and a bare label leaves the user guessing.
 */
export function SettingsSection({
    title,
    description,
    children,
}: {
    title: string;
    description?: string;
    children: ReactNode;
}) {
    return (
        <GlassPanel className="p-4">
            <h2 className="text-sm font-semibold text-text-1">{title}</h2>
            {description && (
                <p className="mt-1 text-xs leading-relaxed text-text-3">{description}</p>
            )}
            <div className="mt-3">{children}</div>
        </GlassPanel>
    );
}

/**
 * Stands in for a tab that has not been rebuilt yet.
 *
 * Links to the equivalent classic page rather than only apologising, so the capability
 * stays reachable while V2 catches up.
 */
export function TabNotBuiltYet({
    title,
    description,
    classicHref,
    classicLabel,
}: {
    title: string;
    description: string;
    classicHref: string;
    classicLabel: string;
}) {
    return (
        <GlassPanel className="p-6 text-center">
            <h2 className="text-sm font-semibold text-text-1">{title}</h2>
            <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-text-3">
                {description}
            </p>
            <a
                href={classicHref}
                className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-edge px-3 py-1.5 text-xs font-medium text-text-1 hover:bg-surface-2"
            >
                {classicLabel}
                <ArrowUpRight size={13} />
            </a>
        </GlassPanel>
    );
}
