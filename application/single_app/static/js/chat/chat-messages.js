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
import { autoplayTTSIfEnabled } from "./chat-tts.js";
import { saveUserSetting } from "./chat-layout.js";
import { isStreamingEnabled, sendMessageWithStreaming } from "./chat-streaming.js";
import { getCurrentReasoningEffort, isReasoningEffortEnabled } from './chat-reasoning.js';
import { areAgentsEnabled } from './chat-agents.js';

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
  // Clear search highlights when loading a different conversation
  clearSearchHighlight();
  
  fetch(`/conversation/${conversationId}/messages`)
    .then((response) => response.json())
    .then((data) => {
      const chatbox = document.getElementById("chatbox");
      if (!chatbox) return;

      chatbox.innerHTML = "";
      console.log(`--- Loading messages for ${conversationId} ---`);
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
      if (chatbox) chatbox.innerHTML = `<div class="text-center p-3 text-danger">Error loading messages.</div>`;
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
    
    // Check if message is masked
    const isMasked = fullMessageObject?.metadata?.masked || (fullMessageObject?.metadata?.masked_ranges && fullMessageObject.metadata.masked_ranges.length > 0);
    const maskIcon = isMasked ? 'bi-front' : 'bi-back';
    const maskTitle = isMasked ? 'Unmask all masked content' : 'Mask entire message';
    
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
      withInlineCitations
    )}</textarea>
        `;
    
    const maskButtonHtml = `
            <button class="mask-btn btn btn-sm btn-link text-muted" data-message-id="${messageId}" title="${maskTitle}">
                <i class="bi ${maskIcon}"></i>
            </button>
        `;
    const actionsDropdownHtml = `
            <div class="dropdown">
                <button class="btn btn-sm btn-link text-muted" type="button" data-bs-toggle="dropdown" data-bs-boundary="viewport" data-bs-reference="parent" aria-expanded="false" title="More actions">
                    <i class="bi bi-three-dots"></i>
                </button>
                <ul class="dropdown-menu dropdown-menu-start">
                    <li><a class="dropdown-item dropdown-delete-btn" href="#" data-message-id="${messageId}"><i class="bi bi-trash me-2"></i>Delete</a></li>
                    <li><a class="dropdown-item dropdown-retry-btn" href="#" data-message-id="${messageId}"><i class="bi bi-arrow-clockwise me-2"></i>Retry</a></li>
                    ${feedbackHtml}
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
      citationToggleHtml = `<button class="btn btn-sm btn-link text-muted citation-toggle-btn" title="Show sources" aria-expanded="false" aria-controls="${citationsContainerId}"><i class="bi bi-journal-text"></i></button>`;
      // citationsButtonsHtml already contains a <div class="citations-container"> wrapper
      // Just add ID and display style by wrapping minimally
      citationContentContainerHtml = `<div id="${citationsContainerId}" style="display: none;">${citationsButtonsHtml}</div>`;
    } else {
      console.log(">>> Will NOT generate citation elements.");
    }

    const metadataContainerId = `metadata-${messageId || Date.now()}`;
    const metadataContainerHtml = `<div class="metadata-container mt-2 pt-2 border-top" id="${metadataContainerId}" style="display: none;"><div class="text-muted">Loading metadata...</div></div>`;
    
    const footerContentHtml = `<div class="message-footer d-flex justify-content-between align-items-center mt-2">
      <div class="d-flex align-items-center">${copyAndFeedbackHtml}</div>
      <div class="d-flex align-items-center"></div>
      <div class="d-flex align-items-center gap-2">${citationToggleHtml}<button class="btn btn-sm btn-link text-muted metadata-info-btn" data-message-id="${messageId}" title="Show metadata" aria-expanded="false" aria-controls="${metadataContainerId}">
        <i class="bi bi-info-circle"></i>
      </button></div>
    </div>`;

    // Build AI message inner HTML
    messageDiv.innerHTML = `
            <div class="message-content">
                <img src="${avatarImg}" alt="${avatarAltText}" class="avatar">
                <div class="message-bubble">
                    <div class="message-sender">${senderLabel}</div>
                    ${mainMessageHtml}
                    ${citationContentContainerHtml}
                    ${metadataContainerHtml}
                    ${footerContentHtml}
                </div>
            </div>`;

    messageDiv.classList.add(messageClass); // Add AI message class
    chatbox.appendChild(messageDiv); // Append AI message
    
    // Auto-play TTS if enabled (only for new messages, not when loading history)
    if (isNewMessage && typeof autoplayTTSIfEnabled === 'function') {
        autoplayTTSIfEnabled(messageId, messageContent);
    }
    
    // Highlight code blocks in the messages
    messageDiv.querySelectorAll('pre code[class^="language-"]').forEach((block) => {
      const match = block.className.match(/language-([a-zA-Z0-9]+)/);
      if (match && !block.hasAttribute('data-language')) {
        block.setAttribute('data-language', match[1]);
      }
      if (window.Prism) Prism.highlightElement(block);
    });

    // Apply masked state if message has masking
    if (fullMessageObject?.metadata) {
      console.log('Applying masked state for AI message:', messageId, fullMessageObject.metadata);
      applyMaskedState(messageDiv, fullMessageObject.metadata);
    } else {
      console.log('No metadata found for AI message:', messageId, 'fullMessageObject:', fullMessageObject);
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
    
    const maskBtn = messageDiv.querySelector(".mask-btn");
    if (maskBtn) {
      // Update tooltip dynamically on hover
      maskBtn.addEventListener("mouseenter", () => {
        updateMaskButtonTooltip(maskBtn, messageDiv);
      });
      
      // Handle mask button click
      maskBtn.addEventListener("click", () => {
        handleMaskButtonClick(messageDiv, messageId, messageContent);
      });
    }
    
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
      
      // Use agent display name if available, otherwise show AI with model
      if (agentDisplayName) {
        senderLabel = agentDisplayName;
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

    // Create message footer for user, image, and file messages
    let messageFooterHtml = "";
    let metadataContainerHtml = "";
    if (sender === "You") {
      const metadataContainerId = `metadata-${messageId || Date.now()}`;
      const isMasked = fullMessageObject?.metadata?.masked || (fullMessageObject?.metadata?.masked_ranges && fullMessageObject.metadata.masked_ranges.length > 0);
      const maskIcon = isMasked ? 'bi-front' : 'bi-back';
      const maskTitle = isMasked ? 'Unmask all masked content' : 'Mask entire message';
      
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
              </ul>
            </div>
            <button class="btn btn-sm btn-link text-muted copy-user-btn" data-message-id="${messageId}" title="Copy message">
              <i class="bi bi-copy"></i>
            </button>
            <button class="btn btn-sm btn-link text-muted mask-btn" data-message-id="${messageId}" title="${maskTitle}">
              <i class="bi ${maskIcon}"></i>
            </button>
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
    } else if (sender === "image" || sender === "File") {
      // Image and file messages get mask button on left, metadata button on right side
      const metadataContainerId = `metadata-${messageId || Date.now()}`;
      
      // Check if message is masked
      const isMasked = fullMessageObject?.metadata?.masked || (fullMessageObject?.metadata?.masked_ranges && fullMessageObject.metadata.masked_ranges.length > 0);
      const maskIcon = isMasked ? 'bi-front' : 'bi-back';
      const maskTitle = isMasked ? 'Unmask all masked content' : 'Mask entire message';
      
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
            <button class="btn btn-sm btn-link text-muted mask-btn" data-message-id="${messageId}" title="${maskTitle}">
              <i class="bi ${maskIcon}"></i>
            </button>
          </div>
          <div class="d-flex align-items-center"></div>
          <div class="d-flex align-items-center gap-2">${imageInfoToggleHtml}<button class="btn btn-sm btn-link text-muted metadata-info-btn" data-message-id="${messageId}" title="Show metadata" aria-expanded="false" aria-controls="${metadataContainerId}">
            <i class="bi bi-info-circle"></i>
          </button></div>
        </div>`;
      metadataContainerHtml = imageInfoContainerHtml + `<div class="metadata-container mt-2 pt-2 border-top" id="${metadataContainerId}" style="display: none;"><div class="text-muted">Loading metadata...</div></div>`;
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
                    <div class="message-sender">
                        ${senderLabel}
                        ${fullMessageObject?.metadata?.edited ? '<span class="badge bg-secondary ms-2">Edited</span>' : ''}
                        ${fullMessageObject?.metadata?.retried ? '<span class="badge bg-info ms-2">Retried</span>' : ''}
                    </div>
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
      
      // Apply masked state if message has masking
      if (fullMessageObject?.metadata) {
        console.log('Applying masked state for user message:', messageId, fullMessageObject.metadata);
        applyMaskedState(messageDiv, fullMessageObject.metadata);
      } else {
        console.log('No metadata found for user message:', messageId, 'fullMessageObject:', fullMessageObject);
      }
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
      const maskBtn = messageDiv.querySelector('.mask-btn');
      if (maskBtn) {
        // Update tooltip dynamically on hover
        maskBtn.addEventListener("mouseenter", () => {
          updateMaskButtonTooltip(maskBtn, messageDiv);
        });
        
        // Handle mask button click
        maskBtn.addEventListener("click", () => {
          handleMaskButtonClick(messageDiv, messageId, messageContent);
        });
      }
      
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
  
  // Only show loading indicator if NOT using streaming (streaming creates its own placeholder)
  if (!isStreamingEnabled()) {
    showLoadingIndicatorInChatbox();
  }

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
    if (selectedAgentOption) {
      agentInfo = {
        id: selectedAgentOption.dataset.agentId || null,
        name: selectedAgentOption.dataset.name || selectedAgentOption.value || '',
        display_name: selectedAgentOption.dataset.displayName || selectedAgentOption.textContent,
        is_global: selectedAgentOption.dataset.isGlobal === 'true',
        is_group: selectedAgentOption.dataset.isGroup === 'true',
        group_id: selectedAgentOption.dataset.groupId || null,
        group_name: selectedAgentOption.dataset.groupName || null
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
  
  // Prepare message data object
  // Get active public workspace ID from user settings (similar to active_group_id)
  const finalPublicWorkspaceId = window.activePublicWorkspaceId || null;
  
  const messageData = {
    message: finalMessageToSend,
    conversation_id: currentConversationId,
    hybrid_search: hybridSearchEnabled,
    selected_document_id: selectedDocumentId,
    classifications: classificationsToSend,
    image_generation: imageGenEnabled,
    doc_scope: effectiveDocScope,
    chat_type: chat_type,
    active_group_id: finalGroupId,
    active_public_workspace_id: finalPublicWorkspaceId,
    model_deployment: modelDeployment,
    prompt_info: promptInfo,
    agent_info: agentInfo,
    reasoning_effort: getCurrentReasoningEffort()
  };
  
  // Check if streaming is enabled (but not for image generation)
  const agentsEnabled = typeof areAgentsEnabled === 'function' && areAgentsEnabled();
  if (isStreamingEnabled() && !imageGenEnabled) {
    const streamInitiated = sendMessageWithStreaming(
      messageData, 
      tempUserMessageId, 
      currentConversationId
    );
    if (streamInitiated) {
      return; // Streaming handles the rest
    }
    // If streaming failed to initiate, fall through to regular fetch
  }
  
  // Regular non-streaming fetch
  fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    credentials: "same-origin",
    body: JSON.stringify(messageData),
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
      console.log(`data.user_message_id: ${data.user_message_id}`);
      console.log(`tempUserMessageId: ${tempUserMessageId}`);

      // Update the user message with the real message ID
      if (data.user_message_id) {
        console.log(`🔄 Calling updateUserMessageId(${tempUserMessageId}, ${data.user_message_id})`);
        updateUserMessageId(tempUserMessageId, data.user_message_id);
      } else {
        console.warn(`⚠️ No user_message_id in response! User message will keep temporary ID: ${tempUserMessageId}`);
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
          data.agent_name, // Pass agent name
          null, // fullMessageObject
          true // isNewMessage - trigger autoplay for new responses
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

      if (data.reload_messages && currentConversationId) {
        console.log("Reload flag received from backend - refreshing messages.");
        loadMessages(currentConversationId);
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
          console.log('[sendMessage] New conversation created, adding to list without reload');
          addConversationToList(
            currentConversationId,
            data.conversation_title,
            data.classification || []
          );
          // Don't call selectConversation here - messages are already displayed
          // Just update the current conversation ID and title
          window.currentConversationId = currentConversationId;
          document.getElementById("current-conversation-title").textContent = data.conversation_title || "New Conversation";
          console.log('[sendMessage] New conversation setup complete, conversation ID:', currentConversationId);
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
    console.error(`❌ Message div with temp ID ${tempId} not found for update`);
  }
}

// Helper function to attach event listeners to user message buttons
function attachUserMessageEventListeners(messageDiv, messageId, messageContent) {
  const copyBtn = messageDiv.querySelector(".copy-user-btn");
  const metadataToggleBtn = messageDiv.querySelector(".metadata-toggle-btn");
  const maskBtn = messageDiv.querySelector(".mask-btn");
  
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
  
  if (maskBtn) {
    // Update tooltip dynamically on hover
    maskBtn.addEventListener("mouseenter", () => {
      updateMaskButtonTooltip(maskBtn, messageDiv);
    });
    
    // Handle mask button click
    maskBtn.addEventListener("click", () => {
      handleMaskButtonClick(messageDiv, messageId, messageContent);
    });
  }
  
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
    
    if (metadata.button_states.document_search !== undefined) {
      content += `<div class="mb-1"><span class="text-muted">Document Search:</span> <span class="ms-2">${createStatusBadge(metadata.button_states.document_search)}</span></div>`;
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
      const imageId = `image-${messageId || Date.now()}-${index}`;
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
      if (metadata.timestamp) html += `<div class="mb-1"><span class="text-muted">Timestamp:</span> <code class="ms-2">${new Date(metadata.timestamp).toLocaleString()}</code></div>`;
      html += '</div></div>';
      
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
        if (metadata.agent_display_name) html += `<div class="mb-1"><span class="text-muted">Agent Display Name:</span> <span class="ms-2">${metadata.agent_display_name}</span></div>`;
        
        // Assistant-specific info
        if (metadata.role === 'assistant') {
          if (metadata.augmented !== undefined) html += `<div class="mb-1"><span class="text-muted">Augmented:</span> <span class="ms-2 badge ${metadata.augmented ? 'bg-success' : 'bg-secondary'}">${metadata.augmented ? 'Yes' : 'No'}</span></div>`;
          if (metadata.metadata?.reasoning_effort) html += `<div class="mb-1"><span class="text-muted">Reasoning Effort:</span> <code class="ms-2">${metadata.metadata.reasoning_effort}</code></div>`;
          if (metadata.hybrid_citations && metadata.hybrid_citations.length > 0) html += `<div class="mb-1"><span class="text-muted">Document Citations:</span> <span class="ms-2 badge bg-info">${metadata.hybrid_citations.length}</span></div>`;
          if (metadata.agent_citations && metadata.agent_citations.length > 0) html += `<div class="mb-1"><span class="text-muted">Agent Citations:</span> <span class="ms-2 badge bg-info">${metadata.agent_citations.length}</span></div>`;
        }
        
        html += '</div></div>';
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

/**
 * Apply masked state to a message when loading from database
 */
function applyMaskedState(messageDiv, metadata) {
  if (!metadata) return;
  
  const messageText = messageDiv.querySelector('.message-text');
  const messageFooter = messageDiv.querySelector('.message-footer');
  
  if (!messageText) return;
  
  // Check if entire message is masked
  if (metadata.masked) {
    messageDiv.classList.add('fully-masked');
    
    // Add exclusion badge to footer if not already present
    if (messageFooter && !messageFooter.querySelector('.message-exclusion-badge')) {
      const badge = document.createElement('div');
      badge.className = 'message-exclusion-badge text-warning small';
      badge.innerHTML = '<i class="bi bi-exclamation-triangle-fill"></i>';
      messageFooter.appendChild(badge);
    }
    return;
  }
  
  // Apply masked ranges if they exist
  if (metadata.masked_ranges && metadata.masked_ranges.length > 0) {
    const content = messageText.textContent;
    let htmlContent = '';
    let lastIndex = 0;
    
    // Sort masked ranges by start position
    const sortedRanges = [...metadata.masked_ranges].sort((a, b) => a.start - b.start);
    
    // Build HTML with masked spans
    sortedRanges.forEach(range => {
      // Add text before masked range
      if (range.start > lastIndex) {
        htmlContent += escapeHtml(content.substring(lastIndex, range.start));
      }
      
      // Add masked span
      const maskedText = escapeHtml(content.substring(range.start, range.end));
      const timestamp = new Date(range.timestamp).toLocaleDateString();
      htmlContent += `<span class="masked-content" data-mask-id="${range.id}" data-user-id="${range.user_id}" data-display-name="${range.display_name}" title="Masked by ${range.display_name} on ${timestamp}">${maskedText}</span>`;
      
      lastIndex = range.end;
    });
    
    // Add remaining text after last masked range
    if (lastIndex < content.length) {
      htmlContent += escapeHtml(content.substring(lastIndex));
    }
    
    // Update message text with masked content
    messageText.innerHTML = htmlContent;
  }
}

/**
 * Update mask button tooltip based on current selection and mask state
 */
function updateMaskButtonTooltip(maskBtn, messageDiv) {
  const messageBubble = messageDiv.querySelector('.message-bubble');
  if (!messageBubble) return;
  
  // Check if there's a text selection within this message
  const selection = window.getSelection();
  const hasSelection = selection && selection.toString().trim().length > 0;
  
  // Verify selection is within this message bubble
  let selectionInMessage = false;
  if (hasSelection && selection.anchorNode) {
    selectionInMessage = messageBubble.contains(selection.anchorNode);
  }
  
  // Check current mask state
  const isMasked = messageDiv.querySelector('.masked-content') || messageDiv.classList.contains('fully-masked');
  
  // Update tooltip based on state
  if (isMasked) {
    maskBtn.title = 'Unmask all masked content';
  } else if (selectionInMessage) {
    maskBtn.title = 'Mask selected content';
  } else {
    maskBtn.title = 'Mask entire message';
  }
}

/**
 * Handle mask button click - masks entire message or selected content
 */
function handleMaskButtonClick(messageDiv, messageId, messageContent) {
  const messageBubble = messageDiv.querySelector('.message-bubble');
  const messageText = messageDiv.querySelector('.message-text');
  const maskBtn = messageDiv.querySelector('.mask-btn');
  
  if (!messageBubble || !messageText || !maskBtn) {
    console.error('Required elements not found for masking');
    return;
  }
  
  // Check if message is currently masked
  const isMasked = messageDiv.querySelector('.masked-content') || messageDiv.classList.contains('fully-masked');
  
  if (isMasked) {
    // Unmask all
    unmaskMessage(messageDiv, messageId, maskBtn);
    return;
  }
  
  // Check for text selection within message
  const selection = window.getSelection();
  const hasSelection = selection && selection.toString().trim().length > 0;
  
  let selectionInMessage = false;
  if (hasSelection && selection.anchorNode) {
    selectionInMessage = messageBubble.contains(selection.anchorNode);
  }
  
  if (selectionInMessage) {
    // Mask selection
    maskSelection(messageDiv, messageId, selection, messageText, maskBtn);
  } else {
    // Mask entire message
    maskEntireMessage(messageDiv, messageId, maskBtn);
  }
}

/**
 * Mask the entire message
 */
function maskEntireMessage(messageDiv, messageId, maskBtn) {
  console.log(`Masking entire message: ${messageId}`);
  
  // Get user info
  const userDisplayName = window.currentUser?.display_name || 'Unknown User';
  const userId = window.currentUser?.id || 'unknown';
  
  console.log('Mask entire message - User info:', { userId, userDisplayName, windowCurrentUser: window.currentUser });
  
  const payload = {
    action: 'mask_all',
    user_id: userId,
    display_name: userDisplayName
  };
  
  console.log('Mask entire message - Sending payload:', payload);
  
  // Call API to mask message
  fetch(`/api/message/${messageId}/mask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload)
  })
  .then(response => {
    console.log('Mask entire message - Response status:', response.status);
    if (!response.ok) {
      return response.json().then(err => {
        console.error('Mask entire message - Error response:', err);
        throw new Error(err.error || 'Failed to mask message');
      });
    }
    return response.json();
  })
  .then(data => {
    console.log('Mask entire message - Success response:', data);
    if (data.success) {
      // Add fully-masked class and exclusion badge
      messageDiv.classList.add('fully-masked');
      
      // Update mask button
      const icon = maskBtn.querySelector('i');
      icon.className = 'bi bi-front';
      maskBtn.title = 'Unmask all masked content';
      
      // Add exclusion badge to footer if not already present
      const messageFooter = messageDiv.querySelector('.message-footer');
      if (messageFooter && !messageFooter.querySelector('.message-exclusion-badge')) {
        const badge = document.createElement('div');
        badge.className = 'message-exclusion-badge text-warning small';
        badge.innerHTML = '<i class="bi bi-exclamation-triangle-fill"></i>';
        messageFooter.appendChild(badge);
      }
      
      showToast('Message masked successfully', 'success');
    } else {
      showToast('Failed to mask message', 'error');
    }
  })
  .catch(error => {
    console.error('Error masking message:', error);
    showToast('Error masking message', 'error');
  });
}

/**
 * Mask selected text content
 */
function maskSelection(messageDiv, messageId, selection, messageText, maskBtn) {
  const selectedText = selection.toString().trim();
  console.log(`Masking selection in message: ${messageId}`);
  
  // Get the range and calculate character offsets
  const range = selection.getRangeAt(0);
  const preSelectionRange = range.cloneRange();
  preSelectionRange.selectNodeContents(messageText);
  preSelectionRange.setEnd(range.startContainer, range.startOffset);
  const start = preSelectionRange.toString().length;
  const end = start + selectedText.length;
  
  // Get user info
  const userDisplayName = window.currentUser?.display_name || 'Unknown User';
  const userId = window.currentUser?.id || 'unknown';
  
  console.log('Mask selection - User info:', { userId, userDisplayName, windowCurrentUser: window.currentUser });
  console.log('Mask selection - Range:', { start, end, selectedText });
  
  const payload = {
    action: 'mask_selection',
    selection: {
      start: start,
      end: end,
      text: selectedText
    },
    user_id: userId,
    display_name: userDisplayName
  };
  
  console.log('Mask selection - Sending payload:', payload);
  
  // Call API to mask selection
  fetch(`/api/message/${messageId}/mask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload)
  })
  .then(response => {
    console.log('Mask selection - Response status:', response.status);
    if (!response.ok) {
      return response.json().then(err => {
        console.error('Mask selection - Error response:', err);
        throw new Error(err.error || 'Failed to mask selection');
      });
    }
    return response.json();
  })
  .then(data => {
    console.log('Mask selection - Success response:', data);
    if (data.success) {
      // Wrap selected text with masked span
      const maskId = data.masked_ranges[data.masked_ranges.length - 1].id;
      const span = document.createElement('span');
      span.className = 'masked-content';
      span.setAttribute('data-mask-id', maskId);
      span.setAttribute('data-user-id', userId);
      span.setAttribute('data-display-name', userDisplayName);
      span.title = `Masked by ${userDisplayName}`;
      
      // Use extractContents and insertNode to handle complex selections
      try {
        const contents = range.extractContents();
        span.appendChild(contents);
        range.insertNode(span);
      } catch (e) {
        console.error('Error wrapping selection:', e);
        // Fallback: reload the message to show the masked content
        location.reload();
        return;
      }
      selection.removeAllRanges();
      
      // Update mask button
      const icon = maskBtn.querySelector('i');
      icon.className = 'bi bi-front';
      maskBtn.title = 'Unmask all masked content';
      
      showToast('Selection masked successfully', 'success');
    } else {
      showToast('Failed to mask selection', 'error');
    }
  })
  .catch(error => {
    console.error('Error masking selection:', error);
    showToast('Error masking selection', 'error');
  });
}

/**
 * Unmask all masked content in a message
 */
function unmaskMessage(messageDiv, messageId, maskBtn) {
  console.log(`Unmasking message: ${messageId}`);
  
  // Call API to unmask
  fetch(`/api/message/${messageId}/mask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      action: 'unmask_all'
    })
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      // Remove fully-masked class
      messageDiv.classList.remove('fully-masked');
      
      // Remove all masked-content spans
      const maskedSpans = messageDiv.querySelectorAll('.masked-content');
      maskedSpans.forEach(span => {
        const text = document.createTextNode(span.textContent);
        span.parentNode.replaceChild(text, span);
      });
      
      // Remove exclusion badge
      const badge = messageDiv.querySelector('.message-exclusion-badge');
      if (badge) {
        badge.remove();
      }
      
      // Update mask button
      const icon = maskBtn.querySelector('i');
      icon.className = 'bi bi-back';
      maskBtn.title = 'Mask entire message';
      
      showToast('Message unmasked successfully', 'success');
    } else {
      showToast('Failed to unmask message', 'error');
    }
  })
  .catch(error => {
    console.error('Error unmasking message:', error);
    showToast('Error unmasking message', 'error');
  });
}

// ============= Message Deletion Functions =============

/**
 * Handle delete button click - shows confirmation modal
 */
function handleDeleteButtonClick(messageDiv, messageId, messageType) {
  console.log(`Delete button clicked for ${messageType} message: ${messageId}`);
  
  // Store message info for deletion confirmation
  window.pendingMessageDeletion = {
    messageDiv,
    messageId,
    messageType
  };
  
  // Show appropriate confirmation modal
  if (messageType === 'user') {
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
        if (messageType === 'assistant') {
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
  
  const { messageDiv, messageId, messageType } = pendingDeletion;
  
  console.log(`Executing deletion for message ${messageId}, deleteThread: ${deleteThread}`);
  console.log(`Message div:`, messageDiv);
  console.log(`Message ID from DOM:`, messageDiv ? messageDiv.getAttribute('data-message-id') : 'N/A');
  
  // Call delete API
  fetch(`/api/message/${messageId}`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      delete_thread: deleteThread
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
  applySearchHighlight,
  clearSearchHighlight,
  scrollToMessageSmooth
};

// Expose deletion function globally for modal buttons
window.executeMessageDeletion = executeMessageDeletion;
