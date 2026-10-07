// AdminLatestFeatures.tsx
// The Admin Latest Features catalogue, as the body of its V2 section card.
//
// The classic page renders this tab from the admin release catalogue rather than from
// settings, so the navigation declares no sections for it. V2 does the same: the page draws
// one card for the tab and this fills it. What an administrator gets from it is a guided
// tour of each release -- what changed, why it matters, how to roll it out -- with
// shortcuts that open the settings involved. A shortcut jumps to the matching card when
// V2 draws one, and opens the classic tab when the work still lives there.

import { useMemo, useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import {
    CatalogueError,
    CatalogueSkeleton,
    FeatureDetails,
    FeatureDisclosure,
    ReleaseGroupPanel,
    latestFeatureActionClass,
} from './LatestFeatureParts';
import { resolveLatestFeatureIcon } from './latestFeatureIcons';
import {
    filterGroups,
    latestFeatureCardId,
    safeClassicAdminTabHref,
    safeLatestFeatureHref,
    type AdminActionTarget,
    type LatestFeature,
    type LatestFeatureAction,
    type LatestFeatureGroup,
} from '../../lib/latestFeatures';

function FeatureShortcut({
    action,
    resolveAction,
    onNavigate,
}: {
    action: LatestFeatureAction;
    resolveAction: (action: LatestFeatureAction) => AdminActionTarget;
    onNavigate: (sectionId: string) => void;
}) {
    const Icon = resolveLatestFeatureIcon(action.icon);

    if (action.kind === 'admin') {
        const target = resolveAction(action);
        if (target.kind === 'section') {
            return (
                <button
                    type="button"
                    className={latestFeatureActionClass}
                    title={action.description || undefined}
                    onClick={() => onNavigate(target.sectionId)}
                >
                    <Icon size={13} aria-hidden="true" />
                    {action.label}
                </button>
            );
        }
        return (
            <a
                className={latestFeatureActionClass}
                href={safeClassicAdminTabHref(target.tab)}
                title={`${action.description ? `${action.description} ` : ''}Opens the classic admin page.`}
            >
                <Icon size={13} aria-hidden="true" />
                {action.label}
                <ArrowUpRight size={12} aria-hidden="true" className="text-text-3" />
                <span className="sr-only"> (classic admin page)</span>
            </a>
        );
    }

    if (!safeLatestFeatureHref(action.href)) {
        return null;
    }
    const external = action.kind === 'external';
    return (
        <a
            className={latestFeatureActionClass}
            href={safeLatestFeatureHref(action.href)}
            title={action.description || undefined}
            {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
        >
            <Icon size={13} aria-hidden="true" />
            {action.label}
            {external ? (
                <>
                    <ArrowUpRight size={12} aria-hidden="true" className="text-text-3" />
                    <span className="sr-only"> (opens in a new tab)</span>
                </>
            ) : null}
        </a>
    );
}

function AdminFeatureRow({
    feature,
    open,
    onToggle,
    resolveAction,
    onNavigate,
}: {
    feature: LatestFeature;
    open: boolean;
    onToggle: () => void;
    resolveAction: (action: LatestFeatureAction) => AdminActionTarget;
    onNavigate: (sectionId: string) => void;
}) {
    const Icon = resolveLatestFeatureIcon(feature.icon);
    const rowId = latestFeatureCardId(feature.id);
    const detailsId = `${rowId}-details`;

    return (
        <li id={rowId} className="scroll-mt-4 py-2.5">
            <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
                <span
                    aria-hidden="true"
                    className="mt-0.5 hidden h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-sunken text-text-2 sm:flex"
                >
                    <Icon size={16} />
                </span>
                <div className="min-w-0 flex-1 basis-40">
                    <p className="text-sm font-semibold text-text-1">{feature.title}</p>
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
                <div className="sm:pl-11">
                    <FeatureDetails
                        id={detailsId}
                        feature={feature}
                        guidanceLabel="Rollout notes"
                        footer={
                            feature.actions.length ? (
                                <div className="flex flex-wrap gap-2 pt-1">
                                    {feature.actions.map((action) => (
                                        <FeatureShortcut
                                            key={`${action.kind}-${action.label}-${action.href}`}
                                            action={action}
                                            resolveAction={resolveAction}
                                            onNavigate={onNavigate}
                                        />
                                    ))}
                                </div>
                            ) : null
                        }
                    />
                </div>
            ) : null}
        </li>
    );
}

export function AdminLatestFeatures({
    groups,
    loading,
    error,
    onRetry,
    query,
    resolveAction,
    onNavigate,
}: {
    groups: LatestFeatureGroup[] | null;
    loading: boolean;
    error: string | null;
    onRetry: () => void;
    /** The page search; narrows the rows to matching announcements. */
    query: string;
    resolveAction: (action: LatestFeatureAction) => AdminActionTarget;
    onNavigate: (sectionId: string) => void;
}) {
    const [openGroups, setOpenGroups] = useState<Set<string> | null>(null);
    const [openFeatures, setOpenFeatures] = useState<Set<string>>(() => new Set());

    const searching = Boolean(query.trim());
    const shownGroups = useMemo(() => filterGroups(groups ?? [], query), [groups, query]);

    // Until an administrator opens or closes one, a release starts the way the catalogue
    // asks: the current release open, older ones closed.
    const isGroupOpen = (group: LatestFeatureGroup) =>
        searching || (openGroups ? openGroups.has(group.id) : group.default_expanded);

    const toggleGroup = (group: LatestFeatureGroup) => {
        setOpenGroups((current) => {
            const next = new Set(
                current ?? (groups ?? []).filter((item) => item.default_expanded).map((item) => item.id),
            );
            if (next.has(group.id)) {
                next.delete(group.id);
            } else {
                next.add(group.id);
            }
            return next;
        });
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

    return (
        <div className="space-y-3 py-1">
            <p className="max-w-[80ch] text-[0.8125rem] leading-relaxed text-text-3">
                What each release changed for administrators, newest first. Shortcuts open the
                settings involved: here when V2 shows them, otherwise on the classic admin page.
                What end users are told lives in User-Facing Latest Features.
            </p>

            {!groups && (loading || !error) ? <CatalogueSkeleton /> : null}
            {error && !groups ? <CatalogueError message={error} onRetry={onRetry} /> : null}

            {groups && searching && !shownGroups.length ? (
                <p className="text-xs text-text-3">No announcements match “{query.trim()}”.</p>
            ) : null}

            {shownGroups.map((group) => {
                const open = isGroupOpen(group);
                return (
                    <ReleaseGroupPanel
                        key={group.id}
                        id={`admin-latest-features-${group.id}`}
                        label={group.label}
                        version={group.release_version}
                        description={group.description}
                        summary={`${group.features.length} ${group.features.length === 1 ? 'feature' : 'features'}`}
                        open={open}
                        onToggle={() => toggleGroup(group)}
                    >
                        {group.features.map((feature) => (
                            <AdminFeatureRow
                                key={feature.id}
                                feature={feature}
                                open={openFeatures.has(feature.id)}
                                onToggle={() => toggleFeature(feature.id)}
                                resolveAction={resolveAction}
                                onNavigate={onNavigate}
                            />
                        ))}
                    </ReleaseGroupPanel>
                );
            })}
        </div>
    );
}
