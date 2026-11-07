// SettingsCard.tsx
// The card, group heading and "On this page" registry shared by every User Settings tab.
//
// User Settings mirrors the Admin Settings design language: each section is a bordered card
// with a tinted header, an icon tile and a title, and the page lists the sections on the
// current tab in a right-hand index. The admin card is tied to admin field definitions, so
// the user card is its own small component that reuses the same classes rather than a fork
// of that one.
//
// A card registers itself with the page when it mounts, so a tab declares its index simply
// by rendering its cards. Cards that are hidden because a capability is off never mount and
// so never appear in the index either.

import {
    createContext,
    useContext,
    useEffect,
    type ReactNode,
} from 'react';
import { clsx } from 'clsx';
import type { LucideIcon } from 'lucide-react';
import type { SectionStatus } from '../../lib/adminSections';
import { presentSectionStatus } from '../admin/sectionStatusPresentation';
import { GlassPanel } from '../ui/primitives';

export interface SettingsSectionEntry {
    sectionId: string;
    label: string;
    groupId: string;
    groupLabel: string;
    Icon: LucideIcon;
    status: SectionStatus;
}

interface SettingsSectionRegistry {
    register: (entry: SettingsSectionEntry) => void;
    unregister: (sectionId: string) => void;
}

export const SettingsSectionRegistryContext = createContext<SettingsSectionRegistry | null>(null);

interface SettingsGroupValue {
    id: string;
    label: string;
}

const SettingsGroupContext = createContext<SettingsGroupValue | null>(null);

/** Turns a label into an id that is stable across renders and safe in a URL fragment. */
export function settingsSectionId(label: string): string {
    return `user-settings-${label
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')}`;
}

/**
 * A titled run of related cards, such as "Appearance" or "Notifications".
 *
 * Groups give a long preferences page a shape a reader can scan, and they become the group
 * headings in the page index.
 */
export function SettingsGroup({
    id,
    label,
    description,
    children,
}: {
    id: string;
    label: string;
    description?: string;
    children: ReactNode;
}) {
    return (
        <SettingsGroupContext.Provider value={{ id, label }}>
            <section aria-labelledby={`user-settings-group-${id}`} className="space-y-3">
                <div className="px-1 pt-2">
                    <h2
                        id={`user-settings-group-${id}`}
                        className="text-xs font-semibold tracking-wide text-text-2 uppercase"
                    >
                        {label}
                    </h2>
                    {description ? <p className="mt-0.5 text-xs text-text-3">{description}</p> : null}
                </div>
                {children}
            </section>
        </SettingsGroupContext.Provider>
    );
}

/**
 * One section of User Settings, styled to match an Admin Settings card.
 *
 * The description is not decoration: several settings only make sense once you know what
 * they affect, and a bare label leaves the user guessing.
 */
export function SettingsCard({
    title,
    description,
    Icon,
    sectionId,
    status = 'none',
    actions,
    bodyClassName,
    children,
}: {
    title: string;
    description?: ReactNode;
    Icon: LucideIcon;
    /** Defaults to an id derived from the title. */
    sectionId?: string;
    status?: SectionStatus;
    /** Controls drawn at the right of the header, such as an export button. */
    actions?: ReactNode;
    bodyClassName?: string;
    children?: ReactNode;
}) {
    const registry = useContext(SettingsSectionRegistryContext);
    const group = useContext(SettingsGroupContext);
    const id = sectionId ?? settingsSectionId(title);
    const groupId = group?.id ?? '';
    const groupLabel = group?.label ?? '';
    const presentation = presentSectionStatus(status);

    useEffect(() => {
        if (!registry) {
            return undefined;
        }
        registry.register({ sectionId: id, label: title, groupId, groupLabel, Icon, status });
        return () => registry.unregister(id);
    }, [registry, id, title, groupId, groupLabel, Icon, status]);

    return (
        <GlassPanel
            id={id}
            edge
            role="region"
            aria-labelledby={`${id}-title`}
            className="admin-settings-distinct scroll-mt-4 border-edge-strong"
        >
            <div className="flex flex-wrap items-start justify-between gap-3 rounded-t-2xl border-b border-edge-strong bg-surface-2 p-4 sm:px-5">
                <div className="flex min-w-0 flex-1 flex-wrap items-start gap-3">
                    <span
                        aria-hidden="true"
                        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-edge-strong bg-surface-solid text-text-2"
                    >
                        <Icon size={20} />
                    </span>
                    <div className="min-w-0 flex-1 basis-40">
                        <h3
                            id={`${id}-title`}
                            tabIndex={-1}
                            className="text-lg leading-snug font-semibold text-text-1"
                        >
                            {title}
                        </h3>
                        {description ? (
                            <p className="mt-1 max-w-[72ch] text-xs leading-relaxed text-text-3">
                                {description}
                            </p>
                        ) : null}
                    </div>
                </div>
                {actions || presentation ? (
                    <div className="flex max-w-full min-w-0 flex-wrap items-center gap-2">
                        {actions}
                        {presentation ? (
                            <span
                                className={clsx(
                                    'flex max-w-full min-w-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs',
                                    presentation.className,
                                )}
                            >
                                <presentation.Icon size={11} className="shrink-0" />
                                {presentation.label}
                            </span>
                        ) : null}
                    </div>
                ) : null}
            </div>
            <div className={clsx('admin-section-body p-4 sm:p-5', bodyClassName)}>{children}</div>
        </GlassPanel>
    );
}
