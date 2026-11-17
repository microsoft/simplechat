// miniReactHooks.ts
// Version: 0.261.445
// Implemented in: 0.261.445
//
// Just enough of React's hooks to run a hook under plain Node, for functional tests that have no DOM
// and no renderer to run it in.
//
// A test bundles the hook with this module aliased to the `react` specifier, so the hook's own
// `useState`, `useRef`, `useCallback`, `useMemo` and `useEffect` come from here, and calls `renderHook`.
// The hook's code is the code that ships; only the runtime around it is replaced.
//
// Updates are batched the way React batches one made outside an event handler: everything set in one
// burst of promise callbacks produces a single render, which runs on a later turn of the event loop, so
// a test sees the values a user would have seen on screen and not the states in between. Effects run
// after the render that asked for them, a state change made after `unmount` is dropped (and counted, so
// a test can require that a hook does not make one), and `hide`/`show` and `restartEffects` stand in for
// what React does to a component that is hidden and shown again, and to a strict-mode mount.

type Dependencies = readonly unknown[] | undefined;
type Cleanup = (() => void) | void;
type SetState<T> = (update: T | ((current: T) => T)) => void;

interface Slot {
    value?: unknown;
    deps?: Dependencies;
    cleanup?: Cleanup;
    effect?: () => Cleanup;
    ref?: { current: unknown };
    set?: SetState<never>;
}

interface Instance {
    slots: Slot[];
    cursor: number;
    mounted: boolean;
    scheduled: boolean;
    droppedUpdates: number;
    effects: Slot[];
    schedule: () => void;
}

let rendering: Instance | null = null;

function enter(): { instance: Instance; slot: Slot } {
    if (!rendering) {
        throw new Error('A hook was called outside renderHook.');
    }
    const instance = rendering;
    const slot = (instance.slots[instance.cursor] ??= {});
    instance.cursor += 1;
    return { instance, slot };
}

function changed(previous: Dependencies, next: Dependencies): boolean {
    return !previous || !next || previous.length !== next.length
        || next.some((value, index) => !Object.is(value, previous[index]));
}

export function useState<T>(initial: T | (() => T)): [T, SetState<T>] {
    const { instance, slot } = enter();
    if (!('value' in slot)) {
        slot.value = typeof initial === 'function' ? (initial as () => T)() : initial;
        slot.set = ((update: T | ((current: T) => T)) => {
            if (!instance.mounted) {
                instance.droppedUpdates += 1;
                return;
            }
            const next = typeof update === 'function' ? (update as (current: T) => T)(slot.value as T) : update;
            if (!Object.is(next, slot.value)) {
                slot.value = next;
                instance.schedule();
            }
        }) as SetState<never>;
    }
    return [slot.value as T, slot.set as SetState<T>];
}

export function useRef<T>(initial: T): { current: T } {
    const { slot } = enter();
    slot.ref ??= { current: initial };
    return slot.ref as { current: T };
}

export function useMemo<T>(factory: () => T, deps: Dependencies): T {
    const { slot } = enter();
    if (!('value' in slot) || changed(slot.deps, deps)) {
        slot.value = factory();
        slot.deps = deps;
    }
    return slot.value as T;
}

export function useCallback<T>(callback: T, deps: Dependencies): T {
    return useMemo(() => callback, deps);
}

export function useEffect(effect: () => Cleanup, deps?: Dependencies): void {
    const { instance, slot } = enter();
    slot.effect = effect;
    if (!('deps' in slot) || changed(slot.deps, deps)) {
        slot.deps = deps;
        instance.effects.push(slot);
    }
}

// The names other React-aware modules in a bundle import. None is called by the hooks under test.
export const useLayoutEffect = useEffect;
export default { useState, useRef, useMemo, useCallback, useEffect, useLayoutEffect };

export interface RenderedHook<T> {
    /** What the latest render returned. */
    readonly current: T;
    /** Everything every committed render returned, oldest first. */
    readonly renders: readonly T[];
    /** State changes made while the hook was not mounted. A hook that guards its updates makes none. */
    readonly updatesAfterUnmount: number;
    /** Let the batched render and the effects it asked for happen. */
    flush: () => Promise<void>;
    /** Remove the hook for good: its cleanups run and later state changes are dropped. */
    unmount: () => void;
    /** Hide it as React can: cleanups run and updates are dropped, but its state is kept. */
    hide: () => void;
    /** Show a hidden hook again: its effects run afresh over the state it kept. */
    show: () => Promise<void>;
    /** What a strict-mode mount does: run every cleanup and then every effect again, while mounted. */
    restartEffects: () => Promise<void>;
}

export function renderHook<T>(hook: () => T): RenderedHook<T> {
    const instance: Instance = {
        slots: [], cursor: 0, mounted: true, scheduled: false, droppedUpdates: 0, effects: [],
        schedule: () => {
            if (!instance.scheduled) {
                instance.scheduled = true;
                setTimeout(render, 0);
            }
        },
    };
    const renders: T[] = [];
    let current: T;

    function runEffects(slots: Slot[]): void {
        for (const slot of slots) {
            slot.cleanup?.();
            slot.cleanup = slot.effect?.();
        }
    }

    function runCleanups(): void {
        for (const slot of instance.slots) {
            slot.cleanup?.();
            slot.cleanup = undefined;
        }
    }

    function render(): void {
        instance.scheduled = false;
        if (!instance.mounted) {
            return;
        }
        instance.cursor = 0;
        rendering = instance;
        try {
            current = hook();
        } finally {
            rendering = null;
        }
        renders.push(current);
        runEffects(instance.effects.splice(0));
    }

    render();

    const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
    // Removing a hook for good and hiding it differ only in whether anyone shows it again.
    const detach = () => {
        instance.mounted = false;
        runCleanups();
    };
    return {
        get current() {
            return current;
        },
        renders,
        get updatesAfterUnmount() {
            return instance.droppedUpdates;
        },
        flush: async () => {
            await settle();
            await settle();
        },
        unmount: detach,
        hide: detach,
        show: async () => {
            instance.mounted = true;
            runEffects(instance.slots.filter((slot) => slot.effect));
            await settle();
            await settle();
        },
        restartEffects: async () => {
            runCleanups();
            runEffects(instance.slots.filter((slot) => slot.effect));
            await settle();
            await settle();
        },
    };
}
