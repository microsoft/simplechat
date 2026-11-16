// SectionCard.tsx
// The distinct card V2 Admin Settings draws every section in, for surfaces outside Admin.
//
// Admin's `SettingsSection` owns its card markup inline, alongside schema-driven fields this
// component knows nothing about. The workflow editor needs the same object -- a header band
// with the section's icon, a title large enough to find while scrolling, a line of facts, and
// the Admin status chip -- around controls it lays out itself. The classes match Admin's card
// (bar one narrow-width allowance, noted below), so a section here and a section there read as
// the same thing, and so `.admin-field` rows inside resolve their container queries against
// this card the way they do in Admin.
//
// The title takes focus (`tabIndex={-1}`) so an "On this page" jump can land a keyboard or
// screen reader user on the card it scrolled to, as Admin's index does.

import { clsx } from 'clsx';
import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import type { SectionStatus } from '../../lib/adminSections';
import { presentSectionStatus } from '../admin/sectionStatusPresentation';

export function SectionCard({
    id,
    title,
    icon: Icon,
    meta,
    status = 'none',
    actions,
    ariaLabel,
    headingLevel = 2,
    className,
    bodyClassName,
    children,
    ...data
}: {
    /** The card's DOM id. The title is `${id}-title`, which an index jump focuses. */
    id: string;
    title: ReactNode;
    icon: LucideIcon;
    /** One line of facts under the title. */
    meta?: ReactNode;
    status?: SectionStatus;
    /** Controls drawn in the header band beside the status chip. */
    actions?: ReactNode;
    /**
     * Names the region instead of its visible title, for a card whose established accessible
     * name differs from the title it now shows.
     */
    ariaLabel?: string;
    headingLevel?: 2 | 3;
    className?: string;
    bodyClassName?: string;
    children?: ReactNode;
    [dataAttribute: `data-${string}`]: string | undefined;
}) {
    const titleId = `${id}-title`;
    const presentation = presentSectionStatus(status);
    const Heading = headingLevel === 3 ? 'h3' : 'h2';

    return (
        <section
            id={id}
            aria-label={ariaLabel}
            aria-labelledby={ariaLabel ? undefined : titleId}
            className={clsx(
                'glass glass-edge rounded-2xl',
                'admin-settings-distinct scroll-mt-4 border-edge-strong',
                className,
            )}
            {...data}
        >
            <div className="flex flex-wrap items-start justify-between gap-3 rounded-t-2xl border-b border-edge-strong bg-surface-2 p-4 sm:px-5">
                {/* Admin's header, except that the title column asks for 15rem before the chip may
                    sit beside it, so a narrow card wraps the chip rather than breaking the facts
                    line mid-word. */}
                <div className="flex min-w-0 flex-1 basis-60 flex-wrap items-start gap-3">
                    <span
                        aria-hidden="true"
                        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-edge-strong bg-surface-solid text-text-2"
                    >
                        <Icon size={20} />
                    </span>
                    <div className="min-w-0 flex-1 basis-40">
                        <Heading
                            id={titleId}
                            tabIndex={-1}
                            className="text-lg leading-snug font-semibold text-text-1"
                        >
                            {title}
                        </Heading>
                        {meta ? <p className="mt-1 text-xs text-text-3">{meta}</p> : null}
                    </div>
                </div>

                {presentation || actions ? (
                    <div className="flex max-w-full min-w-0 flex-wrap items-center gap-2">
                        {presentation ? (
                            // Free to shrink once it has wrapped onto its own line, so a long
                            // status at a large text size wraps inside the card instead of past it.
                            <span
                                className={clsx(
                                    'flex max-w-full min-w-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs',
                                    presentation.className,
                                )}
                            >
                                <presentation.Icon size={11} aria-hidden="true" className="shrink-0" />
                                {presentation.label}
                            </span>
                        ) : null}
                        {actions}
                    </div>
                ) : null}
            </div>

            <div className={clsx('admin-section-body p-4 sm:p-5', bodyClassName)}>{children}</div>
        </section>
    );
}
