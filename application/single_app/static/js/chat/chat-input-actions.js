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

const imageGenBtn = document.getElementById("image-generate-btn");
const webSearchBtn = document.getElementById("search-web-btn");
const chooseFileBtn = document.getElementById("choose-file-btn");
const fileInputEl = document.getElementById("file-input");
const uploadBtn = document.getElementById("upload-btn");
const cancelFileSelection = document.getElementById("cancel-file-selection");

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

  fetch("/upload", {
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

if (imageGenBtn) {
  imageGenBtn.addEventListener("click", function () {
    this.classList.toggle("active");

    const isImageGenEnabled = this.classList.contains("active");
    const docBtn = document.getElementById("search-documents-btn");
    const webBtn = document.getElementById("search-web-btn");
    const fileBtn = document.getElementById("choose-file-btn");
    const modelSelectContainer = document.getElementById("model-select-container");

    if (isImageGenEnabled) {
      if (docBtn) {
        docBtn.disabled = true;
        docBtn.classList.remove("active");
      }
      if (webBtn) {
        webBtn.disabled = true;
        webBtn.classList.remove("active");
      }
      if (fileBtn) {
        fileBtn.disabled = true;
        fileBtn.classList.remove("active");
      }
      if (modelSelectContainer) {
        modelSelectContainer.style.display = "none";
      }
    } else {
      if (docBtn) docBtn.disabled = false;
      if (webBtn) webBtn.disabled = false;
      if (fileBtn) fileBtn.disabled = false;
      if (modelSelectContainer) {
        modelSelectContainer.style.display = "block";
      }
    }
  });
}

if (webSearchBtn) {
  const webSearchNoticeContainer = document.getElementById("web-search-notice-container");
  const webSearchNoticeDismiss = document.getElementById("web-search-notice-dismiss");
  const webSearchNoticeSessionKey = "webSearchNoticeDismissed";
  
  // Check if notice was dismissed this session
  const isNoticeDismissed = () => sessionStorage.getItem(webSearchNoticeSessionKey) === "true";
  
  // Show/hide notice based on web search state
  const updateWebSearchNotice = (isActive) => {
    if (webSearchNoticeContainer && window.appSettings?.enable_web_search_user_notice) {
      if (isActive && !isNoticeDismissed()) {
        webSearchNoticeContainer.style.display = "block";
      } else {
        webSearchNoticeContainer.style.display = "none";
      }
    }
  };
  
  // Dismiss button handler
  if (webSearchNoticeDismiss) {
    webSearchNoticeDismiss.addEventListener("click", function() {
      sessionStorage.setItem(webSearchNoticeSessionKey, "true");
      if (webSearchNoticeContainer) {
        webSearchNoticeContainer.style.display = "none";
      }
    });
  }
  
  webSearchBtn.addEventListener("click", function () {
    this.classList.toggle("active");
    const isActive = this.classList.contains("active");
    updateWebSearchNotice(isActive);
  });
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

    if (file) {
      fileBtn.classList.add("active");
      fileBtn.querySelector(".file-btn-text").textContent = file.name;
      cancelFileSelection.style.display = "inline";
      
      // Hide the upload button since we're auto-uploading
      uploadBtn.style.display = "none";
      
      // Check for user agreement before uploading
      const doUpload = () => {
        if (!currentConversationId) {
          createNewConversation(() => {
            uploadFileToConversation(file);
          }, { preserveSelections: true });
        } else {
          uploadFileToConversation(file);
        }
      };
      
      // Check if UserAgreementManager exists and check for agreement
      if (window.UserAgreementManager) {
        window.UserAgreementManager.checkBeforeUpload(
          fileInputEl.files,
          'chat',
          'default',
          function(files) {
            doUpload();
          }
        );
      } else {
        doUpload();
      }
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

    // Check for user agreement before uploading
    const doUpload = () => {
      if (!currentConversationId) {
        createNewConversation(() => {
          uploadFileToConversation(file);
        }, { preserveSelections: true });
      } else {
        uploadFileToConversation(file);
      }
    };
    
    // Check if UserAgreementManager exists and check for agreement
    if (window.UserAgreementManager) {
      window.UserAgreementManager.checkBeforeUpload(
        fileInput.files,
        'chat',
        'default',
        function(files) {
          doUpload();
        }
      );
    } else {
      doUpload();
    }
  });
}
