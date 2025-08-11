// chat-messages.js
import { parseCitations } from "./chat-citations.js";
import { renderFeedbackIcons } from "./chat-feedback.js";
import {
  showLoadingIndicatorInChatbox,
  hideLoadingIndicatorInChatbox,
} from "./chat-loading-indicator.js";
import { docScopeSelect, getDocumentMetadata } from "./chat-documents.js";
import { promptSelect } from "./chat-prompts.js";
import {
  createNewConversation,
  selectConversation,
  addConversationToList
} from "./chat-conversations.js";
import { escapeHtml } from "./chat-utils.js";
import { showToast } from "./chat-toast.js";
import { saveUserSetting } from "./chat-layout.js";

export const userInput = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");
const promptSelectionContainer = document.getElementById(
  "prompt-selection-container"
);
const chatbox = document.getElementById("chatbox");
const modelSelect = document.getElementById("model-select");

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

function createCitationsHtml(
  hybridCitations = [],
  webCitations = [],
  messageId
) {
  let citationsHtml = "";
  let hasCitations = false;

  if (hybridCitations && hybridCitations.length > 0) {
    hasCitations = true;
    hybridCitations.forEach((cite, index) => {
      const citationId =
        cite.citation_id || `${cite.chunk_id}_${cite.page_number || index}`; // Fallback ID
      const displayText = `${escapeHtml(cite.file_name)}, Page ${
        cite.page_number || "N/A"
      }`;
      citationsHtml += `
              <a href="#"
                 class="btn btn-sm citation-button hybrid-citation-link"
                 data-citation-id="${escapeHtml(citationId)}"
                 title="View source: ${displayText}">
                  <i class="bi bi-file-earmark-text me-1"></i>${displayText}
              </a>`;
    });
  }

  if (webCitations && webCitations.length > 0) {
    hasCitations = true;
    webCitations.forEach((cite) => {
      // Example: cite.url, cite.title
      const displayText = cite.title
        ? escapeHtml(cite.title)
        : escapeHtml(cite.url);
      citationsHtml += `
              <a href="${escapeHtml(
                cite.url
              )}" target="_blank" rel="noopener noreferrer"
                 class="btn btn-sm citation-button web-citation-link"
                 title="View web source: ${displayText}">
                  <i class="bi bi-globe me-1"></i>${displayText}
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

export function loadMessages(conversationId) {
  fetch(`/conversation/${conversationId}/messages`)
    .then((response) => response.json())
    .then((data) => {
      const chatbox = document.getElementById("chatbox");
      if (!chatbox) return;

      chatbox.innerHTML = "";
      console.log(`--- Loading messages for ${conversationId} ---`);
      data.messages.forEach((msg) => {
        console.log(`[loadMessages Loop] -------- START Message ID: ${msg.id} --------`);
        console.log(`[loadMessages Loop] Role: ${msg.role}`);
        if (msg.role === "user") {
          appendMessage("You", msg.content);
        } else if (msg.role === "assistant") {
          console.log(`  [loadMessages Loop] Full Assistant msg object:`, JSON.stringify(msg)); // Stringify to see exact keys
          console.log(`  [loadMessages Loop] Checking keys: msg.id=${msg.id}, msg.augmented=${msg.augmented}, msg.hybrid_citations exists=${'hybrid_citations' in msg}, msg.web_search_citations exists=${'web_search_citations' in msg}`);
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
          console.log(`  [loadMessages Loop] Calling appendMessage with -> sender: ${senderType}, id: ${arg4}, augmented: ${arg5} (type: ${typeof arg5}), hybrid_len: ${arg6?.length}, web_len: ${arg7?.length}`);

          appendMessage(senderType, arg2, arg3, arg4, arg5, arg6, arg7); 
          console.log(`[loadMessages Loop] -------- END Message ID: ${msg.id} --------`);
        } else if (msg.role === "file") {
          appendMessage("File", msg);
        } else if (msg.role === "image") {
          appendMessage("image", msg.content, msg.model_deployment_name);
        } else if (msg.role === "safety") {
          appendMessage("safety", msg.content);
        }
      });
    })
    .catch((error) => {
      console.error("Error loading messages:", error);
      if (chatbox) chatbox.innerHTML = `<div class="text-center p-3 text-danger">Error loading messages.</div>`;
    });
}

export function appendMessage(
  sender,
  messageContent,
  modelName = null,
  messageId = null,
  augmented = false,
  hybridCitations = [],
  webCitations = []
) {
  if (!chatbox || sender === "System") return;

  const messageDiv = document.createElement("div");
  messageDiv.classList.add("mb-2", "message");
  messageDiv.setAttribute("data-message-id", messageId || `msg-${Date.now()}`);

  let avatarImg = "";
  let avatarAltText = "";
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

    messageClass = "ai-message";
    avatarAltText = "AI Avatar";
    avatarImg = "/static/images/ai-avatar.png";
    senderLabel = modelName
      ? `AI <span style="color: #6c757d; font-size: 0.8em;">(${modelName})</span>`
      : "AI";

    // Parse content
    let cleaned = messageContent.trim().replace(/\n{3,}/g, "\n\n");
    cleaned = cleaned.replace(/(\bhttps?:\/\/\S+)(%5D|\])+/gi, (_, url) => url);
    const withInlineCitations = parseCitations(cleaned);
    const htmlContent = DOMPurify.sanitize(marked.parse(withInlineCitations));
    const mainMessageHtml = `<div class="message-text">${htmlContent}</div>`; // Renamed for clarity

    // --- Footer Content (Copy, Feedback, Citations) ---
    const feedbackHtml = renderFeedbackIcons(messageId, currentConversationId);
    const hiddenTextId = `copy-md-${messageId || Date.now()}`;
    const copyButtonHtml = `
            <button class="copy-btn me-2" data-hidden-text-id="${hiddenTextId}" title="Copy AI response as Markdown">
                <i class="bi bi-copy"></i>
            </button>
            <textarea id="${hiddenTextId}" style="display:none;">${escapeHtml(
      withInlineCitations
    )}</textarea>
        `;
    const copyAndFeedbackHtml = `<div class="message-actions d-flex align-items-center">${copyButtonHtml}${feedbackHtml}</div>`;

    const citationsButtonsHtml = createCitationsHtml(
      hybridCitations,
      webCitations,
      messageId
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
    const hybridCheck = hybridCitations && hybridCitations.length > 0;
    const webCheck = webCitations && webCitations.length > 0;
    console.log("Hybrid Check Result:", hybridCheck);
    console.log("Web Check Result:", webCheck);
    const overallCondition = augmented && (hybridCheck || webCheck);
    console.log("Overall Condition Result:", overallCondition);
    const shouldShowCitations = augmented && citationsButtonsHtml;
    console.log(
      `Condition check (augmented && citationsButtonsHtml): ${shouldShowCitations}`
    );

    if (shouldShowCitations) {
      console.log(">>> Will generate and include citation elements.");
      const citationsContainerId = `citations-${messageId || Date.now()}`;
      citationToggleHtml = `<div class="citation-toggle-container"><button class="btn btn-sm btn-outline-secondary citation-toggle-btn" title="Show sources" aria-expanded="false" aria-controls="${citationsContainerId}"><i class="bi bi-journal-text"></i></button></div>`;
      citationContentContainerHtml = `<div class="citations-container mt-2 pt-2 border-top" id="${citationsContainerId}" style="display: none;">${citationsButtonsHtml}</div>`;
    } else {
      console.log(">>> Will NOT generate citation elements.");
    }

    const footerContentHtml = `<div class="message-footer d-flex justify-content-between align-items-center">${copyAndFeedbackHtml}${citationToggleHtml}</div>`;

    // Build AI message inner HTML
    messageDiv.innerHTML = `
            <div class="message-content">
                <img src="${avatarImg}" alt="${avatarAltText}" class="avatar">
                <div class="message-bubble">
                    <div class="message-sender">${senderLabel}</div>
                    ${mainMessageHtml}
                    ${citationContentContainerHtml}
                    ${footerContentHtml}
                </div>
            </div>`;

    messageDiv.classList.add(messageClass); // Add AI message class
    chatbox.appendChild(messageDiv); // Append AI message

    // --- Attach Event Listeners specifically for AI message ---
    attachCodeBlockCopyButtons(messageDiv.querySelector(".message-text"));
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
        const isExpanded = citationsContainer.style.display !== "none";
        citationsContainer.style.display = isExpanded ? "none" : "block";
        toggleBtn.setAttribute("aria-expanded", !isExpanded);
        toggleBtn.title = isExpanded ? "Show sources" : "Hide sources";
        toggleBtn.innerHTML = isExpanded
          ? '<i class="bi bi-journal-text"></i>'
          : '<i class="bi bi-chevron-up"></i>';
        if (!isExpanded) {
          scrollChatToBottom();
        }
      });
    }

    scrollChatToBottom();
    return; // <<< EXIT EARLY FOR AI MESSAGES

    // --- Handle ALL OTHER message types ---
  } else {
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
      
      messageContentHtml = DOMPurify.sanitize(
        marked.parse(escapeHtml(messageContent))
      );
    } else if (sender === "File") {
      messageClass = "file-message";
      senderLabel = "File Added";
      avatarImg = ""; // No avatar for file messages
      avatarAltText = "";
      const filename = escapeHtml(messageContent.filename);
      const fileId = escapeHtml(messageContent.id);
      messageContentHtml = `<a href="#" class="file-link" data-conversation-id="${currentConversationId}" data-file-id="${fileId}"><i class="bi bi-file-earmark-arrow-up me-1"></i>${filename}</a>`;
    } else if (sender === "image") {
      // Make sure this matches the case used in loadMessages/actuallySendMessage
      messageClass = "image-message"; // Use a distinct class if needed, or reuse ai-message
      senderLabel = modelName
        ? `AI <span style="color: #6c757d; font-size: 0.8em;">(${modelName})</span>`
        : "Image"; // Or just "Image"
      avatarImg = "/static/images/ai-avatar.png"; // Or a specific image icon
      avatarAltText = "Generated Image";
      messageContentHtml = `<img src="${messageContent}" alt="Generated Image" class="generated-image" style="width: 170px; height: 170px; cursor: pointer;" data-image-src="${messageContent}" onload="scrollChatToBottom()" />`;
    } else if (sender === "safety") {
      messageClass = "safety-message";
      senderLabel = "Content Safety";
      avatarAltText = "Content Safety Avatar";
      avatarImg = "/static/images/alert.png";
      const linkToViolations = `<br><small><a href="/safety_violations" target="_blank" rel="noopener" style="font-size: 0.85em; color: #6c757d;">View My Safety Violations</a></small>`;
      messageContentHtml = DOMPurify.sanitize(
        marked.parse(messageContent + linkToViolations)
      );
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

    // Set innerHTML using the variables determined above
    messageDiv.innerHTML = `
            <div class="message-content ${
              sender === "You" || sender === "File" ? "flex-row-reverse" : ""
            }">
                ${
                  avatarImg
                    ? `<img src="${avatarImg}" alt="${avatarAltText}" class="avatar">`
                    : ""
                }
                <div class="message-bubble">
                    <div class="message-sender">${senderLabel}</div>
                    <div class="message-text">${messageContentHtml}</div>
                </div>
            </div>`;

    // Append and scroll (common actions for non-AI)
    chatbox.appendChild(messageDiv);
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
    });
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

export function actuallySendMessage(finalMessageToSend) {
  // Append user message first
  appendMessage("You", finalMessageToSend);
  userInput.value = "";
  userInput.style.height = "";
  // Update send button visibility after clearing input
  updateSendButtonVisibility();
  showLoadingIndicatorInChatbox();

  const modelDeployment = modelSelect?.value;

  // ... (keep existing logic for hybridSearchEnabled, selectedDocumentId, classificationsToSend, bingSearchEnabled, imageGenEnabled)
  let hybridSearchEnabled = false;
  const sdbtn = document.getElementById("search-documents-btn");
  if (sdbtn && sdbtn.classList.contains("active")) {
    hybridSearchEnabled = true;
  }

  let selectedDocumentId = null;
  let classificationsToSend = null;
  const docSel = document.getElementById("document-select");
  const classificationInput = document.getElementById("classification-select");

  // Always set selectedDocumentId if a document is selected, regardless of hybridSearchEnabled
  if (docSel) {
    const selectedDocOption = docSel.options[docSel.selectedIndex];
    if (selectedDocOption && selectedDocOption.value !== "") {
      selectedDocumentId = selectedDocOption.value;
    } else {
      selectedDocumentId = null;
    }
  }

  // Only set classificationsToSend if classificationInput exists
  if (classificationInput) {
    classificationsToSend =
      classificationInput.value === "N/A" ? null : classificationInput.value;
  }

  let bingSearchEnabled = false;
  const wbbtn = document.getElementById("search-web-btn");
  if (wbbtn && wbbtn.classList.contains("active")) {
    bingSearchEnabled = true;
  }

  let imageGenEnabled = false;
  const igbtn = document.getElementById("image-generate-btn");
  if (igbtn && igbtn.classList.contains("active")) {
    imageGenEnabled = true;
  }

  // --- Robust chat_type/group_id logic ---
  // Assume: window.activeChatTabType = 'user' | 'group', window.activeGroupId = group id if group tab
  // If you add a group chat tab, set window.activeChatTabType and window.activeGroupId accordingly when switching tabs
  let chat_type = 'user';
  let group_id = null;
  if (window.activeChatTabType === 'group' && window.activeGroupId) {
    chat_type = 'group';
    group_id = window.activeGroupId;
  }

  // Fallback: if group_id is null/empty, use window.activeGroupId
  const finalGroupId = group_id || window.activeGroupId || null;
  fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    credentials: "same-origin",
    body: JSON.stringify({
      message: finalMessageToSend,
      conversation_id: currentConversationId,
      hybrid_search: hybridSearchEnabled,
      selected_document_id: selectedDocumentId,
      classifications: classificationsToSend,
      bing_search: bingSearchEnabled,
      image_generation: imageGenEnabled,
      doc_scope: docScopeSelect ? docScopeSelect.value : "all",
      chat_type: chat_type,
      active_group_id: finalGroupId, // for backward compatibility
      model_deployment: modelDeployment
    }),
  })
    .then((response) => {
      if (!response.ok) {
        // Handle non-OK responses, try to parse JSON error
        return response
          .json()
          .then((errData) => {
            // Throw an error object including the status and parsed data
            const error = new Error(
              errData.error || `HTTP error! status: ${response.status}`
            );
            error.status = response.status;
            error.data = errData; // Attach full error data
            throw error;
          })
          .catch(() => {
            // If JSON parsing fails, throw a generic error
            throw new Error(`HTTP error! status: ${response.status}`);
          });
      }
      return response.json(); // Parse JSON for successful responses
    })
    .then((data) => {
      // Only successful responses reach here
      hideLoadingIndicatorInChatbox();

      console.log("--- Data received from /api/chat ---");
      console.log("Full data object:", data);
      console.log(
        `data.augmented: ${data.augmented} (Type: ${typeof data.augmented})`
      );
      console.log("data.hybrid_citations:", data.hybrid_citations);
      console.log("data.web_search_citations:", data.web_search_citations);
      console.log(`data.message_id: ${data.message_id}`);

      if (data.reply) {
        // *** Pass the new fields to appendMessage ***
        appendMessage(
          "AI",
          data.reply,
          data.model_deployment_name,
          data.message_id,
          data.augmented, // Pass augmented flag
          data.hybrid_citations, // Pass hybrid citations
          data.web_search_citations // Pass web citations
        );
      }
      // Show kernel fallback notice if present
      if (data.kernel_fallback_notice) {
        showToast(data.kernel_fallback_notice, 'warning');
      }
      if (data.image_url) {
        // Assuming image messages don't have citations in this flow
        appendMessage(
          "image",
          data.image_url,
          data.model_deployment_name,
          data.message_id
        );
      }

      // Update conversation list item and header if needed
      if (data.conversation_id) {
        currentConversationId = data.conversation_id; // Update current ID
        const convoItem = document.querySelector(
          `.conversation-item[data-conversation-id="${currentConversationId}"]`
        );
        if (convoItem) {
          let updated = false;
          // Update Title
          if (
            data.conversation_title &&
            convoItem.getAttribute("data-conversation-title") !==
              data.conversation_title
          ) {
            convoItem.setAttribute(
              "data-conversation-title",
              data.conversation_title
            );
            const titleEl = convoItem.querySelector(".conversation-title");
            if (titleEl) titleEl.textContent = data.conversation_title;
            updated = true;
          }
          // Update Classifications
          if (data.classification) {
            // Check if API returned classification
            const currentClassificationJson =
              convoItem.dataset.classifications || "[]";
            const newClassificationJson = JSON.stringify(data.classification);
            if (currentClassificationJson !== newClassificationJson) {
              convoItem.dataset.classifications = newClassificationJson;
              updated = true;
            }
          }
          // Update Timestamp (optional, could be done on load)
          const dateEl = convoItem.querySelector("small");
          if (dateEl)
            dateEl.textContent = new Date().toLocaleString([], {
              dateStyle: "short",
              timeStyle: "short",
            });

          if (updated) {
            selectConversation(currentConversationId); // Re-select to update header
          }
        } else {
          // New conversation case
          addConversationToList(
            currentConversationId,
            data.conversation_title,
            data.classification || []
          );
          selectConversation(currentConversationId); // Select the newly added one
        }
      }
    })
    .catch((error) => {
      hideLoadingIndicatorInChatbox();
      console.error("Error sending message:", error);

      // Display specific error messages based on status or content
      if (error.status === 403 && error.data) {
        // Check for status and data from thrown error
        const categories = (error.data.triggered_categories || [])
          .map((catObj) => `${catObj.category} (severity=${catObj.severity})`)
          .join(", ");
        const reasonMsg = Array.isArray(error.data.reason)
          ? error.data.reason.join(", ")
          : error.data.reason;

        appendMessage(
          "safety", // Use 'safety' sender type
          `Your message was blocked by Content Safety.\n\n` +
            `**Categories triggered**: ${categories}\n` +
            `**Reason**: ${reasonMsg}`,
          null, // No model name for safety message
          error.data.message_id // Use message_id if provided in error
        );
      } else {
        // Show specific embedding error if present, or if status is 500 (embedding backend error)
        const errMsg = (error.message || "").toLowerCase();
        if (errMsg.includes("embedding") || error.status === 500) {
          appendMessage(
            "Error",
            "There was an issue with the embedding process. Please check with an admin on embedding configuration."
          );
        } else {
          // General error message
          appendMessage(
            "Error",
            `Could not get a response. ${error.message || ""}`
          );
        }
      }
    });
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
  userInput.addEventListener("input", updateSendButtonVisibility);
  userInput.addEventListener("focus", updateSendButtonVisibility);
  userInput.addEventListener("blur", updateSendButtonVisibility);
}

// Monitor prompt selection changes
if (promptSelect) {
  promptSelect.addEventListener("change", updateSendButtonVisibility);
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
    console.log(`Saving preferred model: ${selectedModel}`);
    saveUserSetting({ 'preferredModelDeployment': selectedModel });
  });
}
