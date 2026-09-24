// m365-pending-actions.js
(() => {
    'use strict';

    const apiPath = '/api/msgraph/pending-actions';
    const retryDelaysMs = [1000, 3000, 7000, 15000, 30000, 60000];
    const actionableStatuses = new Set(['pending', 'scheduled', 'review_required']);
    const entries = new Map();
    let sequence = 0;
    let chat = null;
    let conversationEpoch = 0;
    let lastClearedConversationId = '';

    function text(value) {
        return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
    }

    function element(tag, className, value) {
        const node = document.createElement(tag);
        node.className = className;
        if (value !== undefined) {
            node.textContent = text(value);
        }
        return node;
    }

    function validAction(action) {
        return action?.type === 'msgraph_pending_action'
            && typeof action.id === 'string' && action.id.trim()
            && !['.', '..'].includes(action.id);
    }

    function needsFullReview(action) {
        return action.review_details_required === true || action.summary?.body_preview_truncated === true;
    }

    function detailPath(id, conversationId = '') {
        const path = `${apiPath}/${encodeURIComponent(id)}`;
        return conversationId ? `${path}?${new URLSearchParams({ conversation_id: conversationId })}` : path;
    }

    function hydrateAuth(entry, action, authoritative) {
        if (action.viewer_is_owner === false) {
            entry.auth = null;
            entry.authAcknowledgedVersion = null;
        } else if (action.auth_required === true) {
            entry.auth = action.version && entry.authAcknowledgedVersion === action.version ? null : {
                auth_required: true,
                sources: Array.isArray(action.sources) ? action.sources
                    : [action.graph_resource_type === 'calendar' ? 'calendar' : 'email'],
                scopes: Array.isArray(action.scopes) ? action.scopes : [],
            };
        } else if (authoritative && action.auth_required === false) {
            entry.auth = null;
        }
    }

    function safeWebLink(value) {
        try {
            const url = new URL(value);
            return url.protocol === 'https:' && !url.username && !url.password ? url.href : '';
        } catch {
            return '';
        }
    }

    function dateTime(value) {
        const date = new Date(value);
        return value && Number.isFinite(date.getTime()) ? date.toLocaleString() : text(value);
    }

    function countdownText(action) {
        const due = Date.parse(action.auto_send_at_utc);
        if (!Number.isFinite(due)) {
            return 'The scheduled time is unavailable. Refresh status to check it.';
        }
        const seconds = Math.max(0, Math.ceil((due - Date.now()) / 1000));
        return seconds
            ? `Scheduled in ${Math.floor(seconds / 60)}m ${seconds % 60}s.`
            : 'Scheduled time reached. Waiting for the server delivery status.';
    }

    function requestJson(path, options) {
        if (!window.SimpleChatM365Approvals?.requestJson) {
            return Promise.reject(new Error('Microsoft 365 controls are unavailable. Reload before trying again.'));
        }
        return window.SimpleChatM365Approvals.requestJson(path, options);
    }

    function notify(entry, focus = false) {
        const focusTarget = Array.from(entry.views).find(view => view.card.contains(document.activeElement))
            || entry.views.values().next().value;
        entry.views.forEach(view => view.render(focus && view === focusTarget));
    }

    function remember(action, authoritative = false) {
        if (!validAction(action)) {
            return null;
        }
        let entry = entries.get(action.id);
        let restoreFullReview = false;
        if (!entry) {
            entry = {
                action, views: new Set(), oldVersions: new Set(), busy: false,
                refreshPromise: null, needsRefresh: false, denied: false, auth: null,
                authAcknowledgedVersion: null, viewConversationId: '',
                reviewing: false, fullDetailsVersion: null, approval: null, approvalBusy: false,
                notice: '', tone: 'info', requestSequence: 0, nextRefreshAt: 0,
            };
            entries.set(action.id, entry);
        } else {
            const previous = entry.action;
            const older = Date.parse(action.updated_at) < Date.parse(previous.updated_at);
            const terminalRegression = !authoritative && !actionableStatuses.has(previous.status)
                && actionableStatuses.has(action.status);
            if (older || terminalRegression || (action.version !== previous.version && entry.oldVersions.has(action.version))) {
                return entry;
            }
            if (previous.version && previous.version !== action.version) {
                entry.oldVersions.add(previous.version);
                entry.fullDetailsVersion = null;
                entry.authAcknowledgedVersion = null;
                entry.auth = null;
            }
            restoreFullReview = needsFullReview(action) && Boolean(action.version)
                && entry.fullDetailsVersion === action.version;
            entry.action = action;
        }
        if (authoritative) {
            entry.needsRefresh = false;
            if (action.review_details_required === false && !needsFullReview(action)
                && typeof action.summary?.body_preview === 'string') {
                entry.fullDetailsVersion = action.version;
            }
        }
        hydrateAuth(entry, action, authoritative);
        notify(entry);
        if (restoreFullReview && !entry.busy && entry.views.size) {
            // Reauthorize details rather than restoring permissions from a cached full-body response.
            void refreshAction(entry);
        }
        return entry;
    }

    function actionFromResponse(payload, id) {
        if (!validAction(payload?.pending_action) || payload.pending_action.id !== id) {
            throw new Error('The saved action could not be verified. Refresh its status before trying again.');
        }
        return payload.pending_action;
    }

    async function refreshAction(entry, { focus = false, clearNotice = false, acknowledgeAuthVersion = null } = {}) {
        const reviewedVersion = acknowledgeAuthVersion || entry.action.version;
        if (entry.refreshPromise) {
            if (!clearNotice) {
                return entry.refreshPromise;
            }
            await entry.refreshPromise;
            if (entries.get(entry.action.id) !== entry) {
                return null;
            }
            return refreshAction(entry, { focus, clearNotice, acknowledgeAuthVersion: reviewedVersion });
        }
        const requestSequence = ++entry.requestSequence;
        entry.nextRefreshAt = Date.now() + 15000;
        entry.refreshPromise = (async () => {
            try {
                const conversationId = entry.action.viewer_is_owner === false
                    ? text(entry.viewConversationId || entry.action.conversation_id) : '';
                const payload = await requestJson(detailPath(entry.action.id, conversationId));
                if (entries.get(entry.action.id) !== entry || requestSequence !== entry.requestSequence) {
                    return null;
                }
                const action = actionFromResponse(payload, entry.action.id);
                remember(action, true);
                entry.denied = false;
                if (clearNotice) {
                    if (entry.action.viewer_is_owner !== false && reviewedVersion && entry.action.version === reviewedVersion) {
                        entry.authAcknowledgedVersion = reviewedVersion;
                        entry.auth = null;
                    }
                    entry.notice = 'Current server status loaded. Review the saved action before choosing Send or Cancel.';
                    entry.tone = 'info';
                }
                notify(entry, focus);
                return action;
            } catch (error) {
                if (entries.get(entry.action.id) === entry && requestSequence === entry.requestSequence) {
                    entry.needsRefresh = true;
                    entry.denied = error.status === 403 || error.status === 404;
                    entry.notice = error.status === 403
                        ? 'You do not have permission to access this action. No action was sent.'
                        : 'The current action status could not be checked. Refresh status before trying again.';
                    entry.tone = 'warning';
                    if (error.status === 401 || error.payload?.auth_required === true) {
                        entry.authAcknowledgedVersion = null;
                        entry.auth = error.payload || {};
                    }
                    notify(entry, focus);
                }
                return null;
            } finally {
                entry.refreshPromise = null;
            }
        })();
        return entry.refreshPromise;
    }

    function canChange(entry) {
        return !entry.busy && !entry.approvalBusy && !entry.needsRefresh && !entry.denied
            && entry.action.viewer_is_owner !== false
            && typeof entry.action.version === 'string' && Boolean(entry.action.version)
            && actionableStatuses.has(entry.action.status);
    }

    function sendRoute(action) {
        if (action.viewer_is_owner === false || action.requires_recreation === true || needsFullReview(action)) {
            return '';
        }
        return action.can_send_now === true ? 'send-now' : action.can_approve === true ? 'approve' : '';
    }

    async function reviewFullMessage(entry, triggerView) {
        if (entry.busy || entry.reviewing || entry.approvalBusy) {
            return;
        }
        entry.reviewing = true;
        entry.notice = 'Loading the complete saved content for review. This review does not send the action.';
        entry.tone = 'info';
        notify(entry);
        const action = await refreshAction(entry);
        const complete = action && !needsFullReview(action) && typeof action.summary?.body_preview === 'string';
        entry.reviewing = false;
        if (complete) {
            entry.detailVersion = entry.action.version;
            entry.notice = 'Complete saved content loaded. Review the recipients and full content before sending.';
            entry.tone = 'info';
        } else if (action) {
            entry.needsRefresh = true;
            entry.notice = 'The complete saved content could not be verified. Review full details again before sending.';
            entry.tone = 'warning';
        }
        notify(entry, !complete);
        if (complete) {
            entry.views.forEach(view => view.expandReview());
            triggerView.card.querySelector('summary')?.focus();
        }
    }

    async function reviewSharing(entry) {
        if (!entry.approval || entry.approvalBusy || !actionableStatuses.has(entry.action.status)) {
            return;
        }
        entry.approvalBusy = true;
        notify(entry);
        try {
            const api = window.SimpleChatM365Approvals;
            if (!api?.openApprovals) {
                throw new Error('The sharing dialog is unavailable. Review the saved decision in Approvals, then refresh this action.');
            }
            let refreshed = false;
            const payload = entry.approval.approvals || entry.approval.approval || !entry.approval.approval_id
                ? entry.approval
                : { ...entry.approval, approvals: [{ id: entry.approval.approval_id }] };
            const result = await api.openApprovals(payload, {
                refreshOnly: true,
                onRefresh: async () => {
                    const action = await refreshAction(entry);
                    if (!action) {
                        throw new Error('Decisions were saved, but the action status could not be checked. Retry refresh; nothing will be resent.');
                    }
                    refreshed = true;
                },
            });
            if (!refreshed) {
                refreshed = Boolean(await refreshAction(entry));
            }
            const decided = result.status === 'decided'
                || (Array.isArray(result.approvals) && result.approvals.length > 0
                    && result.approvals.every(approval => approval.status === 'approved'));
            if (decided) {
                entry.approval = null;
            }
            if (refreshed) {
                entry.notice = decided
                    ? 'Sharing decisions saved. Review this same action and its schedule; select Send again if allowed. The action was not retried.'
                    : 'Sharing review is still pending. Nothing was sent; reopen the saved sharing decision when ready.';
                entry.tone = 'info';
            }
        } catch (error) {
            entry.notice = error.message || 'The sharing decision could not be checked. No action was retried.';
            entry.tone = 'warning';
        } finally {
            entry.approvalBusy = false;
            notify(entry, true);
        }
    }

    async function submit(entry, operation) {
        const allowed = operation === 'cancel'
            ? entry.action.can_cancel === true
            : Boolean(sendRoute(entry.action)) && !entry.auth && !entry.approval;
        if (!canChange(entry) || !allowed) {
            return;
        }
        const version = entry.action.version;
        entry.busy = true;
        entry.notice = operation === 'cancel' ? 'Cancelling this saved action…' : 'Submitting this saved action…';
        entry.tone = 'info';
        ++entry.requestSequence;
        notify(entry);
        try {
            await requestJson('/api/m365/preferences');
            await entry.refreshPromise;
            const payload = await requestJson(`${apiPath}/${encodeURIComponent(entry.action.id)}/${operation}`, {
                method: 'POST', body: { expected_version: version },
            });
            if (payload.approval_required === true) {
                const error = new Error('A Microsoft 365 sharing decision is required.');
                error.payload = payload;
                throw error;
            }
            remember(actionFromResponse(payload, entry.action.id), true);
            entry.auth = null;
            entry.denied = false;
            entry.notice = operation === 'cancel'
                ? 'Cancellation checked. The server status below is authoritative; this does not recall an already sent item.'
                : 'Send request checked. Review the server status and delivery note below.';
            entry.tone = 'info';
            window.dispatchEvent(new CustomEvent('m365-pending-action-updated', {
                detail: { pendingAction: entry.action },
            }));
        } catch (error) {
            const payload = error.payload || {};
            if (validAction(payload.pending_action) && payload.pending_action.id === entry.action.id) {
                remember(payload.pending_action, true);
            }
            entry.tone = 'warning';
            if (payload.approval_required === true) {
                entry.approval = payload;
                entry.notice = 'Review the saved Microsoft 365 sharing decision before sending. Approval will only refresh this action.';
                await reviewSharing(entry);
            } else if (error.status === 401 || payload.auth_required === true) {
                entry.authAcknowledgedVersion = null;
                entry.auth = payload;
                entry.notice = 'Microsoft 365 sign-in is required. Reconnect, review this same saved action, then select Send again. Signing in does not send it.';
            } else if (error.status === 403) {
                entry.denied = true;
                entry.notice = 'You do not have permission to change this action. Refresh status to check your current access.';
            } else if (error.status === 409) {
                entry.notice = 'This action changed or is already being processed. Review its current status and details before making another choice.';
                if (!validAction(payload.pending_action)) {
                    entry.needsRefresh = true;
                    await refreshAction(entry);
                }
            } else {
                entry.needsRefresh = true;
                entry.notice = 'The response was not confirmed. Checking the current server status; the send will not be retried automatically.';
                notify(entry);
                const refreshed = await refreshAction(entry);
                if (refreshed) {
                    entry.notice = 'The response was not confirmed. Current server status has been refreshed. Review it before making another choice; no send was retried automatically.';
                }
            }
        } finally {
            entry.busy = false;
            notify(entry, true);
            if (!entry.views.size) {
                entries.delete(entry.action.id);
            }
        }
    }

    function statusDescription(action) {
        const labels = {
            pending: 'Pending — not sent.',
            scheduled: 'Scheduled — not yet sent.',
            review_required: 'Review required — not sent.',
            sending: 'Sending — the Microsoft 365 request is in progress. Do not submit it again.',
            sent: action.graph_resource_type === 'mail' || action.operation === 'send_mail'
                ? 'Accepted for sending — recipient delivery is not confirmed.'
                : 'Sent — calendar invitation created.',
            cancelled: 'Cancelled — no further delivery is scheduled for this action.',
            canceled: 'Cancelled — no further delivery is scheduled for this action.',
            failed: 'Failed — review the delivery note before creating another action.',
            recovery_required: 'Delivery outcome needs recovery. Check Microsoft 365 before creating or sending another action.',
        };
        return Object.prototype.hasOwnProperty.call(labels, action.status)
            ? labels[action.status]
            : 'The delivery status is not recognized. Refresh status before continuing.';
    }

    function addFact(list, label, value) {
        const content = Array.isArray(value) ? value.map(text).filter(Boolean).join(', ') : text(value);
        if (!content) {
            return;
        }
        list.append(element('dt', 'col-sm-3', label), element('dd', 'col-sm-9 text-break', content));
    }

    function mount(container, action, options = {}) {
        const entry = remember(action, options.authoritative === true);
        if (!container || !entry) {
            return null;
        }
        const card = element('article', 'm365-pending-action-card card my-2 text-break');
        card.dataset.pendingActionId = action.id;
        const headingId = `m365-pending-heading-${++sequence}`;
        card.setAttribute('aria-labelledby', headingId);
        const lifecycle = new AbortController();
        let timer = null;
        let countdown = null;
        let destroyed = false;

        function button(label, control, handler, className = 'btn btn-sm btn-outline-secondary') {
            const node = element('button', className, label);
            node.type = 'button';
            node.dataset.m365Control = control;
            node.addEventListener('click', handler);
            return node;
        }

        function tick() {
            if (destroyed || !card.isConnected) {
                return;
            }
            const current = entry.action;
            const due = Date.parse(current.auto_send_at_utc);
            const scheduled = current.will_auto_send === true && actionableStatuses.has(current.status) && Number.isFinite(due);
            if (countdown && scheduled) {
                countdown.textContent = countdownText(current);
            }
            if (!entry.busy && ((scheduled && due <= Date.now()) || current.status === 'sending')
                && Date.now() >= entry.nextRefreshAt) {
                void refreshAction(entry);
            }
        }

        async function reconnect() {
            if (entry.busy || !window.SimpleChatM365Connect?.reconnectPendingAction) {
                return;
            }
            entry.busy = true;
            const reconnectVersion = entry.action.version;
            entry.notice = 'Opening sign-in for this saved action. No chat request will be resumed and nothing will be sent.';
            entry.tone = 'info';
            notify(entry);
            try {
                const sources = Array.isArray(entry.auth?.sources) ? entry.auth.sources
                    : [entry.action.graph_resource_type === 'calendar' ? 'calendar' : 'email'];
                await window.SimpleChatM365Connect.reconnectPendingAction({ sources, signal: lifecycle.signal });
                if (destroyed) {
                    return;
                }
                await refreshAction(entry, { clearNotice: true, acknowledgeAuthVersion: reconnectVersion });
            } catch (error) {
                if (!destroyed) {
                    entry.notice = error.message || 'Sign-in was not confirmed. No action was sent.';
                    entry.tone = 'warning';
                }
            } finally {
                entry.busy = false;
                if (!destroyed) {
                    notify(entry, true);
                }
                if (!entry.views.size) {
                    entries.delete(entry.action.id);
                }
            }
        }

        function render(focus = false) {
            if (destroyed) {
                return;
            }
            const focusedControl = card.contains(document.activeElement) ? document.activeElement.dataset.m365Control : null;
            const bodyOpen = card.querySelector('details')?.open || false;
            const current = entry.action;
            const summary = current.summary || {};
            const body = element('div', 'card-body p-3');
            const heading = element('h3', 'h6 mb-2',
                current.graph_resource_type === 'calendar' ? 'Microsoft 365 calendar invitation' : 'Microsoft 365 email');
            heading.id = headingId;
            const status = element('p', 'm365-pending-action-status small mb-2', statusDescription(current));
            status.setAttribute('role', 'status');
            status.setAttribute('aria-live', 'polite');
            status.tabIndex = -1;
            body.append(heading, element('h4', 'h6 text-break', current.subject || summary.subject || '(No subject)'), status);
            const facts = element('dl', 'row small mb-2');
            addFact(facts, 'To', summary.to_recipients);
            addFact(facts, 'CC', summary.cc_recipients);
            addFact(facts, 'BCC', summary.bcc_recipients);
            addFact(facts, 'Attendees', summary.attendee_recipients);
            // Outlook time-zone names are not necessarily IANA names. Preserve the reviewed wall time and zone.
            addFact(facts, 'Start', summary.start_datetime);
            addFact(facts, 'End', summary.end_datetime);
            addFact(facts, 'Time zone', summary.timezone);
            addFact(facts, 'Location', summary.location);
            if (typeof summary.teams_meeting_requested === 'boolean') {
                addFact(facts, 'Teams meeting', summary.teams_meeting_requested ? 'Requested' : 'Not requested');
            }
            body.appendChild(facts);
            if (typeof summary.body_preview === 'string') {
                const details = element('details', 'mb-3');
                details.open = bodyOpen;
                const disclosure = element('summary', 'small', needsFullReview(current) ? 'Message preview' : 'Review message body');
                disclosure.dataset.m365Control = 'review';
                const preview = element('pre', 'small mt-2 mb-0 text-break', summary.body_preview);
                preview.style.whiteSpace = 'pre-wrap';
                details.append(disclosure, preview);
                if (text(summary.content_type).toLowerCase() === 'html') {
                    details.appendChild(element('p', 'small text-muted mt-1 mb-0', 'HTML content is displayed as text, not executed.'));
                }
                details.addEventListener('toggle', () => {
                    if (details.open && !entry.busy && !needsFullReview(entry.action) && entry.detailVersion !== entry.action.version) {
                        entry.detailVersion = entry.action.version;
                        void refreshAction(entry);
                    }
                });
                body.appendChild(details);
            }
            if (needsFullReview(current)) {
                const length = Number.isSafeInteger(summary.body_length) && summary.body_length >= 0
                    ? ` (${summary.body_length.toLocaleString()} characters total)` : '';
                body.appendChild(element('p', 'alert alert-info small',
                    `This is a shortened preview${length}. Review the complete saved content before sending.`));
            }
            if ((actionableStatuses.has(current.status) && (current.requires_recreation === true || current.requires_review === true))
                || current.review_message) {
                body.appendChild(element('p', 'alert alert-warning small',
                    current.review_message || (current.requires_recreation
                        ? 'This legacy action cannot be safely sent. Review and recreate it if still needed, or cancel it.'
                        : 'Review the refreshed action details before sending.')));
            }
            if (current.error) {
                body.appendChild(element('p', 'alert alert-warning small', current.error));
            }
            if (current.delivery_note) {
                body.appendChild(element('p', 'alert alert-info small', current.delivery_note));
            }
            countdown = null;
            if (current.will_auto_send === true && actionableStatuses.has(current.status)) {
                body.appendChild(element('p', 'small mb-1', `Server-scheduled delivery: ${dateTime(current.auto_send_at_utc)}.`));
                countdown = element('p', 'm365-pending-action-countdown small text-muted mb-2', countdownText(current));
                body.appendChild(countdown);
            }
            if (entry.notice) {
                const notice = element('p', `alert alert-${entry.tone} small mb-2`, entry.notice);
                notice.setAttribute('role', entry.tone === 'warning' ? 'alert' : 'status');
                notice.tabIndex = -1;
                body.appendChild(notice);
            }
            const controls = element('div', 'm365-pending-action-controls d-flex flex-wrap gap-2');
            if (needsFullReview(current)) {
                const review = button(
                    current.graph_resource_type === 'calendar' ? 'Review full invitation' : 'Review full message',
                    'review-full', () => { void reviewFullMessage(entry, view); }, 'btn btn-sm btn-outline-primary',
                );
                review.disabled = entry.busy || entry.reviewing || entry.approvalBusy;
                controls.appendChild(review);
            }
            if (actionableStatuses.has(current.status)) {
                const route = sendRoute(current);
                if (route) {
                    const send = button(current.action_mode === 'delayed' ? 'Send now' : 'Send', 'send',
                        () => { void submit(entry, route); }, 'btn btn-sm btn-primary');
                    send.disabled = !canChange(entry) || Boolean(entry.auth) || Boolean(entry.approval);
                    controls.appendChild(send);
                }
                if (current.can_cancel === true && current.viewer_is_owner !== false) {
                    const cancel = button('Cancel', 'cancel', () => { void submit(entry, 'cancel'); });
                    cancel.disabled = !canChange(entry);
                    controls.appendChild(cancel);
                }
                if (!route && (current.can_cancel !== true || current.viewer_is_owner === false)
                    && !current.requires_recreation && !needsFullReview(current)) {
                    body.appendChild(element('p', 'small text-muted',
                        current.workflow_id
                            ? 'Only the selected Run as user can send or cancel this action.'
                            : 'Only the action owner can send or cancel this action. This view is read-only.'));
                }
            }
            if (entry.approval && actionableStatuses.has(current.status)) {
                const sharing = button('Review sharing decision', 'sharing', () => { void reviewSharing(entry); },
                    'btn btn-sm btn-outline-primary');
                sharing.disabled = entry.busy || entry.approvalBusy;
                const approvals = element('a', 'btn btn-sm btn-link', 'Open Approvals');
                approvals.href = '/approvals';
                approvals.target = '_blank';
                approvals.rel = 'noopener noreferrer';
                controls.append(sharing, approvals);
            }
            if (entry.auth && current.viewer_is_owner !== false) {
                if (!current.workflow_id && window.SimpleChatM365Connect?.reconnectPendingAction) {
                    const connect = button('Reconnect Microsoft 365', 'connect', () => { void reconnect(); }, 'btn btn-sm btn-outline-primary');
                    connect.disabled = entry.busy;
                    controls.appendChild(connect);
                }
                const profile = element('a', 'btn btn-sm btn-link', current.workflow_id ? 'Reconnect workflow account in Profile' : 'Open Profile connection settings');
                profile.href = '/profile?tab=settings';
                profile.target = '_blank';
                profile.rel = 'noopener noreferrer';
                controls.appendChild(profile);
            }
            const refresh = button('Refresh status', 'refresh', () => { void refreshAction(entry, { focus: true, clearNotice: true }); });
            refresh.disabled = entry.busy;
            controls.appendChild(refresh);
            const webLink = safeWebLink(current.web_link);
            if (webLink) {
                const link = element('a', 'btn btn-sm btn-link', 'Open in Microsoft 365');
                link.href = webLink;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                controls.appendChild(link);
            }
            if (options.showConversationLink && current.conversation_id) {
                const link = element('a', 'btn btn-sm btn-link', 'Open conversation');
                link.href = `/chats?${new URLSearchParams({ conversationId: current.conversation_id })}`;
                controls.appendChild(link);
            }
            body.appendChild(controls);
            card.setAttribute('aria-busy', String(entry.busy || entry.reviewing || entry.approvalBusy));
            card.replaceChildren(body);
            if (timer) {
                window.clearInterval(timer);
                timer = null;
            }
            if ((current.will_auto_send === true && actionableStatuses.has(current.status)) || current.status === 'sending') {
                timer = window.setInterval(tick, 1000);
            }
            if (focus) {
                (body.querySelector('[role="alert"]') || status).focus();
            } else if (focusedControl) {
                const target = Array.from(body.querySelectorAll('[data-m365-control]'))
                    .find(node => node.dataset.m365Control === focusedControl && !node.disabled);
                (target || status).focus();
            }
        }

        const view = {
            card, render,
            update(next) { remember(next); },
            expandReview() {
                const details = card.querySelector('details');
                if (details) {
                    details.open = true;
                }
            },
            destroy() {
                destroyed = true;
                lifecycle.abort();
                window.clearInterval(timer);
                entry.views.delete(view);
                card.remove();
                if (!entry.views.size && !entry.busy) {
                    entries.delete(entry.action.id);
                }
            },
        };
        entry.views.add(view);
        if (options.refreshOnFocus) {
            const refresh = () => { void refreshAction(entry); };
            window.addEventListener('focus', refresh, { signal: lifecycle.signal });
            window.addEventListener('online', refresh, { signal: lifecycle.signal });
        }
        container.appendChild(card);
        render();
        return view;
    }

    function createCollection(root, query, { chatView = false } = {}) {
        const lifecycle = new AbortController();
        const views = new Map();
        const references = new Map();
        const messages = new Map();
        const pendingReferences = new Set();
        const referenceFailures = new Map();
        let loadPromise = null;
        let retryHandle = null;
        let retryAttempt = 0;
        let continuationToken = '';
        let disposed = false;
        let hasError = false;
        let referenceErrorVisible = false;
        root.replaceChildren();
        if (chatView) {
            root.append(
                element('h2', 'h6', 'Microsoft 365 outgoing actions for this conversation'),
                element('p', 'small text-muted', 'Saved actions without a visible originating message appear here. Opening a card never sends it.'),
            );
        }
        const status = element('p', 'small d-none');
        status.setAttribute('role', 'status');
        status.setAttribute('aria-live', 'polite');
        const items = element('div', 'm365-pending-action-list');
        const more = element('button', 'btn btn-sm btn-outline-secondary d-none', 'Load more outgoing actions');
        more.type = 'button';
        const refresh = element('button', 'btn btn-sm btn-outline-secondary ms-2', 'Refresh outgoing actions');
        refresh.type = 'button';
        root.append(status, items, more, refresh);

        function updateVisibility() {
            root.classList.toggle('d-none', chatView && !items.children.length && !hasError && !continuationToken);
        }

        function showError(message, referenceError = false) {
            hasError = true;
            referenceErrorVisible = referenceError;
            status.className = 'alert alert-warning small';
            status.setAttribute('role', 'alert');
            status.textContent = message;
            updateVisibility();
        }

        function scheduleRetry() {
            if (disposed || retryHandle !== null || retryAttempt >= retryDelaysMs.length) {
                return;
            }
            const delay = retryDelaysMs[retryAttempt];
            retryAttempt += 1;
            retryHandle = window.setTimeout(() => {
                retryHandle = null;
                void load();
            }, delay);
        }

        function place(id) {
            const view = views.get(id);
            if (!view || !chatView) {
                return;
            }
            const reference = references.get(id) || {};
            let anchor = messages.get(reference.messageId) || messages.get(reference.userMessageId)
                || messages.get(reference.fallbackMessageId);
            if (!anchor?.isConnected && reference.requestId) {
                anchor = Array.from(messages.values()).reverse()
                    .find(node => node.isConnected && node.dataset.m365RequestId === reference.requestId);
            }
            let destination = items;
            if (anchor?.isConnected) {
                destination = anchor.querySelector('.m365-message-actions');
                if (!destination) {
                    destination = element('section', 'm365-message-actions mt-2');
                    destination.setAttribute('aria-label', 'Microsoft 365 actions for this message');
                    (anchor.querySelector('.message-bubble') || anchor).appendChild(destination);
                }
            }
            if (view.card.parentElement !== destination) {
                const previous = view.card.parentElement;
                destination.appendChild(view.card);
                if (previous?.classList.contains('m365-message-actions')) {
                    previous.classList.toggle('d-none', !previous.children.length);
                }
            }
            destination.classList.remove('d-none');
            updateVisibility();
        }

        function add(action, reference = {}, { authoritative = false, history = false } = {}) {
            if (disposed || !validAction(action)) {
                return;
            }
            const savedReference = references.get(action.id) || {};
            references.set(action.id, {
                ...savedReference,
                ...Object.fromEntries(Object.entries(reference).filter(([, value]) => Boolean(value))),
            });
            const entry = remember(action, authoritative);
            if (query.conversation_id) {
                entry.viewConversationId = text(query.conversation_id);
            }
            referenceFailures.delete(action.id);
            if (referenceErrorVisible && !referenceFailures.size) {
                hasError = false;
                referenceErrorVisible = false;
                status.textContent = '';
                status.classList.add('d-none');
            }
            if (history && !authoritative) {
                entry.needsRefresh = true;
            }
            if (!views.has(action.id)) {
                views.set(action.id, mount(items, entry.action, { showConversationLink: !chatView }));
            } else {
                notify(entry);
            }
            place(action.id);
            if (history && !needsFullReview(entry.action)) {
                void refreshAction(entry);
            }
            updateVisibility();
        }

        function loadReference(id, reference) {
            if (disposed || pendingReferences.has(id)) {
                return;
            }
            pendingReferences.add(id);
            void requestJson(detailPath(id, text(query.conversation_id)), { signal: lifecycle.signal })
                .then(result => {
                    if (!disposed) {
                        add(actionFromResponse(result, id), reference, { authoritative: true });
                    }
                })
                .catch(error => {
                    if (!disposed && error.name !== 'AbortError') {
                        referenceFailures.set(id, reference);
                        showError('A saved Microsoft 365 action could not be recovered. Refresh outgoing actions to check its status.', true);
                    }
                })
                .finally(() => pendingReferences.delete(id));
        }

        async function load(token = '') {
            if (disposed || loadPromise) {
                return loadPromise;
            }
            more.disabled = true;
            refresh.disabled = true;
            referenceFailures.forEach((reference, id) => loadReference(id, reference));
            loadPromise = (async () => {
                try {
                    const params = new URLSearchParams({ ...query, limit: '30' });
                    if (token) {
                        params.set('continuation_token', token);
                    }
                    const payload = await requestJson(`${apiPath}?${params}`, { signal: lifecycle.signal });
                    if (disposed) {
                        return;
                    }
                    if (!Array.isArray(payload.pending_actions) || !payload.pending_actions.every(validAction)) {
                        throw new Error('Microsoft 365 outgoing actions could not be loaded.');
                    }
                    if (!token && !chatView) {
                        const returnedIds = new Set(payload.pending_actions.map(action => action.id));
                        views.forEach((view, id) => {
                            if (!returnedIds.has(id)) {
                                view.destroy();
                                views.delete(id);
                            }
                        });
                    }
                    payload.pending_actions.forEach(action => add(action, {}, { authoritative: true }));
                    continuationToken = typeof payload.continuation_token === 'string' ? payload.continuation_token : '';
                    retryAttempt = 0;
                    more.classList.toggle('d-none', !continuationToken);
                    hasError = false;
                    referenceErrorVisible = false;
                    status.className = 'small text-muted';
                    status.setAttribute('role', 'status');
                    status.textContent = !views.size ? 'No Microsoft 365 outgoing actions are waiting.' : '';
                    status.classList.toggle('d-none', Boolean(views.size));
                    if (referenceFailures.size) {
                        showError('A saved Microsoft 365 action could not be recovered. Refresh outgoing actions to check its status.', true);
                    }
                    updateVisibility();
                } catch (error) {
                    if (!disposed && error.name !== 'AbortError') {
                        views.forEach((view, id) => {
                            const entry = entries.get(id);
                            if (entry) {
                                entry.needsRefresh = true;
                                entry.denied = error.status === 403;
                                notify(entry);
                            }
                        });
                        const hasKnownActionState = views.size > 0 || referenceFailures.size > 0;
                        if (error.status === 403 || !chatView || hasKnownActionState) {
                            showError(error.status === 403
                                ? 'You do not have permission to view outgoing actions for this conversation.'
                                : 'Outgoing actions could not be loaded. Refresh to recover saved actions; this is not an empty inbox.');
                        } else {
                            hasError = false;
                            status.className = 'small text-muted d-none';
                            status.textContent = '';
                            updateVisibility();
                        }
                        if (error.status !== 403) {
                            scheduleRetry();
                        }
                    }
                } finally {
                    loadPromise = null;
                    more.disabled = false;
                    refresh.disabled = false;
                }
            })();
            return loadPromise;
        }

        function trackMessage(node, payload, { history = false } = {}) {
            const messageId = text(payload.id || payload.message_id || node.dataset.messageId);
            const requestId = text(payload.metadata?.m365_request_id || payload.request_id);
            messages.set(messageId, node);
            if (requestId) {
                node.dataset.m365RequestId = requestId;
            }
            const reference = { messageId, requestId };
            const actions = Array.isArray(payload.m365_pending_actions) ? payload.m365_pending_actions : [];
            actions.forEach(action => add(action, reference, { history }));
            const ids = Array.isArray(payload.metadata?.m365_pending_action_ids) ? payload.metadata.m365_pending_action_ids : [];
            ids.filter(id => typeof id === 'string' && id && !['.', '..'].includes(id)).forEach(id => {
                references.set(id, { ...references.get(id), ...reference });
                if (views.has(id)) {
                    const entry = entries.get(id);
                    entry.needsRefresh = true;
                    notify(entry);
                    if (!needsFullReview(entry.action)) {
                        void refreshAction(entry);
                    }
                    return;
                }
                loadReference(id, reference);
            });
            views.forEach((view, id) => place(id));
        }

        more.addEventListener('click', () => { void load(continuationToken); });
        refresh.addEventListener('click', () => { void load(); });
        window.addEventListener('focus', () => { void load(); }, { signal: lifecycle.signal });
        window.addEventListener('online', () => { void load(); }, { signal: lifecycle.signal });
        return {
            add, load, trackMessage,
            async refresh() {
                if (loadPromise) {
                    await loadPromise;
                }
                return load();
            },
            prepareHistory() {
                messages.clear();
                views.forEach(view => items.appendChild(view.card));
                updateVisibility();
            },
            destroy() {
                disposed = true;
                lifecycle.abort();
                if (retryHandle !== null) {
                    window.clearTimeout(retryHandle);
                    retryHandle = null;
                }
                views.forEach(view => view.destroy());
                views.clear();
                root.replaceChildren();
                root.classList.add('d-none');
            },
        };
    }

    function disposeConversation() {
        lastClearedConversationId = chat?.id || lastClearedConversationId;
        conversationEpoch += 1;
        chat?.collection.destroy();
        chat = null;
    }

    function setConversation(conversationId) {
        const id = text(conversationId);
        if (chat?.id === id) {
            return chat;
        }
        if (chat || !id) {
            disposeConversation();
        }
        const chatbox = document.getElementById('chatbox');
        if (!id || !chatbox) {
            return null;
        }
        let root = document.getElementById('chat-m365-pending-actions');
        if (!root) {
            root = element('section', 'px-3 pt-3 d-none');
            root.id = 'chat-m365-pending-actions';
            root.setAttribute('aria-label', 'Conversation outgoing Microsoft 365 actions');
            chatbox.before(root);
        }
        chat = { id, collection: createCollection(root, { conversation_id: id }, { chatView: true }) };
        void chat.collection.load();
        return chat;
    }

    function handleChatPayload(payload = {}, options = {}) {
        if (options.conversationEpoch !== undefined && options.conversationEpoch !== conversationEpoch) {
            return;
        }
        const conversationId = text(options.conversationId || payload.conversation_id || window.currentConversationId);
        if (!conversationId || (window.currentConversationId && conversationId !== window.currentConversationId)) {
            return;
        }
        const active = setConversation(conversationId);
        if (!active) {
            return;
        }
        const reference = {
            messageId: text(options.messageId || (payload.type === 'm365_pending_action' ? '' : payload.message_id)),
            userMessageId: text(payload.user_message_id || options.userMessageId),
            fallbackMessageId: text(options.userMessageId),
            requestId: text(payload.request_id || payload.metadata?.m365_request_id || options.requestId),
        };
        const actions = Array.isArray(payload.m365_pending_actions) ? payload.m365_pending_actions : [];
        if (validAction(payload.pending_action)) {
            active.collection.add(payload.pending_action, reference);
        }
        actions.forEach(action => active.collection.add(action, reference));
    }

    function trackMessage(node, payload = {}, options = {}) {
        const conversationId = text(node.dataset.conversationId || payload?.conversation_id || window.currentConversationId);
        if (!chat && conversationId === lastClearedConversationId) {
            return;
        }
        if (window.currentConversationId && conversationId !== window.currentConversationId) {
            return;
        }
        setConversation(conversationId)?.collection.trackMessage(node, payload || {}, options);
    }

    function prepareHistory(conversationId) {
        if ((!chat && conversationId === lastClearedConversationId)
            || (window.currentConversationId && conversationId !== window.currentConversationId)) {
            return;
        }
        setConversation(conversationId)?.collection.prepareHistory();
    }

    function refreshConversation(conversationId = chat?.id) {
        if (chat?.id === conversationId) {
            return chat.collection.refresh();
        }
        return Promise.resolve();
    }

    function initialize() {
        const outgoing = document.getElementById('m365-outgoing-actions');
        if (outgoing) {
            const collection = createCollection(outgoing, { active_only: '1' });
            window.addEventListener('pagehide', () => collection.destroy(), { once: true });
            void collection.load();
        }
    }

    window.addEventListener('chat:conversation-context-changed', event => {
        setConversation(event.detail?.conversationId);
    });
    window.addEventListener('pagehide', disposeConversation);
    window.addEventListener('pageshow', event => {
        if (event.persisted) {
            initialize();
            setConversation(window.currentConversationId);
        }
    });
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, { once: true });
    } else {
        initialize();
    }
    window.SimpleChatM365PendingActions = Object.freeze({
        mount, setConversation, prepareHistory, handleChatPayload, trackMessage,
        refreshConversation, disposeConversation,
        getConversationEpoch: () => conversationEpoch,
    });
})();
