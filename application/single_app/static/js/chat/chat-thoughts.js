// chat-thoughts.js

import { updateLoadingIndicatorText } from './chat-loading-indicator.js';
import { escapeHtml } from './chat-utils.js';

let thoughtPollingInterval = null;
let lastSeenThoughtIndex = -1;
let lastSeenThoughtMessageId = null;
let activeStreamingThoughtTargetId = null;
let activeStreamingServerMessageId = null;
const streamingAgentActivityStates = new Map();
const streamingSourceReviewStates = new Map();
const progressDetailsExpandedStates = new Map();
let progressDetailsToggleListenerAttached = false;

// ---------------------------------------------------------------------------
// Icon map: step_type → Bootstrap Icon class
// ---------------------------------------------------------------------------
function getThoughtIcon(stepType) {
    const iconMap = {
        'history_context': 'bi-diagram-3',
        'fact_memory': 'bi-journal-bookmark',
        'search': 'bi-search',
        'tabular_analysis': 'bi-table',
        'web_search': 'bi-globe',
        'deep_research': 'bi-binoculars',
        'url_access': 'bi-link-45deg',
        'document_analysis': 'bi-journal-richtext',
        'agent_tool_call': 'bi-robot',
        'generation': 'bi-lightning',
        'content_safety': 'bi-shield-check'
    };
    return iconMap[stepType] || 'bi-stars';
}

function normalizeProgressPercent(value) {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue)) {
        return 0;
    }

    return Math.max(0, Math.min(100, Math.round(numericValue)));
}

function getProgressBarClasses(status, failedWindows = 0) {
    const normalizedStatus = String(status || '').trim().toLowerCase();
    const hasFailures = Number(failedWindows || 0) > 0;

    if (normalizedStatus === 'completed' && !hasFailures) {
        return 'progress-bar bg-success';
    }
    if (normalizedStatus === 'completed_with_failures' || hasFailures) {
        return 'progress-bar bg-warning text-dark';
    }
    if (normalizedStatus === 'running') {
        return 'progress-bar progress-bar-striped progress-bar-animated bg-info';
    }

    return 'progress-bar bg-secondary';
}

function buildProgressSummaryLabel(completedCount, totalCount, singularLabel, pluralLabel = `${singularLabel}s`) {
    const safeCompleted = Number(completedCount || 0);
    const safeTotal = Number(totalCount || 0);
    const label = safeTotal === 1 ? singularLabel : pluralLabel;

    if (safeTotal > 0) {
        return `${safeCompleted}/${safeTotal} ${label}`;
    }

    return `${safeCompleted} ${label}`;
}

function renderProgressBar(percent, status, failedWindows, ariaLabel) {
    const safePercent = normalizeProgressPercent(percent);
    const progressBarClasses = getProgressBarClasses(status, failedWindows);

    return `<div class="progress" role="progressbar" aria-label="${escapeHtml(ariaLabel)}" aria-valuenow="${safePercent}" aria-valuemin="0" aria-valuemax="100">
        <div class="${progressBarClasses}" style="width: ${safePercent}%;"></div>
    </div>`;
}

function getSafeDomIdPart(value) {
    const normalizedValue = String(value || '').trim().replace(/[^a-zA-Z0-9_-]/g, '-').slice(0, 80);
    return normalizedValue || `progress-${Date.now()}`;
}

function resolveProgressDetailsKey(thoughtData, documents, options = {}) {
    const explicitKey = String(options.progressKey || thoughtData?.message_id || activeStreamingThoughtTargetId || '').trim();
    if (explicitKey) {
        return `document-analysis:${explicitKey}`;
    }

    const documentKey = documents
        .map(document => document.document_id || document.document_name || document.file_name || document.title || '')
        .filter(Boolean)
        .join('|')
        .slice(0, 160);
    const progress = thoughtData?.progress && typeof thoughtData.progress === 'object' ? thoughtData.progress : {};
    const overall = progress.overall && typeof progress.overall === 'object' ? progress.overall : {};

    return `document-analysis:${overall.phase || 'progress'}:${overall.document_count || documents.length}:${documentKey}`;
}

function isProgressDetailsExpanded(progressDetailsKey) {
    return progressDetailsExpandedStates.get(progressDetailsKey) === true;
}

function renderProgressDetailsToggle(progressDetailsKey, detailsId, isExpanded) {
    const title = isExpanded ? 'Hide document details' : 'Show document details';
    const iconClass = isExpanded ? 'bi-chevron-up' : 'bi-chevron-down';

    return `<button type="button" class="btn btn-sm btn-outline-secondary action-progress-details-toggle" data-progress-details-key="${escapeHtml(progressDetailsKey)}" aria-expanded="${isExpanded ? 'true' : 'false'}" aria-controls="${escapeHtml(detailsId)}" aria-label="${escapeHtml(title)}" title="${escapeHtml(title)}">
        <i class="bi ${iconClass}" aria-hidden="true"></i>
    </button>`;
}

function updateProgressDetailsToggleButton(toggleButton, isExpanded) {
    const title = isExpanded ? 'Hide document details' : 'Show document details';
    const iconElement = toggleButton.querySelector('i');

    toggleButton.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
    toggleButton.setAttribute('aria-label', title);
    toggleButton.setAttribute('title', title);

    if (iconElement) {
        iconElement.classList.toggle('bi-chevron-up', isExpanded);
        iconElement.classList.toggle('bi-chevron-down', !isExpanded);
    }
}

function setProgressDetailsExpanded(toggleButton, isExpanded) {
    const progressDetailsKey = toggleButton.dataset.progressDetailsKey || '';
    const detailsId = toggleButton.getAttribute('aria-controls') || '';
    const detailsElement = detailsId ? document.getElementById(detailsId) : null;

    if (progressDetailsKey) {
        progressDetailsExpandedStates.set(progressDetailsKey, isExpanded);
    }
    if (detailsElement) {
        detailsElement.classList.toggle('d-none', !isExpanded);
    }

    updateProgressDetailsToggleButton(toggleButton, isExpanded);
}

function handleProgressDetailsToggleClick(event) {
    const eventTarget = event.target;
    if (!eventTarget || typeof eventTarget.closest !== 'function') {
        return;
    }

    const toggleButton = eventTarget.closest('.action-progress-details-toggle');
    if (!toggleButton) {
        return;
    }

    event.preventDefault();
    const isExpanded = toggleButton.getAttribute('aria-expanded') === 'true';
    setProgressDetailsExpanded(toggleButton, !isExpanded);
}

function ensureProgressDetailsToggleListener() {
    if (progressDetailsToggleListenerAttached || typeof document === 'undefined') {
        return;
    }

    document.addEventListener('click', handleProgressDetailsToggleClick);
    progressDetailsToggleListenerAttached = true;
}

function renderDocumentAnalysisProgress(thoughtData, options = {}) {
    ensureProgressDetailsToggleListener();

    const progress = thoughtData.progress && typeof thoughtData.progress === 'object' ? thoughtData.progress : {};
    const overall = progress.overall && typeof progress.overall === 'object' ? progress.overall : {};
    const documents = Array.isArray(progress.documents) ? progress.documents : [];
    const overallPercent = normalizeProgressPercent(overall.percent);
    const derivedOverallStatus = Number(overall.completed_documents || 0) >= Number(overall.document_count || 0) && Number(overall.document_count || 0) > 0
        ? (Number(overall.failed_windows || 0) > 0 ? 'completed_with_failures' : 'completed')
        : 'running';
    const overallStatus = String(overall.status || '').trim().toLowerCase() || derivedOverallStatus;
    const overallPhaseLabel = String(overall.phase_label || '').trim();
    const overallPhaseDetail = String(overall.phase_detail || '').trim();
    const overallSummary = [
        buildProgressSummaryLabel(overall.completed_chunks, overall.total_chunks, 'chunk'),
        buildProgressSummaryLabel(overall.completed_windows, overall.total_windows, 'window'),
        buildProgressSummaryLabel(overall.completed_documents, overall.document_count, 'document'),
    ].join(' | ');
    const overallTitle = String(thoughtData.content || overallPhaseLabel || 'Running analysis across the selected documents').trim();
    const overallDetailParts = [];
    if (overallPhaseLabel && overallPhaseLabel.toLowerCase() !== overallTitle.toLowerCase()) {
        overallDetailParts.push(overallPhaseLabel);
    }
    if (overallPhaseDetail) {
        overallDetailParts.push(overallPhaseDetail);
    }
    if (overallSummary) {
        overallDetailParts.push(overallSummary);
    }
    const overallDetailText = overallDetailParts.join(' | ') || overallSummary;
    const documentsHtml = documents.map(document => {
        const documentPercent = normalizeProgressPercent(document.percent);
        const documentName = document.document_name || document.document_id || 'Document';
        const documentStatusText = document.status_text || [
            buildProgressSummaryLabel(document.completed_chunks, document.total_chunks, 'chunk'),
            buildProgressSummaryLabel(document.completed_windows, document.total_windows, 'window'),
        ].join(' | ');

        return `<div class="border rounded-3 p-2 bg-body-tertiary mb-2">
            <div class="d-flex align-items-center justify-content-between gap-2 mb-1">
                <div class="small fw-semibold text-body">${escapeHtml(documentName)}</div>
                <span class="badge text-bg-light border">${documentPercent}%</span>
            </div>
            <div class="text-muted small mb-2">${escapeHtml(documentStatusText)}</div>
            ${renderProgressBar(documentPercent, document.status, document.failed_windows, `${documentName} analysis progress`)}
        </div>`;
    }).join('');
    const hasDocumentDetails = documents.length > 0;
    const progressDetailsKey = resolveProgressDetailsKey(thoughtData, documents, options);
    const progressDetailsId = `document-analysis-details-${getSafeDomIdPart(progressDetailsKey)}`;
    const progressDetailsExpanded = isProgressDetailsExpanded(progressDetailsKey);
    const progressDetailsToggleHtml = hasDocumentDetails
        ? renderProgressDetailsToggle(progressDetailsKey, progressDetailsId, progressDetailsExpanded)
        : '';
    const progressDetailsHtml = hasDocumentDetails
        ? `<div id="${escapeHtml(progressDetailsId)}" class="document-analysis-progress-details${progressDetailsExpanded ? '' : ' d-none'}">
            ${documentsHtml}
        </div>`
        : '<div class="text-muted small">Preparing document progress...</div>';

    return `<div class="streaming-thought-display document-analysis-progress-card" data-progress-details-key="${escapeHtml(progressDetailsKey)}">
        <div class="card border-info-subtle shadow-sm">
            <div class="card-body py-3 px-3">
                <div class="d-flex align-items-start justify-content-between gap-2 mb-2">
                    <div class="d-flex align-items-start gap-2 flex-grow-1">
                        <i class="bi bi-journal-richtext text-info mt-1"></i>
                        <div>
                            <div class="small fw-semibold text-body">${escapeHtml(overallTitle || 'Running analysis across the selected documents')}</div>
                            <div class="text-muted small">${escapeHtml(overallDetailText)}</div>
                        </div>
                    </div>
                    <div class="d-flex align-items-center gap-2 flex-shrink-0">
                        <span class="badge text-bg-light border">${overallPercent}%</span>
                        ${progressDetailsToggleHtml}
                    </div>
                </div>
                <div class="mb-3">
                    ${renderProgressBar(overallPercent, overallStatus, overall.failed_windows, 'Overall analysis progress')}
                </div>
                ${progressDetailsHtml}
            </div>
        </div>
    </div>`;
}

function createAgentActivityState() {
    return {
        activities: new Map(),
        dispatchStarted: false,
        latestContent: '',
        latestDetail: '',
        latestStepType: '',
        category: '',
        completed: false,
        maxPercent: 0,
    };
}

function createSourceReviewProgressState() {
    return {
        mode: '',
        stage: 'starting',
        latestContent: '',
        latestDetail: '',
        plannedQueries: 0,
        discoveredUrls: 0,
        reviewedPages: 0,
        seedPages: 0,
        childPages: 0,
        skippedPages: 0,
        loadMoreClicks: 0,
        plannerStatus: '',
        noEvidence: false,
        completed: false,
        maxPercent: 0,
    };
}

function isTabularActivityPayload(activity) {
    if (!activity || typeof activity !== 'object') {
        return false;
    }

    return activity.kind === 'tabular_tool_invocation'
        || activity.lane_key === 'tabular'
        || activity.plugin_name === 'TabularProcessingPlugin';
}

function isTabularToolActivity(activity) {
    if (!activity || typeof activity !== 'object') {
        return false;
    }

    return activity.kind === 'tabular_tool_invocation';
}

function isTabularPostProcessingActivity(activity) {
    if (!activity || typeof activity !== 'object') {
        return false;
    }

    return activity.kind === 'tabular_post_processing';
}

function isTabularThought(thoughtData) {
    const stepType = String(thoughtData?.step_type || '').trim().toLowerCase();
    if (stepType === 'tabular_analysis') {
        return true;
    }

    return isTabularActivityPayload(thoughtData?.activity);
}

function isSourceReviewThought(thoughtData, state = null) {
    const stepType = String(thoughtData?.step_type || '').trim().toLowerCase();
    if (stepType === 'deep_research' || stepType === 'url_access' || stepType === 'source_review') {
        return true;
    }

    return Boolean(state?.mode && stepType === 'generation');
}

function resetStreamingAgentActivityState(targetMessageId = null) {
    if (!targetMessageId) {
        return;
    }

    streamingAgentActivityStates.delete(targetMessageId);
}

function resetStreamingSourceReviewState(targetMessageId = null) {
    if (!targetMessageId) {
        return;
    }

    streamingSourceReviewStates.delete(targetMessageId);
}

function getStreamingAgentActivityState(targetMessageId) {
    if (!targetMessageId) {
        return null;
    }

    if (!streamingAgentActivityStates.has(targetMessageId)) {
        streamingAgentActivityStates.set(targetMessageId, createAgentActivityState());
    }

    return streamingAgentActivityStates.get(targetMessageId);
}

function getStreamingSourceReviewState(targetMessageId) {
    if (!targetMessageId) {
        return null;
    }

    if (!streamingSourceReviewStates.has(targetMessageId)) {
        streamingSourceReviewStates.set(targetMessageId, createSourceReviewProgressState());
    }

    return streamingSourceReviewStates.get(targetMessageId);
}

function getNormalizedActivityStatus(activity) {
    return String(activity?.status || activity?.state || '').trim().toLowerCase();
}

function isTerminalActivityStatus(status) {
    return status === 'completed' || status === 'failed';
}

function getAgentActivityCounters(state) {
    const activities = Array.from(state.activities.values());
    let completedCount = 0;
    let failedCount = 0;
    let runningCount = 0;

    activities.forEach(activity => {
        const normalizedStatus = getNormalizedActivityStatus(activity);
        if (normalizedStatus === 'failed') {
            failedCount += 1;
            return;
        }
        if (normalizedStatus === 'completed') {
            completedCount += 1;
            return;
        }
        runningCount += 1;
    });

    return {
        activities,
        completedCount,
        failedCount,
        runningCount,
        finishedCount: completedCount + failedCount,
        totalCount: activities.length,
    };
}

function hasAgentActivity(state) {
    if (!state) {
        return false;
    }

    return state.dispatchStarted || state.activities.size > 0;
}

function updateAgentActivityState(state, thoughtData, preserveMaxPercent = true) {
    if (!state || !thoughtData) {
        return state;
    }

    const content = String(thoughtData.content || '').trim();
    const normalizedContent = content.toLowerCase();
    const stepType = String(thoughtData.step_type || '').trim().toLowerCase();

    if (isTabularThought(thoughtData)) {
        state.category = 'tabular';
    } else if (!state.category && (stepType === 'agent_tool_call' || normalizedContent.startsWith('sending to agent'))) {
        state.category = 'agent';
    }

    if (stepType === 'agent_tool_call' || normalizedContent.startsWith('sending to agent')) {
        state.dispatchStarted = true;
    }

    if (content) {
        state.latestContent = content;
    }
    if (thoughtData.detail) {
        state.latestDetail = String(thoughtData.detail);
    }
    if (stepType) {
        state.latestStepType = stepType;
    }

    if (thoughtData.activity && typeof thoughtData.activity === 'object') {
        const activityPayload = thoughtData.activity;
        const activityKey = activityPayload.activity_key || activityPayload.title || `${thoughtData.step_index || state.activities.size}`;
        const previousActivity = state.activities.get(activityKey) || {};
        if (!state.category) {
            state.category = isTabularActivityPayload(activityPayload) ? 'tabular' : 'agent';
        }
        state.activities.set(activityKey, {
            ...previousActivity,
            ...activityPayload,
            content: content || previousActivity.content || '',
            detail: thoughtData.detail || previousActivity.detail || '',
        });

        if (preserveMaxPercent && isTerminalActivityStatus(getNormalizedActivityStatus(activityPayload))) {
            state.maxPercent = Math.max(state.maxPercent, 45);
        }
    }

    if (stepType === 'generation' && normalizedContent.includes('responded')) {
        state.completed = true;
    }

    return state;
}

function buildAgentActivityStateFromThoughts(thoughts) {
    const state = createAgentActivityState();
    (thoughts || []).forEach(thought => updateAgentActivityState(state, thought, false));
    return state;
}

function parseIntegerFromText(value, pattern) {
    const match = String(value || '').match(pattern);
    if (!match) {
        return 0;
    }

    const parsedValue = Number.parseInt(match[1], 10);
    return Number.isFinite(parsedValue) ? parsedValue : 0;
}

function parseSourceReviewDetail(detail) {
    const detailText = String(detail || '');
    const parsedDetail = {};
    detailText.split(',').forEach(part => {
        const [rawKey, rawValue] = part.split('=');
        const key = String(rawKey || '').trim();
        const value = String(rawValue || '').trim();
        if (!key) {
            return;
        }
        parsedDetail[key] = value;
    });
    return parsedDetail;
}

function computeSourceReviewProgressPercent(state) {
    const stagePercent = {
        starting: 8,
        planning_searches: 18,
        web_search_complete: 42,
        reviewing_sources: state.mode === 'url_access' ? 55 : 68,
        evidence_limited: 84,
        evidence_ready: 86,
        generating_response: state.completed ? 100 : 94,
    };
    const percent = stagePercent[state.stage] || stagePercent.starting;
    return normalizeProgressPercent(Math.max(percent, state.maxPercent || 0));
}

function updateSourceReviewProgressState(state, thoughtData, preserveMaxPercent = true) {
    if (!state || !thoughtData) {
        return state;
    }

    const stepType = String(thoughtData.step_type || '').trim().toLowerCase();
    const content = String(thoughtData.content || '').trim();
    const normalizedContent = content.toLowerCase();
    const detail = String(thoughtData.detail || '').trim();

    if (stepType === 'deep_research') {
        state.mode = 'deep_research';
    } else if (stepType === 'url_access') {
        state.mode = 'url_access';
    } else if (stepType === 'source_review' && !state.mode) {
        state.mode = 'deep_research';
    }

    if (content) {
        state.latestContent = content;
    }
    if (detail) {
        state.latestDetail = detail;
    }

    if (normalizedContent.includes('planning deep research web searches')) {
        state.stage = 'planning_searches';
    } else if (normalizedContent.includes('ran') && normalizedContent.includes('deep research web search')) {
        state.stage = 'web_search_complete';
        state.plannedQueries = parseIntegerFromText(content, /ran\s+(\d+)\s+deep research web search/i) || state.plannedQueries;
        state.discoveredUrls = parseIntegerFromText(detail, /discovered_urls=(\d+)/i) || state.discoveredUrls;
    } else if (normalizedContent.includes('reviewing source pages')) {
        state.stage = 'reviewing_sources';
    } else if (normalizedContent.includes('reviewing pasted urls')) {
        state.mode = state.mode || 'url_access';
        state.stage = 'reviewing_sources';
    } else if (normalizedContent.includes('reviewed') && normalizedContent.includes('url source pages')) {
        const parsedDetail = parseSourceReviewDetail(detail);
        state.stage = 'evidence_ready';
        state.reviewedPages = parseIntegerFromText(content, /reviewed\s+(\d+)\s+url source pages/i) || state.reviewedPages;
        state.seedPages = Number.parseInt(parsedDetail.seed || '0', 10) || state.seedPages;
        state.childPages = Number.parseInt(parsedDetail.child || '0', 10) || state.childPages;
        state.skippedPages = Number.parseInt(parsedDetail.skipped || '0', 10) || state.skippedPages;
        state.loadMoreClicks = Number.parseInt(parsedDetail.load_more || '0', 10) || state.loadMoreClicks;
        state.plannerStatus = parsedDetail.planner || state.plannerStatus;
    } else if (normalizedContent.includes('did not add page evidence')) {
        state.stage = 'evidence_limited';
        state.noEvidence = true;
    } else if (stepType === 'generation' && state.mode) {
        state.stage = 'generating_response';
        if (normalizedContent.includes('responded')) {
            state.completed = true;
        }
    }

    if (preserveMaxPercent) {
        state.maxPercent = Math.max(state.maxPercent, computeSourceReviewProgressPercent(state));
    }

    return state;
}

function buildSourceReviewProgressStateFromThoughts(thoughts) {
    const state = createSourceReviewProgressState();
    (thoughts || []).forEach(thought => {
        if (isSourceReviewThought(thought, state)) {
            updateSourceReviewProgressState(state, thought, false);
        }
    });
    return state;
}

function hasSourceReviewProgress(state) {
    return Boolean(state?.mode);
}

function getSourceReviewStepStatus(state, stepKey) {
    const stageOrder = state.mode === 'url_access'
        ? ['reviewing_sources', 'evidence_ready', 'generating_response']
        : ['planning_searches', 'web_search_complete', 'reviewing_sources', 'evidence_ready', 'generating_response'];
    const normalizedStage = state.stage === 'evidence_limited' ? 'evidence_ready' : state.stage;
    const currentIndex = stageOrder.indexOf(normalizedStage);
    const stepIndex = stageOrder.indexOf(stepKey);

    if (stepIndex < 0) {
        return 'pending';
    }
    if (state.completed || stepIndex < currentIndex) {
        return 'completed';
    }
    if (stepIndex === currentIndex) {
        return 'running';
    }
    return 'pending';
}

function renderSourceReviewStep(label, detail, status) {
    const iconClass = status === 'completed'
        ? 'bi-check-circle-fill text-success'
        : status === 'running'
        ? 'bi-arrow-repeat text-info'
        : 'bi-circle text-muted';
    const rowClass = status === 'running' ? 'text-body' : 'text-muted';

    return `<div class="d-flex align-items-start gap-2 py-1 ${rowClass}">
        <i class="bi ${iconClass} mt-1" aria-hidden="true"></i>
        <div class="flex-grow-1">
            <div class="small fw-semibold">${escapeHtml(label)}</div>
            <div class="small">${escapeHtml(detail)}</div>
        </div>
    </div>`;
}

function buildSourceReviewSteps(state) {
    const reviewedDetail = state.reviewedPages > 0 || state.skippedPages > 0
        ? `${state.reviewedPages} reviewed | ${state.seedPages} seed | ${state.childPages} linked | ${state.skippedPages} skipped`
        : 'Fetching, validating, and extracting source pages';
    const evidenceDetail = state.noEvidence
        ? (state.latestDetail || 'No supporting page evidence was added')
        : state.reviewedPages > 0
        ? `Evidence ready from ${state.reviewedPages} reviewed page${state.reviewedPages === 1 ? '' : 's'}`
        : 'Preparing evidence for the answer';

    if (state.mode === 'url_access') {
        return [
            {
                key: 'reviewing_sources',
                label: 'Review pasted URLs',
                detail: reviewedDetail,
            },
            {
                key: 'evidence_ready',
                label: 'Extract supporting evidence',
                detail: evidenceDetail,
            },
            {
                key: 'generating_response',
                label: 'Prepare response',
                detail: 'Using the reviewed URL evidence in the answer',
            },
        ];
    }

    return [
        {
            key: 'planning_searches',
            label: 'Plan search queries',
            detail: state.plannedQueries > 0
                ? `${state.plannedQueries} planned search quer${state.plannedQueries === 1 ? 'y' : 'ies'}`
                : 'Choosing focused web searches',
        },
        {
            key: 'web_search_complete',
            label: 'Run web searches',
            detail: state.discoveredUrls > 0
                ? `${state.discoveredUrls} discovered URL${state.discoveredUrls === 1 ? '' : 's'}`
                : 'Finding candidate sources',
        },
        {
            key: 'reviewing_sources',
            label: 'Review source pages',
            detail: reviewedDetail,
        },
        {
            key: 'evidence_ready',
            label: 'Assemble evidence',
            detail: evidenceDetail,
        },
        {
            key: 'generating_response',
            label: 'Prepare response',
            detail: 'Grounding the answer in reviewed sources',
        },
    ];
}

function renderSourceReviewProgress(state, options = {}) {
    const isLive = options.live === true;
    const isUrlAccess = state.mode === 'url_access';
    const percent = computeSourceReviewProgressPercent(state);
    const hasIssue = state.noEvidence || (state.skippedPages > 0 && state.reviewedPages === 0);
    const status = state.completed
        ? (hasIssue ? 'completed_with_failures' : 'completed')
        : 'running';
    const title = isUrlAccess ? 'URL Access' : 'Deep Research';
    const progressLabel = isUrlAccess ? 'URL Access evidence review progress' : 'Deep Research evidence review progress';
    const iconClass = isUrlAccess ? 'bi-link-45deg text-info' : 'bi-binoculars text-info';
    const plannerDetail = state.plannerStatus
        ? `Planner: ${state.plannerStatus}`
        : (isUrlAccess ? 'Server-side URL policy checks' : 'Bounded source-page review');
    const summaryParts = [];

    if (state.plannedQueries > 0) {
        summaryParts.push(`${state.plannedQueries} search quer${state.plannedQueries === 1 ? 'y' : 'ies'}`);
    }
    if (state.discoveredUrls > 0) {
        summaryParts.push(`${state.discoveredUrls} URL${state.discoveredUrls === 1 ? '' : 's'} found`);
    }
    if (state.reviewedPages > 0 || state.skippedPages > 0) {
        summaryParts.push(`${state.reviewedPages} reviewed`);
        summaryParts.push(`${state.skippedPages} skipped`);
    }
    if (state.loadMoreClicks > 0) {
        summaryParts.push(`${state.loadMoreClicks} load-more click${state.loadMoreClicks === 1 ? '' : 's'}`);
    }
    if (state.completed) {
        summaryParts.push(hasIssue ? 'Evidence limited' : 'Evidence ready');
    }

    const summaryText = summaryParts.join(' | ') || (isUrlAccess ? 'Checking pasted URLs for usable evidence' : 'Planning, searching, and reviewing source pages');
    const currentText = state.latestContent || (isUrlAccess ? 'Reviewing pasted URLs' : 'Planning Deep Research');
    const stepsHtml = buildSourceReviewSteps(state)
        .map(step => renderSourceReviewStep(step.label, step.detail, getSourceReviewStepStatus(state, step.key)))
        .join('');
    const cardBorderClass = status === 'completed'
        ? 'border-success-subtle'
        : hasIssue && state.completed
        ? 'border-warning-subtle'
        : 'border-info-subtle';
    const badgeClass = state.completed
        ? (hasIssue ? 'text-bg-warning text-dark' : 'text-bg-success')
        : 'text-bg-light border';
    const badgeText = state.completed ? (hasIssue ? 'Limited' : 'Ready') : `${percent}%`;

    return `<div class="streaming-thought-display source-review-progress-card" data-source-review-progress-mode="${escapeHtml(state.mode)}" data-source-review-progress-state="${escapeHtml(status)}" data-source-review-progress-percent="${percent}">
        <div class="card ${cardBorderClass} shadow-sm">
            <div class="card-body py-3 px-3">
                <div class="d-flex align-items-start justify-content-between gap-2 mb-2">
                    <div class="d-flex align-items-start gap-2 flex-grow-1">
                        <i class="bi ${iconClass} mt-1"></i>
                        <div>
                            <div class="small fw-semibold text-body">${escapeHtml(title)}</div>
                            <div class="text-muted small">${escapeHtml(currentText)}</div>
                        </div>
                    </div>
                    <span class="badge ${badgeClass}">${escapeHtml(badgeText)}</span>
                </div>
                <div class="text-muted small mb-2">${escapeHtml(summaryText)}</div>
                <div class="mb-3">
                    ${renderProgressBar(percent, status, hasIssue ? 1 : 0, progressLabel)}
                </div>
                <div class="border rounded-3 bg-body-tertiary px-2 py-1 mb-2">
                    ${stepsHtml}
                </div>
                <div class="small text-muted">${escapeHtml(isLive && !state.completed ? plannerDetail : (state.latestDetail || plannerDetail))}</div>
            </div>
        </div>
    </div>`;
}

function computeAgentActivityPercent(state, counters, forceCompleted = false) {
    let percent = state.dispatchStarted ? 15 : 0;

    if (state.latestStepType === 'generation') {
        percent = Math.max(percent, 25);
    }

    if (counters.totalCount > 0) {
        percent = Math.max(percent, 35 + Math.round((counters.finishedCount / counters.totalCount) * 45));

        if (counters.runningCount > 0) {
            percent = Math.max(percent, 45);
        }

        if (counters.finishedCount === counters.totalCount) {
            percent = Math.max(percent, 80);
        }
    }

    if (state.completed || forceCompleted) {
        percent = 100;
    } else {
        percent = Math.min(percent, 95);
        percent = Math.max(percent, state.maxPercent);
        state.maxPercent = percent;
    }

    return normalizeProgressPercent(percent);
}

function renderAgentActivityProgress(state, options = {}) {
    const isLive = options.live === true;
    const counters = getAgentActivityCounters(state);
    const isTabular = state.category === 'tabular';
    const hasTabularPostProcessingActivity = isTabular && counters.activities.some(activity => isTabularPostProcessingActivity(activity));
    const hasNonToolTabularActivity = isTabular && counters.activities.some(activity => !isTabularToolActivity(activity));
    const isCompleted = isTabular
        ? (state.completed || (hasTabularPostProcessingActivity && counters.totalCount > 0 && counters.runningCount === 0))
        : (state.completed || (counters.totalCount > 0 && counters.runningCount === 0));
    const percent = computeAgentActivityPercent(state, counters, isCompleted);
    const status = isCompleted
        ? (counters.failedCount > 0 ? 'completed_with_failures' : 'completed')
        : 'running';
    const runningActivity = [...counters.activities].reverse().find(activity => getNormalizedActivityStatus(activity) === 'running');
    const summaryParts = [];
    const progressTitle = isTabular ? 'Tabular analysis' : 'Agent progress';
    const progressLabel = isTabular ? 'Tabular analysis progress' : 'Agent progress';
    const currentStepPrefix = isTabular ? 'Current tabular step' : 'Current tool';
    const initialStatusText = isTabular
        ? (hasTabularPostProcessingActivity ? 'Preparing workbook output' : 'Gathering workbook evidence')
        : 'Connecting to the selected agent';
    const completedStatusText = isTabular
        ? (hasTabularPostProcessingActivity ? 'Tabular export ready' : 'Workbook evidence ready')
        : 'Response ready';
    const iconClass = isTabular ? 'bi-table text-info' : 'bi-robot text-info';

    if (counters.totalCount > 0) {
        if (isTabular) {
            summaryParts.push(buildProgressSummaryLabel(
                counters.finishedCount,
                counters.totalCount,
                hasNonToolTabularActivity ? 'step' : 'tool call'
            ));
        } else {
            summaryParts.push(buildProgressSummaryLabel(counters.finishedCount, counters.totalCount, 'tool'));
        }
    }
    if (counters.runningCount > 0) {
        summaryParts.push(`${counters.runningCount} running`);
    }
    if (counters.failedCount > 0) {
        summaryParts.push(`${counters.failedCount} failed`);
    }
    if (isCompleted) {
        summaryParts.push(completedStatusText);
    }

    const summaryText = summaryParts.join(' | ') || initialStatusText;
    const currentActivityText = runningActivity?.title
        ? `${currentStepPrefix}: ${runningActivity.title}`
        : (isLive
            ? (state.latestContent || initialStatusText)
            : (isTabular ? 'Tabular activity captured for this response' : 'Agent activity captured for this response'));

    if (!isLive && isCompleted) {
        const summaryIconClass = counters.failedCount > 0 ? 'bi-exclamation-triangle text-warning' : 'bi-check-circle text-success';
        const summaryBadgeClass = counters.failedCount > 0 ? 'text-bg-warning text-dark' : 'text-bg-success';
        const completionTitle = isTabular ? 'Tabular analysis complete' : 'Agent activity complete';

        return `<div class="streaming-thought-display agent-progress-card" data-agent-progress-state="${escapeHtml(status)}" data-agent-progress-percent="${percent}">
        <div class="card border-success-subtle shadow-sm">
            <div class="card-body py-3 px-3">
                <div class="d-flex align-items-start justify-content-between gap-2 mb-2">
                    <div class="d-flex align-items-start gap-2 flex-grow-1">
                        <i class="bi ${summaryIconClass} mt-1"></i>
                        <div>
                            <div class="small fw-semibold text-body">${escapeHtml(completionTitle)}</div>
                            <div class="text-muted small">${escapeHtml(currentActivityText)}</div>
                        </div>
                    </div>
                    <span class="badge ${summaryBadgeClass}">${counters.failedCount > 0 ? 'Completed with issues' : 'Completed'}</span>
                </div>
                <div class="text-muted small mb-2">${escapeHtml(summaryText)}</div>
                <div class="small text-body">${escapeHtml(state.latestContent || completedStatusText)}</div>
            </div>
        </div>
    </div>`;
    }

    return `<div class="streaming-thought-display agent-progress-card" data-agent-progress-state="${escapeHtml(status)}" data-agent-progress-percent="${percent}">
        <div class="card border-info-subtle shadow-sm">
            <div class="card-body py-3 px-3">
                <div class="d-flex align-items-start justify-content-between gap-2 mb-2">
                    <div class="d-flex align-items-start gap-2 flex-grow-1">
                        <i class="bi ${iconClass} mt-1"></i>
                        <div>
                            <div class="small fw-semibold text-body">${escapeHtml(progressTitle)}</div>
                            <div class="text-muted small">${escapeHtml(currentActivityText)}</div>
                        </div>
                    </div>
                    <span class="badge text-bg-light border">${percent}%</span>
                </div>
                <div class="text-muted small mb-2">${escapeHtml(summaryText)}</div>
                <div class="mb-2">
                    ${renderProgressBar(percent, status, counters.failedCount, progressLabel)}
                </div>
                <div class="small text-body">${escapeHtml(state.latestContent || initialStatusText)}</div>
            </div>
        </div>
    </div>`;
}

function buildPendingThoughtsUrl(conversationId, messageId = null) {
    const queryParams = new URLSearchParams();

    if (messageId) {
        queryParams.set('message_id', messageId);
    }

    const queryString = queryParams.toString();
    if (!queryString) {
        return `/api/conversations/${conversationId}/thoughts/pending`;
    }

    return `/api/conversations/${conversationId}/thoughts/pending?${queryString}`;
}

function getStreamingMessageElement(messageId) {
    if (!messageId) {
        return null;
    }

    return document.querySelector(`[data-message-id="${messageId}"]`);
}

function resetStreamingPlaceholderState(messageElement) {
    if (!messageElement) {
        return;
    }

    delete messageElement.dataset.streamingServerMessageId;
    delete messageElement.dataset.streamingHasContent;
    delete messageElement.dataset.streamingThoughtIndex;
    delete messageElement.dataset.streamingThoughtSignature;
}

// ---------------------------------------------------------------------------
// Polling (non-streaming mode)
// ---------------------------------------------------------------------------

/**
 * Start polling for pending thoughts while waiting for a non-streaming response.
 * @param {string} conversationId - The current conversation ID.
 */
function startThoughtPollingWithHandler(conversationId, thoughtHandler, messageId = null) {
    if (!conversationId) return;
    if (!window.appSettings?.enable_thoughts) return;

    stopThoughtPolling(); // clear any previous interval
    lastSeenThoughtIndex = -1;
    lastSeenThoughtMessageId = messageId || null;

    thoughtPollingInterval = setInterval(() => {
        fetch(buildPendingThoughtsUrl(conversationId, messageId), {
            credentials: 'same-origin'
        })
            .then(r => r.json())
            .then(data => {
                if (data.thoughts && data.thoughts.length > 0) {
                    const latest = data.thoughts[data.thoughts.length - 1];
                    const latestStepIndex = Number(latest.step_index);
                    const latestMessageId = latest.message_id || messageId || null;

                    if (latestMessageId && lastSeenThoughtMessageId && latestMessageId !== lastSeenThoughtMessageId) {
                        lastSeenThoughtIndex = -1;
                    }

                    if (latestMessageId !== lastSeenThoughtMessageId || !Number.isFinite(latestStepIndex) || latestStepIndex > lastSeenThoughtIndex) {
                        lastSeenThoughtMessageId = latestMessageId;
                        lastSeenThoughtIndex = latest.step_index;
                        thoughtHandler(latest);
                    }
                }
            })
            .catch(() => { /* ignore polling errors */ });
    }, 2000);
}


export function startThoughtPolling(conversationId, messageId = null) {
    startThoughtPollingWithHandler(conversationId, latest => {
        const icon = getThoughtIcon(latest.step_type);
        updateLoadingIndicatorText(latest.content, icon);
    }, messageId);
}


export function startStreamingThoughtPolling(conversationId, messageId = null) {
    startThoughtPollingWithHandler(conversationId, latest => {
        handleStreamingThought(latest);
    }, messageId);
}

export function beginStreamingThoughtSession(targetMessageId) {
    activeStreamingThoughtTargetId = targetMessageId || null;
    activeStreamingServerMessageId = null;

    resetStreamingAgentActivityState(activeStreamingThoughtTargetId);
    resetStreamingSourceReviewState(activeStreamingThoughtTargetId);
    resetStreamingPlaceholderState(getStreamingMessageElement(activeStreamingThoughtTargetId));
}

export function clearStreamingThoughtSession(targetMessageId = null) {
    if (targetMessageId && activeStreamingThoughtTargetId && activeStreamingThoughtTargetId !== targetMessageId) {
        return;
    }

    const messageIdToReset = targetMessageId || activeStreamingThoughtTargetId;
    resetStreamingAgentActivityState(messageIdToReset);
    resetStreamingSourceReviewState(messageIdToReset);
    resetStreamingPlaceholderState(getStreamingMessageElement(messageIdToReset));

    activeStreamingThoughtTargetId = null;
    activeStreamingServerMessageId = null;
}

export function markStreamingThoughtContentStarted(targetMessageId) {
    const messageElement = getStreamingMessageElement(targetMessageId);
    if (!messageElement) {
        return;
    }

    resetStreamingAgentActivityState(targetMessageId);
    resetStreamingSourceReviewState(targetMessageId);
    messageElement.dataset.streamingHasContent = 'true';
    delete messageElement.dataset.streamingThoughtIndex;
    delete messageElement.dataset.streamingThoughtSignature;
}

/**
 * Stop the thought polling interval.
 */
export function stopThoughtPolling() {
    if (thoughtPollingInterval) {
        clearInterval(thoughtPollingInterval);
        thoughtPollingInterval = null;
    }
    lastSeenThoughtIndex = -1;
    lastSeenThoughtMessageId = null;
}

// ---------------------------------------------------------------------------
// Streaming handler
// ---------------------------------------------------------------------------

/**
 * Handle a streaming thought event received via SSE.
 * Updates the streaming message placeholder with a styled thought indicator.
 * When actual content starts streaming, updateStreamingMessage() will overwrite this.
 * @param {object} thoughtData - { message_id, step_index, step_type, content }
 * @param {string|null} targetMessageId - Temporary DOM message ID for the active stream.
 */
export function handleStreamingThought(thoughtData, targetMessageId = null) {
    if (targetMessageId && targetMessageId !== activeStreamingThoughtTargetId) {
        beginStreamingThoughtSession(targetMessageId);
    }

    if (!activeStreamingThoughtTargetId) {
        return;
    }

    if (thoughtData.message_id) {
        if (activeStreamingServerMessageId && activeStreamingServerMessageId !== thoughtData.message_id) {
            return;
        }

        activeStreamingServerMessageId = thoughtData.message_id;
    }

    const messageElement = getStreamingMessageElement(activeStreamingThoughtTargetId);
    if (!messageElement) return;

    if (messageElement.dataset.streamingHasContent === 'true') {
        return;
    }

    const thoughtStepIndex = Number(thoughtData.step_index);
    const lastRenderedStepIndex = Number(messageElement.dataset.streamingThoughtIndex ?? -1);
    const thoughtSignature = [
        thoughtData.message_id || '',
        Number.isFinite(thoughtStepIndex) ? thoughtStepIndex : '',
        thoughtData.step_type || '',
        thoughtData.content || '',
        thoughtData.activity ? JSON.stringify(thoughtData.activity) : '',
        thoughtData.detail || '',
        thoughtData.progress ? JSON.stringify(thoughtData.progress) : ''
    ].join('::');

    if (thoughtData.message_id && messageElement.dataset.streamingServerMessageId && messageElement.dataset.streamingServerMessageId !== thoughtData.message_id) {
        return;
    }

    if (Number.isFinite(thoughtStepIndex) && thoughtStepIndex < lastRenderedStepIndex) {
        return;
    }

    if (messageElement.dataset.streamingThoughtSignature === thoughtSignature) {
        return;
    }

    if (activeStreamingServerMessageId) {
        messageElement.dataset.streamingServerMessageId = activeStreamingServerMessageId;
    }

    if (Number.isFinite(thoughtStepIndex)) {
        messageElement.dataset.streamingThoughtIndex = String(thoughtStepIndex);
    } else {
        delete messageElement.dataset.streamingThoughtIndex;
    }
    messageElement.dataset.streamingThoughtSignature = thoughtSignature;

    const contentElement = messageElement.querySelector('.message-text');
    if (!contentElement) return;

    if (thoughtData.progress && typeof thoughtData.progress === 'object') {
        contentElement.innerHTML = renderDocumentAnalysisProgress(thoughtData);
        return;
    }

    const sourceReviewState = getStreamingSourceReviewState(activeStreamingThoughtTargetId);
    if (isSourceReviewThought(thoughtData, sourceReviewState)) {
        updateSourceReviewProgressState(sourceReviewState, thoughtData);
        if (hasSourceReviewProgress(sourceReviewState)) {
            contentElement.innerHTML = renderSourceReviewProgress(sourceReviewState, { live: true });
            return;
        }
    }

    const activityState = getStreamingAgentActivityState(activeStreamingThoughtTargetId);
    updateAgentActivityState(activityState, thoughtData);
    if (hasAgentActivity(activityState)) {
        contentElement.innerHTML = renderAgentActivityProgress(activityState, { live: true });
        return;
    }

    const icon = getThoughtIcon(thoughtData.step_type);
    // Replace entire content with styled thought indicator (visually distinct from AI response)
    contentElement.innerHTML = `<div class="streaming-thought-display">
        <span class="badge bg-info bg-opacity-10 text-info border border-info-subtle px-3 py-2 animate-pulse" style="font-size: 0.85rem; font-weight: 500;">
            <i class="bi ${icon} me-2"></i>${escapeHtml(thoughtData.content)}
        </span>
    </div>`;
}

// ---------------------------------------------------------------------------
// Per-message collapsible: toggle button + container HTML
// ---------------------------------------------------------------------------

/**
 * Create HTML for the thoughts toggle button and hidden container.
 * Returns an object with { toggleHtml, containerHtml }.
 * @param {string} messageId
 */
export function createThoughtsToggleHtml(messageId) {
    if (!window.appSettings?.enable_thoughts) {
        return { toggleHtml: '', containerHtml: '' };
    }

    const containerId = `thoughts-${messageId || Date.now()}`;
    const toggleHtml = `<button class="btn btn-sm btn-link text-muted thoughts-toggle-btn" title="Show processing thoughts" aria-expanded="false" aria-controls="${containerId}"><i class="bi bi-stars"></i></button>`;
    const containerHtml = `<div id="${containerId}" class="thoughts-container d-none mt-2 pt-2 border-top"><div class="text-muted small">Loading thoughts...</div></div>`;

    return { toggleHtml, containerHtml };
}

/**
 * Attach event listener for the thoughts toggle button inside a message div.
 * @param {HTMLElement} messageDiv
 * @param {string} messageId
 * @param {string} conversationId
 */
export function attachThoughtsToggleListener(messageDiv, messageId, conversationId) {
    const toggleBtn = messageDiv.querySelector('.thoughts-toggle-btn');
    if (!toggleBtn) return;

    toggleBtn.addEventListener('click', () => {
        const targetId = toggleBtn.getAttribute('aria-controls');
        const container = messageDiv.querySelector(`#${targetId}`);
        if (!container) return;

        // Store scroll position
        const scrollContainer = document.getElementById('chat-messages-container');
        const currentScroll = scrollContainer?.scrollTop || window.pageYOffset;

        const isExpanded = !container.classList.contains('d-none');
        if (isExpanded) {
            container.classList.add('d-none');
            toggleBtn.setAttribute('aria-expanded', 'false');
            toggleBtn.title = 'Show processing thoughts';
            toggleBtn.innerHTML = '<i class="bi bi-stars"></i>';
        } else {
            container.classList.remove('d-none');
            toggleBtn.setAttribute('aria-expanded', 'true');
            toggleBtn.title = 'Hide processing thoughts';
            toggleBtn.innerHTML = '<i class="bi bi-chevron-up"></i>';

            // Lazy-load thoughts on first expand
            if (container.innerHTML.includes('Loading thoughts')) {
                loadThoughtsForMessage(conversationId, messageId, container);
            }
        }

        // Restore scroll position
        setTimeout(() => {
            if (scrollContainer) {
                scrollContainer.scrollTop = currentScroll;
            } else {
                window.scrollTo(0, currentScroll);
            }
        }, 10);
    });
}

// ---------------------------------------------------------------------------
// Fetch + render thoughts for a message
// ---------------------------------------------------------------------------

/**
 * Fetch thoughts for a specific message from the API and render them.
 * @param {string} conversationId
 * @param {string} messageId
 * @param {HTMLElement} container
 */
function loadThoughtsForMessage(conversationId, messageId, container) {
    fetch(`/api/conversations/${conversationId}/messages/${messageId}/thoughts`, {
        credentials: 'same-origin'
    })
        .then(r => r.json())
        .then(data => {
            if (!data.enabled) {
                container.innerHTML = '<div class="text-muted small">Processing thoughts are disabled.</div>';
                return;
            }
            if (!data.thoughts || data.thoughts.length === 0) {
                container.innerHTML = '<div class="text-muted small">No processing thoughts recorded for this message.</div>';
                return;
            }
            container.innerHTML = renderThoughtsList(data.thoughts);
        })
        .catch(err => {
            console.error('Error loading thoughts:', err);
            container.innerHTML = '<div class="text-danger small">Failed to load processing thoughts.</div>';
        });
}

/**
 * Render a list of thought steps as HTML.
 * @param {Array} thoughts
 * @returns {string} HTML string
 */
function renderThoughtsList(thoughts) {
    let html = '<div class="thoughts-list">';
    const summaryCards = [];
    const latestProgressThought = [...thoughts].reverse().find(thought => thought.progress && typeof thought.progress === 'object');
    const sourceReviewState = buildSourceReviewProgressStateFromThoughts(thoughts);
    const agentActivityState = buildAgentActivityStateFromThoughts(thoughts);

    if (hasSourceReviewProgress(sourceReviewState)) {
        summaryCards.push(renderSourceReviewProgress(sourceReviewState));
    }

    if (hasAgentActivity(agentActivityState)) {
        summaryCards.push(renderAgentActivityProgress(agentActivityState));
    }

    if (latestProgressThought) {
        summaryCards.push(renderDocumentAnalysisProgress(latestProgressThought));
    }

    if (summaryCards.length > 0) {
        html += `<div class="mb-2">${summaryCards.join('')}</div>`;
    }

    thoughts.forEach(t => {
        const icon = getThoughtIcon(t.step_type);
        const durationStr = t.duration_ms != null ? `<span class="text-muted ms-2">(${t.duration_ms}ms)</span>` : '';
        html += `<div class="thought-step small py-1">
            <i class="bi ${icon} me-2 text-muted"></i>
            <span>${escapeHtml(t.content || '')}</span>
            ${durationStr}
        </div>`;
    });
    html += '</div>';
    return html;
}
