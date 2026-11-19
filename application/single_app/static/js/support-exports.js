// support-exports.js

const exportRoot = '/api/admin/support-exports';
const consentRoot = '/api/support-export-consents';
const sourceLabels = {
    telemetry: 'Application Insights telemetry',
    activity: 'Activity and audit logs',
    file_processing: 'File-processing diagnostics',
    console: 'App Service console logs'
};
const activeStates = new Set(['waiting_for_consent', 'queued', 'collecting', 'redacting', 'ai_review']);

function node(tag, text = '', className = '') {
    const element = document.createElement(tag);
    element.textContent = text;
    element.className = className;
    return element;
}

function button(text, action, className = 'btn btn-outline-secondary') {
    const element = node('button', text, className);
    element.type = 'button';
    element.addEventListener('click', action);
    return element;
}

async function api(path, body) {
    const response = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST',
        credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
    if (!response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('Sign in again and refresh the support export page.');
    }
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.error === 'string' ? result.error : 'The support export operation failed.');
    return result;
}

function localTime(date) {
    const pad = (value) => String(value).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function utc(value) {
    const date = new Date(value);
    if (!value || Number.isNaN(date.getTime()) || localTime(date) !== value.slice(0, 16)) {
        throw new Error('Choose a valid local date and time; daylight-saving gaps are not valid times.');
    }
    for (const shift of [-86400000, 86400000]) {
        const offset = new Date(date.getTime() + shift).getTimezoneOffset() - date.getTimezoneOffset();
        if (offset && localTime(new Date(date.getTime() + offset * 60000)) === value.slice(0, 16)) {
            throw new Error('This local time repeats during a clock change. Choose unambiguous endpoints spanning the change.');
        }
    }
    return date.toISOString();
}

async function downloadZip(id) {
    const response = await fetch(`${exportRoot}/${encodeURIComponent(id)}/download`, { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok || !response.headers.get('content-type')?.includes('application/zip')) {
        const problem = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
        throw new Error(typeof problem?.error === 'string' ? problem.error : 'The ZIP could not be downloaded. Refresh its status.');
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = url;
    link.download = 'simplechat-support.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function initializeAdmin(root) {
    const get = (name) => root.querySelector(`#support-export-${name}`);
    const state = {
        ready: null, busy: false, people: [], peopleNext: null, conversations: [], conversationNext: null,
        selected: new Map(), jobs: [], jobsNext: null, job: null, review: null, preview: null, poll: true
    };
    let conversationController = null;
    const show = (name, visible) => get(name).classList.toggle('d-none', !visible);
    const error = (failure) => {
        get('error').textContent = failure instanceof Error ? failure.message : 'Support export failed.';
        show('error', true);
    };
    const updateControls = () => {
        get('fields').disabled = state.busy || state.review !== null;
        get('review').disabled = state.busy || !state.ready?.storage.available;
        get('generate').disabled = state.busy || !get('review-ack').checked;
        get('job').disabled = state.busy;
        get('download').disabled = state.busy || !get('download-ack').checked || !state.job?.can_download;
        get('transcripts').disabled = get('all').checked || state.selected.size === 0
            || [...state.selected.values()].some((item) => !item.transcript_eligible);
        const conversationMode = get('mode').value === 'conversations';
        show('person-fields', !get('all').checked);
        show('margins', conversationMode);
        show('time-fields', !conversationMode || get('narrow').checked);
        show('conversation-fields', !get('all').checked && !!get('user').value);
        show('ai-notice', get('privacy').value === 'ai');
    };
    const act = async (operation) => {
        if (state.busy) return;
        state.busy = true; show('error', false); root.setAttribute('aria-busy', 'true');
        root.querySelectorAll('button').forEach((item) => { item.disabled = true; });
        updateControls();
        try { await operation(); } catch (failure) { error(failure); } finally {
            state.busy = false; root.setAttribute('aria-busy', 'false');
            root.querySelectorAll('button').forEach((item) => { item.disabled = false; });
            updateControls();
        }
    };
    const renderPeople = () => {
        const selected = get('user').value;
        get('user').replaceChildren(new Option('Select a user', ''));
        for (const person of state.people) get('user').appendChild(new Option(`${person.name}${person.email ? ` (${person.email})` : ''}`, person.id));
        get('user').value = state.people.some((item) => item.id === selected) ? selected : '';
        show('more-users', !!state.peopleNext);
    };
    const loadPeople = async (more = false) => {
        const query = new URLSearchParams({ q: get('user-search').value, ...(more ? { after: state.peopleNext } : {}) });
        const page = await api(`${exportRoot}/users?${query}`);
        state.people = more ? [...state.people, ...page.items.filter((item) => !state.people.some((other) => other.id === item.id))] : page.items;
        state.peopleNext = page.next; renderPeople();
    };
    const renderConversations = () => {
        const list = get('conversations');
        list.replaceChildren();
        for (const item of state.conversations) {
            const label = node('label', '', 'd-flex align-items-start gap-2 small mb-2 text-break');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox'; checkbox.className = 'form-check-input flex-shrink-0';
            checkbox.checked = state.selected.has(item.id);
            checkbox.disabled = state.selected.size >= 20 && !checkbox.checked;
            checkbox.addEventListener('change', () => {
                if (checkbox.checked) state.selected.set(item.id, item); else state.selected.delete(item.id);
                if ([...state.selected.values()].some((other) => !other.transcript_eligible)) get('transcripts').checked = false;
                renderConversations(); updateControls();
            });
            label.append(checkbox, node('span', `${item.id} (${item.kind}; last activity ${item.last_activity || 'unknown'})`));
            list.appendChild(label);
        }
        if (!state.conversations.length) list.appendChild(node('p', 'No conversations match this user and ID search.', 'small text-muted'));
        get('selected').replaceChildren(node('p', `Selected: ${state.selected.size}/20`));
        for (const item of state.selected.values()) {
            get('selected').appendChild(button(`Remove ${item.id}`, () => {
                state.selected.delete(item.id); renderConversations(); updateControls();
            }, 'btn btn-sm btn-outline-secondary me-1 mb-1 text-break'));
        }
        show('more-conversations', !!state.conversationNext);
    };
    const loadConversations = async (more = false) => {
        conversationController?.abort();
        conversationController = new AbortController();
        const user = get('user').value;
        if (!user || get('all').checked) return;
        const query = new URLSearchParams({
            user_id: user, q: get('conversation-search').value,
            ...(more ? { after: state.conversationNext } : {})
        });
        const response = await fetch(`${exportRoot}/conversations?${query}`, {
            credentials: 'same-origin', cache: 'no-store', signal: conversationController.signal,
            headers: { Accept: 'application/json' }
        });
        if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Sign in again before loading conversations.');
        const page = await response.json();
        if (!response.ok) throw new Error(page.error || 'Conversations could not be loaded.');
        if (get('user').value !== user || get('all').checked) return;
        state.conversations = more ? [...state.conversations, ...page.items.filter((item) => !state.conversations.some((other) => other.id === item.id))] : page.items;
        state.conversationNext = page.next; renderConversations();
    };
    const resetUser = () => {
        conversationController?.abort(); state.selected.clear(); state.conversations = []; state.conversationNext = null;
        get('transcripts').checked = false; get('conversation-search').value = '';
        if (get('all').checked) { get('user').value = ''; get('mode').value = 'time'; }
        get('mode').querySelector('option[value="conversations"]').disabled = get('all').checked;
        renderConversations(); updateControls();
    };
    const renderReady = (ready) => {
        state.ready = ready;
        get('cloud').value = ready.configuration.cloud;
        get('app-resource').value = ready.configuration.app_resource_id;
        get('site-resource').value = ready.configuration.site_resource_id;
        get('storage-status').textContent = ready.storage.message;
        get('model').textContent = `${ready.model.message || ''}${ready.model.label ? ` Default model: ${ready.model.label} (${ready.model.provider}).` : ''}`;
        get('privacy').querySelector('option[value="ai"]').disabled = !ready.model.available;
        for (const [source, status] of Object.entries(ready.sources)) {
            root.querySelector(`[data-source-note="${source}"]`).textContent = `${status.message}${status.access ? ` Access: ${status.access}.` : ''}`;
        }
        updateControls();
    };
    const renderJob = () => {
        const job = state.job;
        get('job-status').replaceChildren();
        get('job-actions').replaceChildren();
        show('preview', state.preview !== null);
        show('download-review', state.preview !== null);
        show('download', state.preview !== null && !!job?.can_download);
        if (!job) { get('job-status').textContent = 'No support exports requested by this administrator.'; return; }
        get('job-status').dataset.state = job.status;
        get('job-status').appendChild(node('p', `${job.phase} (${job.status}). Expires ${job.expires_at}. Only you can download this export.`, 'small text-break'));
        if (job.error) get('job-status').appendChild(node('p', job.error.message, 'alert alert-danger'));
        get('job-actions').appendChild(button('Refresh export status', () => act(async () => selectJob(await api(`${exportRoot}/${encodeURIComponent(job.id)}`)))));
        if (activeStates.has(job.status) || job.status === 'ready') {
            get('job-actions').appendChild(button('Cancel export', () => act(async () => selectJob(await api(`${exportRoot}/${encodeURIComponent(job.id)}/cancel`, {}))), 'btn btn-outline-danger'));
        }
        if (job.can_download) {
            get('job-actions').appendChild(button('Review redacted preview', () => act(async () => {
                state.preview = await api(`${exportRoot}/${encodeURIComponent(job.id)}/preview`);
                get('preview').textContent = JSON.stringify(state.preview, null, 2);
                get('download-ack').checked = false; renderJob();
            })));
        }
        updateControls();
    };
    const renderJobs = () => {
        get('job').replaceChildren(new Option('Select an export', ''));
        for (const item of state.jobs) get('job').appendChild(new Option(`${item.created_at} - ${item.status} - ${item.id}`, item.id));
        get('job').value = state.job?.id || ''; show('more-jobs', !!state.jobsNext);
    };
    const selectJob = (job) => {
        state.job = job; state.preview = null; state.poll = true; get('download-ack').checked = false;
        state.jobs = [job, ...state.jobs.filter((item) => item.id !== job.id)];
        renderJobs(); renderJob();
    };
    const loadJobs = async (more = false) => {
        const page = await api(`${exportRoot}${more ? `?${new URLSearchParams({ after: state.jobsNext })}` : ''}`);
        state.jobs = more ? [...state.jobs, ...page.items.filter((item) => !state.jobs.some((other) => other.id === item.id))] : page.items;
        state.jobsNext = page.next;
        if (!state.job && state.jobs.length) {
            const ordered = [...state.jobs].sort((a, b) => b.created_at.localeCompare(a.created_at));
            state.job = ordered.find((item) => activeStates.has(item.status)) || ordered[0];
        }
        renderJobs(); renderJob();
    };
    for (const [source, labelText] of Object.entries(sourceLabels)) {
        const label = node('label', '', 'd-flex align-items-start gap-2 mb-2 small');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox'; checkbox.className = 'form-check-input flex-shrink-0';
        checkbox.dataset.source = source; checkbox.checked = ['telemetry', 'activity'].includes(source);
        const text = node('span', labelText);
        const note = node('span', 'Checking source readiness...', 'd-block text-muted');
        note.dataset.sourceNote = source; text.appendChild(note); label.append(checkbox, text); get('sources').appendChild(label);
    }
    const now = new Date();
    get('end').value = localTime(now); get('start').value = localTime(new Date(now.getTime() - 3600000));
    get('timezone').textContent = `Input timezone: ${Intl.DateTimeFormat().resolvedOptions().timeZone}. Review shows exact UTC intervals. Maximum effective span: 7 days.`;
    get('all').addEventListener('change', resetUser);
    get('user').addEventListener('change', () => { resetUser(); act(loadConversations); });
    get('user-search').addEventListener('input', () => { get('user').value = ''; resetUser(); });
    get('search-users').addEventListener('click', () => act(() => loadPeople()));
    get('more-users').addEventListener('click', () => act(() => loadPeople(true)));
    get('search-conversations').addEventListener('click', () => act(() => loadConversations()));
    get('more-conversations').addEventListener('click', () => act(() => loadConversations(true)));
    get('more-jobs').addEventListener('click', () => act(() => loadJobs(true)));
    for (const name of ['mode', 'narrow', 'privacy', 'review-ack', 'download-ack']) get(name).addEventListener('change', updateControls);
    get('save-config').addEventListener('click', () => act(async () => {
        await api(`${exportRoot}/configuration`, {
            cloud: get('cloud').value,
            app_resource_id: get('app-resource').value.trim(), site_resource_id: get('site-resource').value.trim()
        });
        state.review = null; show('review-panel', false); renderReady(await api(`${exportRoot}/readiness`));
    }));
    get('initialize').addEventListener('click', () => act(async () => renderReady(await api(`${exportRoot}/initialize-storage`, { confirmed: true }))));
    get('test').addEventListener('click', () => act(async () => renderReady(await api(`${exportRoot}/test-sources`, {}))));
    get('review').addEventListener('click', () => act(async () => {
        const request = {
            all_users: get('all').checked, user_id: get('user').value,
            conversation_ids: [...state.selected.keys()], mode: get('mode').value,
            before_minutes: Number(get('before').value), after_minutes: Number(get('after').value),
            sources: [...root.querySelectorAll('[data-source]:checked')].map((item) => item.dataset.source),
            include_system_context: get('context').checked, include_transcripts: get('transcripts').checked,
            privacy: get('privacy').value, purpose: get('purpose').value
        };
        if (request.mode === 'time' || get('narrow').checked) { request.start = utc(get('start').value); request.end = utc(get('end').value); }
        const scope = await api(`${exportRoot}/review`, request);
        state.review = { scope, request };
        get('review-details').replaceChildren();
        for (const text of [
            scope.request.all_users ? 'All users' : `User: ${scope.request.user_id}`,
            ...scope.intervals.map(([start, end]) => `UTC: ${start} through ${end} (end exclusive)`),
            `Sources: ${scope.request.sources.map((source) => sourceLabels[source]).join(', ')}`,
            scope.request.include_transcripts ? 'Whole personal-conversation snapshots will wait for owner consent.' : 'Logs only; no transcripts.',
            `Privacy: ${scope.request.privacy}${scope.model_label ? ` (${scope.model_label})` : ''}. Review expires ${scope.expires_at}.`
        ]) get('review-details').appendChild(node('p', text));
        get('review-ack').checked = false; show('review-panel', true); get('review-heading').focus();
    }));
    get('edit').addEventListener('click', () => { state.review = null; show('review-panel', false); updateControls(); });
    get('generate').addEventListener('click', () => act(async () => {
        const review = state.review;
        if (!review || !get('review-ack').checked) throw new Error('Review and acknowledge the exact scope first.');
        const job = await api(exportRoot, { request: review.request, retry_key: review.scope.review_id, review_id: review.scope.review_id });
        state.review = null; show('review-panel', false); selectJob(job);
    }));
    get('job').addEventListener('change', () => {
        const selected = state.jobs.find((item) => item.id === get('job').value);
        if (selected) selectJob(selected);
        else { state.job = null; state.preview = null; renderJob(); updateControls(); }
    });
    get('download').addEventListener('click', () => act(async () => {
        if (!get('download-ack').checked || !state.job?.can_download) throw new Error('Review the scrubbed preview before downloading.');
        await downloadZip(state.job.id);
    }));
    root.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && event.target instanceof HTMLInputElement) {
            event.preventDefault();
            if (event.target === get('user-search')) get('search-users').click();
            if (event.target === get('conversation-search')) get('search-conversations').click();
        }
    });
    const timer = setInterval(async () => {
        if (state.busy || !state.poll || !state.job || !activeStates.has(state.job.status)) return;
        const id = state.job.id;
        try {
            const job = await api(`${exportRoot}/${encodeURIComponent(id)}`);
            if (state.job?.id === id) { state.job = job; state.jobs = state.jobs.map((item) => item.id === id ? job : item); renderJobs(); renderJob(); }
        } catch (failure) { state.poll = false; error(failure); }
    }, 5000);
    window.addEventListener('pagehide', () => { clearInterval(timer); conversationController?.abort(); }, { once: true });
    act(async () => { await Promise.all([api(`${exportRoot}/readiness`).then(renderReady), loadPeople(), loadJobs()]); });
}

function initializeConsents(root) {
    const list = root.querySelector('[data-support-consent-list]');
    const detail = root.querySelector('[data-support-consent-detail]');
    const errorNode = root.querySelector('[data-support-consent-error]');
    const refresh = root.querySelector('[data-support-consent-refresh]');
    const more = root.querySelector('[data-support-consent-more]');
    let items = [];
    let next = null;
    let selected = null;
    let fingerprint = '';
    let busy = false;
    let approveButton = null;
    let acknowledgementInput = null;
    const act = async (operation) => {
        if (busy) return;
        busy = true; errorNode.classList.add('d-none');
        root.querySelectorAll('button').forEach((item) => { item.disabled = true; });
        try { await operation(); } catch (failure) {
            errorNode.textContent = failure instanceof Error ? failure.message : 'Support-data consent failed.';
            errorNode.classList.remove('d-none');
        } finally {
            busy = false;
            root.querySelectorAll('button').forEach((item) => { item.disabled = false; });
            if (approveButton) approveButton.disabled = !fingerprint || !acknowledgementInput?.checked;
            if (acknowledgementInput) acknowledgementInput.disabled = !fingerprint;
        }
    };
    const renderDetail = () => {
        detail.replaceChildren(); fingerprint = ''; approveButton = null; acknowledgementInput = null;
        if (!selected) { detail.appendChild(node('p', 'Choose a support-data request to review its scope.', 'text-muted')); return; }
        const consent = selected;
        detail.appendChild(node('h4', 'Personal conversation data release', 'h6'));
        detail.appendChild(node('p', consent.purpose, 'text-break'));
        detail.appendChild(node('p', consent.scope_notice, 'alert alert-warning'));
        for (const text of [
            `Status: ${consent.status}. Requesting administrator: ${consent.requester_id}`,
            `Whole snapshot cutoff: ${consent.source_cutoff}. Expires: ${consent.expires_at}`,
            `Privacy: ${consent.privacy}${consent.model_label ? ` (${consent.model_label})` : ''}`,
            ...consent.conversations.map((item) => `Personal conversation: ${item.id} (${item.message_count ?? 'unknown'} recorded messages)`)
        ]) detail.appendChild(node('p', text, 'small text-break'));
        if (consent.privacy === 'ai') detail.appendChild(node('p', 'Approving also allows already-scrubbed snapshots to be sent to the default model shown above. Privacy checking is not a guarantee of anonymity.', 'alert alert-warning'));
        const decide = async (action) => {
            const response = await api(`${consentRoot}/${encodeURIComponent(consent.id)}/decision`, { action, ...(action === 'approve' ? { fingerprint } : {}) });
            items = items.map((item) => item.id === response.id ? response : item); selected = response; render();
        };
        if (consent.status === 'pending' && !consent.expired) {
            const preview = node('pre', '', 'bg-body-secondary border rounded p-3 overflow-auto text-break d-none');
            preview.style.maxHeight = '20rem'; preview.style.whiteSpace = 'pre-wrap';
            const acknowledgement = document.createElement('input');
            acknowledgement.type = 'checkbox'; acknowledgement.className = 'form-check-input me-2'; acknowledgement.disabled = true;
            const approve = button('Approve whole-conversation snapshots', () => act(async () => {
                if (!fingerprint || !acknowledgement.checked) throw new Error('Review the snapshot scope and explicitly approve it first.');
                await decide('approve');
            }), 'btn btn-primary');
            approveButton = approve; acknowledgementInput = acknowledgement;
            approve.disabled = true;
            const label = node('label', '', 'd-block small my-3');
            label.append(acknowledgement, document.createTextNode('I approve releasing the whole requested snapshots to this administrator, including selected privacy processing. Downloaded copies cannot be recalled.'));
            acknowledgement.addEventListener('change', () => { approve.disabled = !acknowledgement.checked || !fingerprint; });
            detail.appendChild(button('Review my snapshot preview', () => act(async () => {
                const result = await api(`${consentRoot}/${encodeURIComponent(consent.id)}/preview`);
                fingerprint = result.fingerprint; preview.textContent = JSON.stringify(result.preview, null, 2);
                preview.classList.remove('d-none'); acknowledgement.disabled = false; acknowledgement.checked = false;
                approve.disabled = true;
            })));
            detail.append(preview, node('p', 'Preview shows at most 10 messages per conversation; approval covers the whole snapshot through the cutoff, not just this preview.', 'small text-muted'), label);
            const actions = node('div', '', 'd-flex flex-wrap gap-2');
            actions.append(approve, button('Decline transcript release', () => act(() => decide('decline')), 'btn btn-outline-danger'));
            detail.appendChild(actions);
        }
        if (consent.status === 'approved' && !consent.expired) detail.appendChild(button('Revoke further transcript downloads', () => act(() => decide('revoke')), 'btn btn-outline-danger'));
    };
    const render = () => {
        list.replaceChildren();
        for (const item of items) list.appendChild(button(`${item.purpose} (${item.status})`, () => {
            selected = item; renderDetail();
        }, 'btn btn-outline-secondary text-start text-break mb-2 w-100'));
        if (!items.length) list.appendChild(node('p', 'No support-data consent requests.', 'text-muted'));
        more.classList.toggle('d-none', !next); renderDetail();
    };
    const load = async (append = false) => {
        const page = await api(`${consentRoot}${append ? `?${new URLSearchParams({ after: next })}` : ''}`);
        items = append ? [...items, ...page.items.filter((item) => !items.some((other) => other.id === item.id))] : page.items;
        next = page.next;
        const linked = new URLSearchParams(window.location.search).get('support_export');
        if (linked && !selected) {
            const id = 'consent-' + linked;
            selected = items.find((item) => item.id === id) || await api(`${consentRoot}/${encodeURIComponent(id)}`);
            if (!items.some((item) => item.id === selected.id)) items.unshift(selected);
        } else if (selected) selected = items.find((item) => item.id === selected.id) || selected;
        render();
        if (linked) root.scrollIntoView({ block: 'start' });
    };
    refresh.addEventListener('click', () => act(() => load()));
    more.addEventListener('click', () => act(() => load(true)));
    act(() => load());
}

document.querySelectorAll('[data-support-exports="admin"]').forEach(initializeAdmin);
document.querySelectorAll('[data-support-exports="consent"]').forEach(initializeConsents);
