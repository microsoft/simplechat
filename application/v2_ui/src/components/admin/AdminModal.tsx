// AdminModal.tsx
// Dialog shell shared by the Admin Settings modals.
//
// Follows the conventions the chat dialogs already established: a click-to-close backdrop,
// Escape to dismiss, focus moved in on open and handed back on close, and no focus-trap
// utility, since no other dialog in this UI uses one.

import { useEffect, useRef, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { X } from 'lucide-react';
import { GlassPanel } from '../ui/primitives';

export function AdminModal({
    title,
    description,
    onClose,
    footer,
    size = 'md',
    children,
}: {
    title: string;
    description?: string;
    onClose: () => void;
    footer?: ReactNode;
    size?: 'md' | 'lg';
    children: ReactNode;
}) {
    const closeRef = useRef<HTMLButtonElement>(null);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    useEffect(() => {
        const previous = document.activeElement as HTMLElement | null;
        closeRef.current?.focus();
        return () => previous?.focus?.();
    }, []);

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label={title}
        >
            <div className="absolute inset-0 bg-black/60" aria-hidden="true" onClick={onClose} />

            <GlassPanel
                elevation="modal"
                edge
                className={clsx(
                    'relative flex max-h-[88vh] w-full flex-col overflow-hidden',
                    size === 'lg' ? 'max-w-4xl' : 'max-w-2xl',
                )}
            >
                <div className="flex shrink-0 items-start gap-3 border-b border-edge px-5 py-3">
                    <div className="min-w-0 flex-1">
                        <h2 className="truncate text-sm font-semibold text-text-1">{title}</h2>
                        {description ? (
                            <p className="mt-0.5 text-xs text-text-3">{description}</p>
                        ) : null}
                    </div>
                    <button
                        ref={closeRef}
                        type="button"
                        onClick={onClose}
                        title="Close"
                        aria-label="Close"
                        className="shrink-0 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={16} />
                    </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>

                {footer ? (
                    <div className="flex shrink-0 items-center justify-end gap-2 border-t border-edge px-5 py-3">
                        {footer}
                    </div>
                ) : null}
            </GlassPanel>
        </div>
    );
}
