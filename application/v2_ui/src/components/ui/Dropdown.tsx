// Dropdown.tsx
// Accessible popover menu used by the chat toolbar pickers.

import { useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import { Check, ChevronDown } from 'lucide-react';
import { DropdownScopeContext } from './DropdownScope';
import { dropdownPlacement } from './dropdownPlacement';

/** Tallest the menu is allowed to get, matching the max-h-80 ceiling. */
const MENU_MAX_HEIGHT = 320;
/** Gap between the trigger and the menu, matching the mt-2 / mb-2 spacing. */
const MENU_GAP = 8;
/** Breathing room kept between the menu and the viewport edge. */
const VIEWPORT_MARGIN = 12;
/** Below this a flipped menu is more awkward than a scrolling one. */
const MIN_USABLE_HEIGHT = 140;

export interface DropdownOption {
    value: string;
    label: string;
    description?: string;
    group?: string;
}

interface DropdownProps {
    options: DropdownOption[];
    value?: string;
    placeholder: string;
    onChange: (value: string | undefined) => void;
    icon?: React.ReactNode;
    /** Allows the current selection to be cleared from within the menu. */
    clearable?: boolean;
    disabled?: boolean;
    /**
     * The selection is retained but currently overridden by something else, so the trigger
     * shows the placeholder in its muted styling.
     *
     * Deliberately distinct from `disabled`: the control stays usable, because choosing a
     * value is how the user takes the override back off. The menu still marks the retained
     * value, so it is visible what returns.
     */
    inactive?: boolean;
    /** Tooltip for the trigger. Explains an `inactive` state, where one is not obvious. */
    title?: string;
    align?: 'left' | 'right';
    /** Renders the trigger as an icon-sized button with the label as a tooltip. */
    compact?: boolean;
    /** Optional picker-specific guidance, outside the listbox options. */
    hint?: React.ReactNode;
    /** Escape a scrolling composer ancestor without changing other dropdown surfaces. */
    floating?: boolean;
}

export function Dropdown({
    options,
    value,
    placeholder,
    onChange,
    icon,
    clearable = false,
    disabled = false,
    inactive = false,
    title,
    align = 'left',
    compact = false,
    hint,
    floating = false,
}: DropdownProps) {
    const [localOpen, setLocalOpen] = useState(false);
    const scope = useContext(DropdownScopeContext);
    const scopeSetter = scope?.setActiveId;
    const boundary = scope?.boundary;
    const id = useId();
    const open = !disabled && (floating && scope
        ? scope.enabled && scope.activeId === id : localOpen);
    const setOpen = useCallback((next: boolean) => {
        if (floating && scopeSetter) {
            scopeSetter((current) => next ? id : current === id ? null : current);
        } else {
            setLocalOpen(next);
        }
    }, [floating, scopeSetter, id]);
    // These pickers sit in the composer at the bottom of the viewport, where a menu that
    // always drops downward runs off the bottom of the window. Placement is measured on
    // open rather than fixed, so the same component works wherever it is used.
    const [placement, setPlacement] = useState<'down' | 'up'>('down');
    const [maxHeight, setMaxHeight] = useState(MENU_MAX_HEIGHT);
    const containerRef = useRef<HTMLDivElement>(null);
    const triggerRef = useRef<HTMLButtonElement>(null);
    const panelRef = useRef<HTMLDivElement>(null);
    const [position, setPosition] = useState<ReturnType<typeof dropdownPlacement> | null>(null);

    const selected = options.find((option) => option.value === value);
    // What the trigger reads as. An overridden selection is still `selected` for the menu's
    // check mark, but the trigger falls back to the placeholder so the row does not claim a
    // choice that is not in force.
    const triggerLabel = inactive ? placeholder : (selected?.label ?? placeholder);

    const measure = useCallback(() => {
        const element = triggerRef.current;
        if (!element) {
            return;
        }

        const rect = element.getBoundingClientRect();
        if (floating) {
            const viewport = window.visualViewport;
            const visibleBounds = boundary?.current?.getBoundingClientRect();
            if (!element.isConnected || !element.getClientRects().length || (visibleBounds && (
                rect.bottom <= visibleBounds.top || rect.top >= visibleBounds.bottom
                || rect.right <= visibleBounds.left || rect.left >= visibleBounds.right
            ))) {
                setOpen(false);
                return;
            }
            setPosition(dropdownPlacement(rect, {
                left: viewport?.offsetLeft ?? 0,
                top: viewport?.offsetTop ?? 0,
                width: viewport?.width ?? window.innerWidth,
                height: viewport?.height ?? window.innerHeight,
            }, align));
            return;
        }
        const spaceBelow = window.innerHeight - rect.bottom - MENU_GAP - VIEWPORT_MARGIN;
        const spaceAbove = rect.top - MENU_GAP - VIEWPORT_MARGIN;

        if (spaceBelow >= MENU_MAX_HEIGHT || spaceBelow >= spaceAbove) {
            setPlacement('down');
            setMaxHeight(Math.max(MIN_USABLE_HEIGHT, Math.min(MENU_MAX_HEIGHT, spaceBelow)));
            return;
        }

        setPlacement('up');
        setMaxHeight(Math.max(MIN_USABLE_HEIGHT, Math.min(MENU_MAX_HEIGHT, spaceAbove)));
    }, [floating, align, setOpen, boundary]);

    useEffect(() => {
        if (disabled) {
            setLocalOpen(false);
            if (scope?.activeId === id) scope.setActiveId(null);
        }
    }, [disabled, scope, id]);

    useEffect(() => () => {
        // Do not close a replacement picker during the old trigger's cleanup.
        if (floating && scopeSetter) {
            scopeSetter((current) => current === id ? null : current);
        }
    }, [floating, scopeSetter, id]);

    useLayoutEffect(() => {
        if (!open || !floating) return;
        measure();
        const panel = panelRef.current;
        const initial = panel?.querySelector<HTMLElement>('[role="option"][aria-selected="true"]')
            ?? panel?.querySelector<HTMLElement>('[role="option"], button');
        (initial ?? panel)?.focus({ preventScroll: true });
        initial?.scrollIntoView({ block: 'nearest' });
    }, [open, floating, measure]);

    useEffect(() => {
        if (!open) {
            return;
        }

        const onPointerDown = (event: PointerEvent) => {
            if (!containerRef.current?.contains(event.target as Node)
                && !panelRef.current?.contains(event.target as Node)) {
                setOpen(false);
            }
        };
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                setOpen(false);
                triggerRef.current?.focus({ preventScroll: true });
            }
        };
        const onFocus = (event: FocusEvent) => {
            if (floating && !containerRef.current?.contains(event.target as Node)
                && !panelRef.current?.contains(event.target as Node)) setOpen(false);
        };

        document.addEventListener('pointerdown', onPointerDown);
        document.addEventListener('keydown', onKeyDown);
        document.addEventListener('focusin', onFocus);
        window.addEventListener('resize', measure);
        // Capture, so the menu keeps up with any scrolling ancestor and not just the page.
        window.addEventListener('scroll', measure, true);
        window.visualViewport?.addEventListener('resize', measure);
        window.visualViewport?.addEventListener('scroll', measure);
        const observer = floating ? new ResizeObserver(measure) : null;
        if (triggerRef.current) observer?.observe(triggerRef.current);
        return () => {
            document.removeEventListener('pointerdown', onPointerDown);
            document.removeEventListener('keydown', onKeyDown);
            document.removeEventListener('focusin', onFocus);
            window.removeEventListener('resize', measure);
            window.removeEventListener('scroll', measure, true);
            window.visualViewport?.removeEventListener('resize', measure);
            window.visualViewport?.removeEventListener('scroll', measure);
            observer?.disconnect();
        };
    }, [open, measure, floating, setOpen]);

    // Options arrive pre-grouped by scope (personal / group / public), so headings are
    // emitted whenever the group changes rather than by re-sorting the list.
    let lastGroup: string | undefined;

    const menu = open && (
        <div
            ref={panelRef}
            tabIndex={floating ? -1 : undefined}
            style={floating ? {
                left: position?.left, top: position?.top, width: position?.width,
                maxHeight: position?.maxHeight ?? 0,
                transform: position?.up ? 'translateY(-100%)' : undefined,
            } : { maxHeight }}
            className={clsx(
                'glass-modal flex flex-col rounded-2xl p-1.5',
                floating ? 'composer-picker-panel fixed z-40 overflow-y-auto' : [
                    'absolute z-50 w-72',
                    placement === 'up' ? 'bottom-full mb-2' : 'top-full mt-2',
                    align === 'right' ? 'right-0' : 'left-0',
                ],
            )}
            onKeyDown={(event) => {
                if (!floating) return;
                const buttons = Array.from(panelRef.current?.querySelectorAll<HTMLButtonElement>('button') ?? []);
                const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
                let next: number | undefined;
                if (event.key === 'ArrowDown') next = (index + 1) % buttons.length;
                if (event.key === 'ArrowUp') next = (index - 1 + buttons.length) % buttons.length;
                if (event.key === 'Home') next = 0;
                if (event.key === 'End') next = buttons.length - 1;
                if (next !== undefined && buttons.length) {
                    event.preventDefault();
                    buttons[next].focus({ preventScroll: true });
                    buttons[next].scrollIntoView({ block: 'nearest' });
                }
                if (event.key === 'Tab') {
                    setOpen(false);
                    triggerRef.current?.focus({ preventScroll: true });
                }
            }}
        >
            {clearable && value !== undefined && (
                <button
                    type="button"
                    onClick={() => {
                        onChange(undefined);
                        setOpen(false);
                        if (floating) triggerRef.current?.focus({ preventScroll: true });
                    }}
                    className="w-full shrink-0 rounded-lg px-3 py-2 text-left text-sm text-text-3 hover:bg-surface-2"
                >
                    Clear selection
                </button>
            )}

            <div id={`${id}-options`} role="listbox" aria-label={`${placeholder} options`}
                className={floating ? 'shrink-0' : 'min-h-0 overflow-y-auto'}>
                {options.length === 0 && (
                    <p className="px-3 py-6 text-center text-sm text-text-3">
                        Nothing available
                    </p>
                )}

                {options.map((option) => {
                    const showGroupHeading = option.group && option.group !== lastGroup;
                    lastGroup = option.group;
                    const isSelected = option.value === value;

                    return (
                        <div key={option.value}>
                            {showGroupHeading && (
                                <p className="px-3 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                                    {option.group}
                                </p>
                            )}
                            <button
                                type="button"
                                role="option"
                                aria-selected={isSelected}
                                onClick={() => {
                                    onChange(option.value);
                                    setOpen(false);
                                    if (floating) triggerRef.current?.focus({ preventScroll: true });
                                }}
                                className={clsx(
                                    'flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left',
                                    isSelected ? 'bg-accent-soft' : 'hover:bg-surface-2',
                                )}
                            >
                                <span className="min-w-0 flex-1">
                                    <span className="block truncate text-sm text-text-1">
                                        {option.label}
                                    </span>
                                    {option.description && (
                                        <span className="mt-0.5 block line-clamp-2 text-xs text-text-3">
                                            {option.description}
                                        </span>
                                    )}
                                </span>
                                {isSelected && (
                                    <Check size={15} className="mt-0.5 shrink-0 text-accent" />
                                )}
                            </button>
                        </div>
                    );
                })}
            </div>
            {hint && (
                <div className="mt-1 shrink-0 border-t border-edge px-3 py-2 text-[11px] text-text-3">
                    {hint}
                </div>
            )}
        </div>
    );

    return (
        <div className="relative" ref={containerRef}>
            <button
                ref={triggerRef}
                type="button"
                disabled={disabled}
                onClick={() => {
                    if (!open) measure();
                    setOpen(!open);
                }}
                onKeyDown={(event) => {
                    if (floating && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
                        event.preventDefault();
                        measure();
                        setOpen(true);
                    }
                }}
                aria-haspopup="listbox"
                aria-controls={open ? `${id}-options` : undefined}
                aria-expanded={open}
                title={title ?? (compact ? (selected?.label ?? placeholder) : undefined)}
                className={clsx(
                    'inline-flex h-9 items-center gap-2 rounded-xl border border-edge',
                    'bg-surface-1 text-sm font-medium transition-colors',
                    'hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50',
                    compact ? 'w-9 justify-center' : 'max-w-[14rem] px-3',
                    selected && !inactive ? 'text-text-1' : 'text-text-3',
                    inactive && 'opacity-70',
                )}
            >
                {icon}
                {!compact && (
                    <>
                        <span className="truncate">{triggerLabel}</span>
                        <ChevronDown size={14} className="ml-auto shrink-0 opacity-60" />
                    </>
                )}
            </button>
            {floating ? createPortal(menu, document.body) : menu}
        </div>
    );
}
