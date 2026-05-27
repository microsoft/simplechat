// chat-input-actions.js

import { showToast } from "./chat-toast.js";
import {
  createNewConversation,
  loadConversations,
} from "./chat-conversations.js";
import {
  showFileUploadingMessage,
  hideFileUploadingMessage,
  showLoadingIndicator,
  hideLoadingIndicator,
} from "./chat-loading-indicator.js";
import { loadMessages } from "./chat-messages.js";
import { loadUserSettings, saveUserSetting } from "./chat-layout.js";

const imageGenBtn = document.getElementById("image-generate-btn");
const webSearchBtn = document.getElementById("search-web-btn");
const urlAccessBtn = document.getElementById("url-access-btn");
const sourceReviewBtn = document.getElementById("source-review-btn");
const chooseFileBtn = document.getElementById("choose-file-btn");
const fileInputEl = document.getElementById("file-input");
const uploadBtn = document.getElementById("upload-btn");
const cancelFileSelection = document.getElementById("cancel-file-selection");
const userInputEl = document.getElementById("user-input");
const chatDropZoneEl = document.querySelector(".chat-input-container");
const webSearchNoticeContainer = document.getElementById("web-search-notice-container");
const webSearchNoticeDismiss = document.getElementById("web-search-notice-dismiss");
const httpUrlPattern = /https?:\/\/[^\s<>'"]+/gi;
const DEEP_RESEARCH_DEFAULT_SETTING_KEY = "deepResearchDefaultEnabled";
const DEEP_RESEARCH_DEFAULT_STORAGE_KEY = "simplechat.deepResearchDefaultEnabled";
const WEB_SEARCH_NOTICE_SESSION_KEY = "webSearchNoticeDismissed";

let deepResearchDefaultEnabled = false;
let deepResearchDefaultPreferenceDirty = false;

function getPromptUrls() {
  if (!userInputEl) {
    return [];
  }

  const matches = String(userInputEl.value || "").match(httpUrlPattern) || [];
  return [...new Set(matches.map((url) => url.replace(/[.,);\]}>]+$/, "")))]
    .filter(Boolean);
}

function isToggleButtonActive(button) {
  return Boolean(button?.classList.contains("active"));
}

function setToggleButtonActive(button, isActive) {
  if (!button) {
    return;
  }

  button.classList.toggle("active", Boolean(isActive));
  button.setAttribute("aria-pressed", isActive ? "true" : "false");
}

function isChatFileUploadEnabled() {
  return Boolean(window.appSettings?.enable_chat_file_uploads);
}

function showChatFileUploadDisabledToast() {
  showToast("Chat file uploads are not enabled for your account.", "warning");
}

function parseBooleanPreference(value) {
  return value === true || String(value).toLowerCase() === "true";
}

function readDeepResearchDefaultFromStorage() {
  try {
    const storedValue = window.localStorage?.getItem(DEEP_RESEARCH_DEFAULT_STORAGE_KEY);
    if (storedValue === null || storedValue === undefined) {
      return null;
    }
    return parseBooleanPreference(storedValue);
  } catch (error) {
    return null;
  }
}

function storeDeepResearchDefaultLocally(isEnabled) {
  try {
    window.localStorage?.setItem(DEEP_RESEARCH_DEFAULT_STORAGE_KEY, isEnabled ? "true" : "false");
  } catch (error) {
    // Ignore storage failures; server-side user settings remain the source of truth.
  }
}

function setDeepResearchDefaultPreference(isEnabled, options = {}) {
  const { persist = true, syncVisibleButton = false } = options;
  deepResearchDefaultEnabled = Boolean(isEnabled);
  storeDeepResearchDefaultLocally(deepResearchDefaultEnabled);

  if (persist) {
    deepResearchDefaultPreferenceDirty = true;
    saveUserSetting({ [DEEP_RESEARCH_DEFAULT_SETTING_KEY]: deepResearchDefaultEnabled });
  }

  if (syncVisibleButton) {
    updateDeepResearchAvailability();
    if (!deepResearchDefaultEnabled) {
      setToggleButtonActive(sourceReviewBtn, false);
    }
  }
}

function initializeDeepResearchDefaultPreference() {
  const storedPreference = readDeepResearchDefaultFromStorage();
  if (storedPreference !== null) {
    setDeepResearchDefaultPreference(storedPreference, { persist: false });
  }

  loadUserSettings()
    .then((settings) => {
      if (deepResearchDefaultPreferenceDirty) {
        return;
      }

      if (!Object.prototype.hasOwnProperty.call(settings || {}, DEEP_RESEARCH_DEFAULT_SETTING_KEY)) {
        return;
      }

      setDeepResearchDefaultPreference(
        parseBooleanPreference(settings[DEEP_RESEARCH_DEFAULT_SETTING_KEY]),
        { persist: false, syncVisibleButton: true }
      );
    })
    .catch((error) => {
      console.warn("Unable to load Deep Research default preference:", error);
    });
}

function isWebSearchNoticeDismissed() {
  return sessionStorage.getItem(WEB_SEARCH_NOTICE_SESSION_KEY) === "true";
}

function updateWebSearchNotice(isActive) {
  if (!webSearchNoticeContainer || !window.appSettings?.enable_web_search_user_notice) {
    return;
  }

  const shouldShowNotice = Boolean(isActive) && !isWebSearchNoticeDismissed();
  webSearchNoticeContainer.classList.toggle("d-none", !shouldShowNotice);
}

export function resetContextualSourceActionState(event = null) {
  const detail = event?.detail || {};
  if (detail.preserveSelections) {
    return;
  }

  resetImageGenerationActionState();
  setToggleButtonActive(webSearchBtn, false);
  setToggleButtonActive(urlAccessBtn, false);
  setToggleButtonActive(sourceReviewBtn, false);
  resetFileButton();
  updateWebSearchNotice(false);
  updateUrlAccessAvailability({
    includeDefaultUrlPrompt: false,
    restoreDeepResearchDefault: false,
  });
}

function updateDeepResearchAvailability(options = {}) {
  if (!sourceReviewBtn) {
    return;
  }

  const {
    includeDefaultUrlPrompt = true,
    restoreDeepResearchDefault = true,
  } = options;

  const webSearchActive = isToggleButtonActive(webSearchBtn);
  const urlAccessActive = isToggleButtonActive(urlAccessBtn);
  const promptUrls = getPromptUrls();
  const shouldShow = webSearchActive
    || (urlAccessActive && promptUrls.length > 0)
    || (includeDefaultUrlPrompt && deepResearchDefaultEnabled && promptUrls.length > 0);

  sourceReviewBtn.classList.toggle("d-none", !shouldShow);
  sourceReviewBtn.setAttribute("aria-hidden", shouldShow ? "false" : "true");
  sourceReviewBtn.disabled = !shouldShow || sourceReviewBtn.dataset.disabledByImageGeneration === "true";

  if (!shouldShow || sourceReviewBtn.disabled) {
    setToggleButtonActive(sourceReviewBtn, false);
    return;
  }

  if (restoreDeepResearchDefault && deepResearchDefaultEnabled) {
    setToggleButtonActive(sourceReviewBtn, true);
  }
}

function updateUrlAccessAvailability(options = {}) {
  if (!urlAccessBtn) {
    updateDeepResearchAvailability(options);
    return;
  }

  const promptUrls = getPromptUrls();
  const shouldShow = Boolean(window.appSettings?.enable_url_access) && promptUrls.length > 0;
  urlAccessBtn.classList.toggle("d-none", !shouldShow);
  urlAccessBtn.setAttribute("aria-hidden", shouldShow ? "false" : "true");
  urlAccessBtn.disabled = !shouldShow || urlAccessBtn.dataset.disabledByImageGeneration === "true";

  if (!shouldShow) {
    setToggleButtonActive(urlAccessBtn, false);
  }
  updateDeepResearchAvailability(options);
}

window.addEventListener("chat:conversation-context-changed", resetContextualSourceActionState);

const clipboardMimeExtensionMap = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/jpg": "jpg",
  "image/gif": "gif",
  "image/webp": "webp",
  "image/bmp": "bmp",
  "image/tiff": "tiff",
  "image/heif": "heif",
  "application/pdf": "pdf",
  "text/plain": "txt",
  "text/markdown": "md",
  "application/json": "json",
  "text/csv": "csv",
  "application/xml": "xml",
  "text/xml": "xml",
  "application/yaml": "yaml",
  "text/yaml": "yaml",
};

export function resetFileButton() {
  const fileInputEl = document.getElementById("file-input");
  const fileBtn = document.getElementById("choose-file-btn");
  const uploadBtn = document.getElementById("upload-btn");
  const cancelFileSelection = document.getElementById("cancel-file-selection");

  if (fileInputEl) {
    fileInputEl.value = "";
  }

  if (fileBtn) {
    fileBtn.classList.remove("active");
    const fileBtnText = fileBtn.querySelector(".file-btn-text");
    if (fileBtnText) {
      fileBtnText.textContent = "File";
    }
  }

  if (uploadBtn) {
    uploadBtn.style.display = "none";
  }

  if (cancelFileSelection) {
    cancelFileSelection.style.display = "none";
  }
}

function inferExtensionFromMimeType(mimeType) {
  const normalizedMimeType = String(mimeType || "").trim().toLowerCase();
  if (!normalizedMimeType) {
    return "bin";
  }

  if (clipboardMimeExtensionMap[normalizedMimeType]) {
    return clipboardMimeExtensionMap[normalizedMimeType];
  }

  const mimeSegments = normalizedMimeType.split("/");
  const subtype = mimeSegments.length > 1 ? mimeSegments[1] : "";
  const sanitizedSubtype = subtype.split("+")[0].split(";")[0].trim();
  return sanitizedSubtype || "bin";
}

function normalizeUploadFile(file, fallbackPrefix = "clipboard_upload") {
  if (!(file instanceof File)) {
    return null;
  }

  const currentName = String(file.name || "").trim();
  if (currentName) {
    return file;
  }

  const extension = inferExtensionFromMimeType(file.type);
  const normalizedName = `${fallbackPrefix}_${Date.now()}.${extension}`;
  return new File([file], normalizedName, {
    type: file.type || "application/octet-stream",
    lastModified: file.lastModified || Date.now(),
  });
}

function buildUploadFileList(filesLike, fallbackPrefix = "clipboard_upload") {
  return Array.from(filesLike || [])
    .map((file) => normalizeUploadFile(file, fallbackPrefix))
    .filter(Boolean);
}

function hasNamedFile(files) {
  return Array.from(files || []).some((file) => String(file?.name || "").trim());
}

function uploadFilesInSequence(files) {
  return files.reduce((uploadChain, file) => {
    return uploadChain.then(() => uploadFileToConversation(file));
  }, Promise.resolve());
}

function beginChatFileUpload(filesLike, options = {}) {
  const { fallbackPrefix = "clipboard_upload" } = options;
  const uploadFiles = buildUploadFileList(filesLike, fallbackPrefix);

  if (uploadFiles.length === 0) {
    return Promise.resolve(false);
  }

  if (!isChatFileUploadEnabled()) {
    showChatFileUploadDisabledToast();
    resetFileButton();
    return Promise.resolve(false);
  }

  const doUpload = () => {
    if (!currentConversationId) {
      return createNewConversation(() => {
        uploadFilesInSequence(uploadFiles);
      }, { preserveSelections: true });
    }

    return uploadFilesInSequence(uploadFiles);
  };

  if (window.UserAgreementManager) {
    return Promise.resolve(
      window.UserAgreementManager.checkBeforeUpload(
        uploadFiles,
        "chat",
        "default",
        function () {
          doUpload();
        }
      )
    );
  }

  return Promise.resolve(doUpload());
}

function getClipboardFiles(clipboardData) {
  if (!clipboardData) {
    return [];
  }

  const clipboardFiles = [];
  const clipboardItems = Array.from(clipboardData.items || []);

  clipboardItems.forEach((item) => {
    if (item?.kind !== "file" || typeof item.getAsFile !== "function") {
      return;
    }

    const file = item.getAsFile();
    if (file) {
      clipboardFiles.push(file);
    }
  });

  if (clipboardFiles.length > 0) {
    if (clipboardHasPlainText(clipboardData) && !hasNamedFile(clipboardFiles)) {
      return [];
    }

    return clipboardFiles;
  }

  const fileList = Array.from(clipboardData.files || []);
  if (clipboardHasPlainText(clipboardData) && !hasNamedFile(fileList)) {
    return [];
  }

  return fileList;
}

function clipboardHasPlainText(clipboardData) {
  if (!clipboardData || typeof clipboardData.getData !== "function") {
    return false;
  }

  try {
    return String(clipboardData.getData("text/plain") || clipboardData.getData("Text") || "").trim().length > 0;
  } catch (error) {
    console.debug("Unable to inspect clipboard text data", error);
    return false;
  }
}

function hasFileTransfer(dataTransfer) {
  if (!dataTransfer) {
    return false;
  }

  const transferTypes = Array.from(dataTransfer.types || []);
  if (transferTypes.includes("Files")) {
    return true;
  }

  return Array.from(dataTransfer.items || []).some((item) => item?.kind === "file")
    || (dataTransfer.files && dataTransfer.files.length > 0);
}

function getDataTransferFiles(dataTransfer) {
  if (!dataTransfer) {
    return [];
  }

  const transferFiles = [];
  Array.from(dataTransfer.items || []).forEach((item) => {
    if (item?.kind !== "file" || typeof item.getAsFile !== "function") {
      return;
    }

    const file = item.getAsFile();
    if (file) {
      transferFiles.push(file);
    }
  });

  if (transferFiles.length > 0) {
    return transferFiles;
  }

  return Array.from(dataTransfer.files || []);
}

function setChatDropActive(isActive) {
  if (!chatDropZoneEl) {
    return;
  }

  chatDropZoneEl.classList.toggle("chat-input-drag-active", isActive);
}

export function uploadFileToConversation(file) {
  const uploadingIndicatorEl = showFileUploadingMessage();
  
  // Update the file button to show "Uploading..." state
  const fileBtn = document.getElementById("choose-file-btn");
  if (fileBtn) {
    const fileBtnText = fileBtn.querySelector(".file-btn-text");
    if (fileBtnText) {
      fileBtnText.textContent = "Uploading...";
    }
  }

  const formData = new FormData();
  formData.append("file", file);
  formData.append("conversation_id", currentConversationId);

  return fetch("/upload", {
    method: "POST",
    body: formData,
  })
    .then((response) => {
      hideFileUploadingMessage(uploadingIndicatorEl);

      let clonedResponse = response.clone();
      return response.json().then((data) => {
        if (!response.ok) {
          console.error("Upload failed:", data.error || "Unknown error");
          showToast(
            "Error uploading file: " + (data.error || "Unknown error"),
            "danger"
          );
          throw new Error(data.error || "Upload failed");
        }
        return data;
      });
    })
    .then((data) => {
      if (data.conversation_id) {
        currentConversationId = data.conversation_id;
        
        // If a title was returned and it's different from "New Conversation",
        // update the conversation title in the UI
        if (data.title && data.title !== "New Conversation") {
          const currentConversationTitleEl = document.getElementById("current-conversation-title");
          if (currentConversationTitleEl) {
            currentConversationTitleEl.textContent = data.title;
          }
        }
        
        loadMessages(currentConversationId);
        loadConversations();
      } else {
        console.error("No conversation_id returned from server.");
        showToast("Error: No conversation ID returned from server.", "danger");
      }
      resetFileButton();
    })
    .catch((error) => {
      console.error("Error:", error);
      showToast("Error uploading file: " + error.message, "danger");
      resetFileButton();
      hideFileUploadingMessage(uploadingIndicatorEl);
    });
}

export function fetchFileContent(conversationId, fileId) {
  showLoadingIndicator();
  fetch("/api/get_file_content", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: conversationId,
      file_id: fileId,
    }),
  })
    .then((response) => response.json())
    .then((data) => {
      hideLoadingIndicator();

      if (data.file_content && data.filename) {
        showFileContentPopup(data.file_content, data.filename, data.is_table, data.file_content_source, conversationId, fileId);
      } else if (data.error) {
        showToast(data.error, "danger");
      } else {
        showToast("Unexpected response from server.", "danger");
      }
    })
    .catch((error) => {
      hideLoadingIndicator();
      console.error("Error fetching file content:", error);
      showToast("Error fetching file content.", "danger");
    });
}

export function showFileContentPopup(fileContent, filename, isTable, fileContentSource, conversationId, fileId) {
  let modalContainer = document.getElementById("file-modal");
  if (!modalContainer) {
    modalContainer = document.createElement("div");
    modalContainer.id = "file-modal";
    modalContainer.classList.add("modal", "fade");
    modalContainer.tabIndex = -1;
    modalContainer.setAttribute("aria-hidden", "true");

    modalContainer.innerHTML = `
      <div class="modal-dialog modal-dialog-scrollable modal-xl modal-fullscreen-sm-down">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title"></h5>
            <div class="ms-auto me-2" id="file-modal-download-btn-container"></div>
            <button
              type="button"
              class="btn-close"
              data-bs-dismiss="modal"
              aria-label="Close"
            ></button>
          </div>
          <div class="modal-body">
            <div id="file-content"></div>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modalContainer);
  }

  const modalTitle = modalContainer.querySelector(".modal-title");
  if (modalTitle) {
    modalTitle.textContent = `Uploaded File: ${filename}`;
  }

  // Add or remove download button for blob-stored files
  const downloadBtnContainer = document.getElementById("file-modal-download-btn-container");
  if (downloadBtnContainer) {
    downloadBtnContainer.replaceChildren();

    if (fileContentSource === 'blob' && conversationId && fileId) {
      const downloadLink = document.createElement("a");
      downloadLink.href = `/api/enhanced_citations/tabular?conversation_id=${encodeURIComponent(conversationId)}&file_id=${encodeURIComponent(fileId)}`;
      downloadLink.className = "btn btn-sm btn-outline-primary";
      downloadLink.setAttribute("download", "");

      const downloadIcon = document.createElement("i");
      downloadIcon.className = "bi bi-download me-1";

      downloadLink.appendChild(downloadIcon);
      downloadLink.appendChild(document.createTextNode("Download Original"));
      downloadBtnContainer.appendChild(downloadLink);
    }
  }

  const fileContentElement = document.getElementById("file-content");
  if (!fileContentElement) return;

  fileContentElement.replaceChildren();

  if (isTable) {
    const trimmedContent = String(fileContent ?? "").trim();
    const isLegacyHtmlTableContent = /^<table[\s\S]*<\/table>$/i.test(trimmedContent);

    if (isLegacyHtmlTableContent) {
      renderPreformattedText(fileContentElement, fileContent);
    } else {
      const tableWrapper = buildCsvTableElement(fileContent);

      if (tableWrapper) {
        fileContentElement.appendChild(tableWrapper);
      } else {
        const emptyState = document.createElement("p");
        emptyState.textContent = "No data available";
        fileContentElement.appendChild(emptyState);
      }
    }

    // Apply DataTable after content is set
    $(document).ready(function () {
      const table = $("#file-content table");
      if (table.length > 0) {
        table.DataTable({
          responsive: true,
          scrollX: true,
          destroy: true // Allow re-initialization
        });
      }
    });
  } else {
    renderPreformattedText(fileContentElement, fileContent);
  }

  const modal = new bootstrap.Modal(modalContainer);
  modal.show();
}

function buildCsvTableElement(fileContent) {
  const csvLines = String(fileContent ?? "")
    .trim()
    .split(/\r?\n/)
    .filter((line) => line.trim());

  if (csvLines.length === 0) {
    return null;
  }

  const headers = parseCSVLine(csvLines[0]);
  const headerCount = headers.length;
  const rows = csvLines.slice(1);

  const tableWrapper = document.createElement("div");
  tableWrapper.className = "table-responsive";

  const table = document.createElement("table");
  table.className = "table table-striped table-bordered";

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  headers.forEach((header) => {
    const headerCell = document.createElement("th");
    headerCell.textContent = header;
    headerRow.appendChild(headerCell);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const cells = parseCSVLine(row);
    while (cells.length < headerCount) {
      cells.push("");
    }
    if (cells.length > headerCount) {
      cells.splice(headerCount);
    }

    const rowElement = document.createElement("tr");
    cells.forEach((cell) => {
      const cellElement = document.createElement("td");
      cellElement.textContent = cell;
      rowElement.appendChild(cellElement);
    });
    tbody.appendChild(rowElement);
  });
  table.appendChild(tbody);

  tableWrapper.appendChild(table);
  return tableWrapper;
}

function parseCSVLine(line) {
  const result = [];
  let current = "";
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const nextChar = line[index + 1];

    if (char === '"') {
      if (inQuotes && nextChar === '"') {
        current += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === "," && !inQuotes) {
      result.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }

  result.push(current.trim());
  return result;
}

function renderPreformattedText(container, text) {
  const pre = document.createElement("pre");
  pre.style.whiteSpace = "pre-wrap";
  pre.textContent = String(text ?? "");
  container.replaceChildren(pre);
}

export function getUrlParameter(name) {
  name = name.replace(/[\[]/, "\\[").replace(/[\]]/, "\\]");
  const regex = new RegExp("[\\?&]" + name + "=([^&#]*)");
  const results = regex.exec(location.search);
  return results === null
    ? ""
    : decodeURIComponent(results[1].replace(/\+/g, " "));
}

document.addEventListener("DOMContentLoaded", function () {
  const tooltipTriggerList = [].slice.call(
    document.querySelectorAll('[data-bs-toggle="tooltip"]')
  );
  tooltipTriggerList.forEach(function (tooltipTriggerEl) {
    new bootstrap.Tooltip(tooltipTriggerEl);
  });
});

function syncImageGenerationDependentControls(isImageGenEnabled) {
  const docBtn = document.getElementById("search-documents-btn");
  const webBtn = document.getElementById("search-web-btn");
  const urlBtn = document.getElementById("url-access-btn");
  const sourcesBtn = document.getElementById("source-review-btn");
  const fileBtn = document.getElementById("choose-file-btn");
  const modelSelectContainer = document.getElementById("model-select-container");

  if (isImageGenEnabled) {
    if (docBtn) {
      docBtn.disabled = true;
      docBtn.classList.remove("active");
    }
    if (webBtn) {
      webBtn.disabled = true;
      setToggleButtonActive(webBtn, false);
    }
    if (urlBtn) {
      urlBtn.dataset.disabledByImageGeneration = "true";
      urlBtn.disabled = true;
      setToggleButtonActive(urlBtn, false);
    }
    if (sourcesBtn) {
      sourcesBtn.dataset.disabledByImageGeneration = "true";
      sourcesBtn.disabled = true;
      setToggleButtonActive(sourcesBtn, false);
    }
    if (fileBtn) {
      fileBtn.disabled = true;
      fileBtn.classList.remove("active");
    }
    if (modelSelectContainer) {
      modelSelectContainer.classList.add("d-none");
    }
  } else {
    if (docBtn) docBtn.disabled = false;
    if (webBtn) webBtn.disabled = false;
    if (urlBtn) {
      urlBtn.dataset.disabledByImageGeneration = "false";
      updateUrlAccessAvailability();
    }
    if (sourcesBtn) {
      sourcesBtn.dataset.disabledByImageGeneration = "false";
      updateDeepResearchAvailability();
    }
    if (fileBtn) fileBtn.disabled = false;
    if (modelSelectContainer) {
      modelSelectContainer.classList.remove("d-none");
    }
  }
}

function resetImageGenerationActionState() {
  if (!imageGenBtn) {
    return;
  }

  imageGenBtn.classList.remove("active");
  syncImageGenerationDependentControls(false);
}

if (imageGenBtn) {
  imageGenBtn.addEventListener("click", function () {
    this.classList.toggle("active");
    syncImageGenerationDependentControls(this.classList.contains("active"));
  });
}

if (webSearchNoticeDismiss) {
  webSearchNoticeDismiss.addEventListener("click", function() {
    sessionStorage.setItem(WEB_SEARCH_NOTICE_SESSION_KEY, "true");
    updateWebSearchNotice(false);
  });
}

if (webSearchBtn) {
  if (webSearchNoticeContainer) {
    updateWebSearchNotice(false);
  }

  webSearchBtn.addEventListener("click", function () {
    setToggleButtonActive(this, !isToggleButtonActive(this));
    const isActive = isToggleButtonActive(this);
    updateWebSearchNotice(isActive);
    updateUrlAccessAvailability();
  });
}

if (urlAccessBtn) {
  urlAccessBtn.addEventListener("click", function () {
    if (this.classList.contains("d-none") || this.disabled) {
      return;
    }
    setToggleButtonActive(this, !isToggleButtonActive(this));
    const maxChatUrls = Number.parseInt(window.appSettings?.url_access_max_chat_urls_per_turn || "10", 10);
    const promptUrlCount = getPromptUrls().length;
    if (isToggleButtonActive(this) && promptUrlCount > maxChatUrls) {
      showToast(`URL Access supports up to ${maxChatUrls} URL(s) in this message.`, "warning");
    }
    updateDeepResearchAvailability();
  });
  updateUrlAccessAvailability();
}

if (sourceReviewBtn) {
  initializeDeepResearchDefaultPreference();

  sourceReviewBtn.addEventListener("click", function () {
    if (this.classList.contains("d-none") || this.disabled) {
      return;
    }
    setToggleButtonActive(this, !isToggleButtonActive(this));
    setDeepResearchDefaultPreference(isToggleButtonActive(this));
    const maxUserUrls = Number.parseInt(window.appSettings?.url_access_max_chat_urls_per_turn || window.appSettings?.deep_research_max_user_urls_per_turn || "10", 10);
    const promptUrlCount = getPromptUrls().length;
    if (isToggleButtonActive(this) && promptUrlCount > maxUserUrls) {
      showToast(`Deep Research supports up to ${maxUserUrls} direct URL(s) from this message.`, "info");
    }
  });
  updateDeepResearchAvailability();
}

if (chooseFileBtn) {
  chooseFileBtn.addEventListener("click", function () {
    const fileInput = document.getElementById("file-input");
    if (fileInput) fileInput.click();
  });
}

if (fileInputEl) {
  fileInputEl.addEventListener("change", function () {
    const file = fileInputEl.files[0];
    const fileBtn = document.getElementById("choose-file-btn");
    const uploadBtn = document.getElementById("upload-btn");
    if (!fileBtn || !uploadBtn) return;

    if (!isChatFileUploadEnabled()) {
      showChatFileUploadDisabledToast();
      resetFileButton();
      return;
    }

    if (file) {
      fileBtn.classList.add("active");
      fileBtn.querySelector(".file-btn-text").textContent = file.name;
      cancelFileSelection.style.display = "inline";
      
      // Hide the upload button since we're auto-uploading
      uploadBtn.style.display = "none";

      beginChatFileUpload([file], { fallbackPrefix: "chat_upload" });
    } else {
      resetFileButton();
    }
  });
}

if (cancelFileSelection) {
  // Prevent the click from also triggering the "choose file" flow.
  cancelFileSelection.addEventListener("click", (event) => {
    event.stopPropagation();
    resetFileButton();
  });
}

if (uploadBtn) {
  uploadBtn.addEventListener("click", () => {
    const fileInput = document.getElementById("file-input");
    if (!fileInput) return;

    const file = fileInput.files[0];
    if (!file) {
      showToast("Please select a file to upload.", "danger");
      return;
    }

    beginChatFileUpload([file], { fallbackPrefix: "chat_upload" });
  });
}

if (userInputEl) {
  userInputEl.addEventListener("input", updateUrlAccessAvailability);

  userInputEl.addEventListener("paste", (event) => {
    setTimeout(updateUrlAccessAvailability, 0);
    const clipboardFiles = getClipboardFiles(event.clipboardData);
    if (clipboardFiles.length === 0) {
      return;
    }

    event.preventDefault();
    beginChatFileUpload(clipboardFiles, { fallbackPrefix: "pasted_file" });
  });
}

if (chatDropZoneEl) {
  ["dragenter", "dragover"].forEach((eventName) => {
    chatDropZoneEl.addEventListener(eventName, (event) => {
      if (!hasFileTransfer(event.dataTransfer)) {
        return;
      }

      event.preventDefault();
      if (!isChatFileUploadEnabled()) {
        if (event.dataTransfer) {
          event.dataTransfer.dropEffect = "none";
        }
        setChatDropActive(false);
        return;
      }

      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = "copy";
      }
      setChatDropActive(true);
    });
  });

  chatDropZoneEl.addEventListener("dragleave", (event) => {
    if (event.relatedTarget && chatDropZoneEl.contains(event.relatedTarget)) {
      return;
    }

    setChatDropActive(false);
  });

  chatDropZoneEl.addEventListener("drop", (event) => {
    if (!hasFileTransfer(event.dataTransfer)) {
      return;
    }

    event.preventDefault();
    setChatDropActive(false);

    if (!isChatFileUploadEnabled()) {
      showChatFileUploadDisabledToast();
      return;
    }

    const droppedFiles = getDataTransferFiles(event.dataTransfer);
    beginChatFileUpload(droppedFiles, { fallbackPrefix: "dropped_file" });
  });
}
