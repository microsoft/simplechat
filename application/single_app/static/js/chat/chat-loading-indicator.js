// chat-loading.js

export function showLoadingIndicator() {
  let loadingSpinner = document.getElementById("loading-spinner");
  if (!loadingSpinner) {
    loadingSpinner = document.createElement("div");
    loadingSpinner.id = "loading-spinner";
    loadingSpinner.innerHTML = `
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Loading...</span>
      </div>
    `;
    loadingSpinner.style.position = "fixed";
    loadingSpinner.style.top = "50%";
    loadingSpinner.style.left = "50%";
    loadingSpinner.style.transform = "translate(-50%, -50%)";
    loadingSpinner.style.zIndex = "1050";
    document.body.appendChild(loadingSpinner);
  } else {
    loadingSpinner.style.display = "block";
  }
}

export function hideLoadingIndicator() {
  const loadingSpinner = document.getElementById("loading-spinner");
  if (loadingSpinner) {
    loadingSpinner.style.display = "none";
  }
}

export function showLoadingIndicatorInChatbox() {
  const chatbox = document.getElementById("chatbox");
  if (!chatbox) return;

  const loadingIndicator = document.createElement("div");
  loadingIndicator.classList.add("loading-indicator");
  loadingIndicator.id = "loading-indicator";
  loadingIndicator.innerHTML = `
    <div class="spinner-border text-primary" role="status">
      <span class="visually-hidden">AI is typing...</span>
    </div>
    <span id="loading-indicator-text">AI is typing...</span>
  `;
  chatbox.appendChild(loadingIndicator);
  chatbox.scrollTop = chatbox.scrollHeight;
}

/**
 * Update the loading indicator text with a thought step.
 * Called by the thought polling handler to replace "AI is typing..." dynamically.
 * @param {string} text - The thought content to display.
 * @param {string} iconClass - Bootstrap Icon class (e.g. 'bi-search').
 */
export function updateLoadingIndicatorText(text, iconClass) {
  const textEl = document.getElementById("loading-indicator-text");
  if (!textEl) return;

  if (iconClass) {
    textEl.innerHTML = `<i class="bi ${iconClass} me-1"></i>${text}`;
  } else {
    textEl.textContent = text;
  }

  // Scroll chatbox to keep indicator visible
  const chatbox = document.getElementById("chatbox");
  if (chatbox) {
    chatbox.scrollTop = chatbox.scrollHeight;
  }
}

export function hideLoadingIndicatorInChatbox() {
  const loadingIndicator = document.getElementById("loading-indicator");
  if (loadingIndicator) {
    loadingIndicator.remove();
  }
}

export function showFileUploadingMessage() {
  const chatbox = document.getElementById("chatbox");
  if (!chatbox) return null;

  // Create a wrapper for the system message
  const msgWrapper = document.createElement("div");
  msgWrapper.classList.add("chat-message", "system-message", "file-uploading-msg");
  // You might have your own classes like "ai-message" or "system-message"

  // You can style this similarly to how you show "AI is typing..."
  msgWrapper.innerHTML = `
    <div class="message-content">
      <div class="spinner-border text-primary" role="status" style="margin-right: 8px;">
        <span class="visually-hidden">Uploading file to chat...</span>
      </div>
      <span>Uploading file to chat...</span>
    </div>
  `;

  chatbox.appendChild(msgWrapper);
  chatbox.scrollTop = chatbox.scrollHeight;
  
  return msgWrapper;
}

export function hideFileUploadingMessage(uploadingMsgEl) {
  if (uploadingMsgEl && uploadingMsgEl.parentNode) {
    uploadingMsgEl.parentNode.removeChild(uploadingMsgEl);
  }
}