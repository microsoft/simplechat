// SendFeedback.tsx
// The Send Feedback cards: a bug report or feature request for the SimpleChat team.
//
// This is a utility, not a setting. Each card prepares an email draft through
// `/api/admin/settings/send_feedback_email` -- the endpoint the classic tab posts to, which
// records the submission in the activity log and returns the recipient and subject -- and
// then opens it in the local mail app. Nothing here touches the settings draft, so typing a
// report never lights up the save bar.
//
// The Support menu has a destination with the same name that routes end users' feedback to
// the organisation's own mailbox. The overview card says which is which and links across,
// because the shared name is the easiest thing in this group to get wrong.

import { useRef, useState, type FormEvent } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, ArrowRight, CheckCircle2, Loader2, Mail, TriangleAlert } from 'lucide-react';
import { api } from '../../lib/apiClient';
import type { AdminField } from '../../lib/adminFields';
import {
    FEEDBACK_LABELS,
    feedbackDraftBody,
    safeMailtoHref,
    validateFeedbackFields,
    type FeedbackFields,
    type FeedbackKind,
    type FeedbackResponse,
} from '../../lib/supportFeedback';
import { toast } from '../../stores/toastStore';
import { FieldShell, inputClass } from './fields';
import { GlassButton } from '../ui/primitives';
import { SUPPORT_MENU_SECTION_ID } from './LatestFeaturesPublication';

/**
 * Reports in progress, kept for the life of the page.
 *
 * A search or a category change unmounts these cards, and losing a half-written bug report
 * to a search for something else would be a small disaster. The text stays until it is
 * replaced or the page is reloaded.
 */
const feedbackDrafts: Partial<Record<FeedbackKind, FeedbackFields>> = {};

const DETAILS_PLACEHOLDER: Record<FeedbackKind, string> = {
    bug_report: 'Describe what happened, what you expected, and how to reproduce it.',
    feature_request: 'Describe the problem, the improvement you want, and the outcome you need.',
};

const DETAILS_LABEL: Record<FeedbackKind, string> = {
    bug_report: 'Bug Details',
    feature_request: 'Feature Request Details',
};

const SUBMIT_LABEL: Record<FeedbackKind, string> = {
    bug_report: 'Open Bug Report Email',
    feature_request: 'Open Feature Request Email',
};

/** A pseudo field, so the form rows use the same label/help/control layout as settings. */
function rowField(key: string, label: string, help?: string): AdminField {
    return { key, type: 'text', label, help };
}

export function SendFeedbackOverview({
    field,
    onNavigate,
}: {
    field: AdminField;
    onNavigate: (sectionId: string) => void;
}) {
    return (
        <div className="admin-field py-3" data-field-width="wide">
            <div className="admin-field-heading text-sm font-semibold text-text-1">{field.label}</div>
            {field.help ? (
                <p className="admin-field-help text-[0.8125rem] leading-relaxed text-text-3">{field.help}</p>
            ) : null}
            <div className="admin-field-control min-w-0 space-y-2">
                <p className="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-xs leading-relaxed text-warn">
                    <TriangleAlert size={13} aria-hidden="true" className="mt-0.5 shrink-0" />
                    <span>
                        The draft is text only. To share screenshots or files, attach them in your
                        mail app after the draft opens.
                    </span>
                </p>
                <div className="rounded-lg border border-edge bg-surface-1 px-3 py-2 text-xs leading-relaxed text-text-2">
                    <p>
                        This reaches the SimpleChat product team. Feedback from your own users goes
                        to your support mailbox instead, through the Support menu&apos;s Send
                        Feedback destination.
                    </p>
                    <button
                        type="button"
                        onClick={() => onNavigate(SUPPORT_MENU_SECTION_ID)}
                        className="mt-1.5 inline-flex items-center gap-1 rounded font-medium text-accent hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    >
                        Open Support settings
                        <ArrowRight size={12} aria-hidden="true" />
                    </button>
                </div>
            </div>
        </div>
    );
}

export function SendFeedbackForm({
    kind,
    field,
    defaultName,
    defaultEmail,
    appVersion,
}: {
    kind: FeedbackKind;
    field: AdminField;
    defaultName: string;
    defaultEmail: string;
    appVersion: string;
}) {
    const [fields, setFields] = useState<FeedbackFields>(
        () =>
            feedbackDrafts[kind] ?? {
                name: defaultName,
                email: defaultEmail,
                organization: '',
                details: '',
            },
    );
    const [errors, setErrors] = useState<Partial<Record<keyof FeedbackFields, string>>>({});
    const [sending, setSending] = useState(false);
    const [result, setResult] = useState<
        | { ok: true; recipient: string; subject: string; body: string }
        | { ok: false; message: string }
        | null
    >(null);
    const formRef = useRef<HTMLFormElement>(null);

    const idPrefix = `send-feedback-${kind}`;
    const label = FEEDBACK_LABELS[kind];

    const update = (key: keyof FeedbackFields, next: string) => {
        setFields((current) => {
            const updated = { ...current, [key]: next };
            feedbackDrafts[kind] = updated;
            return updated;
        });
        setErrors((current) => {
            if (!current[key]) {
                return current;
            }
            const remaining = { ...current };
            delete remaining[key];
            return remaining;
        });
    };

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        const problems = validateFeedbackFields(fields);
        setErrors(problems);
        const firstInvalid = (['name', 'email', 'organization', 'details'] as const).find(
            (key) => problems[key],
        );
        if (firstInvalid) {
            setResult({ ok: false, message: 'Complete the highlighted fields to prepare the draft.' });
            formRef.current?.querySelector<HTMLElement>(`#${idPrefix}-${firstInvalid}`)?.focus();
            return;
        }

        setSending(true);
        setResult(null);
        try {
            const response = await api.post<FeedbackResponse>('/api/admin/settings/send_feedback_email', {
                feedbackType: kind,
                reporterName: fields.name.trim(),
                reporterEmail: fields.email.trim(),
                organization: fields.organization.trim(),
                details: fields.details.trim(),
            });
            const body = feedbackDraftBody(kind, fields, appVersion);
            const draftHref = safeMailtoHref(response.recipientEmail, response.subjectLine, body);
            if (!draftHref) {
                throw new Error('The server returned a recipient that is not a valid email address.');
            }
            setResult({
                ok: true,
                recipient: response.recipientEmail,
                subject: response.subjectLine,
                body,
            });
            toast.success(`${label} email draft prepared.`);
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
        <form ref={formRef} noValidate onSubmit={(event) => void submit(event)} aria-label={field.label}>
            <div className="divide-y divide-edge-strong">
                <FieldShell field={rowField('name', 'Name')} htmlFor={`${idPrefix}-name`} error={errors.name}>
                    <input
                        id={`${idPrefix}-name`}
                        type="text"
                        autoComplete="name"
                        className={inputClass}
                        value={fields.name}
                        disabled={sending}
                        aria-invalid={Boolean(errors.name)}
                        onChange={(event) => update('name', event.target.value)}
                    />
                </FieldShell>
                <FieldShell field={rowField('email', 'Email')} htmlFor={`${idPrefix}-email`} error={errors.email}>
                    <input
                        id={`${idPrefix}-email`}
                        type="email"
                        autoComplete="email"
                        className={inputClass}
                        value={fields.email}
                        disabled={sending}
                        aria-invalid={Boolean(errors.email)}
                        onChange={(event) => update('email', event.target.value)}
                    />
                </FieldShell>
                <FieldShell
                    field={rowField('organization', 'Organization')}
                    htmlFor={`${idPrefix}-organization`}
                    error={errors.organization}
                >
                    <input
                        id={`${idPrefix}-organization`}
                        type="text"
                        autoComplete="organization"
                        className={inputClass}
                        value={fields.organization}
                        disabled={sending}
                        aria-invalid={Boolean(errors.organization)}
                        onChange={(event) => update('organization', event.target.value)}
                    />
                </FieldShell>
                <FieldShell
                    field={rowField('details', DETAILS_LABEL[kind])}
                    htmlFor={`${idPrefix}-details`}
                    error={errors.details}
                    width="full"
                >
                    <textarea
                        id={`${idPrefix}-details`}
                        rows={6}
                        autoComplete="off"
                        className={clsx(inputClass, 'resize-y leading-relaxed')}
                        placeholder={DETAILS_PLACEHOLDER[kind]}
                        value={fields.details}
                        disabled={sending}
                        aria-invalid={Boolean(errors.details)}
                        onChange={(event) => update('details', event.target.value)}
                    />
                </FieldShell>

                <div className="admin-field py-3" data-field-width="wide">
                    <div className="admin-field-heading" aria-hidden="true" />
                    <div className="admin-field-control min-w-0 space-y-2">
                        <GlassButton type="submit" variant="primary" size="md" disabled={sending}>
                            {sending ? (
                                <Loader2 size={15} aria-hidden="true" className="animate-spin" />
                            ) : (
                                <Mail size={15} aria-hidden="true" />
                            )}
                            {sending ? 'Preparing draft…' : SUBMIT_LABEL[kind]}
                        </GlassButton>

                        <div aria-live="polite">
                            {result?.ok === true ? (
                                <p className="flex items-start gap-1.5 text-xs leading-relaxed text-text-2">
                                    <CheckCircle2 size={13} aria-hidden="true" className="mt-0.5 shrink-0 text-ok" />
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
                                <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-danger">
                                    <AlertCircle size={13} aria-hidden="true" className="mt-0.5 shrink-0" />
                                    {result.message}
                                </p>
                            ) : null}
                        </div>
                    </div>
                </div>
            </div>
        </form>
    );
}
