// HeaderActions.tsx
// Only explicitly visible actions count toward mobile overflow; statuses and dialog hosts do not.

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { ChevronDown, Loader2 } from 'lucide-react';
import { clsx } from 'clsx';
import { GlassButton } from '../ui/primitives';
import { ActionPopover } from '../ui/ActionPopover';
import { useMobileViewport } from '../../lib/useMobileViewport';

export interface HeaderAction {
    id: string;
    label: string;
    icon: ReactNode;
    onClick: () => void;
    variant?: 'primary' | 'subtle' | 'ghost';
    disabled?: boolean;
    loading?: boolean;
    /** Tours already use an icon on desktop. */
    iconOnly?: boolean;
    testId?: string;
}

export type HeaderActionItems = readonly (HeaderAction | null | false | undefined)[];

export function HeaderActionControl({ action, inPopover = false, onActivate }: {
    action: HeaderAction;
    inPopover?: boolean;
    onActivate?: () => void;
}) {
    return (
        <GlassButton type="button" size="sm" variant={action.variant}
            disabled={action.disabled || action.loading} aria-busy={action.loading || undefined}
            aria-label={action.label} title={action.label} data-testid={action.testId}
            onClick={() => {
                onActivate?.();
                action.onClick();
            }}
            className={clsx('header-action shrink-0', inPopover && 'w-full justify-start',
                action.iconOnly && !inPopover && 'header-action-icon-only')}>
            <span aria-hidden="true" className="flex shrink-0 items-center">
                {action.loading ? <Loader2 size={14} className="animate-spin" /> : action.icon}
            </span>
            <span className={clsx(!inPopover && 'header-action-label')}>{action.label}</span>
        </GlassButton>
    );
}

export function HeaderActions({ actions }: { actions: HeaderActionItems }) {
    const mobile = useMobileViewport();
    const visible = actions.filter((action): action is HeaderAction => Boolean(action));
    const overflow = mobile && visible.length > 2;
    const [open, setOpen] = useState(false);
    const triggerRef = useRef<HTMLButtonElement>(null);
    const id = useId();
    const close = useCallback((returnFocus: boolean) => {
        setOpen(false);
        if (returnFocus) triggerRef.current?.focus();
    }, []);
    const actionIds = visible.map((action) => action.id).join('|');
    useEffect(() => setOpen(false), [mobile, actionIds]);

    if (!visible.length) return null;
    return (
        <div className="page-header-actions ml-auto flex max-w-full shrink-0 items-center gap-2 md:flex-wrap">
            {(overflow ? visible.slice(0, 1) : visible).map((action) =>
                <HeaderActionControl key={action.id} action={action} />)}
            {overflow && (
                <button ref={triggerRef} type="button" title="More actions" aria-label="More actions"
                    aria-expanded={open} aria-controls={id}
                    onClick={() => setOpen((value) => !value)}
                    className="header-action flex shrink-0 items-center justify-center rounded-xl text-text-2 hover:bg-surface-2">
                    <ChevronDown size={18} aria-hidden="true" />
                </button>
            )}
            {overflow && open && (
                <ActionPopover id={id} label="More actions" anchorRef={triggerRef} onClose={close}>
                    {visible.slice(1).map((action) =>
                        <HeaderActionControl key={action.id} action={action} inPopover onActivate={() => close(true)} />)}
                </ActionPopover>
            )}
        </div>
    );
}
