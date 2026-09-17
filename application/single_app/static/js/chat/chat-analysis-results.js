// chat-analysis-results.js
// Saved Analyze findings supplement the answer; only an authorized complete-record page is read.

const pageSize = 25;
const validationNotices = {
    valid: 'Structural checks passed. Findings are model judgments, not independent factual verification or an exhaustive list of every possible issue.',
    partial: 'Partial analysis: accepted findings only. Counts and totals describe this saved subset; some work or checks remain unresolved.',
    invalid: 'Validation failed. These saved findings are not a validated final result.',
    pending: 'Validation pending. The saved findings are not yet a validated final result.',
    not_validated: 'Not validated. No completed validation is claimed for these saved findings.',
};
let selectedContext = null;
let contextConversationId = null;
let contextRevision = 0;
let contextChosen = false;
let initialized = false;
const views = new Set();

function object(value) {
    return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function count(value) {
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function node(tag, className = '', text = '') {
    const element = document.createElement(tag);
    element.className = className;
    element.textContent = text;
    return element;
}

function activeConversationId() {
    return String(window.currentConversationId || '').trim() || null;
}

function pointer(value) {
    return {
        conversation_id: value.conversation_id,
        message_id: value.message_id,
        result_sha256: value.result_sha256,
    };
}

function sameAnalysis(left, right) {
    return Boolean(left && right && left.conversation_id === right.conversation_id &&
        left.message_id === right.message_id && left.result_sha256 === right.result_sha256);
}

export function readSavedAnalysis(metadata) {
    const value = metadata?.saved_analysis;
    if (!object(value) || value.version !== 'analyze-final-v1' ||
        typeof value.conversation_id !== 'string' || !value.conversation_id.trim() ||
        typeof value.message_id !== 'string' || !value.message_id.trim() ||
        typeof value.result_sha256 !== 'string' || !/^[a-f0-9]{64}$/i.test(value.result_sha256) ||
        !count(value.record_count) || !count(value.source_count) ||
        !Object.prototype.hasOwnProperty.call(validationNotices, value.validation_status)) {
        return null;
    }
    return {
        ...pointer(value),
        version: value.version,
        record_count: value.record_count,
        source_count: value.source_count,
        validation_status: value.validation_status,
        available: value.available !== false,
    };
}

export function syncSavedAnalysisConversation(conversationId = activeConversationId()) {
    const next = String(conversationId || '').trim() || null;
    if (contextConversationId !== next) {
        contextConversationId = next;
        selectedContext = null;
        contextChosen = false;
        contextRevision += 1;
        renderContextNotice();
        disposeSavedAnalysisViews();
    }
}

export function getAnalysisContextRevision() {
    syncSavedAnalysisConversation();
    return contextRevision;
}

export function getSavedAnalysisContext(conversationId = activeConversationId()) {
    syncSavedAnalysisConversation();
    return selectedContext?.conversation_id === conversationId ? pointer(selectedContext) : null;
}

export function clearSavedAnalysisContext() {
    selectedContext = null;
    contextChosen = true;
    contextRevision += 1;
    renderContextNotice();
}

export function selectSavedAnalysis(descriptor, expectedRevision) {
    syncSavedAnalysisConversation();
    const saved = readSavedAnalysis({ saved_analysis: descriptor });
    if (!saved || saved.available === false || saved.conversation_id !== activeConversationId() ||
        (expectedRevision !== undefined && contextRevision !== expectedRevision)) {
        return false;
    }
    selectedContext = pointer(saved);
    contextChosen = true;
    contextRevision += 1;
    renderContextNotice();
    // The previous Analyze choice is not the next turn's source action.
    const action = document.getElementById('document-action-select');
    if (action) {
        action.value = 'none';
    }
    window.dispatchEvent(new CustomEvent('chat:saved-analysis-selected'));
    return true;
}

export function offerSavedAnalysis(message, expectedRevision) {
    if (message?.metadata?.masked || message?.metadata?.masked_ranges?.length) {
        return false;
    }
    return selectSavedAnalysis(readSavedAnalysis(message?.metadata), expectedRevision);
}

export function hydrateSavedAnalysisContext(messages, conversationId, expectedRevision) {
    if (conversationId !== activeConversationId() || contextRevision !== expectedRevision) {
        return;
    }
    if (selectedContext && !messages.some(message => {
        const descriptor = readSavedAnalysis(message?.metadata);
        return descriptor?.available !== false && sameAnalysis(selectedContext, descriptor) &&
            !message.metadata?.masked && !message.metadata?.masked_ranges?.length;
    })) {
        clearSavedAnalysisContext();
    }
    if (contextChosen) {
        return;
    }
    const latest = [...messages].reverse().find(message =>
        ['assistant', 'user'].includes(message.role) && !message.metadata?.is_deleted,
    );
    if (latest?.role === 'assistant') {
        offerSavedAnalysis(latest, expectedRevision);
    }
}

function renderContextNotice() {
    const input = document.getElementById('user-input');
    const parent = document.querySelector('.chat-input-container') || input?.parentElement;
    if (!parent) {
        return;
    }
    let notice = document.getElementById('saved-analysis-context');
    if (!notice) {
        notice = node('div', 'alert alert-secondary py-2 px-3 mb-2 d-none');
        notice.id = 'saved-analysis-context';
        notice.setAttribute('role', 'status');
        notice.setAttribute('aria-live', 'polite');
        const content = node('div', 'd-flex align-items-start gap-2');
        const description = node('span', 'small flex-grow-1',
            'Saved analysis selected. Explaining the saved analysis — not running a new pass over the original sources.');
        const remove = node('button', 'btn-close flex-shrink-0');
        remove.type = 'button';
        remove.setAttribute('aria-label', 'Remove saved analysis context');
        remove.addEventListener('click', () => {
            clearSavedAnalysisContext();
            input?.focus();
        });
        content.append(description, remove);
        notice.append(content);
        parent.prepend(notice);
    }
    notice.classList.toggle('d-none', !selectedContext);
}

export function initializeSavedAnalysis() {
    if (initialized) {
        return;
    }
    initialized = true;
    syncSavedAnalysisConversation();
    renderContextNotice();
    window.addEventListener('chat:conversation-context-changed', event => {
        syncSavedAnalysisConversation(event.detail?.conversationId);
    });
    document.addEventListener('click', event => {
        if (event.target instanceof Element && event.target.closest(
            '#search-documents-btn, #search-web-btn, #source-review-btn, #url-access-btn, ' +
            '#image-generate-btn, #upload-btn, #search-documents-container input, ' +
            '#document-dropdown-menu, #tags-dropdown-menu, #scope-dropdown-menu',
        )) {
            clearSavedAnalysisContext();
        }
    }, true);
    document.addEventListener('change', event => {
        if (event.target instanceof Element && event.target.matches(
            '#document-action-select, #document-select, #doc-scope-select, #tags-select, #file-input',
        )) {
            clearSavedAnalysisContext();
        }
    }, true);
}

export function applySavedAnalysisContext(request) {
    const context = getSavedAnalysisContext(request.conversation_id);
    if (!context) {
        return request;
    }
    const result = {
        ...request,
        analysis_result_context: context,
        hybrid_search: false,
        document_context_requested: false,
        user_workspace_context_enabled: false,
        web_search_enabled: false,
        url_access_enabled: false,
        source_review_enabled: false,
        deep_research_enabled: false,
        image_generation: false,
        selected_document_id: null,
        selected_document_ids: [],
        conversation_task_document_ids: [],
        tags: [],
        doc_scope: 'personal',
        active_group_ids: [],
        active_group_id: null,
        active_public_workspace_ids: [],
        active_public_workspace_id: null,
    };
    ['document_action', 'analyze', 'document_filter_mode', 'orchestration', 'orchestration_context']
        .forEach(key => delete result[key]);
    return result;
}

function unavailableMessage(status) {
    if (status === 409) {
        return 'Saved analysis is stale or has changed. Reopen the conversation to use its current saved result.';
    }
    if (status === 401) {
        return 'Saved analysis unavailable. Sign in again to check access.';
    }
    return 'Saved analysis unavailable. It may have been removed, or access to a contributing source may have changed.';
}

function notices(value) {
    return (Array.isArray(value) ? value : [value]).flatMap(item => {
        const text = typeof item === 'string' ? item : object(item) ? item.message : null;
        return typeof text === 'string' && text.trim() ? [text] : [];
    });
}

function validatePage(page, descriptor, offset) {
    if (!object(page) || page.result_sha256 !== descriptor.result_sha256 || page.offset !== offset ||
        !count(page.total_records) || page.total_records !== descriptor.record_count || !count(page.source_count) ||
        !Array.isArray(page.records) || page.records.length > pageSize ||
        offset + page.records.length > page.total_records ||
        (offset < page.total_records && page.records.length === 0) ||
        (page.next_offset !== null &&
            (page.next_offset !== offset + page.records.length || page.next_offset >= page.total_records)) ||
        (page.next_offset === null && offset + page.records.length < page.total_records) ||
        !object(page.validation) || !Object.prototype.hasOwnProperty.call(validationNotices, page.validation.status) ||
        page.records.some(record => !object(record) || typeof record.record_id !== 'string' ||
            typeof record.document_id !== 'string' || !object(record.source) || !object(record.values) ||
            !Array.isArray(record.evidence_refs) || record.evidence_refs.some(id => typeof id !== 'string'))) {
        throw Object.assign(new Error('Saved analysis response does not match this result.'), { status: 409 });
    }
    return page;
}

export function disposeSavedAnalysisViews() {
    views.forEach(view => view.dispose());
    views.clear();
}

function hideUnavailableActions(message) {
    message.dataset.savedAnalysisUnavailable = 'true';
    message.querySelectorAll('.saved-analysis-downloads, .generated-tabular-outputs-container, .assistant-inline-export-actions, .message-footer')
        .forEach(element => element.classList.add('d-none'));
}

export function hydrateSavedAnalysisResult(message, fullMessage) {
    if (fullMessage?.metadata?.saved_analysis == null) {
        return;
    }
    message.dataset.savedAnalysis = 'true';
    const descriptor = readSavedAnalysis(fullMessage.metadata);
    message._savedAnalysisDescriptor = descriptor;
    const root = node('section', 'saved-analysis-result border rounded p-3 mt-3');
    root.setAttribute('aria-label', 'Saved analysis');
    const heading = node('h3', 'h6 mb-1', 'Saved analysis');
    root.append(heading);
    message.querySelector('.message-text')?.after(root);
    const controllers = new Set();
    const view = { root, dispose: () => {
        controllers.forEach(controller => controller.abort());
        controllers.clear();
    } };
    views.forEach(old => {
        if (!old.root.isConnected) {
            old.dispose();
            views.delete(old);
        }
    });
    views.add(view);
    let blocked = false;
    const isCurrent = () => root.isConnected && !blocked &&
        descriptor?.conversation_id === activeConversationId() && message.dataset.savedAnalysisMasked !== 'true';
    const unavailable = status => {
        blocked = true;
        view.dispose();
        const notice = node('p', 'small mb-0', unavailableMessage(status));
        notice.setAttribute('role', 'status');
        notice.setAttribute('aria-live', 'polite');
        root.replaceChildren(heading, notice);
        hideUnavailableActions(message);
        if (sameAnalysis(selectedContext, descriptor)) {
            clearSavedAnalysisContext();
        }
    };
    if (!descriptor || descriptor.available === false || descriptor.conversation_id !== activeConversationId()) {
        unavailable();
        return;
    }
    const fetchResult = async (params, controller) => {
        const query = new URLSearchParams({ ...pointer(descriptor), ...params });
        const response = await fetch(`/api/analysis_results?${query}`, {
            credentials: 'same-origin',
            cache: 'no-store',
            headers: { Accept: 'application/json' },
            signal: controller.signal,
        });
        if (!response.ok) {
            throw Object.assign(new Error('Could not read saved analysis.'), { status: response.status });
        }
        return response.json();
    };
    const handleError = (error, status, retryButton) => {
        if ([401, 403, 404, 409].includes(error?.status)) {
            unavailable(error.status);
        } else {
            status.textContent = 'Could not load saved findings or evidence. Try again.';
            retryButton.classList.remove('d-none');
        }
    };
    const status = node('p', 'small text-muted mb-1',
        `0 of ${descriptor.record_count} records displayed · ${descriptor.source_count} sources in the saved analysis.`);
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const validation = node('p', 'small mb-2', validationNotices[descriptor.validation_status]);
    const ask = node('button', 'btn btn-sm btn-outline-secondary', 'Ask about this analysis');
    ask.type = 'button';
    ask.addEventListener('click', () => {
        if (isCurrent() && selectSavedAnalysis(descriptor)) {
            document.getElementById('user-input')?.focus();
        }
    });
    const diagnostics = node('a', 'small ms-3', 'View diagnostics (JSON)');
    diagnostics.href = `/api/analysis_results?${new URLSearchParams({
        ...pointer(descriptor), representation: 'diagnostics',
    })}`;
    diagnostics.target = '_blank';
    diagnostics.rel = 'noopener noreferrer';
    diagnostics.setAttribute('aria-label', 'View diagnostics as JSON (opens a new tab)');
    const details = node('details', 'mt-2');
    details.append(node('summary', 'small fw-semibold', 'Findings and limitations'));
    const content = node('div', 'mt-2');
    const retry = node('button', 'btn btn-sm btn-outline-secondary d-none', 'Retry findings');
    retry.type = 'button';
    const navigation = node('nav', 'd-flex flex-wrap gap-2 mt-2');
    navigation.setAttribute('aria-label', 'Findings pages');
    const previous = node('button', 'btn btn-sm btn-outline-secondary', 'Previous findings');
    const next = node('button', 'btn btn-sm btn-outline-secondary', 'Next findings');
    previous.type = next.type = 'button';
    previous.disabled = next.disabled = true;
    navigation.append(previous, next);
    details.append(retry, content, navigation);
    root.append(status, validation, ask, diagnostics, details);
    let offset = 0;
    let nextOffset = null;
    const previousOffsets = [];
    let pageController = null;

    const renderEvidence = record => {
        const evidenceDetails = node('details', 'mt-2');
        evidenceDetails.append(node('summary', 'small fw-semibold', `Evidence for finding ${record.record_id}`));
        const body = node('div', 'small mt-2');
        const evidenceStatus = node('p', 'mb-1');
        evidenceStatus.setAttribute('role', 'status');
        evidenceStatus.setAttribute('aria-live', 'polite');
        const retryEvidence = node('button', 'btn btn-sm btn-outline-secondary d-none', 'Retry evidence');
        retryEvidence.type = 'button';
        evidenceDetails.append(evidenceStatus, retryEvidence, body);
        let evidenceController = null;
        const loadEvidence = async () => {
            evidenceController?.abort();
            evidenceController = new AbortController();
            const controller = evidenceController;
            controllers.add(controller);
            evidenceStatus.textContent = 'Loading saved evidence…';
            body.replaceChildren();
            retryEvidence.classList.add('d-none');
            try {
                const result = await fetchResult({ representation: 'evidence', record_id: record.record_id }, controller);
                if (controller.signal.aborted || !isCurrent() || !evidenceDetails.isConnected) {
                    return;
                }
                if (result?.result_sha256 !== descriptor.result_sha256 || !Array.isArray(result.evidence) ||
                    result.evidence.some(item => !object(item) || typeof item.evidence_id !== 'string' ||
                        typeof item.document_id !== 'string')) {
                    throw Object.assign(new Error('Evidence does not match this saved analysis.'), { status: 409 });
                }
                evidenceStatus.textContent = result.evidence.length
                    ? `${result.evidence.length} saved passage(s).` : 'No supporting passages are available.';
                result.evidence.forEach(item => {
                    const figure = node('figure', 'border-start ps-3 my-2');
                    const location = item.page_number != null ? ` · page ${item.page_number}` :
                        item.start_page != null ? ` · pages ${item.start_page}${item.end_page != null ? `–${item.end_page}` : ''}` : '';
                    const chunk = item.chunk_sequence != null ? ` · chunk ${item.chunk_sequence}` :
                        item.chunk_id ? ` · chunk ${item.chunk_id}` : '';
                    figure.append(
                        node('figcaption', 'fw-semibold text-break', `${item.file_name || item.document_id}${location}${chunk}`),
                        node('blockquote', 'mb-0 text-break', typeof item.quote === 'string' ? item.quote :
                            typeof item.text === 'string' ? item.text : 'No passage text was saved.'),
                    );
                    body.append(figure);
                });
            } catch (error) {
                if (!controller.signal.aborted && isCurrent() && evidenceDetails.isConnected) {
                    handleError(error, evidenceStatus, retryEvidence);
                }
            } finally {
                controllers.delete(controller);
            }
        };
        evidenceDetails.addEventListener('toggle', () => {
            if (evidenceDetails.open) {
                void loadEvidence();
            } else {
                evidenceController?.abort();
            }
        });
        retryEvidence.addEventListener('click', () => void loadEvidence());
        return evidenceDetails;
    };
    const loadPage = async () => {
        view.dispose();
        pageController = new AbortController();
        const controller = pageController;
        controllers.add(controller);
        previous.disabled = next.disabled = true;
        content.replaceChildren();
        retry.classList.add('d-none');
        status.textContent = 'Loading saved findings…';
        try {
            const result = validatePage(await fetchResult({ offset: String(offset), limit: String(pageSize) }, controller), descriptor, offset);
            if (controller.signal.aborted || !isCurrent()) {
                return;
            }
            nextOffset = result.next_offset;
            const displayedSources = new Set(result.records.map(record => record.document_id).filter(Boolean)).size;
            status.textContent = `Showing ${result.records.length ? result.offset + 1 : 0}–${result.offset + result.records.length} of ${result.total_records} records · ${displayedSources} of ${result.source_count} sources on this page.`;
            validation.textContent = validationNotices[result.validation.status];
            const limitations = [...notices(result.validation.limitations), ...notices(result.validation.issues)];
            if (limitations.length) {
                const section = node('section', 'alert alert-secondary small p-2');
                section.append(node('h4', 'h6', 'Limitations and validation issues'));
                const list = node('ul', 'mb-0');
                limitations.forEach(text => list.append(node('li', 'text-break', text)));
                section.append(list);
                content.append(section);
            }
            result.records.forEach((record, index) => {
                const article = node('article', 'border-top py-3');
                article.append(
                    node('h4', 'h6', `Finding ${offset + index + 1}`),
                    node('p', 'small text-muted mb-2 text-break', `${record.source.file_name || record.document_id} · ${record.record_id}`),
                );
                const fields = node('dl', 'small mb-0');
                Object.entries(record.values).forEach(([field, value]) => {
                    const text = value == null ? 'Not provided' : typeof value === 'object'
                        ? JSON.stringify(value, null, 2) : String(value);
                    fields.append(node('dt', 'text-break', field.replace(/_/g, ' ')), node('dd', 'text-break', text));
                });
                article.append(fields);
                article.append(record.evidence_refs.length ? renderEvidence(record) :
                    node('p', 'small text-muted mt-2 mb-0', 'No supporting passage saved for this finding.'));
                content.append(article);
            });
            if (!result.total_records) {
                content.append(node('p', 'small', 'No accepted findings were saved.'));
            }
            previous.disabled = previousOffsets.length === 0;
            next.disabled = nextOffset === null;
        } catch (error) {
            if (!controller.signal.aborted && isCurrent()) {
                handleError(error, status, retry);
            }
        } finally {
            controllers.delete(controller);
        }
    };
    details.addEventListener('toggle', () => {
        if (details.open) {
            void loadPage();
        } else {
            view.dispose();
            content.replaceChildren();
            status.textContent = `0 of ${descriptor.record_count} records displayed · ${descriptor.source_count} sources in the saved analysis.`;
        }
    });
    retry.addEventListener('click', () => void loadPage());
    previous.addEventListener('click', () => {
        if (previousOffsets.length) {
            offset = previousOffsets.pop();
            void loadPage();
        }
    });
    next.addEventListener('click', () => {
        if (nextOffset !== null) {
            previousOffsets.push(offset);
            offset = nextOffset;
            void loadPage();
        }
    });
}

export function setSavedAnalysisMasked(message, metadata) {
    if (!message._savedAnalysisDescriptor) {
        return;
    }
    const masked = Boolean(metadata?.masked || metadata?.masked_ranges?.length);
    message.dataset.savedAnalysisMasked = String(masked);
    if (masked) {
        views.forEach(view => {
            if (message.contains(view.root)) {
                view.dispose();
                view.root.querySelectorAll('details[open]').forEach(details => { details.open = false; });
            }
        });
    }
    message.querySelectorAll('.saved-analysis-result, .saved-analysis-downloads').forEach(element => {
        element.classList.toggle('d-none', masked || (element.classList.contains('saved-analysis-downloads') &&
            message.dataset.savedAnalysisUnavailable === 'true'));
    });
    if (masked && sameAnalysis(selectedContext, message._savedAnalysisDescriptor)) {
        clearSavedAnalysisContext();
    }
}
