// NotificationsPager.tsx
// The numbered pager under the Notifications list: Previous, a window of page numbers, Next.
//
// Page numbers are real buttons, not links, because the page keeps its view in the address and
// owns the change. Only the current page is marked, and every control has a name that says which
// page it goes to, so a screen reader hears "Page 3" rather than a bare "3".
//
// Previous on the first page and Next on the last are marked aria-disabled, not disabled. A
// browser takes keyboard focus from a button that becomes disabled, so a reader stepping to the
// last page with Next would be dropped at the top of the document; this way focus stays on the
// button pressed, which says it has nothing further to offer and ignores the press, as the media
// viewer's end stops do.

import { clsx } from 'clsx';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { notificationsPageItems } from '../../lib/notificationsPage';

const stepClass =
    'inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1 aria-disabled:cursor-not-allowed aria-disabled:opacity-40 aria-disabled:hover:bg-transparent aria-disabled:hover:text-text-2 max-md:min-h-11';

export function NotificationsPager({
    page,
    pageCount,
    onPageChange,
}: {
    page: number;
    pageCount: number;
    onPageChange: (page: number) => void;
}) {
    if (pageCount <= 1) {
        return null;
    }
    const items = notificationsPageItems(page, pageCount);

    return (
        <nav
            aria-label="Notification pages"
            data-notifications-pager=""
            className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2"
        >
            <p className="text-xs text-text-3">
                Page {page} of {pageCount}
            </p>
            <div className="flex flex-wrap items-center gap-1">
                <button
                    type="button"
                    data-notification-page="previous"
                    aria-disabled={page <= 1 || undefined}
                    onClick={() => {
                        if (page > 1) {
                            onPageChange(page - 1);
                        }
                    }}
                    className={stepClass}
                >
                    <ChevronLeft size={14} aria-hidden="true" />
                    Previous
                </button>
                {items.map((item, index) =>
                    item === null ? (
                        <span key={`gap-${index}`} aria-hidden="true" className="px-1 text-text-3">
                            …
                        </span>
                    ) : (
                        <button
                            key={item}
                            type="button"
                            data-notification-page={item}
                            aria-label={`Page ${item}`}
                            aria-current={item === page ? 'page' : undefined}
                            onClick={() => onPageChange(item)}
                            className={clsx(
                                'min-w-8 rounded-lg px-2 py-1.5 text-sm tabular-nums transition-colors max-md:min-h-11 max-md:min-w-11',
                                item === page
                                    ? 'bg-accent-soft font-semibold text-accent'
                                    : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                            )}
                        >
                            {item}
                        </button>
                    ),
                )}
                <button
                    type="button"
                    data-notification-page="next"
                    aria-disabled={page >= pageCount || undefined}
                    onClick={() => {
                        if (page < pageCount) {
                            onPageChange(page + 1);
                        }
                    }}
                    className={stepClass}
                >
                    Next
                    <ChevronRight size={14} aria-hidden="true" />
                </button>
            </div>
        </nav>
    );
}
