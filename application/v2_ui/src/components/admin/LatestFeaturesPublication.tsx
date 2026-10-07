// LatestFeaturesPublication.tsx
// Whether the user-facing announcements are reaching anyone right now.
//
// What decides that lives in another section: the Support menu has to be on, and so does
// its Latest Features destination. V1 hides this whole tab while either is off. V2 keeps the
// choices editable so they can be prepared before launch, which makes it essential to say
// plainly when nothing is published yet, and to offer the way to the switch that publishes
// it.

import { clsx } from 'clsx';
import { AlertCircle, ArrowRight, CheckCircle2 } from 'lucide-react';
import type { AdminField } from '../../lib/adminFields';

export const SUPPORT_MENU_SECTION_ID = 'support-menu-section';

export interface PublicationState {
    tone: 'ok' | 'warn';
    headline: string;
    detail: string;
    /** Whether the fix is in the Support section. */
    pointsToSupport: boolean;
}

/** Work out what an administrator needs to be told. Exported for direct testing. */
export function describePublication({
    menuOn,
    destinationOn,
    menuName,
    shared,
    total,
}: {
    menuOn: boolean;
    destinationOn: boolean;
    menuName: string;
    shared: number | null;
    total: number | null;
}): PublicationState {
    const menu = menuName.trim() || 'Support';
    if (!menuOn) {
        return {
            tone: 'warn',
            headline: 'Not published yet',
            detail:
                'The Support menu is off, so users cannot reach Latest Features. Choices made here are saved now and take effect once it is on.',
            pointsToSupport: true,
        };
    }
    if (!destinationOn) {
        return {
            tone: 'warn',
            headline: 'Not published yet',
            detail: `The Latest Features destination is off, so the ${menu} menu does not offer it. Choices made here are saved now and take effect once it is on.`,
            pointsToSupport: true,
        };
    }
    if (shared === 0) {
        return {
            tone: 'warn',
            headline: 'Published, but empty',
            detail: `No announcements are shared, so users do not see Latest Features in the ${menu} menu.`,
            pointsToSupport: false,
        };
    }
    return {
        tone: 'ok',
        headline: 'Published',
        detail:
            shared !== null && total !== null
                ? `Users see ${shared} of ${total} announcements under ${menu} › Latest Features.`
                : `Users reach Latest Features from the ${menu} menu.`,
        pointsToSupport: false,
    };
}

export function LatestFeaturesPublication({
    field,
    state,
    onNavigate,
}: {
    field: AdminField;
    state: PublicationState;
    onNavigate: (sectionId: string) => void;
}) {
    const Icon = state.tone === 'ok' ? CheckCircle2 : AlertCircle;

    return (
        <div className="admin-field py-3" data-field-width="wide">
            <div className="admin-field-heading text-sm font-semibold text-text-1">{field.label}</div>
            {field.help ? (
                <p className="admin-field-help text-[0.8125rem] leading-relaxed text-text-3">{field.help}</p>
            ) : null}
            <div className="admin-field-control min-w-0">
                <div
                    role="status"
                    data-testid="latest-features-publication"
                    className={clsx(
                        'flex items-start gap-2 rounded-lg border px-3 py-2 text-xs',
                        state.tone === 'ok'
                            ? 'border-ok/40 bg-ok/5 text-text-2'
                            : 'border-warn/40 bg-warn/5 text-text-2',
                    )}
                >
                    <Icon
                        size={14}
                        aria-hidden="true"
                        className={clsx('mt-px shrink-0', state.tone === 'ok' ? 'text-ok' : 'text-warn')}
                    />
                    <div className="min-w-0">
                        <p className="font-semibold text-text-1">{state.headline}</p>
                        <p className="mt-0.5 leading-relaxed">{state.detail}</p>
                        {state.pointsToSupport ? (
                            <button
                                type="button"
                                onClick={() => onNavigate(SUPPORT_MENU_SECTION_ID)}
                                className="mt-1.5 inline-flex items-center gap-1 rounded font-medium text-accent hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                            >
                                Open Support settings
                                <ArrowRight size={12} aria-hidden="true" />
                            </button>
                        ) : null}
                    </div>
                </div>
            </div>
        </div>
    );
}
