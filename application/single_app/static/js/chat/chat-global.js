// chat-global.js

let currentConversationId = null;
let personalDocs = [];
let groupDocs = [];
let activeGroupName = "";
let userPrompts = [];
let groupPrompts = [];
let publicPrompts = [];
let currentlyEditingId = null;

function getChatScrollContainer() {
  return (
    document.getElementById("chat-messages-container") ||
    document.getElementById("chatbox") ||
    null
  );
}

function isChatNearBottom(threshold = 40) {
  const container = getChatScrollContainer();
  if (!container) return true;

  const distanceFromBottom =
    container.scrollHeight - (container.scrollTop + container.clientHeight);
  return distanceFromBottom <= threshold;
}

function scrollChatToBottom() {
  const container = getChatScrollContainer();
  if (container) {
    container.scrollTop = container.scrollHeight;
  }
}

function showScrollToBottomButton() {
  const btn = document.getElementById("scroll-to-bottom-btn");
  if (!btn) return;
  btn.classList.remove("d-none");
}

function hideScrollToBottomButton() {
  const btn = document.getElementById("scroll-to-bottom-btn");
  if (!btn) return;
  btn.classList.add("d-none");
}

function initializeChatScrollBehavior() {
  const container = getChatScrollContainer();
  const btn = document.getElementById("scroll-to-bottom-btn");

  if (!container) return;

  // Initial state
  if (isChatNearBottom()) {
    hideScrollToBottomButton();
  } else {
    showScrollToBottomButton();
  }

  container.addEventListener("scroll", () => {
    if (isChatNearBottom()) {
      hideScrollToBottomButton();
    } else {
      showScrollToBottomButton();
    }
  });

  if (btn) {
    btn.addEventListener("click", () => {
      scrollChatToBottom();
      hideScrollToBottomButton();
    });
  }
}

window.addEventListener("load", () => {
  initializeChatScrollBehavior();
});