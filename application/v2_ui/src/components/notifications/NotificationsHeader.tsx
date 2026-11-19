// NotificationsHeader.tsx
// The Notifications page's header: the bar every page header draws, with its two actions kept
// focusable while they work.
//
// The shared header turns an action into a native `disabled` button while it is busy or has
// nothing to do, and a browser takes keyboard focus from a button that becomes disabled and
// leaves it on the page. A reader who pressed Refresh or Mark all read from the keyboard was
// therefore dropped at the top of the document. Here the same actions say they are unavailable
// with aria-disabled instead, and a press while they are unavailable does nothing, as the Control
// Center's Refresh data button does. The markup, classes, names and test ids are those of
// PageHeader and HeaderActions, so the bar looks and lays out as every other, at phone width too.

import { Loader2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { MobileNavigation } from '../layout/MobileNavigation';
import type { HeaderAction } from '../layout/HeaderActions';

/** The shared header's `disabled` and `loading` become aria-disabled, and a press does nothing. */
function NotificationsHeaderAction({ action }: { action: HeaderAction }) {
    const unavailable = Boolean(action.disabled || action.loading);
    return (
        <GlassButton
            type="button"
            size="sm"
            variant={action.variant}
            aria-disabled={unavailable || undefined}
            aria-busy={action.loading || undefined}
            aria-label={action.label}
            title={action.label}
            data-testid={action.testId}
            onClick={() => {
                if (!unavailable) {
                    action.onClick();
                }
            }}
            className="header-action shrink-0 aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
        >
            <span aria-hidden="true" className="flex shrink-0 items-center">
                {action.loading ? (
                    <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
                ) : (
                    action.icon
                )}
            </span>
            <span className="header-action-label">{action.label}</span>
        </GlassButton>
    );
}

export function NotificationsHeader({
    title,
    description,
    actions,
}: {
    title: string;
    description: string;
    actions: readonly HeaderAction[];
}) {
    return (
        <header className="page-header glass glass-edge flex min-h-14 shrink-0 items-center gap-2 rounded-none border-t-0 border-r-0 px-2 py-2 md:flex-wrap md:gap-4 md:px-5 md:py-3">
            <MobileNavigation />
            <div className="min-w-0 flex-1">
                <h1 className="truncate text-[15px] font-semibold text-text-1">{title}</h1>
                <p className="mt-0.5 truncate text-xs text-text-3">{description}</p>
            </div>
            <div className="page-header-actions ml-auto flex max-w-full shrink-0 items-center gap-2 md:flex-wrap">
                {actions.map((action) => (
                    <NotificationsHeaderAction key={action.id} action={action} />
                ))}
            </div>
        </header>
    );
}
