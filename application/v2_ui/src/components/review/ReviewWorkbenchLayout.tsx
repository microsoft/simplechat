// ReviewWorkbenchLayout.tsx
// The frame of a Review center workbench, drawn as the Workflows workbench is: the search,
// filters and bulk bar above, then a list of one-line rows beside the selected record's
// detail once there is room, stacked on narrow screens.

import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { CircleCheck, TriangleAlert } from 'lucide-react';
import { isRecord } from '../../lib/workspaceAuthoring';

/** What a record's editor leaves for the workbench after a save, in the location state. */
export interface ReviewSavedNotice {
    message: string;
    warning?: boolean;
}

/** The save an editor just returned from, if the workbench was opened that way. */
export function useReviewSavedNotice(): ReviewSavedNotice | null {
    const location = useLocation();
    const state = isRecord(location.state) ? location.state : null;
    const notice = state && isRecord(state.reviewNotice) ? state.reviewNotice : null;
    if (!notice || typeof notice.message !== 'string' || !notice.message) return null;
    return { message: notice.message, warning: notice.warning === true };
}

export function ReviewSavedStatus({ notice, testId }: { notice: ReviewSavedNotice | null; testId: string }) {
    if (!notice) return null;
    const Icon = notice.warning ? TriangleAlert : CircleCheck;
    return (
        <p role="status" data-testid={testId} className="inline-flex items-start gap-1.5 text-xs text-text-2">
            <Icon size={13} aria-hidden="true" className={notice.warning ? 'mt-0.5 shrink-0 text-warn' : 'mt-0.5 shrink-0 text-ok'} />
            {notice.message}
        </p>
    );
}

export function ReviewWorkbenchLayout({
    testId,
    label,
    header,
    list,
    pager,
    detail,
}: {
    testId: string;
    /** The workbench's name, for the group around it. */
    label: string;
    /** Search, filters, notices and the bulk bar. */
    header: ReactNode;
    list: ReactNode;
    pager: ReactNode;
    detail: ReactNode;
}) {
    return (
        <section aria-label={label} data-testid={testId} className="@container flex h-full min-h-0 min-w-0 flex-col gap-3 p-4 lg:px-6">
            <div className="shrink-0 space-y-3">{header}</div>
            <div className="min-h-0 flex-1 overflow-y-auto @3xl:overflow-hidden">
                <div className="grid min-w-0 overflow-hidden rounded-xl border border-edge-strong bg-surface-solid @3xl:h-full @3xl:grid-cols-[minmax(18rem,26rem)_minmax(0,1fr)]">
                    <div className="flex max-h-[28rem] min-h-0 flex-col border-b border-edge-strong @3xl:max-h-none @3xl:border-r @3xl:border-b-0">
                        <div className="min-h-0 flex-1 overflow-y-auto">{list}</div>
                        {pager}
                    </div>
                    <div className="@container flex min-h-0 min-w-0 flex-col @3xl:overflow-y-auto">{detail}</div>
                </div>
            </div>
        </section>
    );
}

/** The detail pane's placeholder while nothing is selected. */
export function ReviewDetailEmpty({ title, description }: { title: string; description: string }) {
    return (
        <div className="flex h-full min-h-[12rem] flex-col items-center justify-center px-6 py-10 text-center">
            <p className="text-sm font-medium text-text-1">{title}</p>
            <p className="mt-1 max-w-sm text-[0.8125rem] leading-relaxed text-text-3">{description}</p>
        </div>
    );
}
