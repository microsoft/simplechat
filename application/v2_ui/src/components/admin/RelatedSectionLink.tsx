// RelatedSectionLink.tsx
// Points from a setting to the section where its effect shows up.
//
// Some settings act somewhere else entirely: the Document Access Index diagnostics switch
// lives with Debug Logging but changes what Scale > Cosmos > DAI Metrics draws. Saying where,
// with a way to get there, saves an administrator from flipping a switch and then hunting
// for what changed. The server-rendered page addresses a tab rather than a section, so a
// link there opens the tab that holds it.

import { ArrowRight, ArrowUpRight } from 'lucide-react';

export function RelatedSectionLink({
    label,
    location,
    onNavigate,
}: {
    label: string;
    /** Where the section sits in the navigation, or null when it is not in it. */
    location: { groupLabel: string; tabId: string; tabLabel: string; sectionLabel: string } | null;
    /** Present when the section is shown on this page; otherwise the classic page is linked. */
    onNavigate?: () => void;
}) {
    if (!location) {
        return null;
    }

    return (
        <p className="text-xs leading-relaxed text-text-3">
            Shown in {location.groupLabel} &rsaquo; {location.tabLabel} &rsaquo; {location.sectionLabel}.{' '}
            {onNavigate ? (
                <button
                    type="button"
                    onClick={onNavigate}
                    className="inline-flex items-center gap-1 font-medium text-accent hover:underline"
                >
                    Go to {label}
                    <ArrowRight size={12} aria-hidden="true" />
                </button>
            ) : (
                <a
                    href={`/admin/settings#${encodeURIComponent(location.tabId)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 font-medium text-accent hover:underline"
                >
                    Open {label} on the classic admin page
                    <ArrowUpRight size={12} aria-hidden="true" />
                    <span className="sr-only">(opens in a new tab)</span>
                </a>
            )}
        </p>
    );
}
