// chat-m365-approvals.js
(() => {
    'use strict';

    const sourceLabels = Object.freeze({
        calendar: 'Calendar',
        email: 'Email',
        onedrive: 'OneDrive',
        spo: 'SharePoint Online (SPO)'
    });
    const typeLabels = Object.freeze({
        m365_source_sharing: 'Share Microsoft 365 evidence',
        m365_extended_analysis: 'Extended file analysis',
        m365_workflow_run_as: 'Workflow Run as authorization'
    });
    const durationLabels = Object.freeze({
        no: 'No',
        request: 'Allow this request',
        today: 'Allow for today',
        always: 'Always allow'
    });
    const analysisChoiceLabels = Object.freeze({
        request: 'Analyze more for this request',
        always: 'Always allow deeper analysis',
        fast: 'Use a faster answer'
    });
    let active = null;
    let resumeHandler = null;
    let csrfToken = null;
    let csrfRefresh = null;
    let sequence = 0;

    function makeElement(tag, className, text) {
        const element = document.createElement(tag);
        element.className = className;
        if (text !== undefined) {
            element.textContent = text;
        }
        return element;
    }

    async function requestJson(path, options = {}, csrfRetried = false) {
        const target = new URL(path, window.location.origin);
        if (target.origin !== window.location.origin || !target.pathname.startsWith('/api/m365/')) {
            throw new Error('Microsoft 365 requests must use the local authenticated API.');
        }
        const headers = { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
        if (options.body !== undefined) {
            headers['Content-Type'] = 'application/json';
        }
        if (csrfToken) {
            headers['X-M365-CSRF-Token'] = csrfToken;
        }
        const response = await fetch(path, {
            method: options.method || 'GET',
            credentials: 'same-origin',
            headers,
            ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {})
        });
        const contentType = response.headers.get('Content-Type') || '';
        if (!contentType.includes('application/json')) {
            throw new Error('The Microsoft 365 service did not return a usable response. Sign in or refresh before trying again.');
        }
        const result = await response.json();
        if (!result || typeof result !== 'object') {
            throw new Error('The Microsoft 365 service returned an invalid response.');
        }
        if (!response.ok || result.success === false) {
            if (response.status === 403 && result.error === 'm365_csrf_invalid' && !csrfRetried && options.method && options.method !== 'GET') {
                csrfRefresh = csrfRefresh || requestJson('/api/m365/preferences')
                    .finally(() => { csrfRefresh = null; });
                await csrfRefresh;
                return requestJson(path, options, true);
            }
            const error = new Error(result.message || 'The Microsoft 365 request could not be completed. Refresh before trying again.');
            error.status = response.status;
            error.code = result.error;
            throw error;
        }
        if (typeof result.csrf_token === 'string' && result.csrf_token.length >= 32) {
            csrfToken = result.csrf_token;
        }
        return result;
    }

    function approvalFromResponse(result) {
        const approval = result?.approval || result;
        if (!approval || typeof approval.id !== 'string' || !typeLabels[approval.request_type] || approval.approval_scope !== 'user') {
            throw new Error('The server did not return a user-owned Microsoft 365 approval.');
        }
        return approval;
    }

    function describeStatus(approval, includeDecisions = true) {
        const status = typeof approval.status === 'string' ? approval.status : 'unknown';
        const execution = typeof approval.execution_status === 'string' ? approval.execution_status : 'not reported';
        const summary = `Decision: ${status.replaceAll('_', ' ')}. Execution: ${execution.replaceAll('_', ' ')}.`;
        const outcomes = includeDecisions ? Object.entries(approval.decisions || {}).map(([source, decision]) =>
            `${sourceLabels[source] || source}: ${durationLabels[decision.duration] || decision.duration}`
        ) : [];
        if (outcomes.length) {
            return `${summary} Recorded source choices: ${outcomes.join('; ')}.`;
        }
        if (includeDecisions && Object.prototype.hasOwnProperty.call(analysisChoiceLabels, approval.analysis_choice)) {
            return `${summary} Recorded analysis choice: ${analysisChoiceLabels[approval.analysis_choice]}.`;
        }
        return summary;
    }

    function applyError(error) {
        const element = document.getElementById('m365-approvals-error');
        if (!element) {
            return false;
        }
        element.textContent = error instanceof Error ? error.message : String(error || 'The request could not be completed.');
        element.classList.remove('d-none');
        element.focus();
        if (active?.options.onError) {
            active.options.onError(error);
        }
        return true;
    }

    function canDecide(approval) {
        return approval.status === 'pending' && (approval.can_approve === true || approval.can_deny === true);
    }

    function addChoices(container, name, choices, value, onChange, busy) {
        const group = makeElement('div', 'd-flex flex-wrap gap-2');
        group.setAttribute('role', 'group');
        group.setAttribute('aria-label', name);
        choices.forEach(([choice, label]) => {
            const button = makeElement('button', choice === value ? 'btn btn-primary' : 'btn btn-outline-primary', label);
            button.type = 'button';
            button.dataset.choice = choice;
            button.setAttribute('aria-pressed', String(choice === value));
            button.disabled = busy;
            button.addEventListener('click', () => {
                onChange(choice);
                group.querySelectorAll('button').forEach(item => {
                    const selected = item.dataset.choice === choice;
                    item.setAttribute('aria-pressed', String(selected));
                    item.className = selected ? 'btn btn-primary' : 'btn btn-outline-primary';
                });
            });
            group.appendChild(button);
        });
        container.appendChild(group);
    }

    function renderRecord(approval, state) {
        const section = makeElement('section', 'border rounded p-3');
        const titleId = `m365-approval-heading-${++sequence}`;
        const heading = makeElement('h3', 'fs-6', typeLabels[approval.request_type]);
        heading.id = titleId;
        section.setAttribute('aria-labelledby', titleId);
        section.dataset.approvalId = approval.id;
        section.append(heading, makeElement('p', 'small text-muted', describeStatus(approval, false)));
        if (approval.reason) {
            section.appendChild(makeElement('p', 'small', approval.reason));
        }
        const context = approval.context || {};
        if (context.workflow_id) {
            section.appendChild(makeElement('p', 'small text-break', `Workflow: ${context.workflow_id}`));
        }
        if (context.conversation_id) {
            section.appendChild(makeElement('p', 'small text-break', `Conversation: ${context.conversation_id}`));
        }
        if (approval.expires_at) {
            section.appendChild(makeElement('p', 'small', `Request expires: ${new Date(approval.expires_at).toLocaleString()}`));
        }
        if (!canDecide(approval)) {
            section.appendChild(makeElement('p', 'small mb-0', approval.status === 'pending'
                ? 'This request is not actionable by your account.'
                : 'This saved decision is read-only. Approval does not mean execution has completed.'));
            Object.entries(approval.decisions || {}).forEach(([source, decision]) => {
                section.appendChild(makeElement('p', 'small mb-0', `${sourceLabels[source] || source}: ${durationLabels[decision.duration] || decision.duration}. ${decision.expires_at ? `Expires ${new Date(decision.expires_at).toLocaleString()}.` : ''}`));
            });
            if (Object.prototype.hasOwnProperty.call(analysisChoiceLabels, approval.analysis_choice)) {
                section.appendChild(makeElement('p', 'small mb-0', `Recorded analysis choice: ${analysisChoiceLabels[approval.analysis_choice]}.`));
            }
            return section;
        }
        state.choices[approval.id] = state.choices[approval.id] || {};
        const selected = state.choices[approval.id];
        if (approval.request_type === 'm365_source_sharing') {
            if (context.shared !== true) {
                throw new Error('This sharing request does not describe a shared conversation. Refresh before deciding.');
            }
            const sources = Object.entries(approval.sources || {});
            if (!sources.length) {
                throw new Error('The sharing request has no authoritative source policy.');
            }
            selected.decisions = selected.decisions || {};
            sources.forEach(([source, policy]) => {
                if (!sourceLabels[source] || !Array.isArray(policy.allowed_durations)) {
                    throw new Error('The sharing request has an unsupported source policy.');
                }
                const ceiling = ['request', 'today', 'always'].indexOf(policy.maximum_sharing_acknowledgement);
                if (ceiling < 0) {
                    throw new Error('The action sharing limit could not be verified.');
                }
                const choices = approval.can_deny === true ? [['no', 'No']] : [];
                if (approval.can_approve === true) {
                    ['request', 'today', 'always'].slice(0, ceiling + 1).forEach(duration => {
                        if (policy.allowed_durations.includes(duration)) {
                            choices.push([duration, durationLabels[duration]]);
                        }
                    });
                }
                const sourceSection = makeElement('div', 'mb-3');
                sourceSection.appendChild(makeElement('h4', 'fs-6', sourceLabels[source]));
                sourceSection.appendChild(makeElement('p', 'small text-muted', 'No continues without this source. Other agent capabilities remain available.'));
                addChoices(sourceSection, `${sourceLabels[source]} sharing decision`, choices, selected.decisions[source]?.duration,
                    duration => { selected.decisions[source] = { duration }; }, state.busy);
                section.appendChild(sourceSection);
            });
        } else if (approval.request_type === 'm365_extended_analysis') {
            const proposal = approval.proposal || {};
            const sources = Object.keys(approval.sources || {}).map(source => sourceLabels[source] || source);
            section.appendChild(makeElement('p', 'small', `Sources: ${sources.join(', ')}`));
            const counts = makeElement('dl', 'row small');
            Object.entries({
                file_count: 'Files',
                download_count: 'Content downloads',
                total_bytes: 'Content bytes',
                context_tokens: 'Context tokens'
            }).forEach(([key, label]) => {
                if (Object.prototype.hasOwnProperty.call(proposal, key)) {
                    if (!Number.isSafeInteger(proposal[key]) || proposal[key] < 0) {
                        throw new Error('The requested analysis counts could not be verified. Refresh before deciding.');
                    }
                    counts.append(
                        makeElement('dt', 'col-sm-6', label),
                        makeElement('dd', 'col-sm-6', proposal[key].toLocaleString())
                    );
                }
            });
            if (counts.childElementCount) {
                section.append(makeElement('h4', 'fs-6', 'Requested analysis'), counts);
            }
            section.appendChild(makeElement('p', 'small', 'A faster answer uses the available evidence and explains what was not covered. Deeper analysis remains subject to service limits.'));
            const choices = approval.can_deny === true ? [['fast', analysisChoiceLabels.fast]] : [];
            if (approval.can_approve === true) {
                choices.push(['request', analysisChoiceLabels.request], ['always', analysisChoiceLabels.always]);
            }
            addChoices(section, 'File analysis decision', choices, selected.choice,
                choice => { selected.choice = choice; }, state.busy);
        } else {
            section.appendChild(makeElement('p', 'small', 'This authorizes only this workflow revision and its sources, instructions, inputs, schedule, and destinations. Changes require renewed authorization. A connected account alone is not approval.'));
            const sources = Object.keys(approval.sources || {}).map(source => sourceLabels[source] || source);
            section.appendChild(makeElement('p', 'small', `Sources: ${sources.join(', ')}`));
            const review = approval.binding?.review;
            const hasReview = review && typeof review === 'object' && !Array.isArray(review)
                && ['instructions', 'capabilities', 'runtime_inputs', 'triggers', 'destinations'].every(key =>
                    typeof review[key] === 'string' && review[key].trim().length > 0);
            if (hasReview) {
                const details = makeElement('details', 'mb-3');
                details.open = true;
                details.appendChild(makeElement('summary', 'fw-semibold', 'Workflow revision to authorize'));
                const labels = {
                    instructions: 'Instructions',
                    capabilities: 'Capabilities',
                    runtime_inputs: 'Accepted runtime inputs',
                    triggers: 'Manual triggers and schedule',
                    destinations: 'Destinations and audience'
                };
                Object.entries(labels).forEach(([key, label]) => {
                    details.appendChild(makeElement('h4', 'fs-6 mt-3', label));
                    details.appendChild(makeElement('pre', 'small text-wrap text-break border rounded p-2', review[key]));
                });
                section.appendChild(details);
            } else {
                section.appendChild(makeElement('p', 'alert alert-warning', 'The workflow revision details are unavailable. Approval is disabled until the server supplies the instructions, inputs, schedule, and destinations to review. You can still choose No.'));
            }
            const choices = approval.can_deny === true ? [['deny', 'No']] : [];
            if (approval.can_approve === true && hasReview) {
                choices.push(['approve', 'Allow this workflow revision']);
            }
            addChoices(section, 'Workflow Run as decision', choices, selected.choice,
                choice => { selected.choice = choice; }, state.busy);
        }
        return section;
    }

    function render(state) {
        const container = document.getElementById('m365-approval-records');
        container.replaceChildren();
        const sharing = state.approvals.some(approval => approval.request_type === 'm365_source_sharing' && approval.context?.shared === true);
        document.getElementById('m365-sharing-warning').classList.toggle('d-none', !sharing);
        document.getElementById('m365-approval-timezone-group').classList.toggle('d-none', !sharing);
        state.invalid = false;
        try {
            state.approvals.forEach(approval => container.appendChild(renderRecord(approval, state)));
        } catch (error) {
            state.invalid = true;
            container.replaceChildren();
            applyError(error);
        }
        const button = document.getElementById('m365-approvals-apply');
        button.disabled = state.invalid || state.busy || state.finishing || (!state.result && !state.approvals.some(canDecide));
        button.textContent = state.result ? 'Retry resume' : 'Apply choices';
    }

    function confirmedTimezone() {
        const value = document.getElementById('m365-approval-timezone').value.trim();
        try {
            if (!value) {
                throw new Error('Missing timezone');
            }
            new Intl.DateTimeFormat('en', { timeZone: value }).format();
        } catch (error) {
            throw new Error('Confirm a valid IANA timezone before allowing sharing.');
        }
        return value;
    }

    function decisionPayload(approval, state) {
        const selected = state.choices[approval.id];
        if (approval.request_type !== 'm365_source_sharing') {
            if (!selected?.choice) {
                throw new Error('Choose an outcome for each pending request.');
            }
            return { choice: selected.choice };
        }
        const decisions = {};
        Object.keys(approval.sources).forEach(source => {
            const duration = selected?.decisions?.[source]?.duration;
            if (!duration) {
                throw new Error(`Choose No or a sharing duration for ${sourceLabels[source]}.`);
            }
            decisions[source] = duration === 'no' ? { duration } : { duration, timezone: confirmedTimezone() };
        });
        return { decisions };
    }

    async function finish(state) {
        const callback = state.options.onResume || resumeHandler;
        if (callback) {
            await callback(state.result);
        }
        state.finishing = true;
        state.saving = false;
        state.modal.hide();
    }

    async function saveChoices() {
        const state = active;
        if (!state || state.busy || state.invalid || state.finishing) {
            return;
        }
        document.getElementById('m365-approvals-error').classList.add('d-none');
        try {
            if (state.result) {
                state.busy = true;
                state.saving = true;
                render(state);
                await finish(state);
                return;
            }
            const pending = state.approvals.filter(canDecide);
            const submissions = pending.map(approval => ({ approval, payload: decisionPayload(approval, state) }));
            if (!submissions.length) {
                throw new Error('There are no actionable requests for your account.');
            }
            state.busy = true;
            state.saving = true;
            render(state);
            for (const { approval, payload } of submissions) {
                const response = await requestJson(`/api/m365/approvals/${encodeURIComponent(approval.id)}/decision`, { method: 'POST', body: payload });
                const saved = approvalFromResponse(response);
                if (saved.id !== approval.id || saved.status === 'pending') {
                    throw new Error('The server has not recorded this decision. Refresh before continuing.');
                }
                state.approvals = state.approvals.map(item => item.id === saved.id ? saved : item);
                window.dispatchEvent(new CustomEvent('m365-approval-updated', { detail: saved }));
            }
            state.result = { status: 'decided', approvals: state.approvals };
            document.getElementById('m365-approvals-status').textContent = 'Decisions saved. Execution may be queued or require sign-in; approval is not execution success.';
            await finish(state);
        } catch (error) {
            if (error.status === 409) {
                try {
                    state.approvals = await Promise.all(state.approvals.map(async approval =>
                        approvalFromResponse(await requestJson(`/api/m365/approvals/${encodeURIComponent(approval.id)}`))));
                    state.choices = {};
                } catch (refreshError) {
                    applyError(refreshError);
                }
            }
            applyError(error);
        } finally {
            state.busy = false;
            state.saving = false;
            if (active === state) {
                render(state);
            }
        }
    }

    function openApprovals(payload, options = {}) {
        const approvals = Array.isArray(payload) ? payload : (payload?.approvals || (payload?.approval ? [payload.approval] : []));
        if (!Array.isArray(approvals) || !approvals.length || approvals.some(approval => typeof approval?.id !== 'string')) {
            return Promise.reject(new Error('A persisted Microsoft 365 approval is required. No permission has been granted.'));
        }
        if (active) {
            const sameRecords = approvals.length === active.approvals.length && approvals.every(item => active.approvals.some(current => current.id === item.id));
            return sameRecords ? active.promise : active.promise.then(() => openApprovals(payload, options));
        }
        const element = document.getElementById('m365ApprovalsModal');
        if (!element || !window.bootstrap?.Modal) {
            return Promise.reject(new Error('The Microsoft 365 approval dialog is unavailable. Use the Approvals page; no permission has been granted.'));
        }
        const state = { approvals, choices: {}, options, busy: true, result: null, trigger: document.activeElement };
        state.promise = new Promise(resolve => { state.resolve = resolve; });
        state.modal = bootstrap.Modal.getOrCreateInstance(element);
        active = state;
        document.getElementById('m365-approval-records').replaceChildren();
        document.getElementById('m365-sharing-warning').classList.add('d-none');
        document.getElementById('m365-approval-timezone-group').classList.add('d-none');
        document.getElementById('m365-approvals-error').classList.add('d-none');
        document.getElementById('m365-approvals-status').textContent = 'Loading saved requests...';
        const applyButton = document.getElementById('m365-approvals-apply');
        applyButton.disabled = true;
        applyButton.addEventListener('click', saveChoices);
        element.addEventListener('shown.bs.modal', () => {
            const error = document.getElementById('m365-approvals-error');
            const focusTarget = error.classList.contains('d-none') ? document.getElementById('m365-approvals-title') : error;
            focusTarget.focus();
        }, { once: true });
        const preventPendingWriteDismissal = event => {
            if (state.saving) {
                event.preventDefault();
            }
        };
        element.addEventListener('hide.bs.modal', preventPendingWriteDismissal);
        element.addEventListener('hidden.bs.modal', () => {
            element.removeEventListener('hide.bs.modal', preventPendingWriteDismissal);
            applyButton.removeEventListener('click', saveChoices);
            if (active === state) {
                active = null;
            }
            state.resolve(state.result || { status: 'dismissed', approvals: state.approvals });
            if (state.trigger?.isConnected) {
                state.trigger.focus();
            }
        }, { once: true });
        state.modal.show();
        Promise.all([
            Promise.all(approvals.map(async approval => approvalFromResponse(
                await requestJson(`/api/m365/approvals/${encodeURIComponent(approval.id)}`)))),
            requestJson('/api/m365/preferences')
        ]).then(([records]) => {
            if (active !== state) {
                return;
            }
            state.approvals = records;
            document.getElementById('m365-approval-timezone').value = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
            document.getElementById('m365-approvals-status').textContent = 'Choose an outcome for each request, then apply your choices.';
            state.busy = false;
            render(state);
        }).catch(error => {
            state.busy = false;
            if (active === state) {
                applyError(error);
            }
        });
        return state.promise;
    }

    window.SimpleChatM365Approvals = Object.freeze({
        openApprovals,
        applyError,
        requestJson,
        describeStatus,
        sourceLabels,
        typeLabels,
        setResumeHandler(callback) {
            if (callback !== null && typeof callback !== 'function') {
                throw new TypeError('The resume handler must be a function or null.');
            }
            resumeHandler = callback;
        }
    });
})();
