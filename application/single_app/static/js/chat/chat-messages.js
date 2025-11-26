// chat-messages.js
import { parseCitations } from "./chat-citations.js";
import { renderFeedbackIcons } from "./chat-feedback.js";
import {
  showLoadingIndicatorInChatbox,
  hideLoadingIndicatorInChatbox,
} from "./chat-loading-indicator.js";
import { docScopeSelect, getDocumentMetadata, personalDocs, groupDocs, publicDocs } from "./chat-documents.js";
import { promptSelect } from "./chat-prompts.js";
import {
  createNewConversation,
  selectConversation,
  addConversationToList
} from "./chat-conversations.js";
import { updateSidebarConversationTitle } from "./chat-sidebar-conversations.js";
import { escapeHtml, isColorLight, addTargetBlankToExternalLinks } from "./chat-utils.js";
import { showToast } from "./chat-toast.js";
import { saveUserSetting } from "./chat-layout.js";

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
  agentCitations = [],
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
      
      // Check if this is a metadata citation
      const isMetadata = cite.metadata_type ? true : false;
      const metadataType = cite.metadata_type || '';
      const metadataContent = cite.metadata_content || '';
      
      citationsHtml += `
              <a href="#"
                 class="btn btn-sm citation-button hybrid-citation-link ${isMetadata ? 'metadata-citation' : ''}"
                 data-citation-id="${escapeHtml(citationId)}"
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
          appendMessage("You", msg.content, null, msg.id);
        } else if (msg.role === "assistant") {
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

          appendMessage(senderType, arg2, arg3, arg4, arg5, arg6, arg7, arg8, arg9, arg10); 
          console.log(`[loadMessages Loop] -------- END Message ID: ${msg.id} --------`);
        } else if (msg.role === "file") {
          appendMessage("File", msg);
        } else if (msg.role === "image") {
          // Validate image URL before calling appendMessage
          if (msg.content && msg.content !== 'null' && msg.content.trim() !== '') {
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
  webCitations = [],
  agentCitations = [],
  agentDisplayName = null,
  agentName = null,
  fullMessageObject = null
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
      senderLabel = agentDisplayName;
    } else if (modelName) {
      senderLabel = `AI <span style="color: #6c757d; font-size: 0.8em;">(${modelName})</span>`;
    } else {
      senderLabel = "AI";
    }

    // Parse content with comprehensive table processing
    let cleaned = messageContent.trim().replace(/\n{3,}/g, "\n\n");
    cleaned = cleaned.replace(/(\bhttps?:\/\/\S+)(%5D|\])+/gi, (_, url) => url);
    const withInlineCitations = parseCitations(cleaned);
    const withUnwrappedTables = unwrapTablesFromCodeBlocks(withInlineCitations);
    const withMarkdownTables = convertUnicodeTableToMarkdown(withUnwrappedTables);
    const withPSVTables = convertPSVCodeBlockToMarkdown(withMarkdownTables);
    const withASCIITables = convertASCIIDashTableToMarkdown(withPSVTables);
    const sanitizedHtml = DOMPurify.sanitize(marked.parse(withASCIITables));
    const htmlContent = addTargetBlankToExternalLinks(sanitizedHtml);

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
      agentCitations,
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
    const overallCondition = augmented && (hybridCheck || webCheck || agentCheck);
    console.log("Overall Condition Result:", overallCondition);
    const shouldShowCitations = (augmented && citationsButtonsHtml) || agentCheck;
    console.log(
      `Condition check ((augmented && citationsButtonsHtml) || agentCheck): ${shouldShowCitations}`
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
    
    // Highlight code blocks in the messages
    messageDiv.querySelectorAll('pre code[class^="language-"]').forEach((block) => {
      const match = block.className.match(/language-([a-zA-Z0-9]+)/);
      if (match && !block.hasAttribute('data-language')) {
        block.setAttribute('data-language', match[1]);
      }
      if (window.Prism) Prism.highlightElement(block);
    });

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
      
      const sanitizedUserHtml = DOMPurify.sanitize(
        marked.parse(escapeHtml(messageContent))
      );
      messageContentHtml = addTargetBlankToExternalLinks(sanitizedUserHtml);
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
      
      // Check if this is a user-uploaded image with metadata
      const isUserUpload = fullMessageObject?.metadata?.is_user_upload || false;
      const hasExtractedText = fullMessageObject?.extracted_text || false;
      const hasVisionAnalysis = fullMessageObject?.vision_analysis || false;
      
      // Use agent display name if available, otherwise show AI with model
      if (isUserUpload) {
        senderLabel = "Uploaded Image";
      } else if (agentDisplayName) {
        senderLabel = agentDisplayName;
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
        
        // Add info button for uploaded images with extracted text or vision analysis
        if (isUserUpload && (hasExtractedText || hasVisionAnalysis)) {
          const infoContainerId = `image-info-${messageId || Date.now()}`;
          messageContentHtml += `
            <div class="mt-2">
              <button class="btn btn-sm btn-outline-secondary image-info-btn" data-message-id="${messageId}" title="View extracted text & analysis" aria-expanded="false" aria-controls="${infoContainerId}">
                <i class="bi bi-info-circle"></i> View Text
              </button>
            </div>
            <div class="image-info-container mt-2 pt-2 border-top" id="${infoContainerId}" style="display: none;">
              <div class="text-muted">Loading image information...</div>
            </div>`;
        }
      } else {
        messageContentHtml = `<div class="alert alert-warning"><i class="bi bi-exclamation-triangle me-2"></i>Failed to ${isUserUpload ? 'load' : 'generate'} image - invalid response from image service</div>`;
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

    // Create user message footer if this is a user message
    let messageFooterHtml = "";
    let metadataContainerHtml = "";
    if (sender === "You") {
      const metadataContainerId = `metadata-${messageId || Date.now()}`;
      messageFooterHtml = `
        <div class="message-footer d-flex justify-content-between align-items-center mt-2">
          <button class="btn btn-sm btn-outline-secondary copy-user-btn" data-message-id="${messageId}" title="Copy message">
            <i class="bi bi-copy"></i>
          </button>
          <button class="btn btn-sm btn-outline-secondary metadata-toggle-btn" data-message-id="${messageId}" title="Show metadata" aria-expanded="false" aria-controls="${metadataContainerId}">
            <i class="bi bi-info-circle"></i>
          </button>
        </div>`;
      metadataContainerHtml = `<div class="metadata-container mt-2 pt-2 border-top" id="${metadataContainerId}" style="display: none;"><div class="text-muted">Loading metadata...</div></div>`;
    }

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
                    ${metadataContainerHtml}
                    ${messageFooterHtml}
                </div>
            </div>`;

    // Append and scroll (common actions for non-AI)
    chatbox.appendChild(messageDiv);

    // Highlight code blocks in the messages
    messageDiv.querySelectorAll('pre code[class^="language-"]').forEach((block) => {
      const match = block.className.match(/language-([a-zA-Z0-9]+)/);
      if (match && !block.hasAttribute('data-language')) {
        block.setAttribute('data-language', match[1]);
      }
      if (window.Prism) Prism.highlightElement(block);
    });

    
    // Add event listeners for user message buttons
    if (sender === "You") {
      attachUserMessageEventListeners(messageDiv, messageId, messageContent);
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
  // Generate a temporary message ID for the user message
  const tempUserMessageId = `temp_user_${Date.now()}`;
  
  // Append user message first with temporary ID
  appendMessage("You", finalMessageToSend, null, tempUserMessageId);
  userInput.value = "";
  userInput.style.height = "";
  // Update send button visibility after clearing input
  updateSendButtonVisibility();
  showLoadingIndicatorInChatbox();

  const modelDeployment = modelSelect?.value;

  // ... (keep existing logic for hybridSearchEnabled, selectedDocumentId, classificationsToSend, imageGenEnabled)
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

  // Collect prompt information if a prompt is selected
  let promptInfo = null;
  if (
    promptSelectionContainer &&
    promptSelectionContainer.style.display !== "none" &&
    promptSelect &&
    promptSelect.selectedIndex > 0
  ) {
    const selectedOpt = promptSelect.options[promptSelect.selectedIndex];
    if (selectedOpt) {
      promptInfo = {
        name: selectedOpt.textContent,
        id: selectedOpt.value,
        content: selectedOpt.dataset?.promptContent || ""
      };
    }
  }

  // Collect agent information if agents are enabled
  let agentInfo = null;
  const agentSelectContainer = document.getElementById("agent-select-container");
  const agentSelect = document.getElementById("agent-select");
  if (agentSelectContainer && agentSelectContainer.style.display !== "none" && agentSelect) {
    const selectedAgentOption = agentSelect.options[agentSelect.selectedIndex];
    if (selectedAgentOption && selectedAgentOption.value) {
      agentInfo = {
        name: selectedAgentOption.value,
        display_name: selectedAgentOption.textContent,
        is_global: selectedAgentOption.textContent.includes("(Global)")
      };
    }
  }

  // Determine the correct doc_scope, especially when "all" is selected but a specific document is chosen
  let effectiveDocScope = docScopeSelect ? docScopeSelect.value : "all";
  
  // If scope is "all" but a specific document is selected, determine the actual scope of that document
  if (effectiveDocScope === "all" && selectedDocumentId) {
    const documentMetadata = getDocumentMetadata(selectedDocumentId);
    if (documentMetadata) {
      // Check which list the document belongs to
      if (personalDocs.find(doc => doc.id === selectedDocumentId || doc.document_id === selectedDocumentId)) {
        effectiveDocScope = "personal";
      } else if (groupDocs.find(doc => doc.id === selectedDocumentId || doc.document_id === selectedDocumentId)) {
        effectiveDocScope = "group";
      } else if (publicDocs.find(doc => doc.id === selectedDocumentId || doc.document_id === selectedDocumentId)) {
        effectiveDocScope = "public";
      }
      console.log(`Document ${selectedDocumentId} scope detected as: ${effectiveDocScope}`);
    }
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
      image_generation: imageGenEnabled,
      doc_scope: effectiveDocScope,
      chat_type: chat_type,
      active_group_id: finalGroupId, // for backward compatibility
      model_deployment: modelDeployment,
      prompt_info: promptInfo,
      agent_info: agentInfo
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
      console.log("data.agent_citations:", data.agent_citations);
      console.log(`data.message_id: ${data.message_id}`);

      // Update the user message with the real message ID
      if (data.user_message_id) {
        updateUserMessageId(tempUserMessageId, data.user_message_id);
      }

      if (data.reply) {
        // *** Pass the new fields to appendMessage ***
        appendMessage(
          "AI",
          data.reply,
          data.model_deployment_name,
          data.message_id,
          data.augmented, // Pass augmented flag
          data.hybrid_citations, // Pass hybrid citations
          data.web_search_citations, // Pass web citations
          data.agent_citations, // Pass agent citations
          data.agent_display_name, // Pass agent display name
          data.agent_name // Pass agent name
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
          null, // messageId
          false, // augmented
          [], // hybridCitations
          [], // webCitations
          [], // agentCitations
          data.agent_display_name, // Pass agent display name
          data.agent_name // Pass agent name
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
            
            // Update sidebar conversation title in real-time
            updateSidebarConversationTitle(currentConversationId, data.conversation_title);
            
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
          error.data.message_id, // Use message_id if provided in error
          false, // augmented
          [], // hybridCitations
          [], // webCitations
          [], // agentCitations
          null, // agentDisplayName
          null // agentName
        );
      } else {
        // Show specific embedding error if present, or if status is 500 (embedding backend error)
        const errMsg = (error.message || "").toLowerCase();
        
        // Handle image generation content safety errors
        if (errMsg.includes("safety system") || errMsg.includes("moderation_blocked") || errMsg.includes("content safety")) {
          appendMessage(
            "safety", // Use 'safety' sender type
            `**Image Generation Blocked by Content Safety**\n\n` +
            `Your image generation request was blocked by Azure OpenAI's content safety system. ` +
            `Please try a different prompt that doesn't involve potentially harmful, violent, or illicit content.\n\n` +
            `**Error**: ${error.message || "Content safety violation"}`,
            null, // No model name for safety message
            null, // No message ID for error
            false, // augmented
            [], // hybridCitations
            [], // webCitations
            [], // agentCitations
            null, // agentDisplayName
            null // agentName
          );
        } else if (errMsg.includes("embedding") || error.status === 500) {
          appendMessage(
            "Error",
            "There was an issue with the embedding process. Please check with an admin on embedding configuration.",
            null, // No model name for error message
            null, // No message ID for error
            false, // augmented
            [], // hybridCitations
            [], // webCitations
            [], // agentCitations
            null, // agentDisplayName
            null // agentName
          );
        } else {
          // General error message
          appendMessage(
            "Error",
            `Could not get a response. ${error.message || ""}`,
            null, // No model name for error message
            null, // No message ID for error
            false, // augmented
            [], // hybridCitations
            [], // webCitations
            [], // agentCitations
            null, // agentDisplayName
            null // agentName
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

// Helper function to update user message ID after backend response
function updateUserMessageId(tempId, realId) {
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
    console.error(`❌ Message div with temp ID ${tempId} not found for update`);
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
  
  // User Information Section
  if (metadata.user_info) {
    content += '<div class="metadata-section mb-3">';
    content += '<h6 class="metadata-title mb-2">User Information</h6>';
    
    if (metadata.user_info.display_name) {
      content += `<div class="metadata-item">
        <strong>User:</strong> ${escapeHtml(metadata.user_info.display_name)}
      </div>`;
    }
    
    if (metadata.user_info.email) {
      content += `<div class="metadata-item">
        <strong>Email:</strong> ${escapeHtml(metadata.user_info.email)}
      </div>`;
    }
    
    if (metadata.user_info.username) {
      content += `<div class="metadata-item">
        <strong>Username:</strong> ${escapeHtml(metadata.user_info.username)}
      </div>`;
    }
    
    if (metadata.user_info.timestamp) {
      const date = new Date(metadata.user_info.timestamp);
      content += `<div class="metadata-item">
        <strong>Timestamp:</strong> ${escapeHtml(date.toLocaleString())}
      </div>`;
    }
    
    content += '</div>';
  }
  
  // Button States Section
  if (metadata.button_states) {
    content += '<div class="metadata-section mb-3">';
    content += '<h6 class="metadata-title mb-2">Button States</h6>';
    
    if (metadata.button_states.image_generation !== undefined) {
      content += `<div class="metadata-item">
        <strong>Image Generation:</strong> ${createStatusBadge(metadata.button_states.image_generation)}
      </div>`;
    }
    
    if (metadata.button_states.web_search !== undefined) {
      content += `<div class="metadata-item">
        <strong>Web Search:</strong> ${createStatusBadge(metadata.button_states.web_search)}
      </div>`;
    }
    
    if (metadata.button_states.document_search !== undefined) {
      content += `<div class="metadata-item">
        <strong>Document Search:</strong> ${createStatusBadge(metadata.button_states.document_search)}
      </div>`;
    }
    
    content += '</div>';
  }
  
  // Workspace Search Section
  if (metadata.workspace_search) {
    content += '<div class="metadata-section mb-3">';
    content += '<h6 class="metadata-title mb-2">Workspace & Document Selection</h6>';
    
    if (metadata.workspace_search.search_enabled !== undefined) {
      content += `<div class="metadata-item">
        <strong>Search Enabled:</strong> ${createStatusBadge(metadata.workspace_search.search_enabled)}
      </div>`;
    }
    
    if (metadata.workspace_search.document_name) {
      content += `<div class="metadata-item">
        <strong>Selected Document:</strong> ${escapeHtml(metadata.workspace_search.document_name)}
      </div>`;
    } else if (metadata.workspace_search.selected_document_id && metadata.workspace_search.selected_document_id !== 'None' && metadata.workspace_search.selected_document_id !== 'all') {
      content += `<div class="metadata-item">
        <strong>Document ID:</strong> ${escapeHtml(metadata.workspace_search.selected_document_id)}
      </div>`;
    }
    
    if (metadata.workspace_search.document_scope) {
      content += `<div class="metadata-item">
        <strong>Search Scope:</strong> ${createInfoBadge(metadata.workspace_search.document_scope, 'primary')}
      </div>`;
    }
    
    if (metadata.workspace_search.classification && metadata.workspace_search.classification !== 'None') {
      content += `<div class="metadata-item">
        <strong>Classification:</strong> ${createClassificationBadge(metadata.workspace_search.classification)}
      </div>`;
    }
    
    if (metadata.workspace_search.group_name) {
      content += `<div class="metadata-item">
        <strong>Group:</strong> ${escapeHtml(metadata.workspace_search.group_name)}
      </div>`;
    }
    
    content += '</div>';
  }
  
  // Prompt Selection Section
  if (metadata.prompt_selection) {
    content += '<div class="metadata-section mb-3">';
    content += '<h6 class="metadata-title mb-2">Prompt Selection</h6>';
    
    if (metadata.prompt_selection.prompt_name) {
      content += `<div class="metadata-item">
        <strong>Prompt Name:</strong> ${createInfoBadge(metadata.prompt_selection.prompt_name, 'success')}
      </div>`;
    }
    
    if (metadata.prompt_selection.selected_prompt_index !== undefined) {
      content += `<div class="metadata-item">
        <strong>Prompt Index:</strong> ${escapeHtml(metadata.prompt_selection.selected_prompt_index)}
      </div>`;
    }
    
    if (metadata.prompt_selection.selected_prompt_text) {
      content += `<div class="metadata-item">
        <strong>Content:</strong>
        <div class="mt-1 p-2 bg-light rounded small">
          ${escapeHtml(metadata.prompt_selection.selected_prompt_text)}
        </div>
      </div>`;
    }
    
    content += '</div>';
  }
  
  // Agent Selection Section
  if (metadata.agent_selection) {
    content += '<div class="metadata-section mb-3">';
    content += '<h6 class="metadata-title mb-2">Agent Selection</h6>';
    
    if (metadata.agent_selection.agent_display_name) {
      content += `<div class="metadata-item">
        <strong>Agent:</strong> ${createInfoBadge(metadata.agent_selection.agent_display_name, 'success')}
      </div>`;
    } else if (metadata.agent_selection.selected_agent) {
      content += `<div class="metadata-item">
        <strong>Selected Agent:</strong> ${createInfoBadge(metadata.agent_selection.selected_agent, 'success')}
      </div>`;
    }
    
    if (metadata.agent_selection.is_global !== undefined) {
      content += `<div class="metadata-item">
        <strong>Global Agent:</strong> ${createStatusBadge(metadata.agent_selection.is_global)}
      </div>`;
    }
    
    content += '</div>';
  }
  
  // Model Selection Section
  if (metadata.model_selection) {
    content += '<div class="metadata-section mb-3">';
    content += '<h6 class="metadata-title mb-2">Model Selection</h6>';
    
    if (metadata.model_selection.selected_model) {
      content += `<div class="metadata-item">
        <strong>Selected Model:</strong> ${escapeHtml(metadata.model_selection.selected_model)}
      </div>`;
    }
    
    if (metadata.model_selection.frontend_requested_model && 
        metadata.model_selection.frontend_requested_model !== metadata.model_selection.selected_model) {
      content += `<div class="metadata-item">
        <strong>Frontend Model:</strong> ${escapeHtml(metadata.model_selection.frontend_requested_model)}
      </div>`;
    }
    
    content += '</div>';
  }
  
  // Chat Context Section
  if (metadata.chat_context) {
    content += '<div class="metadata-section mb-3">';
    content += '<h6 class="metadata-title mb-2">Chat Context</h6>';
    
    if (metadata.chat_context.conversation_id) {
      content += `<div class="metadata-item">
        <strong>Conversation ID:</strong> ${escapeHtml(metadata.chat_context.conversation_id)}
      </div>`;
    }
    
    if (metadata.chat_context.chat_type) {
      content += `<div class="metadata-item">
        <strong>Chat Type:</strong> ${createInfoBadge(metadata.chat_context.chat_type, 'primary')}
      </div>`;
    }
    
    // Show context-specific information based on chat type
    if (metadata.chat_context.chat_type === 'group') {
      if (metadata.chat_context.group_name) {
        content += `<div class="metadata-item">
          <strong>Group:</strong> ${escapeHtml(metadata.chat_context.group_name)}
        </div>`;
      } else if (metadata.chat_context.group_id && metadata.chat_context.group_id !== 'None') {
        content += `<div class="metadata-item">
          <strong>Group ID:</strong> ${escapeHtml(metadata.chat_context.group_id)}
        </div>`;
      }
    } else if (metadata.chat_context.chat_type === 'public') {
      if (metadata.chat_context.workspace_context) {
        content += `<div class="metadata-item">
          <strong>Workspace:</strong> ${createInfoBadge(metadata.chat_context.workspace_context, 'info')}
        </div>`;
      }
    }
    // For 'personal' chat type, no additional context needed
    
    content += '</div>';
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
    console.log(`Saving preferred model: ${selectedModel}`);
    saveUserSetting({ 'preferredModelDeployment': selectedModel });
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
    toggleBtn.title = "View extracted text & analysis";
    toggleBtn.innerHTML = '<i class="bi bi-info-circle"></i> View Text';
  } else {
    // Show the info
    infoContainer.style.display = "block";
    toggleBtn.setAttribute("aria-expanded", true);
    toggleBtn.title = "Hide extracted text & analysis";
    toggleBtn.innerHTML = '<i class="bi bi-chevron-up"></i> Hide Text';
    
    // Load image info if not already loaded
    if (infoContainer.innerHTML.includes('Loading image information...')) {
      loadImageInfo(fullMessageObject, infoContainer);
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
    
    if (visionAnalysis.model_name) {
      content += `<div class="mt-1 text-muted" style="font-size: 0.85em;">Model: ${escapeHtml(visionAnalysis.model_name)}</div>`;
    }
    
    if (visionAnalysis.description) {
      content += '<div class="mt-2"><strong>Description:</strong><div class="p-2 bg-light border rounded">';
      content += escapeHtml(visionAnalysis.description);
      content += '</div></div>';
    }
    
    if (visionAnalysis.objects && Array.isArray(visionAnalysis.objects) && visionAnalysis.objects.length > 0) {
      content += '<div class="mt-2"><strong>Objects Detected:</strong><div class="p-2 bg-light border rounded">';
      content += visionAnalysis.objects.map(obj => `<span class="badge bg-secondary me-1">${escapeHtml(obj)}</span>`).join('');
      content += '</div></div>';
    }
    
    if (visionAnalysis.text && visionAnalysis.text.trim()) {
      content += '<div class="mt-2"><strong>Text Visible in Image:</strong><div class="p-2 bg-light border rounded">';
      content += escapeHtml(visionAnalysis.text);
      content += '</div></div>';
    }
    
    if (visionAnalysis.contextual_analysis && visionAnalysis.contextual_analysis.trim()) {
      content += '<div class="mt-2"><strong>Contextual Analysis:</strong><div class="p-2 bg-light border rounded">';
      content += escapeHtml(visionAnalysis.contextual_analysis);
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
