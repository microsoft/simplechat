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
//
// Keyboard focus follows the dialog: it moves inside when the dialog opens (unless the content
// already placed it), Tab and Shift+Tab stay inside the innermost open dialog, and when the
// dialog closes focus returns to the control that opened it, so a keyboard user carries on
// where they were rather than at the top of the page.

import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import { X } from 'lucide-react';
import type { MutableRefObject, ReactNode, Ref } from 'react';

/**
 * How much room the dialog needs.
 *
 * `md` is a confirmation or a short form. `lg` is a form long enough to scroll. `xl` is for a
 * surface that puts two panes side by side, where a narrower dialog would leave each half too
 * cramped to be worth splitting. `2xl` is for an `xl` surface that opens a side panel beside
 * its panes, such as the workflow editor's Changes panel.
 */
export type ModalSize = 'md' | 'lg' | 'xl' | '2xl';

const SIZE_CLASS: Record<ModalSize, string> = {
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-5xl',
    '2xl': 'max-w-7xl',
};

// What Tab can reach: enabled, shown, and not taken out of the tab order.
const FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex], [contenteditable="true"]';

// The dialogs open now, innermost last. Only the innermost keeps Tab inside itself: a dialog
// opened from another, such as a confirmation over a form, owns the keyboard until it closes.
const openPanels: HTMLElement[] = [];

function focusableWithin(panel: HTMLElement): HTMLElement[] {
    return [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((element) => (
        element.tabIndex >= 0 && !element.matches(':disabled') && !element.closest('[hidden], [inert]')
        && element.getClientRects().length > 0
    ));
}

// Focus the dialog should pull back: nothing, or the page underneath it. A popover the dialog
// opened, such as the prompt editor's variable picker, is portaled after the dialog and keeps
// its own Tab order.
function isBehind(dialog: HTMLElement, active: Element | null): boolean {
    if (!active || active === document.body) return true;
    return Boolean(dialog.compareDocumentPosition(active) & Node.DOCUMENT_POSITION_PRECEDING);
}

// The control that last held focus. An opener that disables itself while its dialog loads, as a
// workflow's Edit does while the editor's options are fetched, drops focus to the body before the
// dialog renders; this is how focus still finds its way back to it.
let lastFocused: HTMLElement | null = null;
if (typeof document !== 'undefined') {
    document.addEventListener('focusin', (event) => {
        if (event.target instanceof HTMLElement) lastFocused = event.target;
    }, true);
}

function currentOpener(): HTMLElement | null {
    const active = document.activeElement;
    if (active instanceof HTMLElement && active !== document.body) return active;
    return lastFocused?.isConnected ? lastFocused : null;
}

export function Modal({
    title,
    description,
    onClose,
    children,
    footer,
    size = 'md',
    bodyClassName,
    tall = false,
    banner,
    panelRef: externalPanelRef,
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
    /**
     * Replaces the default title row, for a dialog whose header says more than a title -- the
     * workflow alert card's priority band. The default close button goes with that row, so a
     * banner brings its own. `title` still names the dialog for assistive technology.
     */
    banner?: ReactNode;
    /** The dialog's panel, for a caller that animates it into place. */
    panelRef?: Ref<HTMLDivElement>;
}) {
    // Read while rendering: by the time an effect runs, a field's autoFocus has already moved
    // focus into the dialog, and it is the control that opened it that focus must return to.
    const [opener] = useState<HTMLElement | null>(currentOpener);
    const panelRef = useRef<HTMLDivElement | null>(null);
    const setPanelRef = useCallback((node: HTMLDivElement | null) => {
        panelRef.current = node;
        if (typeof externalPanelRef === 'function') {
            externalPanelRef(node);
        } else if (externalPanelRef) {
            (externalPanelRef as MutableRefObject<HTMLDivElement | null>).current = node;
        }
    }, [externalPanelRef]);

    useEffect(() => {
        const panel = panelRef.current;
        if (!panel) return undefined;
        openPanels.push(panel);
        // Deferred until this commit's effects have all run: a wrapper that places focus itself,
        // such as the workflow flow dialog, does so after this effect and must still record the
        // opener, not this panel, as the focus to return to.
        queueMicrotask(() => {
            if (panel.isConnected && !panel.contains(document.activeElement)) panel.focus({ preventScroll: true });
        });
        return () => {
            openPanels.splice(openPanels.indexOf(panel), 1);
            // Only a dialog that has really closed hands focus back: React StrictMode's rehearsal
            // unmount leaves the panel in the document. Focus a closing action moved elsewhere on
            // purpose stays where it was put.
            if (panel.isConnected) return;
            const active = document.activeElement;
            if (opener?.isConnected && (!active || active === document.body)) {
                opener.focus({ preventScroll: true });
            }
        };
    }, [opener]);

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                onClose();
                return;
            }
            const panel = panelRef.current;
            const dialog = panel?.parentElement;
            if (event.key !== 'Tab' || event.defaultPrevented || !panel || !dialog
                || openPanels[openPanels.length - 1] !== panel) return;
            const active = document.activeElement;
            const behind = !panel.contains(active) && isBehind(dialog, active);
            if (!panel.contains(active) && !behind) return;
            const focusable = focusableWithin(panel);
            if (focusable.length === 0) {
                event.preventDefault();
                panel.focus({ preventScroll: true });
            } else if (event.shiftKey && (behind || active === panel || active === focusable[0])) {
                event.preventDefault();
                focusable[focusable.length - 1].focus();
            } else if (!event.shiftKey && (behind || active === focusable[focusable.length - 1])) {
                event.preventDefault();
                focusable[0].focus();
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
                ref={setPanelRef}
                tabIndex={-1}
                onClick={(event) => event.stopPropagation()}
                className={clsx(
                    'glass-modal flex max-h-[85vh] w-full flex-col rounded-2xl outline-none',
                    SIZE_CLASS[size],
                    tall && 'h-[85vh]',
                )}
            >
                {banner ?? (
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
                )}

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
