// workflowAlertMotion.ts
// The motion behind a workflow-alert notice: whether to move at all, the grow into the card
// and the tuck into the bell.
//
// The entrance and the bell's swing are CSS keyframes (WorkflowAlertNotice.css). The grow
// and the tuck run from one element's box to another's, which only script knows, so they use
// the Web Animations API. Both animate transform and opacity only, which the compositor can
// run without laying the page out again.
//
// The global reduced-motion rule in theme.css shortens CSS animations and transitions. It
// cannot reach these, so every call checks the preference itself and fades instead of
// moving (roadmap gotcha 52). The CSS entrance is swapped for a fade the same way, by class,
// rather than left to the global rule, so the result does not depend on how short the
// browser makes a 0.01 ms keyframe.

import { useSyncExternalStore } from 'react';

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
const GROW_MS = 280;
const TUCK_MS = 420;
const FADE_MS = 160;
/** A finished promise can be held back by a throttled tab; nothing waits on it longer than this. */
const SETTLE_GRACE_MS = 250;

let override: boolean | null = null;
const listeners = new Set<() => void>();

function mediaQuery(): MediaQueryList | null {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
        return null;
    }
    return window.matchMedia(REDUCED_MOTION_QUERY);
}

/** Whether to fade instead of move: the reader's setting, or the lab's override of it. */
export function prefersReducedMotion(): boolean {
    if (override !== null) {
        return override;
    }
    return mediaQuery()?.matches ?? false;
}

/** Only the alert lab calls this, to preview both settings without changing the system's. */
export function setWorkflowAlertMotionOverride(reduced: boolean | null): void {
    override = reduced;
    for (const listener of [...listeners]) {
        listener();
    }
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener);
    const query = mediaQuery();
    query?.addEventListener('change', listener);
    return () => {
        listeners.delete(listener);
        query?.removeEventListener('change', listener);
    };
}

export function useReducedMotion(): boolean {
    return useSyncExternalStore(subscribe, prefersReducedMotion, () => false);
}

function canAnimate(element: Element | null): element is HTMLElement {
    return element instanceof HTMLElement && typeof element.animate === 'function';
}

async function settle(animation: Animation, duration: number): Promise<void> {
    await Promise.race([
        animation.finished.then(() => undefined, () => undefined),
        new Promise<void>((resolve) => setTimeout(resolve, duration + SETTLE_GRACE_MS)),
    ]);
}

function centre(rect: DOMRect): { x: number; y: number } {
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

function usable(rect: DOMRect | null): rect is DOMRect {
    return Boolean(rect && rect.width > 0 && rect.height > 0);
}

/**
 * Grow the card out of the notice it was opened from: the card starts at the notice's box
 * and settles into its own. With reduced motion, or no notice to grow from, it fades in.
 */
export async function growFromRect(panel: HTMLElement | null, from: DOMRect | null): Promise<void> {
    if (!canAnimate(panel)) {
        return;
    }
    const to = panel.getBoundingClientRect();
    if (prefersReducedMotion() || !usable(from) || !usable(to)) {
        await settle(panel.animate([{ opacity: 0 }, { opacity: 1 }], { duration: FADE_MS, easing: 'linear' }), FADE_MS);
        return;
    }
    const start = centre(from);
    const end = centre(to);
    const animation = panel.animate(
        [
            {
                transform: `translate(${start.x - end.x}px, ${start.y - end.y}px) scale(${from.width / to.width}, ${from.height / to.height})`,
                opacity: 0.4,
            },
            { transform: 'translate(0, 0) scale(1, 1)', opacity: 1 },
        ],
        { duration: GROW_MS, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' },
    );
    await settle(animation, GROW_MS);
}

/**
 * Tuck the notice into the bell: it shrinks toward the bell's centre and fades. With reduced
 * motion, or no bell on screen, it fades where it is. The final frame is held, so the notice
 * does not flash back before it is removed.
 */
export async function tuckIntoTarget(notice: HTMLElement | null, target: Element | null): Promise<void> {
    if (!canAnimate(notice)) {
        return;
    }
    const from = notice.getBoundingClientRect();
    const to = target ? target.getBoundingClientRect() : null;
    if (prefersReducedMotion() || !usable(from) || !usable(to)) {
        await settle(
            notice.animate([{ opacity: 1 }, { opacity: 0 }], { duration: FADE_MS, easing: 'linear', fill: 'forwards' }),
            FADE_MS,
        );
        return;
    }
    const start = centre(from);
    const end = centre(to);
    const animation = notice.animate(
        [
            { transform: 'translate(0, 0) scale(1)', opacity: 1 },
            { transform: `translate(${end.x - start.x}px, ${end.y - start.y}px) scale(0.2)`, opacity: 0 },
        ],
        { duration: TUCK_MS, easing: 'cubic-bezier(0.4, 0, 0.2, 1)', fill: 'forwards' },
    );
    await settle(animation, TUCK_MS);
}
