// MessageActionSheet.tsx
// A message's actions as a bottom sheet, opened by pressing and holding the message on a
// touch screen.
//
// The hover-revealed action row never appears on a touch screen, because nothing hovers. The
// sheet shows the same MessageActions -- same entries, same handlers -- laid out for a finger:
// labelled tiles for the quick actions and the overflow menu's entries as a list beneath them.
// Choosing anything closes the sheet; a tap on the backdrop, Escape, or a downward swipe on
// the sheet closes it without doing anything.

import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

/** How far the sheet has to be dragged down before letting go closes it. */
const SWIPE_CLOSE_PX = 80;

/** How long after opening a backdrop click is taken to be the opening press's own lift. */
const LIFT_GRACE_MS = 600;

export function MessageActionSheet({
    onClose,
    children,
}: {
    onClose: () => void;
    children: ReactNode;
}) {
    const panelRef = useRef<HTMLDivElement>(null);
    const dragStart = useRef<number | null>(null);
    // The finger that held the message lifts after the sheet is up, and some browsers send
    // that lift as a click on whatever is under it -- the backdrop. It must not close the sheet.
    const openedAt = useRef(Date.now());

    useEffect(() => {
        const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        panelRef.current?.focus({ preventScroll: true });
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') onClose();
        };
        window.addEventListener('keydown', onKeyDown);
        return () => {
            window.removeEventListener('keydown', onKeyDown);
            if (opener?.isConnected) opener.focus({ preventScroll: true });
        };
    }, [onClose]);

    const setDrag = (offset: number) => {
        const panel = panelRef.current;
        if (panel) panel.style.transform = offset > 0 ? `translateY(${offset}px)` : '';
    };

    return createPortal(
        <div
            className="fixed inset-0 z-50 flex items-end bg-black/40"
            onClick={() => {
                if (Date.now() - openedAt.current > LIFT_GRACE_MS) onClose();
            }}
            data-message-action-sheet=""
        >
            <div
                ref={panelRef}
                role="dialog"
                aria-modal="true"
                aria-label="Message actions"
                tabIndex={-1}
                onClick={(event) => event.stopPropagation()}
                onTouchStart={(event) => {
                    // Only a drag that starts with the list scrolled to the top is a dismiss;
                    // otherwise it is scrolling the list. A dialog the sheet opened (Save as
                    // prompt) is portaled elsewhere but still bubbles here, and is not the sheet.
                    const onSheet = event.currentTarget.contains(event.target as Node);
                    dragStart.current = !onSheet || event.currentTarget.scrollTop > 0
                        ? null
                        : event.touches[0].clientY;
                }}
                onTouchMove={(event) => {
                    if (dragStart.current !== null) setDrag(event.touches[0].clientY - dragStart.current);
                }}
                onTouchEnd={(event) => {
                    if (dragStart.current === null) return;
                    const offset = event.changedTouches[0].clientY - dragStart.current;
                    dragStart.current = null;
                    setDrag(0);
                    if (offset > SWIPE_CLOSE_PX) onClose();
                }}
                className="glass-modal max-h-[80dvh] w-full overflow-y-auto rounded-t-2xl px-3 pt-2 pb-[max(0.75rem,env(safe-area-inset-bottom))] outline-none transition-transform"
            >
                <div aria-hidden="true" className="mx-auto mb-2 h-1 w-10 rounded-full bg-text-3/40" />
                {children}
            </div>
        </div>,
        document.body,
    );
}
