// LegacyUpgradeBanner.tsx
// The "update older documents" notice at the top of the documents explorer.
//
// Documents stored before progress tracking still list and open, but their metadata display and
// search results stay incomplete until they are updated. The classic interface offers the update
// in a dismissible alert, and this is the same offer: say what is old and what updating restores,
// then Update now or Maybe later. Maybe later hides the notice for this visit only, as classic's
// does, so nothing is remembered that could leave documents silently un-updated for good.
//
// It draws and reports. The explorer owns the request, because the update has to hold the
// explorer's own controls still while it runs and has to read the list again when it ends. A
// notice that cannot be acted on is never drawn, so the explorer shows it only to a viewer the
// server lets run the update.

import { forwardRef, useId } from 'react';
import { Info, Loader2 } from 'lucide-react';
import { legacyUpgradeCopy } from '../../lib/documentLegacyUpgrade';
import type { DocumentReadScope } from '../../lib/documentReadAdapter';
import { GlassButton } from '../ui/primitives';

export interface LegacyUpgradeBannerProps {
    scope: DocumentReadScope;
    /** An update is running: the button says so, and nothing else can be started. */
    busy: boolean;
    /** An earlier update ended with older documents still to do. */
    incomplete: boolean;
    onUpgrade: () => void;
    onDismiss: () => void;
}

export const LegacyUpgradeBanner = forwardRef<HTMLElement, LegacyUpgradeBannerProps>(
    function LegacyUpgradeBanner({ scope, busy, incomplete, onUpgrade, onDismiss }, ref) {
        const headingId = useId();
        const copy = legacyUpgradeCopy(scope);
        return (
            <section ref={ref} aria-labelledby={headingId} aria-busy={busy}
                className="shrink-0 rounded-xl border border-info/30 bg-info-soft px-3 py-2.5 text-sm text-text-1">
                <div className="flex items-start gap-2.5">
                    <Info size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-info" />
                    <div className="min-w-0 flex-1 space-y-1">
                        <h3 id={headingId} className="font-semibold">{copy.heading}</h3>
                        <p className="text-text-2">{copy.body}</p>
                        {incomplete && !busy ? (
                            <p role="status" className="text-text-2">
                                Some older documents still need updating. Choose Update now to try again.
                            </p>
                        ) : null}
                        {busy ? (
                            <p role="status" className="text-text-2">
                                Updating older documents. This can take a few moments.
                            </p>
                        ) : null}
                        <div className="flex flex-wrap items-center gap-2 pt-1">
                            <GlassButton type="button" size="sm" variant="primary" disabled={busy} onClick={onUpgrade}>
                                {busy ? <Loader2 size={14} aria-hidden="true" className="animate-spin" /> : null}
                                {busy ? 'Updating...' : 'Update now'}
                            </GlassButton>
                            <GlassButton type="button" size="sm" variant="subtle" disabled={busy} onClick={onDismiss}>
                                Maybe later
                            </GlassButton>
                        </div>
                    </div>
                </div>
            </section>
        );
    },
);
