// SupportAnnouncements.tsx
// The announcements on the Support menu's Latest Features page, grouped by release.
//
// The classic page prints every announcement in full, screenshots and all, which in the current
// release is thirty of them. Here each announcement is a row -- its icon, title and summary --
// that opens in place to show the rest: the details, why it matters, how to try it, the
// screenshots and the shortcuts to the right page. The page reads as a list to scan first and an
// announcement to read second. The pieces are the ones the admin preview of this page is built
// from (LatestFeatureParts), so an administrator choosing what to share sees what users read.
//
// Shortcuts follow lib/latestFeatureShortcuts.ts: a V2 page through the router where V2 has one,
// the page as written where it does not, and another site in a new tab.

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { clsx } from 'clsx';
import { ArrowUpRight } from 'lucide-react';
import { FeatureDetails, FeatureDisclosure, ReleaseGroupPanel } from '../admin/LatestFeatureParts';
import { resolveLatestFeatureIcon } from '../admin/latestFeatureIcons';
import {
    filterGroups,
    latestFeatureCardId,
    safeLatestFeatureHref,
    type LatestFeature,
    type LatestFeatureAction,
    type LatestFeatureGroup,
} from '../../lib/latestFeatures';
import {
    resolveLatestFeatureShortcut,
    safeShortcutRouteHref,
    type LatestFeatureShortcutRoute,
    type LatestFeatureShortcutTarget,
} from '../../lib/latestFeatureShortcuts';
import { requestTour } from '../../lib/tours';
import { useChatStore } from '../../stores/chatStore';

/** Shown where an announcement has no page to open, worded as the classic page words it. */
export const PASSIVE_NOTE =
    'This is mostly a behind-the-scenes improvement managed by your admins. You will usually notice it through a smoother experience rather than a new user control.';

const shortcutClass = clsx(
    'inline-flex items-center gap-1.5 rounded font-medium text-accent',
    'hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
);

/**
 * Set the destination up before the router moves there.
 *
 * A tutorial shortcut asks the page to start its guided tour. A chat shortcut arrives at an empty
 * chat, as the rail's Chats link does -- unless a reply is still streaming, which is returned to
 * rather than swapped out.
 */
function prepareRoute(target: LatestFeatureShortcutRoute) {
    if (target.tour) {
        requestTour(target.tour);
    }
    if (target.freshChat) {
        const chat = useChatStore.getState();
        if (!chat.streaming) {
            chat.startNewConversation();
        }
    }
}

function ShortcutLink({
    action,
    target,
}: {
    action: LatestFeatureAction;
    target: LatestFeatureShortcutTarget;
}) {
    const Icon = resolveLatestFeatureIcon(action.icon);

    if (target.kind === 'route') {
        return (
            <Link
                to={safeShortcutRouteHref(target.path)}
                onClick={() => prepareRoute(target)}
                className={shortcutClass}
            >
                <Icon size={14} aria-hidden="true" className="shrink-0" />
                {action.label}
            </Link>
        );
    }

    const external = target.kind === 'external';
    return (
        <a
            href={safeLatestFeatureHref(target.href)}
            {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
            className={shortcutClass}
        >
            <Icon size={14} aria-hidden="true" className="shrink-0" />
            {action.label}
            <ArrowUpRight size={13} aria-hidden="true" className="shrink-0" />
            <span className="sr-only">
                {external ? ' (opens in a new tab)' : ' (opens in the classic interface)'}
            </span>
        </a>
    );
}

/** The pages an announcement points to, or the classic note when it points nowhere. */
export function AnnouncementShortcuts({ feature }: { feature: LatestFeature }) {
    const shortcuts = feature.actions.flatMap((action) => {
        const target = resolveLatestFeatureShortcut(action.href);
        return target ? [{ action, target }] : [];
    });

    if (!shortcuts.length) {
        return (
            <p className="max-w-[72ch] border-t border-dashed border-edge-strong pt-3 text-text-3">
                {PASSIVE_NOTE}
            </p>
        );
    }

    return (
        <div>
            <p className="text-xs font-semibold text-text-1">Open the right page</p>
            <ul className="mt-1.5 space-y-1.5">
                {shortcuts.map(({ action, target }) => (
                    <li
                        key={`${action.label}-${action.href}`}
                        className="flex max-w-[72ch] flex-wrap items-baseline gap-x-2 gap-y-0.5"
                    >
                        <ShortcutLink action={action} target={target} />
                        {action.description ? (
                            <span className="text-text-3">{action.description}</span>
                        ) : null}
                    </li>
                ))}
            </ul>
        </div>
    );
}

function AnnouncementRow({
    feature,
    open,
    onToggle,
}: {
    feature: LatestFeature;
    open: boolean;
    onToggle: () => void;
}) {
    const Icon = resolveLatestFeatureIcon(feature.icon);
    // The classic page's card id, so a link written for one page lines up on the other.
    const rowId = latestFeatureCardId(feature.id);
    const detailsId = `${rowId}-details`;

    return (
        <li id={rowId} className="scroll-mt-4 py-3">
            <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
                <span
                    aria-hidden="true"
                    className="mt-0.5 hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface-sunken text-text-2 sm:flex"
                >
                    <Icon size={17} />
                </span>
                <div className="min-w-0 flex-1 basis-48">
                    <h2 className="text-sm font-semibold text-text-1">{feature.title}</h2>
                    <p className="mt-0.5 max-w-[80ch] text-[0.8125rem] leading-relaxed text-text-3">
                        {feature.summary}
                    </p>
                </div>
                <FeatureDisclosure
                    label="Details"
                    featureTitle={feature.title}
                    controls={detailsId}
                    open={open}
                    onToggle={onToggle}
                />
            </div>
            {open ? (
                <div className="sm:pl-12">
                    <FeatureDetails
                        id={detailsId}
                        feature={feature}
                        guidanceLabel="How to try it"
                        footer={<AnnouncementShortcuts feature={feature} />}
                    />
                </div>
            ) : null}
        </li>
    );
}

/**
 * The releases that start open: the ones the catalogue marks, or the first one shown when an
 * administrator shared nothing from those, so the page never opens on a wall of closed groups.
 */
export function initiallyOpenGroups(groups: LatestFeatureGroup[]): Set<string> {
    const marked = groups.filter((group) => group.default_expanded).map((group) => group.id);
    if (marked.length) {
        return new Set(marked);
    }
    return new Set(groups.length ? [groups[0].id] : []);
}

function countLabel(count: number): string {
    return `${count} ${count === 1 ? 'announcement' : 'announcements'}`;
}

export function SupportAnnouncementList({
    groups,
    query,
}: {
    groups: LatestFeatureGroup[];
    query: string;
}) {
    const [openGroups, setOpenGroups] = useState<Set<string> | null>(null);
    const [openFeatures, setOpenFeatures] = useState<Set<string>>(() => new Set());

    const searching = Boolean(query.trim());
    const shownGroups = useMemo(() => filterGroups(groups, query), [groups, query]);
    const currentOpen = openGroups ?? initiallyOpenGroups(groups);

    const toggleGroup = (groupId: string) => {
        const next = new Set(currentOpen);
        if (next.has(groupId)) {
            next.delete(groupId);
        } else {
            next.add(groupId);
        }
        setOpenGroups(next);
    };

    const toggleFeature = (featureId: string) => {
        setOpenFeatures((current) => {
            const next = new Set(current);
            if (next.has(featureId)) {
                next.delete(featureId);
            } else {
                next.add(featureId);
            }
            return next;
        });
    };

    if (searching && !shownGroups.length) {
        return (
            <p className="rounded-xl border border-edge bg-surface-1 px-4 py-3 text-sm text-text-2">
                No announcements match “{query.trim()}”.
            </p>
        );
    }

    return (
        <div className="space-y-3">
            {shownGroups.map((group) => (
                <ReleaseGroupPanel
                    key={group.id}
                    id={`support-latest-features-${group.id}`}
                    label={group.label}
                    version={group.release_version}
                    description={group.description}
                    summary={countLabel(group.features.length)}
                    // A search opens every release, so a match is never hidden in a closed one.
                    open={searching || currentOpen.has(group.id)}
                    onToggle={() => toggleGroup(group.id)}
                >
                    {group.features.map((feature) => (
                        <AnnouncementRow
                            key={feature.id}
                            feature={feature}
                            open={openFeatures.has(feature.id)}
                            onToggle={() => toggleFeature(feature.id)}
                        />
                    ))}
                </ReleaseGroupPanel>
            ))}
        </div>
    );
}
