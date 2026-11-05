// ActionPopover.tsx
// A bounded action overlay; its host stays outside clipped page panes.

import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import { dropdownPlacement } from './dropdownPlacement';

export function ActionPopover({
    id, label, anchorRef, onClose, children, inline = false,
    placement = 'below', boundaryRef, className,
}: {
    id: string;
    label: string;
    anchorRef: RefObject<HTMLButtonElement>;
    onClose: (returnFocus: boolean) => void;
    children: ReactNode;
    inline?: boolean;
    placement?: 'below' | 'auto';
    boundaryRef?: RefObject<HTMLElement>;
    className?: string;
}) {
    const panelRef = useRef<HTMLDivElement>(null);
    const [position, setPosition] = useState<CSSProperties>({
        top: 0, left: 8, maxHeight: 320, width: placement === 'auto' ? undefined : 272,
    });

    useLayoutEffect(() => {
        if (inline) return;
        const measure = () => {
            const anchor = anchorRef.current;
            const panel = panelRef.current;
            if (!anchor || !panel) return false;
            const rect = anchor.getBoundingClientRect();
            if (placement === 'auto') {
                const visual = window.visualViewport;
                const viewport = {
                    left: visual?.offsetLeft ?? 0,
                    top: visual?.offsetTop ?? 0,
                    width: visual?.width ?? window.innerWidth,
                    height: visual?.height ?? window.innerHeight,
                };
                const boundary = boundaryRef?.current?.getBoundingClientRect();
                if (!anchor.isConnected || !anchor.getClientRects().length
                    || rect.bottom <= viewport.top || rect.top >= viewport.top + viewport.height
                    || rect.right <= viewport.left || rect.left >= viewport.left + viewport.width
                    || (boundary && (
                        rect.bottom <= boundary.top || rect.top >= boundary.bottom
                        || rect.right <= boundary.left || rect.left >= boundary.right
                    ))) {
                    onClose(false);
                    return false;
                }
                const margin = Math.min(12, viewport.width / 2, viewport.height / 2);
                const maxWidth = Math.max(0, viewport.width - margin * 2);
                const placed = dropdownPlacement(rect, viewport, 'right', {
                    width: Math.min(panel.getBoundingClientRect().width, maxWidth),
                    height: panel.scrollHeight + panel.offsetHeight - panel.clientHeight,
                });
                setPosition({
                    top: placed.top, left: placed.left, maxHeight: placed.maxHeight, maxWidth,
                    transform: placed.up ? 'translateY(-100%)' : undefined,
                });
                return true;
            }
            const width = Math.min(272, window.innerWidth - 16);
            const top = Math.min(rect.bottom + 8, window.innerHeight - 52);
            setPosition({
                top, width,
                left: Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8)),
                maxHeight: Math.max(44, window.innerHeight - top - 8),
            });
            return true;
        };
        if (!measure()) return;
        const first = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled), a[href]',
        ) ?? []).find((control) => control.getClientRects().length > 0);
        (first ?? panelRef.current)?.focus({ preventScroll: placement === 'auto' });
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
        const observer = placement === 'auto' ? new ResizeObserver(measure) : null;
        if (anchorRef.current) observer?.observe(anchorRef.current);
        if (panelRef.current) observer?.observe(panelRef.current);
        if (boundaryRef?.current) observer?.observe(boundaryRef.current);
        if (placement === 'auto') {
            window.visualViewport?.addEventListener('resize', measure);
            window.visualViewport?.addEventListener('scroll', measure);
        }
        return () => {
            document.removeEventListener('pointerdown', outside);
            document.removeEventListener('focusin', focusOutside);
            window.removeEventListener('resize', measure);
            window.removeEventListener('scroll', measure, true);
            observer?.disconnect();
            if (placement === 'auto') {
                window.visualViewport?.removeEventListener('resize', measure);
                window.visualViewport?.removeEventListener('scroll', measure);
            }
        };
    }, [anchorRef, onClose, inline, placement, boundaryRef]);

    if (inline) return <>{children}</>;
    return createPortal(
        <div ref={panelRef} id={id} role="group" aria-label={label} tabIndex={-1}
            style={position}
            className={clsx(
                'header-action-popover glass-modal fixed z-[100] overflow-y-auto rounded-xl p-1.5',
                className,
            )}
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
                    controls[next]?.focus({ preventScroll: placement === 'auto' });
                    if (placement === 'auto') controls[next]?.scrollIntoView({ block: 'nearest' });
                }
            }}>
            {children}
        </div>,
        document.body,
    );
}
