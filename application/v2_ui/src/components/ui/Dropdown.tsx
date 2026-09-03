// Dropdown.tsx
// Accessible popover menu used by the chat toolbar pickers.

import { useCallback, useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Check, ChevronDown } from 'lucide-react';

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
}: DropdownProps) {
    const [open, setOpen] = useState(false);
    // These pickers sit in the composer at the bottom of the viewport, where a menu that
    // always drops downward runs off the bottom of the window. Placement is measured on
    // open rather than fixed, so the same component works wherever it is used.
    const [placement, setPlacement] = useState<'down' | 'up'>('down');
    const [maxHeight, setMaxHeight] = useState(MENU_MAX_HEIGHT);
    const containerRef = useRef<HTMLDivElement>(null);

    const selected = options.find((option) => option.value === value);
    // What the trigger reads as. An overridden selection is still `selected` for the menu's
    // check mark, but the trigger falls back to the placeholder so the row does not claim a
    // choice that is not in force.
    const triggerLabel = inactive ? placeholder : (selected?.label ?? placeholder);

    const measure = useCallback(() => {
        const element = containerRef.current;
        if (!element) {
            return;
        }

        const rect = element.getBoundingClientRect();
        const spaceBelow = window.innerHeight - rect.bottom - MENU_GAP - VIEWPORT_MARGIN;
        const spaceAbove = rect.top - MENU_GAP - VIEWPORT_MARGIN;

        if (spaceBelow >= MENU_MAX_HEIGHT || spaceBelow >= spaceAbove) {
            setPlacement('down');
            setMaxHeight(Math.max(MIN_USABLE_HEIGHT, Math.min(MENU_MAX_HEIGHT, spaceBelow)));
            return;
        }

        setPlacement('up');
        setMaxHeight(Math.max(MIN_USABLE_HEIGHT, Math.min(MENU_MAX_HEIGHT, spaceAbove)));
    }, []);

    useEffect(() => {
        if (!open) {
            return;
        }

        const onPointerDown = (event: MouseEvent) => {
            if (!containerRef.current?.contains(event.target as Node)) {
                setOpen(false);
            }
        };
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setOpen(false);
            }
        };

        document.addEventListener('mousedown', onPointerDown);
        document.addEventListener('keydown', onKeyDown);
        window.addEventListener('resize', measure);
        // Capture, so the menu keeps up with any scrolling ancestor and not just the page.
        window.addEventListener('scroll', measure, true);
        return () => {
            document.removeEventListener('mousedown', onPointerDown);
            document.removeEventListener('keydown', onKeyDown);
            window.removeEventListener('resize', measure);
            window.removeEventListener('scroll', measure, true);
        };
    }, [open, measure]);

    // Options arrive pre-grouped by scope (personal / group / public), so headings are
    // emitted whenever the group changes rather than by re-sorting the list.
    let lastGroup: string | undefined;

    return (
        <div className="relative" ref={containerRef}>
            <button
                type="button"
                disabled={disabled}
                onClick={() => {
                    if (!open) {
                        measure();
                    }
                    setOpen((isOpen) => !isOpen);
                }}
                aria-haspopup="listbox"
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

            {open && (
                <div
                    role="listbox"
                    style={{ maxHeight }}
                    className={clsx(
                        'glass-modal absolute z-50 w-72 overflow-y-auto rounded-2xl p-1.5',
                        placement === 'up' ? 'bottom-full mb-2' : 'top-full mt-2',
                        align === 'right' ? 'right-0' : 'left-0',
                    )}
                >
                    {clearable && value !== undefined && (
                        <button
                            type="button"
                            onClick={() => {
                                onChange(undefined);
                                setOpen(false);
                            }}
                            className="w-full rounded-lg px-3 py-2 text-left text-sm text-text-3 hover:bg-surface-2"
                        >
                            Clear selection
                        </button>
                    )}

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
            )}
        </div>
    );
}
