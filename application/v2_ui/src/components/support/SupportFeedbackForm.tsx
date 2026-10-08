// SupportFeedbackForm.tsx
// The Send Feedback form: a bug report or a feature request for the organisation's own support
// mailbox, prepared as an email draft.
//
// The classic page draws two forms side by side that ask for the same name, email and
// organization. Here there is one form and one choice of what is being sent. The contact fields
// are filled once, and each kind keeps its own details, so switching to a feature request never
// overwrites a half-written bug report.
//
// Sending follows the classic page: `/api/support/send_feedback_email` records the submission
// in the activity log and returns the recipient and subject line, then the browser opens a
// text-only draft in the local mail app for the user to review and send. Nothing is emailed by
// the server, and the recipient is learned only from that reply.

import { useRef, useState, type FormEvent, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, Bug, CheckCircle2, Lightbulb, Loader2, Mail, type LucideIcon } from 'lucide-react';
import { api } from '../../lib/apiClient';
import {
    FEEDBACK_LABELS,
    SUPPORT_FEEDBACK_ENDPOINT,
    feedbackDraftBody,
    safeMailtoHref,
    validateFeedbackFields,
    type FeedbackFields,
    type FeedbackKind,
    type FeedbackResponse,
} from '../../lib/supportFeedback';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';

type ContactFields = Omit<FeedbackFields, 'details'>;
type FieldErrors = Partial<Record<keyof FeedbackFields, string>>;

interface FeedbackDraft {
    kind: FeedbackKind;
    contact: ContactFields;
    details: Record<FeedbackKind, string>;
}

/**
 * The report in progress, kept for the life of the page load.
 *
 * Leaving to check something and coming back is the normal way to write a bug report, and losing
 * the text to that would be a small disaster. It stays until it is replaced or the page reloads.
 */
let savedDraft: FeedbackDraft | null = null;

const KINDS: { kind: FeedbackKind; icon: LucideIcon; description: string }[] = [
    { kind: 'bug_report', icon: Bug, description: 'Something is broken or not working as expected.' },
    { kind: 'feature_request', icon: Lightbulb, description: 'An improvement that would help your work.' },
];

const DETAILS_LABEL: Record<FeedbackKind, string> = {
    bug_report: 'Bug Details',
    feature_request: 'Feature Request Details',
};

const DETAILS_PLACEHOLDER: Record<FeedbackKind, string> = {
    bug_report: 'Describe what happened, what you expected, and how to reproduce it.',
    feature_request: 'Describe the problem, the improvement you want, and the outcome you need.',
};

const SUBMIT_LABEL: Record<FeedbackKind, string> = {
    bug_report: 'Open Bug Report Draft',
    feature_request: 'Open Feature Request Draft',
};

const FIELD_ORDER = ['name', 'email', 'organization', 'details'] as const;

const ID_PREFIX = 'support-feedback';

// Fields sit on a glass panel, where the shell's light `edge` border vanishes against a white
// fill; the strong edge keeps every field's boundary visible in both themes.
const INPUT_CLASS = clsx(
    'w-full min-w-0 rounded-xl border border-edge-strong bg-surface-solid px-3 py-2 text-sm text-text-1',
    'placeholder:text-text-3 aria-[invalid=true]:border-danger',
    'focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60',
);

function fieldId(key: keyof FeedbackFields): string {
    return `${ID_PREFIX}-${key}`;
}

/** The accessibility wiring an input needs to name its own error. */
function errorProps(key: keyof FeedbackFields, errors: FieldErrors) {
    return {
        'aria-invalid': Boolean(errors[key]),
        'aria-describedby': errors[key] ? `${fieldId(key)}-error` : undefined,
    };
}

function Field({
    name,
    label,
    error,
    children,
}: {
    name: keyof FeedbackFields;
    label: string;
    error?: string;
    children: ReactNode;
}) {
    return (
        <div className="space-y-1.5">
            <label htmlFor={fieldId(name)} className="block text-sm font-medium text-text-1">
                {label}
            </label>
            {children}
            {error ? (
                <p id={`${fieldId(name)}-error`} className="flex items-center gap-1 text-xs text-danger">
                    <AlertCircle size={12} aria-hidden="true" className="shrink-0" />
                    {error}
                </p>
            ) : null}
        </div>
    );
}

type SubmitResult =
    | { ok: true; recipient: string; subject: string; body: string }
    | { ok: false; message: string };

export function SupportFeedbackForm({
    defaultName,
    defaultEmail,
    appVersion,
}: {
    defaultName: string;
    defaultEmail: string;
    appVersion: string;
}) {
    const [draft, setDraft] = useState<FeedbackDraft>(
        () =>
            savedDraft ?? {
                kind: 'bug_report',
                contact: { name: defaultName, email: defaultEmail, organization: '' },
                details: { bug_report: '', feature_request: '' },
            },
    );
    const [errors, setErrors] = useState<FieldErrors>({});
    const [sending, setSending] = useState(false);
    const [result, setResult] = useState<SubmitResult | null>(null);
    const formRef = useRef<HTMLFormElement>(null);

    const { kind } = draft;
    const fields: FeedbackFields = { ...draft.contact, details: draft.details[kind] };

    const commit = (next: FeedbackDraft) => {
        savedDraft = next;
        setDraft(next);
    };

    const clearError = (key: keyof FeedbackFields) => {
        setErrors((current) => {
            if (!current[key]) {
                return current;
            }
            const remaining = { ...current };
            delete remaining[key];
            return remaining;
        });
    };

    const updateContact = (key: keyof ContactFields, value: string) => {
        commit({ ...draft, contact: { ...draft.contact, [key]: value } });
        clearError(key);
    };

    const updateDetails = (value: string) => {
        commit({ ...draft, details: { ...draft.details, [kind]: value } });
        clearError('details');
    };

    const chooseKind = (next: FeedbackKind) => {
        commit({ ...draft, kind: next });
        // The details now on screen belong to the other kind, so a complaint about the old
        // ones would point at text that is not there.
        clearError('details');
        setResult(null);
    };

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        const problems = validateFeedbackFields(fields);
        setErrors(problems);
        const firstInvalid = FIELD_ORDER.find((key) => problems[key]);
        if (firstInvalid) {
            setResult({ ok: false, message: 'Complete the highlighted fields to prepare the draft.' });
            formRef.current?.querySelector<HTMLElement>(`#${fieldId(firstInvalid)}`)?.focus();
            return;
        }

        setSending(true);
        setResult(null);
        try {
            const response = await api.post<FeedbackResponse>(SUPPORT_FEEDBACK_ENDPOINT, {
                feedbackType: kind,
                reporterName: fields.name.trim(),
                reporterEmail: fields.email.trim(),
                organization: fields.organization.trim(),
                details: fields.details.trim(),
            });
            const body = feedbackDraftBody(kind, fields, appVersion);
            const draftHref = safeMailtoHref(response.recipientEmail, response.subjectLine, body);
            if (!draftHref) {
                throw new Error(
                    'The support mailbox is not a valid email address. Ask your administrators to check the Send Feedback settings.',
                );
            }
            setResult({ ok: true, recipient: response.recipientEmail, subject: response.subjectLine, body });
            toast.success(`${FEEDBACK_LABELS[kind]} email draft prepared.`);
            window.location.href = draftHref;
        } catch (error) {
            const message =
                error instanceof Error && error.message
                    ? error.message
                    : 'Unable to prepare the feedback email draft.';
            setResult({ ok: false, message });
            toast.error(message);
        } finally {
            setSending(false);
        }
    };

    return (
        <form
            ref={formRef}
            noValidate
            onSubmit={(event) => void submit(event)}
            aria-label="Send Feedback"
            className="space-y-5"
        >
            <fieldset disabled={sending}>
                <legend className="text-sm font-medium text-text-1">What are you sending?</legend>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    {KINDS.map(({ kind: option, icon: Icon, description }) => {
                        const selected = option === kind;
                        return (
                            <label
                                key={option}
                                className={clsx(
                                    'flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2.5 transition-colors',
                                    'has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent',
                                    selected
                                        ? 'border-accent bg-accent-soft'
                                        : 'border-edge-strong bg-surface-solid hover:bg-surface-2',
                                )}
                            >
                                <input
                                    type="radio"
                                    name={`${ID_PREFIX}-kind`}
                                    value={option}
                                    checked={selected}
                                    onChange={() => chooseKind(option)}
                                    className="sr-only"
                                />
                                <Icon
                                    size={18}
                                    aria-hidden="true"
                                    className={clsx('mt-0.5 shrink-0', selected ? 'text-accent' : 'text-text-3')}
                                />
                                <span className="min-w-0">
                                    <span className="block text-sm font-semibold text-text-1">
                                        {FEEDBACK_LABELS[option]}
                                    </span>
                                    <span className="block text-xs text-text-3">{description}</span>
                                </span>
                            </label>
                        );
                    })}
                </div>
            </fieldset>

            <div className="grid gap-4 sm:grid-cols-2">
                <Field name="name" label="Name" error={errors.name}>
                    <input
                        id={fieldId('name')}
                        type="text"
                        autoComplete="name"
                        required
                        className={INPUT_CLASS}
                        value={fields.name}
                        disabled={sending}
                        {...errorProps('name', errors)}
                        onChange={(event) => updateContact('name', event.target.value)}
                    />
                </Field>
                <Field name="email" label="Email" error={errors.email}>
                    <input
                        id={fieldId('email')}
                        type="email"
                        autoComplete="email"
                        required
                        className={INPUT_CLASS}
                        value={fields.email}
                        disabled={sending}
                        {...errorProps('email', errors)}
                        onChange={(event) => updateContact('email', event.target.value)}
                    />
                </Field>
            </div>

            <Field name="organization" label="Organization" error={errors.organization}>
                <input
                    id={fieldId('organization')}
                    type="text"
                    autoComplete="organization"
                    required
                    className={INPUT_CLASS}
                    value={fields.organization}
                    disabled={sending}
                    {...errorProps('organization', errors)}
                    onChange={(event) => updateContact('organization', event.target.value)}
                />
            </Field>

            <Field name="details" label={DETAILS_LABEL[kind]} error={errors.details}>
                <textarea
                    id={fieldId('details')}
                    rows={7}
                    autoComplete="off"
                    required
                    className={clsx(INPUT_CLASS, 'resize-y leading-relaxed')}
                    placeholder={DETAILS_PLACEHOLDER[kind]}
                    value={fields.details}
                    disabled={sending}
                    {...errorProps('details', errors)}
                    onChange={(event) => updateDetails(event.target.value)}
                />
            </Field>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-edge-strong pt-4">
                <GlassButton type="submit" variant="primary" size="md" disabled={sending}>
                    {sending ? (
                        <Loader2 size={15} aria-hidden="true" className="animate-spin" />
                    ) : (
                        <Mail size={15} aria-hidden="true" />
                    )}
                    {sending ? 'Preparing draft…' : SUBMIT_LABEL[kind]}
                </GlassButton>
                <p className="min-w-0 flex-1 basis-56 text-xs text-text-3">
                    Nothing is sent until you send the draft from your mail app.
                </p>
            </div>

            <div aria-live="polite">
                {result?.ok === true ? (
                    <p className="flex items-start gap-1.5 text-sm leading-relaxed text-text-2">
                        <CheckCircle2 size={15} aria-hidden="true" className="mt-0.5 shrink-0 text-ok" />
                        <span>
                            Draft prepared for {result.recipient}. If your mail app did not open,{' '}
                            <a
                                href={safeMailtoHref(result.recipient, result.subject, result.body)}
                                className="font-medium text-accent underline"
                            >
                                open the draft
                            </a>
                            .
                        </span>
                    </p>
                ) : null}
                {result?.ok === false ? (
                    <p role="alert" className="flex items-start gap-1.5 text-sm leading-relaxed text-danger">
                        <AlertCircle size={15} aria-hidden="true" className="mt-0.5 shrink-0" />
                        {result.message}
                    </p>
                ) : null}
            </div>
        </form>
    );
}
