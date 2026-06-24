// chat-messages.js
import { parseCitations, showCitedTextPopup } from "./chat-citations.js";
import { renderFeedbackIcons } from "./chat-feedback.js";
import {
  showLoadingIndicatorInChatbox,
  hideLoadingIndicatorInChatbox,
} from "./chat-loading-indicator.js";
import { getDocumentMetadata, fetchDocumentVersions, personalDocs, groupDocs, publicDocs, getSelectedTags, getEffectiveScopes, applyScopeLock, ensureDocumentPickerReady, isAssignedKnowledgeActive, isUserWorkspaceContextEnabled, activateUserWorkspaceContextForChatUpload, selectWorkspaceDocumentForChatUpload, registerConversationTaskDocument, updateConversationTaskDocumentsFromMessages, getConversationTaskDocumentIds, getConversationTaskDocumentSummary } from "./chat-documents.js";
import { promptSelect } from "./chat-prompts.js";
import {
  createNewConversation,
  selectConversation,
  addConversationToList
} from "./chat-conversations.js";
import { updateSidebarConversationTitle } from "./chat-sidebar-conversations.js";
import { getActiveConversationContext, getActiveConversationScope } from "./chat-conversation-scope.js";
import { escapeHtml, isColorLight, addTargetBlankToExternalLinks, sanitizeHttpUrl } from "./chat-utils.js";
import { showToast } from "./chat-toast.js";
import { autoplayTTSIfEnabled } from "./chat-tts.js";
import { saveUserSetting } from "./chat-layout.js";
import { sendMessageWithStreaming } from "./chat-streaming.js";
import { getCurrentReasoningEffort, isReasoningEffortEnabled } from './chat-reasoning.js';
import { areAgentsEnabled } from './chat-agents.js';
import { createThoughtsToggleHtml, attachThoughtsToggleListener } from './chat-thoughts.js';
import { destroyInlineCharts, extractInlineChartBlocks, hydrateInlineCharts, injectInlineChartHtml, restoreInlineChartTokens } from './chat-inline-charts.js';
import { attachGeneratedImageProposalResults, extractInlineImageProposalBlocks, hydrateInlineImageProposals, injectInlineImageProposalHtml, restoreInlineImageProposalTokens } from './chat-inline-image-proposals.js';
import { renderInlineVideoGalleries } from './chat-inline-videos.js';
import { renderInlineImageGalleries } from './chat-inline-images.js';
import { renderInlineAzureMaps } from './chat-inline-maps.js';

// Conditionally import TTS if enabled
let ttsModule = null;
if (typeof window.appSettings !== 'undefined' && window.appSettings.enable_text_to_speech) {
    import('./chat-tts.js').then(module => {
        ttsModule = module;
        console.log('TTS module loaded');
        module.initializeTTS();
    }).catch(error => {
        console.error('Failed to load TTS module:', error);
    });
}

const documentActionSelect = document.getElementById('document-action-select');
const documentComparisonSummaryBar = document.getElementById('document-comparison-summary-bar');
const documentComparisonInlineSourceTags = document.getElementById('document-comparison-inline-source-tags');
const documentComparisonInlineTargetTags = document.getElementById('document-comparison-inline-target-tags');
const documentComparisonEditButtonLabel = document.getElementById('document-comparison-edit-btn-label');
const documentComparisonModalEl = document.getElementById('document-comparison-modal');
const documentComparisonModal = documentComparisonModalEl && window.bootstrap
  ? bootstrap.Modal.getOrCreateInstance(documentComparisonModalEl)
  : null;
const documentComparisonBoard = document.getElementById('document-comparison-board');
const documentComparisonAvailableList = document.getElementById('document-comparison-available-list');
const documentComparisonSourceDropzone = document.getElementById('document-comparison-source-dropzone');
const documentComparisonLeftSelect = document.getElementById('document-comparison-left-select');
const documentComparisonSelectionSummary = document.getElementById('document-comparison-selection-summary');
const documentComparisonSelectionList = document.getElementById('document-comparison-selection-list');
const documentComparisonPickerPanel = document.getElementById('document-comparison-picker-panel');
const documentComparisonPickerControls = document.getElementById('document-comparison-picker-controls');
const documentComparisonPickerStatus = document.getElementById('document-comparison-picker-status');
let comparisonVersionLoadToken = 0;
let comparisonVersionCatalog = [];
let comparisonChatUploadCatalog = [];
let comparisonSelectedDocumentIdsSnapshot = [];
let comparisonDocumentSelectionOrder = [];
let selectedComparisonTargetIds = [];
const comparisonPickerPlacements = new Map();
const chatWorkspaceUploadPolls = new Map();
const chatWorkspaceUploadCompletionWatchers = new Map();
const COMPARISON_PICKER_FIELD_NAMES = ['scope', 'tags', 'document'];
const DOCUMENT_ACTION_NONE = 'none';
const DOCUMENT_ACTION_ANALYZE = 'analyze';
const DOCUMENT_ACTION_COMPARISON = 'comparison';
const DOCUMENT_ACTION_DESCRIPTIONS = {
  [DOCUMENT_ACTION_NONE]: 'Find relevant information in the selected documents.',
  [DOCUMENT_ACTION_ANALYZE]: 'Perform an in-depth analysis across all selected documents based on your request.',
  [DOCUMENT_ACTION_COMPARISON]: 'Compare one selected Source document against the Target documents to explain differences, relationships, or downstream impact.',
};
const DEFAULT_DOCUMENT_ACTION_CAPABILITIES = {
  [DOCUMENT_ACTION_ANALYZE]: {
    enabled: true,
    chat_max_documents: 3,
    workflow_max_documents: 10,
  },
  [DOCUMENT_ACTION_COMPARISON]: {
    enabled: true,
    chat_max_documents: 3,
    workflow_max_documents: 10,
  },
};

function getChatWorkspaceProgressValue(value) {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return 0;
  }
  return Math.max(0, Math.min(100, numericValue));
}

function isChatWorkspaceDocumentComplete(doc) {
  const statusText = String(doc?.status || '').toLowerCase();
  return getChatWorkspaceProgressValue(doc?.percentage_complete) >= 100
    || statusText.includes('processing complete')
    || statusText.includes('complete')
    || statusText.includes('error')
    || statusText.includes('failed');
}

function isChatWorkspaceDocumentFailure(doc) {
  const statusText = String(doc?.status || '').toLowerCase();
  return statusText.includes('error') || statusText.includes('failed');
}

function isChatWorkspaceDocumentSuccessComplete(doc) {
  const statusText = String(doc?.status || '').toLowerCase();
  return !isChatWorkspaceDocumentFailure(doc)
    && (
      getChatWorkspaceProgressValue(doc?.percentage_complete) >= 100
      || statusText.includes('processing complete')
      || statusText.includes('complete')
    );
}

function normalizeChatWorkspaceDocumentResponse(payload) {
  if (!payload || typeof payload !== 'object') {
    return {};
  }
  if (payload.document && typeof payload.document === 'object') {
    return payload.document;
  }
  if (payload.document_record && typeof payload.document_record === 'object') {
    return payload.document_record;
  }
  return payload;
}

function getChatWorkspaceDocumentId(doc, fallbackDocumentId = '') {
  return String(doc?.id || doc?.document_id || doc?.documentId || fallbackDocumentId || '').trim();
}

function getChatWorkspaceProgressDetailsId(workspaceDocumentId) {
  return `chat-workspace-progress-details-${String(workspaceDocumentId || '').replace(/[^a-zA-Z0-9_-]/g, '-')}`;
}

function createCompletedChatWorkspaceAttachmentElement(attachment) {
  const workspaceDocumentId = String(attachment?.document_id || attachment?.id || '').trim();
  if (!workspaceDocumentId) {
    return null;
  }

  const pct = getChatWorkspaceProgressValue(attachment?.percentage_complete);
  const statusText = String(attachment?.status || 'Processing complete').trim() || 'Processing complete';
  const detailsId = getChatWorkspaceProgressDetailsId(workspaceDocumentId);

  const container = document.createElement('div');
  container.className = 'chat-workspace-upload-progress chat-workspace-upload-progress-complete mt-2';
  container.dataset.workspaceDocumentId = workspaceDocumentId;
  container.dataset.workspaceUploadComplete = 'true';

  const toggleButton = document.createElement('button');
  toggleButton.type = 'button';
  toggleButton.className = 'btn btn-sm btn-link text-muted p-0 chat-workspace-progress-toggle';
  toggleButton.setAttribute('aria-expanded', 'false');
  toggleButton.setAttribute('aria-controls', detailsId);
  toggleButton.title = 'Show processing details';

  const icon = document.createElement('i');
  icon.className = 'bi bi-chevron-right';
  toggleButton.appendChild(icon);

  const details = document.createElement('div');
  details.id = detailsId;
  details.className = 'chat-workspace-upload-progress-details d-none mt-1 small text-muted';

  const status = document.createElement('span');
  status.className = 'chat-workspace-upload-status-text';
  status.textContent = `${statusText} (${pct.toFixed(0)}%)`;
  details.appendChild(status);

  container.append(toggleButton, details);
  return container;
}

function buildCompletedChatWorkspaceAttachmentHtml(attachment) {
  return createCompletedChatWorkspaceAttachmentElement(attachment)?.outerHTML || '';
}

function buildChatWorkspaceAttachmentHtml(attachment) {
  const workspaceDocumentId = String(attachment?.document_id || '').trim();
  if (!workspaceDocumentId) {
    return '';
  }

  if (isChatWorkspaceDocumentSuccessComplete(attachment)) {
    return buildCompletedChatWorkspaceAttachmentHtml(attachment);
  }

  const pct = getChatWorkspaceProgressValue(attachment?.percentage_complete);
  const statusText = String(attachment?.status || 'Queued for workspace processing').trim() || 'Queued for workspace processing';
  const detailsId = getChatWorkspaceProgressDetailsId(workspaceDocumentId);
  const statusLower = statusText.toLowerCase();
  const progressClass = statusLower.includes('error') || statusLower.includes('failed')
    ? 'bg-danger'
    : (pct >= 100 || statusLower.includes('complete') ? 'bg-success' : 'progress-bar-striped progress-bar-animated bg-info');

  return `
    <div class="chat-workspace-upload-progress mt-2 p-2 border rounded bg-body-tertiary"
         data-workspace-document-id="${escapeHtml(workspaceDocumentId)}">
      <div class="d-flex align-items-center gap-2">
        <button type="button"
                class="btn btn-sm btn-link text-muted p-0 chat-workspace-progress-toggle flex-shrink-0"
                aria-expanded="false"
                aria-controls="${escapeHtml(detailsId)}"
                title="Show processing details">
          <i class="bi bi-chevron-right"></i>
        </button>
        <div class="progress flex-grow-1" style="height: 8px;" title="${escapeHtml(statusText)} (${pct.toFixed(0)}%)">
          <div class="progress-bar ${progressClass}"
               role="progressbar"
               style="width: ${pct}%;"
               aria-valuenow="${pct}"
               aria-valuemin="0"
               aria-valuemax="100"></div>
        </div>
      </div>
      <div id="${escapeHtml(detailsId)}" class="chat-workspace-upload-progress-details d-none mt-1 small text-muted">
        <span class="chat-workspace-upload-status-text text-muted">${escapeHtml(statusText)} (${pct.toFixed(0)}%)</span>
      </div>
    </div>
  `;
}

function stopChatWorkspaceAttachmentPolling(workspaceDocumentId) {
  const intervalId = chatWorkspaceUploadPolls.get(workspaceDocumentId);
  if (intervalId) {
    clearInterval(intervalId);
    chatWorkspaceUploadPolls.delete(workspaceDocumentId);
  }
}

function replaceChatWorkspaceProgressWithCompleted(container, doc) {
  if (!container) {
    return null;
  }

  const workspaceDocumentId = getChatWorkspaceDocumentId(doc, container.dataset.workspaceDocumentId);
  const replacement = createCompletedChatWorkspaceAttachmentElement({
    ...doc,
    document_id: workspaceDocumentId,
  });
  if (!replacement) {
    return null;
  }

  container.replaceWith(replacement);
  hydrateChatWorkspaceProgressDetailsToggle(replacement);
  return replacement;
}

function updateChatWorkspaceProgressContainer(container, doc) {
  if (!container) {
    return;
  }

  if (isChatWorkspaceDocumentSuccessComplete(doc)) {
    replaceChatWorkspaceProgressWithCompleted(container, doc);
    return;
  }

  const pct = getChatWorkspaceProgressValue(doc?.percentage_complete);
  const statusText = String(doc?.status || 'Processing workspace document...').trim() || 'Processing workspace document...';
  const statusLower = statusText.toLowerCase();
  const hasFailure = statusLower.includes('error') || statusLower.includes('failed');
  const hasCompleted = !hasFailure && (pct >= 100 || statusLower.includes('complete'));
  const progressBar = container.querySelector('.progress-bar');
  const statusElement = container.querySelector('.chat-workspace-upload-status-text');
  const progressElement = container.querySelector('.progress');

  if (statusElement) {
    statusElement.textContent = `${statusText} (${pct.toFixed(0)}%)`;
    statusElement.classList.toggle('text-danger', hasFailure);
    statusElement.classList.remove('text-warning');
    statusElement.classList.toggle('text-muted', !hasFailure);
  }
  if (progressElement) {
    progressElement.setAttribute('title', `${statusText} (${pct.toFixed(0)}%)`);
  }
  if (progressBar) {
    progressBar.style.width = `${pct}%`;
    progressBar.setAttribute('aria-valuenow', String(pct));
    progressBar.classList.remove('bg-warning');
    progressBar.classList.toggle('bg-danger', hasFailure);
    progressBar.classList.toggle('bg-success', hasCompleted);
    progressBar.classList.toggle('bg-info', !hasFailure && !hasCompleted);
    progressBar.classList.toggle('progress-bar-striped', !hasFailure && !hasCompleted);
    progressBar.classList.toggle('progress-bar-animated', !hasFailure && !hasCompleted);
  }
}

function updateChatWorkspaceDocumentProgressEverywhere(workspaceDocumentId, doc) {
  const normalizedDocumentId = String(workspaceDocumentId || '').trim();
  if (!normalizedDocumentId) {
    return;
  }

  document.querySelectorAll('.chat-workspace-upload-progress[data-workspace-document-id]').forEach(container => {
    if (String(container.dataset.workspaceDocumentId || '').trim() === normalizedDocumentId) {
      updateChatWorkspaceProgressContainer(container, doc);
    }
  });
}

function hydrateChatWorkspaceProgressDetailsToggle(rootElement) {
  rootElement?.querySelectorAll?.('.chat-workspace-progress-toggle')?.forEach(button => {
    if (button.dataset.toggleInitialized === 'true') {
      return;
    }

    button.dataset.toggleInitialized = 'true';
    button.addEventListener('click', event => {
      event.preventDefault();
      const container = button.closest('.chat-workspace-upload-progress');
      const details = container?.querySelector('.chat-workspace-upload-progress-details');
      if (!details) {
        return;
      }

      const isExpanded = !details.classList.contains('d-none');
      details.classList.toggle('d-none', isExpanded);
      button.setAttribute('aria-expanded', String(!isExpanded));
      button.title = isExpanded ? 'Show processing details' : 'Hide processing details';

      const icon = button.querySelector('i');
      if (icon) {
        icon.classList.toggle('bi-chevron-right', isExpanded);
        icon.classList.toggle('bi-chevron-down', !isExpanded);
      }
    });
  });
}

function fetchChatWorkspaceDocumentStatus(workspaceDocumentId, options = {}) {
  const workspaceScope = String(options.workspaceScope || options.scope || '').trim().toLowerCase();
  const statusEndpoint = workspaceScope === 'group'
    ? `/api/group_documents/${encodeURIComponent(workspaceDocumentId)}`
    : `/api/documents/${encodeURIComponent(workspaceDocumentId)}`;

  return fetch(statusEndpoint, {
    cache: 'no-store',
    credentials: 'same-origin',
  })
    .then(response => {
      if (response.status === 404) {
        const notFoundError = new Error('Workspace copy was deleted or is unavailable.');
        notFoundError.isPermanent = true;
        throw notFoundError;
      }
      return response.ok
        ? response.json()
        : response.json().catch(() => ({})).then(errorBody => {
            const statusError = new Error(errorBody?.error || 'Workspace copy status is temporarily unavailable.');
            statusError.status = response.status;
            throw statusError;
          });
    })
    .then(payload => normalizeChatWorkspaceDocumentResponse(payload));
}

function stopChatWorkspaceUploadCompletionWatcher(workspaceDocumentId) {
  const watcher = chatWorkspaceUploadCompletionWatchers.get(workspaceDocumentId);
  if (!watcher) {
    return;
  }

  clearInterval(watcher.intervalId);
  chatWorkspaceUploadCompletionWatchers.delete(workspaceDocumentId);
}

function autoSelectCompletedChatWorkspaceDocument(workspaceDocumentId, options = {}) {
  selectWorkspaceDocumentForChatUpload(workspaceDocumentId, {
    replaceSelection: true,
    workspaceScope: options.workspaceScope,
    groupId: options.groupId,
  }).catch(error => {
    console.warn('Unable to select completed chat upload workspace document:', error);
  });
}

export function watchChatWorkspaceUploadDocument(workspaceDocumentId, options = {}) {
  const normalizedDocumentId = String(workspaceDocumentId || '').trim();
  if (!normalizedDocumentId) {
    return false;
  }

  stopChatWorkspaceUploadCompletionWatcher(normalizedDocumentId);
  const watcher = {
    autoSelect: options.autoSelect !== false,
    errorCount: 0,
    workspaceScope: String(options.workspaceScope || options.scope || '').trim().toLowerCase(),
    groupId: String(options.groupId || options.group_id || '').trim(),
    intervalId: null,
  };

  if (watcher.autoSelect) {
    activateUserWorkspaceContextForChatUpload();
  }

  const pollOnce = () => {
    fetchChatWorkspaceDocumentStatus(normalizedDocumentId, watcher)
      .then(doc => {
        watcher.errorCount = 0;
        updateChatWorkspaceDocumentProgressEverywhere(normalizedDocumentId, doc);

        if (!isChatWorkspaceDocumentComplete(doc)) {
          registerConversationTaskDocument({
            ...doc,
            id: getChatWorkspaceDocumentId(doc, normalizedDocumentId),
            conversation_id: currentConversationId,
            scope: watcher.workspaceScope,
            group_id: watcher.groupId,
            ready: false,
          });
          return;
        }

        stopChatWorkspaceUploadCompletionWatcher(normalizedDocumentId);
        if (watcher.autoSelect && isChatWorkspaceDocumentSuccessComplete(doc)) {
          registerConversationTaskDocument({
            ...doc,
            id: getChatWorkspaceDocumentId(doc, normalizedDocumentId),
            conversation_id: currentConversationId,
            scope: watcher.workspaceScope,
            group_id: watcher.groupId,
            ready: true,
          });
          autoSelectCompletedChatWorkspaceDocument(normalizedDocumentId, watcher);
        }
      })
      .catch(error => {
        watcher.errorCount += 1;
        if (error?.isPermanent || watcher.errorCount >= 5) {
          stopChatWorkspaceUploadCompletionWatcher(normalizedDocumentId);
        }
      });
  };

  watcher.intervalId = setInterval(pollOnce, 3000);
  chatWorkspaceUploadCompletionWatchers.set(normalizedDocumentId, watcher);
  pollOnce();
  return true;
}

function markChatWorkspaceProgressUnavailable(container, message) {
  if (!container) {
    return;
  }
  const statusElement = container.querySelector('.chat-workspace-upload-status-text');
  const progressBar = container.querySelector('.progress-bar');
  if (statusElement) {
    statusElement.textContent = message || 'Workspace copy status is unavailable.';
    statusElement.classList.remove('text-muted');
    statusElement.classList.add('text-warning');
  }
  if (progressBar) {
    progressBar.classList.remove('progress-bar-striped', 'progress-bar-animated', 'bg-info', 'bg-success');
    progressBar.classList.add('bg-warning');
  }
}

function startChatWorkspaceAttachmentPolling(container) {
  const workspaceDocumentId = String(container?.dataset?.workspaceDocumentId || '').trim();
  if (!workspaceDocumentId) {
    return;
  }

  stopChatWorkspaceAttachmentPolling(workspaceDocumentId);
  let disconnectedPolls = 0;

  const pollOnce = () => {
    if (!container.isConnected) {
      disconnectedPolls += 1;
      if (disconnectedPolls > 1) {
        stopChatWorkspaceAttachmentPolling(workspaceDocumentId);
      }
      return;
    }
    disconnectedPolls = 0;

    fetchChatWorkspaceDocumentStatus(workspaceDocumentId)
      .then(doc => {
        updateChatWorkspaceProgressContainer(container, doc);
        if (isChatWorkspaceDocumentComplete(doc)) {
          stopChatWorkspaceAttachmentPolling(workspaceDocumentId);
        }
      })
      .catch(error => {
        if (error?.isPermanent) {
          stopChatWorkspaceAttachmentPolling(workspaceDocumentId);
        }
        markChatWorkspaceProgressUnavailable(container, error?.error || error?.message || 'Workspace copy status is unavailable.');
      });
  };

  pollOnce();
  chatWorkspaceUploadPolls.set(workspaceDocumentId, setInterval(pollOnce, 5000));
}

function hydrateChatWorkspaceAttachmentProgress(rootElement) {
  hydrateChatWorkspaceProgressDetailsToggle(rootElement);
  rootElement?.querySelectorAll('.chat-workspace-upload-progress[data-workspace-document-id]').forEach(container => {
    if (container.dataset.workspaceUploadComplete === 'true') {
      return;
    }
    startChatWorkspaceAttachmentPolling(container);
  });
}

function getDocumentActionCapability(actionType) {
  const defaultCapability = DEFAULT_DOCUMENT_ACTION_CAPABILITIES[actionType] || {
    enabled: false,
    chat_max_documents: 3,
    workflow_max_documents: 10,
  };
  const configuredCapability = window.appSettings?.documentActionCapabilities?.[actionType] || {};
  return {
    ...defaultCapability,
    ...configuredCapability,
  };
}

function isDocumentActionEnabled(actionType) {
  if (actionType === DOCUMENT_ACTION_NONE) {
    return true;
  }

  return Boolean(getDocumentActionCapability(actionType).enabled);
}

function getDocumentActionMaxDocuments(actionType, executionContext) {
  const capability = getDocumentActionCapability(actionType);
  return executionContext === 'workflow'
    ? Number.parseInt(capability.workflow_max_documents || 10, 10)
    : Number.parseInt(capability.chat_max_documents || 3, 10);
}

function getDocumentActionLabel(actionType) {
  if (actionType === DOCUMENT_ACTION_COMPARISON) {
    return 'compare';
  }
  if (actionType === DOCUMENT_ACTION_ANALYZE) {
    return 'analyze';
  }
  return 'search';
}

function getDocumentActionDescription(actionType) {
  return DOCUMENT_ACTION_DESCRIPTIONS[actionType] || DOCUMENT_ACTION_DESCRIPTIONS[DOCUMENT_ACTION_NONE];
}

function syncDocumentActionTooltip() {
  if (!documentActionSelect) {
    return;
  }

  const selectedOption = documentActionSelect.selectedOptions?.[0] || null;
  const description = String(
    selectedOption?.dataset.actionDescription
    || selectedOption?.getAttribute('title')
    || getDocumentActionDescription(getDocumentActionType())
  ).trim();

  documentActionSelect.title = description;
  documentActionSelect.setAttribute('aria-description', description);
}

function isWorkspaceDocumentSearchEnabled() {
  if (isAssignedKnowledgeActive()) {
    return true;
  }
  const searchDocumentsButton = document.getElementById('search-documents-btn');
  return Boolean(searchDocumentsButton?.classList.contains('active'));
}

const INLINE_ASSISTANT_EXPORT_ACTIONS = Object.freeze({
  powerpoint: {
    actionName: 'exportMessageAsPowerPoint',
    buttonClass: 'inline-export-ppt-btn',
    iconClass: 'bi bi-file-earmark-slides',
    label: 'Create PowerPoint Presentation',
    pendingLabel: 'Creating PowerPoint Presentation...',
    title: 'Create PowerPoint Presentation',
  },
  word: {
    actionName: 'exportMessageAsWord',
    buttonClass: 'inline-export-word-btn',
    iconClass: 'bi bi-file-earmark-word',
    label: 'Create Word Document',
    pendingLabel: 'Creating Word Document...',
    title: 'Create Word Document',
  },
  markdown: {
    actionName: 'exportMessageAsMarkdown',
    buttonClass: 'inline-export-md-btn',
    iconClass: 'bi bi-markdown',
    label: 'Create Markdown Document',
    pendingLabel: 'Creating Markdown Document...',
    title: 'Create Markdown Document',
  },
  email: {
    actionName: 'openInEmail',
    buttonClass: 'inline-open-email-btn',
    iconClass: 'bi bi-envelope',
    label: 'Send an Email',
    pendingLabel: 'Opening Email Draft...',
    title: 'Opens Message in your default mail program',
  },
});

const INLINE_ASSISTANT_EXPORT_ACTIONS_BY_NAME = Object.freeze(
  Object.values(INLINE_ASSISTANT_EXPORT_ACTIONS).reduce((actionsByName, actionConfig) => {
    if (actionConfig?.actionName) {
      actionsByName[actionConfig.actionName] = actionConfig;
    }
    return actionsByName;
  }, {})
);

const INLINE_ASSISTANT_EXPORT_ACTION_ORDER = ['powerpoint', 'word', 'markdown', 'email'];
const INLINE_ASSISTANT_EXPORT_VERB_PATTERN = /\b(create|make|generate|draft|write|prepare|compose|build|send|export|provide|turn|convert)\b/i;
const INLINE_ASSISTANT_EXPORT_PATTERNS = Object.freeze({
  powerpoint: /\b(powerpoint|pptx|slide deck|presentation deck|executive deck|board deck|deck|slides?)\b/i,
  presentation: /\bpresentation\b/i,
  word: /\b(word document|word doc|docx|microsoft word|word file)\b|\b(?:in|as)\s+word\b/i,
  markdown: /\b(markdown|markdown document|\.md|md file)\b/i,
  email: /\b(e-?mail|email)\b/i,
});
const MAX_SUGGESTED_FOLLOW_UP_ACTIONS = 3;
const FOLLOW_UP_TRIGGER_PATTERNS = Object.freeze([
  /if\s+you\s+want[,\s]/i,
  /do\s+you\s+want\s+me\s+to/i,
  /i\s+can\s+(?:also\s+)?(?:do|create|give|build|prepare|provide)/i,
  /next\s+step/i,
  /would\s+you\s+like\b/i,
  /which\s+format\s+do\s+you\s+want/i,
  /suggested\s+(?:follow[-\s]?ups|prompts|next\s+steps|actions)/i,
  /follow[-\s]?up\s+(?:options|questions|prompts)/i,
]);

function getSelectedDocumentIds() {
  const docSel = document.getElementById('document-select');
  if (!docSel) {
    return [];
  }

  return Array.from(docSel.selectedOptions)
    .map(option => option.value)
    .filter(value => value);
}

function getSelectedComparisonTargetIds() {
  return selectedComparisonTargetIds.filter(Boolean);
}

function formatDocumentVersionDate(uploadDate) {
  const parsedTime = Date.parse(String(uploadDate || '').trim());
  if (Number.isNaN(parsedTime)) {
    return '';
  }

  return new Date(parsedTime).toLocaleDateString();
}

function buildDocumentVersionLabel(version, fallbackName) {
  const baseName = String(
    version?.title
    || version?.file_name
    || fallbackName
    || version?.id
    || 'Document version'
  ).trim() || 'Document version';
  const versionNumber = Number.parseInt(version?.version, 10);
  const detailParts = [];

  if (Number.isFinite(versionNumber)) {
    detailParts.push(`v${versionNumber}`);
  }
  if (version?.is_current_version) {
    detailParts.push('current');
  }

  const formattedDate = formatDocumentVersionDate(version?.upload_date);
  if (formattedDate) {
    detailParts.push(formattedDate);
  }

  return detailParts.length ? `${baseName} (${detailParts.join(' | ')})` : baseName;
}

function buildFallbackComparisonVersion(documentId) {
  const metadata = getDocumentMetadata(documentId) || {};
  return [{
    id: documentId,
    title: metadata.title || '',
    file_name: metadata.file_name || metadata.name || metadata.filename || '',
    version: metadata.version,
    upload_date: metadata.upload_date,
    is_current_version: true,
  }];
}

function getOrderedSelectedDocumentIds() {
  const selectedDocumentIds = getSelectedDocumentIds();
  const orderedSelectedDocumentIds = comparisonDocumentSelectionOrder.filter(documentId => selectedDocumentIds.includes(documentId));

  selectedDocumentIds.forEach(documentId => {
    if (!orderedSelectedDocumentIds.includes(documentId)) {
      orderedSelectedDocumentIds.push(documentId);
    }
  });

  return orderedSelectedDocumentIds;
}

function getComparisonCandidateCatalog() {
  return [...comparisonVersionCatalog, ...comparisonChatUploadCatalog];
}

function getCurrentComparisonSourceId() {
  return String(selectedComparisonTargetIds[0] || '').trim();
}

function getCurrentComparisonTargetIds() {
  const sourceId = getCurrentComparisonSourceId();
  return getSelectedComparisonTargetIds().filter(versionId => versionId !== sourceId);
}

function getComparisonVersionEntry(versionId) {
  return getComparisonCandidateCatalog().find(version => version.id === versionId) || null;
}

function buildComparisonVersionDetails(version) {
  if (version?.sourceType === 'chat_upload') {
    const detailParts = [String(version.kindLabel || 'Chat upload').trim() || 'Chat upload'];
    const formattedUploadDate = formatDocumentVersionDate(version?.upload_date || version?.timestamp);
    if (formattedUploadDate) {
      detailParts.push(formattedUploadDate);
    }
    return detailParts.join(' | ');
  }

  const detailParts = [];
  const versionNumber = Number.parseInt(version?.version, 10);

  if (Number.isFinite(versionNumber)) {
    detailParts.push(`v${versionNumber}`);
  }
  if (version?.is_current_version) {
    detailParts.push('Current');
  }

  const formattedDate = formatDocumentVersionDate(version?.upload_date);
  if (formattedDate) {
    detailParts.push(formattedDate);
  }

  return detailParts.join(' | ');
}

function buildComparisonOrderSummary(selectedVersions) {
  if (!selectedVersions.length) {
    return 'Choose one Source and at least one Target. Workspace versions come from the document picker, and chat uploads appear here after upload.';
  }

  const sourceVersion = selectedVersions[0];
  const targetCount = Math.max(0, selectedVersions.length - 1);
  if (targetCount === 0) {
    return `Source ready: ${sourceVersion.label || sourceVersion.groupLabel || sourceVersion.id}. Add one or more Targets to compare.`;
  }

  return `Source ready: ${sourceVersion.label || sourceVersion.groupLabel || sourceVersion.id}. ${targetCount} Target${targetCount === 1 ? '' : 's'} selected.`;
}

function buildComparisonChatUploadCatalog(messages = []) {
  if (!Array.isArray(messages)) {
    return [];
  }

  return messages
    .map(message => {
      const roleName = String(message?.role || '').trim().toLowerCase();
      const isUserUploadedImage = roleName === 'image' && Boolean(message?.metadata?.is_user_upload);
      if (roleName !== 'file' && !isUserUploadedImage) {
        return null;
      }

      const hasInlineText = typeof message?.file_content === 'string' && message.file_content.trim().length > 0;
      const hasExtractedText = typeof message?.extracted_text === 'string' && message.extracted_text.trim().length > 0;
      const hasBlobBackedContent = String(message?.file_content_source || '').trim().toLowerCase() === 'blob';
      const hasVisionAnalysis = message?.vision_analysis !== null
        && message?.vision_analysis !== undefined
        && message?.vision_analysis !== ''
        && (!Array.isArray(message.vision_analysis) || message.vision_analysis.length > 0);

      if (!hasInlineText && !hasExtractedText && !hasBlobBackedContent && !hasVisionAnalysis) {
        return null;
      }

      const label = String(
        message?.filename
        || (isUserUploadedImage ? 'Uploaded image' : '')
        || message?.id
        || 'Chat upload'
      ).trim() || 'Chat upload';
      const uploadDate = message?.timestamp || message?.created_at || '';

      return {
        id: String(message.id || '').trim(),
        label,
        groupLabel: 'Chat Uploads',
        sourceType: 'chat_upload',
        upload_date: uploadDate,
        timestamp: uploadDate,
        kindLabel: isUserUploadedImage
          ? 'Image upload'
          : (message?.is_table ? 'Table upload' : 'Chat upload'),
      };
    })
    .filter(upload => upload?.id)
    .sort((leftUpload, rightUpload) => {
      const timestampComparison = String(rightUpload.timestamp || '').localeCompare(String(leftUpload.timestamp || ''));
      if (timestampComparison !== 0) {
        return timestampComparison;
      }
      return String(leftUpload.label || '').localeCompare(String(rightUpload.label || ''));
    });
}

function buildComparisonEmptyState(messageText) {
  return `<div class="h-100 d-flex align-items-center justify-content-center text-center text-muted small px-3">${escapeHtml(messageText)}</div>`;
}

function getComparisonPickerField(fieldName) {
  return document.querySelector(`[data-chat-document-picker-field="${fieldName}"]`);
}

function setComparisonPickerStatus(statusText, statusClass = 'text-bg-light') {
  if (!documentComparisonPickerStatus) {
    return;
  }

  documentComparisonPickerStatus.textContent = statusText;
  documentComparisonPickerStatus.className = `badge border text-body-secondary ${statusClass}`;
}

function mountComparisonDocumentPickerControls() {
  if (!documentComparisonPickerPanel || !documentComparisonPickerControls) {
    return false;
  }

  const fields = COMPARISON_PICKER_FIELD_NAMES
    .map(fieldName => ({ fieldName, element: getComparisonPickerField(fieldName) }))
    .filter(field => field.element);

  if (!fields.length) {
    documentComparisonPickerPanel.classList.add('d-none');
    return false;
  }

  fields.forEach(({ fieldName, element }) => {
    if (!comparisonPickerPlacements.has(fieldName)) {
      const placeholder = document.createComment(`document-comparison-picker-${fieldName}`);
      element.parentNode?.insertBefore(placeholder, element);
      comparisonPickerPlacements.set(fieldName, { placeholder });
    }

    element.classList.add('document-comparison-picker-field');
    documentComparisonPickerControls.appendChild(element);
  });

  documentComparisonPickerPanel.classList.remove('d-none');
  return true;
}

function restoreComparisonDocumentPickerControls() {
  COMPARISON_PICKER_FIELD_NAMES.forEach(fieldName => {
    const placement = comparisonPickerPlacements.get(fieldName);
    const element = getComparisonPickerField(fieldName);

    if (!placement?.placeholder || !element) {
      return;
    }

    element.classList.remove('document-comparison-picker-field');
    placement.placeholder.parentNode?.insertBefore(element, placement.placeholder);
    placement.placeholder.remove();
    comparisonPickerPlacements.delete(fieldName);
  });
}

function refreshComparisonPickerDropdownLayouts() {
  if (typeof bootstrap === 'undefined' || !bootstrap.Dropdown) {
    return;
  }

  ['scope-dropdown-button', 'tags-dropdown-button', 'document-dropdown-button'].forEach(buttonId => {
    const button = document.getElementById(buttonId);
    if (!button) {
      return;
    }

    bootstrap.Dropdown.getInstance(button)?.update();
  });
}

function prepareComparisonModalPicker() {
  if (!mountComparisonDocumentPickerControls()) {
    return;
  }

  setComparisonPickerStatus('Loading', 'text-bg-light');
  ensureDocumentPickerReady({ reload: false })
    .then(() => {
      setComparisonPickerStatus('Current filters', 'text-bg-light');
      refreshComparisonPickerDropdownLayouts();
      return updateDocumentActionControls();
    })
    .catch(error => {
      console.error('Failed to prepare comparison document picker:', error);
      setComparisonPickerStatus('Unavailable', 'text-bg-warning');
    });
}

function truncateComparisonSummaryLabel(label, maxLength = 28) {
  const normalizedLabel = String(label || '').trim();
  if (normalizedLabel.length <= maxLength) {
    return normalizedLabel;
  }

  return `${normalizedLabel.slice(0, maxLength - 1).trimEnd()}…`;
}

function buildComparisonSummaryLabel(candidate) {
  if (!candidate) {
    return '';
  }

  const baseName = String(
    candidate.groupLabel
    || candidate.title
    || candidate.file_name
    || candidate.label
    || candidate.id
    || 'Document'
  ).trim() || 'Document';
  const versionNumber = Number.parseInt(candidate.version, 10);

  if (candidate.sourceType === 'workspace_document' && Number.isFinite(versionNumber)) {
    return `${baseName} v${versionNumber}`;
  }

  return baseName;
}

function renderComparisonSummaryBadge(candidate, badgeClass) {
  const fullLabel = buildComparisonSummaryLabel(candidate);
  const compactLabel = truncateComparisonSummaryLabel(fullLabel);
  return `<span class="badge rounded-pill ${badgeClass} text-truncate" style="max-width: 14rem;" title="${escapeHtml(fullLabel)}">${escapeHtml(compactLabel)}</span>`;
}

function renderComparisonSummaryPlaceholder(labelText) {
  return `<span class="badge rounded-pill text-bg-light border text-body-secondary">${escapeHtml(labelText)}</span>`;
}

function renderComparisonInlineSummary(selectedVersions = []) {
  const sourceVersion = selectedVersions[0] || null;
  const targetVersions = selectedVersions.slice(1);

  if (documentComparisonInlineSourceTags) {
    // xss-check: ignore reviewed legacy summary badge HTML built from renderComparisonSummary* helpers that escape labels.
    documentComparisonInlineSourceTags.innerHTML = sourceVersion
      ? renderComparisonSummaryBadge(sourceVersion, 'text-bg-primary')
      : renderComparisonSummaryPlaceholder('Not set');
  }

  if (documentComparisonInlineTargetTags) {
    // xss-check: ignore reviewed legacy summary badge HTML built from renderComparisonSummary* helpers that escape labels.
    documentComparisonInlineTargetTags.innerHTML = targetVersions.length
      ? targetVersions.map(targetVersion => renderComparisonSummaryBadge(targetVersion, 'text-bg-secondary')).join('')
      : renderComparisonSummaryPlaceholder('None selected');
  }

  if (documentComparisonEditButtonLabel) {
    documentComparisonEditButtonLabel.textContent = selectedVersions.length ? 'Edit Compare' : 'Set Up Compare';
  }
}

function renderComparisonAvailableCard(candidate, currentSourceId, targetIdSet) {
  const isSource = candidate.id === currentSourceId;
  const isTarget = targetIdSet.has(candidate.id);
  const canMoveSourceToTarget = isSource && selectedComparisonTargetIds.length > 1;
  const sourceButtonLabel = isSource ? 'Source selected' : 'Use as Source';
  const targetButtonLabel = isSource
    ? (canMoveSourceToTarget ? 'Move to Target' : 'Source selected')
    : (isTarget ? 'Added to Target' : 'Add to Target');
  const badgeClass = isSource
    ? 'text-bg-primary'
    : (isTarget ? 'text-bg-info' : 'text-bg-light border text-body-secondary');
  const badgeText = isSource
    ? 'Source'
    : (isTarget ? 'Target' : (candidate.sourceType === 'chat_upload' ? 'Chat' : 'Version'));

  return `<div class="border rounded-3 p-2 bg-body d-flex flex-column gap-2"
              draggable="true"
              data-comparison-drag-id="${escapeHtml(candidate.id)}"
              aria-grabbed="false">
          <div class="d-flex align-items-start justify-content-between gap-2">
              <div class="flex-grow-1" style="min-width: 0;">
                  <div class="small fw-semibold text-body">${escapeHtml(candidate.label || candidate.groupLabel || candidate.id)}</div>
                  <div class="small text-muted">${escapeHtml(buildComparisonVersionDetails(candidate) || 'Ready to compare')}</div>
              </div>
              <span class="badge ${badgeClass}">${escapeHtml(badgeText)}</span>
          </div>
          <div class="d-flex flex-wrap gap-2">
              <button type="button"
                      class="btn btn-outline-primary btn-sm"
                      data-comparison-set-source-id="${escapeHtml(candidate.id)}"
                      ${isSource ? 'disabled' : ''}>${escapeHtml(sourceButtonLabel)}</button>
              <button type="button"
                      class="btn btn-outline-secondary btn-sm"
                      data-comparison-set-target-id="${escapeHtml(candidate.id)}"
                      ${(isTarget && !canMoveSourceToTarget) ? 'disabled' : ''}>${escapeHtml(targetButtonLabel)}</button>
          </div>
      </div>`;
}

function renderComparisonSelectionCard(candidate, roleLabel, badgeClass, actionsHtml = '') {
  return `<div class="border rounded-3 p-2 bg-body d-flex flex-column gap-2"
              draggable="true"
              data-comparison-drag-id="${escapeHtml(candidate.id)}"
              role="listitem"
              aria-grabbed="false">
          <div class="d-flex align-items-start justify-content-between gap-2">
              <div class="flex-grow-1" style="min-width: 0;">
                  <div class="small fw-semibold text-body">${escapeHtml(candidate.label || candidate.groupLabel || candidate.id)}</div>
                  <div class="small text-muted">${escapeHtml(buildComparisonVersionDetails(candidate) || 'Selected item')}</div>
              </div>
              <span class="badge ${badgeClass}">${escapeHtml(roleLabel)}</span>
          </div>
          ${actionsHtml ? `<div class="d-flex flex-wrap gap-2">${actionsHtml}</div>` : ''}
      </div>`;
}

function renderComparisonAvailableList() {
  if (!documentComparisonAvailableList) {
    return;
  }

  const candidateGroups = [
    {
      heading: 'Workspace Versions',
      items: comparisonVersionCatalog,
    },
    {
      heading: 'Chat Uploads',
      items: comparisonChatUploadCatalog,
    },
  ].filter(group => group.items.length > 0);

  if (!candidateGroups.length) {
    documentComparisonAvailableList.innerHTML = buildComparisonEmptyState(
      'No workspace documents or chat uploads selected yet.'
    );
    return;
  }

  const currentSourceId = getCurrentComparisonSourceId();
  const targetIdSet = new Set(getCurrentComparisonTargetIds());
  documentComparisonAvailableList.innerHTML = candidateGroups.map(group => `
      <div class="d-flex flex-column gap-2">
          <div class="small text-uppercase text-muted fw-semibold">${escapeHtml(group.heading)}</div>
          ${group.items.map(candidate => renderComparisonAvailableCard(candidate, currentSourceId, targetIdSet)).join('')}
      </div>
  `).join('');
}

function renderComparisonSelectionList() {
  const selectedVersions = getSelectedComparisonTargetIds()
    .map(versionId => getComparisonVersionEntry(versionId))
    .filter(Boolean);
  const sourceVersion = selectedVersions[0] || null;
  const targetVersions = selectedVersions.slice(1);

  renderComparisonInlineSummary(selectedVersions);

  if (documentComparisonSelectionSummary) {
    documentComparisonSelectionSummary.textContent = buildComparisonOrderSummary(selectedVersions);
  }

  if (documentComparisonSourceDropzone) {
    if (!sourceVersion) {
      documentComparisonSourceDropzone.innerHTML = buildComparisonEmptyState(
        'Drop a workspace version or chat upload here, or use "Use as Source".'
      );
    } else {
      const sourceActions = [
        targetVersions.length > 0
          ? `<button type="button" class="btn btn-outline-secondary btn-sm" data-comparison-set-target-id="${escapeHtml(sourceVersion.id)}">Move to Target</button>`
          : '',
        `<button type="button" class="btn btn-outline-danger btn-sm" data-comparison-remove-id="${escapeHtml(sourceVersion.id)}">Remove</button>`,
      ].filter(Boolean).join('');
      documentComparisonSourceDropzone.innerHTML = renderComparisonSelectionCard(
        sourceVersion,
        'Source',
        'text-bg-primary',
        sourceActions,
      );
    }
  }

  if (!documentComparisonSelectionList) {
    return;
  }

  if (!targetVersions.length) {
    documentComparisonSelectionList.innerHTML = buildComparisonEmptyState(
      'Drop one or more items here, or use "Add to Target".'
    );
    return;
  }

  documentComparisonSelectionList.innerHTML = targetVersions.map((version, index) => renderComparisonSelectionCard(
    version,
    `Target ${index + 1}`,
    'text-bg-secondary',
    [
      `<button type="button" class="btn btn-outline-primary btn-sm" data-comparison-promote-id="${escapeHtml(version.id)}">Use as Source</button>`,
      `<button type="button" class="btn btn-outline-danger btn-sm" data-comparison-remove-id="${escapeHtml(version.id)}">Remove</button>`,
    ].join(''),
  )).join('');
}

function syncComparisonSelectionState(preferredSelection = '') {
  const availableIds = new Set(getComparisonCandidateCatalog().map(version => version.id));
  selectedComparisonTargetIds = selectedComparisonTargetIds.filter(versionId => availableIds.has(versionId));
  syncComparisonLeftOptions(preferredSelection);
  renderComparisonAvailableList();
  renderComparisonSelectionList();
}

function clearComparisonVersionTargets(resetSelections = true) {
  comparisonVersionCatalog = [];
  comparisonSelectedDocumentIdsSnapshot = [];
  if (resetSelections) {
    const availableChatUploadIds = new Set(comparisonChatUploadCatalog.map(version => version.id));
    selectedComparisonTargetIds = selectedComparisonTargetIds.filter(versionId => availableChatUploadIds.has(versionId));
  }

  syncComparisonSelectionState();
}

function getDocumentActionType() {
  return String(documentActionSelect?.value || DOCUMENT_ACTION_NONE).trim() || DOCUMENT_ACTION_NONE;
}

function syncComparisonLeftOptions(preferredSelection = '') {
  if (!documentComparisonLeftSelect) {
    return;
  }

  const previousSelection = String(preferredSelection || documentComparisonLeftSelect.value || '').trim();
  documentComparisonLeftSelect.innerHTML = '';

  getSelectedComparisonTargetIds().forEach((targetId, index) => {
    const version = getComparisonVersionEntry(targetId);
    const option = document.createElement('option');
    option.value = targetId;
    option.textContent = version?.label || targetId;
    if ((previousSelection && previousSelection === targetId) || (!previousSelection && index === 0)) {
      option.selected = true;
    }
    documentComparisonLeftSelect.appendChild(option);
  });

  documentComparisonLeftSelect.disabled = getSelectedComparisonTargetIds().length === 0;
}

function addSelectedComparisonTarget(versionId) {
  assignComparisonTarget(versionId);
}

function removeSelectedComparisonTarget(versionId) {
  const normalizedVersionId = String(versionId || '').trim();
  if (!normalizedVersionId) {
    return;
  }

  const preferredLeftSelection = String(documentComparisonLeftSelect?.value || '').trim();
  selectedComparisonTargetIds = selectedComparisonTargetIds.filter(targetId => targetId !== normalizedVersionId);
  syncComparisonSelectionState(preferredLeftSelection === normalizedVersionId ? '' : preferredLeftSelection);
}

function promoteComparisonTarget(versionId) {
  assignComparisonSource(versionId);
}

function assignComparisonSource(versionId) {
  const normalizedVersionId = String(versionId || '').trim();
  if (!normalizedVersionId) {
    return;
  }

  selectedComparisonTargetIds = [
    normalizedVersionId,
    ...selectedComparisonTargetIds.filter(targetId => targetId !== normalizedVersionId),
  ];
  syncComparisonSelectionState(normalizedVersionId);
}

function assignComparisonTarget(versionId) {
  const normalizedVersionId = String(versionId || '').trim();
  if (!normalizedVersionId) {
    return;
  }

  if (selectedComparisonTargetIds.includes(normalizedVersionId)) {
    if (getCurrentComparisonSourceId() === normalizedVersionId && selectedComparisonTargetIds.length > 1) {
      const reorderedIds = [
        ...selectedComparisonTargetIds.filter(targetId => targetId !== normalizedVersionId),
        normalizedVersionId,
      ];
      selectedComparisonTargetIds = reorderedIds;
      syncComparisonSelectionState(reorderedIds[0] || '');
    }
    return;
  }

  selectedComparisonTargetIds = [...selectedComparisonTargetIds, normalizedVersionId];
  syncComparisonSelectionState();
}

function toggleComparisonDropzoneHighlight(dropzone, isHighlighted) {
  if (!dropzone) {
    return;
  }

  dropzone.classList.toggle('border-primary', isHighlighted);
  dropzone.classList.toggle('bg-primary-subtle', isHighlighted);
}

function updateComparisonChatUploadCatalog(messages = []) {
  const preferredLeftSelection = String(documentComparisonLeftSelect?.value || '').trim();
  comparisonChatUploadCatalog = buildComparisonChatUploadCatalog(messages);
  syncComparisonSelectionState(preferredLeftSelection);

  updateDocumentActionControls().catch(error => {
    console.error('Failed to refresh comparison board after loading chat uploads:', error);
  });
}

async function loadComparisonVersionTargets() {
  if (!documentComparisonLeftSelect) {
    return;
  }

  const selectedDocumentIds = getOrderedSelectedDocumentIds();
  const previousLeftSelection = String(documentComparisonLeftSelect?.value || '').trim();
  const requestToken = ++comparisonVersionLoadToken;

  if (!selectedDocumentIds.length) {
    comparisonVersionCatalog = [];
    comparisonSelectedDocumentIdsSnapshot = [];
    syncComparisonSelectionState(previousLeftSelection);
    return;
  }

  const comparisonGroups = await Promise.all(selectedDocumentIds.map(async (documentId) => {
    const metadata = getDocumentMetadata(documentId) || {};
    let versions = [];

    try {
      versions = await fetchDocumentVersions(documentId);
    } catch (error) {
      console.warn('Unable to load comparison versions for document:', documentId, error);
    }

    if (!Array.isArray(versions) || versions.length === 0) {
      versions = buildFallbackComparisonVersion(documentId);
    }

    return {
      documentId,
      groupLabel: String(
        metadata.title
        || metadata.file_name
        || metadata.name
        || metadata.filename
        || versions[0]?.title
        || versions[0]?.file_name
        || documentId
      ).trim() || documentId,
      versions,
    };
  }));

  if (requestToken !== comparisonVersionLoadToken) {
    return;
  }

  comparisonVersionCatalog = [];
  comparisonGroups.forEach(({ documentId, groupLabel, versions }) => {
    versions.forEach(version => {
      comparisonVersionCatalog.push({
        ...version,
        documentId,
        groupLabel,
        sourceType: 'workspace_document',
        label: buildDocumentVersionLabel(version, groupLabel),
      });
    });
  });

  const addedDocumentIds = selectedDocumentIds.filter(documentId => !comparisonSelectedDocumentIdsSnapshot.includes(documentId));
  if (comparisonSelectedDocumentIdsSnapshot.length === 0 && selectedComparisonTargetIds.length === 0) {
    comparisonGroups.forEach(({ versions }) => {
      const defaultVersionId = versions.find(version => version.is_current_version)?.id || versions[0]?.id;
      if (defaultVersionId) {
        selectedComparisonTargetIds.push(defaultVersionId);
      }
    });
  } else {
    addedDocumentIds.forEach(documentId => {
      const comparisonGroup = comparisonGroups.find(group => group.documentId === documentId);
      const defaultVersionId = comparisonGroup?.versions.find(version => version.is_current_version)?.id || comparisonGroup?.versions?.[0]?.id;
      if (defaultVersionId && !selectedComparisonTargetIds.includes(defaultVersionId)) {
        selectedComparisonTargetIds.push(defaultVersionId);
      }
    });
  }

  comparisonSelectedDocumentIdsSnapshot = [...selectedDocumentIds];
  syncComparisonSelectionState(previousLeftSelection);
}

async function updateDocumentActionControls() {
  const actionType = getDocumentActionType();
  const selectedDocumentIds = getSelectedDocumentIds();
  const showComparisonUi = actionType === DOCUMENT_ACTION_COMPARISON;

  syncDocumentActionTooltip();

  if (documentComparisonSummaryBar) {
    documentComparisonSummaryBar.classList.toggle('d-none', !showComparisonUi);
  }

  if (documentComparisonBoard) {
    documentComparisonBoard.classList.toggle('d-none', !showComparisonUi);
  }

  if (showComparisonUi) {
    await loadComparisonVersionTargets();
  } else if (!selectedDocumentIds.length) {
    clearComparisonVersionTargets();
  }

  if (!showComparisonUi) {
    documentComparisonModal?.hide();
  }

  renderComparisonInlineSummary(
    getSelectedComparisonTargetIds()
      .map(versionId => getComparisonVersionEntry(versionId))
      .filter(Boolean),
  );
}

documentActionSelect?.addEventListener('change', () => {
  updateDocumentActionControls().catch(error => {
    console.error('Failed to update document action controls:', error);
  });
});

documentComparisonModalEl?.addEventListener('show.bs.modal', () => {
  prepareComparisonModalPicker();
});

documentComparisonModalEl?.addEventListener('shown.bs.modal', () => {
  refreshComparisonPickerDropdownLayouts();
});

documentComparisonModalEl?.addEventListener('hidden.bs.modal', () => {
  restoreComparisonDocumentPickerControls();
});

documentComparisonBoard?.addEventListener('click', event => {
  const sourceButton = event.target.closest('[data-comparison-set-source-id]');
  if (sourceButton) {
    event.preventDefault();
    assignComparisonSource(sourceButton.getAttribute('data-comparison-set-source-id'));
    return;
  }

  const targetButton = event.target.closest('[data-comparison-set-target-id]');
  if (targetButton) {
    event.preventDefault();
    assignComparisonTarget(targetButton.getAttribute('data-comparison-set-target-id'));
    return;
  }

  const removeButton = event.target.closest('[data-comparison-remove-id]');
  if (removeButton) {
    event.preventDefault();
    removeSelectedComparisonTarget(removeButton.getAttribute('data-comparison-remove-id'));
    return;
  }

  const promoteButton = event.target.closest('[data-comparison-promote-id]');
  if (promoteButton) {
    event.preventDefault();
    promoteComparisonTarget(promoteButton.getAttribute('data-comparison-promote-id'));
  }
});

documentComparisonBoard?.addEventListener('dragstart', event => {
  const dragCard = event.target.closest('[data-comparison-drag-id]');
  if (!dragCard || !event.dataTransfer) {
    return;
  }

  const dragId = String(dragCard.getAttribute('data-comparison-drag-id') || '').trim();
  if (!dragId) {
    return;
  }

  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', dragId);
});

documentComparisonBoard?.addEventListener('dragend', () => {
  toggleComparisonDropzoneHighlight(documentComparisonSourceDropzone, false);
  toggleComparisonDropzoneHighlight(documentComparisonSelectionList, false);
});

[documentComparisonSourceDropzone, documentComparisonSelectionList].forEach(dropzone => {
  dropzone?.addEventListener('dragover', event => {
    event.preventDefault();
    toggleComparisonDropzoneHighlight(dropzone, true);
  });

  dropzone?.addEventListener('dragleave', event => {
    if (!dropzone.contains(event.relatedTarget)) {
      toggleComparisonDropzoneHighlight(dropzone, false);
    }
  });

  dropzone?.addEventListener('drop', event => {
    event.preventDefault();
    toggleComparisonDropzoneHighlight(dropzone, false);
    const draggedId = String(event.dataTransfer?.getData('text/plain') || '').trim();
    if (!draggedId) {
      return;
    }

    if (dropzone === documentComparisonSourceDropzone) {
      assignComparisonSource(draggedId);
      return;
    }

    assignComparisonTarget(draggedId);
  });
});

window.addEventListener('chat:document-selection-changed', event => {
  const orderedDocumentIds = Array.isArray(event.detail?.documentIds)
    ? event.detail.documentIds.map(documentId => String(documentId || '').trim()).filter(Boolean)
    : [];
  if (orderedDocumentIds.length > 0) {
    comparisonDocumentSelectionOrder = orderedDocumentIds;
  }

  updateDocumentActionControls().catch(error => {
    console.error('Failed to refresh comparison target options:', error);
  });
});
updateDocumentActionControls().catch(error => {
  console.error('Failed to initialize document action controls:', error);
});

/**
 * Unwraps markdown tables that are mistakenly wrapped in code blocks.
 * This fixes the issue where AI responses contain tables in code blocks,
 * preventing them from being rendered as proper HTML tables.
 *
 * @param {string} content - The markdown content to process
 * @returns {string} - Content with tables unwrapped from code blocks
 */
function unwrapTablesFromCodeBlocks(content) {
  // Pattern to match code blocks that contain markdown tables
  const codeBlockTablePattern = /```(?:\w+)?\n((?:[^\n]*\|[^\n]*\n)+(?:\|[-\s|:]+\|\n)?(?:[^\n]*\|[^\n]*\n)*)\n?```/g;

  return content.replace(codeBlockTablePattern, (match, tableContent) => {
    // Check if the content inside the code block looks like a markdown table
    const lines = tableContent.trim().split('\n');

    // A markdown table should have:
    // 1. At least 2 lines
    // 2. Lines containing pipe characters (|)
    // 3. Potentially a separator line with dashes and pipes
    if (lines.length >= 2) {
      const hasTableStructure = lines.every(line => line.includes('|'));
      const hasSeparatorLine = lines.some(line => /^[\s|:-]+$/.test(line));

      // If it looks like a table, unwrap it from the code block
      if (hasTableStructure && (hasSeparatorLine || lines.length >= 3)) {
        console.log('🔧 Unwrapping table from code block:', tableContent.substring(0, 50) + '...');
        return '\n\n' + tableContent.trim() + '\n\n';
      }
    }

    // If it doesn't look like a table, keep it as a code block
    return match;
  });
}

/**
 * Converts Unicode box-drawing tables to markdown table format.
 * This handles the case where AI agents generate ASCII art tables using
 * Unicode box-drawing characters instead of markdown table syntax.
 *
 * @param {string} content - The content containing Unicode tables
 * @returns {string} - Content with Unicode tables converted to markdown
 */
function convertUnicodeTableToMarkdown(content) {
  // Pattern to match Unicode box-drawing tables
  const unicodeTablePattern = /┌[─┬]+┐\n(?:│[^│\n]*│[^│\n]*│[^\n]*\n)+├[─┼]+┤\n(?:│[^│\n]*│[^│\n]*│[^\n]*\n)+└[─┴]+┘/g;

  return content.replace(unicodeTablePattern, (match) => {
    console.log('🔧 Converting Unicode table to markdown format');

    try {
      const lines = match.split('\n');
      const dataLines = [];
      let headerLine = null;

      // Extract data from Unicode table
      for (const line of lines) {
        if (line.includes('│') && !line.includes('┌') && !line.includes('├') && !line.includes('└')) {
          // Remove Unicode characters and extract cell data
          const cells = line.split('│')
            .filter(cell => cell.trim() !== '')
            .map(cell => cell.trim());

          if (cells.length > 0) {
            if (!headerLine) {
              headerLine = cells;
            } else {
              dataLines.push(cells);
            }
          }
        }
      }

      if (headerLine && dataLines.length > 0) {
        // Build markdown table
        let markdownTable = '\n\n';

        // Header row
        markdownTable += '| ' + headerLine.join(' | ') + ' |\n';

        // Separator row
        markdownTable += '|' + headerLine.map(() => '---').join('|') + '|\n';

        // Data rows (limit to first 10 for display)
        const displayRows = dataLines.slice(0, 10);
        for (const row of displayRows) {
          markdownTable += '| ' + row.join(' | ') + ' |\n';
        }

        if (dataLines.length > 10) {
          markdownTable += '\n*Showing first 10 of ' + dataLines.length + ' total rows*\n';
        }

        markdownTable += '\n';

        return markdownTable;
      }
    } catch (error) {
      console.error('Error converting Unicode table:', error);
    }

    // If conversion fails, return original content
    return match;
  });
}

/**
 * Converts pipe-separated values (PSV) in code blocks to markdown table format.
 * This handles cases where AI agents generate tabular data as pipe-separated
 * format inside code blocks instead of proper markdown tables.
 *
 * @param {string} content - The content containing PSV code blocks
 * @returns {string} - Content with PSV converted to markdown tables
 */
function convertPSVCodeBlockToMarkdown(content) {
  // Pattern to match code blocks that contain pipe-separated data
  const psvCodeBlockPattern = /```(?:\w+)?\n([^`]+?)\n```/g;

  return content.replace(psvCodeBlockPattern, (match, codeContent) => {
    const lines = codeContent.trim().split('\n');

    // Check if this looks like pipe-separated tabular data
    if (lines.length >= 2) {
      const firstLine = lines[0];
      const hasConsistentPipes = lines.every(line => {
        const pipeCount = (line.match(/\|/g) || []).length;
        const firstLinePipeCount = (firstLine.match(/\|/g) || []).length;
        return pipeCount === firstLinePipeCount && pipeCount > 0;
      });

      if (hasConsistentPipes) {
        console.log('🔧 Converting PSV code block to markdown table');

        try {
          // Extract header and data rows
          const headerRow = lines[0].split('|').map(cell => cell.trim());
          const dataRows = lines.slice(1).map(line =>
            line.split('|').map(cell => cell.trim())
          );

          // Build markdown table
          let markdownTable = '\n\n';
          markdownTable += '| ' + headerRow.join(' | ') + ' |\n';
          markdownTable += '|' + headerRow.map(() => '---').join('|') + '|\n';

          // Add data rows (limit to first 50 for readability)
          const displayRows = dataRows.slice(0, 50);
          for (const row of displayRows) {
            markdownTable += '| ' + row.join(' | ') + ' |\n';
          }

          if (dataRows.length > 50) {
            markdownTable += '\n*Showing first 50 of ' + dataRows.length + ' total rows*\n';
          }

          markdownTable += '\n';

          return markdownTable;
        } catch (error) {
          console.error('Error converting PSV to markdown:', error);
        }
      }
    }

    // If it doesn't look like PSV data, keep as code block
    return match;
  });
}

/**
 * Converts ASCII dash tables to markdown table format.
 * This handles cases where AI agents generate tables using em-dash characters
 * and spaces for table formatting instead of proper markdown tables.
 *
 * @param {string} content - The content containing ASCII dash tables
 * @returns {string} - Content with ASCII tables converted to markdown
 */
function convertASCIIDashTableToMarkdown(content) {
  console.log('🔧 Converting ASCII dash tables to markdown format');

  try {
    const lines = content.split('\n');
    const dashLineIndices = [];

    // Find all lines that are primarily dash characters (table boundaries)
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.includes('─') && line.replace(/[─\s]/g, '').length === 0 && line.length > 10) {
        dashLineIndices.push(i);
      }
    }

    console.log('Found dash line boundaries at:', dashLineIndices);

    // Process each complete table (from first dash to last dash in a sequence)
    let processedContent = content;

    if (dashLineIndices.length >= 2) {
      // Process tables in reverse order to avoid index shifting issues
      let i = dashLineIndices.length - 1;
      while (i >= 0) {
        // Find the start of this table group
        let tableStart = i;
        while (tableStart > 0 &&
               dashLineIndices[tableStart] - dashLineIndices[tableStart - 1] <= 10) {
          tableStart--;
        }

        const firstDashIdx = dashLineIndices[tableStart];
        const lastDashIdx = dashLineIndices[i];

        console.log(`Processing complete ASCII table from line ${firstDashIdx} to ${lastDashIdx}`);

        // Extract header and data lines
        const headerLine = lines[firstDashIdx + 1]; // Line immediately after first dash

        if (headerLine && headerLine.trim()) {
          // Process header
          const headerCells = headerLine.split(/\s{2,}/)
            .map(cell => cell.trim())
            .filter(cell => cell !== '');

          // Process data rows (skip intermediate dash lines)
          const processedDataRows = [];
          for (let lineIdx = firstDashIdx + 2; lineIdx < lastDashIdx; lineIdx++) {
            const line = lines[lineIdx];
            // Skip dash separator lines
            if (line.includes('─') && line.replace(/[─\s]/g, '').length === 0) {
              continue;
            }

            if (line.trim()) {
              const dataCells = line.split(/\s{2,}/)
                .map(cell => cell.trim())
                .filter(cell => cell !== '');

              if (dataCells.length > 1) {
                processedDataRows.push(dataCells);
              }
            }
          }

          console.log('Processed header:', headerCells);
          console.log('Processed data rows:', processedDataRows);

          if (headerCells.length > 1 && processedDataRows.length > 0) {
            console.log(`✅ Converting ASCII table: ${headerCells.length} columns, ${processedDataRows.length} rows`);

            // Build markdown table
            let markdownTable = '\n\n';
            markdownTable += '| ' + headerCells.join(' | ') + ' |\n';
            markdownTable += '|' + headerCells.map(() => '---').join('|') + '|\n';

            for (const row of processedDataRows) {
              // Ensure we have the same number of columns as header
              while (row.length < headerCells.length) {
                row.push('—');
              }
              // Trim extra columns if any
              const trimmedRow = row.slice(0, headerCells.length);
              markdownTable += '| ' + trimmedRow.join(' | ') + ' |\n';
            }
            markdownTable += '\n';

            // Replace the original table section with markdown
            const tableSection = lines.slice(firstDashIdx, lastDashIdx + 1);
            const originalTableText = tableSection.join('\n');
            processedContent = processedContent.replace(originalTableText, markdownTable);

            console.log('✅ ASCII table successfully converted to markdown');
          }
        }

        // Move to the next table group
        i = tableStart - 1;
      }
    }

    return processedContent;

  } catch (error) {
    console.error('Error converting ASCII dash table:', error);
    return content;
  }
}

export const userInput = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");
const promptSelectionContainer = document.getElementById(
  "prompt-selection-container"
);
const chatbox = document.getElementById("chatbox");
const modelSelect = document.getElementById("model-select");
let followUpAutoSendFrame = null;
let followUpAutoSendCancel = null;

// Function to show/hide send button based on content
export function updateSendButtonVisibility() {
  if (!sendBtn || !userInput) return;

  const hasTextContent = userInput.value.trim().length > 0;

  // Check if prompt selection is active and has a selected value
  const hasPromptSelected = promptSelectionContainer &&
    promptSelectionContainer.style.display === 'block' &&
    promptSelect &&
    promptSelect.selectedIndex > 0; // selectedIndex > 0 means not the default option

  const shouldShow = hasTextContent || hasPromptSelected;

  if (shouldShow) {
    sendBtn.classList.add('show');
    userInput.classList.add('has-content');
    // Adjust textarea padding to accommodate button
    userInput.style.paddingRight = '50px';
  } else {
    sendBtn.classList.remove('show');
    userInput.classList.remove('has-content');
    // Reset textarea padding
    userInput.style.paddingRight = '60px';
  }
}

// Make function available globally for inline oninput handler
window.handleInputChange = updateSendButtonVisibility;

function resolveMessageConversationId(fullMessageObject = null) {
  const conversationCandidates = [
    fullMessageObject?.conversation_id,
    fullMessageObject?.metadata?.source_conversation_id,
    fullMessageObject?.source_conversation_id,
    window.chatConversations?.getCurrentConversationId?.(),
    window.currentConversationId,
  ];

  for (const candidate of conversationCandidates) {
    const normalizedConversationId = String(candidate || '').trim();
    if (normalizedConversationId) {
      return normalizedConversationId;
    }
  }

  return '';
}

function resolveHybridCitationId(cite, index) {
  const directCitationId = String(cite?.citation_id || '').trim();
  if (directCitationId) {
    return directCitationId;
  }

  const documentId = String(cite?.document_id || '').trim();
  const chunkLocator = String(cite?.chunk_id || cite?.page_number || index).trim();
  if (documentId && chunkLocator) {
    return `${documentId}_${chunkLocator}`;
  }

  return `${cite?.chunk_id || ''}_${cite?.page_number || index}`;
}

function createCitationsHtml(
  hybridCitations = [],
  webCitations = [],
  agentCitations = [],
  messageId,
  messageConversationId = ""
) {
  let citationsHtml = "";
  let hasCitations = false;

  if (hybridCitations && hybridCitations.length > 0) {
    hasCitations = true;
    hybridCitations.forEach((cite, index) => {
      const citationId = resolveHybridCitationId(cite, index);
      const fileName = cite.file_name || 'Document';
      const documentId = cite.document_id || '';
      const locationLabel = cite.location_label || (cite.sheet_name ? 'Sheet' : 'Page');
      const locationValue = cite.location_value || cite.sheet_name || cite.page_number || 'N/A';
      const displayText = `${escapeHtml(fileName)}, ${escapeHtml(locationLabel)}: ${escapeHtml(locationValue)}`;
      // Check if this is a metadata citation
      const isMetadata = cite.metadata_type ? true : false;
      const metadataType = cite.metadata_type || '';
      const metadataContent = cite.metadata_content || '';
      const sheetNameAttribute = cite.sheet_name
        ? `data-sheet-name="${escapeHtml(cite.sheet_name)}"`
        : '';
      const enhancedTargetValue = isMetadata && documentId
        ? (cite.sheet_name || (cite.page_number && cite.page_number !== 'Metadata' ? cite.page_number : '1'))
        : '';
      const enhancedTargetAttribute = enhancedTargetValue
        ? `data-enhanced-target="${escapeHtml(String(enhancedTargetValue))}"`
        : '';
      const documentIdAttribute = documentId
        ? `data-document-id="${escapeHtml(documentId)}"`
        : '';
      const chunkIdAttribute = cite.chunk_id !== undefined && cite.chunk_id !== null
        ? `data-chunk-id="${escapeHtml(String(cite.chunk_id))}"`
        : '';
      const pageNumberAttribute = cite.page_number !== undefined && cite.page_number !== null
        ? `data-page-number="${escapeHtml(String(cite.page_number))}"`
        : '';
      const fileNameAttribute = `data-file-name="${escapeHtml(fileName)}"`;

      if (isMetadata && documentId) {
        const summaryText = `${escapeHtml(locationLabel)}: ${escapeHtml(locationValue)}`;
        citationsHtml += `
              <a href="#"
                 class="btn btn-sm citation-button hybrid-citation-link"
                 data-citation-id="${escapeHtml(citationId)}"
                 ${sheetNameAttribute}
                 ${enhancedTargetAttribute}
                 ${documentIdAttribute}
                 ${chunkIdAttribute}
                 ${pageNumberAttribute}
                 ${fileNameAttribute}
                 data-is-metadata="false"
                 title="Open source document: ${escapeHtml(fileName)}">
                  <i class="bi bi-file-earmark-text me-1"></i>${escapeHtml(fileName)}
              </a>
              <a href="#"
                 class="btn btn-sm citation-button hybrid-citation-link metadata-citation"
                 data-citation-id="${escapeHtml(citationId)}"
                 ${sheetNameAttribute}
                 ${enhancedTargetAttribute}
                 ${documentIdAttribute}
                 ${chunkIdAttribute}
                 ${pageNumberAttribute}
                 ${fileNameAttribute}
                 data-is-metadata="true"
                 data-metadata-type="${escapeHtml(metadataType)}"
                 data-metadata-content="${escapeHtml(metadataContent)}"
                 title="View source summary: ${displayText}">
                  <i class="bi bi-tags me-1"></i>${summaryText}
              </a>`;
        return;
      }

      citationsHtml += `
              <a href="#"
                 class="btn btn-sm citation-button hybrid-citation-link ${isMetadata ? 'metadata-citation' : ''}"
                 data-citation-id="${escapeHtml(citationId)}"
                 ${sheetNameAttribute}
                 ${enhancedTargetAttribute}
                 ${documentIdAttribute}
                 ${chunkIdAttribute}
                 ${pageNumberAttribute}
                 ${fileNameAttribute}
                 data-is-metadata="${isMetadata}"
                 data-metadata-type="${escapeHtml(metadataType)}"
                 data-metadata-content="${escapeHtml(metadataContent)}"
                 title="View source: ${displayText}">
                  <i class="bi ${isMetadata ? 'bi-tags' : 'bi-file-earmark-text'} me-1"></i>${displayText}
              </a>`;
    });
  }

  if (webCitations && webCitations.length > 0) {
    hasCitations = true;
    webCitations.forEach((cite) => {
      // Example: cite.url, cite.title
      const safeWebCitationUrl = sanitizeHttpUrl(cite.url);
      if (!safeWebCitationUrl) {
        return;
      }
      const displayText = cite.title
        ? escapeHtml(cite.title)
        : escapeHtml(safeWebCitationUrl);
      citationsHtml += `
              <a href="${escapeHtml(safeWebCitationUrl)}" target="_blank" rel="noopener noreferrer"
                 class="btn btn-sm citation-button web-citation-link"
                 title="View web source: ${displayText}">
                  <i class="bi bi-globe me-1"></i>${displayText}
              </a>`;
    });
  }

  if (agentCitations && agentCitations.length > 0) {
    hasCitations = true;
    agentCitations.forEach((cite, index) => {
      // Agent citation format: { tool_name, function_arguments, function_result, timestamp }
      const displayText = cite.tool_name || `Tool ${index + 1}`;

      // Handle function arguments properly - convert object to JSON string
      let toolArgs = "";
      if (cite.function_arguments) {
        if (typeof cite.function_arguments === 'object') {
          toolArgs = JSON.stringify(cite.function_arguments);
        } else {
          toolArgs = cite.function_arguments;
        }
      }

      // Handle function result properly - convert object to JSON string
      let toolResult = "No result";
      if (cite.function_result) {
        if (typeof cite.function_result === 'object') {
          toolResult = JSON.stringify(cite.function_result);
        } else {
          toolResult = cite.function_result;
        }
      }
      citationsHtml += `
              <a href="#"
                 class="btn btn-sm citation-button agent-citation-link"
                 data-tool-name="${escapeHtml(cite.tool_name || '')}"
                 data-tool-args="${escapeHtml(toolArgs)}"
                 data-tool-result="${escapeHtml(toolResult)}"
                 data-artifact-id="${escapeHtml(cite.artifact_id || '')}"
                 data-conversation-id="${escapeHtml(messageConversationId)}"
                 title="Agent tool: ${escapeHtml(displayText)} - Click to view details">
                  <i class="bi bi-cpu me-1"></i>${escapeHtml(displayText)}
              </a>`;
    });
  }

  // Optionally wrap in a container if there are any citations
  if (hasCitations) {
    return `<div class="citations-container" data-message-id="${escapeHtml(
      messageId
    )}">${citationsHtml}</div>`;
  } else {
    return "";
  }
}

function createCitationDetailsSectionHtml(
  hybridCitations = [],
  webCitations = [],
  agentCitations = [],
  messageId = "",
  messageConversationId = ""
) {
  const documentCitationCount = Array.isArray(hybridCitations) ? hybridCitations.length : 0;
  const webCitationCount = Array.isArray(webCitations) ? webCitations.length : 0;
  const agentCitationCount = Array.isArray(agentCitations) ? agentCitations.length : 0;
  const totalCitationCount = documentCitationCount + webCitationCount + agentCitationCount;

  if (totalCitationCount === 0) {
    return "";
  }

  const countBadges = [];
  if (documentCitationCount > 0) {
    countBadges.push(`<span class="badge bg-info-subtle text-info-emphasis">Documents ${documentCitationCount}</span>`);
  }
  if (webCitationCount > 0) {
    countBadges.push(`<span class="badge bg-primary-subtle text-primary-emphasis">Web ${webCitationCount}</span>`);
  }
  if (agentCitationCount > 0) {
    countBadges.push(`<span class="badge bg-warning-subtle text-warning-emphasis">Agent ${agentCitationCount}</span>`);
  }

  const citationsHtml = createCitationsHtml(
    hybridCitations,
    webCitations,
    agentCitations,
    messageId,
    messageConversationId
  );

  return `
    <div class="mb-3">
      <div class="fw-bold mb-2"><i class="bi bi-journal-text me-2"></i>Citations</div>
      <div class="ms-3 small">
        <div class="d-flex flex-wrap gap-2 mb-2">${countBadges.join("")}</div>
        ${citationsHtml}
      </div>
    </div>`;
}

export function getGeneratedImageProposalMetadata(message) {
  const metadata = message?.metadata && typeof message.metadata === 'object'
    ? message.metadata
    : {};
  const proposalMetadata = metadata.image_proposal;
  return proposalMetadata && typeof proposalMetadata === 'object' ? proposalMetadata : null;
}

export function getGeneratedImageProposalSourceMessageId(message) {
  return String(getGeneratedImageProposalMetadata(message)?.source_assistant_message_id || '').trim();
}

export function groupGeneratedImageProposalMessages(messages = []) {
  const groupedMessages = new Map();
  (Array.isArray(messages) ? messages : []).forEach((message) => {
    if (message?.role !== 'image') {
      return;
    }

    const sourceAssistantMessageId = getGeneratedImageProposalSourceMessageId(message);
    if (!sourceAssistantMessageId) {
      return;
    }

    if (!groupedMessages.has(sourceAssistantMessageId)) {
      groupedMessages.set(sourceAssistantMessageId, []);
    }
    groupedMessages.get(sourceAssistantMessageId).push(message);
  });
  return groupedMessages;
}

export function loadMessages(conversationId) {
  // Clear search highlights when loading a different conversation
  clearSearchHighlight();

  return fetch(`/conversation/${conversationId}/messages?ts=${Date.now()}`, {
    cache: "no-store",
    headers: {
      "Cache-Control": "no-cache",
    },
  })
    .then(async (response) => {
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        const error = new Error(data.error || "Error loading messages.");
        error.status = response.status;
        throw error;
      }

      return data;
    })
    .then((data) => {
      const chatbox = document.getElementById("chatbox");
      if (!chatbox) return;

      chatbox.innerHTML = "";
      console.log(`--- Loading messages for ${conversationId} ---`);
      updateConversationTaskDocumentsFromMessages(Array.isArray(data.messages) ? data.messages : [], conversationId);
      updateComparisonChatUploadCatalog(Array.isArray(data.messages) ? data.messages : []);
      const generatedImageProposalMessages = groupGeneratedImageProposalMessages(data.messages);
      const assistantMessageIds = new Set(
        (Array.isArray(data.messages) ? data.messages : [])
          .filter(message => message?.role === 'assistant' && message?.id)
          .map(message => String(message.id))
      );
      data.messages.forEach((msg) => {
        // Skip deleted messages (when conversation archiving is enabled)
        if (msg.metadata && msg.metadata.is_deleted === true) {
          console.log(`Skipping deleted message: ${msg.id}`);
          return;
        }
        console.log(`[loadMessages Loop] -------- START Message ID: ${msg.id} --------`);
        console.log(`[loadMessages Loop] Role: ${msg.role}`);
        if (msg.role === "user") {
          appendMessage("You", msg.content, null, msg.id, false, [], [], [], null, null, msg);
        } else if (msg.role === "assistant") {
          if (generatedImageProposalMessages.has(msg.id)) {
            msg.generated_image_proposals = generatedImageProposalMessages.get(msg.id);
          }
          console.log(`  [loadMessages Loop] Full Assistant msg object:`, JSON.stringify(msg)); // Stringify to see exact keys
          console.log(`  [loadMessages Loop] Checking keys: msg.id=${msg.id}, msg.augmented=${msg.augmented}, msg.hybrid_citations exists=${'hybrid_citations' in msg}, msg.web_search_citations exists=${'web_search_citations' in msg}, msg.agent_citations exists=${'agent_citations' in msg}`);
          const senderType = msg.role === "user" ? "You" :
                       msg.role === "assistant" ? "AI" :
                       msg.role === "file" ? "File" :
                       msg.role === "image" ? "image" :
                       msg.role === "safety" ? "safety" : "System";

          const arg2 = msg.content;
          const arg3 = msg.model_deployment_name;
          const arg4 = msg.id;
          const arg5 = msg.augmented; // Get value
          const arg6 = msg.hybrid_citations; // Get value
          const arg7 = msg.web_search_citations; // Get value
          const arg8 = msg.agent_citations; // Get value
          const arg9 = msg.agent_display_name; // Get agent display name
          const arg10 = msg.agent_name; // Get agent name
          console.log(`  [loadMessages Loop] Calling appendMessage with -> sender: ${senderType}, id: ${arg4}, augmented: ${arg5} (type: ${typeof arg5}), hybrid_len: ${arg6?.length}, web_len: ${arg7?.length}, agent_len: ${arg8?.length}, agent_display: ${arg9}`);
          console.log(`  [loadMessages Loop] Message metadata:`, msg.metadata);

          appendMessage(senderType, arg2, arg3, arg4, arg5, arg6, arg7, arg8, arg9, arg10, msg);
          console.log(`[loadMessages Loop] -------- END Message ID: ${msg.id} --------`);
        } else if (msg.role === "file") {
          // Pass file message with proper parameters including message ID
          appendMessage("File", msg, null, msg.id, false, [], [], [], null, null, msg);
        } else if (msg.role === "image") {
          const sourceAssistantMessageId = getGeneratedImageProposalSourceMessageId(msg);
          if (sourceAssistantMessageId && assistantMessageIds.has(sourceAssistantMessageId)) {
            console.log(`[loadMessages] Folding generated proposal image ${msg.id} into source assistant card.`);
            return;
          }
          // Validate image URL before calling appendMessage
          if (msg.content && msg.content !== 'null' && msg.content.trim() !== '') {
            // Debug logging for image message metadata
            console.log(`[loadMessages] Image message ${msg.id}:`, {
              hasExtractedText: !!msg.extracted_text,
              hasVisionAnalysis: !!msg.vision_analysis,
              isUserUpload: msg.metadata?.is_user_upload,
              filename: msg.filename
            });
            // Pass the full message object for images that may have metadata (uploaded images)
            appendMessage("image", msg.content, msg.model_deployment_name, msg.id, false, [], [], [], msg.agent_display_name, msg.agent_name, msg);
          } else {
            console.error(`[loadMessages] Invalid image URL for message ${msg.id}: "${msg.content}"`);
            // Show error message instead of broken image
            appendMessage("Error", "Failed to load generated image - invalid URL", msg.model_deployment_name, msg.id, false, [], [], [], msg.agent_display_name, msg.agent_name);
          }
        } else if (msg.role === "safety") {
          appendMessage("safety", msg.content, null, msg.id, false, [], [], [], null, null);
        }
      });
    })
    .catch((error) => {
      console.error("Error loading messages:", error);
      updateComparisonChatUploadCatalog([]);
      const chatbox = document.getElementById("chatbox");
      let errorMessage = "Error loading messages.";

      if (error?.status === 403) {
        errorMessage = "You do not have access to this conversation.";
      } else if (error?.status === 404) {
        errorMessage = "Conversation not found.";
      } else if (error?.message) {
        errorMessage = error.message;
      }

      showToast(errorMessage, "danger");
      if (chatbox) {
        chatbox.innerHTML = `<div class="text-center p-3 text-danger">${escapeHtml(errorMessage)}</div>`;
      }
    })
    .finally(() => {
      // Check if there's a search highlight to apply
      if (window.searchHighlight && window.searchHighlight.term) {
        const elapsed = Date.now() - window.searchHighlight.timestamp;
        if (elapsed < 30000) { // Within 30 seconds
          setTimeout(() => applySearchHighlight(window.searchHighlight.term), 100);
        } else {
          // Clear expired highlight
          window.searchHighlight = null;
        }
      }
    });
}

const collaboratorProfileImageCache = new Map();

function stripHtmlTags(value) {
  const tempElement = document.createElement("div");
  tempElement.innerHTML = String(value ?? "");
  return tempElement.textContent || tempElement.innerText || "";
}

function buildPlainTextPreview(value, maxLength = 160) {
  const normalizedValue = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!normalizedValue) {
    return "No message content";
  }
  if (normalizedValue.length <= maxLength) {
    return normalizedValue;
  }
  return `${normalizedValue.slice(0, maxLength - 3)}...`;
}

function getMessageSenderUserId(fullMessageObject = null) {
  const senderUserId = String(
    fullMessageObject?.sender?.user_id || fullMessageObject?.metadata?.sender?.user_id || ""
  ).trim();
  return senderUserId || null;
}

function getMessageSenderDisplayName(fullMessageObject = null, fallbackLabel = "Participant") {
  const senderDisplayName = String(
    fullMessageObject?.sender?.display_name
      || fullMessageObject?.metadata?.sender?.display_name
      || fallbackLabel
  ).trim();
  return senderDisplayName || fallbackLabel;
}

function getInitials(name) {
  const words = String(name ?? "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);

  if (words.length === 0) {
    return "?";
  }

  return words
    .slice(0, 2)
    .map(word => word.charAt(0).toUpperCase())
    .join("");
}

function createCollaboratorAvatarHtml(fullMessageObject, senderLabel) {
  const senderUserId = getMessageSenderUserId(fullMessageObject);
  const cachedProfileImage = senderUserId ? collaboratorProfileImageCache.get(senderUserId) : null;
  const altText = `${senderLabel} Avatar`;
  const safeCachedProfileImage = sanitizeAvatarImageSrc(cachedProfileImage);

  if (safeCachedProfileImage) {
    return `<img src="${escapeHtml(safeCachedProfileImage)}" alt="${escapeHtml(altText)}" class="avatar collaborator-avatar" data-avatar-user-id="${escapeHtml(senderUserId || "")}" />`;
  }

  return `
    <div class="avatar avatar-initials collaborator-avatar" data-avatar-user-id="${escapeHtml(senderUserId || "")}" aria-label="${escapeHtml(altText)}">
      ${escapeHtml(getInitials(senderLabel))}
    </div>`;
}

function normalizeAssistantAgentIcon(iconPayload) {
  if (!iconPayload || typeof iconPayload !== 'object' || Array.isArray(iconPayload)) {
    return null;
  }

  const kind = String(iconPayload.kind || '').trim().toLowerCase();
  const value = String(iconPayload.value || '').trim();
  if (!kind || !value) {
    return null;
  }

  if (kind === 'bootstrap' && /^bi-[a-z0-9][a-z0-9-]{0,80}$/.test(value)) {
    return { kind, value };
  }

  if (
    kind === 'image'
    && /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(value)
    && value.length <= 350000
  ) {
    return { kind, value };
  }

  return null;
}

function findModelIconFromChatOptions(fullMessageObject = null) {
  const modelSelection = fullMessageObject?.metadata?.model_selection || {};
  const endpointId = String(
    modelSelection.model_endpoint_id
    || fullMessageObject?.model_endpoint_id
    || ''
  ).trim();
  const modelId = String(
    modelSelection.model_id
    || fullMessageObject?.model_id
    || ''
  ).trim();
  const deploymentName = String(
    modelSelection.selected_model
    || fullMessageObject?.model_deployment_name
    || ''
  ).trim();

  if (!endpointId && !modelId && !deploymentName) {
    return null;
  }

  const options = Array.isArray(window.chatModelOptions) ? window.chatModelOptions : [];
  const matchingOption = options.find(option => {
    if (!option || typeof option !== 'object') {
      return false;
    }

    const optionEndpointId = String(option.endpoint_id || '').trim();
    const optionModelId = String(option.model_id || '').trim();
    const optionDeploymentName = String(option.deployment_name || '').trim();
    const endpointMatches = !endpointId || optionEndpointId === endpointId;
    const modelMatches = Boolean(
      (modelId && optionModelId === modelId)
      || (deploymentName && optionDeploymentName === deploymentName)
    );

    return endpointMatches && modelMatches;
  });

  return normalizeAssistantAgentIcon(matchingOption?.icon || null);
}

function resolveAssistantModelIcon(fullMessageObject = null) {
  return normalizeAssistantAgentIcon(fullMessageObject?.model_icon)
    || normalizeAssistantAgentIcon(fullMessageObject?.metadata?.model_selection?.model_icon)
    || findModelIconFromChatOptions(fullMessageObject);
}

function hasAssistantAgentIdentity(fullMessageObject = null) {
  return Boolean(
    String(fullMessageObject?.agent_display_name || '').trim()
    || String(fullMessageObject?.agent_name || '').trim()
    || String(fullMessageObject?.metadata?.agent_selection?.agent_display_name || '').trim()
    || String(fullMessageObject?.metadata?.agent_selection?.selected_agent || '').trim()
    || String(fullMessageObject?.metadata?.agent_selection?.agent_id || '').trim()
  );
}

function sanitizeAvatarImageSrc(value) {
  const normalizedValue = String(value || '').trim();
  if (!normalizedValue) {
    return '';
  }

  if (/^\/static\/images\/[A-Za-z0-9_.-]+$/.test(normalizedValue)) {
    return normalizedValue;
  }

  if (
    /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(normalizedValue)
    && normalizedValue.length <= 350000
  ) {
    return normalizedValue;
  }

  return '';
}

function createAssistantAvatarHtml(fullMessageObject, senderLabel, defaultAvatarSrc) {
  const agentIconPayload = normalizeAssistantAgentIcon(
    fullMessageObject?.agent_icon || fullMessageObject?.metadata?.agent_selection?.agent_icon
  );
  const iconPayload = agentIconPayload || (hasAssistantAgentIdentity(fullMessageObject) ? null : resolveAssistantModelIcon(fullMessageObject));
  const avatarClass = agentIconPayload ? 'agent-avatar' : 'model-avatar';
  const altText = `${stripHtmlTags(senderLabel || 'AI').replace(/\s+/g, ' ').trim() || 'AI'} Avatar`;

  if (iconPayload?.kind === 'image') {
    const safeIconImageSrc = sanitizeAvatarImageSrc(iconPayload.value);
    if (safeIconImageSrc) {
      return `<img src="${escapeHtml(safeIconImageSrc)}" alt="${escapeHtml(altText)}" class="avatar ${avatarClass}" />`;
    }
  }

  if (iconPayload?.kind === 'bootstrap') {
    return `<div class="avatar avatar-initials ${avatarClass}" aria-label="${escapeHtml(altText)}"><i class="bi ${iconPayload.value}" aria-hidden="true"></i></div>`;
  }

  const safeDefaultAvatarSrc = sanitizeAvatarImageSrc(defaultAvatarSrc) || '/static/images/ai-avatar.png';
  return `<img src="${escapeHtml(safeDefaultAvatarSrc)}" alt="${escapeHtml(altText)}" class="avatar" />`;
}

function hydrateCollaboratorAvatar(messageDiv, senderUserId, senderLabel) {
  if (!messageDiv || !senderUserId) {
    return;
  }

  const avatarElement = messageDiv.querySelector(".collaborator-avatar");
  if (!avatarElement) {
    return;
  }

  const cachedProfileImage = collaboratorProfileImageCache.get(senderUserId);
  const safeCachedProfileImage = sanitizeAvatarImageSrc(cachedProfileImage);
  if (safeCachedProfileImage) {
    if (avatarElement.tagName === "IMG") {
      avatarElement.src = safeCachedProfileImage;
      avatarElement.alt = `${senderLabel} Avatar`;
    } else {
      const imageElement = document.createElement("img");
      imageElement.src = safeCachedProfileImage;
      imageElement.alt = `${senderLabel} Avatar`;
      imageElement.className = "avatar collaborator-avatar";
      imageElement.dataset.avatarUserId = senderUserId;
      avatarElement.replaceWith(imageElement);
    }
    return;
  }

  fetch(`/api/user/profile-image/${encodeURIComponent(senderUserId)}`, {
    credentials: "same-origin",
  })
    .then(response => {
      if (!response.ok) {
        throw new Error("Failed to load user profile image");
      }
      return response.json();
    })
    .then(userData => {
      const profileImage = sanitizeAvatarImageSrc(userData?.profile_image);
      if (!profileImage) {
        return;
      }

      collaboratorProfileImageCache.set(senderUserId, profileImage);
      if (avatarElement.tagName === "IMG") {
        avatarElement.src = profileImage;
        avatarElement.alt = `${senderLabel} Avatar`;
      } else {
        const imageElement = document.createElement("img");
        imageElement.src = profileImage;
        imageElement.alt = `${senderLabel} Avatar`;
        imageElement.className = "avatar collaborator-avatar";
        imageElement.dataset.avatarUserId = senderUserId;
        avatarElement.replaceWith(imageElement);
      }
    })
    .catch(() => {
      console.debug("Could not load profile image for collaborator:", senderUserId);
    });
}

function buildReplyContextFromMessage(message = null) {
  if (!message) {
    return null;
  }

  const messageId = String(message.id || "").trim();
  if (!messageId) {
    return null;
  }

  return {
    message_id: messageId,
    sender_display_name: getMessageSenderDisplayName(
      message,
      message.role === "assistant" ? "AI" : "Participant"
    ),
    content_preview: buildPlainTextPreview(
      message.content || message.metadata?.last_message_preview || ""
    ),
  };
}

function resolveReplyContextFromDom(messageId) {
  if (!messageId) {
    return null;
  }

  const replyElement = document.querySelector(`[data-message-id="${messageId}"]`);
  if (!replyElement) {
    return null;
  }

  const senderDisplayName = String(
    replyElement.dataset.replySenderName
      || replyElement.querySelector(".message-sender")?.textContent
      || "Participant"
  )
    .replace(/\s+/g, " ")
    .trim();
  const contentPreview = String(
    replyElement.dataset.replyPreviewText
      || buildPlainTextPreview(replyElement.querySelector(".message-text")?.textContent || "")
  ).trim();

  return {
    message_id: messageId,
    sender_display_name: senderDisplayName || "Participant",
    content_preview: contentPreview || "No message content",
  };
}

function resolveReplyContext(fullMessageObject = null) {
  const replyMessageContext = buildReplyContextFromMessage(fullMessageObject?.reply_message);
  if (replyMessageContext) {
    return replyMessageContext;
  }

  const metadataReplyContext = fullMessageObject?.metadata?.reply_context;
  if (metadataReplyContext) {
    return {
      message_id: String(metadataReplyContext.message_id || "").trim(),
      sender_display_name: String(metadataReplyContext.sender_display_name || "Participant").trim() || "Participant",
      content_preview: buildPlainTextPreview(metadataReplyContext.content_preview || ""),
    };
  }

  const replyToMessageId = String(fullMessageObject?.reply_to_message_id || "").trim();
  if (!replyToMessageId) {
    return null;
  }

  return resolveReplyContextFromDom(replyToMessageId);
}

function renderReplyQuoteHtml(fullMessageObject = null) {
  const replyContext = resolveReplyContext(fullMessageObject);
  if (!replyContext) {
    return "";
  }

  return `
    <div class="collaboration-quote-block" data-reply-to-message-id="${escapeHtml(replyContext.message_id || "")}">
      <div class="collaboration-quote-label">Replying to ${escapeHtml(replyContext.sender_display_name || "Participant")}</div>
      <div class="collaboration-quote-text">${escapeHtml(replyContext.content_preview || "No message content")}</div>
    </div>`;
}

  function escapeMentionPattern(value) {
    return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function buildAtMentionPattern(displayName) {
    return new RegExp(
      `(^|\\s)@${escapeMentionPattern(displayName)}(?=$|\\s|[.,!?;:])`,
      "gi"
    );
  }

  function normalizeStructuredMessageContent(messageContent) {
    return String(messageContent ?? "")
      .replace(/[ \t]{2,}/g, " ")
      .replace(/\s+\n/g, "\n")
      .replace(/\n\s+/g, "\n")
      .replace(/\s+([.,!?;:])/g, "$1")
      .trim();
  }

  function stripInlineAzureMapsBlocks(messageContent) {
    const normalizedContent = String(messageContent ?? "");
    if (!normalizedContent.includes("{{map:")) {
      return normalizedContent;
    }

    return normalizeStructuredMessageContent(
      normalizedContent
        .replace(/\n?\{\{map:[\s\S]*?\}\}\n?/g, "\n")
        .replace(/\n{3,}/g, "\n\n")
    );
  }

  function getMentionedParticipants(fullMessageObject = null) {
    const rawMentions = Array.isArray(fullMessageObject?.metadata?.mentioned_participants)
      ? fullMessageObject.metadata.mentioned_participants
      : [];

    return rawMentions
      .map(participant => ({
        user_id: String(participant?.user_id || "").trim(),
        display_name: String(participant?.display_name || participant?.name || participant?.email || "").trim(),
        email: String(participant?.email || "").trim(),
      }))
      .filter(participant => participant.user_id && participant.display_name);
  }

  function stripMentionTextFromMessageContent(messageContent, fullMessageObject = null) {
    let normalizedMessageContent = String(messageContent ?? "");
    if (!normalizedMessageContent.trim()) {
      return normalizedMessageContent;
    }

    const mentions = getMentionedParticipants(fullMessageObject)
      .slice()
      .sort((left, right) => right.display_name.length - left.display_name.length);
    if (mentions.length === 0) {
      return normalizedMessageContent;
    }

    mentions.forEach(participant => {
      const displayName = String(participant.display_name || "").trim();
      if (!displayName) {
        return;
      }

      const mentionPattern = buildAtMentionPattern(displayName);
      normalizedMessageContent = normalizedMessageContent.replace(
        mentionPattern,
        (match, leadingWhitespace) => leadingWhitespace || ""
      );
    });

    const invocationTarget = getInvocationTarget(fullMessageObject);
    if (invocationTarget?.display_name) {
      normalizedMessageContent = normalizedMessageContent.replace(
        buildAtMentionPattern(invocationTarget.display_name),
        (match, leadingWhitespace) => leadingWhitespace || ""
      );
    }

    return normalizeStructuredMessageContent(normalizedMessageContent);
  }

  function renderMentionTagsHtml(fullMessageObject = null) {
    const mentions = getMentionedParticipants(fullMessageObject);
    if (mentions.length === 0) {
      return "";
    }

    const currentUserId = String(window.currentUser?.id || window.currentUser?.user_id || "").trim();
    const mentionChipsHtml = mentions.map(participant => {
      const isCurrentUser = currentUserId && participant.user_id === currentUserId;
      const currentUserClass = isCurrentUser ? " collaboration-mention-chip-current-user" : "";
      return `<span class="collaboration-mention-chip${currentUserClass}" data-mentioned-user-id="${escapeHtml(participant.user_id)}">@${escapeHtml(participant.display_name)}</span>`;
    }).join("");

    return `
      <div class="collaboration-mentions-block" aria-label="Tagged participants">
        <div class="collaboration-mentions-label">Tagged</div>
        <div class="collaboration-mentions-list">${mentionChipsHtml}</div>
      </div>`;
  }

  function getInvocationTarget(fullMessageObject = null) {
    const target = fullMessageObject?.metadata?.ai_invocation_target;
    if (!target || typeof target !== "object") {
      return null;
    }

    const displayName = String(target.display_name || target.label || "").trim();
    if (!displayName) {
      return null;
    }

    const targetType = String(target.target_type || target.type || "model").trim() || "model";
    const sourceMode = String(target.source_mode || target.mode || "").trim() || null;
    return {
      target_type: targetType,
      display_name: displayName,
      mention_text: String(target.mention_text || `@${displayName}`).trim() || `@${displayName}`,
      source_mode: sourceMode,
    };
  }

  function renderInvocationTargetHtml(fullMessageObject = null) {
    const invocationTarget = getInvocationTarget(fullMessageObject);
    if (!invocationTarget) {
      return "";
    }

    const targetTypeClass = ` collaboration-mention-chip-target-${String(invocationTarget.target_type || "model")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]/g, "") || "model"}`;

    return `
      <div class="collaboration-mentions-block" aria-label="AI invocation target">
        <div class="collaboration-mentions-list">
          <span class="collaboration-mention-chip collaboration-mention-chip-target${targetTypeClass}" data-target-type="${escapeHtml(invocationTarget.target_type)}">${escapeHtml(invocationTarget.mention_text)}</span>
        </div>
      </div>`;
  }

  export function renderAiMessageContent(messageContent) {
    const followUpRenderModel = buildFollowUpRenderModel(messageContent);
    let cleaned = stripInlineAzureMapsBlocks(followUpRenderModel.visibleMarkdown).trim().replace(/\n{3,}/g, "\n\n");
    cleaned = cleaned.replace(/(\bhttps?:\/\/\S+)(%5D|\])+/gi, (_, url) => url);

    const chartExtraction = extractInlineChartBlocks(cleaned);
    const imageProposalExtraction = extractInlineImageProposalBlocks(chartExtraction.markdown);
    const withInlineCitations = parseCitations(imageProposalExtraction.markdown);
    const withUnwrappedTables = unwrapTablesFromCodeBlocks(withInlineCitations);
    const withMarkdownTables = convertUnicodeTableToMarkdown(withUnwrappedTables);
    const withPSVTables = convertPSVCodeBlockToMarkdown(withMarkdownTables);
    const withASCIITables = convertASCIIDashTableToMarkdown(withPSVTables);
    const sanitizedHtml = DOMPurify.sanitize(marked.parse(withASCIITables));
    const htmlWithCharts = injectInlineChartHtml(sanitizedHtml, chartExtraction.blocks);
    const htmlWithImageProposals = injectInlineImageProposalHtml(htmlWithCharts, imageProposalExtraction.blocks);
    const copyMarkdown = restoreInlineChartTokens(
      restoreInlineImageProposalTokens(withInlineCitations, imageProposalExtraction.blocks),
      chartExtraction.blocks,
    );

    return {
      htmlContent: addTargetBlankToExternalLinks(htmlWithImageProposals),
      copyMarkdown,
      previewMarkdown: imageProposalExtraction.markdown,
      followUpSuggestions: followUpRenderModel.suggestions,
    };
  }

  function buildFollowUpRenderModel(markdownText) {
    const rawText = String(markdownText || '');
    const suggestions = extractSuggestedFollowUpPrompts(rawText);
    if (!suggestions.length) {
      return {
        visibleMarkdown: rawText,
        suggestions,
      };
    }

    return {
      visibleMarkdown: stripSuggestedFollowUpSourceText(rawText),
      suggestions,
    };
  }

  export function extractSuggestedFollowUpPrompts(markdownText) {
    const rawText = String(markdownText || '').trim();
    if (!rawText) {
      return [];
    }

    const withoutCodeBlocks = rawText.replace(/```[\s\S]*?```/g, '');
    const triggerIndex = findFollowUpTriggerIndex(withoutCodeBlocks);
    if (triggerIndex < 0) {
      return [];
    }

    const suggestionText = withoutCodeBlocks.slice(triggerIndex).split('\n').slice(0, 16).join('\n');
    const suggestions = [];
    const seenSuggestions = new Set();
    const suggestionCandidates = extractFollowUpSuggestionCandidates(suggestionText);

    suggestionCandidates.forEach(candidateText => {
      const cleanedCandidate = normalizeSuggestedPromptText(candidateText);
      if (!isUsefulFollowUpSuggestion(cleanedCandidate)) {
        return;
      }

      const promptText = buildFollowUpPrompt(cleanedCandidate);
      const dedupeKey = promptText.toLowerCase();
      if (seenSuggestions.has(dedupeKey)) {
        return;
      }

      seenSuggestions.add(dedupeKey);
      suggestions.push({
        label: formatSuggestedPromptLabel(cleanedCandidate),
        prompt: promptText,
      });
    });

    return suggestions.slice(0, MAX_SUGGESTED_FOLLOW_UP_ACTIONS);
  }

  function findFollowUpTriggerIndex(text) {
    const indexes = FOLLOW_UP_TRIGGER_PATTERNS
      .map(pattern => {
        const match = pattern.exec(text);
        return match ? match.index : -1;
      })
      .filter(index => index >= 0);
    return indexes.length ? Math.min(...indexes) : -1;
  }

  function stripSuggestedFollowUpSourceText(markdownText) {
    const normalizedText = String(markdownText || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const lines = normalizedText.split('\n');
    const triggerLineIndex = findTrailingFollowUpTriggerLineIndex(lines);
    if (triggerLineIndex < 0) {
      return markdownText;
    }

    const visibleLines = lines.slice(0, triggerLineIndex);
    while (visibleLines.length && !String(visibleLines[visibleLines.length - 1] || '').trim()) {
      visibleLines.pop();
    }

    return visibleLines.join('\n').trimEnd();
  }

  function findTrailingFollowUpTriggerLineIndex(lines) {
    let inCodeBlock = false;
    const trailingStartIndex = Math.max(0, lines.length - 18);

    for (let index = 0; index < lines.length; index += 1) {
      const line = String(lines[index] || '');
      if (line.trim().startsWith('```')) {
        inCodeBlock = !inCodeBlock;
        continue;
      }
      if (inCodeBlock || index < trailingStartIndex) {
        continue;
      }
      if (FOLLOW_UP_TRIGGER_PATTERNS.some(pattern => pattern.test(line))) {
        return index;
      }
    }

    return -1;
  }

  function extractFollowUpSuggestionCandidates(text) {
    const candidates = [];
    const lines = String(text || '').split('\n');

    lines.forEach(line => {
      const normalizedLine = String(line || '').trim();
      if (!normalizedLine) {
        return;
      }

      const candidateMatch = normalizedLine.match(/^\s*(?:[-*]\s+|\d+[.)]\s+)(.+)$/);
      if (candidateMatch) {
        candidates.push(candidateMatch[1]);
        return;
      }

      extractQuestionFollowUpCandidates(normalizedLine).forEach(candidate => {
        candidates.push(candidate);
      });
    });

    return candidates;
  }

  function extractQuestionFollowUpCandidates(line) {
    const questionPattern = /(?:^|\s)(?:or\s+)?(?:do\s+you\s+want\s+me\s+to|do\s+you\s+want\s+(?:a|an|the)|would\s+you\s+like\s+me\s+to|would\s+you\s+like|would\s+you\s+prefer|should\s+i|want\s+me\s+to)\b[^?]*\?/gi;
    const matches = String(line || '').match(questionPattern) || [];

    return matches
      .map(match => normalizeFollowUpQuestionCandidate(match))
      .filter(Boolean);
  }

  function normalizeFollowUpQuestionCandidate(text) {
    let candidate = String(text || '')
      .replace(/^\s*or\s+/i, '')
      .replace(/\?+$/g, '')
      .replace(/\s+/g, ' ')
      .trim();

    const questionScaffolds = [
      /^do\s+you\s+want\s+me\s+to\s+(.+)$/i,
      /^do\s+you\s+want\s+(.+)$/i,
      /^would\s+you\s+like\s+me\s+to\s+(.+)$/i,
      /^would\s+you\s+like\s+(.+)$/i,
      /^would\s+you\s+prefer\s+(?:that\s+i\s+)?(.+)$/i,
      /^should\s+i\s+(.+)$/i,
      /^want\s+me\s+to\s+(.+)$/i,
    ];

    for (const scaffoldPattern of questionScaffolds) {
      const scaffoldMatch = candidate.match(scaffoldPattern);
      if (scaffoldMatch) {
        candidate = scaffoldMatch[1];
        break;
      }
    }

    return normalizeFollowUpPromptPerspective(candidate);
  }

  function normalizeFollowUpPromptPerspective(text) {
    return String(text || '')
      .replace(/\bwalk\s+you\s+through\b/gi, 'walk me through')
      .replace(/\bgive\s+you\b/gi, 'give me')
      .replace(/\bshow\s+you\b/gi, 'show me')
      .replace(/\bsend\s+you\b/gi, 'send me')
      .replace(/\btell\s+you\b/gi, 'tell me')
      .replace(/\bfor\s+you\b/gi, 'for me')
      .trim();
  }

  function normalizeSuggestedPromptText(text) {
    return String(text || '')
      .replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1')
      .replace(/[*_`#>]/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/[.?!:;]+$/, '')
      .slice(0, 180);
  }

  function formatSuggestedPromptLabel(text) {
    const normalizedText = String(text || '').trim();
    if (!normalizedText) {
      return normalizedText;
    }
    return `${normalizedText.charAt(0).toUpperCase()}${normalizedText.slice(1)}`;
  }

  function isUsefulFollowUpSuggestion(text) {
    if (!text || text.length < 8 || text.length > 180) {
      return false;
    }
    if (/^https?:\/\//i.test(text)) {
      return false;
    }
    return /\b(create|build|make|draft|prepare|provide|give|show|list|summarize|compare|export|format|table|csv|markdown|analyze|review|search|find|explain|clarify|expand|rank|filter)\b/i.test(text)
      || /^(a|an)\s+/i.test(text);
  }

  function buildFollowUpPrompt(suggestionText) {
    const trimmedSuggestion = String(suggestionText || '').trim();
    if (/^(please|create|build|make|draft|prepare|provide|give|show|list|summarize|compare|export|analyze|review|search|find|explain|clarify|expand|rank|filter)\b/i.test(trimmedSuggestion)) {
      return trimmedSuggestion;
    }
    if (/^(a|an)\s+/i.test(trimmedSuggestion)) {
      return `Please provide ${trimmedSuggestion.charAt(0).toLowerCase()}${trimmedSuggestion.slice(1)}.`;
    }
    return `Please ${trimmedSuggestion.charAt(0).toLowerCase()}${trimmedSuggestion.slice(1)}.`;
  }

  function renderSuggestedFollowUpButtons(messageDiv, suggestedPrompts) {
    const suggestions = Array.isArray(suggestedPrompts)
      ? suggestedPrompts.slice(0, MAX_SUGGESTED_FOLLOW_UP_ACTIONS)
      : extractSuggestedFollowUpPrompts(suggestedPrompts);
    if (!suggestions.length) {
      return;
    }

    const messageText = messageDiv.querySelector('.message-text');
    if (!messageText) {
      return;
    }

    const container = document.createElement('div');
    container.className = 'assistant-follow-up-actions';

    suggestions.forEach(suggestion => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-sm btn-outline-primary assistant-follow-up-action';
      button.textContent = suggestion.label;
      button.title = 'Use this as the next prompt';
      button.addEventListener('click', () => {
        stageFollowUpPrompt(suggestion.prompt);
      });
      container.appendChild(button);
    });

    messageText.insertAdjacentElement('afterend', container);
  }

  function stageFollowUpPrompt(promptText) {
    if (!userInput) {
      return;
    }
    clearFollowUpAutoSendCountdown();
    userInput.value = String(promptText || '').trim();
    userInput.style.height = '';
    userInput.style.height = `${Math.min(userInput.scrollHeight, 200)}px`;
    userInput.dispatchEvent(new Event('input', { bubbles: true }));
    updateSendButtonVisibility();
    userInput.focus();
    startFollowUpAutoSendCountdown();
  }

  function startFollowUpAutoSendCountdown() {
    if (!sendBtn) {
      return;
    }

    const totalCountdownMs = 5000;
    const originalHtml = sendBtn.innerHTML;
    const originalDisabled = sendBtn.disabled;
    const progressElement = document.createElement('span');
    progressElement.className = 'follow-up-send-progress';
    progressElement.setAttribute('aria-hidden', 'true');
    sendBtn.classList.add('follow-up-auto-send-active');
    sendBtn.appendChild(progressElement);

    followUpAutoSendCancel = event => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      clearFollowUpAutoSendCountdown(originalHtml, originalDisabled);
      showToast('Follow-up prompt staged. Click Send when ready.', 'info');
    };
    sendBtn.addEventListener('click', followUpAutoSendCancel, true);

    const startTime = Date.now();
    const updateProgress = () => {
      const progress = Math.min((Date.now() - startTime) / totalCountdownMs, 1);
      progressElement.style.setProperty('--follow-up-send-progress', `${progress * 100}%`);

      if (progress < 1) {
        followUpAutoSendFrame = requestAnimationFrame(updateProgress);
        return;
      }

      clearFollowUpAutoSendCountdown(originalHtml, originalDisabled);
      sendMessage();
    };

    followUpAutoSendFrame = requestAnimationFrame(updateProgress);
  }

  function clearFollowUpAutoSendCountdown(originalHtml = null, originalDisabled = null) {
    if (followUpAutoSendFrame) {
      cancelAnimationFrame(followUpAutoSendFrame);
      followUpAutoSendFrame = null;
    }
    if (sendBtn && followUpAutoSendCancel) {
      sendBtn.removeEventListener('click', followUpAutoSendCancel, true);
    }
    followUpAutoSendCancel = null;
    if (sendBtn) {
      const progressElement = sendBtn.querySelector('.follow-up-send-progress');
      if (progressElement) {
        progressElement.remove();
      }
      sendBtn.classList.remove('follow-up-auto-send-active');
      if (originalHtml !== null) {
        sendBtn.innerHTML = originalHtml;
      }
      if (originalDisabled !== null) {
        sendBtn.disabled = originalDisabled;
      }
    }
  }

  function getLatestUserPromptText() {
    if (!chatbox) {
      return '';
    }

    const userMessages = Array.from(chatbox.querySelectorAll('.message.user-message'));
    for (let index = userMessages.length - 1; index >= 0; index -= 1) {
      const userMessage = userMessages[index];
      const previewText = String(userMessage?.dataset?.replyPreviewText || '').trim();
      if (previewText) {
        return previewText;
      }

      const messageText = userMessage.querySelector('.message-text');
      const visibleText = String(messageText?.innerText || messageText?.textContent || '').trim();
      if (visibleText) {
        return visibleText;
      }
    }

    return '';
  }

  function getMostRecentRenderedMessage() {
    if (!chatbox) {
      return null;
    }

    const renderedMessages = Array.from(chatbox.children).filter(child => {
      return child instanceof HTMLElement && child.classList.contains('message');
    });

    return renderedMessages.length ? renderedMessages[renderedMessages.length - 1] : null;
  }

  function getInlineAssistantExportActionTypes(promptText) {
    const normalizedPromptText = String(promptText || '').trim();
    if (!normalizedPromptText || !INLINE_ASSISTANT_EXPORT_VERB_PATTERN.test(normalizedPromptText)) {
      return [];
    }

    const actionTypes = new Set();
    const hasPowerPointIntent = INLINE_ASSISTANT_EXPORT_PATTERNS.powerpoint.test(normalizedPromptText);
    const hasPresentationIntent = INLINE_ASSISTANT_EXPORT_PATTERNS.presentation.test(normalizedPromptText);

    if (hasPowerPointIntent) {
      actionTypes.add('powerpoint');
    }

    if (INLINE_ASSISTANT_EXPORT_PATTERNS.word.test(normalizedPromptText)) {
      actionTypes.add('word');
    }

    if (INLINE_ASSISTANT_EXPORT_PATTERNS.markdown.test(normalizedPromptText)) {
      actionTypes.add('markdown');
    }

    if (INLINE_ASSISTANT_EXPORT_PATTERNS.email.test(normalizedPromptText)) {
      actionTypes.add('email');
    }

    if (hasPresentationIntent && !hasPowerPointIntent) {
      actionTypes.add('powerpoint');
      actionTypes.add('word');
    }

    return INLINE_ASSISTANT_EXPORT_ACTION_ORDER.filter(actionType => actionTypes.has(actionType));
  }

  function isStreamingAssistantPlaceholder(messageId, fullMessageObject = null) {
    const normalizedMessageId = String(messageId || '').trim();
    if (normalizedMessageId.startsWith('temp_ai_')) {
      return true;
    }

    const metadata = fullMessageObject?.metadata;
    return Boolean(
      metadata?.is_streaming_placeholder
      || metadata?.streaming_placeholder
      || metadata?.stream_status === 'streaming'
    );
  }

  function shouldRenderCompletedAssistantActions(messageId, fullMessageObject = null) {
    return !isStreamingAssistantPlaceholder(messageId, fullMessageObject);
  }

  function buildInlineAssistantExportActionsHtml(messageId) {
    const previousMessage = getMostRecentRenderedMessage();
    if (!(previousMessage instanceof HTMLElement) || !previousMessage.classList.contains('user-message')) {
      return '';
    }

    const actionTypes = getInlineAssistantExportActionTypes(getLatestUserPromptText());
    if (!actionTypes.length) {
      return '';
    }

    const buttonsHtml = actionTypes.map(actionType => {
      const actionConfig = INLINE_ASSISTANT_EXPORT_ACTIONS[actionType];
      if (!actionConfig) {
        return '';
      }

      return `
        <button
          type="button"
          class="btn btn-sm btn-outline-primary ${actionConfig.buttonClass}"
          data-message-id="${messageId}"
          data-default-label="${actionConfig.label}"
          data-pending-label="${actionConfig.pendingLabel || actionConfig.label}"
          data-icon-class="${actionConfig.iconClass}"
          data-default-title="${actionConfig.title}"
          title="${actionConfig.title}">
          <i class="${actionConfig.iconClass} me-1"></i>${actionConfig.label}
        </button>`;
    }).join('');

    if (!buttonsHtml) {
      return '';
    }

    return `
      <div class="inline-assistant-export-actions d-flex flex-wrap gap-2 mt-3" aria-label="Quick export actions">
        ${buttonsHtml}
      </div>`;
  }

  function normalizeGeneratedAnalysisArtifact(output, defaultCapability = 'analysis') {
    if (!output || typeof output !== 'object') {
      return null;
    }

    const normalizedArtifactMessageId = String(output.artifact_message_id || '').trim();
    const normalizedDocumentId = String(output.document_id || '').trim();
    const normalizedExportRunId = String(output.export_run_id || output.run_id || '').trim();
    const isBackgroundExport = Boolean(output.background_export) && Boolean(normalizedExportRunId);
    if (!normalizedArtifactMessageId && !normalizedDocumentId && !isBackgroundExport) {
      return null;
    }

    return {
      ...output,
      capability: String(output.capability || defaultCapability || 'analysis').trim().toLowerCase() || 'analysis',
      artifact_message_id: normalizedArtifactMessageId,
      document_id: normalizedDocumentId,
      export_run_id: normalizedExportRunId,
      run_id: normalizedExportRunId,
      background_export: isBackgroundExport,
    };
  }

  function getGeneratedAnalysisArtifacts(fullMessageObject = null) {
    const normalizedArtifacts = [];
    const seenArtifacts = new Set();
    const rawArtifacts = Array.isArray(fullMessageObject?.metadata?.generated_analysis_artifacts)
      ? fullMessageObject.metadata.generated_analysis_artifacts
      : [];
    const rawTabularOutputs = Array.isArray(fullMessageObject?.metadata?.generated_tabular_outputs)
      ? fullMessageObject.metadata.generated_tabular_outputs
      : [];

    const appendArtifact = (output, defaultCapability = 'analysis') => {
      const normalizedArtifact = normalizeGeneratedAnalysisArtifact(output, defaultCapability);
      if (!normalizedArtifact) {
        return;
      }

      const dedupeKey = normalizedArtifact.artifact_message_id
        || normalizedArtifact.document_id
        || normalizedArtifact.export_run_id
        || `${String(normalizedArtifact.file_name || '').trim()}:${String(normalizedArtifact.output_format || '').trim()}`;

      if (seenArtifacts.has(dedupeKey)) {
        return;
      }

      seenArtifacts.add(dedupeKey);
      normalizedArtifacts.push(normalizedArtifact);
    };

    rawArtifacts.forEach(output => appendArtifact(output, 'analysis'));
    rawTabularOutputs.forEach(output => appendArtifact(output, 'tabular'));

    return normalizedArtifacts;
  }

  function getGeneratedTabularOutputs(fullMessageObject = null) {
    return getGeneratedAnalysisArtifacts(fullMessageObject).filter(output => output.capability === 'tabular');
  }

  function getGeneratedTabularStorageNote(outputMetadata) {
    if (outputMetadata?.background_export) {
      return 'Continuing in the background. Progress is checkpointed and the download will appear here when complete.';
    }

    const storageScope = String(outputMetadata?.storage_scope || '').trim().toLowerCase();
    if (storageScope === 'chat') {
      return 'Saved to this chat for download in this conversation.';
    }

    return 'Saved to your personal workspace for reuse in future chats.';
  }

  function formatGeneratedTabularRowCount(rowCount) {
    const normalizedRowCount = Number.parseInt(rowCount, 10);
    if (!Number.isFinite(normalizedRowCount) || normalizedRowCount < 0) {
      return '';
    }

    return normalizedRowCount.toLocaleString();
  }

  function clampGeneratedOutputProgress(value) {
    const numericValue = Number.parseFloat(value);
    if (!Number.isFinite(numericValue)) {
      return 0;
    }

    return Math.max(0, Math.min(100, numericValue));
  }

  function calculateGeneratedOutputProgress(outputMetadata) {
    const explicitPercent = Number.parseFloat(outputMetadata?.progress_percent);
    if (Number.isFinite(explicitPercent)) {
      return clampGeneratedOutputProgress(explicitPercent);
    }

    const completedBatches = Number.parseInt(outputMetadata?.completed_batches, 10);
    const batchCount = Number.parseInt(outputMetadata?.batch_count, 10);
    if (Number.isFinite(completedBatches) && Number.isFinite(batchCount) && batchCount > 0) {
      return clampGeneratedOutputProgress((completedBatches / batchCount) * 100);
    }

    return 0;
  }

  function formatGeneratedOutputStatusLabel(status, outputMetadata = null) {
    const explicitLabel = String(outputMetadata?.status_label || '').trim();
    if (explicitLabel) {
      return explicitLabel;
    }

    const normalizedStatus = String(status || '').trim().toLowerCase();
    if (normalizedStatus === 'completed') {
      return 'Complete';
    }
    if (normalizedStatus === 'failed') {
      return 'Failed';
    }
    if (normalizedStatus === 'canceled') {
      return 'Canceled';
    }
    if (normalizedStatus === 'running') {
      return 'Running';
    }

    return 'Queued';
  }

  function getGeneratedOutputStatusBadgeClass(outputMetadata) {
    const statusTone = String(outputMetadata?.status_tone || '').trim().toLowerCase();
    if (statusTone === 'success') {
      return 'badge text-bg-success';
    }
    if (statusTone === 'warning') {
      return 'badge text-bg-warning';
    }
    if (statusTone === 'danger') {
      return 'badge text-bg-danger';
    }
    if (statusTone === 'secondary') {
      return 'badge text-bg-secondary';
    }
    return 'badge text-bg-info';
  }

  function formatGeneratedOutputTimestamp(value) {
    const normalizedValue = String(value || '').trim();
    if (!normalizedValue) {
      return '';
    }
    const parsedDate = new Date(normalizedValue);
    if (Number.isNaN(parsedDate.getTime())) {
      return normalizedValue;
    }
    return parsedDate.toLocaleString();
  }

  function formatGeneratedOutputDuration(seconds) {
    const normalizedSeconds = Number.parseInt(seconds, 10);
    if (!Number.isFinite(normalizedSeconds) || normalizedSeconds < 0) {
      return '';
    }
    if (normalizedSeconds < 60) {
      return '<1 min';
    }

    const totalMinutes = Math.max(1, Math.round(normalizedSeconds / 60));
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    if (!hours) {
      return `${totalMinutes} min`;
    }
    if (!minutes) {
      return `${hours} hr`;
    }
    return `${hours} hr ${minutes} min`;
  }

  function getBackgroundGeneratedOutputContinueLabel(outputMetadata) {
    if (outputMetadata?.waiting_for_retry) {
      return 'Continue Now';
    }
    return 'Continue';
  }

  function canContinueBackgroundGeneratedOutput(outputMetadata) {
    return Boolean(outputMetadata?.background_export && outputMetadata?.can_resume);
  }

  function updateBackgroundGeneratedOutputContinueButton(continueButton, outputMetadata) {
    if (!(continueButton instanceof HTMLElement)) {
      return;
    }

    const canContinue = canContinueBackgroundGeneratedOutput(outputMetadata);
    continueButton.classList.toggle('d-none', !canContinue);
    continueButton.disabled = !canContinue;
    if (continueButton.dataset.busy !== 'true') {
      continueButton.textContent = getBackgroundGeneratedOutputContinueLabel(outputMetadata);
    }
  }

  function formatGeneratedTabularPreviewValue(value, maxLength = 120) {
    let formattedValue = '';

    if (value === null || typeof value === 'undefined') {
      formattedValue = '';
    } else if (typeof value === 'string') {
      formattedValue = value;
    } else if (typeof value === 'number' || typeof value === 'boolean') {
      formattedValue = String(value);
    } else {
      try {
        formattedValue = JSON.stringify(value);
      } catch (error) {
        formattedValue = String(value);
      }
    }

    if (formattedValue.length <= maxLength) {
      return formattedValue;
    }

    return `${formattedValue.slice(0, maxLength - 1)}…`;
  }

  function isGeneratedTabularPreviewObjectRow(row) {
    return Boolean(row) && typeof row === 'object' && !Array.isArray(row);
  }

  function buildGeneratedTabularPreviewTable(previewRows) {
    if (!Array.isArray(previewRows) || !previewRows.length || !previewRows.every(isGeneratedTabularPreviewObjectRow)) {
      return null;
    }

    const previewColumns = [];
    previewRows.forEach(row => {
      Object.keys(row).forEach(columnName => {
        if (!previewColumns.includes(columnName)) {
          previewColumns.push(columnName);
        }
      });
    });

    if (!previewColumns.length) {
      return null;
    }

    const displayedColumns = previewColumns.slice(0, 4);
    const tableWrapper = document.createElement('div');
    tableWrapper.className = 'table-responsive small border rounded';

    const table = document.createElement('table');
    table.className = 'table table-sm align-middle mb-0';

    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    displayedColumns.forEach(columnName => {
      const headerCell = document.createElement('th');
      headerCell.scope = 'col';
      headerCell.textContent = columnName;
      headerRow.appendChild(headerCell);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    previewRows.forEach(row => {
      const tableRow = document.createElement('tr');
      displayedColumns.forEach(columnName => {
        const valueCell = document.createElement('td');
        valueCell.textContent = formatGeneratedTabularPreviewValue(row[columnName]);
        tableRow.appendChild(valueCell);
      });
      tbody.appendChild(tableRow);
    });
    table.appendChild(tbody);
    tableWrapper.appendChild(table);

    if (previewColumns.length > displayedColumns.length) {
      const hiddenColumnsNotice = document.createElement('div');
      hiddenColumnsNotice.className = 'small text-muted mt-2';
      hiddenColumnsNotice.textContent = `Preview limited to ${displayedColumns.length} of ${previewColumns.length} fields.`;
      tableWrapper.appendChild(hiddenColumnsNotice);
    }

    return tableWrapper;
  }

  function formatGeneratedAnalysisPreviewBlock(previewBlock, options = {}) {
    const preserveWhitespace = options.preserveWhitespace !== false;
    previewBlock.className = 'generated-analysis-preview-block small bg-light border rounded p-2 mb-0 overflow-auto text-break';
    previewBlock.style.whiteSpace = preserveWhitespace ? 'pre-wrap' : 'normal';
    previewBlock.style.wordBreak = 'break-word';
    previewBlock.style.overflowWrap = 'anywhere';
    previewBlock.style.maxWidth = '100%';
    return previewBlock;
  }

  function isGeneratedMarkdownArtifact(outputMetadata, outputFormat) {
    const normalizedOutputFormat = String(outputFormat || outputMetadata?.output_format || '').trim().toLowerCase();
    if (normalizedOutputFormat === 'md' || normalizedOutputFormat === 'markdown') {
      return true;
    }

    const fileName = String(outputMetadata?.file_name || '').trim().toLowerCase();
    return fileName.endsWith('.md') || fileName.endsWith('.markdown');
  }

  function buildGeneratedAnalysisMarkdownPreview(previewText) {
    const previewBlock = formatGeneratedAnalysisPreviewBlock(document.createElement('div'), { preserveWhitespace: false });
    previewBlock.classList.add('generated-analysis-markdown-preview');

    const normalizedPreviewText = String(previewText || '').trim();
    if (!normalizedPreviewText) {
      return previewBlock;
    }

    const sanitizedHtml = DOMPurify.sanitize(marked.parse(normalizedPreviewText));
    const linkedHtml = addTargetBlankToExternalLinks(sanitizedHtml);
    previewBlock.innerHTML = DOMPurify.sanitize(linkedHtml);
    return previewBlock;
  }

  function buildGeneratedTabularPreviewFallback(previewRows) {
    const previewBlock = formatGeneratedAnalysisPreviewBlock(document.createElement('pre'));

    try {
      previewBlock.textContent = JSON.stringify(previewRows || [], null, 2);
    } catch (error) {
      previewBlock.textContent = String(previewRows || '[]');
    }

    return previewBlock;
  }

  function buildGeneratedAnalysisPreviewText(previewText, outputMetadata = null, outputFormat = '') {
    if (isGeneratedMarkdownArtifact(outputMetadata, outputFormat)) {
      return buildGeneratedAnalysisMarkdownPreview(previewText);
    }

    const previewBlock = formatGeneratedAnalysisPreviewBlock(document.createElement('pre'));
    previewBlock.textContent = String(previewText || '').trim();
    return previewBlock;
  }

  function getGeneratedAnalysisArtifactTitle(outputMetadata, outputFormat) {
    const capability = String(outputMetadata?.capability || '').trim().toLowerCase();
    if (capability === 'analyze') {
      return `Analyze ${outputFormat.toUpperCase()} artifact`;
    }
    if (capability === 'comparison') {
      return `Comparison ${outputFormat.toUpperCase()} artifact`;
    }

    return `Generated ${outputFormat.toUpperCase()} export`;
  }

  function shouldCollapseGeneratedAnalysisPreview(outputMetadata) {
    const capability = String(outputMetadata?.capability || '').trim().toLowerCase();
    return capability === 'analyze' || capability === 'comparison';
  }

  function shouldRenderPreviewItemsAsRows(outputMetadata, outputFormat) {
    const normalizedOutputFormat = String(outputFormat || outputMetadata?.output_format || '').trim().toLowerCase();
    return ['csv', 'tsv', 'xls', 'xlsx', 'xlsm'].includes(normalizedOutputFormat);
  }

  function buildGeneratedArtifactDownloadUrl(outputMetadata) {
    const normalizedDocId = String(outputMetadata?.document_id || '').trim();
    const normalizedArtifactMessageId = String(outputMetadata?.artifact_message_id || '').trim();
    const normalizedConversationId = String(outputMetadata?.conversation_id || window.currentConversationId || '').trim();

    if (normalizedArtifactMessageId && normalizedConversationId) {
      return `/api/chat_artifacts/download?conversation_id=${encodeURIComponent(normalizedConversationId)}&message_id=${encodeURIComponent(normalizedArtifactMessageId)}`;
    }

    if (normalizedDocId) {
      return `/api/workspace_documents/download?doc_id=${encodeURIComponent(normalizedDocId)}`;
    }

    return '';
  }

  function triggerGeneratedTabularOutputDownload(outputMetadata) {
    const downloadHref = buildGeneratedArtifactDownloadUrl(outputMetadata);

    if (!downloadHref) {
      showToast('Generated export is missing download metadata.', 'warning');
      return;
    }

    const downloadLink = document.createElement('a');
    downloadLink.href = downloadHref;
    downloadLink.rel = 'noopener';
    downloadLink.className = 'd-none';
    document.body.appendChild(downloadLink);
    downloadLink.click();
    downloadLink.remove();
  }

  async function viewGeneratedMarkdownArtifact(outputMetadata, viewButton) {
    const downloadHref = buildGeneratedArtifactDownloadUrl(outputMetadata);
    const fileName = String(outputMetadata?.file_name || 'generated-artifact.md').trim() || 'generated-artifact.md';

    if (!downloadHref) {
      showToast('Generated Markdown artifact is missing view metadata.', 'warning');
      return;
    }

    const originalButtonText = viewButton?.textContent || 'View MD';
    if (viewButton) {
      viewButton.disabled = true;
      viewButton.textContent = 'Opening...';
    }

    try {
      const response = await fetch(downloadHref, {
        method: 'GET',
        headers: {
          'Accept': 'text/markdown, text/plain, */*',
        },
      });

      if (!response.ok) {
        throw new Error(`Server responded with status ${response.status}`);
      }

      const markdownContent = await response.text();
      showCitedTextPopup(markdownContent, fileName, 'Markdown', {
        renderMarkdown: true,
        title: `Markdown artifact: ${fileName}`,
      });
    } catch (error) {
      showToast(error.message || 'Could not open the generated Markdown artifact.', 'danger');
    } finally {
      if (viewButton) {
        viewButton.disabled = false;
        viewButton.textContent = originalButtonText;
      }
    }
  }

  function getGeneratedArtifactGroupName(groupId) {
    const normalizedGroupId = String(groupId || '').trim();
    if (!normalizedGroupId) {
      return 'Group workspace';
    }

    const matchingGroup = (window.userGroups || []).find(group => String(group?.id || '').trim() === normalizedGroupId);
    return String(matchingGroup?.name || window.activeGroupName || 'Group workspace').trim() || 'Group workspace';
  }

  function getGeneratedArtifactPublicWorkspaceName(publicWorkspaceId) {
    const normalizedWorkspaceId = String(publicWorkspaceId || '').trim();
    if (!normalizedWorkspaceId) {
      return 'Public workspace';
    }

    const matchingWorkspace = (window.userVisiblePublicWorkspaces || []).find(workspace => String(workspace?.id || '').trim() === normalizedWorkspaceId);
    return String(matchingWorkspace?.name || 'Public workspace').trim() || 'Public workspace';
  }

  function createGeneratedArtifactPromotionTarget(workspaceScope, options = {}) {
    const normalizedScope = String(workspaceScope || 'personal').trim().toLowerCase();
    if (normalizedScope === 'group') {
      const groupId = String(options.groupId || '').trim();
      const groupName = getGeneratedArtifactGroupName(groupId);
      return {
        targetId: `group:${groupId}`,
        workspace_scope: 'group',
        group_id: groupId,
        label: groupName,
        displayName: groupName,
        detail: 'Group workspace approval request',
      };
    }

    if (normalizedScope === 'public') {
      const publicWorkspaceId = String(options.publicWorkspaceId || '').trim();
      const publicWorkspaceName = getGeneratedArtifactPublicWorkspaceName(publicWorkspaceId);
      return {
        targetId: `public:${publicWorkspaceId}`,
        workspace_scope: 'public',
        public_workspace_id: publicWorkspaceId,
        label: publicWorkspaceName,
        displayName: publicWorkspaceName,
        detail: 'Public workspace approval request',
      };
    }

    return {
      targetId: 'personal',
      workspace_scope: 'personal',
      label: 'personal workspace',
      displayName: 'Personal workspace',
      detail: 'Private to you',
    };
  }

  function dedupeGeneratedArtifactPromotionTargets(targets) {
    const seenTargetIds = new Set();
    const dedupedTargets = [];
    targets.forEach(target => {
      const targetId = String(target?.targetId || '').trim();
      if (!targetId || seenTargetIds.has(targetId)) {
        return;
      }
      seenTargetIds.add(targetId);
      dedupedTargets.push(target);
    });
    return dedupedTargets;
  }

  function getGeneratedArtifactPromotionTargets() {
    const activeConversationScope = getActiveConversationScope();
    const activeConversationContext = getActiveConversationContext();

    if (activeConversationScope === 'group' && activeConversationContext.groupId) {
      return [createGeneratedArtifactPromotionTarget('group', { groupId: activeConversationContext.groupId })];
    }

    if (activeConversationScope === 'public' && activeConversationContext.publicWorkspaceId) {
      return [createGeneratedArtifactPromotionTarget('public', { publicWorkspaceId: activeConversationContext.publicWorkspaceId })];
    }

    if (activeConversationScope === 'personal') {
      return [createGeneratedArtifactPromotionTarget('personal')];
    }

    const effectiveScopes = getEffectiveScopes();
    const hasPersonalScope = Boolean(effectiveScopes?.personal);
    const groupIds = Array.isArray(effectiveScopes?.groupIds)
      ? effectiveScopes.groupIds.filter(Boolean)
      : [];
    const publicWorkspaceIds = Array.isArray(effectiveScopes?.publicWorkspaceIds)
      ? effectiveScopes.publicWorkspaceIds.filter(Boolean)
      : [];
    const targets = [];

    if (hasPersonalScope) {
      targets.push(createGeneratedArtifactPromotionTarget('personal'));
    }
    groupIds.forEach(groupId => {
      targets.push(createGeneratedArtifactPromotionTarget('group', { groupId }));
    });
    publicWorkspaceIds.forEach(publicWorkspaceId => {
      targets.push(createGeneratedArtifactPromotionTarget('public', { publicWorkspaceId }));
    });

    const resolvedTargets = dedupeGeneratedArtifactPromotionTargets(targets);
    if (!resolvedTargets.length) {
      resolvedTargets.push(createGeneratedArtifactPromotionTarget('personal'));
    }

    return resolvedTargets;
  }

  function resolveGeneratedArtifactPromotionTarget() {
    const targets = getGeneratedArtifactPromotionTargets();
    if (targets.length === 1) {
      return targets[0];
    }

    return {
      requiresSelection: true,
      targets,
    };
  }

  function getGeneratedArtifactPromotionModalElements() {
    let modal = document.getElementById('generated-artifact-workspace-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.className = 'modal fade';
      modal.id = 'generated-artifact-workspace-modal';
      modal.tabIndex = -1;
      modal.setAttribute('aria-labelledby', 'generated-artifact-workspace-modal-label');
      modal.setAttribute('aria-hidden', 'true');

      const dialog = document.createElement('div');
      dialog.className = 'modal-dialog modal-dialog-centered';
      modal.appendChild(dialog);

      const content = document.createElement('div');
      content.className = 'modal-content';
      dialog.appendChild(content);

      const header = document.createElement('div');
      header.className = 'modal-header';
      content.appendChild(header);

      const title = document.createElement('h5');
      title.className = 'modal-title';
      title.id = 'generated-artifact-workspace-modal-label';
      header.appendChild(title);

      const closeButton = document.createElement('button');
      closeButton.type = 'button';
      closeButton.className = 'btn-close';
      closeButton.setAttribute('data-bs-dismiss', 'modal');
      closeButton.setAttribute('aria-label', 'Close');
      header.appendChild(closeButton);

      const body = document.createElement('div');
      body.className = 'modal-body';
      content.appendChild(body);

      const description = document.createElement('p');
      description.className = 'mb-3';
      description.id = 'generated-artifact-workspace-modal-description';
      body.appendChild(description);

      const choiceList = document.createElement('div');
      choiceList.className = 'd-grid gap-2';
      choiceList.id = 'generated-artifact-workspace-targets';
      body.appendChild(choiceList);

      const footer = document.createElement('div');
      footer.className = 'modal-footer';
      content.appendChild(footer);

      const cancelButton = document.createElement('button');
      cancelButton.type = 'button';
      cancelButton.className = 'btn btn-outline-secondary';
      cancelButton.setAttribute('data-bs-dismiss', 'modal');
      cancelButton.textContent = 'Cancel';
      footer.appendChild(cancelButton);

      const confirmButton = document.createElement('button');
      confirmButton.type = 'button';
      confirmButton.className = 'btn btn-primary';
      confirmButton.id = 'generated-artifact-workspace-confirm-btn';
      footer.appendChild(confirmButton);

      document.body.appendChild(modal);
    }

    return {
      modal,
      title: modal.querySelector('#generated-artifact-workspace-modal-label'),
      description: modal.querySelector('#generated-artifact-workspace-modal-description'),
      choiceList: modal.querySelector('#generated-artifact-workspace-targets'),
      confirmButton: modal.querySelector('#generated-artifact-workspace-confirm-btn'),
    };
  }

  function getGeneratedArtifactPromotionConfirmText(targets) {
    if (!Array.isArray(targets) || targets.length !== 1) {
      return 'Add to Selected Workspace';
    }

    const targetScope = targets[0]?.workspace_scope;
    if (targetScope === 'personal') {
      return 'Add to Personal';
    }
    if (targetScope === 'group') {
      return 'Submit to Group';
    }
    if (targetScope === 'public') {
      return 'Submit to Public';
    }
    return 'Add to Workspace';
  }

  function createGeneratedArtifactPromotionChoice(target, checked) {
    const targetOption = document.createElement('label');
    targetOption.className = 'generated-artifact-workspace-target-option border rounded p-3 d-flex gap-2 align-items-start';

    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.className = 'form-check-input mt-1';
    radio.name = 'generated-artifact-workspace-target';
    radio.value = target.targetId;
    radio.checked = checked;
    targetOption.appendChild(radio);

    const textWrapper = document.createElement('span');
    textWrapper.className = 'd-block';
    targetOption.appendChild(textWrapper);

    const title = document.createElement('span');
    title.className = 'd-block fw-semibold';
    title.textContent = target.displayName;
    textWrapper.appendChild(title);

    const detail = document.createElement('span');
    detail.className = 'd-block small text-muted';
    detail.textContent = target.detail;
    textWrapper.appendChild(detail);

    return targetOption;
  }

  function chooseGeneratedArtifactPromotionTarget(outputMetadata) {
    const targets = getGeneratedArtifactPromotionTargets();
    const artifactFileName = String(outputMetadata?.file_name || 'this generated artifact').trim() || 'this generated artifact';
    const modalElements = getGeneratedArtifactPromotionModalElements();
    if (!modalElements.modal || !modalElements.choiceList || !modalElements.confirmButton) {
      return Promise.resolve(targets[0] || createGeneratedArtifactPromotionTarget('personal'));
    }

    const isSingleTarget = targets.length === 1;
    const targetTitle = isSingleTarget
      ? `Add to ${targets[0].displayName}?`
      : 'Choose Workspace';
    const targetDescription = isSingleTarget
      ? `${artifactFileName} will be saved to ${targets[0].displayName}.`
      : `Select where to save ${artifactFileName}.`;

    modalElements.title.textContent = targetTitle;
    modalElements.description.textContent = targetDescription;
    modalElements.confirmButton.textContent = getGeneratedArtifactPromotionConfirmText(targets);
    modalElements.choiceList.replaceChildren();
    targets.forEach((target, index) => {
      modalElements.choiceList.appendChild(createGeneratedArtifactPromotionChoice(target, index === 0));
    });

    return new Promise(resolve => {
      let hasResolved = false;
      const modalInstance = window.bootstrap?.Modal?.getOrCreateInstance(modalElements.modal);

      const cleanup = () => {
        modalElements.confirmButton.removeEventListener('click', handleConfirm);
        modalElements.modal.removeEventListener('hidden.bs.modal', handleHidden);
      };

      const resolveOnce = value => {
        if (hasResolved) {
          return;
        }
        hasResolved = true;
        cleanup();
        resolve(value);
      };

      const handleConfirm = () => {
        const selectedInput = modalElements.choiceList.querySelector('input[name="generated-artifact-workspace-target"]:checked');
        const selectedTargetId = String(selectedInput?.value || '').trim();
        const selectedTarget = targets.find(target => target.targetId === selectedTargetId) || targets[0] || null;
        resolveOnce(selectedTarget);
        modalInstance?.hide();
      };

      const handleHidden = () => {
        resolveOnce(null);
      };

      modalElements.confirmButton.addEventListener('click', handleConfirm);
      modalElements.modal.addEventListener('hidden.bs.modal', handleHidden);

      if (modalInstance) {
        modalInstance.show();
      } else {
        resolveOnce(targets[0] || createGeneratedArtifactPromotionTarget('personal'));
      }
    });
  }

  async function promoteGeneratedArtifactToWorkspace(outputMetadata, promoteButton) {
    const normalizedArtifactMessageId = String(outputMetadata?.artifact_message_id || '').trim();
    const normalizedConversationId = String(outputMetadata?.conversation_id || window.currentConversationId || '').trim();

    if (!normalizedArtifactMessageId || !normalizedConversationId) {
      showToast('Generated export is missing promotion metadata.', 'warning');
      return;
    }

    const target = await chooseGeneratedArtifactPromotionTarget(outputMetadata);
    if (!target) {
      return;
    }

    const originalButtonText = promoteButton?.textContent || 'Add to Workspace';
    if (promoteButton) {
      promoteButton.disabled = true;
      promoteButton.textContent = 'Adding...';
    }

    try {
      const requestPayload = {
        conversation_id: normalizedConversationId,
        message_id: normalizedArtifactMessageId,
        workspace_scope: target.workspace_scope,
      };
      if (target.group_id) {
        requestPayload.group_id = target.group_id;
      }
      if (target.public_workspace_id) {
        requestPayload.public_workspace_id = target.public_workspace_id;
      }

      const response = await fetch('/api/chat_artifacts/promote', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestPayload),
      });

      const responseData = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(responseData?.error || `Server responded with status ${response.status}`);
      }

      const approvalRequired = Boolean(responseData?.approval_required);
      const successMessage = approvalRequired
        ? `Artifact submitted to the ${target.label} for approval.`
        : `Artifact added to your ${target.label}.`;
      showToast(successMessage, 'success');

      if (promoteButton) {
        promoteButton.classList.remove('btn-outline-secondary');
        promoteButton.classList.add(approvalRequired ? 'btn-outline-warning' : 'btn-outline-success');
        promoteButton.textContent = approvalRequired ? 'Pending Approval' : 'Added to Workspace';
      }
    } catch (error) {
      if (promoteButton) {
        promoteButton.disabled = false;
        promoteButton.textContent = originalButtonText;
      }
      showToast(error.message || 'Failed to add the generated artifact to a workspace.', 'danger');
    }
  }

  async function exportGeneratedMarkdownArtifactAsPowerPoint(outputMetadata, exportButton) {
    const normalizedArtifactMessageId = String(outputMetadata?.artifact_message_id || '').trim();
    const normalizedConversationId = String(outputMetadata?.conversation_id || window.currentConversationId || '').trim();
    const parentMessageDiv = exportButton?.closest('.message');
    const parentMessageId = String(parentMessageDiv?.getAttribute('data-message-id') || '').trim();

    if (!normalizedArtifactMessageId || !normalizedConversationId || !parentMessageId) {
      showToast('Generated Markdown artifact is missing PowerPoint export metadata.', 'warning');
      return;
    }

    const originalButtonText = exportButton?.textContent || 'Create PowerPoint';
    if (exportButton) {
      exportButton.disabled = true;
      exportButton.textContent = 'Creating...';
    }

    try {
      const module = await import('./chat-message-export.js');
      if (typeof module.exportMessageAsPowerPoint === 'function') {
        await module.exportMessageAsPowerPoint(parentMessageDiv, parentMessageId, 'assistant', {
          artifactMessageId: normalizedArtifactMessageId,
          conversationId: normalizedConversationId,
        });
      }
    } catch (error) {
      console.error('Error exporting generated Markdown artifact to PowerPoint:', error);
      showToast('Failed to export the generated Markdown artifact to PowerPoint.', 'danger');
    } finally {
      if (exportButton) {
        exportButton.disabled = false;
        exportButton.textContent = originalButtonText;
      }
    }
  }

  function updateBackgroundGeneratedOutputStatusCard(statusElements, outputMetadata) {
    const statusLabel = formatGeneratedOutputStatusLabel(outputMetadata?.status, outputMetadata);
    const completedBatches = Number.parseInt(outputMetadata?.completed_batches, 10);
    const batchCount = Number.parseInt(outputMetadata?.batch_count, 10);
    const processedRows = Number.parseInt(outputMetadata?.processed_rows, 10);
    const rowCount = Number.parseInt(outputMetadata?.row_count, 10);
    const transientFailureCount = Number.parseInt(outputMetadata?.transient_failure_count, 10);
    const manualResumeCount = Number.parseInt(outputMetadata?.manual_resume_count, 10);
    const retryDelaySeconds = Number.parseInt(outputMetadata?.retry_delay_seconds, 10);
    const estimatedRemainingSeconds = Number.parseInt(outputMetadata?.estimated_remaining_seconds, 10);
    const progressPercent = calculateGeneratedOutputProgress(outputMetadata);
    const progressPercentLabel = `${Math.round(progressPercent)}%`;

    if (statusElements.statusBadge) {
      statusElements.statusBadge.textContent = statusLabel;
      statusElements.statusBadge.className = getGeneratedOutputStatusBadgeClass(outputMetadata);
    }

    if (statusElements.progressBar) {
      statusElements.progressBar.style.width = progressPercentLabel;
      statusElements.progressBar.setAttribute('aria-valuenow', String(Math.round(progressPercent)));
      statusElements.progressBar.textContent = progressPercentLabel;
    }

    const detailParts = [];
    const statusDetail = String(outputMetadata?.status_detail || outputMetadata?.last_message || '').trim();
    if (statusDetail) {
      detailParts.push(statusDetail);
    }

    const checkpointSummary = String(outputMetadata?.checkpoint_summary || '').trim();
    if (checkpointSummary) {
      detailParts.push(checkpointSummary);
    } else if (Number.isFinite(completedBatches) && Number.isFinite(batchCount) && batchCount > 0) {
      const checkpointParts = [`${completedBatches.toLocaleString()} of ${batchCount.toLocaleString()} batches`];
      if (Number.isFinite(processedRows) && Number.isFinite(rowCount) && rowCount > 0) {
        checkpointParts.push(`${processedRows.toLocaleString()} of ${rowCount.toLocaleString()} rows`);
      }
      detailParts.push(checkpointParts.join(', '));
    }

    if (outputMetadata?.waiting_for_retry) {
      const nextAttempt = formatGeneratedOutputTimestamp(outputMetadata?.next_attempt_at);
      const retryDelay = formatGeneratedOutputDuration(retryDelaySeconds);
      if (nextAttempt && retryDelay) {
        detailParts.push(`Next retry: ${nextAttempt} (${retryDelay})`);
      } else if (nextAttempt) {
        detailParts.push(`Next retry: ${nextAttempt}`);
      }
    } else if (Number.isFinite(estimatedRemainingSeconds) && estimatedRemainingSeconds > 0) {
      const remainingDuration = formatGeneratedOutputDuration(estimatedRemainingSeconds);
      if (remainingDuration) {
        detailParts.push(`Estimated remaining: ${remainingDuration}`);
      }
    }

    if (Number.isFinite(transientFailureCount) && transientFailureCount > 0) {
      detailParts.push(`Transient retries: ${transientFailureCount.toLocaleString()}`);
    }
    if (Number.isFinite(manualResumeCount) && manualResumeCount > 0) {
      detailParts.push(`Manual continues: ${manualResumeCount.toLocaleString()}`);
    }

    if (statusElements.detailText) {
      statusElements.detailText.textContent = detailParts.length
        ? detailParts.join(' | ')
        : 'Waiting for the background worker to start.';
    }

    if (statusElements.updatedText) {
      const updatedAt = String(outputMetadata?.updated_at || outputMetadata?.created_at || '').trim();
      const heartbeatAt = String(outputMetadata?.last_heartbeat_at || '').trim();
      const updatedParts = [];
      const formattedUpdatedAt = formatGeneratedOutputTimestamp(updatedAt);
      const formattedHeartbeatAt = formatGeneratedOutputTimestamp(heartbeatAt);
      if (formattedUpdatedAt) {
        updatedParts.push(`Last update: ${formattedUpdatedAt}`);
      }
      if (formattedHeartbeatAt && formattedHeartbeatAt !== formattedUpdatedAt) {
        updatedParts.push(`Heartbeat: ${formattedHeartbeatAt}`);
      }
      statusElements.updatedText.textContent = updatedParts.join(' | ');
    }
  }

  function createBackgroundGeneratedOutputStatusBlock(outputMetadata) {
    const wrapper = document.createElement('div');
    wrapper.className = 'generated-tabular-background-status mt-3';

    const statusRow = document.createElement('div');
    statusRow.className = 'd-flex flex-wrap align-items-center gap-2 mb-2 small';

    const statusLabel = document.createElement('span');
    statusLabel.className = 'fw-semibold';
    statusLabel.textContent = 'Background export';
    statusRow.appendChild(statusLabel);

    const statusBadge = document.createElement('span');
    statusBadge.className = 'badge text-bg-info';
    statusRow.appendChild(statusBadge);
    wrapper.appendChild(statusRow);

    const progress = document.createElement('div');
    progress.className = 'progress';
    progress.setAttribute('role', 'progressbar');
    progress.setAttribute('aria-valuemin', '0');
    progress.setAttribute('aria-valuemax', '100');

    const progressBar = document.createElement('div');
    progressBar.className = 'progress-bar progress-bar-striped progress-bar-animated';
    progress.appendChild(progressBar);
    wrapper.appendChild(progress);

    const detailText = document.createElement('div');
    detailText.className = 'small text-muted mt-2';
    wrapper.appendChild(detailText);

    const updatedText = document.createElement('div');
    updatedText.className = 'small text-muted';
    wrapper.appendChild(updatedText);

    const statusElements = {
      statusBadge,
      progressBar,
      detailText,
      updatedText,
    };
    updateBackgroundGeneratedOutputStatusCard(statusElements, outputMetadata);

    return {
      wrapper,
      statusElements,
    };
  }

  async function refreshBackgroundGeneratedOutputStatus(outputMetadata, card, statusElements = {}) {
    const runId = String(outputMetadata?.export_run_id || outputMetadata?.run_id || '').trim();
    if (!runId || !(card instanceof HTMLElement) || !document.body.contains(card)) {
      return;
    }

    try {
      const response = await fetch(`/api/tabular/generated-output/runs/${encodeURIComponent(runId)}`, {
        method: 'GET',
        headers: {
          'Accept': 'application/json',
        },
      });
      const responseData = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(responseData?.error || `Server responded with status ${response.status}`);
      }

      const runStatus = responseData?.run || {};
      const generatedArtifact = runStatus?.generated_artifact || null;
      Object.assign(outputMetadata, runStatus, {
        export_run_id: runStatus.run_id || runId,
        run_id: runStatus.run_id || runId,
        background_export: String(runStatus.status || '').toLowerCase() !== 'completed' || !generatedArtifact,
      });

      if (String(runStatus.status || '').toLowerCase() === 'completed' && generatedArtifact) {
        Object.assign(outputMetadata, generatedArtifact, {
          background_export: false,
          status: 'completed',
          export_run_id: runStatus.run_id || runId,
          run_id: runStatus.run_id || runId,
        });
        const refreshedCard = createGeneratedAnalysisArtifactCard(outputMetadata);
        card.replaceWith(refreshedCard);
        return;
      }

      updateBackgroundGeneratedOutputStatusCard(statusElements, outputMetadata);
      updateBackgroundGeneratedOutputContinueButton(statusElements.continueButton, outputMetadata);
    } catch (error) {
      if (statusElements.detailText) {
        statusElements.detailText.textContent = error.message || 'Could not refresh export progress.';
      }
    }
  }

  async function continueBackgroundGeneratedOutputRun(outputMetadata, card, statusElements = {}, continueButton = null) {
    const runId = String(outputMetadata?.export_run_id || outputMetadata?.run_id || '').trim();
    if (!runId || !(card instanceof HTMLElement) || !document.body.contains(card)) {
      return;
    }

    const originalButtonText = continueButton?.textContent || 'Continue';
    if (continueButton) {
      continueButton.dataset.busy = 'true';
      continueButton.disabled = true;
      continueButton.textContent = 'Continuing...';
    }

    try {
      const response = await fetch(`/api/tabular/generated-output/runs/${encodeURIComponent(runId)}/resume`, {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
        },
      });
      const responseData = await response.json().catch(() => ({}));
      if (!response.ok) {
        delete continueButton.dataset.busy;
        throw new Error(responseData?.message || responseData?.error || `Server responded with status ${response.status}`);
      }

      const runStatus = responseData?.run || {};
      const generatedArtifact = runStatus?.generated_artifact || null;
      Object.assign(outputMetadata, runStatus, {
        export_run_id: runStatus.run_id || runId,
        run_id: runStatus.run_id || runId,
        background_export: String(runStatus.status || '').toLowerCase() !== 'completed' || !generatedArtifact,
      });

      if (String(runStatus.status || '').toLowerCase() === 'completed' && generatedArtifact) {
        Object.assign(outputMetadata, generatedArtifact, {
          background_export: false,
          status: 'completed',
          export_run_id: runStatus.run_id || runId,
          run_id: runStatus.run_id || runId,
        });
        const refreshedCard = createGeneratedAnalysisArtifactCard(outputMetadata);
        card.replaceWith(refreshedCard);
        showToast(responseData?.message || 'Background export is already complete.', 'success');
        return;
      }

      updateBackgroundGeneratedOutputStatusCard(statusElements, outputMetadata);
      updateBackgroundGeneratedOutputContinueButton(continueButton, outputMetadata);
      scheduleBackgroundGeneratedOutputStatusPolling(outputMetadata, card, statusElements);
      showToast(responseData?.message || 'Background export was queued to continue.', 'success');
    } catch (error) {
      if (statusElements.detailText) {
        statusElements.detailText.textContent = error.message || 'Could not continue background export.';
      }
      showToast(error.message || 'Could not continue background export.', 'danger');
    } finally {
      if (continueButton) {
        continueButton.textContent = originalButtonText;
        updateBackgroundGeneratedOutputContinueButton(continueButton, outputMetadata);
      }
    }
  }

  function shouldPollBackgroundGeneratedOutput(outputMetadata) {
    if (!outputMetadata?.background_export) {
      return false;
    }

    const status = String(outputMetadata?.status || '').trim().toLowerCase();
    if (status === 'completed' || status === 'canceled') {
      return false;
    }
    if (status === 'failed' && !outputMetadata?.retryable_failure) {
      return false;
    }
    return true;
  }

  function scheduleBackgroundGeneratedOutputStatusPolling(outputMetadata, card, statusElements = {}) {
    if (!(card instanceof HTMLElement) || card.dataset.backgroundExportPolling === 'true') {
      return;
    }

    if (!shouldPollBackgroundGeneratedOutput(outputMetadata)) {
      return;
    }

    card.dataset.backgroundExportPolling = 'true';
    const pollOnce = async () => {
      card.dataset.backgroundExportPolling = 'false';
      await refreshBackgroundGeneratedOutputStatus(outputMetadata, card, statusElements);
      if (
        document.body.contains(card)
        && shouldPollBackgroundGeneratedOutput(outputMetadata)
      ) {
        setTimeout(() => scheduleBackgroundGeneratedOutputStatusPolling(outputMetadata, card, statusElements), 10000);
      }
    };
    setTimeout(pollOnce, 2000);
  }

  function createGeneratedAnalysisArtifactCard(outputMetadata) {
    const card = document.createElement('section');
    card.className = 'generated-tabular-output-card border rounded p-3 mt-3';

    const outputFormat = String(outputMetadata?.output_format || 'json').trim().toLowerCase() || 'json';
    const fileName = String(outputMetadata?.file_name || `generated-output.${outputFormat}`).trim() || `generated-output.${outputFormat}`;
    const rowCountLabel = formatGeneratedTabularRowCount(outputMetadata?.row_count);
    const sourceFileName = String(outputMetadata?.source_file_name || '').trim();
    const selectedSheet = String(outputMetadata?.selected_sheet || '').trim();
    const summary = String(outputMetadata?.summary || '').trim();
    const previewRows = Array.isArray(outputMetadata?.preview_rows) ? outputMetadata.preview_rows : [];
    const previewItems = Array.isArray(outputMetadata?.preview_items) ? outputMetadata.preview_items : [];
    const previewLines = Array.isArray(outputMetadata?.preview_lines) ? outputMetadata.preview_lines : [];
    const previewText = String(
      outputMetadata?.preview_text || outputMetadata?.analysis_text || outputMetadata?.panalysis_text || ''
    ).trim();

    const header = document.createElement('div');
    header.className = 'd-flex flex-wrap justify-content-between align-items-start gap-2';

    const headerText = document.createElement('div');
    const title = document.createElement('h6');
    title.className = 'mb-1';
    title.textContent = getGeneratedAnalysisArtifactTitle(outputMetadata, outputFormat);
    headerText.appendChild(title);

    const fileNameText = document.createElement('div');
    fileNameText.className = 'small text-muted text-break';
    fileNameText.textContent = fileName;
    headerText.appendChild(fileNameText);
    header.appendChild(headerText);

    if (rowCountLabel) {
      const rowCountBadge = document.createElement('span');
      rowCountBadge.className = 'badge text-bg-light';
      rowCountBadge.textContent = `${rowCountLabel} rows`;
      header.appendChild(rowCountBadge);
    }

    card.appendChild(header);

    const storageNote = document.createElement('div');
    storageNote.className = 'small text-muted mt-2';
    storageNote.textContent = getGeneratedTabularStorageNote(outputMetadata);
    card.appendChild(storageNote);

    if (sourceFileName || selectedSheet) {
      const sourceNote = document.createElement('div');
      sourceNote.className = 'small text-muted';
      const sourceSegments = [];
      if (sourceFileName) {
        sourceSegments.push(`Source: ${sourceFileName}`);
      }
      if (selectedSheet) {
        sourceSegments.push(`Sheet: ${selectedSheet}`);
      }
      sourceNote.textContent = sourceSegments.join(' | ');
      card.appendChild(sourceNote);
    }

    if (summary) {
      const summaryText = document.createElement('p');
      summaryText.className = 'small mb-0 mt-2';
      summaryText.textContent = summary;
      card.appendChild(summaryText);
    }

    let backgroundStatusElements = null;
    if (outputMetadata?.background_export) {
      const backgroundStatusBlock = createBackgroundGeneratedOutputStatusBlock(outputMetadata);
      backgroundStatusElements = backgroundStatusBlock.statusElements;
      card.appendChild(backgroundStatusBlock.wrapper);
    }

    if (previewRows.length || previewItems.length || previewLines.length || previewText) {
      let previewContent = null;
      if (previewRows.length) {
        previewContent = buildGeneratedTabularPreviewTable(previewRows) || buildGeneratedTabularPreviewFallback(previewRows);
      } else if (previewItems.length) {
        if (shouldRenderPreviewItemsAsRows(outputMetadata, outputFormat)) {
          previewContent = buildGeneratedTabularPreviewTable(previewItems) || buildGeneratedTabularPreviewFallback(previewItems);
        } else {
          previewContent = buildGeneratedTabularPreviewFallback(previewItems);
        }
      } else if (previewLines.length) {
        previewContent = buildGeneratedAnalysisPreviewText(previewLines.join('\n'), outputMetadata, outputFormat);
      } else if (previewText) {
        previewContent = buildGeneratedAnalysisPreviewText(previewText, outputMetadata, outputFormat);
      }

      if (previewContent) {
        if (shouldCollapseGeneratedAnalysisPreview(outputMetadata)) {
          const previewDetails = document.createElement('details');
          previewDetails.className = 'generated-analysis-preview-details mt-3';

          const previewSummary = document.createElement('summary');
          previewSummary.className = 'small fw-semibold';
          previewSummary.textContent = 'Show preview';
          previewDetails.appendChild(previewSummary);
          previewDetails.appendChild(previewContent);
          card.appendChild(previewDetails);
        } else {
          const previewLabel = document.createElement('div');
          previewLabel.className = 'small fw-semibold mt-3 mb-2';
          previewLabel.textContent = 'Preview';
          card.appendChild(previewLabel);
          card.appendChild(previewContent);
        }
      }
    }

    const actions = document.createElement('div');
    actions.className = 'd-flex flex-wrap gap-2 mt-3';

    if (outputMetadata?.background_export) {
      const continueButton = document.createElement('button');
      continueButton.type = 'button';
      continueButton.className = 'btn btn-sm btn-outline-primary generated-tabular-continue-btn d-none';
      continueButton.textContent = 'Continue';
      continueButton.addEventListener('click', async () => {
        await continueBackgroundGeneratedOutputRun(outputMetadata, card, backgroundStatusElements || {}, continueButton);
      });
      if (backgroundStatusElements) {
        backgroundStatusElements.continueButton = continueButton;
      }
      updateBackgroundGeneratedOutputContinueButton(continueButton, outputMetadata);
      actions.appendChild(continueButton);

      const refreshStatusButton = document.createElement('button');
      refreshStatusButton.type = 'button';
      refreshStatusButton.className = 'btn btn-sm btn-outline-secondary generated-tabular-refresh-status-btn';
      refreshStatusButton.textContent = 'Refresh Status';
      refreshStatusButton.addEventListener('click', async () => {
        refreshStatusButton.disabled = true;
        refreshStatusButton.textContent = 'Refreshing...';
        await refreshBackgroundGeneratedOutputStatus(outputMetadata, card, backgroundStatusElements || {});
        refreshStatusButton.disabled = false;
        refreshStatusButton.textContent = 'Refresh Status';
      });
      actions.appendChild(refreshStatusButton);
      card.appendChild(actions);
      scheduleBackgroundGeneratedOutputStatusPolling(outputMetadata, card, backgroundStatusElements || {});
      return card;
    }

    const downloadButton = document.createElement('button');
    downloadButton.type = 'button';
    downloadButton.className = 'btn btn-sm btn-outline-primary generated-tabular-download-btn';
    downloadButton.textContent = `Download ${outputFormat.toUpperCase()}`;
    downloadButton.addEventListener('click', () => {
      triggerGeneratedTabularOutputDownload(outputMetadata);
    });
    actions.appendChild(downloadButton);

    if (isGeneratedMarkdownArtifact(outputMetadata, outputFormat)) {
      const normalizedArtifactMessageId = String(outputMetadata?.artifact_message_id || '').trim();
      const normalizedConversationId = String(outputMetadata?.conversation_id || window.currentConversationId || '').trim();
      if (normalizedArtifactMessageId && normalizedConversationId) {
        const exportPowerPointButton = document.createElement('button');
        exportPowerPointButton.type = 'button';
        exportPowerPointButton.className = 'btn btn-sm btn-outline-primary generated-artifact-export-ppt-btn';
        exportPowerPointButton.textContent = 'Create PowerPoint';
        exportPowerPointButton.dataset.artifactMessageId = normalizedArtifactMessageId;
        exportPowerPointButton.dataset.conversationId = normalizedConversationId;
        exportPowerPointButton.addEventListener('click', () => {
          exportGeneratedMarkdownArtifactAsPowerPoint(outputMetadata, exportPowerPointButton);
        });
        actions.appendChild(exportPowerPointButton);
      }

      const viewButton = document.createElement('button');
      viewButton.type = 'button';
      viewButton.className = 'btn btn-sm btn-outline-secondary generated-artifact-view-md-btn';
      viewButton.textContent = 'View MD';
      viewButton.addEventListener('click', () => {
        viewGeneratedMarkdownArtifact(outputMetadata, viewButton);
      });
      actions.appendChild(viewButton);
    }

    const normalizedArtifactMessageId = String(outputMetadata?.artifact_message_id || '').trim();
    const normalizedConversationId = String(outputMetadata?.conversation_id || window.currentConversationId || '').trim();
    if (normalizedArtifactMessageId && normalizedConversationId) {
      const promoteButton = document.createElement('button');
      promoteButton.type = 'button';
      promoteButton.className = 'btn btn-sm btn-outline-secondary generated-artifact-promote-btn';
      promoteButton.textContent = 'Add to Workspace';
      promoteButton.addEventListener('click', () => {
        promoteGeneratedArtifactToWorkspace(outputMetadata, promoteButton);
      });
      actions.appendChild(promoteButton);
    }

    card.appendChild(actions);

    return card;
  }

  function createGeneratedTabularOutputCard(outputMetadata) {
    return createGeneratedAnalysisArtifactCard(outputMetadata);
  }

  function hydrateGeneratedAnalysisArtifacts(messageDiv, fullMessageObject = null) {
    const generatedOutputsContainer = messageDiv.querySelector('.generated-tabular-outputs-container');
    if (!(generatedOutputsContainer instanceof HTMLElement)) {
      return;
    }

    generatedOutputsContainer.replaceChildren();
    const generatedOutputs = getGeneratedAnalysisArtifacts(fullMessageObject);
    if (!generatedOutputs.length) {
      generatedOutputsContainer.classList.add('d-none');
      return;
    }

    generatedOutputs.forEach(outputMetadata => {
      generatedOutputsContainer.appendChild(createGeneratedAnalysisArtifactCard(outputMetadata));
    });
    generatedOutputsContainer.classList.remove('d-none');
  }

  function hydrateGeneratedTabularOutputs(messageDiv, fullMessageObject = null) {
    const generatedOutputsContainer = messageDiv.querySelector('.generated-tabular-outputs-container');
    if (!(generatedOutputsContainer instanceof HTMLElement)) {
      return;
    }

    generatedOutputsContainer.replaceChildren();
    const generatedOutputs = getGeneratedTabularOutputs(fullMessageObject);
    if (!generatedOutputs.length) {
      generatedOutputsContainer.classList.add('d-none');
      return;
    }

    generatedOutputs.forEach(outputMetadata => {
      generatedOutputsContainer.appendChild(createGeneratedTabularOutputCard(outputMetadata));
    });
    generatedOutputsContainer.classList.remove('d-none');
  }

  function renderInlineExportButtonContent(button, labelText, iconHtml) {
    button.innerHTML = `${iconHtml || ''}${labelText}`;
  }

  function setInlineExportButtonPendingState(button, isPending, actionName) {
    if (!(button instanceof HTMLElement) || !button.dataset.pendingLabel) {
      return;
    }

    const actionConfig = INLINE_ASSISTANT_EXPORT_ACTIONS_BY_NAME[actionName] || {};
    const defaultLabel = button.dataset.defaultLabel || actionConfig.label || button.textContent.trim();
    const pendingLabel = button.dataset.pendingLabel || actionConfig.pendingLabel || defaultLabel;
    const iconClass = button.dataset.iconClass || actionConfig.iconClass || '';
    const defaultTitle = button.dataset.defaultTitle || actionConfig.title || '';

    button.disabled = isPending;
    button.setAttribute('aria-busy', isPending ? 'true' : 'false');
    button.title = isPending ? pendingLabel : defaultTitle;

    if (isPending) {
      renderInlineExportButtonContent(
        button,
        pendingLabel,
        '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>'
      );
      return;
    }

    const iconHtml = iconClass ? `<i class="${iconClass} me-1"></i>` : '';
    renderInlineExportButtonContent(button, defaultLabel, iconHtml);
  }

  function waitForUiPaint() {
    return new Promise(resolve => {
      requestAnimationFrame(() => resolve());
    });
  }

  async function triggerMessageExportAction(messageDiv, role, actionName, actionButton = null) {
    const currentMessageId = messageDiv.getAttribute('data-message-id');
    const shouldShowPendingState = actionButton instanceof HTMLElement && actionButton.dataset.pendingLabel;

    try {
      if (shouldShowPendingState) {
        setInlineExportButtonPendingState(actionButton, true, actionName);
        await waitForUiPaint();
      }

      const module = await import('./chat-message-export.js');
      const actionHandler = module[actionName];
      if (typeof actionHandler === 'function') {
        await Promise.resolve(actionHandler(messageDiv, currentMessageId, role));
      }
    } catch (err) {
      console.error('Error loading message export module:', err);
    } finally {
      if (shouldShowPendingState) {
        setInlineExportButtonPendingState(actionButton, false, actionName);
      }
    }
  }

  function attachMessageExportActionListeners(messageDiv, role) {
    const actionMappings = [
      {
        selectors: ['.dropdown-export-md-btn', '.inline-export-md-btn'],
        actionName: 'exportMessageAsMarkdown',
      },
      {
        selectors: ['.dropdown-export-word-btn', '.inline-export-word-btn'],
        actionName: 'exportMessageAsWord',
      },
      {
        selectors: ['.dropdown-export-ppt-btn', '.inline-export-ppt-btn'],
        actionName: 'exportMessageAsPowerPoint',
      },
      {
        selectors: ['.dropdown-copy-prompt-btn'],
        actionName: 'copyAsPrompt',
      },
      {
        selectors: ['.dropdown-open-email-btn', '.inline-open-email-btn'],
        actionName: 'openInEmail',
      },
    ];

    actionMappings.forEach(({ selectors, actionName }) => {
      selectors.forEach(selector => {
        messageDiv.querySelectorAll(selector).forEach(button => {
          button.addEventListener('click', (event) => {
            event.preventDefault();
            void triggerMessageExportAction(messageDiv, role, actionName, button);
          });
        });
      });
    });
  }

export function appendMessage(
  sender,
  messageContent,
  modelName = null,
  messageId = null,
  augmented = false,
  hybridCitations = [],
  webCitations = [],
  agentCitations = [],
  agentDisplayName = null,
  agentName = null,
  fullMessageObject = null,
  isNewMessage = false
) {
  if (!chatbox || sender === "System") return;

  const messageDiv = document.createElement("div");
  messageDiv.classList.add("mb-2", "message");
  messageDiv.setAttribute("data-message-id", messageId || `msg-${Date.now()}`);
  messageDiv.dataset.conversationId = resolveMessageConversationId(fullMessageObject);

  let avatarImg = "";
  let avatarAltText = "";
  let avatarHtml = "";
  let messageClass = ""; // <<< ENSURE THIS IS DECLARED HERE
  let senderLabel = "";
  let messageContentHtml = "";
  // let postContentHtml = ""; // Not needed for the general structure anymore

  // --- Handle AI message separately ---
  if (sender === "AI") {
    console.log(`--- appendMessage called for AI ---`);
    console.log(`Message ID: ${messageId}`);
    console.log(`Received augmented: ${augmented} (Type: ${typeof augmented})`);
    console.log(
      `Received hybridCitations:`,
      hybridCitations,
      `(Length: ${hybridCitations?.length})`
    );
    console.log(
      `Received webCitations:`,
      webCitations,
      `(Length: ${webCitations?.length})`
    );
    console.log(
      `Received agentCitations:`,
      agentCitations,
      `(Length: ${agentCitations?.length})`
    );

    messageClass = "ai-message";
    avatarAltText = "AI Avatar";
    avatarImg = "/static/images/ai-avatar.png";

    // Use agent display name if available, otherwise show AI with model
    if (agentDisplayName) {
      senderLabel = escapeHtml(agentDisplayName);
    } else if (modelName) {
      senderLabel = `AI <span style="color: #6c757d; font-size: 0.8em;">(${modelName})</span>`;
    } else {
      senderLabel = "AI";
    }
    avatarHtml = createAssistantAvatarHtml(fullMessageObject, senderLabel, avatarImg);

    const messageConversationId = resolveMessageConversationId(fullMessageObject);
    const renderCompletedAssistantActions = shouldRenderCompletedAssistantActions(
      messageId,
      fullMessageObject
    );

    const renderedAiContent = renderAiMessageContent(messageContent);
    const htmlContent = renderedAiContent.htmlContent;
    const inlineAssistantExportActionsHtml = renderCompletedAssistantActions
      ? buildInlineAssistantExportActionsHtml(messageId)
      : '';

    const mainMessageHtml = `<div class="message-text">${htmlContent}</div>`; // Renamed for clarity

    // --- Footer Content (Copy, Feedback, Citations) ---
    const feedbackHtml = renderFeedbackIcons(messageId, currentConversationId);
    const hiddenTextId = `copy-md-${messageId || Date.now()}`;

    const maskState = getMaskStateFromMetadata(fullMessageObject?.metadata);

    // TTS button (only for AI messages)
    const ttsButtonHtml = (sender === 'AI' && typeof window.appSettings !== 'undefined' && window.appSettings.enable_text_to_speech) ? `
            <button class="btn btn-sm btn-link text-muted tts-play-btn"
                    title="Read this to me"
                    data-message-id="${messageId}"
                    onclick="if(window.chatTTS) window.chatTTS.handleButtonClick('${messageId}')">
                <i class="bi bi-volume-up"></i>
            </button>
        ` : '';

    const copyButtonHtml = `
            <button class="copy-btn btn btn-sm btn-link text-muted" data-hidden-text-id="${hiddenTextId}" title="Copy AI response as Markdown">
                <i class="bi bi-copy"></i>
            </button>
            <textarea id="${hiddenTextId}" style="display:none;">${escapeHtml(
          renderedAiContent.copyMarkdown
    )}</textarea>
        `;

    const maskButtonHtml = buildMaskControlsHtml(messageId, maskState);
    const exportMenuItemsHtml = renderCompletedAssistantActions ? `
            <li><hr class="dropdown-divider"></li>
            <li><a class="dropdown-item dropdown-export-md-btn" href="#" data-message-id="${messageId}"><i class="bi bi-markdown me-2"></i>Export to Markdown</a></li>
            <li><a class="dropdown-item dropdown-export-word-btn" href="#" data-message-id="${messageId}"><i class="bi bi-file-earmark-word me-2"></i>Export to Word</a></li>
            <li><a class="dropdown-item dropdown-export-ppt-btn" href="#" data-message-id="${messageId}"><i class="bi bi-file-earmark-slides me-2"></i>Export to PowerPoint</a></li>
            <li><a class="dropdown-item dropdown-copy-prompt-btn" href="#" data-message-id="${messageId}"><i class="bi bi-clipboard-plus me-2"></i>Use as Prompt</a></li>
            <li><a class="dropdown-item dropdown-open-email-btn" href="#" data-message-id="${messageId}"><i class="bi bi-envelope me-2"></i>Open in Email</a></li>` : '';
    const actionsDropdownHtml = `
            <div class="dropdown">
                <button class="btn btn-sm btn-link text-muted" type="button" data-bs-toggle="dropdown" data-bs-boundary="viewport" data-bs-reference="parent" aria-expanded="false" title="More actions">
                    <i class="bi bi-three-dots"></i>
                </button>
                <ul class="dropdown-menu dropdown-menu-start">
                    <li><a class="dropdown-item dropdown-delete-btn" href="#" data-message-id="${messageId}"><i class="bi bi-trash me-2"></i>Delete</a></li>
                    <li><a class="dropdown-item dropdown-retry-btn" href="#" data-message-id="${messageId}"><i class="bi bi-arrow-clockwise me-2"></i>Retry</a></li>
                    ${feedbackHtml}
            ${exportMenuItemsHtml}
                </ul>
            </div>
        `;
    const carouselButtonsHtml = `
            <button class="carousel-prev-btn btn btn-sm btn-link text-muted" data-message-id="${messageId}" title="Previous attempt" style="display: none;">
                <i class="bi bi-box-arrow-in-left"></i>
            </button>
            <button class="carousel-next-btn btn btn-sm btn-link text-muted" data-message-id="${messageId}" title="Next attempt" style="display: none;">
                <i class="bi bi-box-arrow-in-right"></i>
            </button>
        `;
    const copyAndFeedbackHtml = `<div class="message-actions d-flex align-items-center gap-2">${actionsDropdownHtml}${ttsButtonHtml}${copyButtonHtml}${maskButtonHtml}${carouselButtonsHtml}</div>`;

    const citationsButtonsHtml = createCitationsHtml(
      hybridCitations,
      webCitations,
      agentCitations,
      messageId,
      messageConversationId
    );
    console.log(
      `Generated citationsButtonsHtml (length ${
        citationsButtonsHtml.length
      }): ${citationsButtonsHtml.substring(0, 100)}...`
    );
    let citationToggleHtml = "";
    let citationContentContainerHtml = "";

    console.log("--- Checking Citation Conditions ---");
    console.log("Message ID:", messageId);
    console.log("augmented:", augmented, "Type:", typeof augmented);
    console.log(
      "hybridCitations:",
      hybridCitations,
      "Type:",
      typeof hybridCitations,
      "Length:",
      hybridCitations?.length
    );
    console.log(
      "webCitations:",
      webCitations,
      "Type:",
      typeof webCitations,
      "Length:",
      webCitations?.length
    );
    console.log(
      "agentCitations:",
      agentCitations,
      "Type:",
      typeof agentCitations,
      "Length:",
      agentCitations?.length
    );
    const hybridCheck = hybridCitations && hybridCitations.length > 0;
    const webCheck = webCitations && webCitations.length > 0;
    const agentCheck = agentCitations && agentCitations.length > 0;
    console.log("Hybrid Check Result:", hybridCheck);
    console.log("Web Check Result:", webCheck);
    console.log("Agent Check Result:", agentCheck);
    const hasAnyCitations = hybridCheck || webCheck || agentCheck;
    const overallCondition = hasAnyCitations;
    console.log("Overall Condition Result:", overallCondition);
    const shouldShowCitations = Boolean(citationsButtonsHtml) && hasAnyCitations;
    console.log(
      `Condition check (Boolean(citationsButtonsHtml) && hasAnyCitations): ${shouldShowCitations}`
    );

    if (shouldShowCitations) {
      console.log(">>> Will generate and include citation elements.");
      const citationsContainerId = `citations-${messageId || Date.now()}`;
      citationToggleHtml = `<button class="btn btn-sm btn-link text-muted citation-toggle-btn" title="Show sources" aria-expanded="false" aria-controls="${citationsContainerId}"><i class="bi bi-journal-text"></i></button>`;
      // citationsButtonsHtml already contains a <div class="citations-container"> wrapper
      // Just add ID and display style by wrapping minimally
      citationContentContainerHtml = `<div id="${citationsContainerId}" style="display: none;">${citationsButtonsHtml}</div>`;
    } else {
      console.log(">>> Will NOT generate citation elements.");
    }

    const metadataContainerId = `metadata-${messageId || Date.now()}`;
    const metadataContainerHtml = `<div class="metadata-container mt-2 pt-2 border-top" id="${metadataContainerId}" style="display: none;"><div class="text-muted">Loading metadata...</div></div>`;

    const thoughtsHtml = createThoughtsToggleHtml(messageId);

    const footerContentHtml = `<div class="message-footer d-flex justify-content-between align-items-center mt-2">
      <div class="d-flex align-items-center">${copyAndFeedbackHtml}</div>
      <div class="d-flex align-items-center"></div>
      <div class="d-flex align-items-center gap-2">${thoughtsHtml.toggleHtml}${citationToggleHtml}<button class="btn btn-sm btn-link text-muted metadata-info-btn" data-message-id="${messageId}" title="Show metadata" aria-expanded="false" aria-controls="${metadataContainerId}">
        <i class="bi bi-info-circle"></i>
      </button></div>
    </div>`;

    // Build AI message inner HTML
    messageDiv.innerHTML = `
            <div class="message-content">
          ${avatarHtml}
                <div class="message-bubble">
                    <div class="message-sender">${senderLabel}</div>
                    ${mainMessageHtml}
                  ${inlineAssistantExportActionsHtml}
                      <div class="generated-tabular-outputs-container d-none"></div>
            <div class="inline-visualizations-container d-none"></div>
                    ${citationContentContainerHtml}
                    ${thoughtsHtml.containerHtml}
                    ${metadataContainerHtml}
                    ${footerContentHtml}
                </div>
            </div>`;

              messageDiv.dataset.replySenderName = stripHtmlTags(senderLabel).replace(/\s+/g, " ").trim() || "AI";
              messageDiv.dataset.replyPreviewText = buildPlainTextPreview(renderedAiContent.previewMarkdown);

    messageDiv.classList.add(messageClass); // Add AI message class
    if (!renderCompletedAssistantActions) {
      messageDiv.dataset.messageComplete = 'false';
    }
    chatbox.appendChild(messageDiv); // Append AI message
    renderSuggestedFollowUpButtons(messageDiv, renderedAiContent.followUpSuggestions);
    hydrateGeneratedAnalysisArtifacts(messageDiv, fullMessageObject);
    attachGeneratedImageProposalResults(messageDiv, fullMessageObject?.generated_image_proposals || []);

    // Auto-play TTS if enabled (only for new messages, not when loading history)
    if (isNewMessage && typeof autoplayTTSIfEnabled === 'function') {
      autoplayTTSIfEnabled(messageId, renderedAiContent.previewMarkdown || messageContent);
    }

    void (async () => {
      await renderInlineVideoGalleries(
        messageDiv,
        hybridCitations || [],
        webCitations || [],
        agentCitations || [],
        messageConversationId
      );
      await renderInlineImageGalleries(
        messageDiv,
        hybridCitations || [],
        webCitations || [],
        agentCitations || [],
        messageId,
        messageConversationId
      );
      await renderInlineAzureMaps(
        messageDiv,
        agentCitations || [],
        messageId,
        messageConversationId
      );
    })();

    // Highlight code blocks in the messages
    messageDiv.querySelectorAll('pre code[class^="language-"]').forEach((block) => {
      const match = block.className.match(/language-([a-zA-Z0-9]+)/);
      if (match && !block.hasAttribute('data-language')) {
        block.setAttribute('data-language', match[1]);
      }
      if (window.Prism) Prism.highlightElement(block);
    });

    captureMessageMaskingOriginalContent(messageDiv);

    // Apply masked state if message has masking
    if (fullMessageObject?.metadata) {
      applyMaskedState(messageDiv, fullMessageObject.metadata);
    } else {
      hydrateInlineCharts(messageDiv);
      hydrateInlineImageProposals(messageDiv);
    }

    // --- Attach Event Listeners specifically for AI message ---
    attachCodeBlockCopyButtons(messageDiv.querySelector(".message-text"));

    const metadataBtn = messageDiv.querySelector(".metadata-info-btn");
    if (metadataBtn) {
      metadataBtn.addEventListener("click", () => {
        const metadataContainer = messageDiv.querySelector('.metadata-container');
        if (metadataContainer) {
          const isVisible = metadataContainer.style.display !== 'none';
          metadataContainer.style.display = isVisible ? 'none' : 'block';
          metadataBtn.setAttribute('aria-expanded', !isVisible);
          metadataBtn.title = isVisible ? 'Show metadata' : 'Hide metadata';

          // Toggle icon
          const icon = metadataBtn.querySelector('i');
          if (icon) {
            icon.className = isVisible ? 'bi bi-info-circle' : 'bi bi-chevron-up';
          }

          // Load metadata if container is empty (first open)
          if (!isVisible && metadataContainer.innerHTML.includes('Loading metadata')) {
            loadMessageMetadataForDisplay(messageId, metadataContainer);
          }
        }
      });
    }

    attachMessageExportActionListeners(messageDiv, 'assistant');
    attachThoughtsToggleListener(messageDiv, messageId, currentConversationId);

    attachMaskButtonEventListeners(messageDiv);

    const dropdownDeleteBtn = messageDiv.querySelector(".dropdown-delete-btn");
    if (dropdownDeleteBtn) {
      dropdownDeleteBtn.addEventListener("click", (e) => {
        e.preventDefault();
        // Always read the message ID from the DOM attribute dynamically
        const currentMessageId = messageDiv.getAttribute('data-message-id');
        console.log(`🗑️ AI Delete button clicked - using message ID from DOM: ${currentMessageId}`);
        handleDeleteButtonClick(messageDiv, currentMessageId, 'assistant');
      });
    }

    const dropdownRetryBtn = messageDiv.querySelector(".dropdown-retry-btn");
    if (dropdownRetryBtn) {
      dropdownRetryBtn.addEventListener("click", (e) => {
        e.preventDefault();
        // Always read the message ID from the DOM attribute dynamically
        const currentMessageId = messageDiv.getAttribute('data-message-id');
        console.log(`🔄 AI Retry button clicked - using message ID from DOM: ${currentMessageId}`);
        handleRetryButtonClick(messageDiv, currentMessageId, 'assistant');
      });
    }

    // Handle dropdown positioning manually - move to chatbox container
    const dropdownToggle = messageDiv.querySelector(".message-actions .dropdown button[data-bs-toggle='dropdown']");
    const dropdownMenu = messageDiv.querySelector(".message-actions .dropdown-menu");
    if (dropdownToggle && dropdownMenu) {
      dropdownToggle.addEventListener("show.bs.dropdown", () => {
        // Move dropdown menu to chatbox to escape message bubble
        const chatbox = document.getElementById('chatbox');
        if (chatbox) {
          dropdownMenu.remove();
          chatbox.appendChild(dropdownMenu);

          // Position relative to button
          const rect = dropdownToggle.getBoundingClientRect();
          const chatboxRect = chatbox.getBoundingClientRect();
          dropdownMenu.style.position = 'absolute';
          dropdownMenu.style.top = `${rect.bottom - chatboxRect.top + chatbox.scrollTop + 2}px`;
          dropdownMenu.style.left = `${rect.left - chatboxRect.left}px`;
          dropdownMenu.style.zIndex = '9999';
        }
      });

      // Return menu to original position when closed
      dropdownToggle.addEventListener("hidden.bs.dropdown", () => {
        const dropdown = messageDiv.querySelector(".message-actions .dropdown");
        if (dropdown && dropdownMenu.parentElement !== dropdown) {
          dropdownMenu.remove();
          dropdown.appendChild(dropdownMenu);
        }
      });
    }

    const carouselPrevBtn = messageDiv.querySelector(".carousel-prev-btn");
    if (carouselPrevBtn) {
      carouselPrevBtn.addEventListener("click", () => {
        handleCarouselClick(messageId, 'prev');
      });
    }

    const carouselNextBtn = messageDiv.querySelector(".carousel-next-btn");
    if (carouselNextBtn) {
      carouselNextBtn.addEventListener("click", () => {
        handleCarouselClick(messageId, 'next');
      });
    }

    const copyBtn = messageDiv.querySelector(".copy-btn");
    copyBtn?.addEventListener("click", () => {
      /* ... copy logic ... */
      const hiddenTextarea = document.getElementById(
        copyBtn.dataset.hiddenTextId
      );
      if (!hiddenTextarea) return;
      navigator.clipboard
        .writeText(hiddenTextarea.value)
        .then(() => {
          copyBtn.innerHTML = '<i class="bi bi-check-lg text-success"></i>'; // Use check-lg
          copyBtn.title = "Copied!";
          setTimeout(() => {
            copyBtn.innerHTML = '<i class="bi bi-copy"></i>';
            copyBtn.title = "Copy AI response as Markdown";
          }, 2000);
        })
        .catch((err) => {
          console.error("Error copying text:", err);
          showToast("Failed to copy text.", "warning");
        });
    });
    const toggleBtn = messageDiv.querySelector(".citation-toggle-btn");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", () => {
        /* ... toggle logic ... */
        const targetId = toggleBtn.getAttribute("aria-controls");
        const citationsContainer = messageDiv.querySelector(`#${targetId}`);
        if (!citationsContainer) return;

        // Store current scroll position to maintain user's view
        const currentScrollTop = document.getElementById('chat-messages-container')?.scrollTop || window.pageYOffset;

        const isExpanded = citationsContainer.style.display !== "none";
        citationsContainer.style.display = isExpanded ? "none" : "block";
        toggleBtn.setAttribute("aria-expanded", !isExpanded);
        toggleBtn.title = isExpanded ? "Show sources" : "Hide sources";
        toggleBtn.innerHTML = isExpanded
          ? '<i class="bi bi-journal-text"></i>'
          : '<i class="bi bi-chevron-up"></i>';
        // Note: Removed scrollChatToBottom() to prevent jumping when expanding citations

        // Restore scroll position after DOM changes
        setTimeout(() => {
          if (document.getElementById('chat-messages-container')) {
            document.getElementById('chat-messages-container').scrollTop = currentScrollTop;
          } else {
            window.scrollTo(0, currentScrollTop);
          }
        }, 10);
      });
    }

    scrollChatToBottom();
    return; // <<< EXIT EARLY FOR AI MESSAGES

    // --- Handle ALL OTHER message types ---
  } else {
    // Declare variables for image metadata checks (needed for footer logic)
    let isUserUpload = false;
    let hasExtractedText = false;
    let hasVisionAnalysis = false;

    // Determine variables based on sender type
    if (sender === "You") {
      messageClass = "user-message";
      senderLabel = "You";
      avatarAltText = "User Avatar";

      // Use profile image if available, otherwise use default
      const userProfileImage = window.ProfileImage?.getUserImage();
      if (userProfileImage) {
        avatarImg = userProfileImage;
      } else {
        avatarImg = "/static/images/user-avatar.png";
      }

      const renderedMessageContent = stripMentionTextFromMessageContent(messageContent, fullMessageObject);
      const sanitizedUserHtml = DOMPurify.sanitize(
        marked.parse(escapeHtml(renderedMessageContent))
      );
      messageContentHtml = addTargetBlankToExternalLinks(sanitizedUserHtml);
    } else if (sender === "Collaborator") {
      messageClass = "collaborator-message";
      senderLabel = fullMessageObject?.sender?.display_name
        || fullMessageObject?.metadata?.sender?.display_name
        || "Participant";
      avatarAltText = `${senderLabel} Avatar`;
      avatarHtml = createCollaboratorAvatarHtml(fullMessageObject, senderLabel);
      const renderedMessageContent = stripMentionTextFromMessageContent(messageContent, fullMessageObject);
      const sanitizedCollaboratorHtml = DOMPurify.sanitize(
        marked.parse(escapeHtml(renderedMessageContent))
      );
      messageContentHtml = addTargetBlankToExternalLinks(sanitizedCollaboratorHtml);
    } else if (sender === "File") {
      messageClass = "file-message";
      senderLabel = "File Added";
      avatarImg = ""; // No avatar for file messages
      avatarAltText = "";
      const filename = escapeHtml(messageContent.filename);
      const fileId = escapeHtml(messageContent.id);
      const workspaceAttachment = fullMessageObject?.metadata?.workspace_attachment;
      const workspaceAttachmentHtml = buildChatWorkspaceAttachmentHtml(workspaceAttachment);
      const isWorkspaceBackedFile = String(fullMessageObject?.file_content_source || '').trim().toLowerCase() === 'workspace'
        && String(workspaceAttachment?.document_id || '').trim();
      if (isWorkspaceBackedFile) {
        const workspaceUrl = `/workspace?document_id=${encodeURIComponent(String(workspaceAttachment.document_id).trim())}`;
        messageContentHtml = `<a href="${escapeHtml(workspaceUrl)}" class="workspace-file-link"><i class="bi bi-file-earmark-arrow-up me-1"></i>${filename}</a>${workspaceAttachmentHtml}`;
      } else {
        messageContentHtml = `<a href="#" class="file-link" data-conversation-id="${currentConversationId}" data-file-id="${fileId}"><i class="bi bi-file-earmark-arrow-up me-1"></i>${filename}</a>${workspaceAttachmentHtml}`;
      }
    } else if (sender === "image") {
      // Make sure this matches the case used in loadMessages/actuallySendMessage
      messageClass = "image-message"; // Use a distinct class if needed, or reuse ai-message

      // Use agent display name if available, otherwise show AI with model
      if (agentDisplayName) {
        senderLabel = escapeHtml(agentDisplayName);
      } else if (modelName) {
        senderLabel = `AI <span style="color: #6c757d; font-size: 0.8em;">(${modelName})</span>`;
      } else {
        senderLabel = "Image";
      }

      // Check if this is a user-uploaded image with metadata
      isUserUpload = fullMessageObject?.metadata?.is_user_upload || false;
      hasExtractedText = fullMessageObject?.extracted_text || false;
      hasVisionAnalysis = fullMessageObject?.vision_analysis || false;

      // Use agent display name if available, otherwise show AI with model
      if (isUserUpload) {
        senderLabel = "Uploaded Image";
      } else if (agentDisplayName) {
        senderLabel = escapeHtml(agentDisplayName);
      } else if (modelName) {
        senderLabel = `AI <span style="color: #6c757d; font-size: 0.8em;">(${modelName})</span>`;
      } else {
        senderLabel = "Image";
      }

      avatarImg = isUserUpload ? "/static/images/user-avatar.png" : "/static/images/ai-avatar.png";
      avatarAltText = isUserUpload ? "Uploaded Image" : "Generated Image";

      // Validate image URL before creating img tag
      if (messageContent && messageContent !== 'null' && messageContent.trim() !== '') {
        messageContentHtml = `<img src="${messageContent}" alt="${isUserUpload ? 'Uploaded' : 'Generated'} Image" class="generated-image" style="width: 170px; height: 170px; cursor: pointer;" data-image-src="${messageContent}" onload="scrollChatToBottom()" onerror="this.src='/static/images/image-error.png'; this.alt='Failed to load image';" />`;
      } else {
        messageContentHtml = `<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>Failed to ${isUserUpload ? 'load' : 'generate'} image - invalid response from image service</div>`;
      }
      if (isUserUpload) {
        messageContentHtml += buildChatWorkspaceAttachmentHtml(fullMessageObject?.metadata?.workspace_attachment);
      }
    } else if (sender === "safety") {
      messageClass = "safety-message";
      senderLabel = "Content Safety";
      avatarAltText = "Content Safety Avatar";
      avatarImg = "/static/images/alert.png";
      const linkToViolations = `<br><small><a href="/safety_violations" target="_blank" rel="noopener" style="font-size: 0.85em; color: #6c757d;">View My Safety Violations</a></small>`;
      const sanitizedSafetyHtml = DOMPurify.sanitize(
        marked.parse(messageContent + linkToViolations)
      );
      messageContentHtml = addTargetBlankToExternalLinks(sanitizedSafetyHtml);
    } else if (sender === "Error") {
      messageClass = "error-message";
      senderLabel = "System Error";
      avatarImg = "/static/images/alert.png";
      avatarAltText = "Error Avatar";
      messageContentHtml = `<span class="text-danger">${escapeHtml(
        messageContent
      )}</span>`;
    } else {
      // This block should ideally not be reached if all sender types are handled
      console.warn("Unknown message sender type:", sender); // Keep the warning
      messageClass = "unknown-message"; // Fallback class
      senderLabel = "System";
      avatarImg = "/static/images/ai-avatar.png";
      avatarAltText = "System Avatar";
      messageContentHtml = escapeHtml(messageContent); // Default safe display
    }

    // --- Build the General Message Structure ---
    // This runs for "You", "File", "image", "safety", "Error", and the fallback "unknown"
    messageDiv.classList.add(messageClass); // Add the determined class

    // Create message footer for user, image, and file messages
    let messageFooterHtml = "";
    let metadataContainerHtml = "";
    const replyQuoteHtml = (sender === "You" || sender === "Collaborator")
      ? renderReplyQuoteHtml(fullMessageObject)
      : "";
    const invocationTargetHtml = (sender === "You" || sender === "Collaborator")
      ? renderInvocationTargetHtml(fullMessageObject)
      : "";
    const mentionTagsHtml = (sender === "You" || sender === "Collaborator")
      ? renderMentionTagsHtml(fullMessageObject)
      : "";
    const hasVisibleMessageText = sender === "image"
      || Boolean(stripHtmlTags(messageContentHtml || "").replace(/\s+/g, " ").trim());
    if (sender === "You") {
      const metadataContainerId = `metadata-${messageId || Date.now()}`;
      const maskState = getMaskStateFromMetadata(fullMessageObject?.metadata);

      messageFooterHtml = `
        <div class="message-footer d-flex justify-content-between align-items-center mt-2">
          <div class="d-flex align-items-center gap-2">
            <div class="dropdown">
              <button class="btn btn-sm btn-link text-muted" type="button" data-bs-toggle="dropdown" data-bs-boundary="viewport" data-bs-reference="parent" aria-expanded="false" title="More actions">
                <i class="bi bi-three-dots"></i>
              </button>
              <ul class="dropdown-menu dropdown-menu-start">
                <li><a class="dropdown-item dropdown-edit-btn" href="#" data-message-id="${messageId}"><i class="bi bi-pencil me-2"></i>Edit</a></li>
                <li><a class="dropdown-item dropdown-delete-btn" href="#" data-message-id="${messageId}"><i class="bi bi-trash me-2"></i>Delete</a></li>
                <li><a class="dropdown-item dropdown-retry-btn" href="#" data-message-id="${messageId}"><i class="bi bi-arrow-clockwise me-2"></i>Retry</a></li>
                <li><hr class="dropdown-divider"></li>
                <li><a class="dropdown-item dropdown-export-md-btn" href="#" data-message-id="${messageId}"><i class="bi bi-markdown me-2"></i>Export to Markdown</a></li>
                <li><a class="dropdown-item dropdown-export-word-btn" href="#" data-message-id="${messageId}"><i class="bi bi-file-earmark-word me-2"></i>Export to Word</a></li>
                <li><a class="dropdown-item dropdown-export-ppt-btn" href="#" data-message-id="${messageId}"><i class="bi bi-file-earmark-slides me-2"></i>Export to PowerPoint</a></li>
                <li><a class="dropdown-item dropdown-copy-prompt-btn" href="#" data-message-id="${messageId}"><i class="bi bi-clipboard-plus me-2"></i>Use as Prompt</a></li>
                <li><a class="dropdown-item dropdown-open-email-btn" href="#" data-message-id="${messageId}"><i class="bi bi-envelope me-2"></i>Open in Email</a></li>
              </ul>
            </div>
            <button class="btn btn-sm btn-link text-muted copy-user-btn" data-message-id="${messageId}" title="Copy message">
              <i class="bi bi-copy"></i>
            </button>
            ${buildMaskControlsHtml(messageId, maskState)}
            <button class="carousel-prev-btn btn btn-sm btn-link text-muted" data-message-id="${messageId}" title="Previous attempt" style="display: none;">
              <i class="bi bi-box-arrow-in-left"></i>
            </button>
            <button class="carousel-next-btn btn btn-sm btn-link text-muted" data-message-id="${messageId}" title="Next attempt" style="display: none;">
              <i class="bi bi-box-arrow-in-right"></i>
            </button>
          </div>
          <div class="d-flex align-items-center"></div>
          <div class="d-flex align-items-center">
            <button class="btn btn-sm btn-link text-muted metadata-toggle-btn" data-message-id="${messageId}" title="Show metadata" aria-expanded="false" aria-controls="${metadataContainerId}">
              <i class="bi bi-info-circle"></i>
            </button>
          </div>
        </div>`;
      metadataContainerHtml = `<div class="metadata-container mt-2 pt-2 border-top" id="${metadataContainerId}" style="display: none;"><div class="text-muted">Loading metadata...</div></div>`;
    } else if (sender === "Collaborator") {
      const metadataContainerId = `metadata-${messageId || Date.now()}`;
      messageFooterHtml = `
        <div class="message-footer d-flex justify-content-between align-items-center mt-2">
          <div class="d-flex align-items-center gap-2">
            <div class="dropdown">
              <button class="btn btn-sm btn-link text-muted" type="button" data-bs-toggle="dropdown" data-bs-boundary="viewport" data-bs-reference="parent" aria-expanded="false" title="More actions">
                <i class="bi bi-three-dots"></i>
              </button>
              <ul class="dropdown-menu dropdown-menu-start">
                <li><a class="dropdown-item dropdown-reply-btn" href="#" data-message-id="${messageId}"><i class="bi bi-reply me-2"></i>Reply</a></li>
              </ul>
            </div>
          </div>
          <div class="d-flex align-items-center"></div>
          <div class="d-flex align-items-center">
            <button class="btn btn-sm btn-link text-muted metadata-toggle-btn" data-message-id="${messageId}" title="Show metadata" aria-expanded="false" aria-controls="${metadataContainerId}">
              <i class="bi bi-info-circle"></i>
            </button>
          </div>
        </div>`;
      metadataContainerHtml = `<div class="metadata-container mt-2 pt-2 border-top" id="${metadataContainerId}" style="display: none;"><div class="text-muted">Loading metadata...</div></div>`;
    } else if (sender === "image" || sender === "File") {
      // Image and file messages get mask button on left, metadata button on right side
      const metadataContainerId = `metadata-${messageId || Date.now()}`;

      const maskState = getMaskStateFromMetadata(fullMessageObject?.metadata);

      // For images with extracted text or vision analysis, add View Text button like citation button
      let imageInfoToggleHtml = '';
      let imageInfoContainerHtml = '';
      if (sender === "image" && isUserUpload && (hasExtractedText || hasVisionAnalysis)) {
        const infoContainerId = `image-info-${messageId || Date.now()}`;
        imageInfoToggleHtml = `<button class="btn btn-sm btn-link text-muted image-info-btn" data-message-id="${messageId}" title="View extracted text" aria-expanded="false" aria-controls="${infoContainerId}"><i class="bi bi-file-text"></i></button>`;
        imageInfoContainerHtml = `<div id="${infoContainerId}" class="image-info-container mt-2 pt-2 border-top" style="display: none;"><div class="image-info-content">Loading image information...</div></div>`;
      }

      messageFooterHtml = `
        <div class="message-footer d-flex justify-content-between align-items-center mt-2">
          <div class="d-flex align-items-center gap-2">
            <div class="dropdown">
              <button class="btn btn-sm btn-link text-muted" type="button" data-bs-toggle="dropdown" data-bs-boundary="viewport" data-bs-reference="parent" aria-expanded="false" title="More actions">
                <i class="bi bi-three-dots"></i>
              </button>
              <ul class="dropdown-menu dropdown-menu-start">
                <li><a class="dropdown-item dropdown-delete-btn" href="#" data-message-id="${messageId}"><i class="bi bi-trash me-2"></i>Delete</a></li>
              </ul>
            </div>
            ${buildMaskControlsHtml(messageId, maskState)}
          </div>
          <div class="d-flex align-items-center"></div>
          <div class="d-flex align-items-center gap-2">${imageInfoToggleHtml}<button class="btn btn-sm btn-link text-muted metadata-info-btn" data-message-id="${messageId}" title="Show metadata" aria-expanded="false" aria-controls="${metadataContainerId}">
            <i class="bi bi-info-circle"></i>
          </button></div>
        </div>`;
      metadataContainerHtml = imageInfoContainerHtml + `<div class="metadata-container mt-2 pt-2 border-top" id="${metadataContainerId}" style="display: none;"><div class="text-muted">Loading metadata...</div></div>`;
    }

    // Set innerHTML using the variables determined above
    const safeAvatarImg = sanitizeAvatarImageSrc(avatarImg);
    messageDiv.innerHTML = `
            <div class="message-content ${
              sender === "You" || sender === "File" ? "flex-row-reverse" : ""
            }">
                ${
                  avatarHtml
                    ? avatarHtml
                    : safeAvatarImg
                      ? `<img src="${escapeHtml(safeAvatarImg)}" alt="${escapeHtml(avatarAltText)}" class="avatar">`
                      : ""
                }
                <div class="message-bubble">
                    <div class="message-sender">
                        ${senderLabel}
                        ${fullMessageObject?.metadata?.edited ? '<span class="badge bg-secondary ms-2">Edited</span>' : ''}
                        ${fullMessageObject?.metadata?.retried ? '<span class="badge bg-info ms-2">Retried</span>' : ''}
                    </div>
                    ${replyQuoteHtml}
                    ${invocationTargetHtml}
                    ${mentionTagsHtml}
                    ${hasVisibleMessageText ? `<div class="message-text">${messageContentHtml}</div>` : ""}
                    ${metadataContainerHtml}
                    ${messageFooterHtml}
                </div>
            </div>`;

    messageDiv.dataset.replySenderName = stripHtmlTags(senderLabel).replace(/\s+/g, " ").trim() || "Participant";
    if (typeof messageContent === "string") {
      messageDiv.dataset.replyPreviewText = buildPlainTextPreview(messageContent);
    }

    // Append and scroll (common actions for non-AI)
    chatbox.appendChild(messageDiv);
    hydrateChatWorkspaceAttachmentProgress(messageDiv);

    // Highlight code blocks in the messages
    messageDiv.querySelectorAll('pre code[class^="language-"]').forEach((block) => {
      const match = block.className.match(/language-([a-zA-Z0-9]+)/);
      if (match && !block.hasAttribute('data-language')) {
        block.setAttribute('data-language', match[1]);
      }
      if (window.Prism) Prism.highlightElement(block);
    });

    captureMessageMaskingOriginalContent(messageDiv);


    // Add event listeners for user message buttons
    if (sender === "You") {
      attachUserMessageEventListeners(messageDiv, messageId, messageContent);

      // Apply masked state if message has masking
      if (fullMessageObject?.metadata) {
        console.log('Applying masked state for user message:', messageId, fullMessageObject.metadata);
        applyMaskedState(messageDiv, fullMessageObject.metadata);
      } else {
        console.log('No metadata found for user message:', messageId, 'fullMessageObject:', fullMessageObject);
      }
    }

    if (sender === "Collaborator") {
      attachCollaboratorMessageEventListeners(messageDiv, fullMessageObject, messageContent);
      hydrateCollaboratorAvatar(messageDiv, getMessageSenderUserId(fullMessageObject), senderLabel);
    }

    // Add event listener for image info button (uploaded images)
    if (sender === "image" && fullMessageObject?.metadata?.is_user_upload) {
      const imageInfoBtn = messageDiv.querySelector('.image-info-btn');
      if (imageInfoBtn) {
        imageInfoBtn.addEventListener('click', () => {
          toggleImageInfo(messageDiv, messageId, fullMessageObject);
        });
      }
    }

    // Add event listener for mask button (image and file messages)
    if (sender === "image" || sender === "File") {
      attachMaskButtonEventListeners(messageDiv);

      // Apply masked state if message has masking
      if (fullMessageObject?.metadata) {
        console.log('Applying masked state for image/file message:', messageId, fullMessageObject.metadata);
        applyMaskedState(messageDiv, fullMessageObject.metadata);
      }
    }

    // Add event listener for metadata button (image and file messages)
    if (sender === "image" || sender === "File") {
      const metadataBtn = messageDiv.querySelector('.metadata-info-btn');
      if (metadataBtn) {
        metadataBtn.addEventListener('click', () => {
          const metadataContainer = messageDiv.querySelector('.metadata-container');
          if (metadataContainer) {
            const isVisible = metadataContainer.style.display !== 'none';
            metadataContainer.style.display = isVisible ? 'none' : 'block';
            metadataBtn.setAttribute('aria-expanded', !isVisible);
            metadataBtn.title = isVisible ? 'Show metadata' : 'Hide metadata';

            // Toggle icon
            const icon = metadataBtn.querySelector('i');
            if (icon) {
              icon.className = isVisible ? 'bi bi-info-circle' : 'bi bi-chevron-up';
            }

            // Load metadata if container is empty (first open)
            if (!isVisible && metadataContainer.innerHTML.includes('Loading metadata')) {
              loadMessageMetadataForDisplay(messageId, metadataContainer);
            }
          }
        });
      }

      // Add delete button event listener from dropdown
      const dropdownDeleteBtn = messageDiv.querySelector('.dropdown-delete-btn');
      if (dropdownDeleteBtn) {
        dropdownDeleteBtn.addEventListener('click', (e) => {
          e.preventDefault();
          // Always read the message ID from the DOM attribute dynamically
          const currentMessageId = messageDiv.getAttribute('data-message-id');
          console.log(`🗑️ Image/File Delete button clicked - using message ID from DOM: ${currentMessageId}`);
          handleDeleteButtonClick(messageDiv, currentMessageId, sender === "image" ? 'image' : 'file');
        });
      }

      // Handle dropdown positioning manually for image/file messages - move to chatbox
      const dropdownToggle = messageDiv.querySelector(".message-footer .dropdown button[data-bs-toggle='dropdown']");
      const dropdownMenu = messageDiv.querySelector(".message-footer .dropdown-menu");
      if (dropdownToggle && dropdownMenu) {
        dropdownToggle.addEventListener("show.bs.dropdown", () => {
          const chatbox = document.getElementById('chatbox');
          if (chatbox) {
            dropdownMenu.remove();
            chatbox.appendChild(dropdownMenu);

            const rect = dropdownToggle.getBoundingClientRect();
            const chatboxRect = chatbox.getBoundingClientRect();
            dropdownMenu.style.position = 'absolute';
            dropdownMenu.style.top = `${rect.bottom - chatboxRect.top + chatbox.scrollTop + 2}px`;
            dropdownMenu.style.left = `${rect.left - chatboxRect.left}px`;
            dropdownMenu.style.zIndex = '9999';
          }
        });

        dropdownToggle.addEventListener("hidden.bs.dropdown", () => {
          const dropdown = messageDiv.querySelector(".message-footer .dropdown");
          if (dropdown && dropdownMenu.parentElement !== dropdown) {
            dropdownMenu.remove();
            dropdown.appendChild(dropdownMenu);
          }
        });
      }
    }

    scrollChatToBottom();
  } // End of the large 'else' block for non-AI messages
}

export function sendMessage() {
  if (!userInput) {
    console.error("User input element not found.");
    return;
  }
  let userText = userInput.value.trim();
  let promptText = "";
  let combinedMessage = "";

  if (
    promptSelectionContainer &&
    promptSelectionContainer.style.display !== "none" &&
    promptSelect &&
    promptSelect.selectedIndex > 0
  ) {
    const selectedOpt = promptSelect.options[promptSelect.selectedIndex];
    promptText = selectedOpt?.dataset?.promptContent?.trim() || "";
  }

  if (userText && promptText) {
    combinedMessage = userText + "\n\n" + promptText;
  } else {
    combinedMessage = userText || promptText;
  }
  combinedMessage = combinedMessage.trim();

  if (!combinedMessage) {
    return;
  }

  if (!currentConversationId) {
    createNewConversation(() => {
      actuallySendMessage(combinedMessage);
    }, { preserveSelections: true, initialMessage: combinedMessage });
  } else {
    actuallySendMessage(combinedMessage);
  }

  userInput.value = "";
  userInput.style.height = "";
  if (promptSelect) {
    promptSelect.selectedIndex = 0;
  }
  // Update send button visibility after clearing input
  updateSendButtonVisibility();
  // Keep focus on input
  userInput.focus();
}

function getCurrentModelSelection() {
  let modelDeployment = modelSelect?.value;
  let modelId = null;
  let modelEndpointId = null;
  let modelProvider = null;
  let modelIcon = {};

  if (window.appSettings?.enable_multi_model_endpoints && modelSelect) {
    const selectedOption = modelSelect.options[modelSelect.selectedIndex];
    modelId = selectedOption?.dataset?.modelId || selectedOption?.value || null;
    modelEndpointId = selectedOption?.dataset?.endpointId || null;
    modelProvider = selectedOption?.dataset?.provider || null;
    modelDeployment = selectedOption?.dataset?.deploymentName || null;
    modelIcon = parseSafeJsonObject(selectedOption?.dataset?.modelIcon || '');
  }

  return {
    modelDeployment,
    modelId,
    modelEndpointId,
    modelProvider,
    modelIcon,
    modelDisplayName: String(
      modelSelect?.options?.[modelSelect.selectedIndex]?.dataset?.displayName
      || modelSelect?.options?.[modelSelect.selectedIndex]?.textContent
      || modelDeployment
      || 'Model'
    ).trim() || 'Model',
  };
}

function getCurrentAgentSelection() {
  const agentSelectContainer = document.getElementById('agent-select-container');
  const agentSelect = document.getElementById('agent-select');
  if (!areAgentsEnabled() || !agentSelectContainer || agentSelectContainer.style.display === 'none' || !agentSelect) {
    return null;
  }

  const selectedAgentOption = agentSelect.options[agentSelect.selectedIndex];
  if (!selectedAgentOption) {
    return null;
  }

  let assignedKnowledge = { enabled: false };
  try {
    const parsedAssignedKnowledge = JSON.parse(selectedAgentOption.dataset.assignedKnowledge || '{}');
    if (parsedAssignedKnowledge && typeof parsedAssignedKnowledge === 'object') {
      assignedKnowledge = parsedAssignedKnowledge;
    }
  } catch (error) {
    assignedKnowledge = { enabled: false };
  }

  const parseAgentJsonObject = (rawValue) => {
    if (!rawValue) {
      return {};
    }
    try {
      const parsedValue = JSON.parse(rawValue);
      return parsedValue && typeof parsedValue === 'object' && !Array.isArray(parsedValue) ? parsedValue : {};
    } catch (error) {
      return {};
    }
  };

  const parseAgentJsonArray = (rawValue) => {
    if (!rawValue) {
      return [];
    }
    try {
      const parsedValue = JSON.parse(rawValue);
      return Array.isArray(parsedValue) ? parsedValue : [];
    } catch (error) {
      return [];
    }
  };

  return {
    id: selectedAgentOption.dataset.agentId || null,
    name: selectedAgentOption.dataset.name || selectedAgentOption.value || '',
    display_name: selectedAgentOption.dataset.displayName || selectedAgentOption.textContent,
    is_global: selectedAgentOption.dataset.isGlobal === 'true',
    is_group: selectedAgentOption.dataset.isGroup === 'true',
    group_id: selectedAgentOption.dataset.groupId || null,
    group_name: selectedAgentOption.dataset.groupName || null,
    assigned_knowledge: assignedKnowledge,
    icon: parseAgentJsonObject(selectedAgentOption.dataset.agentIcon || ''),
    tags: parseAgentJsonArray(selectedAgentOption.dataset.agentTags || '[]'),
    catalog_key: selectedAgentOption.dataset.catalogKey || null,
  };
}

function normalizeCollaborativeTargetLabel(value) {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function getCollaborativeModelDisplayName(option = {}) {
  const dataset = option?.dataset || {};
  return String(
    dataset.displayName
    || option.display_name
    || option.model_id
    || dataset.modelId
    || dataset.deploymentName
    || option.deployment_name
    || option.textContent
    || option.label
    || option.value
    || ''
  ).trim();
}

function getCollaborativeAgentDisplayName(option = {}) {
  const dataset = option?.dataset || {};
  return String(
    dataset.displayName
    || option.display_name
    || option.displayName
    || option.textContent
    || option.label
    || option.name
    || option.value
    || ''
  ).trim();
}

function parseSafeJsonObject(rawValue) {
  if (!rawValue) {
    return {};
  }
  try {
    const parsedValue = JSON.parse(rawValue);
    return parsedValue && typeof parsedValue === 'object' && !Array.isArray(parsedValue) ? parsedValue : {};
  } catch (error) {
    return {};
  }
}

function parseSafeJsonArray(rawValue) {
  if (!rawValue) {
    return [];
  }
  try {
    const parsedValue = JSON.parse(rawValue);
    return Array.isArray(parsedValue) ? parsedValue : [];
  } catch (error) {
    return [];
  }
}

function buildCollaborativeModelTarget(option = {}) {
  const dataset = option?.dataset || {};
  const displayName = getCollaborativeModelDisplayName(option);
  const hasModelIdentity = Boolean(
    dataset.modelId
    || option.model_id
    || dataset.deploymentName
    || option.deployment_name
    || dataset.endpointId
    || option.endpoint_id
    || option.display_name
  );
  if (!displayName) {
    return null;
  }

  if (!hasModelIdentity && String(option.value || '').trim() === '') {
    return null;
  }

  const modelDeployment = String(dataset.deploymentName || option.deployment_name || option.value || '').trim() || null;
  const modelId = String(dataset.modelId || option.model_id || option.value || '').trim() || null;
  const modelEndpointId = String(dataset.endpointId || option.endpoint_id || '').trim() || null;
  const modelProvider = String(dataset.provider || option.provider || '').trim() || null;
  const parsedIcon = parseSafeJsonObject(dataset.modelIcon);
  const selectionKey = String(
    dataset.selectionKey
    || option.selection_key
    || modelDeployment
    || modelId
    || displayName
  ).trim();

  return {
    action: 'ai_tag',
    target_type: 'model',
    display_name: displayName,
    mention_text: `@${displayName}`,
    source_mode: 'explicit_tag',
    selection_key: selectionKey,
    model_deployment: modelDeployment,
    model_id: modelId,
    model_endpoint_id: modelEndpointId,
    model_provider: modelProvider,
    model_icon: Object.keys(parsedIcon).length ? parsedIcon : (option.icon || {}),
    subtitle: modelDeployment && modelDeployment !== displayName
      ? modelDeployment
      : modelProvider
      ? `${modelProvider} model`
      : 'Model deployment',
    search_text: [displayName, modelDeployment, modelId, modelProvider].filter(Boolean).join(' '),
  };
}

function buildCollaborativeAgentTarget(option = {}) {
  const dataset = option?.dataset || {};
  const displayName = getCollaborativeAgentDisplayName(option);
  const agentId = String(dataset.agentId || option.id || '').trim() || null;
  const agentName = String(dataset.name || option.name || option.value || '').trim() || null;
  if (!displayName || (!agentId && !agentName)) {
    return null;
  }

  const isGlobal = String(dataset.isGlobal || option.is_global || '').trim() === 'true' || option.is_global === true;
  const isGroup = String(dataset.isGroup || option.is_group || '').trim() === 'true' || option.is_group === true;
  const groupName = String(dataset.groupName || option.group_name || '').trim() || null;
  const parsedIcon = parseSafeJsonObject(dataset.agentIcon);
  const parsedTags = parseSafeJsonArray(dataset.agentTags);

  return {
    action: 'ai_tag',
    target_type: 'agent',
    display_name: displayName,
    mention_text: `@${displayName}`,
    source_mode: 'explicit_tag',
    agent_info: {
      id: agentId,
      name: agentName || displayName,
      display_name: displayName,
      is_global: isGlobal,
      is_group: isGroup,
      group_id: String(dataset.groupId || option.group_id || '').trim() || null,
      group_name: groupName,
      icon: Object.keys(parsedIcon).length ? parsedIcon : (option.icon || {}),
      tags: parsedTags.length ? parsedTags : (Array.isArray(option.tags) ? option.tags : []),
      catalog_key: String(dataset.catalogKey || option.catalog_key || '').trim() || null,
    },
    subtitle: isGroup && groupName
      ? `Group agent · ${groupName}`
      : isGlobal
      ? 'Global agent'
      : 'Personal agent',
    search_text: [displayName, agentName, agentId, groupName].filter(Boolean).join(' '),
  };
}

function getAvailableCollaborativeModelTargets() {
  const modelOptions = modelSelect?.options ? Array.from(modelSelect.options) : [];
  const mappedSelectTargets = modelOptions
    .map(option => buildCollaborativeModelTarget(option))
    .filter(Boolean);

  if (mappedSelectTargets.length > 0) {
    return mappedSelectTargets;
  }

  return (Array.isArray(window.chatModelOptions) ? window.chatModelOptions : [])
    .map(option => buildCollaborativeModelTarget(option))
    .filter(Boolean);
}

function getAvailableCollaborativeAgentTargets() {
  const agentSelect = document.getElementById('agent-select');
  const agentOptions = agentSelect?.options ? Array.from(agentSelect.options) : [];
  const mappedSelectTargets = agentOptions
    .map(option => buildCollaborativeAgentTarget(option))
    .filter(Boolean);

  if (mappedSelectTargets.length > 0) {
    return mappedSelectTargets;
  }

  return (Array.isArray(window.chatAgentOptions) ? window.chatAgentOptions : [])
    .map(option => buildCollaborativeAgentTarget(option))
    .filter(Boolean);
}

export function getCollaborativeTagSuggestions(query = '') {
  const normalizedQuery = normalizeCollaborativeTargetLabel(query);
  const matchesQuery = target => {
    if (!normalizedQuery) {
      return true;
    }

    const haystack = normalizeCollaborativeTargetLabel([
      target.display_name,
      target.subtitle,
      target.search_text,
      target.mention_text,
    ].filter(Boolean).join(' '));
    return haystack.includes(normalizedQuery);
  };

  return [
    ...getAvailableCollaborativeAgentTargets().filter(matchesQuery),
    ...getAvailableCollaborativeModelTargets().filter(matchesQuery),
  ];
}

function resolveCollaborativeExplicitInvocationTarget(messageText = '') {
  const normalizedMessageText = String(messageText || '');
  if (!normalizedMessageText.includes('@')) {
    return null;
  }

  const targets = getCollaborativeTagSuggestions('')
    .slice()
    .sort((leftTarget, rightTarget) => String(rightTarget.display_name || '').length - String(leftTarget.display_name || '').length);

  for (const target of targets) {
    const displayName = String(target.display_name || '').trim();
    if (!displayName) {
      continue;
    }

    if (buildAtMentionPattern(displayName).test(normalizedMessageText)) {
      return target;
    }
  }

  return null;
}

function stripExplicitCollaborativeTargetText(messageText = '', invocationTarget = null) {
  if (!invocationTarget?.display_name) {
    return String(messageText || '');
  }

  return normalizeStructuredMessageContent(
    String(messageText || '').replace(
      buildAtMentionPattern(invocationTarget.display_name),
      (match, leadingWhitespace) => leadingWhitespace || ''
    )
  );
}

function buildCollaborativeSendContext(finalMessageToSend, conversationId = currentConversationId) {
  const messageText = String(finalMessageToSend ?? '');
  const explicitInvocationTarget = resolveCollaborativeExplicitInvocationTarget(messageText);
  const messageData = buildChatRequestPayload(messageText, conversationId);

  if (explicitInvocationTarget?.target_type === 'agent' && explicitInvocationTarget.agent_info) {
    messageData.image_generation = false;
    messageData.agent_info = { ...explicitInvocationTarget.agent_info };
  }

  if (explicitInvocationTarget?.target_type === 'model') {
    messageData.image_generation = false;
    messageData.agent_info = null;
    messageData.model_deployment = explicitInvocationTarget.model_deployment || messageData.model_deployment;
    messageData.model_id = explicitInvocationTarget.model_id || messageData.model_id;
    messageData.model_endpoint_id = explicitInvocationTarget.model_endpoint_id || messageData.model_endpoint_id;
    messageData.model_provider = explicitInvocationTarget.model_provider || messageData.model_provider;
    messageData.model_icon = explicitInvocationTarget.model_icon || messageData.model_icon;
  }

  const invocationTarget = buildCollaborativeInvocationTarget(messageData, explicitInvocationTarget);
  const displayMessageText = explicitInvocationTarget
    ? stripExplicitCollaborativeTargetText(messageText, explicitInvocationTarget)
    : messageText;

  messageData.message = displayMessageText;

  return {
    messageData,
    invocationTarget,
    explicitInvocationTarget,
    displayMessageText,
  };
}

export function buildChatRequestPayload(finalMessageToSend, conversationId = currentConversationId) {
  const {
    modelDeployment,
    modelId,
    modelEndpointId,
    modelProvider,
    modelIcon,
  } = getCurrentModelSelection();

  const hybridSearchEnabled = isWorkspaceDocumentSearchEnabled();

  let selectedDocumentId = null;
  let selectedDocumentIds = [];
  const docSel = document.getElementById('document-select');
  if (docSel) {
    selectedDocumentIds = Array.from(docSel.selectedOptions)
      .map(option => option.value)
      .filter(value => value);
    selectedDocumentId = selectedDocumentIds.length > 0 ? selectedDocumentIds[0] : null;
  }

  let imageGenEnabled = false;
  const igbtn = document.getElementById('image-generate-btn');
  if (igbtn && igbtn.classList.contains('active')) {
    imageGenEnabled = true;
  }

  let chat_type = 'user';
  let group_id = null;
  if (window.activeChatTabType === 'group' && window.activeGroupId) {
    chat_type = 'group';
    group_id = window.activeGroupId;
  }

  let promptInfo = null;
  if (
    promptSelectionContainer
    && promptSelectionContainer.style.display !== 'none'
    && promptSelect
    && promptSelect.selectedIndex > 0
  ) {
    const selectedOpt = promptSelect.options[promptSelect.selectedIndex];
    if (selectedOpt) {
      promptInfo = {
        name: selectedOpt.textContent,
        id: selectedOpt.value,
        content: selectedOpt.dataset?.promptContent || '',
      };
    }
  }

  const agentInfo = getCurrentAgentSelection();
  const scopes = getEffectiveScopes();

  let effectiveDocScope = 'all';
  if (scopes.personal && scopes.groupIds.length === 0 && scopes.publicWorkspaceIds.length === 0) {
    effectiveDocScope = 'personal';
  } else if (!scopes.personal && scopes.groupIds.length > 0 && scopes.publicWorkspaceIds.length === 0) {
    effectiveDocScope = 'group';
  } else if (!scopes.personal && scopes.groupIds.length === 0 && scopes.publicWorkspaceIds.length > 0) {
    effectiveDocScope = 'public';
  }

  if (selectedDocumentIds.length > 0) {
    const docScopes = new Set();
    selectedDocumentIds.forEach(docId => {
      if (personalDocs.find(doc => doc.id === docId || doc.document_id === docId)) {
        docScopes.add('personal');
      } else if (groupDocs.find(doc => doc.id === docId || doc.document_id === docId)) {
        docScopes.add('group');
      } else if (publicDocs.find(doc => doc.id === docId || doc.document_id === docId)) {
        docScopes.add('public');
      }
    });

    if (docScopes.size === 1) {
      effectiveDocScope = docScopes.values().next().value;
      console.log(`All selected documents are from scope: ${effectiveDocScope}`);
    } else if (docScopes.size > 1) {
      effectiveDocScope = 'all';
      console.log(`Selected documents span ${docScopes.size} scopes (${[...docScopes].join(', ')}), keeping scope as "all"`);
    }
  }

  const finalGroupIds = scopes.groupIds.length > 0 ? scopes.groupIds : (window.activeGroupId ? [window.activeGroupId] : []);
  const finalGroupId = finalGroupIds[0] || group_id || null;
  const webSearchToggle = document.getElementById('search-web-btn');
  const webSearchEnabled = webSearchToggle ? webSearchToggle.classList.contains('active') : false;
  const urlAccessToggle = document.getElementById('url-access-btn');
  const urlAccessEnabled = urlAccessToggle ? urlAccessToggle.classList.contains('active') : false;
  const deepResearchToggle = document.getElementById('source-review-btn');
  const deepResearchEnabled = deepResearchToggle ? deepResearchToggle.classList.contains('active') : false;
  const finalPublicWorkspaceId = scopes.publicWorkspaceIds[0] || window.activePublicWorkspaceId || null;
  const selectedTags = getSelectedTags();
  const userWorkspaceContextEnabled = isUserWorkspaceContextEnabled();
  const selectedDocumentActionType = getDocumentActionType();
  const taskDocumentSummaryForSelectedAction = getConversationTaskDocumentSummary({
    actionType: selectedDocumentActionType,
    conversationId,
  });
  const documentActionType = (userWorkspaceContextEnabled || taskDocumentSummaryForSelectedAction.totalCount > 0)
    ? selectedDocumentActionType
    : DOCUMENT_ACTION_NONE;
  const comparisonTargetIds = documentActionType === DOCUMENT_ACTION_COMPARISON
    ? getSelectedComparisonTargetIds()
    : [];
  const comparisonLeftDocumentId = documentActionType === DOCUMENT_ACTION_COMPARISON
    ? String(documentComparisonLeftSelect?.value || comparisonTargetIds[0] || '').trim()
    : '';
  const comparisonRightDocumentIds = documentActionType === DOCUMENT_ACTION_COMPARISON
    ? comparisonTargetIds.filter(documentId => documentId !== comparisonLeftDocumentId)
    : [];
  const documentAction = {
    type: documentActionType,
    document_ids: documentActionType === DOCUMENT_ACTION_ANALYZE
      ? selectedDocumentIds
      : comparisonTargetIds,
    left_document_id: documentActionType === DOCUMENT_ACTION_COMPARISON ? comparisonLeftDocumentId : '',
    right_document_ids: comparisonRightDocumentIds,
    doc_scope: effectiveDocScope,
    active_group_ids: finalGroupIds,
    active_public_workspace_id: scopes.publicWorkspaceIds,
    window_unit: 'pages',
    max_retries_per_window: 1,
  };
  const conversationTaskDocumentIds = getConversationTaskDocumentIds({
    actionType: documentActionType,
    conversationId,
  });

  const requestPayload = {
    message: finalMessageToSend,
    conversation_id: conversationId,
    hybrid_search: hybridSearchEnabled,
    user_workspace_context_enabled: userWorkspaceContextEnabled,
    web_search_enabled: webSearchEnabled,
    url_access_enabled: urlAccessEnabled,
    source_review_enabled: deepResearchEnabled,
    deep_research_enabled: deepResearchEnabled,
    selected_document_id: selectedDocumentId,
    selected_document_ids: selectedDocumentIds,
    conversation_task_document_ids: conversationTaskDocumentIds,
    classifications: null,
    tags: selectedTags,
    image_generation: imageGenEnabled,
    doc_scope: effectiveDocScope,
    chat_type,
    active_group_ids: finalGroupIds,
    active_group_id: finalGroupId,
    active_public_workspace_ids: scopes.publicWorkspaceIds,
    active_public_workspace_id: finalPublicWorkspaceId,
    model_deployment: modelDeployment,
    model_id: modelId,
    model_endpoint_id: modelEndpointId,
    model_provider: modelProvider,
    model_icon: modelIcon,
    prompt_info: promptInfo,
    agent_info: agentInfo,
    reasoning_effort: getCurrentReasoningEffort(),
  };

  if (documentActionType !== DOCUMENT_ACTION_NONE) {
    requestPayload.document_action = documentAction;
  }

  if (documentActionType === DOCUMENT_ACTION_ANALYZE) {
    requestPayload.analyze = {
      enabled: true,
      document_ids: selectedDocumentIds,
      doc_scope: effectiveDocScope,
      active_group_ids: finalGroupIds,
      active_public_workspace_id: scopes.publicWorkspaceIds,
    };
  }

  return requestPayload;
}

export function buildCollaborativeInvocationTarget(messageData = {}, explicitInvocationTarget = null) {
  if (!messageData || typeof messageData !== 'object') {
    return null;
  }

  if (explicitInvocationTarget?.target_type === 'agent' || explicitInvocationTarget?.target_type === 'model') {
    return {
      ...explicitInvocationTarget,
      source_mode: 'explicit_tag',
      mention_text: explicitInvocationTarget.mention_text || `@${explicitInvocationTarget.display_name}`,
    };
  }

  const hasAgentTarget = Boolean(
    messageData.agent_info
    && (messageData.agent_info.id || messageData.agent_info.name || messageData.agent_info.display_name)
  );
  const sourceMode = messageData.image_generation
    ? 'image_generation'
    : hasAgentTarget
    ? 'agent'
    : messageData.deep_research_enabled || messageData.source_review_enabled
    ? 'deep_research'
    : messageData.url_access_enabled
    ? 'url_access'
    : messageData.web_search_enabled
    ? 'web_search'
    : messageData.hybrid_search
    ? 'workspace'
    : messageData.prompt_info
    ? 'prompt'
    : null;

  if (!sourceMode) {
    return null;
  }

  if (messageData.image_generation) {
    return {
      target_type: 'image',
      display_name: 'Image',
      mention_text: '@Image',
      source_mode: sourceMode,
    };
  }

  if (hasAgentTarget) {
    const agentLabel = String(
      messageData.agent_info.display_name
      || messageData.agent_info.name
      || messageData.agent_info.id
      || 'Agent'
    ).trim() || 'Agent';
    return {
      target_type: 'agent',
      display_name: agentLabel,
      mention_text: `@${agentLabel}`,
      source_mode: sourceMode,
    };
  }

  const { modelDisplayName } = getCurrentModelSelection();
  return {
    target_type: 'model',
    display_name: modelDisplayName,
    mention_text: `@${modelDisplayName}`,
    source_mode: sourceMode,
  };
}

export function shouldUseCollaborativeAiWorkflow(messageData = {}, explicitInvocationTarget = null) {
  return Boolean(buildCollaborativeInvocationTarget(messageData, explicitInvocationTarget));
}

export function actuallySendMessage(finalMessageToSend) {
  const isCollaborativeConversation = Boolean(
    currentConversationId
    && window.chatCollaboration?.isCollaborationConversation?.(currentConversationId)
  );

  if (isCollaborativeConversation) {
    const tempUserMessageId = `temp_user_${Date.now()}`;
    const {
      messageData: collaborativeMessageData,
      invocationTarget,
      explicitInvocationTarget,
      displayMessageText,
    } = buildCollaborativeSendContext(finalMessageToSend, currentConversationId);
    if (invocationTarget && !String(displayMessageText || '').trim()) {
      showToast('Add a message after the selected @agent or @model tag.', 'warning');
      return;
    }

    const pendingCollaborativeContext = window.chatCollaboration?.getPendingMessageContext?.({ invocationTarget }) || null;
    appendMessage("You", displayMessageText, null, tempUserMessageId, false, [], [], [], null, null, pendingCollaborativeContext);
    userInput.value = "";
    userInput.style.height = "";
    updateSendButtonVisibility();

    const collaborativeSendOperation = shouldUseCollaborativeAiWorkflow(collaborativeMessageData, explicitInvocationTarget)
      ? window.chatCollaboration.sendCollaborativeAiMessage?.(
        displayMessageText,
        tempUserMessageId,
        collaborativeMessageData,
        pendingCollaborativeContext,
      )
      : window.chatCollaboration.sendCollaborativeMessage(displayMessageText, tempUserMessageId);

    Promise.resolve(collaborativeSendOperation).catch(error => {
      const tempMessage = document.querySelector(`[data-message-id="${tempUserMessageId}"]`);
      if (tempMessage) {
        tempMessage.remove();
      }
      showToast(error.message || 'Failed to send shared message.', 'danger');
    });
    return;
  }

  // Generate a temporary message ID for the user message
  const tempUserMessageId = `temp_user_${Date.now()}`;
  const messageData = buildChatRequestPayload(finalMessageToSend, currentConversationId);
  const actionType = String(messageData.document_action?.type || DOCUMENT_ACTION_NONE).trim() || DOCUMENT_ACTION_NONE;
  const useDocumentAction = actionType !== DOCUMENT_ACTION_NONE;
  const totalSelectedDocuments = actionType === DOCUMENT_ACTION_COMPARISON
    ? (Array.isArray(messageData.document_action?.document_ids) ? messageData.document_action.document_ids.length : 0)
    : (Array.isArray(messageData.selected_document_ids) ? messageData.selected_document_ids.length : 0);
  const conversationTaskDocumentSummary = getConversationTaskDocumentSummary({
    actionType,
    conversationId: currentConversationId,
  });

  if (actionType === DOCUMENT_ACTION_ANALYZE && totalSelectedDocuments === 0 && conversationTaskDocumentSummary.readyCount === 0) {
    if (!conversationTaskDocumentSummary.allowed && conversationTaskDocumentSummary.totalCount > 0) {
      showToast('This agent does not allow uploaded task documents for analysis.', 'warning');
    } else if (conversationTaskDocumentSummary.pendingCount > 0) {
      showToast('Uploaded task documents are still processing. Try again when the upload is ready.', 'warning');
    } else {
      showToast('Select one or more documents before starting analysis.', 'warning');
    }
    return;
  }
  if (actionType === DOCUMENT_ACTION_COMPARISON && totalSelectedDocuments < 2) {
    showToast('Select at least two documents before starting compare.', 'warning');
    return;
  }
  if (actionType === DOCUMENT_ACTION_COMPARISON && (!messageData.document_action?.left_document_id || !Array.isArray(messageData.document_action?.right_document_ids) || messageData.document_action.right_document_ids.length === 0)) {
    showToast('Choose one left document and at least one right document for compare.', 'warning');
    return;
  }
  if (useDocumentAction && !isDocumentActionEnabled(actionType)) {
    showToast(`${getDocumentActionLabel(actionType)} is currently disabled by an administrator.`, 'warning');
    return;
  }
  const chatMaxDocuments = getDocumentActionMaxDocuments(actionType, 'chat');
  const workflowMaxDocuments = getDocumentActionMaxDocuments(actionType, 'workflow');
  if (useDocumentAction && totalSelectedDocuments > chatMaxDocuments) {
    showToast(
      `Chat ${getDocumentActionLabel(actionType)} supports up to ${chatMaxDocuments} documents. Use workflows for up to ${workflowMaxDocuments} documents.`,
      'warning'
    );
    return;
  }

  // Append user message first with temporary ID
  appendMessage("You", finalMessageToSend, null, tempUserMessageId);
  userInput.value = "";
  userInput.style.height = "";
  // Update send button visibility after clearing input
  updateSendButtonVisibility();
  sendMessageWithStreaming(
    messageData,
    tempUserMessageId,
    currentConversationId,
    {
      endpoint: useDocumentAction ? '/api/chat/document-action/stream' : '/api/chat/stream',
      fallbackAgentInfo: messageData.agent_info || null,
    }
  );

  return;
}

function attachCodeBlockCopyButtons(parentElement) {
  if (!parentElement) return; // Add guard clause
  const codeBlocks = parentElement.querySelectorAll("pre code");
  codeBlocks.forEach((codeBlock) => {
    const pre = codeBlock.parentElement;
    if (pre.querySelector(".copy-code-btn")) return; // Don't add if already exists

    pre.style.position = "relative";
    const copyBtn = document.createElement("button");
    copyBtn.innerHTML = '<i class="bi bi-copy"></i>';
    copyBtn.classList.add(
      "copy-code-btn",
      "btn",
      "btn-sm",
      "btn-outline-secondary"
    ); // Add Bootstrap classes
    copyBtn.title = "Copy code";
    copyBtn.style.position = "absolute";
    copyBtn.style.top = "5px";
    copyBtn.style.right = "5px";
    copyBtn.style.lineHeight = "1"; // Prevent extra height
    copyBtn.style.padding = "0.15rem 0.3rem"; // Smaller padding

    copyBtn.addEventListener("click", (e) => {
      e.stopPropagation(); // Prevent clicks bubbling up
      const codeToCopy = codeBlock.innerText; // Use innerText to get rendered text
      navigator.clipboard
        .writeText(codeToCopy)
        .then(() => {
          copyBtn.innerHTML = '<i class="bi bi-check-lg text-success"></i>';
          copyBtn.title = "Copied!";
          setTimeout(() => {
            copyBtn.innerHTML = '<i class="bi bi-copy"></i>';
            copyBtn.title = "Copy code";
          }, 2000);
        })
        .catch((err) => {
          console.error("Error copying code:", err);
          showToast("Failed to copy code.", "warning");
        });
    });
    pre.appendChild(copyBtn);
  });
}

if (sendBtn) {
  sendBtn.addEventListener("click", sendMessage);
}

if (userInput) {
  userInput.addEventListener("keydown", function (e) {
    if (window.chatCollaboration?.handleComposerKeydown?.(e)) {
      return;
    }

    // Check if Enter key is pressed
    if (e.key === "Enter") {
      // Check if Shift key is NOT pressed
      if (!e.shiftKey) {
        // Prevent default behavior (inserting a newline)
        e.preventDefault();
        // Send the message
        sendMessage();
      }
      // If Shift key IS pressed, do nothing - allow the default behavior (inserting a newline)
    }
  });

  // Monitor input changes for send button visibility
  userInput.addEventListener("input", () => {
    updateSendButtonVisibility();
    window.chatCollaboration?.handleComposerInput?.();
  });
  userInput.addEventListener("focus", () => {
    updateSendButtonVisibility();
    window.chatCollaboration?.handleComposerInput?.();
  });
  userInput.addEventListener("blur", () => {
    updateSendButtonVisibility();
    window.chatCollaboration?.handleComposerBlur?.();
  });
}

// Monitor prompt selection changes
if (promptSelect) {
  promptSelect.addEventListener("change", updateSendButtonVisibility);
}

updateDocumentActionControls();

// Helper function to update user message ID after backend response
export function updateUserMessageId(tempId, realId) {
  console.log(`🔄 Updating message ID: ${tempId} -> ${realId}`);

  // Find the message with the temporary ID
  const messageDiv = document.querySelector(`[data-message-id="${tempId}"]`);
  if (messageDiv) {
    // Update the data-message-id attribute
    messageDiv.setAttribute('data-message-id', realId);
    console.log(`✅ Updated messageDiv data-message-id to: ${realId}`);

    // Update ALL elements with the temporary ID to ensure consistency
    const elementsToUpdate = [
      messageDiv.querySelector('.copy-user-btn'),
      messageDiv.querySelector('.metadata-toggle-btn'),
      ...messageDiv.querySelectorAll(`[data-message-id="${tempId}"]`),
      ...messageDiv.querySelectorAll(`[aria-controls*="${tempId}"]`)
    ];

    let updateCount = 0;
    elementsToUpdate.forEach(element => {
      if (element) {
        // Update data-message-id attribute
        if (element.hasAttribute('data-message-id')) {
          element.setAttribute('data-message-id', realId);
          updateCount++;
        }

        // Update aria-controls attribute for metadata toggles
        if (element.hasAttribute('aria-controls')) {
          const ariaControls = element.getAttribute('aria-controls');
          if (ariaControls.includes(tempId)) {
            const newAriaControls = ariaControls.replace(tempId, realId);
            element.setAttribute('aria-controls', newAriaControls);
            updateCount++;
          }
        }
      }
    });

    // Update metadata container IDs
    const metadataContainer = messageDiv.querySelector(`[id*="${tempId}"]`);
    if (metadataContainer) {
      const oldId = metadataContainer.id;
      const newId = oldId.replace(tempId, realId);
      metadataContainer.id = newId;
      console.log(`✅ Updated metadata container ID: ${oldId} -> ${newId}`);
      updateCount++;
    }

    console.log(`✅ Updated ${updateCount} elements with new message ID`);

    // Verify the update was successful
    const verifyDiv = document.querySelector(`[data-message-id="${realId}"]`);
    if (verifyDiv) {
      console.log(`✅ ID update verification successful: ${realId} found in DOM`);
    } else {
      console.error(`❌ ID update verification failed: ${realId} not found in DOM`);
    }
  } else {
    const existingRealMessageDiv = document.querySelector(`[data-message-id="${realId}"]`);
    if (existingRealMessageDiv) {
      console.info(`ℹ️ Message div for temp ID ${tempId} was already reconciled to ${realId}`);
    } else {
      console.warn(`⚠️ Message div with temp ID ${tempId} not found for update`);
    }
  }
}

// Helper function to attach event listeners to user message buttons
function attachUserMessageEventListeners(messageDiv, messageId, messageContent) {
  const copyBtn = messageDiv.querySelector(".copy-user-btn");
  const metadataToggleBtn = messageDiv.querySelector(".metadata-toggle-btn");

  if (copyBtn) {
    copyBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(messageContent)
        .then(() => {
          copyBtn.innerHTML = '<i class="bi bi-check-lg text-success"></i>';
          copyBtn.title = "Copied!";
          setTimeout(() => {
            copyBtn.innerHTML = '<i class="bi bi-copy"></i>';
            copyBtn.title = "Copy message";
          }, 2000);
        })
        .catch((err) => {
          console.error("Error copying message:", err);
          showToast("Failed to copy message.", "warning");
        });
    });
  }

  if (metadataToggleBtn) {
    metadataToggleBtn.addEventListener("click", () => {
      toggleUserMessageMetadata(messageDiv, messageId);
    });
  }

  attachMaskButtonEventListeners(messageDiv);

  const dropdownDeleteBtn = messageDiv.querySelector(".dropdown-delete-btn");
  if (dropdownDeleteBtn) {
    dropdownDeleteBtn.addEventListener("click", (e) => {
      e.preventDefault();
      // Always read the message ID from the DOM attribute dynamically
      // This ensures we use the updated ID after updateUserMessageId is called
      const currentMessageId = messageDiv.getAttribute('data-message-id');
      console.log(`🗑️ Delete button clicked - using message ID from DOM: ${currentMessageId}`);
      handleDeleteButtonClick(messageDiv, currentMessageId, 'user');
    });
  }

  const dropdownRetryBtn = messageDiv.querySelector(".dropdown-retry-btn");
  if (dropdownRetryBtn) {
    dropdownRetryBtn.addEventListener("click", (e) => {
      e.preventDefault();
      // Always read the message ID from the DOM attribute dynamically
      const currentMessageId = messageDiv.getAttribute('data-message-id');
      console.log(`🔄 Retry button clicked - using message ID from DOM: ${currentMessageId}`);
      handleRetryButtonClick(messageDiv, currentMessageId, 'user');
    });
  }

  const dropdownEditBtn = messageDiv.querySelector(".dropdown-edit-btn");
  if (dropdownEditBtn) {
    dropdownEditBtn.addEventListener("click", (e) => {
      e.preventDefault();
      // Always read the message ID from the DOM attribute dynamically
      const currentMessageId = messageDiv.getAttribute('data-message-id');
      console.log(`✏️ Edit button clicked - using message ID from DOM: ${currentMessageId}`);
      // Import chat-edit module dynamically
      import('./chat-edit.js').then(module => {
        module.handleEditButtonClick(messageDiv, currentMessageId, 'user');
      }).catch(err => {
        console.error('❌ Error loading chat-edit module:', err);
      });
    });
  }

  attachMessageExportActionListeners(messageDiv, 'user');

  // Handle dropdown positioning manually for user messages - move to chatbox
  const dropdownToggle = messageDiv.querySelector(".message-footer .dropdown button[data-bs-toggle='dropdown']");
  const dropdownMenu = messageDiv.querySelector(".message-footer .dropdown-menu");
  if (dropdownToggle && dropdownMenu) {
    dropdownToggle.addEventListener("show.bs.dropdown", () => {
      const chatbox = document.getElementById('chatbox');
      if (chatbox) {
        dropdownMenu.remove();
        chatbox.appendChild(dropdownMenu);

        const rect = dropdownToggle.getBoundingClientRect();
        const chatboxRect = chatbox.getBoundingClientRect();
        dropdownMenu.style.position = 'absolute';
        dropdownMenu.style.top = `${rect.bottom - chatboxRect.top + chatbox.scrollTop + 2}px`;
        dropdownMenu.style.left = `${rect.left - chatboxRect.left}px`;
        dropdownMenu.style.zIndex = '9999';
      }
    });

    dropdownToggle.addEventListener("hidden.bs.dropdown", () => {
      const dropdown = messageDiv.querySelector(".message-footer .dropdown");
      if (dropdown && dropdownMenu.parentElement !== dropdown) {
        dropdownMenu.remove();
        dropdown.appendChild(dropdownMenu);
      }
    });
  }

  const carouselPrevBtn = messageDiv.querySelector(".carousel-prev-btn");
  if (carouselPrevBtn) {
    carouselPrevBtn.addEventListener("click", () => {
      handleCarouselClick(messageId, 'prev');
    });
  }

  const carouselNextBtn = messageDiv.querySelector(".carousel-next-btn");
  if (carouselNextBtn) {
    carouselNextBtn.addEventListener("click", () => {
      handleCarouselClick(messageId, 'next');
    });
  }
}

function attachCollaboratorMessageEventListeners(messageDiv, fullMessageObject, messageContent) {
  const dropdownReplyBtn = messageDiv.querySelector(".dropdown-reply-btn");
  if (dropdownReplyBtn) {
    dropdownReplyBtn.addEventListener("click", e => {
      e.preventDefault();
      const currentMessageId = messageDiv.getAttribute("data-message-id");
      window.chatCollaboration?.replyToMessage?.({
        ...(fullMessageObject || {}),
        id: currentMessageId,
        content: messageContent,
        sender: fullMessageObject?.sender || fullMessageObject?.metadata?.sender || {
          display_name: messageDiv.dataset.replySenderName || "Participant",
        },
      });
    });
  }

  const metadataToggleBtn = messageDiv.querySelector(".metadata-toggle-btn");
  if (metadataToggleBtn) {
    metadataToggleBtn.addEventListener("click", () => {
      const currentMessageId = messageDiv.getAttribute("data-message-id");
      toggleUserMessageMetadata(messageDiv, currentMessageId);
    });
  }

  const dropdownToggle = messageDiv.querySelector(".message-footer .dropdown button[data-bs-toggle='dropdown']");
  const dropdownMenu = messageDiv.querySelector(".message-footer .dropdown-menu");
  if (dropdownToggle && dropdownMenu) {
    dropdownToggle.addEventListener("show.bs.dropdown", () => {
      const localChatbox = document.getElementById("chatbox");
      if (localChatbox) {
        dropdownMenu.remove();
        localChatbox.appendChild(dropdownMenu);

        const rect = dropdownToggle.getBoundingClientRect();
        const chatboxRect = localChatbox.getBoundingClientRect();
        dropdownMenu.style.position = "absolute";
        dropdownMenu.style.top = `${rect.bottom - chatboxRect.top + localChatbox.scrollTop + 2}px`;
        dropdownMenu.style.left = `${rect.left - chatboxRect.left}px`;
        dropdownMenu.style.zIndex = "9999";
      }
    });

    dropdownToggle.addEventListener("hidden.bs.dropdown", () => {
      const dropdown = messageDiv.querySelector(".message-footer .dropdown");
      if (dropdown && dropdownMenu.parentElement !== dropdown) {
        dropdownMenu.remove();
        dropdown.appendChild(dropdownMenu);
      }
    });
  }
}

// Function to toggle user message metadata drawer
function toggleUserMessageMetadata(messageDiv, messageId) {
  console.log(`🔀 Toggling metadata for message: ${messageId}`);

  // Validate that we're not using a temporary ID
  if (messageId && messageId.startsWith('temp_user_')) {
    console.error(`❌ Metadata toggle called with temporary ID: ${messageId}`);
    console.log(`🔍 Checking if real ID is available in DOM...`);

    // Try to find the real ID from the message div
    const actualMessageId = messageDiv.getAttribute('data-message-id');
    if (actualMessageId && actualMessageId !== messageId && !actualMessageId.startsWith('temp_user_')) {
      console.log(`✅ Found real ID in DOM: ${actualMessageId}, using that instead`);
      messageId = actualMessageId;
    } else {
      console.error(`❌ No valid real ID found, metadata toggle may fail`);
    }
  }

  const toggleBtn = messageDiv.querySelector('.metadata-toggle-btn');
  const targetId = toggleBtn.getAttribute('aria-controls');
  const metadataContainer = messageDiv.querySelector(`#${targetId}`);

  if (!metadataContainer) {
    console.error(`❌ Metadata container not found for targetId: ${targetId}`);
    return;
  }

  const isExpanded = metadataContainer.style.display !== "none";

  // Store current scroll position to maintain user's view
  const currentScrollTop = document.getElementById('chat-messages-container')?.scrollTop || window.pageYOffset;

  if (isExpanded) {
    // Hide the metadata
    metadataContainer.style.display = "none";
    toggleBtn.setAttribute("aria-expanded", false);
    toggleBtn.title = "Show metadata";
    toggleBtn.innerHTML = '<i class="bi bi-info-circle"></i>';
    console.log(`✅ Metadata hidden for ${messageId}`);
  } else {
    // Show the metadata
    metadataContainer.style.display = "block";
    toggleBtn.setAttribute("aria-expanded", true);
    toggleBtn.title = "Hide metadata";
    toggleBtn.innerHTML = '<i class="bi bi-chevron-up"></i>';

    // Load metadata if not already loaded
    if (metadataContainer.innerHTML.includes('Loading metadata...')) {
      console.log(`🔄 Loading metadata content for ${messageId}`);
      loadUserMessageMetadata(messageId, metadataContainer);
    }

    console.log(`✅ Metadata shown for ${messageId}`);
    // Note: Removed scrollChatToBottom() to prevent jumping when expanding metadata
  }

  // Restore scroll position after DOM changes
  setTimeout(() => {
    if (document.getElementById('chat-messages-container')) {
      document.getElementById('chat-messages-container').scrollTop = currentScrollTop;
    } else {
      window.scrollTo(0, currentScrollTop);
    }
  }, 10);
}

// Function to load user message metadata into the drawer
function loadUserMessageMetadata(messageId, container, retryCount = 0) {
  console.log(`🔍 Loading metadata for message ID: ${messageId} (attempt ${retryCount + 1})`);

  // Validate message ID to catch temporary IDs early
  if (!messageId || messageId === "null" || messageId === "undefined") {
    console.error(`❌ Invalid message ID: ${messageId}`);
    container.innerHTML = '<div class="text-muted">Message metadata not available.</div>';
    return;
  }

  // Check for temporary IDs which indicate a bug
  if (messageId.startsWith('temp_user_')) {
    console.error(`❌ Attempting to load metadata with temporary ID: ${messageId}`);
    console.error(`This indicates the updateUserMessageId function didn't work properly`);

    if (retryCount < 2) {
      // Short retry for temp IDs in case the real ID update is still in progress
      console.log(`🔄 Retrying metadata load for temp ID in 100ms (attempt ${retryCount + 1}/3)`);
      setTimeout(() => {
        loadUserMessageMetadata(messageId, container, retryCount + 1);
      }, 100);
      return;
    } else {
      container.innerHTML = '<div class="text-danger">Message metadata unavailable (temporary ID not updated).</div>';
      return;
    }
  }

  // Fetch message metadata from the backend
  fetch(`/api/message/${messageId}/metadata`)
    .then(response => {
      console.log(`📡 Metadata API response for ${messageId}: ${response.status}`);

      if (!response.ok) {
        if (response.status === 404 && retryCount < 3) {
          // Message might not be fully saved yet, retry with exponential backoff
          const delay = Math.min((retryCount + 1) * 500, 2000); // Cap at 2 seconds
          console.log(`⏳ Message ${messageId} not found, retrying in ${delay}ms (attempt ${retryCount + 1}/3)`);
          setTimeout(() => {
            loadUserMessageMetadata(messageId, container, retryCount + 1);
          }, delay);
          return;
        }
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      return response.json();
    })
    .then(data => {
      if (data) {
        console.log(`✅ Successfully loaded metadata for ${messageId}`);
        container.innerHTML = formatMetadataForDrawer(data);

        // Attach event listeners to View Text buttons
        const viewTextButtons = container.querySelectorAll('.view-text-btn');
        viewTextButtons.forEach(btn => {
          btn.addEventListener('click', function() {
            const imageId = this.getAttribute('data-image-id');
            const collapseElement = document.getElementById(`${imageId}-info`);

            if (collapseElement) {
              const bsCollapse = new bootstrap.Collapse(collapseElement, {
                toggle: true
              });

              // Update button text
              if (collapseElement.classList.contains('show')) {
                this.innerHTML = '<i class="bi bi-eye me-1"></i>View Text';
              } else {
                this.innerHTML = '<i class="bi bi-eye-slash me-1"></i>Hide Text';
              }
            }
          });
        });
      }
    })
    .catch(error => {
      console.error(`❌ Error fetching message metadata for ${messageId}:`, error);

      if (retryCount >= 3) {
        container.innerHTML = '<div class="text-danger">Failed to load message metadata after multiple attempts.</div>';
      } else {
        container.innerHTML = '<div class="text-warning">Retrying to load message metadata...</div>';
      }
    });
}

// Helper function to format metadata for drawer display
function formatMetadataForDrawer(metadata) {
  let content = '';

  // Helper function to create status badge
  function createStatusBadge(status, type = 'status') {
    const isEnabled = status === 'Enabled' || status === true;
    const badgeClass = isEnabled ? 'badge bg-success' : 'badge bg-secondary';
    const text = isEnabled ? 'Enabled' : 'Disabled';
    return `<span class="${badgeClass}">${text}</span>`;
  }

  // Helper function to create info badge
  function createInfoBadge(text, variant = 'primary') {
    return `<span class="badge bg-${variant}">${escapeHtml(text)}</span>`;
  }

  // Helper function to create classification badge with proper colors
  function createClassificationBadge(classification) {
    if (!classification || classification === 'None') {
      return `<span class="badge bg-secondary">None</span>`;
    }

    // Try to find the classification in the global configuration
    const categories = window.classification_categories || [];
    const category = categories.find(cat => cat.label === classification);

    if (category && category.color) {
      const bgColor = category.color;
      const useDarkText = isColorLight(bgColor);
      const textColorClass = useDarkText ? 'text-dark' : 'text-white';
      return `<span class="badge ${textColorClass}" style="background-color: ${escapeHtml(bgColor)};">${escapeHtml(classification)}</span>`;
    } else {
      // Fallback to warning badge if category not found but classification exists
      return `<span class="badge bg-warning text-dark" title="Category config not found">${escapeHtml(classification)} (?)</span>`;
    }
  }

  if (metadata.message_details) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-chat-left-text me-2"></i>Message Details</div>';
    content += '<div class="ms-3 small">';

    if (metadata.message_details.message_id) {
      content += `<div class="mb-1"><span class="text-muted">Message ID:</span> <code class="ms-2">${escapeHtml(metadata.message_details.message_id)}</code></div>`;
    }
    if (metadata.message_details.conversation_id) {
      content += `<div class="mb-1"><span class="text-muted">Conversation ID:</span> <code class="ms-2">${escapeHtml(metadata.message_details.conversation_id)}</code></div>`;
    }
    if (metadata.message_details.role) {
      content += `<div class="mb-1"><span class="text-muted">Stored Role:</span> <span class="ms-2">${createInfoBadge(metadata.message_details.role, 'primary')}</span></div>`;
    }
    if (metadata.message_details.display_role) {
      content += `<div class="mb-1"><span class="text-muted">Display Role:</span> <span class="ms-2">${createInfoBadge(metadata.message_details.display_role, 'info')}</span></div>`;
    }
    if (metadata.message_details.message_kind) {
      content += `<div class="mb-1"><span class="text-muted">Message Kind:</span> <span class="ms-2">${createInfoBadge(metadata.message_details.message_kind, 'secondary')}</span></div>`;
    }
    if (metadata.message_details.source_role) {
      content += `<div class="mb-1"><span class="text-muted">Original Role:</span> <span class="ms-2">${createInfoBadge(metadata.message_details.source_role, 'warning')}</span></div>`;
    }
    if (metadata.message_details.timestamp) {
      content += `<div class="mb-1"><span class="text-muted">Timestamp:</span> <code class="ms-2">${escapeHtml(new Date(metadata.message_details.timestamp).toLocaleString())}</code></div>`;
    }
    if (metadata.message_details.explicit_ai_invocation !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Explicit AI Invocation:</span> <span class="ms-2">${createStatusBadge(Boolean(metadata.message_details.explicit_ai_invocation))}</span></div>`;
    }

    content += '</div></div>';
  }

  if (metadata.reply_context) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-reply me-2"></i>Reply Context</div>';
    content += '<div class="ms-3 small">';
    if (metadata.reply_context.message_id) {
      content += `<div class="mb-1"><span class="text-muted">Reply Message ID:</span> <code class="ms-2">${escapeHtml(metadata.reply_context.message_id)}</code></div>`;
    }
    if (metadata.reply_context.sender_display_name) {
      content += `<div class="mb-1"><span class="text-muted">Replying To:</span> <span class="ms-2">${escapeHtml(metadata.reply_context.sender_display_name)}</span></div>`;
    }
    if (metadata.reply_context.content_preview) {
      content += `<div class="mb-1"><span class="text-muted">Preview:</span><div class="mt-1 p-2 bg-light rounded small">${escapeHtml(metadata.reply_context.content_preview)}</div></div>`;
    }
    content += '</div></div>';
  }

  if (Array.isArray(metadata.mentions) && metadata.mentions.length > 0) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-at me-2"></i>Tagged Participants</div>';
    content += '<div class="ms-3 small d-flex flex-wrap gap-2">';
    metadata.mentions.forEach(participant => {
      content += `<span class="badge bg-success-subtle text-success-emphasis">@${escapeHtml(participant.display_name || participant.email || participant.user_id || 'Participant')}</span>`;
    });
    content += '</div></div>';
  }

  if (metadata.collaboration) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-people me-2"></i>Shared Conversation</div>';
    content += '<div class="ms-3 small">';
    if (metadata.collaboration.conversation_title) {
      content += `<div class="mb-1"><span class="text-muted">Conversation:</span> <span class="ms-2">${escapeHtml(metadata.collaboration.conversation_title)}</span></div>`;
    }
    if (metadata.collaboration.chat_type) {
      content += `<div class="mb-1"><span class="text-muted">Collaboration Type:</span> <span class="ms-2">${createInfoBadge(metadata.collaboration.chat_type, 'success')}</span></div>`;
    }
    if (metadata.collaboration.participant_count !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Participants:</span> <span class="ms-2 badge bg-secondary">${escapeHtml(metadata.collaboration.participant_count)}</span></div>`;
    }
    content += '</div></div>';
  }

  if (metadata.file_details) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-file-earmark me-2"></i>File Details</div>';
    content += '<div class="ms-3 small">';
    if (metadata.file_details.filename) {
      content += `<div class="mb-1"><span class="text-muted">Filename:</span> <code class="ms-2">${escapeHtml(metadata.file_details.filename)}</code></div>`;
    }
    if (metadata.file_details.source_message_id) {
      content += `<div class="mb-1"><span class="text-muted">Source Message ID:</span> <code class="ms-2">${escapeHtml(metadata.file_details.source_message_id)}</code></div>`;
    }
    if (metadata.file_details.is_table !== undefined && metadata.file_details.is_table !== null) {
      content += `<div class="mb-1"><span class="text-muted">Table Data:</span> <span class="ms-2">${createStatusBadge(Boolean(metadata.file_details.is_table))}</span></div>`;
    }
    content += '</div></div>';
  }

  if (metadata.image_details) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-image me-2"></i>Image Details</div>';
    content += '<div class="ms-3 small">';
    if (metadata.image_details.filename) {
      content += `<div class="mb-1"><span class="text-muted">Filename:</span> <code class="ms-2">${escapeHtml(metadata.image_details.filename)}</code></div>`;
    }
    if (metadata.image_details.image_url) {
      content += `<div class="mb-1"><span class="text-muted">Image URL:</span> <code class="ms-2 text-break">${escapeHtml(metadata.image_details.image_url)}</code></div>`;
    }
    if (metadata.image_details.is_user_upload !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">User Upload:</span> <span class="ms-2">${createStatusBadge(Boolean(metadata.image_details.is_user_upload))}</span></div>`;
    }
    if (metadata.image_details.extracted_text) {
      content += `<div class="mb-1"><span class="text-muted">Extracted Text:</span><div class="mt-1 p-2 bg-light rounded small">${escapeHtml(metadata.image_details.extracted_text)}</div></div>`;
    }
    if (metadata.image_details.vision_analysis) {
      content += `<div class="mb-1"><span class="text-muted">Vision Analysis:</span><div class="mt-1 p-2 bg-light rounded small">${escapeHtml(metadata.image_details.vision_analysis)}</div></div>`;
    }
    content += '</div></div>';
  }

  if (metadata.generation_details) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-cpu me-2"></i>Generation Details</div>';
    content += '<div class="ms-3 small">';
    if (metadata.generation_details.selected_model) {
      content += `<div class="mb-1"><span class="text-muted">Model:</span> <code class="ms-2">${escapeHtml(metadata.generation_details.selected_model)}</code></div>`;
    }
    if (metadata.generation_details.agent_display_name || metadata.generation_details.agent_name) {
      content += `<div class="mb-1"><span class="text-muted">Agent:</span> <span class="ms-2">${escapeHtml(metadata.generation_details.agent_display_name || metadata.generation_details.agent_name)}</span></div>`;
    }
    if (metadata.generation_details.augmented !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Augmented:</span> <span class="ms-2">${createStatusBadge(Boolean(metadata.generation_details.augmented))}</span></div>`;
    }
    if (metadata.generation_details.document_citation_count !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Document Citations:</span> <span class="ms-2 badge bg-info">${escapeHtml(metadata.generation_details.document_citation_count)}</span></div>`;
    }
    if (metadata.generation_details.web_citation_count !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Web Citations:</span> <span class="ms-2 badge bg-info">${escapeHtml(metadata.generation_details.web_citation_count)}</span></div>`;
    }
    if (metadata.generation_details.agent_citation_count !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Agent Citations:</span> <span class="ms-2 badge bg-info">${escapeHtml(metadata.generation_details.agent_citation_count)}</span></div>`;
    }
    content += '</div></div>';
  }

  // User Information Section
  if (metadata.user_info) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-person me-2"></i>User Information</div>';
    content += '<div class="ms-3 small">';

    if (metadata.user_info.display_name) {
      content += `<div class="mb-1"><span class="text-muted">User:</span> <span class="ms-2">${escapeHtml(metadata.user_info.display_name)}</span></div>`;
    }

    if (metadata.user_info.email) {
      content += `<div class="mb-1"><span class="text-muted">Email:</span> <span class="ms-2">${escapeHtml(metadata.user_info.email)}</span></div>`;
    }

    if (metadata.user_info.username) {
      content += `<div class="mb-1"><span class="text-muted">Username:</span> <span class="ms-2">${escapeHtml(metadata.user_info.username)}</span></div>`;
    }

    if (metadata.user_info.timestamp) {
      const date = new Date(metadata.user_info.timestamp);
      content += `<div class="mb-1"><span class="text-muted">Timestamp:</span> <code class="ms-2">${escapeHtml(date.toLocaleString())}</code></div>`;
    }

    content += '</div></div>';
  }

  // Thread Information Section (priority display)
  if (metadata.thread_info) {
    const ti = metadata.thread_info;
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-diagram-3 me-2"></i>Thread Information</div>';
    content += '<div class="ms-3 small">';

    content += `<div class="mb-1"><span class="text-muted">Thread ID:</span> <code class="ms-2">${escapeHtml(ti.thread_id || 'N/A')}</code></div>`;

    content += `<div class="mb-1"><span class="text-muted">Previous Thread:</span> <code class="ms-2">${escapeHtml(ti.previous_thread_id || 'None')}</code></div>`;

    const activeThreadBadge = ti.active_thread ?
      '<span class="badge bg-success">Yes</span>' :
      '<span class="badge bg-secondary">No</span>';
    content += `<div class="mb-1"><span class="text-muted">Active:</span> <span class="ms-2">${activeThreadBadge}</span></div>`;

    content += `<div><span class="text-muted">Attempt:</span> <span class="ms-2 badge bg-info">${ti.thread_attempt || 1}</span></div>`;

    content += '</div></div>';
  }

  // Button States Section
  if (metadata.button_states) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-toggles me-2"></i>Button States</div>';
    content += '<div class="ms-3 small">';

    if (metadata.button_states.image_generation !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Image Generation:</span> <span class="ms-2">${createStatusBadge(metadata.button_states.image_generation)}</span></div>`;
    }

    if (metadata.button_states.web_search !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Web Search:</span> <span class="ms-2">${createStatusBadge(metadata.button_states.web_search)}</span></div>`;
    }

    if (metadata.button_states.url_access !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">URL Access:</span> <span class="ms-2">${createStatusBadge(metadata.button_states.url_access)}</span></div>`;
    }

    if (metadata.button_states.deep_research !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Deep Research:</span> <span class="ms-2">${createStatusBadge(metadata.button_states.deep_research)}</span></div>`;
    }

    if (metadata.button_states.document_search !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Document Search:</span> <span class="ms-2">${createStatusBadge(metadata.button_states.document_search)}</span></div>`;
    }

    content += '</div></div>';
  }

  if (metadata.capability_usage) {
    const capabilityUsage = metadata.capability_usage;
    const workspaceUsage = capabilityUsage.workspace || {};
    const actionUsage = capabilityUsage.actions || {};
    const webSearchUsage = capabilityUsage.web_search || {};
    const deepResearchUsage = capabilityUsage.deep_research || {};

    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-sliders me-2"></i>Capability Usage</div>';
    content += '<div class="ms-3 small">';

    if (workspaceUsage.action) {
      content += `<div class="mb-1"><span class="text-muted">Workspace Action:</span> <span class="ms-2">${createInfoBadge(workspaceUsage.action, 'primary')}</span></div>`;
    }
    if (actionUsage.search !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Search Used:</span> <span class="ms-2">${createStatusBadge(Boolean(actionUsage.search))}</span></div>`;
    }
    if (actionUsage.analyze !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Analyze Used:</span> <span class="ms-2">${createStatusBadge(Boolean(actionUsage.analyze))}</span></div>`;
    }
    if (actionUsage.compare !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Compare Used:</span> <span class="ms-2">${createStatusBadge(Boolean(actionUsage.compare))}</span></div>`;
    }
    if (webSearchUsage.enabled !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Web Search Enabled:</span> <span class="ms-2">${createStatusBadge(Boolean(webSearchUsage.enabled))}</span></div>`;
    }
    if (webSearchUsage.used !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Web Search Used:</span> <span class="ms-2">${createStatusBadge(Boolean(webSearchUsage.used))}</span></div>`;
    }
    if (deepResearchUsage.enabled !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Deep Research Enabled:</span> <span class="ms-2">${createStatusBadge(Boolean(deepResearchUsage.enabled))}</span></div>`;
    }
    if (deepResearchUsage.used !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Deep Research Used:</span> <span class="ms-2">${createStatusBadge(Boolean(deepResearchUsage.used))}</span></div>`;
    }

    content += '</div></div>';
  }

  // Workspace Search Section
  if (metadata.workspace_search) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-folder me-2"></i>Workspace & Document Selection</div>';
    content += '<div class="ms-3 small">';

    if (metadata.workspace_search.search_enabled !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Search Enabled:</span> <span class="ms-2">${createStatusBadge(metadata.workspace_search.search_enabled)}</span></div>`;
    }

    if (metadata.workspace_search.document_name) {
      content += `<div class="mb-1"><span class="text-muted">Selected Document:</span> <span class="ms-2">${escapeHtml(metadata.workspace_search.document_name)}</span></div>`;
    } else if (metadata.workspace_search.selected_document_id && metadata.workspace_search.selected_document_id !== 'None' && metadata.workspace_search.selected_document_id !== 'all') {
      content += `<div class="mb-1"><span class="text-muted">Document ID:</span> <span class="ms-2">${escapeHtml(metadata.workspace_search.selected_document_id)}</span></div>`;
    }

    if (metadata.workspace_search.document_scope) {
      content += `<div class="mb-1"><span class="text-muted">Search Scope:</span> <span class="ms-2">${createInfoBadge(metadata.workspace_search.document_scope, 'primary')}</span></div>`;
    }

    if (metadata.workspace_search.classification && metadata.workspace_search.classification !== 'None') {
      content += `<div class="mb-1"><span class="text-muted">Classification:</span> <span class="ms-2">${createClassificationBadge(metadata.workspace_search.classification)}</span></div>`;
    }

    if (metadata.workspace_search.group_name) {
      content += `<div class="mb-1"><span class="text-muted">Group:</span> <span class="ms-2">${escapeHtml(metadata.workspace_search.group_name)}</span></div>`;
    }

    content += '</div></div>';
  }

  // Prompt Selection Section
  if (metadata.prompt_selection) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-chat-quote me-2"></i>Prompt Selection</div>';
    content += '<div class="ms-3 small">';

    if (metadata.prompt_selection.prompt_name) {
      content += `<div class="mb-1"><span class="text-muted">Prompt Name:</span> <span class="ms-2">${createInfoBadge(metadata.prompt_selection.prompt_name, 'success')}</span></div>`;
    }

    if (metadata.prompt_selection.selected_prompt_index !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Prompt Index:</span> <span class="ms-2">${escapeHtml(metadata.prompt_selection.selected_prompt_index)}</span></div>`;
    }

    if (metadata.prompt_selection.selected_prompt_text) {
      content += `<div class="mb-1"><span class="text-muted">Content:</span><div class="mt-1 p-2 bg-light rounded small">${escapeHtml(metadata.prompt_selection.selected_prompt_text)}</div></div>`;
    }

    content += '</div></div>';
  }

  // Agent Selection Section
  if (metadata.agent_selection) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-robot me-2"></i>Agent Selection</div>';
    content += '<div class="ms-3 small">';

    if (metadata.agent_selection.agent_display_name) {
      content += `<div class="mb-1"><span class="text-muted">Agent:</span> <span class="ms-2">${createInfoBadge(metadata.agent_selection.agent_display_name, 'success')}</span></div>`;
    } else if (metadata.agent_selection.selected_agent) {
      content += `<div class="mb-1"><span class="text-muted">Selected Agent:</span> <span class="ms-2">${createInfoBadge(metadata.agent_selection.selected_agent, 'success')}</span></div>`;
    }

    if (metadata.agent_selection.is_global !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Global Agent:</span> <span class="ms-2">${createStatusBadge(metadata.agent_selection.is_global)}</span></div>`;
    }

    content += '</div></div>';
  }

  // Model Selection Section
  if (metadata.model_selection) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-cpu me-2"></i>Model Selection</div>';
    content += '<div class="ms-3 small">';

    if (metadata.model_selection.selected_model) {
      content += `<div class="mb-1"><span class="text-muted">Selected Model:</span> <code class="ms-2">${escapeHtml(metadata.model_selection.selected_model)}</code></div>`;
    }

    if (metadata.model_selection.frontend_requested_model &&
        metadata.model_selection.frontend_requested_model !== metadata.model_selection.selected_model) {
      content += `<div class="mb-1"><span class="text-muted">Frontend Model:</span> <code class="ms-2">${escapeHtml(metadata.model_selection.frontend_requested_model)}</code></div>`;
    }

    if (metadata.model_selection.reasoning_effort) {
      content += `<div class="mb-1"><span class="text-muted">Reasoning Effort:</span> <code class="ms-2">${escapeHtml(metadata.model_selection.reasoning_effort)}</code></div>`;
    }

    if (metadata.model_selection.streaming !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Streaming:</span> <span class="ms-2">${createStatusBadge(metadata.model_selection.streaming)}</span></div>`;
    }

    content += '</div></div>';
  }

  // Uploaded Images Section
  if (metadata.uploaded_images && metadata.uploaded_images.length > 0) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-image me-2"></i>Uploaded Image</div>';
    content += '<div class="ms-3 small">';

    metadata.uploaded_images.forEach((image, index) => {
      const imageId = `image-${metadata.message_details?.message_id || Date.now()}-${index}`;
      content += `<div class="metadata-item">`;
      content += `<div class="card">`;
      content += `<img src="${escapeHtml(image.url)}" alt="Uploaded Image" class="card-img-top" style="max-width: 100%; height: auto;" />`;
      content += `<div class="card-body">`;
      content += `<div class="d-flex justify-content-between align-items-center">`;
      content += `<small class="text-muted">Filename: ${escapeHtml(image.filename || 'Unknown')}</small>`;

      // Add View Text button if OCR or vision data exists
      if ((image.ocr_text && image.ocr_text.trim()) || (image.vision_analysis && image.vision_analysis.trim())) {
        content += `<button class="btn btn-sm btn-outline-primary view-text-btn"
                      data-image-id="${imageId}"
                      title="View extracted text">
                      <i class="bi bi-eye me-1"></i>View Text
                    </button>`;
      }

      content += `</div>`; // End d-flex

      // Add collapsible drawer for OCR and vision analysis
      if ((image.ocr_text && image.ocr_text.trim()) || (image.vision_analysis && image.vision_analysis.trim())) {
        content += `<div class="collapse mt-2" id="${imageId}-info">`;

        if (image.ocr_text && image.ocr_text.trim()) {
          content += `<div class="border-top pt-2 mt-2">`;
          content += `<strong class="text-muted"><i class="bi bi-file-text me-1"></i>Extracted Text (OCR):</strong>`;
          content += `<div class="mt-1 p-2 bg-light rounded small" style="max-height: 200px; overflow-y: auto;">`;
          content += `<pre class="mb-0" style="white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(image.ocr_text)}</pre>`;
          content += `</div></div>`;
        }

        if (image.vision_analysis && image.vision_analysis.trim()) {
          content += `<div class="border-top pt-2 mt-2">`;
          content += `<strong class="text-muted"><i class="bi bi-info-circle me-1"></i>AI Vision Analysis:</strong>`;
          content += `<div class="mt-1 p-2 bg-light rounded small">`;
          content += `<div>${escapeHtml(image.vision_analysis)}</div>`;
          content += `</div></div>`;
        }

        content += `</div>`; // End collapse
      }

      content += `</div>`; // End card-body
      content += `</div>`; // End card
      content += `</div>`; // End item wrapper
    });

    content += '</div></div>'; // End ms-3 small and mb-3
  }

  // Chat Context Section
  if (metadata.chat_context) {
    content += '<div class="mb-3">';
    content += '<div class="fw-bold mb-2"><i class="bi bi-chat-left-text me-2"></i>Chat Context</div>';
    content += '<div class="ms-3 small">';

    if (metadata.chat_context.conversation_id) {
      content += `<div class="mb-1"><span class="text-muted">Conversation ID:</span> <code class="ms-2">${escapeHtml(metadata.chat_context.conversation_id)}</code></div>`;
    }

    if (metadata.chat_context.chat_type) {
      content += `<div class="mb-1"><span class="text-muted">Chat Type:</span> <span class="ms-2">${createInfoBadge(metadata.chat_context.chat_type, 'primary')}</span></div>`;
    }

    // Show context-specific information based on chat type
    if (metadata.chat_context.chat_type === 'group') {
      if (metadata.chat_context.group_name) {
        content += `<div class="mb-1"><span class="text-muted">Group:</span> <span class="ms-2">${escapeHtml(metadata.chat_context.group_name)}</span></div>`;
      } else if (metadata.chat_context.group_id && metadata.chat_context.group_id !== 'None') {
        content += `<div class="mb-1"><span class="text-muted">Group ID:</span> <span class="ms-2">${escapeHtml(metadata.chat_context.group_id)}</span></div>`;
      }
    } else if (metadata.chat_context.chat_type === 'public') {
      if (metadata.chat_context.workspace_context) {
        content += `<div class="mb-1"><span class="text-muted">Workspace:</span> <span class="ms-2">${createInfoBadge(metadata.chat_context.workspace_context, 'info')}</span></div>`;
      }
    }
    // For 'personal' chat type, no additional context needed

    content += '</div></div>';
  }

  if (!content) {
    content = '<div class="text-muted">No metadata available for this message.</div>';
  }

  return `<div class="metadata-content">${content}</div>`;
}

// Monitor when prompt container is shown/hidden
const searchPromptsBtn = document.getElementById("search-prompts-btn");
if (searchPromptsBtn) {
  searchPromptsBtn.addEventListener("click", function() {
    // Small delay to allow the prompt container to update
    setTimeout(updateSendButtonVisibility, 100);
  });
}

// Initial check for send button visibility
document.addEventListener('DOMContentLoaded', function() {
  updateSendButtonVisibility();
});

// Save the selected model when it changes
if (modelSelect) {
  modelSelect.addEventListener("change", function() {
    const selectedModel = modelSelect.value;
    if (window.appSettings?.enable_multi_model_endpoints) {
      const selectedOption = modelSelect.options[modelSelect.selectedIndex];
      const selectionKey = selectedOption?.dataset?.selectionKey || selectedModel;
      console.log(`Saving preferred model ID: ${selectionKey}`);
      saveUserSetting({ preferredModelId: selectionKey });
    } else {
      console.log(`Saving preferred model deployment: ${selectedModel}`);
      saveUserSetting({ preferredModelDeployment: selectedModel });
    }
  });
}

/**
 * Toggle the image info drawer for uploaded images
 * Shows extracted text (OCR) and vision analysis
 */
function toggleImageInfo(messageDiv, messageId, fullMessageObject) {
  const toggleBtn = messageDiv.querySelector('.image-info-btn');
  const targetId = toggleBtn.getAttribute('aria-controls');
  const infoContainer = messageDiv.querySelector(`#${targetId}`);

  if (!infoContainer) {
    console.error(`Image info container not found for targetId: ${targetId}`);
    return;
  }

  const isExpanded = infoContainer.style.display !== "none";

  // Store current scroll position to maintain user's view
  const currentScrollTop = document.getElementById('chat-messages-container')?.scrollTop || window.pageYOffset;

  if (isExpanded) {
    // Hide the info
    infoContainer.style.display = "none";
    toggleBtn.setAttribute("aria-expanded", false);
    toggleBtn.title = "View extracted text";
    toggleBtn.innerHTML = '<i class="bi bi-file-text"></i>';
  } else {
    // Show the info
    infoContainer.style.display = "block";
    toggleBtn.setAttribute("aria-expanded", true);
    toggleBtn.title = "Hide extracted text";
    toggleBtn.innerHTML = '<i class="bi bi-chevron-up"></i>';

    // Load image info if not already loaded
    const contentDiv = infoContainer.querySelector('.image-info-content');
    if (contentDiv && (contentDiv.innerHTML.trim() === '' || contentDiv.innerHTML.includes('Loading image information...'))) {
      loadImageInfo(fullMessageObject, contentDiv);
    }
  }

  // Restore scroll position after DOM changes
  setTimeout(() => {
    if (document.getElementById('chat-messages-container')) {
      document.getElementById('chat-messages-container').scrollTop = currentScrollTop;
    } else {
      window.scrollTo(0, currentScrollTop);
    }
  }, 10);
}

/**
 * Toggle the metadata drawer for AI, image, and file messages
 */
function toggleMessageMetadata(messageDiv, messageId) {
  const existingDrawer = messageDiv.querySelector('.message-metadata-drawer');

  if (existingDrawer) {
    // Drawer exists, remove it
    existingDrawer.remove();
    return;
  }

  // Create new drawer
  const drawerDiv = document.createElement('div');
  drawerDiv.className = 'message-metadata-drawer mt-2 p-3 border rounded bg-light';
  drawerDiv.innerHTML = '<div class="spinner-border spinner-border-sm" role="status"><span class="visually-hidden">Loading...</span></div>';

  messageDiv.appendChild(drawerDiv);

  // Load metadata
  loadMessageMetadataForDisplay(messageId, drawerDiv);
}

/**
 * Load message metadata into the drawer for AI/image/file messages
 */
function loadMessageMetadataForDisplay(messageId, container) {
  function renderHistoryContextRefRow(label, refs) {
    if (!Array.isArray(refs) || refs.length === 0) {
      return `<div class="mb-2"><span class="text-muted">${label}:</span> <span class="ms-2 text-muted">none</span></div>`;
    }

    return `
      <div class="mb-2">
        <div><span class="text-muted">${label}:</span></div>
        <div class="ms-3 mt-1 text-break" style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(refs.join(', '))}</div>
      </div>
    `;
  }

  function renderHistoryContextSection(historyContext) {
    if (!historyContext || typeof historyContext !== 'object') {
      return '';
    }

    let sectionHtml = '<div class="mb-3">';
    sectionHtml += '<div class="fw-bold mb-2"><i class="bi bi-clock-history me-2"></i>History Context</div>';
    sectionHtml += '<div class="ms-3 small">';
    sectionHtml += `<div class="mb-1"><span class="text-muted">Path:</span> <code class="ms-2">${escapeHtml(String(historyContext.path || 'unknown'))}</code></div>`;
    sectionHtml += `<div class="mb-1"><span class="text-muted">Stored Messages:</span> <span class="ms-2 badge bg-secondary">${Number(historyContext.stored_total_messages || 0)}</span></div>`;
    sectionHtml += `<div class="mb-1"><span class="text-muted">History Limit:</span> <span class="ms-2 badge bg-secondary">${Number(historyContext.history_limit || 0)}</span></div>`;
    sectionHtml += `<div class="mb-1"><span class="text-muted">Older Messages:</span> <span class="ms-2 badge bg-secondary">${Number(historyContext.older_message_count || 0)}</span></div>`;
    sectionHtml += `<div class="mb-1"><span class="text-muted">Recent Selected:</span> <span class="ms-2 badge bg-info">${Number(historyContext.recent_message_count || 0)}</span></div>`;
    sectionHtml += `<div class="mb-1"><span class="text-muted">Final API Messages:</span> <span class="ms-2 badge bg-primary">${Number(historyContext.final_api_message_count || 0)}</span></div>`;
    sectionHtml += `<div class="mb-1"><span class="text-muted">Summary Requested:</span> <span class="ms-2 badge ${historyContext.summary_requested ? 'bg-warning text-dark' : 'bg-secondary'}">${historyContext.summary_requested ? 'Yes' : 'No'}</span></div>`;
    sectionHtml += `<div class="mb-1"><span class="text-muted">Summary Used:</span> <span class="ms-2 badge ${historyContext.summary_used ? 'bg-success' : 'bg-secondary'}">${historyContext.summary_used ? 'Yes' : 'No'}</span></div>`;
    sectionHtml += `<div class="mb-2"><span class="text-muted">Default System Prompt:</span> <span class="ms-2 badge ${historyContext.default_system_prompt_inserted ? 'bg-success' : 'bg-secondary'}">${historyContext.default_system_prompt_inserted ? 'Inserted' : 'Not inserted'}</span></div>`;
    sectionHtml += renderHistoryContextRefRow('Recent Refs', historyContext.selected_recent_message_refs);
    sectionHtml += renderHistoryContextRefRow('Summarized Refs', historyContext.summarized_message_refs);
    sectionHtml += renderHistoryContextRefRow('Skipped Inactive', historyContext.skipped_inactive_message_refs);
    sectionHtml += renderHistoryContextRefRow('Skipped Masked', historyContext.skipped_masked_message_refs);
    sectionHtml += renderHistoryContextRefRow('Final API Refs', historyContext.final_api_source_refs);
    sectionHtml += '</div></div>';

    return sectionHtml;
  }

  fetch(`/api/message/${messageId}/metadata`)
    .then(response => {
      if (!response.ok) {
        throw new Error('Failed to load metadata');
      }
      return response.json();
    })
    .then(data => {
      if (!data) {
        container.innerHTML = '<p class="text-muted mb-0">No metadata available</p>';
        return;
      }

      const metadata = data;
      let html = '<div class="metadata-content">';

      // Thread Information (check both locations for backward compatibility)
      const threadInfo = metadata.metadata?.thread_info || {
        thread_id: metadata.thread_id,
        previous_thread_id: metadata.previous_thread_id,
        active_thread: metadata.active_thread,
        thread_attempt: metadata.thread_attempt
      };
      const historyContext = metadata.metadata?.history_context || null;
      const capabilityUsage = metadata.metadata?.capability_usage || null;
      const collaborationInfo = metadata.metadata?.collaboration || null;
      const replyContext = metadata.metadata?.reply_context || null;
      const mentionList = Array.isArray(metadata.metadata?.mentions)
        ? metadata.metadata.mentions
        : [];

      if (threadInfo.thread_id) {
        html += '<div class="mb-3">';
        html += '<div class="fw-bold mb-2"><i class="bi bi-diagram-3 me-2"></i>Thread Information</div>';
        html += '<div class="ms-3 small">';
        html += `<div class="mb-1"><span class="text-muted">Thread ID:</span> <code class="ms-2">${threadInfo.thread_id}</code></div>`;
        html += `<div class="mb-1"><span class="text-muted">Previous Thread:</span> <code class="ms-2">${threadInfo.previous_thread_id || 'None (first message)'}</code></div>`;
        html += `<div class="mb-1"><span class="text-muted">Active:</span> <span class="ms-2 badge ${threadInfo.active_thread ? 'bg-success' : 'bg-secondary'}">${threadInfo.active_thread ? 'Yes' : 'No'}</span></div>`;
        html += `<div><span class="text-muted">Attempt:</span> <span class="ms-2 badge bg-info">${threadInfo.thread_attempt || 1}</span></div>`;
        html += '</div></div>';
      }

      // Message Details
      html += '<div class="mb-3">';
      html += '<div class="fw-bold mb-2"><i class="bi bi-chat-left-text me-2"></i>Message Details</div>';
      html += '<div class="ms-3 small">';
      if (metadata.id) html += `<div class="mb-1"><span class="text-muted">Message ID:</span> <code class="ms-2">${metadata.id}</code></div>`;
      if (metadata.conversation_id) html += `<div class="mb-1"><span class="text-muted">Conversation ID:</span> <code class="ms-2">${metadata.conversation_id}</code></div>`;
      if (metadata.role) html += `<div class="mb-1"><span class="text-muted">Role:</span> <span class="ms-2 badge bg-primary">${metadata.role}</span></div>`;
      if (metadata.message_kind) html += `<div class="mb-1"><span class="text-muted">Message Kind:</span> <span class="ms-2 badge bg-secondary">${metadata.message_kind}</span></div>`;
      if (metadata.metadata?.source_role) html += `<div class="mb-1"><span class="text-muted">Original Role:</span> <span class="ms-2 badge bg-warning text-dark">${metadata.metadata.source_role}</span></div>`;
      if (metadata.timestamp) html += `<div class="mb-1"><span class="text-muted">Timestamp:</span> <code class="ms-2">${new Date(metadata.timestamp).toLocaleString()}</code></div>`;
      html += '</div></div>';

      if (replyContext) {
        html += '<div class="mb-3">';
        html += '<div class="fw-bold mb-2"><i class="bi bi-reply me-2"></i>Reply Context</div>';
        html += '<div class="ms-3 small">';
        if (replyContext.message_id) html += `<div class="mb-1"><span class="text-muted">Reply Message ID:</span> <code class="ms-2">${escapeHtml(replyContext.message_id)}</code></div>`;
        if (replyContext.sender_display_name) html += `<div class="mb-1"><span class="text-muted">Replying To:</span> <span class="ms-2">${escapeHtml(replyContext.sender_display_name)}</span></div>`;
        if (replyContext.content_preview) html += `<div class="mb-1"><span class="text-muted">Preview:</span><div class="mt-1 p-2 bg-light rounded small">${escapeHtml(replyContext.content_preview)}</div></div>`;
        html += '</div></div>';
      }

      if (mentionList.length > 0) {
        html += '<div class="mb-3">';
        html += '<div class="fw-bold mb-2"><i class="bi bi-at me-2"></i>Tagged Participants</div>';
        html += '<div class="ms-3 small d-flex flex-wrap gap-2">';
        mentionList.forEach(participant => {
          html += `<span class="badge bg-success-subtle text-success-emphasis">@${escapeHtml(participant.display_name || participant.email || participant.user_id || 'Participant')}</span>`;
        });
        html += '</div></div>';
      }

      if (collaborationInfo) {
        html += '<div class="mb-3">';
        html += '<div class="fw-bold mb-2"><i class="bi bi-people me-2"></i>Shared Conversation</div>';
        html += '<div class="ms-3 small">';
        if (collaborationInfo.conversation_title) html += `<div class="mb-1"><span class="text-muted">Conversation:</span> <span class="ms-2">${escapeHtml(collaborationInfo.conversation_title)}</span></div>`;
        if (collaborationInfo.chat_type) html += `<div class="mb-1"><span class="text-muted">Collaboration Type:</span> <span class="ms-2 badge bg-success">${escapeHtml(collaborationInfo.chat_type)}</span></div>`;
        if (collaborationInfo.participant_count !== undefined) html += `<div class="mb-1"><span class="text-muted">Participants:</span> <span class="ms-2 badge bg-secondary">${escapeHtml(collaborationInfo.participant_count)}</span></div>`;
        html += '</div></div>';
      }

      // Image/File specific info
      if (metadata.role === 'image') {
        html += '<div class="mb-3">';
        html += '<div class="fw-bold mb-2"><i class="bi bi-image me-2"></i>Image Details</div>';
        html += '<div class="ms-3 small">';
        if (metadata.filename) html += `<div class="mb-1"><span class="text-muted">Filename:</span> <code class="ms-2">${metadata.filename}</code></div>`;
        if (metadata.prompt) html += `<div class="mb-1"><span class="text-muted">Prompt:</span> <span class="ms-2">${metadata.prompt}</span></div>`;
        if (metadata.metadata?.is_chunked !== undefined) html += `<div class="mb-1"><span class="text-muted">Chunked:</span> <span class="ms-2 badge ${metadata.metadata.is_chunked ? 'bg-warning' : 'bg-success'}">${metadata.metadata.is_chunked ? 'Yes' : 'No'}</span></div>`;
        if (metadata.metadata?.is_user_upload !== undefined) html += `<div class="mb-1"><span class="text-muted">User Upload:</span> <span class="ms-2 badge ${metadata.metadata.is_user_upload ? 'bg-info' : 'bg-secondary'}">${metadata.metadata.is_user_upload ? 'Yes' : 'No'}</span></div>`;
        html += '</div></div>';
      } else if (metadata.role === 'file') {
        html += '<div class="mb-3">';
        html += '<div class="fw-bold mb-2"><i class="bi bi-file-earmark me-2"></i>File Details</div>';
        html += '<div class="ms-3 small">';
        if (metadata.filename) html += `<div class="mb-1"><span class="text-muted">Filename:</span> <code class="ms-2">${metadata.filename}</code></div>`;
        if (metadata.is_table !== undefined) html += `<div class="mb-1"><span class="text-muted">Table Data:</span> <span class="ms-2 badge ${metadata.is_table ? 'bg-success' : 'bg-secondary'}">${metadata.is_table ? 'Yes' : 'No'}</span></div>`;
        html += '</div></div>';
      }

      // Generation Details (for assistant, image, and file messages)
      if (metadata.role === 'assistant' || metadata.role === 'image' || metadata.role === 'file') {
        html += '<div class="mb-3">';
        html += '<div class="fw-bold mb-2"><i class="bi bi-cpu me-2"></i>Generation Details</div>';
        html += '<div class="ms-3 small">';

        // Model and Agent info (for all types)
        if (metadata.model_deployment_name) html += `<div class="mb-1"><span class="text-muted">Model:</span> <code class="ms-2">${metadata.model_deployment_name}</code></div>`;
        if (metadata.agent_name) html += `<div class="mb-1"><span class="text-muted">Agent:</span> <code class="ms-2">${metadata.agent_name}</code></div>`;
        if (metadata.agent_display_name) html += `<div class="mb-1"><span class="text-muted">Agent Display Name:</span> <span class="ms-2">${escapeHtml(metadata.agent_display_name)}</span></div>`;

        // Assistant-specific info
        if (metadata.role === 'assistant') {
          if (metadata.augmented !== undefined) html += `<div class="mb-1"><span class="text-muted">Augmented:</span> <span class="ms-2 badge ${metadata.augmented ? 'bg-success' : 'bg-secondary'}">${metadata.augmented ? 'Yes' : 'No'}</span></div>`;
          if (metadata.metadata?.reasoning_effort) html += `<div class="mb-1"><span class="text-muted">Reasoning Effort:</span> <code class="ms-2">${metadata.metadata.reasoning_effort}</code></div>`;
          if (capabilityUsage?.workspace?.action) html += `<div class="mb-1"><span class="text-muted">Workspace Action:</span> <span class="ms-2 badge bg-primary">${escapeHtml(capabilityUsage.workspace.action)}</span></div>`;
          if (capabilityUsage?.actions?.search !== undefined) html += `<div class="mb-1"><span class="text-muted">Search Used:</span> <span class="ms-2 badge ${capabilityUsage.actions.search ? 'bg-success' : 'bg-secondary'}">${capabilityUsage.actions.search ? 'Yes' : 'No'}</span></div>`;
          if (capabilityUsage?.actions?.analyze !== undefined) html += `<div class="mb-1"><span class="text-muted">Analyze Used:</span> <span class="ms-2 badge ${capabilityUsage.actions.analyze ? 'bg-success' : 'bg-secondary'}">${capabilityUsage.actions.analyze ? 'Yes' : 'No'}</span></div>`;
          if (capabilityUsage?.actions?.compare !== undefined) html += `<div class="mb-1"><span class="text-muted">Compare Used:</span> <span class="ms-2 badge ${capabilityUsage.actions.compare ? 'bg-success' : 'bg-secondary'}">${capabilityUsage.actions.compare ? 'Yes' : 'No'}</span></div>`;
          if (capabilityUsage?.web_search?.enabled !== undefined) html += `<div class="mb-1"><span class="text-muted">Web Search Enabled:</span> <span class="ms-2 badge ${capabilityUsage.web_search.enabled ? 'bg-success' : 'bg-secondary'}">${capabilityUsage.web_search.enabled ? 'Yes' : 'No'}</span></div>`;
          if (capabilityUsage?.web_search?.used !== undefined) html += `<div class="mb-1"><span class="text-muted">Web Search Used:</span> <span class="ms-2 badge ${capabilityUsage.web_search.used ? 'bg-success' : 'bg-secondary'}">${capabilityUsage.web_search.used ? 'Yes' : 'No'}</span></div>`;
          if (capabilityUsage?.deep_research?.enabled !== undefined) html += `<div class="mb-1"><span class="text-muted">Deep Research Enabled:</span> <span class="ms-2 badge ${capabilityUsage.deep_research.enabled ? 'bg-success' : 'bg-secondary'}">${capabilityUsage.deep_research.enabled ? 'Yes' : 'No'}</span></div>`;
          if (capabilityUsage?.deep_research?.used !== undefined) html += `<div class="mb-1"><span class="text-muted">Deep Research Used:</span> <span class="ms-2 badge ${capabilityUsage.deep_research.used ? 'bg-success' : 'bg-secondary'}">${capabilityUsage.deep_research.used ? 'Yes' : 'No'}</span></div>`;
          if (metadata.hybrid_citations && metadata.hybrid_citations.length > 0) html += `<div class="mb-1"><span class="text-muted">Document Citations:</span> <span class="ms-2 badge bg-info">${metadata.hybrid_citations.length}</span></div>`;
          if (metadata.web_search_citations && metadata.web_search_citations.length > 0) html += `<div class="mb-1"><span class="text-muted">Web Citations:</span> <span class="ms-2 badge bg-info">${metadata.web_search_citations.length}</span></div>`;
          if (metadata.agent_citations && metadata.agent_citations.length > 0) html += `<div class="mb-1"><span class="text-muted">Agent Citations:</span> <span class="ms-2 badge bg-info">${metadata.agent_citations.length}</span></div>`;
        }

        html += '</div></div>';
      }

      if (metadata.role === 'assistant') {
        html += createCitationDetailsSectionHtml(
          Array.isArray(metadata.hybrid_citations) ? metadata.hybrid_citations : [],
          Array.isArray(metadata.web_search_citations) ? metadata.web_search_citations : [],
          Array.isArray(metadata.agent_citations) ? metadata.agent_citations : [],
          metadata.id || messageId,
          metadata.conversation_id || ''
        );
      }

      if (metadata.role === 'assistant' && historyContext) {
        html += renderHistoryContextSection(historyContext);
      }

      html += '</div>';
      container.innerHTML = html;
    })
    .catch(error => {
      console.error('Error loading message metadata:', error);
      container.innerHTML = '<div class="alert alert-danger mb-0"><i class="bi bi-exclamation-triangle me-2"></i>Failed to load metadata</div>';
    });
}

/**
 * Load image extracted text and vision analysis into the info drawer
 */
function loadImageInfo(fullMessageObject, container) {
  const extractedText = fullMessageObject?.extracted_text || '';
  const visionAnalysis = fullMessageObject?.vision_analysis || null;
  const filename = fullMessageObject?.filename || 'Image';

  let content = '<div class="image-info-content">';

  // Filename
  content += `<div class="mb-3"><strong><i class="bi bi-file-earmark-image me-1"></i>Filename:</strong> ${escapeHtml(filename)}</div>`;

  // Extracted Text (OCR from Document Intelligence)
  if (extractedText && extractedText.trim()) {
    content += '<div class="mb-3">';
    content += '<strong><i class="bi bi-file-text me-1"></i>Extracted Text (OCR):</strong>';
    content += '<div class="mt-2 p-2 bg-light border rounded" style="max-height: 300px; overflow-y: auto; white-space: pre-wrap; font-family: monospace; font-size: 0.9em;">';
    content += escapeHtml(extractedText);
    content += '</div></div>';
  }

  // Vision Analysis (AI-generated description, objects, text)
  if (visionAnalysis) {
    content += '<div class="mb-3">';
    content += '<strong><i class="bi bi-eye me-1"></i>AI Vision Analysis:</strong>';

    // Model name can be either 'model' or 'model_name'
    const modelName = visionAnalysis.model || visionAnalysis.model_name;
    if (modelName) {
      content += `<div class="mt-1 text-muted" style="font-size: 0.85em;">Model: ${escapeHtml(modelName)}</div>`;
    }

    if (visionAnalysis.description) {
      content += '<div class="mt-2"><strong>Description:</strong><div class="p-2 bg-light border rounded" style="white-space: pre-wrap;">';
      content += escapeHtml(visionAnalysis.description);
      content += '</div></div>';
    }

    if (visionAnalysis.objects && Array.isArray(visionAnalysis.objects) && visionAnalysis.objects.length > 0) {
      content += '<div class="mt-2"><strong>Objects Detected:</strong><div class="p-2 bg-light border rounded">';
      content += visionAnalysis.objects.map(obj => `<span class="badge bg-secondary me-1">${escapeHtml(obj)}</span>`).join('');
      content += '</div></div>';
    }

    if (visionAnalysis.text && visionAnalysis.text.trim()) {
      content += '<div class="mt-2"><strong>Text Visible in Image:</strong><div class="p-2 bg-light border rounded" style="white-space: pre-wrap;">';
      content += escapeHtml(visionAnalysis.text);
      content += '</div></div>';
    }

    // Contextual analysis can be either 'analysis' or 'contextual_analysis'
    const analysis = visionAnalysis.analysis || visionAnalysis.contextual_analysis;
    if (analysis && analysis.trim()) {
      content += '<div class="mt-2"><strong>Contextual Analysis:</strong><div class="p-2 bg-light border rounded" style="white-space: pre-wrap;">';
      content += escapeHtml(analysis);
      content += '</div></div>';
    }

    content += '</div>';
  }

  content += '</div>';

  if (!extractedText && !visionAnalysis) {
    content = '<div class="text-muted">No extracted text or analysis available for this image.</div>';
  }

  container.innerHTML = content;
}

// Search highlight functions
export function applySearchHighlight(searchTerm) {
  if (!searchTerm || searchTerm.trim() === '') return;

  // Clear any existing highlights first
  clearSearchHighlight();

  const chatbox = document.getElementById('chatbox');
  if (!chatbox) return;

  // Find all message content elements
  const messageContents = chatbox.querySelectorAll('.message-content, .ai-response');

  // Escape special regex characters in search term
  const escapedTerm = searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(`(${escapedTerm})`, 'gi');

  messageContents.forEach(element => {
    const walker = document.createTreeWalker(
      element,
      NodeFilter.SHOW_TEXT,
      null,
      false
    );

    const textNodes = [];
    let node;
    while (node = walker.nextNode()) {
      if (node.nodeValue.trim() !== '') {
        textNodes.push(node);
      }
    }

    textNodes.forEach(textNode => {
      const text = textNode.nodeValue;
      if (regex.test(text)) {
        const span = document.createElement('span');
        span.innerHTML = text.replace(regex, '<mark class="search-highlight">$1</mark>');
        textNode.parentNode.replaceChild(span, textNode);
      }
    });
  });

  // Set timeout to clear highlights after 30 seconds
  if (window.searchHighlight) {
    if (window.searchHighlight.timeoutId) {
      clearTimeout(window.searchHighlight.timeoutId);
    }
    window.searchHighlight.timeoutId = setTimeout(() => {
      clearSearchHighlight();
      window.searchHighlight = null;
    }, 30000);
  }
}

export function clearSearchHighlight() {
  const chatbox = document.getElementById('chatbox');
  if (!chatbox) return;

  // Find all highlight marks
  const highlights = chatbox.querySelectorAll('mark.search-highlight');
  highlights.forEach(mark => {
    const text = document.createTextNode(mark.textContent);
    mark.parentNode.replaceChild(text, mark);
  });

  // Clear timeout if exists
  if (window.searchHighlight && window.searchHighlight.timeoutId) {
    clearTimeout(window.searchHighlight.timeoutId);
    window.searchHighlight.timeoutId = null;
  }
}

export function scrollToMessageSmooth(messageId) {
  if (!messageId) return;

  const chatbox = document.getElementById('chatbox');
  if (!chatbox) return;

  // Find message by data-message-id attribute
  const messageElement = chatbox.querySelector(`[data-message-id="${messageId}"]`);
  if (!messageElement) {
    console.warn(`Message with ID ${messageId} not found`);
    return;
  }

  // Scroll smoothly to message
  messageElement.scrollIntoView({
    behavior: 'smooth',
    block: 'center'
  });

  // Add pulse animation
  messageElement.classList.add('message-pulse');

  // Remove pulse after 2 seconds
  setTimeout(() => {
    messageElement.classList.remove('message-pulse');
  }, 2000);
}

// ============= Message Masking Functions =============

function getMaskStateFromMetadata(metadata = {}) {
  const maskedRanges = Array.isArray(metadata?.masked_ranges) ? metadata.masked_ranges : [];
  const fullyMasked = Boolean(metadata?.masked);
  return {
    fullyMasked,
    hasRanges: maskedRanges.length > 0,
    hasAnyMask: fullyMasked || maskedRanges.length > 0,
    maskedRanges,
  };
}

function buildMaskActionIconHtml(action, showModifier = true) {
  const baseIcon = action === 'remove' ? 'bi-front' : 'bi-back';
  const modifierIcon = action === 'remove' ? 'bi-dash-lg' : 'bi-plus-lg';
  const modifierClass = showModifier ? '' : ' d-none';
  return `
    <span class="mask-action-icon" aria-hidden="true">
      <i class="bi ${baseIcon}"></i>
      <i class="bi ${modifierIcon} mask-action-modifier${modifierClass}"></i>
    </span>`;
}

function buildMaskControlsHtml(messageId, maskState = {}) {
  const safeMessageId = escapeHtml(String(messageId || ''));
  const removeHiddenClass = maskState.hasAnyMask ? '' : ' d-none';
  const addTitle = maskState.hasAnyMask ? 'Add another mask' : 'Mask entire message';
  const removeTitle = maskState.fullyMasked ? 'Remove full-message mask' : 'Clear text masks';
  return `
    <span class="message-mask-controls d-inline-flex align-items-center gap-1">
      <button class="btn btn-sm btn-link text-muted mask-btn mask-add-btn" data-message-id="${safeMessageId}" title="${addTitle}" aria-label="${addTitle}">
        ${buildMaskActionIconHtml('add', Boolean(maskState.hasAnyMask))}
      </button>
      <button class="btn btn-sm btn-link text-muted mask-btn mask-remove-btn${removeHiddenClass}" data-message-id="${safeMessageId}" title="${removeTitle}" aria-label="${removeTitle}">
        ${buildMaskActionIconHtml('remove', true)}
      </button>
    </span>`;
}

function captureMessageMaskingOriginalContent(messageDiv) {
  if (!messageDiv || messageDiv._maskingOriginalNodes) {
    return;
  }

  const messageText = messageDiv.querySelector('.message-text');
  if (!messageText) {
    return;
  }

  messageDiv._maskingOriginalNodes = Array.from(messageText.childNodes).map(node => node.cloneNode(true));
}

function restoreMessageMaskingOriginalContent(messageDiv, messageText) {
  captureMessageMaskingOriginalContent(messageDiv);
  destroyInlineCharts(messageText);
  const originalNodes = Array.isArray(messageDiv._maskingOriginalNodes)
    ? messageDiv._maskingOriginalNodes.map(node => node.cloneNode(true))
    : [];
  if (originalNodes.length > 0) {
    messageText.replaceChildren(...originalNodes);
  }
}

function addMessageExclusionBadge(messageDiv) {
  const messageFooter = messageDiv.querySelector('.message-footer');
  if (!messageFooter || messageFooter.querySelector('.message-exclusion-badge')) {
    return;
  }

  const badge = document.createElement('div');
  badge.className = 'message-exclusion-badge text-warning small';
  const icon = document.createElement('i');
  icon.className = 'bi bi-exclamation-triangle-fill';
  badge.appendChild(icon);
  messageFooter.appendChild(badge);
}

function removeMessageExclusionBadge(messageDiv) {
  const badge = messageDiv.querySelector('.message-exclusion-badge');
  if (badge) {
    badge.remove();
  }
}

function getTextNodeSegments(rootElement) {
  const segments = [];
  const walker = document.createTreeWalker(rootElement, NodeFilter.SHOW_TEXT);
  let offset = 0;
  let node = walker.nextNode();
  while (node) {
    const length = node.textContent.length;
    segments.push({ node, start: offset, end: offset + length });
    offset += length;
    node = walker.nextNode();
  }
  return segments;
}

function findTextPosition(segments, offset, preferEnd = false) {
  for (const segment of segments) {
    if (preferEnd) {
      if (offset > segment.start && offset <= segment.end) {
        return { node: segment.node, offset: offset - segment.start };
      }
    } else if (offset >= segment.start && offset < segment.end) {
      return { node: segment.node, offset: offset - segment.start };
    }
  }
  return null;
}

function createMaskedContentSpan(range) {
  const timestampValue = range.timestamp ? new Date(range.timestamp) : null;
  const timestamp = timestampValue && !Number.isNaN(timestampValue.getTime())
    ? timestampValue.toLocaleDateString()
    : 'unknown date';
  const maskedSpan = document.createElement('span');
  maskedSpan.className = 'masked-content';
  maskedSpan.setAttribute('data-mask-id', String(range.id ?? ''));
  maskedSpan.setAttribute('data-user-id', String(range.user_id ?? ''));
  maskedSpan.setAttribute('data-display-name', String(range.display_name ?? ''));
  maskedSpan.title = `Masked by ${String(range.display_name ?? 'Unknown User')} on ${timestamp}`;
  return maskedSpan;
}

function wrapMaskedRange(messageText, range) {
  const contentLength = messageText.textContent.length;
  const rawDisplayStart = Number(range.display_start);
  const rawDisplayEnd = Number(range.display_end);
  const rawStart = Number.isFinite(rawDisplayStart) ? rawDisplayStart : Number(range.start);
  const rawEnd = Number.isFinite(rawDisplayEnd) ? rawDisplayEnd : Number(range.end);
  const start = Math.max(0, Math.min(rawStart, contentLength));
  const end = Math.max(0, Math.min(rawEnd, contentLength));
  if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) {
    return;
  }

  const segments = getTextNodeSegments(messageText);
  const startPosition = findTextPosition(segments, start, false);
  const endPosition = findTextPosition(segments, end, true);
  if (!startPosition || !endPosition) {
    return;
  }

  const domRange = document.createRange();
  domRange.setStart(startPosition.node, startPosition.offset);
  domRange.setEnd(endPosition.node, endPosition.offset);

  const maskedSpan = createMaskedContentSpan(range);
  try {
    domRange.surroundContents(maskedSpan);
  } catch (error) {
    const contents = domRange.extractContents();
    maskedSpan.appendChild(contents);
    domRange.insertNode(maskedSpan);
  }
}

function applyMaskedRangesToMessageText(messageText, maskedRanges) {
  const sortedRanges = [...maskedRanges]
    .filter(range => range && Number.isFinite(Number(range.start)) && Number.isFinite(Number(range.end)))
    .sort((left, right) => Number(right.start) - Number(left.start));
  sortedRanges.forEach(range => wrapMaskedRange(messageText, range));
}

function updateMaskControls(messageDiv, metadata = {}) {
  const maskState = getMaskStateFromMetadata(metadata);
  const addButton = messageDiv.querySelector('.mask-add-btn');
  const removeButton = messageDiv.querySelector('.mask-remove-btn');
  const addModifier = addButton?.querySelector('.mask-action-modifier');

  if (addButton) {
    const selectionInfo = getSelectionInfoForMessage(messageDiv);
    const title = selectionInfo
      ? 'Mask selected content'
      : maskState.hasAnyMask
        ? 'Add full-message mask'
        : 'Mask entire message';
    addButton.title = title;
    addButton.setAttribute('aria-label', title);
  }
  if (addModifier) {
    addModifier.classList.toggle('d-none', !maskState.hasAnyMask);
  }
  if (removeButton) {
    const removeTitle = maskState.fullyMasked
      ? 'Remove full-message mask'
      : 'Clear text masks';
    removeButton.title = removeTitle;
    removeButton.setAttribute('aria-label', removeTitle);
    removeButton.classList.toggle('d-none', !maskState.hasAnyMask);
  }
}

function applyMaskedState(messageDiv, metadata = {}) {
  if (!messageDiv) return;

  const messageText = messageDiv.querySelector('.message-text');
  if (!messageText) return;

  const nextMetadata = {
    ...(messageDiv._maskingMetadata || {}),
    ...(metadata || {}),
  };
  messageDiv._maskingMetadata = nextMetadata;

  restoreMessageMaskingOriginalContent(messageDiv, messageText);

  if (nextMetadata.masked) {
    messageDiv.classList.add('fully-masked');
    addMessageExclusionBadge(messageDiv);
  } else {
    messageDiv.classList.remove('fully-masked');
    removeMessageExclusionBadge(messageDiv);
  }

  const maskedRanges = Array.isArray(nextMetadata.masked_ranges) ? nextMetadata.masked_ranges : [];
  if (maskedRanges.length > 0) {
    applyMaskedRangesToMessageText(messageText, maskedRanges);
  }

  hydrateInlineCharts(messageDiv);
  hydrateInlineImageProposals(messageDiv);
  updateMaskControls(messageDiv, nextMetadata);
}

function getSelectionInfoForMessage(messageDiv) {
  const messageText = messageDiv?.querySelector('.message-text');
  const selection = window.getSelection();
  if (!messageText || !selection || selection.rangeCount === 0 || !selection.toString().trim()) {
    return null;
  }

  const range = selection.getRangeAt(0);
  if (!messageText.contains(range.commonAncestorContainer)) {
    return null;
  }

  const preSelectionRange = range.cloneRange();
  preSelectionRange.selectNodeContents(messageText);
  preSelectionRange.setEnd(range.startContainer, range.startOffset);
  const selectedText = selection.toString();
  const start = preSelectionRange.toString().length;
  return {
    selection,
    start,
    end: start + selectedText.length,
    text: selectedText,
  };
}

function getMaskConversationId(messageDiv) {
  return String(
    messageDiv?.dataset?.conversationId
      || window.chatConversations?.getCurrentConversationId?.()
      || window.currentConversationId
      || ''
  ).trim();
}

function getMaskEndpoint(messageDiv, messageId) {
  const conversationId = getMaskConversationId(messageDiv);
  const encodedMessageId = encodeURIComponent(messageId);
  if (conversationId && window.chatCollaboration?.isCollaborationConversation?.(conversationId)) {
    return `/api/collaboration/conversations/${encodeURIComponent(conversationId)}/messages/${encodedMessageId}/mask`;
  }
  return `/api/message/${encodedMessageId}/mask`;
}

function buildMaskPayload(messageDiv, action, selectionInfo = null) {
  const payload = {
    action,
    conversation_id: getMaskConversationId(messageDiv),
  };
  if (selectionInfo) {
    payload.selection = {
      start: selectionInfo.start,
      end: selectionInfo.end,
      text: selectionInfo.text,
      display_start: selectionInfo.start,
      display_end: selectionInfo.end,
      display_text: selectionInfo.text,
    };
  }
  return payload;
}

async function sendMaskRequest(messageDiv, action, selectionInfo = null) {
  const messageId = String(messageDiv?.getAttribute('data-message-id') || '').trim();
  if (!messageId) {
    throw new Error('Message id is missing');
  }

  const response = await fetch(getMaskEndpoint(messageDiv, messageId), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(buildMaskPayload(messageDiv, action, selectionInfo)),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || 'Failed to update message mask');
  }
  return data;
}

function getMetadataFromMaskResponse(messageDiv, data) {
  return {
    ...(messageDiv._maskingMetadata || {}),
    ...(data?.message?.metadata || {}),
    masked: Boolean(data?.masked),
    masked_ranges: Array.isArray(data?.masked_ranges) ? data.masked_ranges : [],
  };
}

async function handleMaskAddButtonClick(messageDiv) {
  const selectionInfo = getSelectionInfoForMessage(messageDiv);
  const action = selectionInfo ? 'mask_selection' : 'mask_all';

  try {
    const data = await sendMaskRequest(messageDiv, action, selectionInfo);
    applyMaskedState(messageDiv, getMetadataFromMaskResponse(messageDiv, data));
    selectionInfo?.selection?.removeAllRanges();
    showToast(selectionInfo ? 'Selection masked successfully' : 'Message masked successfully', 'success');
  } catch (error) {
    console.error('Error updating message mask:', error);
    showToast(error.message || 'Error updating message mask', 'error');
  }
}

async function handleMaskRemoveButtonClick(messageDiv) {
  const maskState = getMaskStateFromMetadata(messageDiv._maskingMetadata || {});
  if (!maskState.hasAnyMask) {
    updateMaskControls(messageDiv, messageDiv._maskingMetadata || {});
    return;
  }

  const action = maskState.fullyMasked ? 'unmask_message' : 'clear_all_masks';
  try {
    const data = await sendMaskRequest(messageDiv, action);
    applyMaskedState(messageDiv, getMetadataFromMaskResponse(messageDiv, data));
    const toastMessage = maskState.fullyMasked && maskState.hasRanges
      ? 'Full-message mask removed; text masks remain'
      : 'Message masks removed successfully';
    showToast(toastMessage, 'success');
  } catch (error) {
    console.error('Error removing message mask:', error);
    showToast(error.message || 'Error removing message mask', 'error');
  }
}

function attachMaskButtonEventListeners(messageDiv) {
  const addButton = messageDiv.querySelector('.mask-add-btn');
  const removeButton = messageDiv.querySelector('.mask-remove-btn');

  if (addButton && !addButton.dataset.maskListenerAttached) {
    addButton.dataset.maskListenerAttached = 'true';
    addButton.addEventListener('mouseenter', () => {
      updateMaskControls(messageDiv, messageDiv._maskingMetadata || {});
    });
    addButton.addEventListener('click', () => {
      handleMaskAddButtonClick(messageDiv);
    });
  }

  if (removeButton && !removeButton.dataset.maskListenerAttached) {
    removeButton.dataset.maskListenerAttached = 'true';
    removeButton.addEventListener('mouseenter', () => {
      updateMaskControls(messageDiv, messageDiv._maskingMetadata || {});
    });
    removeButton.addEventListener('click', () => {
      handleMaskRemoveButtonClick(messageDiv);
    });
  }
}

// ============= Message Deletion Functions =============

/**
 * Handle delete button click - shows confirmation modal
 */
function handleDeleteButtonClick(messageDiv, messageId, messageType) {
  console.log(`Delete button clicked for ${messageType} message: ${messageId}`);

  const conversationId = window.chatConversations?.getCurrentConversationId?.() || window.currentConversationId || '';
  const isCollaborativeConversation = Boolean(
    conversationId && window.chatCollaboration?.isCollaborationConversation?.(conversationId)
  );

  // Store message info for deletion confirmation
  window.pendingMessageDeletion = {
    messageDiv,
    messageId,
    messageType,
    conversationId,
    isCollaborativeConversation,
  };

  // Show appropriate confirmation modal
  if (messageType === 'user' && !isCollaborativeConversation) {
    // User message - offer thread deletion option
    const modal = document.getElementById('delete-message-modal');
    if (modal) {
      const bsModal = new bootstrap.Modal(modal);
      bsModal.show();
    }
  } else {
    // AI, image, or file message - single confirmation
    const modal = document.getElementById('delete-single-message-modal');
    if (modal) {
      // Update modal text based on message type
      const modalBody = modal.querySelector('.modal-body p');
      if (modalBody) {
        if (isCollaborativeConversation && messageType === 'user') {
          modalBody.textContent = 'Are you sure you want to delete this shared message? This action cannot be undone.';
        } else if (messageType === 'assistant') {
          modalBody.textContent = 'Are you sure you want to delete this AI response? This action cannot be undone.';
        } else if (messageType === 'image') {
          modalBody.textContent = 'Are you sure you want to delete this image? This action cannot be undone.';
        } else if (messageType === 'file') {
          modalBody.textContent = 'Are you sure you want to delete this file? This action cannot be undone.';
        }
      }
      const bsModal = new bootstrap.Modal(modal);
      bsModal.show();
    }
  }
}

/**
 * Execute message deletion via API
 */
function executeMessageDeletion(deleteThread = false) {
  const pendingDeletion = window.pendingMessageDeletion;
  if (!pendingDeletion) {
    console.error('No pending message deletion');
    return;
  }

  const {
    messageDiv,
    messageId,
    messageType,
    conversationId,
    isCollaborativeConversation,
  } = pendingDeletion;
  const shouldDeleteThread = Boolean(deleteThread && !isCollaborativeConversation);
  const deleteEndpoint = isCollaborativeConversation && conversationId
    ? `/api/collaboration/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}`
    : `/api/message/${encodeURIComponent(messageId)}`;

  console.log(`Executing deletion for message ${messageId}, deleteThread: ${shouldDeleteThread}`);
  console.log(`Message div:`, messageDiv);
  console.log(`Message ID from DOM:`, messageDiv ? messageDiv.getAttribute('data-message-id') : 'N/A');
  console.log(`Delete endpoint:`, deleteEndpoint);

  // Call delete API
  fetch(deleteEndpoint, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      delete_thread: shouldDeleteThread
    })
  })
  .then(response => {
    if (!response.ok) {
      return response.json().then(data => {
        const errorMsg = data.error || 'Failed to delete message';
        console.error(`Delete API error (${response.status}):`, errorMsg);
        console.error(`Failed message ID:`, messageId);

        // Add specific error message for 404
        if (response.status === 404) {
          throw new Error(`Message not found in database. This may happen if the message was just created and hasn't fully synced yet. Try refreshing the page and deleting again.`);
        }
        throw new Error(errorMsg);
      }).catch(jsonError => {
        // If response.json() fails, throw a generic error
        if (response.status === 404) {
          throw new Error(`Message not found in database. Message ID: ${messageId}. Try refreshing the page.`);
        }
        throw new Error(`Failed to delete message (status ${response.status})`);
      });
    }
    return response.json();
  })
  .then(data => {
    console.log('Delete API response:', data);

    if (data.success) {
      // Remove message(s) from DOM
      const deletedIds = data.deleted_message_ids || [messageId];
      deletedIds.forEach(id => {
        const msgDiv = document.querySelector(`[data-message-id="${id}"]`);
        if (msgDiv) {
          msgDiv.remove();
          console.log(`Removed message ${id} from DOM`);
        }
      });

      // Show success message
      const archiveMsg = data.archived ? ' (archived)' : '';
      const countMsg = deletedIds.length > 1 ? `${deletedIds.length} messages` : 'Message';
      showToast(`${countMsg} deleted successfully${archiveMsg}`, 'success');

      // Clean up pending deletion
      delete window.pendingMessageDeletion;

      // Optionally reload conversation list to update preview
      if (typeof loadConversations === 'function') {
        loadConversations();
      }
    } else {
      showToast('Failed to delete message', 'error');
    }
  })
  .catch(error => {
    console.error('Error deleting message:', error);

    // If we got a 404, suggest reloading messages
    if (error.message && error.message.includes('not found')) {
      showToast(error.message + ' Click here to reload messages.', 'error', 8000, () => {
        // Reload messages when toast is clicked
        if (window.currentConversationId) {
          loadMessages(window.currentConversationId);
        }
      });
    } else {
      showToast(error.message || 'Failed to delete message', 'error');
    }

    // Clean up pending deletion
    delete window.pendingMessageDeletion;
  });
}

// Expose functions globally
window.chatMessages = {
  applyMaskedState,
  applySearchHighlight,
  appendMessage,
  clearSearchHighlight,
  extractSuggestedFollowUpPrompts,
  scrollToMessageSmooth
};

// Expose deletion function globally for modal buttons
window.executeMessageDeletion = executeMessageDeletion;
