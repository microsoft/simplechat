// chat-citations.js

import { showToast } from "./chat-toast.js";
import { showLoadingIndicator, hideLoadingIndicator } from "./chat-loading-indicator.js";
import { toBoolean } from "./chat-utils.js";
import { fetchFileContent } from "./chat-input-actions.js";
// --- NEW IMPORT ---
import { getDocumentMetadata } from './chat-documents.js';
import { showEnhancedCitationModal } from './chat-enhanced-citations.js';
// ------------------

const chatboxEl = document.getElementById("chatbox");

export function parseDocIdAndPage(citationId) {
  // ... (keep existing implementation)
  const underscoreIndex = citationId.lastIndexOf("_");
  if (underscoreIndex === -1) {
    return { docId: null, pageNumber: null };
  }
  const docId = citationId.substring(0, underscoreIndex);
  const pageNumber = citationId.substring(underscoreIndex + 1);
  return { docId, pageNumber };
}

export function parseCitations(message) {
  // ... (keep existing implementation)
  const citationRegex = /\(Source:\s*([^,]+),\s*Page(?:s)?:\s*([^)]+)\)\s*((?:\[#.*?\]\s*)+)/gi;

  return message.replace(citationRegex, (whole, filename, pages, bracketSection) => {
    let filenameHtml;
    if (/^https?:\/\/.+/i.test(filename.trim())) {
      filenameHtml = `<a href="${filename.trim()}" target="_blank" rel="noopener noreferrer">${filename.trim()}</a>`;
    } else {
      filenameHtml = filename.trim();
    }

    const bracketMatches = bracketSection.match(/\[#.*?\]/g) || [];
    const pageToRefMap = {};

    bracketMatches.forEach((match) => {
      let inner = match.slice(2, -1).trim();
      const refs = inner.split(/[;,]/);
      refs.forEach((r) => {
        let ref = r.trim();
        if (ref.startsWith('#')) ref = ref.slice(1);
        const parts = ref.split('_');
        const pageNumber = parts.pop();
        // Ensure docId part is also captured if needed, though ref is the full ID here
        // const docIdPart = parts.join('_');
        pageToRefMap[pageNumber] = ref; // ref is the full citationId like 'docid_pagenum'
      });
    });

    function getDocPrefix(ref) {
      const underscoreIndex = ref.lastIndexOf('_');
      return underscoreIndex === -1 ? ref : ref.slice(0, underscoreIndex + 1);
    }

    const pagesTokens = pages.split(/,/).map(tok => tok.trim());
    const linkedTokens = pagesTokens.map(token => {
      const dashParts = token.split(/[–—-]/).map(p => p.trim());

      if (dashParts.length === 2 && dashParts[0] && dashParts[1]) {
        const startNum = parseInt(dashParts[0], 10);
        const endNum   = parseInt(dashParts[1], 10);

        if (!isNaN(startNum) && !isNaN(endNum)) {
          let discoveredPrefix = '';
          if (pageToRefMap[startNum]) {
            discoveredPrefix = getDocPrefix(pageToRefMap[startNum]);
          } else if (pageToRefMap[endNum]) {
            discoveredPrefix = getDocPrefix(pageToRefMap[endNum]);
          }

          const increment = startNum <= endNum ? 1 : -1;
          const pageAnchors = [];
          for (let p = startNum; increment > 0 ? p <= endNum : p >= endNum; p += increment) {
            if (!pageToRefMap[p] && discoveredPrefix) {
              pageToRefMap[p] = discoveredPrefix + p;
            }
            // Use the full citation ID (ref) from the map for the anchor
            pageAnchors.push(buildAnchorIfExists(String(p), pageToRefMap[p]));
          }
          return pageAnchors.join(', ');
        }
      }

      const singleNum = parseInt(token, 10);
      if (!isNaN(singleNum)) {
        const ref = pageToRefMap[singleNum];
        return buildAnchorIfExists(token, ref);
      }
      return token;
    });

    const linkedPagesText = linkedTokens.join(', ');
    return `(Source: ${filenameHtml}, Pages: ${linkedPagesText})`;
  });
}


export function buildAnchorIfExists(pageStr, citationId) {
  // ... (keep existing implementation)
   if (!citationId) {
    return pageStr;
  }
  // Ensure citationId doesn't have a leading # if passed accidentally
  const cleanCitationId = citationId.startsWith('#') ? citationId.slice(1) : citationId;
  return `<a href="#" class="citation-link" data-citation-id="${cleanCitationId}" target="_blank" rel="noopener noreferrer">${pageStr}</a>`;
}

// --- MODIFIED: fetchCitedText handles errors more gracefully ---
export function fetchCitedText(citationId) {
  showLoadingIndicator();
  fetch("/api/get_citation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ citation_id: citationId }),
  })
    .then((response) => {
        if (!response.ok) {
            // Try to parse error message from JSON response if possible
            return response.json().then(errData => {
                // Throw an error that includes the server's message
                throw new Error(errData.error || `Server responded with status ${response.status}`);
            }).catch(() => {
                 // If parsing JSON fails, throw a generic error
                 throw new Error(`Server responded with status ${response.status}`);
            });
        }
        return response.json();
    })
    .then((data) => {
      hideLoadingIndicator();

      // Check for expected data fields explicitly
      if (data.cited_text !== undefined && data.file_name && data.page_number !== undefined) {
        showCitedTextPopup(data.cited_text, data.file_name, data.page_number);
      } else if (data.error) { // Handle explicit errors from server even on 200 OK
         showToast(`Could not retrieve citation: ${data.error}`, "warning");
      } else {
         // Handle cases where the response is OK but data is missing
         console.warn("Received citation response but required data is missing:", data);
         showToast("Citation data incomplete.", "warning");
      }
    })
    .catch((error) => {
      hideLoadingIndicator();
      console.error("Error fetching cited text:", error);
      // Show the error message from the caught error
      showToast(`Error fetching citation: ${error.message}`, "danger");
    });
}

export function showCitedTextPopup(citedText, fileName, pageNumber) {
  // ... (keep existing implementation)
  let modalContainer = document.getElementById("citation-modal");
  if (!modalContainer) {
    modalContainer = document.createElement("div");
    modalContainer.id = "citation-modal";
    modalContainer.classList.add("modal", "fade");
    modalContainer.tabIndex = -1;
    modalContainer.setAttribute("aria-hidden", "true");

    modalContainer.innerHTML = `
      <div class="modal-dialog modal-dialog-scrollable modal-xl modal-fullscreen-sm-down">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Source: ${fileName}, Page: ${pageNumber}</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <pre id="cited-text-content"></pre>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modalContainer);
  } else {
    const modalTitle = modalContainer.querySelector(".modal-title");
    if (modalTitle) {
      modalTitle.textContent = `Source: ${fileName}, Page: ${pageNumber}`;
    }
  }

  const citedTextContent = document.getElementById("cited-text-content");
  if (citedTextContent) {
    citedTextContent.textContent = citedText;
  }

  const modal = new bootstrap.Modal(modalContainer);
  modal.show();
}

export function showImagePopup(imageSrc) {
  // ... (keep existing implementation)
  let modalContainer = document.getElementById("image-modal");
  if (!modalContainer) {
    modalContainer = document.createElement("div");
    modalContainer.id = "image-modal";
    modalContainer.classList.add("modal", "fade");
    modalContainer.tabIndex = -1;
    modalContainer.setAttribute("aria-hidden", "true");

    modalContainer.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-body text-center">
            <img
              id="image-modal-img"
              src=""
              alt="Generated Image"
              class="img-fluid"
            />
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modalContainer);
  }
  const modalImage = modalContainer.querySelector("#image-modal-img");
  if (modalImage) {
    modalImage.src = imageSrc;
  }
  const modal = new bootstrap.Modal(modalContainer);
  modal.show();
}

export function showMetadataModal(metadataType, metadataContent, fileName) {
  // Create or reuse the metadata modal
  let modalContainer = document.getElementById("metadata-modal");
  if (!modalContainer) {
    modalContainer = document.createElement("div");
    modalContainer.id = "metadata-modal";
    modalContainer.classList.add("modal", "fade");
    modalContainer.tabIndex = -1;
    modalContainer.setAttribute("aria-hidden", "true");

    modalContainer.innerHTML = `
      <div class="modal-dialog modal-dialog-scrollable modal-lg modal-fullscreen-sm-down">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="metadata-modal-title">Document Metadata</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="mb-2">
              <strong>File:</strong> <span id="metadata-file-name"></span>
            </div>
            <div class="mb-2">
              <strong>Type:</strong> <span id="metadata-type" class="badge bg-info"></span>
            </div>
            <div class="mt-3">
              <strong>Content:</strong>
              <div id="metadata-content" class="mt-2 p-3 bg-light rounded" style="white-space: pre-wrap; max-height: 60vh; overflow-y: auto;"></div>
            </div>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modalContainer);
  }

  // Update modal content
  const modalTitle = modalContainer.querySelector("#metadata-modal-title");
  const fileNameEl = modalContainer.querySelector("#metadata-file-name");
  const metadataTypeEl = modalContainer.querySelector("#metadata-type");
  const metadataContentEl = modalContainer.querySelector("#metadata-content");

  if (modalTitle) {
    modalTitle.textContent = `Document Metadata - ${metadataType.charAt(0).toUpperCase() + metadataType.slice(1)}`;
  }
  if (fileNameEl) {
    fileNameEl.textContent = fileName;
  }
  if (metadataTypeEl) {
    metadataTypeEl.textContent = metadataType.charAt(0).toUpperCase() + metadataType.slice(1);
  }
  if (metadataContentEl) {
    metadataContentEl.textContent = metadataContent;
  }

  const modal = new bootstrap.Modal(modalContainer);
  modal.show();
}

export function showAgentCitationModal(toolName, toolArgs, toolResult) {
  // Create or reuse the agent citation modal
  let modalContainer = document.getElementById("agent-citation-modal");
  if (!modalContainer) {
    modalContainer = document.createElement("div");
    modalContainer.id = "agent-citation-modal";
    modalContainer.classList.add("modal", "fade");
    modalContainer.tabIndex = -1;
    modalContainer.setAttribute("aria-hidden", "true");

    modalContainer.innerHTML = `
      <div class="modal-dialog modal-dialog-scrollable modal-xl modal-fullscreen-sm-down">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Agent Tool Execution</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="mb-3">
              <h6 class="fw-bold">Tool Name:</h6>
              <div id="agent-tool-name" class="bg-light p-2 rounded"></div>
            </div>
            <div class="mb-3">
              <h6 class="fw-bold">Function Arguments:</h6>
              <pre id="agent-tool-args" class="bg-light p-2 rounded" style="white-space: pre-wrap; word-wrap: break-word;"></pre>
            </div>
            <div class="mb-3">
              <h6 class="fw-bold">Function Result:</h6>
              <pre id="agent-tool-result" class="bg-light p-2 rounded" style="white-space: pre-wrap; word-wrap: break-word;"></pre>
            </div>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modalContainer);
  }

  // Update the content
  const toolNameEl = document.getElementById("agent-tool-name");
  const toolArgsEl = document.getElementById("agent-tool-args");
  const toolResultEl = document.getElementById("agent-tool-result");

  if (toolNameEl) {
    toolNameEl.textContent = toolName || "Unknown";
  }
  
  if (toolArgsEl) {
    // Handle empty or no parameters more gracefully
    let argsContent = "";
    
    try {
      let parsedArgs;
      if (!toolArgs || toolArgs === "" || toolArgs === "{}") {
        argsContent = "No parameters required";
      } else {
        parsedArgs = JSON.parse(toolArgs);
        // Check if it's an empty object
        if (typeof parsedArgs === 'object' && Object.keys(parsedArgs).length === 0) {
          argsContent = "No parameters required";
        } else {
          argsContent = JSON.stringify(parsedArgs, null, 2);
        }
      }
    } catch (e) {
      // If it's not valid JSON, check if it's an object representation
      if (toolArgs === "[object Object]" || !toolArgs || toolArgs.trim() === "") {
        argsContent = "No parameters required";
      } else {
        argsContent = toolArgs;
      }
    }
    
    // Add truncation with expand/collapse if content is long
    if (argsContent.length > 300 && argsContent !== "No parameters required") {
      const truncatedContent = argsContent.substring(0, 300);
      const remainingContent = argsContent.substring(300);
      
      toolArgsEl.innerHTML = `
        <div class="args-content position-relative">
          <span class="args-truncated">${escapeHtml(truncatedContent)}</span><span class="args-remaining" style="display: none;">${escapeHtml(remainingContent)}</span>
          <button class="btn btn-link p-0 ms-2 expand-args-btn" 
                  style="font-size: 0.75rem; text-decoration: none; vertical-align: baseline;" 
                  onclick="toggleArgsExpansion(this)">
            <i class="bi bi-chevron-down" style="font-size: 0.7rem;"></i>
          </button>
        </div>
      `;
    } else {
      toolArgsEl.textContent = argsContent;
    }
  }
  
  if (toolResultEl) {
    // Handle result formatting and truncation with expand/collapse
    let resultContent = "";
    
    try {
      let parsedResult;
      if (!toolResult || toolResult === "" || toolResult === "{}") {
        resultContent = "No result";
      } else if (toolResult === "[object Object]") {
        resultContent = "No result data available";
      } else {
        // Try to parse as JSON first
        try {
          parsedResult = JSON.parse(toolResult);
          resultContent = JSON.stringify(parsedResult, null, 2);
        } catch (parseError) {
          // If not JSON, treat as string
          resultContent = toolResult;
        }
      }
    } catch (e) {
      resultContent = toolResult || "No result";
    }
    
    // Add truncation with expand/collapse if content is long
    if (resultContent.length > 300) {
      const truncatedContent = resultContent.substring(0, 300);
      const remainingContent = resultContent.substring(300);
      
      toolResultEl.innerHTML = `
        <div class="result-content position-relative">
          <span class="result-truncated">${escapeHtml(truncatedContent)}</span><span class="result-remaining" style="display: none;">${escapeHtml(remainingContent)}</span>
          <button class="btn btn-link p-0 ms-2 expand-result-btn" 
                  style="font-size: 0.75rem; text-decoration: none; vertical-align: baseline;" 
                  onclick="toggleResultExpansion(this)">
            <i class="bi bi-chevron-down" style="font-size: 0.7rem;"></i>
          </button>
        </div>
      `;
    } else {
      toolResultEl.textContent = resultContent;
    }
  }

  const modal = new bootstrap.Modal(modalContainer);
  modal.show();
}

// --- MODIFIED: Added citationId parameter and fallback in catch ---
export function showPdfModal(docId, pageNumber, citationId) {
  const fetchUrl = `/view_pdf?doc_id=${encodeURIComponent(docId)}&page=${encodeURIComponent(pageNumber)}`;

  let pdfModal = document.getElementById("pdf-modal");
  if (!pdfModal) {
    pdfModal = document.createElement("div");
    pdfModal.id = "pdf-modal";
    pdfModal.classList.add("modal", "fade");
    pdfModal.tabIndex = -1;
    pdfModal.innerHTML = `
      <div class="modal-dialog modal-dialog-scrollable modal-xl modal-fullscreen-sm-down">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Citation +/- one page</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body" style="height:80vh;">
            <iframe
              id="pdf-iframe"
              src=""
              style="width:100%; height:100%; border:none;"
            ></iframe>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(pdfModal);
  }

  showLoadingIndicator();

  fetch(fetchUrl)
    .then(async (resp) => {
      // Keep existing success logic
      if (!resp.ok) {
         // Throw an error to be caught by the .catch block
         const errorText = await resp.text(); // Try to get more info
         throw new Error(`Failed to load PDF. Status: ${resp.status}. ${errorText.substring(0, 100)}`);
      }
       hideLoadingIndicator(); // Hide indicator ONLY on successful fetch response start

      const newPage = resp.headers.get("X-Sub-PDF-Page") || "1";
      const blob = await resp.blob();
      const pdfBlobUrl = URL.createObjectURL(blob);
      const iframeSrc = pdfBlobUrl + `#page=${newPage}`;
      const iframe = pdfModal.querySelector("#pdf-iframe");
      if (iframe) {
        iframe.src = iframeSrc;
        // Ensure modal is shown AFTER iframe src is set
         const modalInstance = new bootstrap.Modal(pdfModal);
         modalInstance.show();
      } else {
          // Should not happen if modal structure is correct
          console.error("PDF iframe element not found after creating modal.");
          showToast("Error displaying PDF viewer.", "danger");
           // Fallback if iframe fails to load? Maybe too complex.
           // fetchCitedText(citationId);
      }

    })
    .catch((error) => {
      // --- FALLBACK LOGIC ---
      hideLoadingIndicator(); // Ensure indicator is hidden on error
      console.error("Error fetching PDF, falling back to text citation:", error);
      // showToast(`Could not load PDF preview: ${error.message}. Falling back to text citation.`, "warning");
      // Call the text-based citation fetcher
      fetchCitedText(citationId);
      // --- END FALLBACK ---

      // Ensure modal doesn't linger if PDF fetch failed before showing
      const maybeModalInstance = bootstrap.Modal.getInstance(pdfModal);
      if (maybeModalInstance) {
          maybeModalInstance.hide();
      }
    });
}
// --------------------------------------------------------------------

// --- MODIFIED: Event Listener Logic ---
if (chatboxEl) {
  chatboxEl.addEventListener("click", (event) => {
    const target = event.target.closest('a'); // Find the nearest ancestor anchor tag

    // Check if it's an inline citation link OR a hybrid citation button
    if (target && (target.matches("a.citation-link") || target.matches("a.citation-button.hybrid-citation-link"))) {
      event.preventDefault();
      const citationId = target.getAttribute("data-citation-id");
      if (!citationId) {
          console.warn("Citation link/button clicked but data-citation-id is missing.");
          showToast("Cannot process citation: Missing ID.", "warning");
          return;
      }

      // Check if this is a metadata citation
      const isMetadata = target.getAttribute("data-is-metadata") === "true";
      if (isMetadata) {
          // Show metadata content directly in a modal
          const metadataType = target.getAttribute("data-metadata-type");
          const metadataContent = target.getAttribute("data-metadata-content");
          const fileName = citationId.split('_')[0]; // Extract filename from citation ID
          
          showMetadataModal(metadataType, metadataContent, fileName);
          return;
      }

      const { docId, pageNumber } = parseDocIdAndPage(citationId);

      // Safety check: Ensure docId and pageNumber were parsed correctly
      if (!docId || !pageNumber) {
          console.warn(`Could not parse docId/pageNumber from citationId: ${citationId}. Falling back to text citation.`);
          // showToast("Could not identify document source, showing text.", "info");
          fetchCitedText(citationId); // Fallback to text if parsing fails
          return;
      }

      // --- Logic to decide between PDF and Text ---
      const useEnhancedGlobally = toBoolean(window.enableEnhancedCitations);
      let attemptEnhanced = false; // Default to not attempting enhanced

      if (useEnhancedGlobally) {
          // console.log(`Checking metadata for docId: ${docId}`);
          const docMetadata = getDocumentMetadata(docId); // Fetch metadata

          // Decide based on metadata:
          // Attempt enhanced if:
          // 1. Metadata found AND enhanced_citations is NOT explicitly false
          // 2. Metadata not found (assume enhanced might be possible, rely on error fallback)
          if (!docMetadata) {
              // console.log(`Metadata not found for ${docId}, attempting enhanced citation (will fallback on error).`);
              attemptEnhanced = true;
          } else if (docMetadata.enhanced_citations === false) {
              // console.log(`Metadata found for ${docId}, enhanced_citations is false. Using text citation.`);
              attemptEnhanced = false; // Explicitly disabled for this doc
          } else {
              // console.log(`Metadata found for ${docId}, enhanced_citations is true or undefined. Attempting enhanced citation.`);
              attemptEnhanced = true; // Includes cases where metadata exists but enhanced_citations is true, null, or undefined
          }
      } else {
        // console.log("Global enhanced citations disabled. Using text citation.");
        attemptEnhanced = false; // Globally disabled
      }

      // --- Execute based on the decision ---
      if (attemptEnhanced) {
          // console.log(`Attempting Enhanced Citation for ${docId}, page/timestamp ${pageNumber}, citationId ${citationId}`);
          // Use new enhanced citation system that supports multiple file types
          showEnhancedCitationModal(docId, pageNumber, citationId);
      } else {
          // console.log(`Fetching Text Citation for ${citationId}`);
          // Use text citation if globally disabled OR explicitly disabled for this doc OR if parsing failed earlier
          fetchCitedText(citationId);
      }
      // --- End Logic ---

    } else if (target && target.matches("a.agent-citation-link")) { // Handle agent citation links
      event.preventDefault();
      const toolName = target.getAttribute("data-tool-name");
      const toolArgs = target.getAttribute("data-tool-args");
      const toolResult = target.getAttribute("data-tool-result");
      
      if (!toolName) {
        console.warn("Agent citation link clicked but data-tool-name is missing.");
        showToast("Cannot process agent citation: Missing tool name.", "warning");
        return;
      }
      
      showAgentCitationModal(toolName, toolArgs, toolResult);
      
    } else if (target && target.matches("a.file-link")) { // Keep existing file link logic
      event.preventDefault();
      const fileId = target.getAttribute("data-file-id");
      const conversationId = target.getAttribute("data-conversation-id");
      if (fileId && conversationId) { // Add checks
        fetchFileContent(conversationId, fileId);
      } else {
        console.warn("File link clicked but missing data-file-id or data-conversation-id");
        showToast("Could not open file: Missing information.", "warning");
      }
    } else if (event.target && event.target.classList.contains("generated-image")) { // Keep existing image logic
        // Use event.target directly here as it's the image itself
      const imageSrc = event.target.getAttribute("data-image-src");
      if (imageSrc) {
          showImagePopup(imageSrc);
      }
    }
    // Clicks on web citation buttons (a.citation-button.web-citation-link) are handled
    // natively by the browser because they have a valid href and target="_blank".
    // No specific JS handling needed here unless you want to add tracking etc.
  });
}

// Helper function to escape HTML
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Global function to toggle result expansion (called from inline onclick)
window.toggleResultExpansion = function(button) {
  const resultContent = button.closest('.result-content');
  const remaining = resultContent.querySelector('.result-remaining');
  const icon = button.querySelector('i');
  
  if (remaining.style.display === 'none') {
    // Expand
    remaining.style.display = 'inline';
    icon.className = 'bi bi-chevron-up';
    button.title = 'Show less';
  } else {
    // Collapse
    remaining.style.display = 'none';
    icon.className = 'bi bi-chevron-down';
    button.title = 'Show more';
  }
};

// Global function to toggle arguments expansion (called from inline onclick)
window.toggleArgsExpansion = function(button) {
  const argsContent = button.closest('.args-content');
  const remaining = argsContent.querySelector('.args-remaining');
  const icon = button.querySelector('i');
  
  if (remaining.style.display === 'none') {
    // Expand
    remaining.style.display = 'inline';
    icon.className = 'bi bi-chevron-up';
    button.title = 'Show less';
  } else {
    // Collapse
    remaining.style.display = 'none';
    icon.className = 'bi bi-chevron-down';
    button.title = 'Show more';
  }
};
// ---------------------------------------