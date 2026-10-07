// LatestFeatureParts.tsx
// The pieces both Latest Features cards in the Help group are built from.
//
// Admin Latest Features and the User-Facing Latest Features choices show the same kind of
// content: release groups of announcements, each with details, guidance and screenshots.
// They share one vocabulary so they read as one feature. A release group collapses like any
// other admin field group, an announcement is a row that opens in place, and a screenshot
// opens in the admin dialog. Only what sits beside each row differs: shortcuts for
// administrators, and a share checkbox for what users see.

import { useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { ChevronRight, Info, Maximize2, RotateCcw } from 'lucide-react';
import { AdminModal } from './AdminModal';
import { Skeleton } from '../ui/primitives';
import {
    safeLatestFeatureImageUrl,
    type LatestFeature,
    type LatestFeatureImage,
} from '../../lib/latestFeatures';

/** Marks content that is new in this release, as the classic navigation does. */
export function NewBadge({ className }: { className?: string }) {
    return (
        <span
            className={clsx(
                'shrink-0 rounded-full border border-info/40 bg-info-soft px-2 py-0.5',
                'text-[11px] leading-none font-semibold text-info',
                className,
            )}
        >
            New
        </span>
    );
}

/** The compact button style shared by row shortcuts and bulk actions. */
export const latestFeatureActionClass = clsx(
    'inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-edge px-2.5 py-1.5',
    'text-xs font-medium text-text-1 transition-colors',
    'hover:border-accent hover:bg-surface-2',
    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
    'disabled:cursor-not-allowed disabled:opacity-60',
);

/**
 * One release, collapsed or open.
 *
 * Drawn like an admin field group so the catalogue reads as part of the settings page rather
 * than a document pasted into it. Header actions only show while the group is open, because
 * they act on rows that are otherwise out of sight.
 */
export function ReleaseGroupPanel({
    id,
    label,
    version,
    description,
    summary,
    open,
    onToggle,
    actions,
    children,
}: {
    id: string;
    label: string;
    version?: string;
    description?: string;
    /** Shown at the end of the header, such as a count. */
    summary?: ReactNode;
    open: boolean;
    onToggle: () => void;
    actions?: ReactNode;
    children: ReactNode;
}) {
    const panelId = `${id}-panel`;
    return (
        <div className="rounded-xl border border-edge-strong bg-surface-solid">
            <div
                className={clsx(
                    'flex flex-wrap items-center gap-x-2 rounded-xl',
                    open && 'rounded-b-none bg-surface-sunken',
                )}
            >
                <button
                    type="button"
                    aria-expanded={open}
                    aria-controls={panelId}
                    onClick={onToggle}
                    className={clsx(
                        'flex min-h-11 min-w-0 flex-1 basis-64 items-start gap-2 rounded-xl px-3 py-2.5 text-left',
                        !open && 'hover:bg-surface-sunken',
                    )}
                >
                    <ChevronRight
                        size={14}
                        aria-hidden="true"
                        className={clsx('mt-[3px] shrink-0 text-text-2 transition-transform', open && 'rotate-90')}
                    />
                    {/* Wraps as a unit on a narrow card, so the label never breaks mid-word to
                        make room for the version and the count. */}
                    <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="text-sm font-semibold text-text-1">{label}</span>
                        {version ? (
                            <span className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-text-2">
                                v{version}
                            </span>
                        ) : null}
                        {summary ? <span className="ml-auto text-xs text-text-3">{summary}</span> : null}
                    </span>
                </button>
                {open && actions ? (
                    <div className="flex shrink-0 flex-wrap items-center gap-1.5 px-3 pb-2 sm:pb-0">{actions}</div>
                ) : null}
            </div>

            {open ? (
                <div id={panelId} className="border-t border-edge-strong px-3 sm:px-4">
                    {description ? (
                        <p className="max-w-[72ch] pt-2.5 text-[0.8125rem] leading-relaxed text-text-3">
                            {description}
                        </p>
                    ) : null}
                    <ul className="divide-y divide-edge-strong">{children}</ul>
                </div>
            ) : null}
        </div>
    );
}

/** The disclosure on an announcement row. Names the announcement for screen readers. */
export function FeatureDisclosure({
    label,
    featureTitle,
    controls,
    open,
    onToggle,
}: {
    label: string;
    featureTitle: string;
    controls: string;
    open: boolean;
    onToggle: () => void;
}) {
    return (
        <button
            type="button"
            aria-expanded={open}
            aria-controls={controls}
            onClick={onToggle}
            className={clsx(
                // Pushed to the end of its row, and onto a row of its own when the card is
                // too narrow to hold it beside the text.
                'ml-auto inline-flex min-h-8 shrink-0 items-center gap-1 rounded-lg px-2 text-xs font-medium',
                'text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1',
                'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
            )}
        >
            {label}
            <span className="sr-only"> for {featureTitle}</span>
            <ChevronRight
                size={13}
                aria-hidden="true"
                className={clsx('transition-transform', open && 'rotate-90')}
            />
        </button>
    );
}

/** Screenshots as a strip of thumbnails; one opens full size in the admin dialog. */
export function ScreenshotStrip({ images }: { images: LatestFeatureImage[] }) {
    const [enlarged, setEnlarged] = useState<LatestFeatureImage | null>(null);
    const shown = images.filter((image) => safeLatestFeatureImageUrl(image.url));
    if (!shown.length) {
        return null;
    }

    return (
        <>
            <ul className="grid max-w-3xl grid-cols-2 gap-2 sm:grid-cols-3" aria-label="Screenshots">
                {shown.map((image) => (
                    <li key={image.url}>
                        <button
                            type="button"
                            onClick={() => setEnlarged(image)}
                            className={clsx(
                                'group flex w-full flex-col overflow-hidden rounded-lg border border-edge bg-surface-1 text-left',
                                'transition-colors hover:border-accent',
                                'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
                            )}
                        >
                            <span className="relative block aspect-video w-full overflow-hidden bg-surface-sunken">
                                <img
                                    src={safeLatestFeatureImageUrl(image.url)}
                                    alt={image.alt}
                                    loading="lazy"
                                    className="h-full w-full object-cover object-top"
                                />
                                <span
                                    aria-hidden="true"
                                    className="absolute top-1.5 right-1.5 rounded-md bg-surface-solid/90 p-1 text-text-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
                                >
                                    <Maximize2 size={12} />
                                </span>
                            </span>
                            <span className="truncate px-2 py-1.5 text-xs text-text-2">
                                {image.label || image.title}
                                <span className="sr-only"> (enlarge)</span>
                            </span>
                        </button>
                    </li>
                ))}
            </ul>

            {enlarged ? (
                <AdminModal
                    title={enlarged.title || enlarged.label || 'Screenshot'}
                    description={enlarged.caption || undefined}
                    size="lg"
                    onClose={() => setEnlarged(null)}
                >
                    <img
                        src={safeLatestFeatureImageUrl(enlarged.url)}
                        alt={enlarged.alt}
                        className="mx-auto max-h-[70vh] w-auto max-w-full rounded-lg border border-edge"
                    />
                </AdminModal>
            ) : null}
        </>
    );
}

/**
 * What an announcement says once opened: details, why it matters, its steps, screenshots,
 * and whatever the caller adds at the end.
 *
 * The catalogue phrases every "why" as "This matters because ...", so it needs no heading of
 * its own; a quiet tinted line sets it apart from the details above it.
 */
export function FeatureDetails({
    id,
    feature,
    guidanceLabel,
    footer,
}: {
    id: string;
    feature: LatestFeature;
    guidanceLabel: string;
    footer?: ReactNode;
}) {
    return (
        <div id={id} className="space-y-3 pt-1 pb-3 text-[0.8125rem] leading-relaxed text-text-2">
            {feature.details ? <p className="max-w-[72ch]">{feature.details}</p> : null}
            {feature.why ? (
                <p className="flex max-w-[72ch] items-start gap-2 rounded-lg border border-edge bg-surface-2 px-3 py-2">
                    <Info size={13} aria-hidden="true" className="mt-1 shrink-0 text-text-3" />
                    <span>{feature.why}</span>
                </p>
            ) : null}
            {feature.guidance.length ? (
                <div>
                    <p className="text-xs font-semibold text-text-1">{guidanceLabel}</p>
                    <ul className="mt-1 max-w-[72ch] list-disc space-y-0.5 pl-5">
                        {feature.guidance.map((step) => (
                            <li key={step}>{step}</li>
                        ))}
                    </ul>
                </div>
            ) : null}
            <ScreenshotStrip images={feature.images} />
            {footer}
        </div>
    );
}

/** Rows standing in for a catalogue that is still loading. */
export function CatalogueSkeleton() {
    return (
        <div className="space-y-2" aria-hidden="true">
            <Skeleton className="h-11 w-full rounded-xl" />
            <Skeleton className="h-11 w-full rounded-xl" />
            <Skeleton className="h-11 w-full rounded-xl" />
        </div>
    );
}

/** A catalogue that could not be loaded, with a way to try again. */
export function CatalogueError({ message, onRetry }: { message: string; onRetry: () => void }) {
    return (
        <div
            role="alert"
            className="flex flex-wrap items-center gap-3 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-xs text-text-2"
        >
            <span className="min-w-0 flex-1">{message}</span>
            <button type="button" className={latestFeatureActionClass} onClick={onRetry}>
                <RotateCcw size={12} aria-hidden="true" />
                Try again
            </button>
        </div>
    );
}
