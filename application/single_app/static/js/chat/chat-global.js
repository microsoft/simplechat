// chat-global.js

let currentConversationId = null;
let personalDocs = [];
let groupDocs = [];
let activeGroupName = "";
let userPrompts = [];
let groupPrompts = [];
let publicPrompts = [];
let currentlyEditingId = null;

function scrollChatToBottom() {
  const chatbox = document.getElementById("chatbox");
  if (chatbox) {
    chatbox.scrollTop = chatbox.scrollHeight;
  }
}