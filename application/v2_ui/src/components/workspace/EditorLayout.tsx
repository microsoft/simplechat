// EditorLayout.tsx
// The building blocks every agent and action editor is drawn with, so an editor reads the
// way an Admin Settings card does.
//
// The same editors open from My Workspace, from a group workspace, and from Admin Settings
// for the organisation's global agents and actions. Each piece here reuses the Admin
// Settings row (`.admin-field` in theme.css): the label and its help sit in a left column
// with the control on the right once there is room, and stack otherwise.
//
// One difference from an Admin Settings card: an editor nests fields inside panels, groups
// and fieldsets, so a row cannot judge its layout by the card's width. Every row measures
// its own width and takes the two-column layout once it is wide enough (`data-wide`).
// Rows are not CSS size containers: in Chromium a size container can be left with a
// stale, collapsed layout when React adds an editor section after it.

import { useId, useLayoutEffect, useRef, type ComponentProps, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { ChevronRight } from 'lucide-react';
import { Toggle } from '../ui/primitives';

/** How much of the control column a control may take on a wide row; see `.admin-field`. */
export type EditorFieldWidth = 'compact' | 'standard' | 'wide' | 'full';

const HELP_CLASS = 'admin-field-help break-words text-[0.8125rem] leading-relaxed text-text-3';

/** The row width, in rem, at which Admin Settings puts the label beside the control. */
const WIDE_ROW_REM = 50;

let rowObserver: ResizeObserver | null = null;

function markRowWidth(row: Element, width: number) {
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    row.toggleAttribute('data-wide', width >= WIDE_ROW_REM * rem);
}

/**
 * Keeps a row's `data-wide` in step with its width. One observer serves every row, and
 * its callbacks run before paint, so a row never shows the wrong layout; the first
 * measurement happens before the row is first painted.
 */
function useRowWidth<T extends HTMLElement>() {
    const row = useRef<T>(null);
    useLayoutEffect(() => {
        const element = row.current;
        if (!element || typeof ResizeObserver === 'undefined') return undefined;
        rowObserver ??= new ResizeObserver((entries) => {
            for (const entry of entries) markRowWidth(entry.target, entry.contentRect.width);
        });
        markRowWidth(element, element.getBoundingClientRect().width);
        rowObserver.observe(element);
        return () => rowObserver?.unobserve(element);
    }, []);
    return row;
}

/**
 * One labelled setting: label and help beside the control on a wide row, stacked on a
 * narrow one. `helpId` and `errorId` keep the ids controls already point `aria-describedby`
 * at, so describing a control does not change with the layout.
 */
export function EditorFieldRow({
    htmlFor, label, required = false, help, helpId, error, errorId, trailing, width = 'wide', children,
}: {
    htmlFor: string;
    label: ReactNode;
    required?: boolean;
    help?: ReactNode;
    helpId?: string;
    error?: ReactNode;
    errorId?: string;
    /** Shown at the end of the label line, such as a character count. */
    trailing?: ReactNode;
    width?: EditorFieldWidth;
    children: ReactNode;
}) {
    const row = useRowWidth<HTMLDivElement>();
    return (
        <div ref={row} className="editor-field">
            <div className="admin-field py-3" data-field-width={width}>
                <div className="admin-field-heading flex items-baseline justify-between gap-3">
                    <label htmlFor={htmlFor} className="min-w-0 break-words text-sm font-semibold text-text-1">
                        {label}{required ? <span aria-hidden="true" className="ml-1 text-danger">*</span> : null}
                    </label>
                    {trailing}
                </div>
                {help ? <p id={helpId} className={HELP_CLASS}>{help}</p> : null}
                <div className="admin-field-control min-w-0 space-y-1.5">
                    {children}
                    {error ? <p id={errorId} role="alert" className="break-words text-sm text-danger">{error}</p> : null}
                </div>
            </div>
        </div>
    );
}

/**
 * A row headed by plain text rather than a form label, for a readout or a set of commands
 * that belongs in the settings list without being one control.
 */
export function EditorRow({
    heading, help, width = 'wide', children,
}: {
    heading: ReactNode;
    help?: ReactNode;
    width?: EditorFieldWidth;
    children: ReactNode;
}) {
    const row = useRowWidth<HTMLDivElement>();
    return (
        <div ref={row} className="editor-field">
            <div className="admin-field py-3" data-field-width={width}>
                <div className="admin-field-heading">
                    <span className="block break-words text-sm font-semibold text-text-1">{heading}</span>
                </div>
                {help ? <p className={HELP_CLASS}>{help}</p> : null}
                <div className="admin-field-control min-w-0 space-y-2">{children}</div>
            </div>
        </div>
    );
}

/**
 * A group of related choices -- radio cards, a checkbox list, an icon picker -- laid out as
 * one row. The legend stays the group's accessible name; the visible heading repeats it in
 * the label column, which a rendered legend cannot occupy.
 */
export function EditorFieldset({
    legend, help, width = 'full', disabled, children,
}: {
    legend: string;
    help?: ReactNode;
    width?: EditorFieldWidth;
    disabled?: boolean;
    children: ReactNode;
}) {
    const helpId = useId();
    const row = useRowWidth<HTMLFieldSetElement>();
    return (
        <fieldset ref={row} className="editor-field min-w-0" disabled={disabled} aria-describedby={help ? helpId : undefined}>
            <legend className="sr-only">{legend}</legend>
            <div className="admin-field py-3" data-field-width={width}>
                <div className="admin-field-heading" aria-hidden="true">
                    <span className="block break-words text-sm font-semibold text-text-1">{legend}</span>
                </div>
                {help ? <p id={helpId} className={HELP_CLASS}>{help}</p> : null}
                <div className="admin-field-control min-w-0 space-y-3">{children}</div>
            </div>
        </fieldset>
    );
}

/**
 * A switch drawn as an Admin Settings switch row. A `lead` switch is the one the settings
 * after it depend on; it is highlighted the way a section's leading switch is, and those
 * settings go inside `EditorDependents` beneath it.
 */
export function EditorSwitch({
    lead = false, error, ...toggle
}: ComponentProps<typeof Toggle> & { lead?: boolean; error?: ReactNode }) {
    return (
        <div
            className={clsx(lead
                ? 'editor-lead mb-1 rounded-xl border border-accent/40 bg-accent-soft px-3 py-1'
                : 'editor-field')}
            data-setting-emphasis={lead ? 'primary' : undefined}
        >
            <div className="admin-switch-row py-1">
                <Toggle {...toggle} labelClassName="font-semibold" descriptionClassName="max-w-[72ch] text-[0.8125rem]" />
            </div>
            {error ? <p role="alert" className="pb-2 text-sm text-danger">{error}</p> : null}
        </div>
    );
}

/** The settings that only apply while a lead switch is on, indented beneath it. */
export function EditorDependents({ children }: { children: ReactNode }) {
    return (
        <div className="editor-dependents ms-3 min-w-0 space-y-3 border-s-2 border-edge-strong ps-3" data-setting-emphasis="dependent">
            {children}
        </div>
    );
}

/**
 * A collapsible group of settings, drawn as Admin Settings draws one. Built on `details`,
 * so find-in-page and the editor's invalid-field handling still open it. Pass `open` and
 * `onToggle` to control it; otherwise `defaultOpen` sets how it starts.
 */
export function EditorGroup({
    summary, hint, open, defaultOpen = false, onToggle, tone = 'default', children,
}: {
    summary: string;
    /** Shown at the end of the header, such as a count. */
    hint?: ReactNode;
    open?: boolean;
    defaultOpen?: boolean;
    onToggle?: (open: boolean) => void;
    tone?: 'default' | 'warn';
    children: ReactNode;
}) {
    return (
        <details
            className={clsx(
                'editor-group group/editor-group min-w-0 rounded-xl border bg-surface-solid',
                tone === 'warn' ? 'border-warn/40' : 'border-edge-strong',
            )}
            open={open ?? defaultOpen}
            onToggle={onToggle ? (event) => onToggle(event.currentTarget.open) : undefined}
        >
            <summary
                className={clsx(
                    'flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-xl px-3 py-2 text-left',
                    'hover:bg-surface-sunken group-open/editor-group:rounded-b-none group-open/editor-group:bg-surface-sunken',
                    '[&::-webkit-details-marker]:hidden',
                )}
            >
                <ChevronRight size={14} aria-hidden="true"
                    className="shrink-0 text-text-2 transition-transform group-open/editor-group:rotate-90" />
                <span className="min-w-0 break-words text-sm font-semibold text-text-1">{summary}</span>
                {hint ? <span className="ml-auto shrink-0 text-xs text-text-3">{hint}</span> : null}
            </summary>
            <div className="min-w-0 space-y-3 border-t border-edge-strong px-3 pt-1 pb-3 sm:px-4">{children}</div>
        </details>
    );
}

/** A titled panel that stays open, for tools that sit beside the settings. */
export function EditorPanel({
    title, description, tone = 'default', children,
}: {
    title?: string;
    description?: ReactNode;
    tone?: 'default' | 'warn';
    children: ReactNode;
}) {
    return (
        <div className={clsx(
            'editor-panel min-w-0 rounded-xl border bg-surface-solid',
            tone === 'warn' ? 'border-warn/40' : 'border-edge-strong',
        )}>
            {title ? (
                <div className="rounded-t-xl border-b border-edge-strong bg-surface-sunken px-3 py-2.5 sm:px-4">
                    <h4 className="break-words text-sm font-semibold text-text-1">{title}</h4>
                    {description ? <p className="mt-0.5 text-[0.8125rem] leading-relaxed text-text-3">{description}</p> : null}
                </div>
            ) : null}
            <div className="min-w-0 space-y-3 px-3 py-3 sm:px-4">{children}</div>
        </div>
    );
}

/**
 * An `EditorPanel` that is also a fieldset, for a group of settings that share one name.
 * The legend is floated so it renders as the panel's header band instead of sitting on the
 * border, while staying the group's accessible name.
 */
export function EditorPanelFieldset({
    legend, description, tone = 'default', disabled, children,
}: {
    legend: string;
    description?: ReactNode;
    tone?: 'default' | 'warn';
    disabled?: boolean;
    children: ReactNode;
}) {
    const descriptionId = useId();
    return (
        <fieldset
            className={clsx(
                'editor-panel min-w-0 rounded-xl border bg-surface-solid',
                tone === 'warn' ? 'border-warn/40' : 'border-edge-strong',
            )}
            disabled={disabled}
            aria-describedby={description ? descriptionId : undefined}
        >
            <legend className="float-left w-full rounded-t-xl border-b border-edge-strong bg-surface-sunken px-3 py-2.5 sm:px-4">
                <span className="block break-words text-sm font-semibold text-text-1">{legend}</span>
            </legend>
            <div className="clear-both min-w-0 space-y-3 px-3 py-3 sm:px-4">
                {description ? <p id={descriptionId} className="text-[0.8125rem] leading-relaxed text-text-3">{description}</p> : null}
                {children}
            </div>
        </fieldset>
    );
}
