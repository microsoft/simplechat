// Dropdown.tsx
// Accessible popover menu used by the chat toolbar pickers.

import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Check, ChevronDown } from 'lucide-react';

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
    align = 'left',
    compact = false,
}: DropdownProps) {
    const [open, setOpen] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

    const selected = options.find((option) => option.value === value);

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
        return () => {
            document.removeEventListener('mousedown', onPointerDown);
            document.removeEventListener('keydown', onKeyDown);
        };
    }, [open]);

    // Options arrive pre-grouped by scope (personal / group / public), so headings are
    // emitted whenever the group changes rather than by re-sorting the list.
    let lastGroup: string | undefined;

    return (
        <div className="relative" ref={containerRef}>
            <button
                type="button"
                disabled={disabled}
                onClick={() => setOpen((isOpen) => !isOpen)}
                aria-haspopup="listbox"
                aria-expanded={open}
                title={compact ? (selected?.label ?? placeholder) : undefined}
                className={clsx(
                    'inline-flex h-9 items-center gap-2 rounded-xl border border-edge',
                    'bg-surface-1 text-sm font-medium transition-colors',
                    'hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50',
                    compact ? 'w-9 justify-center' : 'max-w-[14rem] px-3',
                    selected ? 'text-text-1' : 'text-text-3',
                )}
            >
                {icon}
                {!compact && (
                    <>
                        <span className="truncate">{selected?.label ?? placeholder}</span>
                        <ChevronDown size={14} className="ml-auto shrink-0 opacity-60" />
                    </>
                )}
            </button>

            {open && (
                <div
                    role="listbox"
                    className={clsx(
                        'glass-modal absolute z-50 mt-2 max-h-80 w-72 overflow-y-auto rounded-2xl p-1.5',
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
