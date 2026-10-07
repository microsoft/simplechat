// DmShared.tsx
// Building blocks shared by the Backup & Recovery cards.
//
// Nine cards make up the group, and five of them are workbenches. Drawing a status chip, a
// review check, a pager or a typed confirmation the same way in every one is what lets the
// group read as one surface rather than nine, and what keeps it reading like the rest of
// Admin Settings: the tones, borders and type sizes here are the ones the shared field
// controls and the Model Catalog workbench already use.

import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from 'react';
import { clsx } from 'clsx';
import {
    AlertCircle,
    CheckCircle2,
    ChevronLeft,
    ChevronRight,
    CircleSlash,
    Info,
    Loader2,
    OctagonX,
    TriangleAlert,
} from 'lucide-react';
import { GlassButton } from '../../ui/primitives';
import { inputClass } from '../fields';
import {
    humanizeToken,
    jobStatusTone,
    MIGRATION_STEP_LABELS,
    isMigrationStep,
    type ReviewCheckView,
    type StatusTone,
} from '../../../lib/dataManagementLogic';

/** Props every Backup & Recovery card takes from the settings page. */
export interface DmCardProps {
    /** The schema's help text for the section. */
    help?: string;
    /** Move the page to another section, clearing a filter that hides it. */
    onNavigate: (sectionId: string) => void;
    /** True while the page is saving, which locks every editable control. */
    disabled?: boolean;
}

/** The short description a card opens with, as the Model Catalog's does. */
export function DmIntro({ children }: { children: ReactNode }) {
    return <p className="mb-4 max-w-[72ch] text-[0.8125rem] leading-relaxed text-text-3">{children}</p>;
}

export type NoticeTone = 'info' | 'warning' | 'danger' | 'success';

const NOTICE_STYLE: Record<NoticeTone, { className: string; Icon: typeof Info }> = {
    info: { className: 'border-edge bg-surface-2 text-text-2', Icon: Info },
    warning: { className: 'border-warn/40 bg-warn-soft text-warn', Icon: TriangleAlert },
    danger: { className: 'border-danger/40 bg-danger-soft text-danger', Icon: AlertCircle },
    success: { className: 'border-ok/40 bg-ok-soft text-ok', Icon: CheckCircle2 },
};

/**
 * A standing callout: guidance, a risk, or the outcome of an action.
 *
 * `role` is left to the caller, because a risk that is always on screen is not an alert,
 * while the result of an action an administrator just took is.
 */
export function DmNotice({
    tone = 'info',
    title,
    children,
    action,
    role,
    className,
}: {
    tone?: NoticeTone;
    title?: string;
    children?: ReactNode;
    action?: ReactNode;
    role?: 'alert' | 'status' | 'note';
    className?: string;
}) {
    const { className: toneClass, Icon } = NOTICE_STYLE[tone];
    return (
        <div
            role={role}
            className={clsx(
                'flex flex-wrap items-start gap-2 rounded-lg border px-3 py-2 text-xs leading-relaxed',
                toneClass,
                className,
            )}
        >
            <Icon size={14} aria-hidden="true" className="mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1 basis-48">
                {title ? <p className="font-semibold">{title}</p> : null}
                {children ? <div className={clsx(title && 'mt-0.5')}>{children}</div> : null}
            </div>
            {action ? <div className="shrink-0">{action}</div> : null}
        </div>
    );
}

const PILL_TONE: Record<StatusTone, string> = {
    ok: 'border-ok/40 bg-ok-soft text-ok',
    warn: 'border-warn/40 bg-warn-soft text-warn',
    danger: 'border-danger/40 bg-danger-soft text-danger',
    active: 'border-accent/40 bg-accent-soft text-accent',
    neutral: 'border-edge-strong bg-surface-2 text-text-2',
};

/** A job or backup status, in the same words and tones wherever it appears. */
export function DmStatusPill({ status, className }: { status: unknown; className?: string }) {
    const text = humanizeToken(status) || 'Unknown';
    const tone = jobStatusTone(status);
    return (
        <span
            className={clsx(
                'inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap',
                PILL_TONE[tone],
                className,
            )}
        >
            {tone === 'active' ? (
                <Loader2 size={11} aria-hidden="true" className="shrink-0 animate-spin" />
            ) : null}
            {text}
        </span>
    );
}

/** A label chip, for a type or mode rather than a job state. */
export function DmChip({ children, tone = 'neutral' }: { children: ReactNode; tone?: StatusTone }) {
    return (
        <span
            className={clsx(
                'inline-flex max-w-full items-center rounded-full border px-2 py-0.5 text-xs whitespace-nowrap',
                PILL_TONE[tone],
            )}
        >
            {children}
        </span>
    );
}

/** Label and value tiles: counts, sizes, times. */
export function DmMetricGrid({
    items,
    className,
    label,
}: {
    items: Array<{ label: string; value: ReactNode }>;
    className?: string;
    label?: string;
}) {
    if (!items.length) return null;
    return (
        <dl
            aria-label={label}
            className={clsx('grid grid-cols-2 gap-2 @xl:grid-cols-3 @4xl:grid-cols-4', className)}
        >
            {items.map((item) => (
                <div
                    key={item.label}
                    className="min-w-0 rounded-lg border border-edge bg-surface-1 px-3 py-2"
                >
                    <dt className="text-xs text-text-3">{item.label}</dt>
                    <dd className="mt-0.5 text-sm font-semibold break-words text-text-1 tabular-nums">
                        {item.value}
                    </dd>
                </div>
            ))}
        </dl>
    );
}

const CHECK_STYLE = {
    pass: { Icon: CheckCircle2, className: 'text-ok', label: 'Passed' },
    warning: { Icon: TriangleAlert, className: 'text-warn', label: 'Warning' },
    block: { Icon: OctagonX, className: 'text-danger', label: 'Blocked' },
} as const;

/**
 * Server-owned review evidence.
 *
 * A migration check names the wizard step that fixes it, and when it fails `onFixStep` turns
 * that into a way back to the step.
 */
export function DmEvidenceChecks({
    checks,
    onFixStep,
    label = 'Review checks',
}: {
    checks: ReviewCheckView[];
    onFixStep?: (step: string) => void;
    label?: string;
}) {
    if (!checks.length) {
        return <p className="text-sm text-text-3">The review returned no checks.</p>;
    }
    return (
        <ul
            aria-label={label}
            className="divide-y divide-edge rounded-xl border border-edge-strong bg-surface-solid"
        >
            {checks.map((check) => {
                const style = CHECK_STYLE[check.tone];
                const step =
                    check.workflowStep && isMigrationStep(check.workflowStep) ? check.workflowStep : null;
                return (
                    <li key={check.id} className="flex flex-wrap items-start gap-2.5 px-3 py-2.5">
                        <style.Icon
                            size={16}
                            aria-hidden="true"
                            className={clsx('mt-0.5 shrink-0', style.className)}
                        />
                        <div className="min-w-0 flex-1 basis-48">
                            <p className="text-sm font-semibold text-text-1">
                                {check.label}
                                <span className="sr-only">: {style.label}</span>
                            </p>
                            <p className="mt-0.5 text-[0.8125rem] leading-relaxed text-text-3">
                                {check.message}
                            </p>
                        </div>
                        {onFixStep && step && check.tone !== 'pass' ? (
                            <GlassButton
                                type="button"
                                variant="subtle"
                                size="sm"
                                onClick={() => onFixStep(step)}
                            >
                                Go to {MIGRATION_STEP_LABELS[step]}
                            </GlassButton>
                        ) : null}
                    </li>
                );
            })}
        </ul>
    );
}

/** Previous and next over continuation tokens, with the page announced politely. */
export function DmPager({
    label,
    page,
    hasPrevious,
    hasNext,
    loading,
    status,
    className,
    onPrevious,
    onNext,
}: {
    label: string;
    page: number;
    hasPrevious: boolean;
    hasNext: boolean;
    loading?: boolean;
    status?: string;
    className?: string;
    onPrevious: () => void;
    onNext: () => void;
}) {
    return (
        <nav
            aria-label={label}
            className={clsx('flex flex-wrap items-center justify-between gap-2 pt-3', className)}
        >
            <span role="status" aria-live="polite" className="text-xs text-text-3">
                {status ?? `Page ${page}`}
            </span>
            <div className="flex items-center gap-1">
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    disabled={!hasPrevious || loading}
                    onClick={onPrevious}
                >
                    <ChevronLeft size={14} aria-hidden="true" />
                    Previous
                </GlassButton>
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    disabled={!hasNext || loading}
                    onClick={onNext}
                >
                    Next
                    <ChevronRight size={14} aria-hidden="true" />
                </GlassButton>
            </div>
        </nav>
    );
}

/**
 * A typed confirmation.
 *
 * The phrase is shown in full and compared exactly, as the server compares it. Whether it
 * matches is said in words as well as colour, so the state is not carried by colour alone.
 */
export function DmPhraseField({
    phrase,
    value,
    onChange,
    label,
    disabled,
}: {
    phrase: string;
    value: string;
    onChange: (value: string) => void;
    label?: string;
    disabled?: boolean;
}) {
    const id = useId();
    const matches = value === phrase;
    return (
        <div>
            <label htmlFor={id} className="block text-sm font-semibold text-text-1">
                {label ?? 'Type the confirmation phrase'}
            </label>
            <p id={`${id}-phrase`} className="mt-0.5 text-xs text-text-3">
                Type <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-text-1">{phrase}</code>{' '}
                exactly.
            </p>
            <input
                id={id}
                type="text"
                autoComplete="off"
                spellCheck={false}
                aria-describedby={`${id}-phrase ${id}-state`}
                className={clsx(inputClass, 'mt-1.5 font-mono')}
                value={value}
                disabled={disabled}
                onChange={(event) => onChange(event.target.value)}
            />
            <p
                id={`${id}-state`}
                aria-live="polite"
                className={clsx('mt-1 text-xs', matches ? 'text-ok' : 'text-text-3')}
            >
                {matches ? 'Phrase matches.' : value ? 'Phrase does not match yet.' : ''}
            </p>
        </div>
    );
}

/**
 * A collapsible group, drawn like the groups inside a settings card.
 *
 * `defaultOpen` decides the first render only; after that the administrator decides. A
 * search that should reveal the contents passes `forceOpen`.
 */
export function DmDisclosure({
    title,
    summary,
    defaultOpen = false,
    forceOpen = false,
    children,
}: {
    title: string;
    summary?: string;
    defaultOpen?: boolean;
    forceOpen?: boolean;
    children: ReactNode;
}) {
    const [open, setOpen] = useState(defaultOpen);
    const contentId = useId();
    useEffect(() => {
        if (forceOpen) setOpen(true);
    }, [forceOpen]);
    return (
        <div className="mt-3 rounded-xl border border-edge-strong bg-surface-solid">
            <button
                type="button"
                aria-expanded={open}
                aria-controls={contentId}
                className={clsx(
                    'flex min-h-11 w-full items-center gap-2 rounded-xl px-3 py-2 text-left hover:bg-surface-sunken',
                    open && 'rounded-b-none bg-surface-sunken',
                )}
                onClick={() => setOpen((current) => !current)}
            >
                <ChevronRight
                    size={14}
                    aria-hidden="true"
                    className={clsx('shrink-0 text-text-2 transition-transform', open && 'rotate-90')}
                />
                <span className="min-w-0 text-sm font-semibold text-text-1">{title}</span>
                {!open && summary ? (
                    <span className="ml-auto min-w-0 truncate pl-2 text-right text-xs text-text-3">
                        {summary}
                    </span>
                ) : null}
            </button>
            {open ? (
                <div id={contentId} className="border-t border-edge-strong px-3 pb-2 sm:px-4">
                    {children}
                </div>
            ) : null}
        </div>
    );
}

/** A labelled select for a workbench's filter row. */
export function DmFilterSelect({
    label,
    value,
    options,
    onChange,
    disabled,
}: {
    label: string;
    value: string;
    options: ReadonlyArray<readonly [string, string]>;
    onChange: (value: string) => void;
    disabled?: boolean;
}) {
    const id = useId();
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <label htmlFor={id} className="text-xs font-medium text-text-2">
                {label}
            </label>
            <select
                id={id}
                className={clsx(inputClass, 'min-w-0')}
                value={value}
                disabled={disabled}
                onChange={(event) => onChange(event.target.value)}
            >
                {options.map(([optionValue, text]) => (
                    <option key={optionValue} value={optionValue}>
                        {text}
                    </option>
                ))}
            </select>
        </div>
    );
}

/** A labelled date input for a workbench's filter row. */
export function DmDateFilter({
    label,
    value,
    onChange,
    disabled,
    invalid,
}: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    disabled?: boolean;
    invalid?: boolean;
}) {
    const id = useId();
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <label htmlFor={id} className="text-xs font-medium text-text-2">
                {label}
            </label>
            <input
                id={id}
                type="date"
                aria-invalid={invalid || undefined}
                className={clsx(inputClass, 'min-w-0', invalid && 'border-danger')}
                value={value}
                disabled={disabled}
                onChange={(event) => onChange(event.target.value)}
            />
        </div>
    );
}

/**
 * The list-beside-detail layout the Model Catalog uses.
 *
 * Side by side once the card is wide enough, stacked below that, with each pane scrolling
 * on its own so a long list does not push the detail out of view.
 */
export function DmWorkbench({
    list,
    detail,
    listLabel,
    detailRef,
}: {
    list: ReactNode;
    detail: ReactNode;
    listLabel: string;
    detailRef?: RefObject<HTMLDivElement>;
}) {
    return (
        <div className="mt-3 grid min-w-0 overflow-hidden rounded-xl border border-edge-strong bg-surface-solid @3xl:h-[clamp(28rem,68vh,48rem)] @3xl:grid-cols-[minmax(17rem,24rem)_minmax(0,1fr)]">
            <div
                role="region"
                aria-label={listLabel}
                className="max-h-[24rem] min-h-0 overflow-y-auto border-b border-edge-strong @3xl:max-h-none @3xl:border-r @3xl:border-b-0"
            >
                {list}
            </div>
            <div ref={detailRef} className="@container min-h-0 min-w-0 @3xl:overflow-y-auto">
                {detail}
            </div>
        </div>
    );
}

/** An empty pane with a sentence of guidance. */
export function DmEmpty({ title, children }: { title: string; children?: ReactNode }) {
    return (
        <div className="flex h-full min-h-[10rem] flex-col items-center justify-center px-6 py-8 text-center">
            <CircleSlash size={18} aria-hidden="true" className="mb-2 text-text-3" />
            <p className="text-sm font-medium text-text-1">{title}</p>
            {children ? (
                <div className="mt-1 max-w-sm text-[0.8125rem] leading-relaxed text-text-3">{children}</div>
            ) : null}
        </div>
    );
}

/**
 * Whether an element has been on screen at least once.
 *
 * The inventory and job lists run several Cosmos queries each, so a card loads them once an
 * administrator scrolls it into view rather than whenever the settings page opens.
 */
export function useVisibleOnce(ref: RefObject<Element>, rootMargin = '200px'): boolean {
    const [visible, setVisible] = useState(false);
    useEffect(() => {
        if (visible) return;
        const element = ref.current;
        if (!element || typeof IntersectionObserver === 'undefined') {
            setVisible(true);
            return;
        }
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) {
                    setVisible(true);
                    observer.disconnect();
                }
            },
            { rootMargin },
        );
        observer.observe(element);
        return () => observer.disconnect();
    }, [ref, rootMargin, visible]);
    return visible;
}

/**
 * Run a callback on an interval while `delay` is a number, stopping when it is null.
 *
 * The latest callback is the one called, so a poll never acts on stale props, and the timer
 * is cleared on unmount so nothing is fetched after the card is gone.
 */
export function useInterval(callback: () => void, delay: number | null): void {
    const saved = useRef(callback);
    saved.current = callback;
    useEffect(() => {
        if (delay === null) return;
        const timer = window.setInterval(() => saved.current(), delay);
        return () => window.clearInterval(timer);
    }, [delay]);
}

/** The current time, refreshed on an interval, for countdowns and "2m ago" readouts. */
export function useNow(intervalMs = 1000, active = true): number {
    const [now, setNow] = useState(() => Date.now());
    useInterval(() => setNow(Date.now()), active ? intervalMs : null);
    return now;
}
