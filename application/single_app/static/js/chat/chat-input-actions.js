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
        showFileContentPopup(data.file_content, data.filename, data.is_table);
      } else if (data.error) {
        showToast(data.error, "danger");
      } else {
        ashowToastlert("Unexpected response from server.", "danger");
      }
    })
    .catch((error) => {
      hideLoadingIndicator();
      console.error("Error fetching file content:", error);
      showToast("Error fetching file content.", "danger");
    });
}

export function showFileContentPopup(fileContent, filename, isTable) {
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
            <h5 class="modal-title">Uploaded File: ${filename}</h5>
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
  } else {
    const modalTitle = modalContainer.querySelector(".modal-title");
    if (modalTitle) {
      modalTitle.textContent = `Uploaded File: ${filename}`;
    }
  }

  const fileContentElement = document.getElementById("file-content");
  if (!fileContentElement) return;

  if (isTable) {
    fileContentElement.innerHTML = `<div class="table-responsive">${fileContent}</div>`;
    $(document).ready(function () {
      $("#file-content table").DataTable({
        responsive: true,
        scrollX: true,
      });
    });
  } else {
    fileContentElement.innerHTML = `<pre style="white-space: pre-wrap;">${fileContent}</pre>`;
  }

  const modal = new bootstrap.Modal(modalContainer);
  modal.show();
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
    } else {
      if (docBtn) docBtn.disabled = false;
      if (webBtn) webBtn.disabled = false;
      if (fileBtn) fileBtn.disabled = false;
    }
  });
}

if (webSearchBtn) {
  webSearchBtn.addEventListener("click", function () {
    this.classList.toggle("active");
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
      
      // Automatically upload the file
      if (!currentConversationId) {
        createNewConversation(() => {
          uploadFileToConversation(file);
        });
      } else {
        uploadFileToConversation(file);
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

    if (!currentConversationId) {
      createNewConversation(() => {
        uploadFileToConversation(file);
      });
    } else {
      uploadFileToConversation(file);
    }
  });
}
