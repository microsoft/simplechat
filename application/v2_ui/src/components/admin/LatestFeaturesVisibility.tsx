// LatestFeaturesVisibility.tsx
// Which release announcements end users see on the Support menu's Latest Features page.
//
// The classic page splits this across two tabs: a checklist on User-Facing Latest Features,
// and a read-only preview of older releases on Admin Latest Features. Here they are one
// list. Each announcement carries its share checkbox and opens to show exactly what users
// read -- the details, the steps they are given, the screenshots, and the shortcuts they
// would see with the settings as currently edited -- so the decision is made with the
// content in view.
//
// The whole map is written into the page draft and saved with everything else. Every
// announcement is named in it, so a save does not depend on what the stored map happened
// to contain, and the server merges it over the stored choices regardless.

import { useMemo, useState } from 'react';
import { clsx } from 'clsx';
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
    allFeatures,
    countShared,
    filterGroups,
    isActionShown,
    latestFeatureCardId,
    readVisibility,
    safeLatestFeatureHref,
    type LatestFeature,
    type LatestFeatureGroup,
} from '../../lib/latestFeatures';
import type { AdminField } from '../../lib/adminFields';

/** The shortcuts a user would see, opened in a new tab so unsaved settings survive. */
function UserShortcuts({
    feature,
    read,
}: {
    feature: LatestFeature;
    read: (key: string) => unknown;
}) {
    const shown = feature.actions.filter(
        (action) => isActionShown(action, read) && safeLatestFeatureHref(action.href),
    );
    if (!shown.length) {
        return null;
    }
    return (
        <div>
            <p className="text-xs font-semibold text-text-1">Shortcuts users see</p>
            <div className="mt-1.5 flex flex-wrap gap-2">
                {shown.map((action) => {
                    const Icon = resolveLatestFeatureIcon(action.icon);
                    return (
                        <a
                            key={`${action.label}-${action.href}`}
                            className={latestFeatureActionClass}
                            href={safeLatestFeatureHref(action.href)}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={action.description || undefined}
                        >
                            <Icon size={13} aria-hidden="true" />
                            {action.label}
                            <ArrowUpRight size={12} aria-hidden="true" className="text-text-3" />
                            <span className="sr-only"> (opens in a new tab)</span>
                        </a>
                    );
                })}
            </div>
        </div>
    );
}

function UserFeatureRow({
    feature,
    shared,
    disabled,
    open,
    onShare,
    onToggle,
    read,
}: {
    feature: LatestFeature;
    shared: boolean;
    disabled: boolean;
    open: boolean;
    onShare: (next: boolean) => void;
    onToggle: () => void;
    read: (key: string) => unknown;
}) {
    const Icon = resolveLatestFeatureIcon(feature.icon);
    const rowId = `user-${latestFeatureCardId(feature.id)}`;
    const checkboxId = `${rowId}-shared`;
    const previewId = `${rowId}-preview`;

    return (
        <li id={rowId} className="py-2.5">
            <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
                <input
                    id={checkboxId}
                    type="checkbox"
                    className="mt-1.5 h-4 w-4 shrink-0 cursor-pointer accent-[var(--accent)] disabled:cursor-not-allowed"
                    checked={shared}
                    disabled={disabled}
                    onChange={(event) => onShare(event.target.checked)}
                />
                <span
                    aria-hidden="true"
                    className={clsx(
                        'mt-0.5 hidden h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-sunken sm:flex',
                        shared ? 'text-text-2' : 'text-text-3',
                    )}
                >
                    <Icon size={16} />
                </span>
                <div className="min-w-0 flex-1 basis-40">
                    <label
                        htmlFor={checkboxId}
                        className={clsx(
                            'flex cursor-pointer flex-wrap items-baseline gap-x-2 text-sm font-semibold',
                            shared ? 'text-text-1' : 'text-text-2',
                        )}
                    >
                        {feature.title}
                        {!shared ? (
                            <span className="rounded-full bg-surface-2 px-1.5 py-0.5 text-[11px] leading-none font-medium text-text-3">
                                Hidden from users
                            </span>
                        ) : null}
                    </label>
                    <p className="mt-0.5 max-w-[80ch] text-[0.8125rem] leading-relaxed text-text-3">
                        {feature.summary}
                    </p>
                </div>
                <FeatureDisclosure
                    label="Preview"
                    featureTitle={feature.title}
                    controls={previewId}
                    open={open}
                    onToggle={onToggle}
                />
            </div>
            {open ? (
                <div className="sm:pl-[4.5rem]">
                    <FeatureDetails
                        id={previewId}
                        feature={feature}
                        guidanceLabel="Steps users are given"
                        footer={<UserShortcuts feature={feature} read={read} />}
                    />
                </div>
            ) : null}
        </li>
    );
}

export function LatestFeaturesVisibility({
    field,
    groups,
    loading,
    error,
    onRetry,
    value,
    disabled,
    query,
    read,
    onChange,
}: {
    field: AdminField;
    groups: LatestFeatureGroup[] | null;
    loading: boolean;
    error: string | null;
    onRetry: () => void;
    /** The stored or drafted visibility map. */
    value: unknown;
    disabled: boolean;
    /** The page search; narrows the rows to matching announcements. */
    query: string;
    /** Reads the settings being edited, so previews follow unsaved switches. */
    read: (key: string) => unknown;
    onChange: (next: Record<string, boolean>) => void;
}) {
    const [openGroups, setOpenGroups] = useState<Set<string> | null>(null);
    const [openFeatures, setOpenFeatures] = useState<Set<string>>(() => new Set());

    const catalogue = useMemo(() => groups ?? [], [groups]);
    const visibility = useMemo(() => readVisibility(value, catalogue), [value, catalogue]);
    const searching = Boolean(query.trim());
    const shownGroups = useMemo(() => filterGroups(catalogue, query), [catalogue, query]);
    const total = allFeatures(catalogue).length;
    const shared = countShared(visibility, allFeatures(catalogue));

    const isGroupOpen = (group: LatestFeatureGroup) =>
        searching || (openGroups ? openGroups.has(group.id) : group.default_expanded);

    const toggleGroup = (group: LatestFeatureGroup) => {
        setOpenGroups((current) => {
            const next = new Set(
                current ?? catalogue.filter((item) => item.default_expanded).map((item) => item.id),
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

    const share = (features: LatestFeature[], next: boolean) => {
        const updated = { ...visibility };
        for (const feature of features) {
            updated[feature.id] = next;
        }
        onChange(updated);
    };

    return (
        <div className="py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <p className="text-sm font-semibold text-text-1">{field.label}</p>
                {groups ? (
                    <p className="text-xs text-text-3" aria-live="polite">
                        {shared} of {total} shared
                    </p>
                ) : null}
            </div>
            {field.help ? (
                <p className="mt-1 max-w-[72ch] text-[0.8125rem] leading-relaxed text-text-3">{field.help}</p>
            ) : null}

            <div className="mt-3 space-y-3">
                {!groups && (loading || !error) ? <CatalogueSkeleton /> : null}
                {error && !groups ? <CatalogueError message={error} onRetry={onRetry} /> : null}

                {groups && searching && !shownGroups.length ? (
                    <p className="text-xs text-text-3">No announcements match “{query.trim()}”.</p>
                ) : null}

                {shownGroups.map((group) => {
                    const open = isGroupOpen(group);
                    const groupShared = countShared(visibility, group.features);
                    const allShared = groupShared === group.features.length;
                    const noneShared = groupShared === 0;
                    return (
                        <ReleaseGroupPanel
                            key={group.id}
                            id={`user-latest-features-${group.id}`}
                            label={group.label}
                            version={group.release_version}
                            description={group.description}
                            summary={`${groupShared} of ${group.features.length} shared`}
                            open={open}
                            onToggle={() => toggleGroup(group)}
                            actions={
                                <>
                                    <button
                                        type="button"
                                        className={latestFeatureActionClass}
                                        disabled={disabled || allShared}
                                        onClick={() => share(group.features, true)}
                                    >
                                        Share all
                                        <span className="sr-only"> in {group.label}</span>
                                    </button>
                                    <button
                                        type="button"
                                        className={latestFeatureActionClass}
                                        disabled={disabled || noneShared}
                                        onClick={() => share(group.features, false)}
                                    >
                                        Hide all
                                        <span className="sr-only"> in {group.label}</span>
                                    </button>
                                </>
                            }
                        >
                            {group.features.map((feature) => (
                                <UserFeatureRow
                                    key={feature.id}
                                    feature={feature}
                                    shared={visibility[feature.id] ?? true}
                                    disabled={disabled}
                                    open={openFeatures.has(feature.id)}
                                    onShare={(next) => share([feature], next)}
                                    onToggle={() => toggleFeature(feature.id)}
                                    read={read}
                                />
                            ))}
                        </ReleaseGroupPanel>
                    );
                })}
            </div>
        </div>
    );
}
