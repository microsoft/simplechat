// Modal.tsx
// The dialog shell shared by the documents explorer and the chat rail.
//
// Rendered through a portal rather than in place. A `backdrop-filter` anywhere in an
// ancestor establishes a containing block for `position: fixed`, so a dialog opened from
// inside the glass sidebar would otherwise be laid out against the 280px rail instead of
// the viewport. The portal is what lets one shell serve both callers.

import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';

export function Modal({
    title,
    description,
    onClose,
    children,
    footer,
    wide = false,
}: {
    title: string;
    description?: string;
    onClose: () => void;
    children: ReactNode;
    footer?: ReactNode;
    wide?: boolean;
}) {
    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [onClose]);

    return createPortal(
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
            role="dialog"
            aria-modal="true"
            aria-label={title}
            onClick={onClose}
        >
            <div
                onClick={(event) => event.stopPropagation()}
                className={clsx(
                    'glass-modal flex max-h-[85vh] w-full flex-col rounded-2xl',
                    wide ? 'max-w-2xl' : 'max-w-lg',
                )}
            >
                <div className="flex items-start justify-between gap-3 border-b border-edge px-4 py-3">
                    <div className="min-w-0">
                        <h2 className="text-sm font-semibold text-text-1">{title}</h2>
                        {description ? (
                            <p className="mt-0.5 text-xs text-text-3">{description}</p>
                        ) : null}
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close"
                        className="rounded-lg p-1 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={16} />
                    </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>

                {footer ? (
                    <div className="flex items-center justify-end gap-2 border-t border-edge px-4 py-3">
                        {footer}
                    </div>
                ) : null}
            </div>
        </div>,
        document.body,
    );
}
