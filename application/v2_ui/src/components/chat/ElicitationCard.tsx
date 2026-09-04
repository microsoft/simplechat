// ElicitationCard.tsx
// The planner's question, inline in the thread, asked one page at a time.
//
// When the planner cannot plan without more from the user, it returns an elicitation instead of a
// plan: a flat JSON-Schema object of primitives that MCP guarantees any client can render without a
// general Schema implementation (see the contract note on `ElicitationFieldSchema`). We render it
// as a short interview rather than one dense form, because `ui_hints.pages` groups the fields for
// exactly that reading — a question at a time is far less daunting than a wall of inputs.
//
// The answer is MCP-shaped verbatim: `{action, content}`. Only an `accept` carries content; a
// `decline` or `cancel` sends `{}`, because forwarding answers past the user's refusal would be a
// way to smuggle them in. That rule is the whole reason decline and cancel are separate buttons
// from Finish rather than a single dismiss.

import { useEffect, useMemo, useRef, useState } from 'react';
import { HelpCircle, X } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import {
    selectElicitation,
    useOrchestrationStore,
} from '../../stores/orchestrationStore';
import { answerElicitation } from '../../lib/orchestrationController';
import type {
    ElicitationAction,
    ElicitationFieldSchema,
    ElicitationRequestedSchema,
} from '../../lib/orchestration';

type FieldValues = Record<string, unknown>;

/**
 * How a field is drawn, decided once from its schema.
 *
 * The contract permits only these shapes: a top-level `enum` is a single choice, an `array` whose
 * `items` carry an `enum` is a multiple choice, and everything else is one primitive input. A
 * non-enum array has no natural single control, so it is a line-per-value textarea coerced back to
 * an array on submit.
 */
type FieldKind = 'radio' | 'checkboxes' | 'boolean' | 'number' | 'arrayText' | 'text';

function fieldKind(field: ElicitationFieldSchema): FieldKind {
    if (Array.isArray(field.enum)) {
        return 'radio';
    }
    if (field.type === 'array') {
        return field.items && Array.isArray(field.items.enum) ? 'checkboxes' : 'arrayText';
    }
    if (field.type === 'boolean') {
        return 'boolean';
    }
    if (field.type === 'number' || field.type === 'integer') {
        return 'number';
    }
    return 'text';
}

/** A field's label, preferring its schema title and falling back to a humanised key. */
function fieldLabel(name: string, field: ElicitationFieldSchema): string {
    if (field.title) {
        return field.title;
    }
    return name
        .replace(/[_-]+/g, ' ')
        .replace(/\b\w/g, (character) => character.toUpperCase());
}

/** Split a textarea's lines into a trimmed array, coercing numeric item types. */
function parseArrayText(raw: string, itemType: string | undefined): unknown[] {
    return raw
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line.length > 0)
        .map((line) => {
            if (itemType === 'number' || itemType === 'integer') {
                const parsed = Number(line);
                return Number.isFinite(parsed) ? parsed : line;
            }
            return line;
        });
}

/** Seed the form from each field's `default`, storing editable inputs as strings. */
function initialValues(schema: ElicitationRequestedSchema): FieldValues {
    const values: FieldValues = {};
    for (const [name, field] of Object.entries(schema.properties)) {
        if (field.default === undefined) {
            continue;
        }
        const kind = fieldKind(field);
        if (kind === 'number') {
            values[name] = String(field.default);
        } else if (kind === 'arrayText') {
            values[name] = Array.isArray(field.default)
                ? field.default.join('\n')
                : String(field.default);
        } else if (kind === 'text') {
            values[name] = String(field.default);
        } else {
            values[name] = field.default;
        }
    }
    return values;
}

export function ElicitationCard({
    conversationId,
    turnId,
}: {
    conversationId: string;
    turnId: string;
}) {
    const elicitation = useOrchestrationStore((state) =>
        selectElicitation(state, conversationId, turnId),
    );

    // Keyed on the elicitation id so a re-plan that asks a fresh question resets the form rather
    // than carrying the previous answers into it. The first render seeds through the lazy
    // initialiser below; only a genuinely new id re-seeds, which is the documented React pattern
    // for adjusting state to a changed input without an effect and its stale first frame.
    const elicitationId = elicitation?.elicitation_id ?? '';
    const [values, setValues] = useState<FieldValues>(() =>
        elicitation ? initialValues(elicitation.requested_schema) : {},
    );
    const [pageIndex, setPageIndex] = useState(0);
    const [submitted, setSubmitted] = useState(false);
    const pageRef = useRef<HTMLDivElement | null>(null);
    const seededFor = useRef(elicitationId);

    if (elicitation && seededFor.current !== elicitationId) {
        seededFor.current = elicitationId;
        setValues(initialValues(elicitation.requested_schema));
        setPageIndex(0);
        setSubmitted(false);
    }

    const schema = elicitation?.requested_schema;
    const pages = useMemo<string[][]>(() => {
        if (!elicitation || !schema) {
            return [];
        }
        const declared = elicitation.ui_hints.pages;
        if (declared.length > 0) {
            return declared;
        }
        // No paging hint: fall back to the ask order, or the property order, as a single page.
        const order =
            elicitation.ui_hints.order.length > 0
                ? elicitation.ui_hints.order
                : Object.keys(schema.properties);
        return [order];
    }, [elicitation, schema]);

    // Move focus to the page's first input whenever the page changes, so the interview is operable
    // from the keyboard without hunting for where the next answer goes.
    useEffect(() => {
        const first = pageRef.current?.querySelector<HTMLElement>(
            'input, textarea, [role="radio"]',
        );
        first?.focus();
    }, [pageIndex, elicitationId]);

    const requiredAnswered = useMemo(() => {
        if (!schema) {
            return false;
        }
        return schema.required.every((name) => {
            const field = schema.properties[name];
            if (!field) {
                return true;
            }
            return isAnswered(field, values[name]);
        });
    }, [schema, values]);

    if (!elicitation || !schema) {
        return null;
    }

    const pageFields = pages[pageIndex] ?? [];
    const isLastPage = pageIndex >= pages.length - 1;

    const setValue = (name: string, value: unknown) => {
        setValues((previous) => ({ ...previous, [name]: value }));
    };

    const buildContent = (): Record<string, unknown> => {
        const content: Record<string, unknown> = {};
        for (const [name, field] of Object.entries(schema.properties)) {
            const value = values[name];
            const kind = fieldKind(field);
            if (kind === 'number') {
                if (typeof value === 'string' && value.trim() !== '') {
                    const parsed = Number(value);
                    if (Number.isFinite(parsed)) {
                        content[name] = parsed;
                    }
                } else if (typeof value === 'number') {
                    content[name] = value;
                }
            } else if (kind === 'arrayText') {
                if (typeof value === 'string' && value.trim() !== '') {
                    content[name] = parseArrayText(value, field.items?.type);
                }
            } else if (kind === 'checkboxes') {
                if (Array.isArray(value) && value.length > 0) {
                    content[name] = value;
                }
            } else if (kind === 'boolean') {
                if (typeof value === 'boolean') {
                    content[name] = value;
                }
            } else if (value !== undefined && value !== null && String(value).trim() !== '') {
                content[name] = value;
            }
        }
        return content;
    };

    const send = (action: ElicitationAction) => {
        if (submitted) {
            return;
        }
        setSubmitted(true);
        // Only an accept carries content; a decline or cancel sends nothing, per the contract.
        const content = action === 'accept' ? buildContent() : {};
        void answerElicitation({ conversationId, turnId, response: { action, content } });
    };

    const advance = () => {
        if (isLastPage) {
            if (requiredAnswered) {
                send('accept');
            }
            return;
        }
        setPageIndex((index) => Math.min(index + 1, pages.length - 1));
    };

    return (
        <div className="my-3 rounded-2xl border border-edge-strong bg-surface-sunken p-3">
            <div className="flex items-start gap-2">
                <HelpCircle size={16} className="mt-0.5 shrink-0 text-accent" />
                <p className="min-w-0 flex-1 text-sm text-text-1">{elicitation.message}</p>
                <span className="shrink-0 text-xs text-text-3" aria-hidden="true">
                    {pageIndex + 1}/{pages.length}
                </span>
            </div>

            <form
                className="mt-3"
                onSubmit={(event) => {
                    event.preventDefault();
                    advance();
                }}
            >
                <div ref={pageRef} className="space-y-4">
                    {pageFields.map((name) => {
                        const field = schema.properties[name];
                        if (!field) {
                            return null;
                        }
                        return (
                            <Field
                                key={name}
                                name={name}
                                field={field}
                                required={schema.required.includes(name)}
                                value={values[name]}
                                onChange={(next) => setValue(name, next)}
                                disabled={submitted}
                            />
                        );
                    })}
                </div>

                <div className="mt-4 flex items-center gap-2">
                    <div className="flex items-center gap-1.5">
                        <GlassButton
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => send('cancel')}
                            disabled={submitted}
                            aria-label="Cancel and abandon this request"
                        >
                            <X size={14} />
                            Cancel
                        </GlassButton>
                        <GlassButton
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => send('decline')}
                            disabled={submitted}
                            aria-label="Decline to answer"
                        >
                            Decline
                        </GlassButton>
                    </div>
                    <div className="ml-auto flex items-center gap-2">
                        {pageIndex > 0 ? (
                            <GlassButton
                                type="button"
                                size="sm"
                                variant="subtle"
                                onClick={() => setPageIndex((index) => Math.max(index - 1, 0))}
                                disabled={submitted}
                            >
                                Back
                            </GlassButton>
                        ) : null}
                        <GlassButton
                            type="submit"
                            size="sm"
                            variant="primary"
                            disabled={submitted || (isLastPage && !requiredAnswered)}
                        >
                            {isLastPage ? 'Finish' : 'Next'}
                        </GlassButton>
                    </div>
                </div>

                {isLastPage && !requiredAnswered ? (
                    <p className="mt-2 text-right text-xs text-text-3">
                        Answer the required fields to finish.
                    </p>
                ) : null}
            </form>
        </div>
    );
}

/** Whether a field carries a usable answer, used both for required gating and content assembly. */
function isAnswered(field: ElicitationFieldSchema, value: unknown): boolean {
    switch (fieldKind(field)) {
        case 'radio':
            return value !== undefined && value !== null;
        case 'checkboxes':
            return Array.isArray(value) && value.length > 0;
        case 'boolean':
            return typeof value === 'boolean';
        case 'number':
            if (typeof value === 'number') {
                return Number.isFinite(value);
            }
            return typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value));
        case 'arrayText':
            if (Array.isArray(value)) {
                return value.length > 0;
            }
            return typeof value === 'string' && value.trim() !== '';
        default:
            return value !== undefined && value !== null && String(value).trim() !== '';
    }
}

/** One field of the schema, drawn as the control its kind calls for. */
function Field({
    name,
    field,
    required,
    value,
    onChange,
    disabled,
}: {
    name: string;
    field: ElicitationFieldSchema;
    required: boolean;
    value: unknown;
    onChange: (next: unknown) => void;
    disabled: boolean;
}) {
    const kind = fieldKind(field);
    const label = fieldLabel(name, field);
    const fieldId = `elicitation-${name}`;
    const describedById = field.description ? `${fieldId}-description` : undefined;

    // A single label node, reused verbatim in a <label>, a <legend> and a text label so the
    // required marker and wording never drift between control kinds.
    const labelText = (
        <span className="text-sm font-medium text-text-1">
            {label}
            {required ? (
                <span className="text-danger" aria-hidden="true">
                    {' '}
                    *
                </span>
            ) : null}
        </span>
    );

    const description = field.description ? (
        <p id={describedById} className="mt-0.5 text-xs text-text-3">
            {field.description}
        </p>
    ) : null;

    if (kind === 'radio') {
        const options = field.enum ?? [];
        return (
            <fieldset className="space-y-1.5" aria-required={required}>
                <legend>{labelText}</legend>
                {description}
                <div className="space-y-1">
                    {options.map((option, index) => (
                        <label
                            key={index}
                            className="flex items-center gap-2 text-sm text-text-2"
                        >
                            <input
                                type="radio"
                                name={name}
                                className="accent-accent"
                                checked={value === option}
                                disabled={disabled}
                                onChange={() => onChange(option)}
                            />
                            <span>{String(option)}</span>
                        </label>
                    ))}
                </div>
            </fieldset>
        );
    }

    if (kind === 'checkboxes') {
        const options = field.items?.enum ?? [];
        const selected = Array.isArray(value) ? value : [];
        return (
            <fieldset className="space-y-1.5" aria-required={required}>
                <legend>{labelText}</legend>
                {description}
                <div className="space-y-1">
                    {options.map((option, index) => (
                        <label
                            key={index}
                            className="flex items-center gap-2 text-sm text-text-2"
                        >
                            <input
                                type="checkbox"
                                className="accent-accent"
                                checked={selected.some((item) => item === option)}
                                disabled={disabled}
                                onChange={(event) => {
                                    const next = event.target.checked
                                        ? [...selected, option]
                                        : selected.filter((item) => item !== option);
                                    onChange(next);
                                }}
                            />
                            <span>{String(option)}</span>
                        </label>
                    ))}
                </div>
            </fieldset>
        );
    }

    if (kind === 'boolean') {
        return (
            <div>
                <label className="flex items-center gap-2">
                    <input
                        id={fieldId}
                        type="checkbox"
                        className="accent-accent"
                        checked={value === true}
                        disabled={disabled}
                        aria-describedby={describedById}
                        onChange={(event) => onChange(event.target.checked)}
                    />
                    {labelText}
                </label>
                {description}
            </div>
        );
    }

    if (kind === 'arrayText') {
        return (
            <div>
                <label htmlFor={fieldId}>{labelText}</label>
                {description}
                <textarea
                    id={fieldId}
                    className="mt-1 w-full rounded-xl border border-edge bg-surface-2 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:outline-none focus:ring-2 focus:ring-accent-ring"
                    rows={3}
                    value={typeof value === 'string' ? value : ''}
                    disabled={disabled}
                    placeholder="One value per line"
                    aria-describedby={describedById}
                    onChange={(event) => onChange(event.target.value)}
                />
            </div>
        );
    }

    return (
        <div>
            <label htmlFor={fieldId}>{labelText}</label>
            {description}
            <input
                id={fieldId}
                type={kind === 'number' ? 'number' : 'text'}
                className="mt-1 w-full rounded-xl border border-edge bg-surface-2 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:outline-none focus:ring-2 focus:ring-accent-ring"
                value={typeof value === 'string' || typeof value === 'number' ? String(value) : ''}
                disabled={disabled}
                aria-describedby={describedById}
                onChange={(event) => onChange(event.target.value)}
            />
        </div>
    );
}
