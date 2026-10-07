// WorkflowField.tsx
// Field rows for the workflow editor, laid out the way V2 Admin Settings lays out a setting.
//
// Admin's `FieldShell` renders schema-declared fields; the workflow editor's fields are bespoke
// controls with their own change tracking, drafts and validation. These shells give those
// controls Admin's reading without routing them through Admin's schema: the label and its help
// on the left and the control on the right once the card is wide enough, stacked below that
// (the `.admin-field` rules in theme.css resolve against the card's container).
//
// Controls keep their own `aria-label`s. The visible label is associated with `htmlFor` for
// pointer users and so it reads as the field's name; the `aria-label` stays the accessible name
// the editor has always exposed, which assistive technology and the browser tests both rely on.

import { clsx } from 'clsx';
import type { ReactNode } from 'react';
import type { SectionStatus } from '../../lib/adminSections';
import { Toggle } from '../ui/primitives';

/**
 * What the editor hands each card it draws: where the card sits for the index, how it reads at
 * a glance, and the heading level the surrounding page needs.
 */
export interface WorkflowCardFrame {
    id: string;
    status: SectionStatus;
    meta?: string;
    headingLevel?: 2 | 3;
}

/**
 * How much of the control column a control may take on a wide card. The same scale as Admin's
 * `FieldWidth`: numbers are compact, selects standard, text wide, and longer content full.
 */
export type WorkflowFieldWidth = 'compact' | 'standard' | 'wide' | 'full';

/** The control classes shared by the editor's rows; a 40px control the heading lines up with. */
export const workflowFieldInputClass = clsx(
    'min-h-10 w-full rounded-lg border border-edge bg-surface-1 px-3 py-2',
    'text-sm text-text-1 placeholder:text-text-3',
    'focus:border-accent focus:outline-none',
    'disabled:cursor-not-allowed disabled:opacity-60',
);

export function WorkflowField({
    label,
    htmlFor,
    labelId,
    required = false,
    help,
    helpId,
    width = 'wide',
    inline = false,
    group = false,
    trailing,
    className,
    children,
}: {
    label: ReactNode;
    /** The control the visible label names. */
    htmlFor?: string;
    /** The heading's id, for a group of controls that names itself with `aria-labelledby`. */
    labelId?: string;
    required?: boolean;
    help?: ReactNode;
    /** Lets a control point `aria-describedby` at the help text. */
    helpId?: string;
    width?: WorkflowFieldWidth;
    /** A short readout, such as a status, that stays beside its label when the card is narrow. */
    inline?: boolean;
    /**
     * Render the control column as a labelled group, for several controls that share one name,
     * such as the days of the week. Requires `labelId`.
     */
    group?: boolean;
    trailing?: ReactNode;
    className?: string;
    children: ReactNode;
}) {
    const heading = htmlFor ? (
        <label htmlFor={htmlFor} className="text-sm font-semibold text-text-1">
            {label}
            {required ? <span aria-hidden="true"> *</span> : null}
        </label>
    ) : (
        <p id={labelId} className="text-sm font-semibold text-text-1">
            {label}
            {required ? <span aria-hidden="true"> *</span> : null}
        </p>
    );

    return (
        <div
            className={clsx('admin-field py-3', inline && 'admin-field-inline', className)}
            data-field-width={width}
        >
            <div className="admin-field-heading flex items-baseline justify-between gap-3">
                {heading}
                {trailing}
            </div>
            {help ? (
                <div id={helpId} className="admin-field-help text-[0.8125rem] leading-relaxed text-text-3">
                    {help}
                </div>
            ) : null}
            {group ? (
                <div role="group" aria-labelledby={labelId} className="admin-field-control min-w-0">
                    {children}
                </div>
            ) : (
                <div className="admin-field-control min-w-0">{children}</div>
            )}
        </div>
    );
}

/**
 * A value shown beside its label, such as the effective runner. Reads as a fact, not a control.
 */
export function WorkflowReadout({
    label,
    help,
    children,
}: {
    label: ReactNode;
    help?: ReactNode;
    children: ReactNode;
}) {
    return (
        <WorkflowField label={label} help={help} width="wide">
            <p className="flex min-h-10 items-center rounded-lg border border-edge bg-surface-sunken px-3 py-2 text-sm text-text-2">
                {children}
            </p>
        </WorkflowField>
    );
}

/**
 * The emphasis Admin derives from a section's switches, applied by hand.
 *
 * `primary` is the accent-backed row a card hangs off; `dependent` indents settings beside a
 * neutral rail under the control that leads them. The `data-setting-emphasis` attribute is the
 * hook theme.css uses to let a nested row's label column give up the indent, so its control
 * lines up with the rows around it.
 */
export function WorkflowFieldEmphasis({
    emphasis,
    className,
    children,
}: {
    emphasis: 'primary' | 'dependent';
    className?: string;
    children: ReactNode;
}) {
    return (
        <div
            data-setting-emphasis={emphasis}
            className={clsx(
                'min-w-0',
                emphasis === 'primary' && 'mb-3 rounded-xl border border-accent/40 bg-accent-soft px-3 py-1',
                emphasis === 'dependent' && 'ms-3 border-s-2 border-edge-strong ps-3',
                className,
            )}
        >
            {children}
        </div>
    );
}

/** A switch row in Admin's style: the switch, a semibold label, and its help beneath. */
export function WorkflowSwitch({
    label,
    description,
    checked,
    disabled,
    onChange,
}: {
    label: string;
    description?: string;
    checked: boolean;
    disabled?: boolean;
    onChange: (checked: boolean) => void;
}) {
    return (
        <div className="admin-switch-row py-1">
            <Toggle
                label={label}
                description={description}
                checked={checked}
                disabled={disabled}
                onChange={onChange}
                labelClassName="font-semibold"
                descriptionClassName="max-w-[72ch] text-[0.8125rem]"
            />
        </div>
    );
}

/** Independent switches, one per row until the card is wide enough to pair them. */
export function WorkflowSwitchGrid({ children }: { children: ReactNode }) {
    return <div className="admin-switch-grid">{children}</div>;
}

/** A stack of field rows divided like an Admin card's ungrouped fields. */
export function WorkflowFieldList({ className, children }: { className?: string; children: ReactNode }) {
    return <div className={clsx('divide-y divide-edge-strong', className)}>{children}</div>;
}

/** Explanatory text at the top of a card body, at Admin's group-help measure. */
export function WorkflowCardHelp({ className, children }: { className?: string; children: ReactNode }) {
    return (
        <p className={clsx('max-w-[72ch] text-[0.8125rem] leading-relaxed text-text-3', className)}>
            {children}
        </p>
    );
}
