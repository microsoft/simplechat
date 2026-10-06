// useFocusFallback.ts
// Keep keyboard focus near an action whose own button goes away once the action is done.
//
// A run's Retry or Cancel disappears as soon as the server no longer offers it, which is usually
// right after it was used. The browser then drops focus to the page body, and a keyboard or screen
// reader user loses their place. Arm this when the action starts; once it has finished, if its
// control is gone and nothing else took focus, focus moves to the container instead.

import { useCallback, useEffect, useRef, type RefObject } from 'react';

export function useFocusFallback(
    container: RefObject<HTMLElement | null>,
    controlShown: boolean,
    busy: boolean,
): () => void {
    const armed = useRef(false);

    useEffect(() => {
        if (!armed.current || busy) {
            return;
        }
        armed.current = false;
        if (controlShown) {
            return;
        }
        const active = document.activeElement;
        if (!active || active === document.body) {
            container.current?.focus({ preventScroll: true });
        }
    }, [container, controlShown, busy]);

    return useCallback(() => {
        armed.current = true;
    }, []);
}
