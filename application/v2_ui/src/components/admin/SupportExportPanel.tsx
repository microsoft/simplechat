// SupportExportPanel.tsx

import { useEffect, useRef, useState } from 'react';
import { api, apiUrl, CREDENTIALS_MODE } from '../../lib/apiClient';
import { saveBlob } from '../../lib/endpoints';
import {
    SUPPORT_EXPORT_ROOT, SUPPORT_SOURCE_LABELS, SUPPORT_SOURCES, buildSupportRequest,
    supportDefaults, supportExportPath, supportJobActive,
    type SupportConfiguration, type SupportConversation, type SupportForm, type SupportJob,
    type SupportPage, type SupportPerson, type SupportReadiness, type SupportRequest, type SupportReview,
} from '../../lib/supportExports';
import { v2ApiFetch } from '../../lib/v2SourcePolicy';
import { Notice, StatusBadge } from '../approvals/ApprovalParts';
import { GlassButton } from '../ui/primitives';
import { inputClass } from './fields';

const configFields = [
    ['app_resource_id', 'Application Insights resource ID'],
    ['site_resource_id', 'App Service resource ID (optional console source)'],
] as const;

function message(error: unknown): string {
    return error instanceof Error ? error.message : 'The support export operation failed.';
}

export function SupportExportPanel() {
    const [readiness, setReadiness] = useState<SupportReadiness | null>(null);
    const [configuration, setConfiguration] = useState<SupportConfiguration | null>(null);
    const [form, setForm] = useState<SupportForm>(() => supportDefaults());
    const [people, setPeople] = useState<SupportPerson[]>([]);
    const [peopleNext, setPeopleNext] = useState<string | null>(null);
    const [search, setSearch] = useState('');
    const [conversationSearch, setConversationSearch] = useState('');
    const [conversations, setConversations] = useState<SupportConversation[]>([]);
    const [conversationNext, setConversationNext] = useState<string | null>(null);
    const [selected, setSelected] = useState<SupportConversation[]>([]);
    const [jobs, setJobs] = useState<SupportJob[]>([]);
    const [jobsNext, setJobsNext] = useState<string | null>(null);
    const [job, setJob] = useState<SupportJob | null>(null);
    const [review, setReview] = useState<{ scope: SupportReview; request: SupportRequest } | null>(null);
    const [reviewAcknowledged, setReviewAcknowledged] = useState(false);
    const [preview, setPreview] = useState<unknown>(null);
    const [downloadAcknowledged, setDownloadAcknowledged] = useState(false);
    const [busy, setBusy] = useState(false);
    const [loadingConversations, setLoadingConversations] = useState(false);
    const [polling, setPolling] = useState(true);
    const [error, setError] = useState('');
    const reviewHeading = useRef<HTMLHeadingElement>(null);
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

    const run = async (operation: () => Promise<void>) => {
        setBusy(true);
        setError('');
        try { await operation(); } catch (failure) { setError(message(failure)); } finally { setBusy(false); }
    };
    const rememberJob = (item: SupportJob) => {
        setJob(item);
        setJobs((current) => [item, ...current.filter((other) => other.id !== item.id)]);
        setPreview(null);
        setDownloadAcknowledged(false);
        setPolling(true);
    };

    useEffect(() => {
        const controller = new AbortController();
        Promise.all([
            api.get<SupportReadiness>(`${SUPPORT_EXPORT_ROOT}/readiness`, controller.signal),
            api.get<SupportPage<SupportJob>>(SUPPORT_EXPORT_ROOT, controller.signal),
        ]).then(([ready, page]) => {
            setReadiness(ready); setConfiguration(ready.configuration); setJobs(page.items); setJobsNext(page.next);
            const latest = [...page.items].sort((a, b) => b.created_at.localeCompare(a.created_at));
            setJob(latest.find((item) => supportJobActive(item.status)) ?? latest[0] ?? null);
        }).catch((failure) => { if (!controller.signal.aborted) setError(message(failure)); });
        return () => controller.abort();
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        const timer = setTimeout(() => {
            const query = new URLSearchParams({ q: search });
            api.get<SupportPage<SupportPerson>>(`${SUPPORT_EXPORT_ROOT}/users?${query}`, controller.signal)
                .then((page) => { setPeople(page.items); setPeopleNext(page.next); })
                .catch((failure) => { if (!controller.signal.aborted) setError(message(failure)); });
        }, 200);
        return () => { clearTimeout(timer); controller.abort(); };
    }, [search]);

    useEffect(() => {
        if (!form.user_id || form.all_users) return;
        const controller = new AbortController();
        setLoadingConversations(true);
        const query = new URLSearchParams({ user_id: form.user_id, q: conversationSearch });
        api.get<SupportPage<SupportConversation>>(`${SUPPORT_EXPORT_ROOT}/conversations?${query}`, controller.signal)
            .then((page) => { setConversations(page.items); setConversationNext(page.next); })
            .catch((failure) => { if (!controller.signal.aborted) setError(message(failure)); })
            .finally(() => { if (!controller.signal.aborted) setLoadingConversations(false); });
        return () => controller.abort();
    }, [form.user_id, form.all_users, conversationSearch]);

    useEffect(() => {
        if (!job || !supportJobActive(job.status) || !polling) return;
        const controller = new AbortController();
        const timer = setInterval(() => {
            api.get<SupportJob>(supportExportPath(job.id), controller.signal).then((updated) => {
                setJob(updated); setJobs((current) => current.map((item) => item.id === updated.id ? updated : item));
            }).catch((failure) => {
                if (!controller.signal.aborted) { setError(message(failure)); setPolling(false); }
            });
        }, 5000);
        return () => { clearInterval(timer); controller.abort(); };
    }, [job?.id, job?.status, polling]);

    const changeUser = (id: string, allUsers: boolean) => {
        setForm((current) => ({
            ...current, user_id: id, all_users: allUsers, conversation_ids: [], include_transcripts: false,
            mode: allUsers ? 'time' : current.mode,
        }));
        setSelected([]); setConversations([]); setConversationNext(null); setConversationSearch('');
    };
    const chooseConversation = (item: SupportConversation, checked: boolean) => {
        const next = checked ? [...selected, item] : selected.filter((other) => other.id !== item.id);
        setSelected(next);
        setForm((current) => ({
            ...current, conversation_ids: next.map((other) => other.id),
            include_transcripts: current.include_transcripts && next.length > 0 && next.every((other) => other.transcript_eligible),
        }));
    };
    const refreshReadiness = async () => {
        const ready = await api.get<SupportReadiness>(`${SUPPORT_EXPORT_ROOT}/readiness`);
        setReadiness(ready); setConfiguration(ready.configuration); setReview(null);
    };

    return (
        <div className="min-w-0 space-y-6" data-testid="support-export-panel" aria-busy={busy}>
            <p className="max-w-prose text-sm text-text-2">
                Collect retained diagnostics for a support case. Nothing is sent to the development team automatically.
                These actions run separately from Save settings.
            </p>
            {error ? <Notice tone="danger">{error}</Notice> : null}
            <details className="rounded-xl border border-edge p-3">
                <summary className="cursor-pointer text-sm font-medium text-text-1">Source and storage setup</summary>
                {configuration ? <div className="mt-4 space-y-3">
                    <label className="block text-sm">Azure cloud
                        <select aria-label="Support export Azure cloud" className={`${inputClass} mt-1 w-full`} value={configuration.cloud}
                            disabled={busy} onChange={(event) => setConfiguration({ ...configuration, cloud: event.target.value as SupportConfiguration['cloud'] })}>
                            <option value="public">Azure Commercial</option><option value="usgovernment">Azure US Government</option>
                        </select>
                    </label>
                    {configFields.map(([key, label]) => <label key={key} className="block text-sm">{label}
                        <input className={`${inputClass} mt-1 w-full`} aria-label={label} value={configuration[key]} disabled={busy}
                            onChange={(event) => setConfiguration({ ...configuration, [key]: event.target.value })} />
                    </label>)}
                    <p className="text-sm text-text-2">Queries use Azure Monitor resource context. Give the application identity read access to these resources; the connected workspace must allow resource permissions. The ingestion connection string does not grant query access.</p>
                    <p className="text-sm text-text-2">{readiness?.storage.message}</p>
                    <div className="flex flex-wrap gap-2">
                        <GlassButton type="button" variant="subtle" disabled={busy} onClick={() => void run(async () => {
                            await api.post(`${SUPPORT_EXPORT_ROOT}/configuration`, configuration); await refreshReadiness();
                        })}>Save export configuration</GlassButton>
                        <GlassButton type="button" variant="subtle" disabled={busy} onClick={() => void run(async () => {
                            const ready = await api.post<SupportReadiness>(`${SUPPORT_EXPORT_ROOT}/initialize-storage`, { confirmed: true }); setReadiness(ready);
                        })}>Initialize private export storage</GlassButton>
                        <GlassButton type="button" variant="subtle" disabled={busy} onClick={() => void run(async () => {
                            setReadiness(await api.post<SupportReadiness>(`${SUPPORT_EXPORT_ROOT}/test-sources`, {}));
                        })}>Test source access</GlassButton>
                    </div>
                </div> : <p className="mt-3 text-sm text-text-2">Source setup could not be loaded.</p>}
            </details>

            <fieldset disabled={busy || review !== null} className="min-w-0 space-y-5">
                <legend className="text-base font-semibold">Choose diagnostic scope</legend>
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.all_users}
                    onChange={(event) => changeUser('', event.target.checked)} />All users (explicitly include deployment-wide activity)</label>
                {!form.all_users ? <div className="grid gap-3 sm:grid-cols-2">
                    <label className="block text-sm">Find a SimpleChat user
                        <input type="search" className={`${inputClass} mt-1 w-full`} value={search}
                            onChange={(event) => { setSearch(event.target.value); changeUser('', false); }} />
                    </label>
                    <label className="block text-sm">Selected user
                        <select aria-label="Selected user" className={`${inputClass} mt-1 w-full`} value={form.user_id} onChange={(event) => changeUser(event.target.value, false)}>
                            <option value="">Select a user</option>
                            {people.map((person) => <option key={person.id} value={person.id}>{person.name} {person.email ? `(${person.email})` : ''}</option>)}
                        </select>
                    </label>
                    {peopleNext ? <GlassButton type="button" variant="subtle" onClick={() => void run(async () => {
                        const page = await api.get<SupportPage<SupportPerson>>(`${SUPPORT_EXPORT_ROOT}/users?${new URLSearchParams({ q: search, after: peopleNext })}`);
                        setPeople((current) => [...current, ...page.items.filter((item) => !current.some((other) => other.id === item.id))]); setPeopleNext(page.next);
                    })}>Load more users</GlassButton> : null}
                </div> : null}

                <label className="block text-sm">Collection mode
                    <select aria-label="Collection mode" className={`${inputClass} mt-1 w-full`} value={form.mode} onChange={(event) => setForm({ ...form, mode: event.target.value as SupportForm['mode'] })}>
                        <option value="time">Time-based</option><option value="conversations" disabled={form.all_users}>Conversation windows</option>
                    </select>
                </label>
                {form.mode === 'conversations' ? <div className="space-y-3">
                    <div className="grid grid-cols-2 gap-3">
                        <label className="text-sm">Minutes before<input type="number" min={0} max={1440} step={1} className={`${inputClass} mt-1 w-full`}
                            value={form.before_minutes} onChange={(event) => setForm({ ...form, before_minutes: event.target.value })} /></label>
                        <label className="text-sm">Minutes after<input type="number" min={0} max={1440} step={1} className={`${inputClass} mt-1 w-full`}
                            value={form.after_minutes} onChange={(event) => setForm({ ...form, after_minutes: event.target.value })} /></label>
                    </div>
                    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.narrow_range}
                        onChange={(event) => setForm({ ...form, narrow_range: event.target.checked })} />Also narrow conversation windows to an explicit time range</label>
                </div> : null}
                {(form.mode === 'time' || form.narrow_range) ? <div className="grid gap-3 sm:grid-cols-2">
                    <label className="text-sm">Start time<input type="datetime-local" className={`${inputClass} mt-1 w-full`} value={form.start}
                        onChange={(event) => setForm({ ...form, start: event.target.value })} /></label>
                    <label className="text-sm">End time<input type="datetime-local" className={`${inputClass} mt-1 w-full`} value={form.end}
                        onChange={(event) => setForm({ ...form, end: event.target.value })} /></label>
                </div> : null}
                <p className="text-xs text-text-2">Input timezone: {timezone}. Review shows exact UTC intervals. Maximum effective span: 7 days.</p>

                {!form.all_users && form.user_id ? <div className="space-y-3">
                    <label className="block text-sm">Find conversation ID
                        <input type="search" className={`${inputClass} mt-1 w-full`} value={conversationSearch}
                            onChange={(event) => setConversationSearch(event.target.value)} />
                    </label>
                    <p className="text-xs text-text-2">Metadata only: messages and sensitive titles are not available to admins without transcript consent. Selected: {selected.length}/20.</p>
                    {loadingConversations ? <p role="status" className="text-sm">Loading conversations...</p> : null}
                    <ul className="max-h-60 space-y-2 overflow-auto text-sm" aria-label="Available conversations">
                        {conversations.map((item) => <li key={item.id}>
                            <label className="flex items-start gap-2">
                                <input type="checkbox" checked={selected.some((other) => other.id === item.id)}
                                    disabled={selected.length >= 20 && !selected.some((other) => other.id === item.id)}
                                    onChange={(event) => chooseConversation(item, event.target.checked)} />
                                <span className="min-w-0 break-all">{item.id} <span className="text-text-2">({item.kind}; last activity {item.last_activity ?? 'unknown'})</span></span>
                            </label>
                        </li>)}
                    </ul>
                    {!loadingConversations && !conversations.length ? <p className="text-sm text-text-2">No conversations match this user and ID search.</p> : null}
                    {selected.length ? <div className="space-y-1 text-sm"><p className="font-medium">Selected conversation IDs</p>
                        {selected.map((item) => <div key={item.id} className="flex flex-wrap items-center gap-2"><span className="break-all">{item.id}</span>
                            <GlassButton type="button" size="sm" onClick={() => chooseConversation(item, false)}>Remove {item.id}</GlassButton></div>)}
                    </div> : null}
                    {conversationNext ? <GlassButton type="button" variant="subtle" onClick={() => void run(async () => {
                        const page = await api.get<SupportPage<SupportConversation>>(`${SUPPORT_EXPORT_ROOT}/conversations?${new URLSearchParams({ user_id: form.user_id, q: conversationSearch, after: conversationNext })}`);
                        setConversations((current) => [...current, ...page.items.filter((item) => !current.some((other) => other.id === item.id))]); setConversationNext(page.next);
                    })}>Load more conversations</GlassButton> : null}
                </div> : null}

                <fieldset className="space-y-2">
                    <legend className="mb-2 text-sm font-semibold">Log sources</legend>
                    {SUPPORT_SOURCES.map((source) => <label key={source} className="flex items-start gap-2 text-sm">
                        <input type="checkbox" checked={form.sources.includes(source)} onChange={(event) => setForm({
                            ...form, sources: event.target.checked ? [...form.sources, source] : form.sources.filter((other) => other !== source),
                        })} /><span>{SUPPORT_SOURCE_LABELS[source]}<span className="block text-xs text-text-2">{readiness?.sources[source].message ?? 'Readiness not loaded'}
                            {readiness?.sources[source].access ? ` Access: ${readiness.sources[source].access}.` : ''}</span></span>
                    </label>)}
                    <p className="text-xs text-text-2">Explicitly deselect unavailable sources. Historical console output is not recoverable unless Azure already collected it.</p>
                    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.include_system_context}
                        onChange={(event) => setForm({ ...form, include_system_context: event.target.checked })} />Include nearby unscoped system context (may include unrelated activity)</label>
                </fieldset>

                <fieldset className="space-y-3">
                    <legend className="mb-2 text-sm font-semibold">Privacy and optional transcripts</legend>
                    <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={form.include_transcripts}
                        disabled={!selected.length || selected.some((item) => !item.transcript_eligible)}
                        onChange={(event) => setForm({ ...form, include_transcripts: event.target.checked })} />
                        Request whole personal-conversation snapshots with explicit owner approval</label>
                    <p className="text-xs text-text-2">Transcripts are optional, not restricted to the diagnostic time window, and unavailable for shared/group conversations.</p>
                    <label className="block text-sm">Privacy checking<select aria-label="Privacy checking" className={`${inputClass} mt-1 w-full`} value={form.privacy}
                        onChange={(event) => setForm({ ...form, privacy: event.target.value as SupportForm['privacy'] })}>
                        <option value="deterministic">Deterministic credential and PII redaction</option>
                        <option value="ai" disabled={!readiness?.model.available}>Deterministic plus AI privacy inspection</option>
                    </select></label>
                    <p className="text-xs text-text-2">{readiness?.model.message} {readiness?.model.label ? `Default model: ${readiness.model.label} (${readiness.model.provider}).` : ''}</p>
                    {form.privacy === 'ai' ? <Notice tone="warn">Only already-scrubbed data is sent to the configured default model. The complete inspection has a 200,000-input-token budget; oversized or incomplete checks block release.</Notice> : null}
                    <label className="block text-sm">Support purpose<textarea className={`${inputClass} mt-1 w-full`} maxLength={500} rows={2} value={form.purpose}
                        onChange={(event) => setForm({ ...form, purpose: event.target.value })} /></label>
                </fieldset>
                <p className="text-xs text-text-2">Limits: 20 conversations, 100,000 records, 50 MiB uncompressed. Download expires after 24 hours. No raw export or automatic sharing.</p>
                <GlassButton type="button" variant="primary" disabled={!readiness?.storage.available} onClick={() => void run(async () => {
                    const request = buildSupportRequest(form);
                    const scope = await api.post<SupportReview>(`${SUPPORT_EXPORT_ROOT}/review`, request);
                    setReview({ scope, request }); setReviewAcknowledged(false);
                    setTimeout(() => reviewHeading.current?.focus(), 0);
                })}>Review export scope</GlassButton>
                {!readiness?.storage.available ? <p className="text-sm text-warn">Set up private export storage before reviewing a collection request.</p> : null}
            </fieldset>

            {review ? <section className="space-y-3 rounded-xl border border-edge p-4" aria-labelledby="support-scope-review">
                <h3 id="support-scope-review" ref={reviewHeading} tabIndex={-1} className="font-semibold">Review the exact collection scope</h3>
                <p className="text-sm">{review.scope.request.all_users ? 'All users' : `User: ${review.scope.request.user_id}`}</p>
                <ul className="space-y-1 text-sm">{review.scope.intervals.map(([start, end]) => <li key={start} className="break-words">UTC: {start} through {end} (end exclusive)</li>)}</ul>
                <p className="text-sm">Sources: {review.scope.request.sources.map((source) => SUPPORT_SOURCE_LABELS[source]).join(', ')}.</p>
                <p className="text-sm">{review.scope.request.include_transcripts ? 'Whole personal-conversation snapshots will wait for owner consent.' : 'Diagnostic logs only; no transcripts.'}</p>
                <p className="text-sm">Privacy: {review.scope.request.privacy === 'ai' ? `deterministic plus AI (${review.scope.model_label})` : 'deterministic'}.</p>
                <p className="text-xs text-text-2">Review expires {review.scope.expires_at}. Editing the scope requires a new review.</p>
                <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={reviewAcknowledged}
                    onChange={(event) => setReviewAcknowledged(event.target.checked)} />I reviewed the scope and understand privacy checking is best effort; sharing remains manual.</label>
                <div className="flex flex-wrap gap-2">
                    <GlassButton type="button" variant="primary" disabled={busy || !reviewAcknowledged} onClick={() => void run(async () => {
                        const created = await api.post<SupportJob>(SUPPORT_EXPORT_ROOT, {
                            request: review.request, retry_key: review.scope.review_id, review_id: review.scope.review_id,
                        });
                        rememberJob(created); setReview(null);
                    })}>Generate support ZIP</GlassButton>
                    <GlassButton type="button" variant="subtle" disabled={busy} onClick={() => setReview(null)}>Edit scope</GlassButton>
                </div>
            </section> : null}

            <section className="space-y-3 border-t border-edge pt-5" aria-labelledby="support-jobs-heading">
                <h3 id="support-jobs-heading" className="font-semibold">Your support exports</h3>
                {jobs.length ? <label className="block text-sm">Export request<select aria-label="Export request" className={`${inputClass} mt-1 w-full`} value={job?.id ?? ''}
                    onChange={(event) => { const item = jobs.find((entry) => entry.id === event.target.value); if (item) rememberJob(item); }}>
                    {jobs.map((item) => <option key={item.id} value={item.id}>{item.created_at} - {item.status} - {item.id}</option>)}
                </select></label> : <p className="text-sm text-text-2">No support exports have been requested by this administrator.</p>}
                {jobsNext ? <GlassButton type="button" variant="subtle" disabled={busy} onClick={() => void run(async () => {
                    const page = await api.get<SupportPage<SupportJob>>(`${SUPPORT_EXPORT_ROOT}?${new URLSearchParams({ after: jobsNext })}`);
                    setJobs((current) => [...current, ...page.items.filter((item) => !current.some((other) => other.id === item.id))]); setJobsNext(page.next);
                })}>Load more exports</GlassButton> : null}
                {job ? <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2" role="status" aria-live="polite"><StatusBadge status={job.status} /><span className="text-sm">{job.phase}</span></div>
                    <p className="text-xs text-text-2">Expires {job.expires_at}. Only you can download this export.</p>
                    {job.error ? <Notice tone="danger">{job.error.message}</Notice> : null}
                    <div className="flex flex-wrap gap-2">
                        <GlassButton type="button" variant="subtle" disabled={busy} onClick={() => void run(async () => {
                            rememberJob(await api.get<SupportJob>(supportExportPath(job.id)));
                        })}>Refresh export status</GlassButton>
                        {(supportJobActive(job.status) || job.status === 'ready') ? <GlassButton type="button" variant="danger" disabled={busy}
                            onClick={() => void run(async () => { rememberJob(await api.post<SupportJob>(supportExportPath(job.id, 'cancel'), {})); })}>Cancel export</GlassButton> : null}
                        {job.can_download ? <GlassButton type="button" variant="subtle" disabled={busy} onClick={() => void run(async () => {
                            setPreview(await api.get<unknown>(supportExportPath(job.id, 'preview'))); setDownloadAcknowledged(false);
                        })}>Review redacted preview</GlassButton> : null}
                    </div>
                    {preview !== null ? <div className="space-y-3">
                        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-surface-2 p-3 text-xs" data-testid="support-export-preview">{JSON.stringify(preview, null, 2)}</pre>
                        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={downloadAcknowledged}
                            onChange={(event) => setDownloadAcknowledged(event.target.checked)} />I reviewed the scrubbed preview and will check the ZIP for residual sensitive data before sharing.</label>
                        <GlassButton type="button" variant="primary" disabled={busy || !downloadAcknowledged || !job.can_download} onClick={() => void run(async () => {
                            const response = await v2ApiFetch(apiUrl(supportExportPath(job.id, 'download')), { credentials: CREDENTIALS_MODE, cache: 'no-store' });
                            if (!response.ok) {
                                const payload: unknown = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
                                const problem = payload && typeof payload === 'object' && 'error' in payload && typeof payload.error === 'string' ? payload.error : 'The ZIP could not be downloaded. Refresh its status.';
                                throw new Error(problem);
                            }
                            if (!response.headers.get('content-type')?.includes('application/zip')) throw new Error('The server did not return a ZIP. Sign in again and refresh its status.');
                            saveBlob(await response.blob(), 'simplechat-support.zip');
                        })}>Download support ZIP</GlassButton>
                    </div> : null}
                </div> : null}
            </section>
        </div>
    );
}
