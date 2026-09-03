// LargeRunDialog.tsx
// The confirmation shown before a prompt starts a long row-level export.
//
// Offers "Narrow scope" as the primary way out rather than a bare Cancel, because the useful
// response to this notice is usually to edit the prompt, not to abandon the request. Closing
// it any other way — backdrop, Escape, the X — means the same thing, so the composer keeps
// what was typed and nothing is sent.

import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { TriangleAlert, X } from 'lucide-react';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { describeLargeTabularRun, type TabularRunEstimate } from '../../lib/tabularRunEstimate';

export function LargeRunDialog({
    estimate,
    onContinue,
    onCancel,
}: {
    estimate: TabularRunEstimate;
    onContinue: () => void;
    onCancel: () => void;
}) {
    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onCancel();
            }
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [onCancel]);

    return createPortal(
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-labelledby="large-run-dialog-title"
        >
            <div className="absolute inset-0 bg-black/40" aria-hidden="true" onClick={onCancel} />

            <GlassPanel elevation="modal" edge className="relative w-full max-w-md">
                <div className="flex h-14 items-center gap-3 border-b border-edge px-5">
                    <TriangleAlert size={16} className="shrink-0 text-warn" />
                    <h2
                        id="large-run-dialog-title"
                        className="flex-1 text-[15px] font-semibold text-text-1"
                    >
                        Large tabular run
                    </h2>
                    <GlassButton size="icon" variant="ghost" aria-label="Close" onClick={onCancel}>
                        <X size={16} />
                    </GlassButton>
                </div>

                <div className="space-y-2 px-5 py-4">
                    <p className="text-sm text-text-1">{describeLargeTabularRun(estimate)}</p>
                    <p className="text-sm text-text-3">
                        Large row-level runs are checkpointed in the background. Continue to
                        start the run, or narrow the prompt before sending.
                    </p>
                </div>

                <div className="flex justify-end gap-2 border-t border-edge px-5 py-3">
                    <GlassButton size="sm" variant="subtle" onClick={onCancel}>
                        Narrow scope
                    </GlassButton>
                    <GlassButton size="sm" variant="primary" onClick={onContinue}>
                        Continue run
                    </GlassButton>
                </div>
            </GlassPanel>
        </div>,
        // Portalled for the same reason as the other chat dialogs: the composer sits inside a
        // transformed container, where `fixed` would resolve against it rather than the
        // viewport.
        document.body,
    );
}
