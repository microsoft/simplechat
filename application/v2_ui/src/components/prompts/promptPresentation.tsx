// promptPresentation.tsx
// Small shared pieces the prompt surfaces draw with.
//
// Kept out of the components that use them because the list, the details pane and the editor
// all show the same variable pill and the same favourite star, and three copies of a pill is
// how two of them end up a different size.

import { clsx } from 'clsx';
import { Braces, Star } from 'lucide-react';
import type { ReactNode } from 'react';

/**
 * The count of placeholders in a prompt.
 *
 * Shown rather than hidden because it changes what using the prompt will feel like: a prompt
 * with variables asks a question before it is inserted, and knowing that from the list is the
 * difference between choosing one and being interrupted by one.
 */
export function VariableCountPill({ count, className }: { count: number; className?: string }) {
    if (count <= 0) {
        return null;
    }
    return (
        <span
            className={clsx(
                'inline-flex shrink-0 items-center gap-1 rounded-full border border-edge',
                'bg-surface-2 px-1.5 py-0.5 text-[10px] leading-none font-medium text-text-3',
                className,
            )}
            title={count === 1 ? '1 variable to fill in' : `${count} variables to fill in`}
        >
            <Braces size={10} />
            {count}
        </span>
    );
}

/** A single placeholder, as it appears in the editor and the details pane. */
export function VariableChip({
    name,
    builtIn = false,
    hasDefault = false,
}: {
    name: string;
    builtIn?: boolean;
    hasDefault?: boolean;
}) {
    return (
        <span
            className={clsx(
                'inline-flex items-center rounded-md px-1.5 py-0.5 font-mono text-[11px] leading-none',
                builtIn
                    ? 'bg-accent-soft text-accent'
                    : 'border border-edge bg-surface-2 text-text-2',
            )}
            title={
                builtIn
                    ? 'Filled in automatically from this conversation'
                    : hasDefault
                      ? 'Has a default, so it can be left blank'
                      : 'You will be asked for this before the prompt is used'
            }
        >
            {`{{${name}}}`}
        </span>
    );
}

/** The favourite toggle, used in the list row and the details pane. */
export function FavoriteButton({
    active,
    onToggle,
    label,
    className,
}: {
    active: boolean;
    onToggle: () => void;
    label: string;
    className?: string;
}) {
    return (
        <button
            type="button"
            aria-pressed={active}
            aria-label={active ? `Remove ${label} from favourites` : `Add ${label} to favourites`}
            title={active ? 'Remove from favourites' : 'Add to favourites'}
            onClick={(event) => {
                event.stopPropagation();
                onToggle();
            }}
            className={clsx(
                'rounded-lg p-1 transition-colors',
                active
                    ? 'text-warn hover:bg-surface-2'
                    : 'text-text-3 hover:bg-surface-2 hover:text-text-1',
                className,
            )}
        >
            <Star size={14} fill={active ? 'currentColor' : 'none'} />
        </button>
    );
}

/** A labelled block in the details pane, matching the documents pane's headings. */
export function DetailField({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div>
            <h4 className="mb-1 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                {label}
            </h4>
            {children}
        </div>
    );
}
