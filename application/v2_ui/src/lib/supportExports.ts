// supportExports.ts
// Shared, transport-free contracts for support exports and owner consent.

export const SUPPORT_EXPORT_ROOT = '/api/admin/support-exports';
export const SUPPORT_CONSENT_ROOT = '/api/support-export-consents';
export const SUPPORT_SOURCES = ['telemetry', 'activity', 'file_processing', 'console'] as const;
export type SupportSource = (typeof SUPPORT_SOURCES)[number];
export const SUPPORT_SOURCE_LABELS: Record<SupportSource, string> = {
    telemetry: 'Application Insights telemetry',
    activity: 'Activity and audit logs',
    file_processing: 'File-processing diagnostics',
    console: 'App Service console logs',
};

export interface SupportConfiguration {
    cloud: 'public' | 'usgovernment';
    app_resource_id: string;
    site_resource_id: string;
}

export interface SupportReadiness {
    configuration: SupportConfiguration;
    sources: Record<SupportSource, { available: boolean; message: string; access?: string }>;
    storage: { available: boolean; message: string };
    model: { available: boolean; label?: string; provider?: string; message?: string };
    warnings: string[];
}

export interface SupportPerson { id: string; name: string; email: string }
export interface SupportPage<T> { items: T[]; next: string | null }
export interface SupportConversation {
    id: string;
    kind: string;
    first_activity: string | null;
    last_activity: string | null;
    message_count: number | null;
    transcript_eligible: boolean;
}

export interface SupportRequest {
    all_users: boolean;
    user_id: string;
    conversation_ids: string[];
    mode: 'time' | 'conversations';
    start?: string;
    end?: string;
    before_minutes: number;
    after_minutes: number;
    sources: SupportSource[];
    include_system_context: boolean;
    include_transcripts: boolean;
    privacy: 'deterministic' | 'ai';
    purpose: string;
}

export interface SupportForm extends Omit<SupportRequest, 'before_minutes' | 'after_minutes' | 'start' | 'end'> {
    start: string;
    end: string;
    before_minutes: string;
    after_minutes: string;
    narrow_range: boolean;
}

export interface SupportReview {
    review_id: string;
    request: SupportRequest;
    intervals: string[][];
    conversations: SupportConversation[];
    expires_at: string;
    model_label: string;
    warnings: string[];
}

export interface SupportJob {
    id: string;
    status: string;
    phase: string;
    created_at: string;
    expires_at: string;
    plan: SupportRequest;
    intervals: string[][];
    counts?: Record<string, number>;
    privacy_report?: unknown;
    error?: { code: string; message: string };
    can_download: boolean;
}

export interface SupportConsent {
    id: string;
    job_id: string;
    requester_id: string;
    status: string;
    purpose: string;
    created_at: string;
    expires_at: string;
    source_cutoff: string;
    conversations: SupportConversation[];
    privacy: 'deterministic' | 'ai';
    model_label: string;
    scope_notice: string;
    expired: boolean;
}

export function supportLocalTime(value: Date): string {
    const pad = (part: number) => String(part).padStart(2, '0');
    return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

export function supportDefaults(now = new Date()): SupportForm {
    return {
        all_users: false, user_id: '', conversation_ids: [], mode: 'time',
        start: supportLocalTime(new Date(now.getTime() - 3_600_000)), end: supportLocalTime(now),
        before_minutes: '15', after_minutes: '15', narrow_range: false,
        sources: ['telemetry', 'activity'], include_system_context: false,
        include_transcripts: false, privacy: 'deterministic', purpose: 'Troubleshoot a SimpleChat issue.',
    };
}

function toUtc(value: string): string {
    const date = new Date(value);
    if (!value || Number.isNaN(date.getTime()) || supportLocalTime(date) !== value.slice(0, 16)) {
        throw new Error('Choose a valid local date and time. A daylight-saving gap is not a valid time.');
    }
    for (const shift of [-86_400_000, 86_400_000]) {
        const offset = new Date(date.getTime() + shift).getTimezoneOffset() - date.getTimezoneOffset();
        if (offset && supportLocalTime(new Date(date.getTime() + offset * 60_000)) === value.slice(0, 16)) {
            throw new Error('This local time repeats during a clock change. Choose unambiguous endpoints spanning the change.');
        }
    }
    return date.toISOString();
}

export function buildSupportRequest(form: SupportForm): SupportRequest {
    if (!form.all_users && !form.user_id) throw new Error('Select one SimpleChat user or explicitly choose all users.');
    if (!form.sources.length) throw new Error('Select at least one log source.');
    if (form.conversation_ids.length > 20) throw new Error('Select at most 20 conversations.');
    if ((form.mode === 'conversations' || form.include_transcripts) && !form.conversation_ids.length) {
        throw new Error('Select at least one conversation.');
    }
    if (form.all_users && (form.conversation_ids.length || form.include_transcripts)) {
        throw new Error('All-users exports cannot include selected conversations or transcripts.');
    }
    if (form.sources.includes('console') && !form.all_users && !form.include_system_context) {
        throw new Error('For one user, console logs require the nearby system context option.');
    }
    const before = Number(form.before_minutes);
    const after = Number(form.after_minutes);
    if (![before, after].every((value) => Number.isInteger(value) && value >= 0 && value <= 1440)
        || !form.before_minutes.trim() || !form.after_minutes.trim()) {
        throw new Error('Before/after margins must be whole minutes from 0 to 1440.');
    }
    const { narrow_range: _narrow, ...rest } = form;
    const request: SupportRequest = {
        ...rest, before_minutes: before, after_minutes: after,
        conversation_ids: [...new Set(form.conversation_ids)].sort(),
        sources: [...new Set(form.sources)],
    };
    if (form.mode === 'time' || form.narrow_range) {
        request.start = toUtc(form.start);
        request.end = toUtc(form.end);
        const duration = Date.parse(request.end) - Date.parse(request.start);
        if (duration <= 0 || duration > 7 * 86_400_000) throw new Error('Choose a time range longer than zero and at most 7 days.');
    } else {
        delete request.start;
        delete request.end;
    }
    return request;
}

export function supportExportPath(id: string, action: '' | 'preview' | 'download' | 'cancel' = ''): string {
    return `${SUPPORT_EXPORT_ROOT}/${encodeURIComponent(id)}${action ? `/${action}` : ''}`;
}

export function supportConsentPath(id: string, action: '' | 'preview' | 'decision' = ''): string {
    return `${SUPPORT_CONSENT_ROOT}/${encodeURIComponent(id)}${action ? `/${action}` : ''}`;
}

export function supportJobActive(status: string): boolean {
    return ['waiting_for_consent', 'queued', 'collecting', 'redacting', 'ai_review'].includes(status);
}
