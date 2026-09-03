// Modal.tsx
// The dialog shell every modal surface in the application sits inside.
//
// Previously local to the documents explorer. It is here because the prompts workbench needs
// the same shell, and a second copy is how two dialogs end up closing on different keys or
// trapping focus differently.
//
// Rendered through a portal to `document.body`. `position: fixed` escapes layout but not
// inherited opacity, and a message's action row lives inside a reveal-on-hover wrapper that
// sits at `opacity-0` unless the pointer is over that message or something inside it holds
// focus. A dialog opened from there and left as a descendant would fade to invisible the moment
// focus fell back to the body -- while still covering the page and swallowing clicks.
//
// `onClose` fires on Escape and on a backdrop click. A dialog holding unsaved work is expected
// to guard both by passing a handler that asks first, rather than by suppressing them: a modal
// that cannot be dismissed with Escape reads as broken.

import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';

/**
 * How much room the dialog needs.
 *
 * `md` is a confirmation or a short form. `lg` is a form long enough to scroll. `xl` is for a
 * surface that puts two panes side by side, where a narrower dialog would leave each half too
 * cramped to be worth splitting.
 */
export type ModalSize = 'md' | 'lg' | 'xl';

const SIZE_CLASS: Record<ModalSize, string> = {
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-5xl',
};

export function Modal({
    title,
    description,
    onClose,
    children,
    footer,
    size = 'md',
    bodyClassName,
    tall = false,
}: {
    title: string;
    description?: string;
    onClose: () => void;
    children: ReactNode;
    footer?: ReactNode;
    size?: ModalSize;
    /** Replaces the default body padding, for a body that manages its own panes. */
    bodyClassName?: string;
    /**
     * Claim the available height instead of growing to fit.
     *
     * An editor with a live preview needs a stable, tall body: sizing to content makes the
     * dialog jump every time a line is added, and the preview pane shrink as you type.
     */
    tall?: boolean;
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
                    SIZE_CLASS[size],
                    tall && 'h-[85vh]',
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

                <div
                    className={clsx(
                        'min-h-0 flex-1',
                        bodyClassName ?? 'overflow-y-auto px-4 py-3',
                    )}
                >
                    {children}
                </div>

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
