// FilterPill.tsx
// Azure-portal-style filter pills: each pill shows its filter's current value and opens the
// editor for it. The popover is portalled and fixed-positioned so the page's scrolling
// containers never clip it, and it follows the incumbent picker pattern: outside click
// closes, Escape closes and returns focus to the pill.

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import { ChevronDown, X } from 'lucide-react';

const POPOVER_GAP = 6;
const VIEWPORT_MARGIN = 8;
const POPOVER_MAX_HEIGHT = 480;

export function AnchoredPopover({
    anchorRef,
    label,
    onClose,
    width = 320,
    align = 'left',
    children,
}: {
    anchorRef: RefObject<HTMLElement | null>;
    label: string;
    /** `restoreFocus` is true for Escape and explicit closes, false for outside clicks. */
    onClose: (restoreFocus: boolean) => void;
    width?: number;
    align?: 'left' | 'right';
    children: ReactNode;
}) {
    const panel = useRef<HTMLDivElement>(null);
    const [position, setPosition] = useState<{ top: number; left: number; maxHeight: number; width: number } | null>(null);
    const closeRef = useRef(onClose);
    closeRef.current = onClose;

    useLayoutEffect(() => {
        const measure = () => {
            const rect = anchorRef.current?.getBoundingClientRect();
            if (!rect) return;
            const panelWidth = Math.min(width, window.innerWidth - VIEWPORT_MARGIN * 2);
            const below = window.innerHeight - rect.bottom - VIEWPORT_MARGIN * 2;
            const above = rect.top - VIEWPORT_MARGIN * 2;
            const placeBelow = below >= Math.min(above, 280);
            const maxHeight = Math.max(160, Math.min(POPOVER_MAX_HEIGHT, placeBelow ? below : above));
            const left = align === 'right' ? rect.right - panelWidth : rect.left;
            setPosition({
                top: placeBelow ? rect.bottom + POPOVER_GAP : Math.max(VIEWPORT_MARGIN, rect.top - maxHeight - POPOVER_GAP),
                left: Math.max(VIEWPORT_MARGIN, Math.min(left, window.innerWidth - panelWidth - VIEWPORT_MARGIN)),
                maxHeight,
                width: panelWidth,
            });
        };
        measure();
        window.addEventListener('resize', measure);
        window.addEventListener('scroll', measure, true);
        return () => {
            window.removeEventListener('resize', measure);
            window.removeEventListener('scroll', measure, true);
        };
    }, [anchorRef, width, align]);

    useEffect(() => {
        const closeOutside = (event: PointerEvent) => {
            const target = event.target;
            if (target instanceof Node && !panel.current?.contains(target) && !anchorRef.current?.contains(target)) {
                closeRef.current(false);
            }
        };
        document.addEventListener('pointerdown', closeOutside);
        return () => document.removeEventListener('pointerdown', closeOutside);
    }, [anchorRef]);

    const positioned = position !== null;
    useEffect(() => {
        if (!positioned) return;
        const preferred = panel.current?.querySelector<HTMLElement>('[data-autofocus]');
        const first = panel.current?.querySelector<HTMLElement>(
            'input:not([disabled]), select:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        (preferred ?? first ?? panel.current)?.focus();
    }, [positioned]);

    return createPortal(
        <div
            ref={panel}
            role="dialog"
            aria-label={label}
            tabIndex={-1}
            style={position
                ? { top: position.top, left: position.left, maxHeight: position.maxHeight, width: position.width }
                : { visibility: 'hidden' }}
            className="glass-modal fixed z-[60] overflow-y-auto rounded-xl border border-edge p-3 shadow-xl outline-none"
            onKeyDown={(event) => {
                if (event.key === 'Escape') {
                    event.preventDefault();
                    event.stopPropagation();
                    closeRef.current(true);
                }
            }}
            onBlur={(event) => {
                // Tabbing past the last control leaves the popover; close it rather than
                // strand an open panel behind the focus.
                const next = event.relatedTarget;
                if (next instanceof Node && !panel.current?.contains(next) && !anchorRef.current?.contains(next)) {
                    closeRef.current(false);
                }
            }}
        >
            {children}
        </div>,
        document.body,
    );
}

/** Open state for a trigger and its popover, with focus returned to the trigger on close. */
export function usePopover(defaultOpen = false, onOpenChange?: (open: boolean, restoreFocus: boolean) => void) {
    const [open, setOpen] = useState(defaultOpen);
    const triggerRef = useRef<HTMLButtonElement | null>(null);
    const anchorRef = useRef<HTMLDivElement>(null);
    const change = (next: boolean, restoreFocus = false) => {
        setOpen(next);
        onOpenChange?.(next, restoreFocus);
    };
    return {
        open,
        triggerRef,
        anchorRef,
        // Closing from the trigger itself counts as a deliberate close, like Escape.
        toggle: () => change(!open, open),
        /** `restoreFocus` is false when the user clicked elsewhere, so focus stays where they clicked. */
        close: (restoreFocus = true) => {
            change(false, restoreFocus);
            if (restoreFocus) requestAnimationFrame(() => triggerRef.current?.focus());
        },
    };
}

export function FilterPill({
    label,
    value,
    active,
    onClear,
    clearLabel,
    focusAfterClear,
    popoverLabel,
    pillId,
    width,
    defaultOpen = false,
    onOpenChange,
    children,
}: {
    label: string;
    value: string;
    active: boolean;
    onClear?: () => void;
    clearLabel?: string;
    /**
     * Where keyboard focus goes when the clear button removes itself. Defaults to the pill;
     * a pill that disappears once cleared must send focus somewhere that stays.
     */
    focusAfterClear?: () => void;
    popoverLabel: string;
    /** A stable hook, so a filter set elsewhere on the page can move focus to its pill. */
    pillId?: string;
    width?: number;
    defaultOpen?: boolean;
    onOpenChange?: (open: boolean, restoreFocus: boolean) => void;
    children: (close: () => void) => ReactNode;
}) {
    const popover = usePopover(defaultOpen, onOpenChange);
    const clearText = clearLabel ?? `Clear ${label.toLowerCase()} filter`;
    return (
        <>
            <div
                ref={popover.anchorRef}
                className={clsx(
                    'inline-flex h-8 max-w-full items-stretch rounded-full border text-xs transition-colors',
                    active ? 'border-accent/40 bg-accent-soft text-accent' : 'border-edge bg-surface-1 text-text-2',
                )}
            >
                <button
                    ref={popover.triggerRef}
                    type="button"
                    data-filter-pill={pillId}
                    aria-haspopup="dialog"
                    aria-expanded={popover.open}
                    onClick={popover.toggle}
                    className={clsx(
                        'inline-flex min-w-0 items-center gap-1 rounded-full pl-3 transition-colors',
                        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
                        active ? 'hover:bg-accent/10' : 'hover:bg-surface-2 hover:text-text-1',
                        active && onClear ? 'pr-1.5' : 'pr-2.5',
                    )}
                >
                    <span className={active ? 'text-accent/80' : 'text-text-3'}>{label}:</span>{' '}
                    <span className="min-w-0 max-w-52 truncate font-medium">{value}</span>
                    <ChevronDown size={13} aria-hidden="true" className="shrink-0" />
                </button>
                {active && onClear ? (
                    <button
                        type="button"
                        aria-label={clearText}
                        title={clearText}
                        onClick={() => {
                            // The clear button unmounts with the filter, so focus moves first.
                            if (focusAfterClear) focusAfterClear();
                            else popover.triggerRef.current?.focus();
                            onClear();
                        }}
                        className="mr-1 inline-flex w-6 shrink-0 items-center justify-center self-center rounded-full py-1 hover:bg-accent/15 focus-visible:outline-2 focus-visible:outline-accent"
                    >
                        <X size={12} aria-hidden="true" />
                    </button>
                ) : null}
            </div>
            {popover.open ? (
                <AnchoredPopover anchorRef={popover.anchorRef} label={popoverLabel} width={width}
                    onClose={(restoreFocus) => popover.close(restoreFocus)}>
                    {children(() => popover.close(true))}
                </AnchoredPopover>
            ) : null}
        </>
    );
}
