// ReleaseNotificationsBadge.tsx
// Registered / Unregistered, beside the version, and the registration behind it.
//
// The classic page shows whether this deployment is registered for SimpleChat release
// updates and community call notifications as a badge next to the version number, because
// that is where an administrator checking for a new release is already looking. Choosing it
// opens the registration: read-only once registered, with an edit step, and a form until
// then. Submitting saves the details through the classic endpoint, which also records the
// registration in the activity log, and opens a prefilled email draft to the product team.
//
// The registration is written straight to the settings document rather than through the
// page's draft, so the page is told the new values and keeps its copy current.

import { useState, type FormEvent } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, BellPlus, CheckCircle2, Loader2, Send, TriangleAlert } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { asBoolean, asString, type AdminField } from '../../lib/adminFields';
import {
    formatRegistrationTime,
    isPlausibleEmail,
    registrationDraftBody,
    safeMailtoHref,
    type RegistrationResponse,
} from '../../lib/supportFeedback';
import { toast } from '../../stores/toastStore';
import type { Json } from '../../lib/types';
import { AdminModal } from './AdminModal';
import { FieldShell, inputClass } from './fields';
import { GlassButton } from '../ui/primitives';

interface RegistrationFields {
    name: string;
    email: string;
    organization: string;
}

function rowField(key: string, label: string): AdminField {
    return { key, type: 'text', label };
}

export function ReleaseNotificationsBadge({
    settings,
    defaultName,
    defaultEmail,
    appVersion,
    onRegistered,
}: {
    settings: Json;
    defaultName: string;
    defaultEmail: string;
    appVersion: string;
    /** Receives the stored keys the registration just wrote. */
    onRegistered: (updates: Json) => void;
}) {
    const registered = asBoolean(settings.release_notifications_registered);
    const stored: RegistrationFields = {
        name: asString(settings.release_notifications_name),
        email: asString(settings.release_notifications_email),
        organization: asString(settings.release_notifications_org),
    };

    const [open, setOpen] = useState(false);
    const [editing, setEditing] = useState(false);
    const [fields, setFields] = useState<RegistrationFields>(stored);
    const [errors, setErrors] = useState<Partial<Record<keyof RegistrationFields, string>>>({});
    const [sending, setSending] = useState(false);
    const [result, setResult] = useState<
        | { ok: true; recipient: string; subject: string; body: string }
        | { ok: false; message: string }
        | null
    >(null);

    const begin = () => {
        // A first registration starts from the signed-in administrator, as the classic
        // page does; an existing one starts from what is stored.
        setFields({
            name: stored.name || defaultName,
            email: stored.email || defaultEmail,
            organization: stored.organization,
        });
        setErrors({});
        setResult(null);
        setEditing(!registered);
        setOpen(true);
    };

    const close = () => {
        setOpen(false);
        setEditing(false);
    };

    const update = (key: keyof RegistrationFields, next: string) => {
        setFields((current) => ({ ...current, [key]: next }));
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
        const problems: Partial<Record<keyof RegistrationFields, string>> = {};
        if (!fields.name.trim()) {
            problems.name = 'Enter your name.';
        }
        if (!fields.email.trim()) {
            problems.email = 'Enter your email address.';
        } else if (!isPlausibleEmail(fields.email)) {
            problems.email = 'Enter a valid email address.';
        }
        if (!fields.organization.trim()) {
            problems.organization = 'Enter your organization.';
        }
        setErrors(problems);
        if (Object.keys(problems).length) {
            setResult({ ok: false, message: 'Complete the highlighted fields to register.' });
            return;
        }

        setSending(true);
        setResult(null);
        try {
            const name = fields.name.trim();
            const email = fields.email.trim();
            const organization = fields.organization.trim();
            const response = await api.post<RegistrationResponse>(
                '/api/admin/settings/release_notifications_registration',
                { name, email, organization },
            );
            const registeredAt = response.registeredAt || asString(settings.release_notifications_registered_at);
            onRegistered({
                release_notifications_registered: true,
                release_notifications_name: name,
                release_notifications_email: email,
                release_notifications_org: organization,
                release_notifications_registered_at: registeredAt,
                release_notifications_updated_at:
                    response.updatedAt || asString(settings.release_notifications_updated_at),
            });

            const body = registrationDraftBody({ name, email, organization, appVersion, registeredAt });
            const draftHref = safeMailtoHref(response.recipientEmail, response.subjectLine, body);
            setEditing(false);
            if (!draftHref) {
                setResult({
                    ok: false,
                    message: 'Registration saved, but the server returned a recipient that is not a valid email address.',
                });
                return;
            }
            setResult({ ok: true, recipient: response.recipientEmail, subject: response.subjectLine, body });
            toast.success('Release notifications registration saved.');
            window.location.href = draftHref;
        } catch (error) {
            setResult({
                ok: false,
                message:
                    error instanceof Error && error.message
                        ? error.message
                        : 'Unable to prepare the registration email draft.',
            });
        } finally {
            setSending(false);
        }
    };

    const formId = 'release-notifications-form';

    return (
        <>
            <button
                type="button"
                onClick={begin}
                aria-haspopup="dialog"
                title="Release and community call notifications for this deployment"
                className={clsx(
                    'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors',
                    'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
                    registered
                        ? 'border-ok/40 bg-ok-soft text-ok hover:bg-ok/15'
                        : 'border-edge bg-surface-2 text-text-2 hover:border-accent hover:text-text-1',
                )}
            >
                {registered ? (
                    <CheckCircle2 size={12} aria-hidden="true" />
                ) : (
                    <BellPlus size={12} aria-hidden="true" />
                )}
                {registered ? 'Registered' : 'Unregistered'}
                <span className="sr-only"> for release notifications</span>
            </button>

            {open ? (
                <AdminModal
                    title="Release notifications"
                    description="Latest release updates and community call notifications for this deployment."
                    onClose={close}
                    footer={
                        editing ? (
                            <>
                                <GlassButton
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    disabled={sending}
                                    onClick={() => {
                                        if (registered) {
                                            setEditing(false);
                                            setErrors({});
                                            setResult(null);
                                        } else {
                                            close();
                                        }
                                    }}
                                >
                                    Cancel
                                </GlassButton>
                                <GlassButton type="submit" form={formId} variant="primary" size="sm" disabled={sending}>
                                    {sending ? (
                                        <Loader2 size={14} aria-hidden="true" className="animate-spin" />
                                    ) : (
                                        <Send size={14} aria-hidden="true" />
                                    )}
                                    {sending ? 'Registering…' : 'Submit registration'}
                                </GlassButton>
                            </>
                        ) : (
                            <>
                                <GlassButton type="button" variant="ghost" size="sm" onClick={close}>
                                    Close
                                </GlassButton>
                                <GlassButton
                                    type="button"
                                    variant="subtle"
                                    size="sm"
                                    onClick={() => {
                                        setEditing(true);
                                        setResult(null);
                                    }}
                                >
                                    Edit registration
                                </GlassButton>
                            </>
                        )
                    }
                >
                    {editing ? (
                        <form id={formId} noValidate onSubmit={(event) => void submit(event)}>
                            <p className="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-xs leading-relaxed text-warn">
                                <TriangleAlert size={13} aria-hidden="true" className="mt-0.5 shrink-0" />
                                <span>
                                    Submitting saves these details in Admin Settings and opens a
                                    prefilled email draft to simplechat@microsoft.com.
                                </span>
                            </p>
                            <FieldShell field={rowField('name', 'Your Name')} htmlFor="release-notifications-name" error={errors.name}>
                                <input
                                    id="release-notifications-name"
                                    type="text"
                                    autoComplete="name"
                                    className={inputClass}
                                    value={fields.name}
                                    disabled={sending}
                                    aria-invalid={Boolean(errors.name)}
                                    onChange={(event) => update('name', event.target.value)}
                                />
                            </FieldShell>
                            <FieldShell field={rowField('email', 'Email')} htmlFor="release-notifications-email" error={errors.email}>
                                <input
                                    id="release-notifications-email"
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
                                htmlFor="release-notifications-organization"
                                error={errors.organization}
                            >
                                <input
                                    id="release-notifications-organization"
                                    type="text"
                                    autoComplete="organization"
                                    className={inputClass}
                                    value={fields.organization}
                                    disabled={sending}
                                    aria-invalid={Boolean(errors.organization)}
                                    onChange={(event) => update('organization', event.target.value)}
                                />
                            </FieldShell>
                        </form>
                    ) : (
                        <div>
                            <p className="flex items-start gap-2 rounded-lg border border-ok/40 bg-ok/5 px-3 py-2 text-xs leading-relaxed text-text-2">
                                <CheckCircle2 size={13} aria-hidden="true" className="mt-0.5 shrink-0 text-ok" />
                                <span>
                                    This deployment is registered for release updates and community
                                    call notifications.
                                </span>
                            </p>
                            <dl className="mt-3 grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-4 gap-y-2 text-sm">
                                <dt className="text-text-3">Name</dt>
                                <dd className="min-w-0 text-text-1">{asString(settings.release_notifications_name) || '-'}</dd>
                                <dt className="text-text-3">Email</dt>
                                <dd className="min-w-0 text-text-1">{asString(settings.release_notifications_email) || '-'}</dd>
                                <dt className="text-text-3">Organization</dt>
                                <dd className="min-w-0 text-text-1">{asString(settings.release_notifications_org) || '-'}</dd>
                                <dt className="text-text-3">Registered</dt>
                                <dd className="min-w-0 text-text-1">
                                    {formatRegistrationTime(settings.release_notifications_registered_at)}
                                </dd>
                                <dt className="text-text-3">Last updated</dt>
                                <dd className="min-w-0 text-text-1">
                                    {formatRegistrationTime(settings.release_notifications_updated_at)}
                                </dd>
                            </dl>
                        </div>
                    )}

                    <div aria-live="polite" className="mt-3">
                        {result?.ok === true ? (
                            <p className="flex items-start gap-1.5 text-xs leading-relaxed text-text-2">
                                <CheckCircle2 size={13} aria-hidden="true" className="mt-0.5 shrink-0 text-ok" />
                                <span>
                                    Registration saved. If your mail app did not open,{' '}
                                    <a
                                        href={safeMailtoHref(result.recipient, result.subject, result.body)}
                                        className="font-medium text-accent underline"
                                    >
                                        open the draft to {result.recipient}
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
                </AdminModal>
            ) : null}
        </>
    );
}
