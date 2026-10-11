// PageHeader.tsx
// Shared header for the non-chat content pages.

import type { ReactNode } from 'react';
import { MobileNavigation } from './MobileNavigation';

export function PageHeader({
    title,
    description,
    actions,
    leading,
}: {
    title: string;
    description?: string;
    actions?: ReactNode;
    /** Rendered before the title block, for a page identified by more than its name. */
    leading?: ReactNode;
}) {
    return (
        <header className="page-header glass glass-edge flex min-h-14 shrink-0 flex-wrap items-center gap-2 rounded-none border-t-0 border-r-0 px-2 py-2 md:gap-4 md:px-5 md:py-3">
            <MobileNavigation />
            {leading && <div className="flex shrink-0 items-center">{leading}</div>}
            <div className="min-w-0 flex-1">
                <h1 className="truncate text-[15px] font-semibold text-text-1">{title}</h1>
                {description && (
                    <p className="mt-0.5 truncate text-xs text-text-3">{description}</p>
                )}
            </div>
            {actions && <div className="page-header-actions ml-auto flex max-w-full flex-wrap items-center gap-2">{actions}</div>}
        </header>
    );
}
