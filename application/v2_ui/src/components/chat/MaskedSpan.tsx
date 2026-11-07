// MaskedSpan.tsx
// A redacted span inside a message, and the popup for masking a selection.

import { useEffect, useRef, useState } from 'react';
import { EyeOff, Loader2 } from 'lucide-react';
import { buildSelection, describeMask, type MaskedRange, type MaskSelection } from '../../lib/masking';

/** Roughly the popup's height; flipping on this is steadier than measuring after render. */
const POPUP_HEIGHT = 34;
/** Gap between the selection and the popup. */
const POPUP_GAP = 8;
/** Half the popup's width, used to keep it clear of the viewport edges. */
const POPUP_HALF_WIDTH = 90;
/** Breathing room kept against the viewport edge. */
const VIEWPORT_MARGIN = 8;

/**
 * Stands in for text that has been masked.
 *
 * The original text is never rendered, not even hidden behind CSS: the server has already
 * removed it from what the model sees, and putting it in the DOM would make the redaction
 * cosmetic. Only who applied it, and when, is shown.
 */
export function MaskedSpan({ range }: { range: MaskedRange | undefined }) {
    return (
        <span
            title={describeMask(range)}
            className="mx-0.5 inline-flex items-center gap-1 rounded bg-text-1/85 px-1.5 align-baseline text-[11px] font-medium text-surface-solid select-none"
        >
            <EyeOff size={10} />
            masked
        </span>
    );
}

/**
 * Floating control offered when text inside a message is selected.
 *
 * Anchored to the selection rather than the message so it appears where the user is looking,
 * and clamped to the viewport so a selection near an edge does not push it off-screen.
 */
export function MaskSelectionPopup({
    containerRef,
    onMask,
    disabled = false,
}: {
    containerRef: React.RefObject<HTMLElement | null>;
    onMask: (selection: MaskSelection) => Promise<void> | void;
    disabled?: boolean;
}) {
    const [selection, setSelection] = useState<MaskSelection | null>(null);
    const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null);
    const [busy, setBusy] = useState(false);
    const popupRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (disabled) {
            return;
        }

        const update = () => {
            // Clicking the popup itself changes the selection; ignoring that keeps the
            // control from disappearing on the way to being pressed.
            if (popupRef.current?.contains(document.activeElement)) {
                return;
            }

            const next = buildSelection(containerRef.current);
            if (!next) {
                setSelection(null);
                setAnchor(null);
                return;
            }

            const domSelection = window.getSelection();
            if (!domSelection || domSelection.rangeCount === 0) {
                return;
            }
            const rect = domSelection.getRangeAt(0).getBoundingClientRect();
            if (rect.width === 0 && rect.height === 0) {
                return;
            }

            // Above the selection by default, flipping below when there is no room there.
            // The result is then clamped: a control rendered off-screen cannot be clicked
            // at all, so position is computed outright rather than left to a transform.
            const above = rect.top - POPUP_GAP - POPUP_HEIGHT;
            const below = rect.bottom + POPUP_GAP;
            const preferred = above >= VIEWPORT_MARGIN ? above : below;
            const top = Math.max(
                VIEWPORT_MARGIN,
                Math.min(preferred, window.innerHeight - POPUP_HEIGHT - VIEWPORT_MARGIN),
            );

            setSelection(next);
            setAnchor({
                top,
                left: Math.min(
                    Math.max(rect.left + rect.width / 2, POPUP_HALF_WIDTH),
                    window.innerWidth - POPUP_HALF_WIDTH,
                ),
            });
        };

        // `selectionchange` fires continuously while dragging, so the control settles on
        // mouseup rather than flickering during the drag.
        document.addEventListener('mouseup', update);
        document.addEventListener('keyup', update);
        return () => {
            document.removeEventListener('mouseup', update);
            document.removeEventListener('keyup', update);
        };
    }, [containerRef, disabled]);

    if (disabled || !selection || !anchor) {
        return null;
    }

    return (
        <div
            ref={popupRef}
            style={{ top: anchor.top, left: anchor.left }}
            className="glass-modal fixed z-50 -translate-x-1/2 rounded-lg px-1 py-1"
        >
            <button
                type="button"
                disabled={busy}
                // Pointer-down rather than click: a click would first collapse the
                // selection, leaving nothing to mask.
                onMouseDown={(event) => {
                    event.preventDefault();
                    void (async () => {
                        setBusy(true);
                        try {
                            await onMask(selection);
                            window.getSelection()?.removeAllRanges();
                            setSelection(null);
                            setAnchor(null);
                        } finally {
                            setBusy(false);
                        }
                    })();
                }}
                className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-text-1 transition-colors hover:bg-surface-2 disabled:opacity-60"
            >
                {busy ? <Loader2 size={12} className="animate-spin" /> : <EyeOff size={12} />}
                Mask selection
            </button>
        </div>
    );
}
