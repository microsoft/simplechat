// useLongPress.ts
// Press-and-hold on a touch screen, for surfaces whose controls are only revealed on hover.
//
// Touch only: a mouse or pen keeps hover and right-click, so their behaviour is unchanged.
// The press is abandoned the moment it turns into anything else -- a scroll (the browser
// cancels the pointer), a drag past a few pixels, a second finger, or an early lift -- so
// scrolling a thread never opens anything. Presses that start on something with a touch
// behaviour of its own (a link, a button, a field, code someone may want to select) are left
// to it.

import { useCallback, useEffect, useRef } from 'react';
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from 'react';

/** How long a finger has to stay down. Matches the platform feel of iOS and Android menus. */
export const LONG_PRESS_MS = 450;

/** How far a finger may drift before the press counts as a scroll or drag instead. */
export const LONG_PRESS_MOVE_TOLERANCE_PX = 10;

/** Presses that start on these keep their own behaviour. */
export const LONG_PRESS_IGNORED_TARGETS = [
    'a',
    'button',
    'input',
    'textarea',
    'select',
    'summary',
    'pre',
    'code',
    '[contenteditable="true"]',
    '[role="dialog"]',
    '[data-no-long-press]',
].join(',');

/** How long after the lift a click is still treated as the lift's own. */
const LIFT_CLICK_WINDOW_MS = 400;

/** Whether the event started in the element's own DOM, rather than in a portal it renders. */
function isOwnEvent(event: { currentTarget: EventTarget; target: EventTarget }): boolean {
    return event.currentTarget instanceof Node
        && event.target instanceof Node
        && event.currentTarget.contains(event.target);
}

interface PressState {
    pointerId: number;
    x: number;
    y: number;
    timer: number;
    element: HTMLElement;
}

export interface LongPressHandlers {
    onPointerDown: (event: ReactPointerEvent<HTMLElement>) => void;
    onPointerMove: (event: ReactPointerEvent<HTMLElement>) => void;
    onPointerUp: (event: ReactPointerEvent<HTMLElement>) => void;
    onPointerCancel: (event: ReactPointerEvent<HTMLElement>) => void;
    onContextMenu: (event: ReactMouseEvent<HTMLElement>) => void;
    onClickCapture: (event: ReactMouseEvent<HTMLElement>) => void;
}

/**
 * Handlers to spread onto the element that should answer a long press.
 *
 * While a press is held the element's text cannot start a native selection or the iOS callout;
 * once the press fires, the lift that ends it is swallowed so it does not also tap whatever is
 * under the finger.
 */
export function useLongPress(onLongPress: () => void, enabled = true): LongPressHandlers {
    const press = useRef<PressState | null>(null);
    const fired = useRef(false);
    const callback = useRef(onLongPress);
    callback.current = onLongPress;

    const release = useCallback(() => {
        const current = press.current;
        if (!current) return;
        window.clearTimeout(current.timer);
        current.element.style.removeProperty('-webkit-user-select');
        current.element.style.removeProperty('user-select');
        current.element.style.removeProperty('-webkit-touch-callout');
        press.current = null;
    }, []);

    useEffect(() => release, [release]);

    const onPointerDown = useCallback((event: ReactPointerEvent<HTMLElement>) => {
        // React delivers events from a portal (the action sheet itself) to its React parent.
        // Only a press on the element's own DOM counts.
        if (!isOwnEvent(event)) return;
        release();
        fired.current = false;
        if (!enabled || event.pointerType !== 'touch' || !event.isPrimary) return;
        const target = event.target as Element | null;
        if (target?.closest(LONG_PRESS_IGNORED_TARGETS)) return;

        const element = event.currentTarget;
        element.style.setProperty('-webkit-user-select', 'none');
        element.style.setProperty('user-select', 'none');
        element.style.setProperty('-webkit-touch-callout', 'none');
        press.current = {
            pointerId: event.pointerId,
            x: event.clientX,
            y: event.clientY,
            element,
            timer: window.setTimeout(() => {
                fired.current = true;
                release();
                window.getSelection?.()?.removeAllRanges();
                navigator.vibrate?.(10);
                callback.current();
            }, LONG_PRESS_MS),
        };
    }, [enabled, release]);

    const onPointerMove = useCallback((event: ReactPointerEvent<HTMLElement>) => {
        const current = press.current;
        if (!current || event.pointerId !== current.pointerId) return;
        if (Math.abs(event.clientX - current.x) > LONG_PRESS_MOVE_TOLERANCE_PX
            || Math.abs(event.clientY - current.y) > LONG_PRESS_MOVE_TOLERANCE_PX) {
            release();
        }
    }, [release]);

    const onPointerUp = useCallback((event: ReactPointerEvent<HTMLElement>) => {
        if (!isOwnEvent(event)) return;
        release();
        // Some browsers send a click for the lift that ends a long press and some do not, so
        // the swallow below only waits briefly; a later tap is the user's own.
        if (fired.current) window.setTimeout(() => { fired.current = false; }, LIFT_CLICK_WINDOW_MS);
    }, [release]);
    const onPointerCancel = useCallback(() => release(), [release]);

    const onContextMenu = useCallback((event: ReactMouseEvent<HTMLElement>) => {
        // Android raises the browser's own menu on a long press; ours replaces it. A mouse
        // right-click is not a touch press and keeps the browser menu.
        if (isOwnEvent(event) && (press.current || fired.current)) event.preventDefault();
    }, []);

    const onClickCapture = useCallback((event: ReactMouseEvent<HTMLElement>) => {
        if (fired.current && isOwnEvent(event)) {
            fired.current = false;
            event.preventDefault();
            event.stopPropagation();
        }
    }, []);

    return { onPointerDown, onPointerMove, onPointerUp, onPointerCancel, onContextMenu, onClickCapture };
}
