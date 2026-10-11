// ActionPopover.tsx
// A bounded overlay for header actions; its host stays outside clipped page panes.

import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';

export function ActionPopover({
    id, label, anchorRef, onClose, children, inline = false,
}: {
    id: string;
    label: string;
    anchorRef: RefObject<HTMLButtonElement>;
    onClose: (returnFocus: boolean) => void;
    children: ReactNode;
    inline?: boolean;
}) {
    const panelRef = useRef<HTMLDivElement>(null);
    const [position, setPosition] = useState({ top: 0, left: 8, maxHeight: 320, width: 272 });

    useLayoutEffect(() => {
        if (inline) return;
        const measure = () => {
            const anchor = anchorRef.current;
            if (!anchor) return;
            const rect = anchor.getBoundingClientRect();
            const width = Math.min(272, window.innerWidth - 16);
            const top = Math.min(rect.bottom + 8, window.innerHeight - 52);
            setPosition({
                top, width,
                left: Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8)),
                maxHeight: Math.max(44, window.innerHeight - top - 8),
            });
        };
        measure();
        const first = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled), a[href]',
        ) ?? []).find((control) => control.getClientRects().length > 0);
        (first ?? panelRef.current)?.focus();
        const outside = (event: PointerEvent) => {
            if (event.target instanceof Node &&
                !panelRef.current?.contains(event.target) && !anchorRef.current?.contains(event.target)) {
                onClose(false);
            }
        };
        const focusOutside = (event: FocusEvent) => {
            if (event.target instanceof Node &&
                !panelRef.current?.contains(event.target) && !anchorRef.current?.contains(event.target)) {
                onClose(false);
            }
        };
        document.addEventListener('pointerdown', outside);
        document.addEventListener('focusin', focusOutside);
        window.addEventListener('resize', measure);
        window.addEventListener('scroll', measure, true);
        return () => {
            document.removeEventListener('pointerdown', outside);
            document.removeEventListener('focusin', focusOutside);
            window.removeEventListener('resize', measure);
            window.removeEventListener('scroll', measure, true);
        };
    }, [anchorRef, onClose, inline]);

    if (inline) return <>{children}</>;
    return createPortal(
        <div ref={panelRef} id={id} role="group" aria-label={label} tabIndex={-1}
            style={position}
            className="header-action-popover glass-modal fixed z-[100] overflow-y-auto rounded-xl p-1.5"
            onKeyDown={(event) => {
                if (event.key === 'Escape') {
                    event.preventDefault();
                    event.stopPropagation();
                    onClose(true);
                }
                if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Tab'].includes(event.key)) {
                    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
                        'button:not(:disabled), a[href]',
                    )).filter((control) => control.getClientRects().length > 0);
                    const current = controls.indexOf(document.activeElement as HTMLElement);
                    if (event.key === 'Tab') {
                        if ((event.shiftKey && current === 0) || (!event.shiftKey && current === controls.length - 1)) {
                            event.preventDefault();
                            onClose(true);
                        }
                        return;
                    }
                    const next = event.key === 'Home' ? 0 : event.key === 'End' ? controls.length - 1
                        : (current + (event.key === 'ArrowDown' ? 1 : -1) + controls.length) % controls.length;
                    event.preventDefault();
                    controls[next]?.focus();
                }
            }}>
            {children}
        </div>,
        document.body,
    );
}
