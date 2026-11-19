// ScopeLockControl.tsx
// The ways a conversation's workspace scope lock is shown and opened, one per place it appears.
//
// Classic reaches the same modal from two icons: one beside the conversation title and one beside
// the "Scope" selector in its search panel. V2 has the same two places -- the chat header and the
// Documents picker -- and the conversation details, where the lock is also read. Each variant
// only asks `scopeLockStore` for the dialog; none of them owns it, because the picker closes when
// the reader clicks outside it and a dialog it hosted would go with it.
//
// Every variant draws nothing until the conversation has a lock state at all: a null state means
// no workspace document has been used yet, so there is nothing to lock or unlock.

import { clsx } from 'clsx';
import { Lock, Unlock } from 'lucide-react';
import { scopeLockControlLabel } from '../../lib/scopeLock';
import { useScopeLockStore, useScopeLockView } from '../../stores/scopeLockStore';

export type ScopeLockControlVariant = 'badge' | 'row' | 'notice';

export function ScopeLockControl({
    variant,
    onActivate,
}: {
    variant: ScopeLockControlVariant;
    /** Runs before the dialog opens, for a host that must get out of its way first. */
    onActivate?: () => void;
}) {
    const view = useScopeLockView();
    const pending = useScopeLockStore((state) => state.pending);

    if (view.state === 'hidden' || (variant === 'notice' && view.state !== 'locked')) {
        return null;
    }

    const locked = view.state === 'locked';
    const Icon = locked ? Lock : Unlock;
    const label = scopeLockControlLabel(view);
    const names = view.workspaces.map((workspace) => workspace.name).join(', ');
    const open = () => {
        onActivate?.();
        useScopeLockStore.getState().openDialog();
    };

    if (variant === 'badge') {
        return (
            <button
                type="button"
                onClick={open}
                aria-haspopup="dialog"
                aria-label={label}
                aria-busy={pending || undefined}
                title={label}
                data-scope-lock-state={view.state}
                className={clsx(
                    'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors',
                    'hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent',
                    locked ? 'text-warn' : 'text-text-3',
                )}
            >
                <Icon size={13} aria-hidden="true" />
            </button>
        );
    }

    if (variant === 'row') {
        const action =
            view.action === 'unlock' ? 'Unlock scope…' : view.action === 'lock' ? 'Lock scope…' : 'View details';
        const actionLabel =
            view.action === 'unlock'
                ? 'Unlock workspace scope'
                : view.action === 'lock'
                  ? 'Lock workspace scope'
                  : 'View workspace scope details';
        return (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span
                    className={clsx(
                        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs',
                        locked ? 'bg-warn-soft text-warn' : 'bg-surface-sunken text-text-3',
                    )}
                >
                    <Icon size={11} aria-hidden="true" />
                    {locked ? 'Locked' : 'Unlocked'}
                </span>
                {names && <span className="min-w-0 text-xs break-words text-text-3">{names}</span>}
                <button
                    type="button"
                    onClick={open}
                    aria-haspopup="dialog"
                    aria-label={actionLabel}
                    className="rounded-md px-1.5 py-0.5 text-xs font-medium text-accent hover:bg-accent-soft focus-visible:outline-2 focus-visible:outline-accent"
                >
                    {action}
                </button>
            </div>
        );
    }

    return (
        <div
            role="note"
            className="flex items-start gap-2 border-b border-edge bg-warn-soft px-3 py-2 text-xs text-text-2"
        >
            <Lock size={13} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
            <p className="min-w-0 flex-1 break-words">
                This conversation is locked to {names || 'its recorded workspaces'}. Only those
                workspaces are listed here.
            </p>
            <button
                type="button"
                onClick={open}
                aria-haspopup="dialog"
                className="shrink-0 rounded-md px-1.5 py-0.5 font-medium text-accent hover:bg-accent-soft focus-visible:outline-2 focus-visible:outline-accent"
            >
                {view.action === 'unlock' ? 'Manage' : 'Details'}
            </button>
        </div>
    );
}
