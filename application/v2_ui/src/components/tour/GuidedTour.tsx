// GuidedTour.tsx
// Walks the user through the controls on a page, one highlighted element at a time.
//
// The highlight is a transparent box positioned over the target, with an enormous box
// shadow that dims everything else. The page underneath stays as it is: no element is
// moved, wrapped or restyled, so a tour cannot break the layout it describes.
//
// Steps whose target is missing or not visible are dropped when the tour starts, so a
// control turned off by an administrator is skipped rather than pointed at.
//
// Keyboard: Escape ends the tour, the arrow keys move between steps, and Tab stays inside
// the step card. Focus returns to whatever opened the tour when it ends.

import {
    useCallback,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
    type KeyboardEvent,
} from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import type { TourDefinition, TourStep } from '../../lib/tours';

interface Box {
    top: number;
    left: number;
    width: number;
    height: number;
}

const PADDING = 6;
const CARD_WIDTH = 320;
const GAP = 12;

function findTarget(step: TourStep): HTMLElement | null {
    const element = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
    if (!element) {
        return null;
    }
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) {
        return null;
    }
    return element;
}

function measure(element: HTMLElement): Box {
    const rect = element.getBoundingClientRect();
    return {
        top: rect.top - PADDING,
        left: rect.left - PADDING,
        width: rect.width + PADDING * 2,
        height: rect.height + PADDING * 2,
    };
}

/** Below the target when there is room, otherwise above, clamped to the viewport. */
function placeCard(box: Box, cardHeight: number): { top: number; left: number } {
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const width = Math.min(CARD_WIDTH, viewportWidth - GAP * 2);

    let top = box.top + box.height + GAP;
    if (top + cardHeight > viewportHeight - GAP) {
        top = box.top - cardHeight - GAP;
    }
    // A target taller than the viewport leaves no room either side; overlap it instead.
    if (top < GAP) {
        top = Math.max(GAP, viewportHeight - cardHeight - GAP);
    }

    let left = box.left;
    left = Math.min(left, viewportWidth - width - GAP);
    left = Math.max(GAP, left);
    return { top, left };
}

export function GuidedTour({
    tour,
    onClose,
}: {
    tour: TourDefinition;
    onClose: () => void;
}) {
    // Resolved once, when the tour starts, so the step count does not shift under the user.
    const steps = useMemo(() => tour.steps.filter((step) => findTarget(step) !== null), [tour]);
    const [index, setIndex] = useState(0);
    const [box, setBox] = useState<Box | null>(null);
    const [cardPosition, setCardPosition] = useState<{ top: number; left: number } | null>(null);
    const cardRef = useRef<HTMLDivElement>(null);

    const step = steps[index];
    const reduceMotion = useMemo(
        () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
        [],
    );

    useEffect(() => {
        const previous = document.activeElement;
        return () => {
            if (previous instanceof HTMLElement && previous.isConnected) {
                previous.focus();
            }
        };
    }, []);

    const reposition = useCallback(() => {
        if (!step) {
            return;
        }
        const element = findTarget(step);
        if (!element) {
            setBox(null);
            return;
        }
        const nextBox = measure(element);
        setBox(nextBox);
        const cardHeight = cardRef.current?.offsetHeight ?? 160;
        setCardPosition(placeCard(nextBox, cardHeight));
    }, [step]);

    useLayoutEffect(() => {
        if (!step) {
            return;
        }
        findTarget(step)?.scrollIntoView({
            block: 'nearest',
            inline: 'nearest',
            behavior: reduceMotion ? 'auto' : 'smooth',
        });
        reposition();
        // Smooth scrolling settles after this frame; measure again once it has.
        const settle = window.setTimeout(reposition, reduceMotion ? 0 : 350);
        return () => window.clearTimeout(settle);
    }, [step, reposition, reduceMotion]);

    useEffect(() => {
        window.addEventListener('resize', reposition);
        // Capture, so scrolling inside any pane moves the highlight with its target.
        window.addEventListener('scroll', reposition, true);
        return () => {
            window.removeEventListener('resize', reposition);
            window.removeEventListener('scroll', reposition, true);
        };
    }, [reposition]);

    useEffect(() => {
        cardRef.current?.focus();
    }, [index]);

    const last = index >= steps.length - 1;
    const next = useCallback(() => {
        if (last) {
            onClose();
        } else {
            setIndex((value) => value + 1);
        }
    }, [last, onClose]);
    const previous = useCallback(() => setIndex((value) => Math.max(0, value - 1)), []);

    const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
        if (event.key === 'Escape') {
            event.preventDefault();
            onClose();
            return;
        }
        if (event.key === 'ArrowRight') {
            event.preventDefault();
            next();
            return;
        }
        if (event.key === 'ArrowLeft') {
            event.preventDefault();
            previous();
            return;
        }
        if (event.key === 'Tab') {
            const focusable = cardRef.current?.querySelectorAll<HTMLElement>('button:not([disabled])');
            if (!focusable || focusable.length === 0) {
                return;
            }
            const first = focusable[0];
            const final = focusable[focusable.length - 1];
            const active = document.activeElement;
            if (event.shiftKey && (active === first || active === cardRef.current)) {
                event.preventDefault();
                final.focus();
            } else if (!event.shiftKey && active === final) {
                event.preventDefault();
                first.focus();
            }
        }
    };

    if (!step) {
        return createPortal(
            <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-4">
                <div
                    ref={cardRef}
                    role="dialog"
                    aria-modal="true"
                    aria-labelledby="guided-tour-title"
                    tabIndex={-1}
                    onKeyDown={onKeyDown}
                    className="w-full max-w-sm rounded-2xl border border-edge bg-surface-solid p-5 shadow-xl outline-none"
                >
                    <h2 id="guided-tour-title" className="text-sm font-semibold text-text-1">
                        {tour.title}
                    </h2>
                    <p className="mt-2 text-sm text-text-2">
                        None of the controls this tour describes are on screen right now.
                    </p>
                    <div className="mt-4 flex justify-end">
                        <button
                            type="button"
                            onClick={onClose}
                            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-on-accent"
                        >
                            Close
                        </button>
                    </div>
                </div>
            </div>,
            document.body,
        );
    }

    return createPortal(
        <div className="fixed inset-0 z-[80]">
            {/* Swallows clicks on the dimmed page, so nothing behind it fires mid-tour. */}
            <div className="absolute inset-0" aria-hidden="true" onClick={onClose} />
            {box && (
                <div
                    aria-hidden="true"
                    className={clsx(
                        'pointer-events-none absolute rounded-xl ring-2 ring-accent',
                        !reduceMotion && 'transition-all duration-200',
                    )}
                    style={{
                        top: box.top,
                        left: box.left,
                        width: box.width,
                        height: box.height,
                        boxShadow: '0 0 0 9999px rgb(0 0 0 / 0.45)',
                    }}
                />
            )}
            <div
                ref={cardRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby="guided-tour-title"
                aria-describedby="guided-tour-body"
                tabIndex={-1}
                onKeyDown={onKeyDown}
                className={clsx(
                    'absolute rounded-2xl border border-edge bg-surface-solid p-4 shadow-xl outline-none',
                    !cardPosition && 'invisible',
                )}
                style={{
                    top: cardPosition?.top ?? 0,
                    left: cardPosition?.left ?? 0,
                    width: Math.min(CARD_WIDTH, window.innerWidth - GAP * 2),
                }}
            >
                <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                        <p className="text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                            {tour.title} · {index + 1} of {steps.length}
                        </p>
                        <h2 id="guided-tour-title" className="mt-1 text-sm font-semibold text-text-1">
                            {step.title}
                        </h2>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="End tour"
                        className="shrink-0 rounded-lg p-1 text-text-3 hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={15} />
                    </button>
                </div>
                <p id="guided-tour-body" className="mt-2 text-sm leading-relaxed text-text-2">
                    {step.body}
                </p>
                <div className="mt-4 flex items-center gap-2">
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-lg px-2 py-1.5 text-xs text-text-3 hover:bg-surface-2 hover:text-text-1"
                    >
                        Skip tour
                    </button>
                    <div className="ml-auto flex items-center gap-1.5">
                        <button
                            type="button"
                            onClick={previous}
                            disabled={index === 0}
                            className="flex items-center gap-1 rounded-lg border border-edge px-2.5 py-1.5 text-xs text-text-2 hover:bg-surface-2 disabled:opacity-40"
                        >
                            <ChevronLeft size={13} />
                            Back
                        </button>
                        <button
                            type="button"
                            onClick={next}
                            className="flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-medium text-on-accent"
                        >
                            {last ? 'Done' : 'Next'}
                            {!last && <ChevronRight size={13} />}
                        </button>
                    </div>
                </div>
            </div>
        </div>,
        document.body,
    );
}
