// supportFeedback.ts
// The email drafts the Help group and the Support menu prepare: feedback for the SimpleChat
// team from administrators, feedback for the organisation's own support mailbox from users,
// and the release notifications registration.
//
// All follow the classic pages. The server records the intent and returns the recipient
// and subject line, then the browser opens a text-only mailto: draft in the local mail app.
// Building the draft lives here so its wording can be tested, and so the only way to a
// mailto: URL is one that refuses anything but a single plain address.

export type FeedbackKind = 'bug_report' | 'feature_request';

/** Where the Support menu's Send Feedback page posts; the server owns the recipient. */
export const SUPPORT_FEEDBACK_ENDPOINT = '/api/support/send_feedback_email';

export const FEEDBACK_LABELS: Readonly<Record<FeedbackKind, string>> = {
    bug_report: 'Bug Report',
    feature_request: 'Feature Request',
};

/** What a reporter types into a Send Feedback card. */
export interface FeedbackFields {
    name: string;
    email: string;
    organization: string;
    details: string;
}

/** `POST /api/admin/settings/send_feedback_email` and `POST /api/support/send_feedback_email`. */
export interface FeedbackResponse {
    success: boolean;
    recipientEmail: string;
    subjectLine: string;
    feedbackLabel?: string;
}

/** `POST /api/admin/settings/release_notifications_registration`. */
export interface RegistrationResponse {
    success: boolean;
    recipientEmail: string;
    subjectLine: string;
    registered: boolean;
    registeredAt?: string;
    updatedAt?: string;
}

/**
 * One plain address: letters, digits and the punctuation real addresses use, then a
 * dotted domain. No display name, no second recipient, and none of the characters a
 * mailto: URL would read as the start of its headers or fragment.
 */
const MAIL_ADDRESS = /^[A-Za-z0-9._+'-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*$/;

/** Whether a typed address is worth sending. The server's own check is looser. */
export function isPlausibleEmail(value: string): boolean {
    return MAIL_ADDRESS.test(value.trim());
}

/** Build a mailto: draft, or undefined when the recipient is not one plain address. */
export function safeMailtoHref(recipient: string, subject: string, body: string): string | undefined {
    const address = recipient.trim();
    if (!MAIL_ADDRESS.test(address)) {
        return undefined;
    }
    return `mailto:${address}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

/** Which required feedback fields are still empty or invalid, keyed by field. */
export function validateFeedbackFields(fields: FeedbackFields): Partial<Record<keyof FeedbackFields, string>> {
    const errors: Partial<Record<keyof FeedbackFields, string>> = {};
    if (!fields.name.trim()) {
        errors.name = 'Enter your name.';
    }
    if (!fields.email.trim()) {
        errors.email = 'Enter your email address.';
    } else if (!isPlausibleEmail(fields.email)) {
        errors.email = 'Enter a valid email address.';
    }
    if (!fields.organization.trim()) {
        errors.organization = 'Enter your organization.';
    }
    if (!fields.details.trim()) {
        errors.details = 'Describe the feedback.';
    }
    return errors;
}

/** The body of a feedback draft, worded as the classic page words it. */
export function feedbackDraftBody(kind: FeedbackKind, fields: FeedbackFields, appVersion: string): string {
    return [
        `Feedback Type: ${FEEDBACK_LABELS[kind]}`,
        `Name: ${fields.name.trim()}`,
        `Email: ${fields.email.trim()}`,
        `Organization: ${fields.organization.trim()}`,
        `App Version: ${appVersion || 'Unknown'}`,
        '',
        'Details:',
        fields.details.trim(),
    ].join('\n');
}

/** The body of a registration draft, worded as the classic page words it. */
export function registrationDraftBody({
    name,
    email,
    organization,
    appVersion,
    registeredAt,
}: {
    name: string;
    email: string;
    organization: string;
    appVersion: string;
    registeredAt?: string;
}): string {
    return [
        'Registration submission to receive the latest release updates and community call notifications.',
        '',
        `Name: ${name.trim()}`,
        `Email: ${email.trim()}`,
        `Organization: ${organization.trim()}`,
        `App Version: ${appVersion || 'Unknown'}`,
        `Registered At: ${registeredAt || 'Pending'}`,
    ].join('\n');
}

/** A stored ISO timestamp in the reader's locale, or a dash when there is none. */
export function formatRegistrationTime(value: unknown): string {
    if (typeof value !== 'string' || !value.trim()) {
        return '-';
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}
