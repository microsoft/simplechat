// chat-documents.js

import { showToast } from "./chat-toast.js"; // Assuming you have this
import { toBoolean } from "./chat-utils.js"; // Import the toBoolean helper

export const docScopeSelect = document.getElementById("doc-scope-select");
const searchDocumentsBtn = document.getElementById("search-documents-btn");
const docSelectEl = document.getElementById("document-select"); // Hidden select element
const searchDocumentsContainer = document.getElementById("search-documents-container"); // Container for scope/doc/class

// Custom dropdown elements
const docDropdownButton = document.getElementById("document-dropdown-button");
const docDropdownItems = document.getElementById("document-dropdown-items");
const docDropdownMenu = document.getElementById("document-dropdown-menu");
const docSearchInput = document.getElementById("document-search-input");

// Classification elements
const classificationContainer = document.querySelector(".classification-container"); // Main container div
const classificationSelectInput = document.getElementById("classification-select"); // The input field (now dual purpose)
const classificationMultiselectDropdown = document.getElementById("classification-multiselect-dropdown"); // Wrapper for button+menu
const classificationDropdownBtn = document.getElementById("classification-dropdown-btn");
const classificationDropdownMenu = document.getElementById("classification-dropdown-menu");

// --- Get Classification Categories ---
// Ensure classification_categories is correctly parsed and available
// It should be an array of objects like [{label: 'Confidential', color: '#ff0000'}, ...]
// If it's just a comma-separated string from settings, parse it first.
let classificationCategories = [];
try {
    // Use the structure already provided in base.html
    classificationCategories = window.classification_categories || [];
    if (typeof classificationCategories === 'string') {
        // If it was a simple string "cat1,cat2", convert to objects
         classificationCategories = classificationCategories.split(',')
            .map(cat => cat.trim())
            .filter(cat => cat) // Remove empty strings
            .map(label => ({ label: label, color: '#6c757d' })); // Assign default color if only labels provided
    }
} catch (e) {
    console.error("Error parsing classification categories:", e);
    classificationCategories = [];
}
// ----------------------------------

// We'll store personalDocs/groupDocs/publicDocs in memory once loaded:
export let personalDocs = [];
export let groupDocs = [];
export let publicDocs = [];
let activeGroupName = "";
let activePublicWorkspaceName = "";
let publicWorkspaceIdToName = {};
let visiblePublicWorkspaceIds = []; // Store IDs of public workspaces visible to the user

/* ---------------------------------------------------------------------------
   Populate the Document Dropdown Based on the Scope
--------------------------------------------------------------------------- */
export function populateDocumentSelectScope() {
  if (!docScopeSelect || !docSelectEl) return;

  console.log("Populating document dropdown with scope:", docScopeSelect.value);
  console.log("Personal docs:", personalDocs.length);
  console.log("Group docs:", groupDocs.length);

  const previousValue = docSelectEl.value; // Store previous selection if needed
  docSelectEl.innerHTML = ""; // Clear existing options
  
  // Clear the dropdown items container
  if (docDropdownItems) {
    docDropdownItems.innerHTML = "";
  }

  // Always add an "All Documents" option to the hidden select
  const allOpt = document.createElement("option");
  allOpt.value = ""; // Use empty string for "All"
  allOpt.textContent = "All Documents"; // Consistent label
  docSelectEl.appendChild(allOpt);
  
  // Add "All Documents" item to custom dropdown
  if (docDropdownItems) {
    const allItem = document.createElement("button");
    allItem.type = "button";
    allItem.classList.add("dropdown-item");
    allItem.setAttribute("data-document-id", "");
    allItem.textContent = "All Documents";
    allItem.style.display = "block";
    allItem.style.width = "100%";
    allItem.style.textAlign = "left";
    docDropdownItems.appendChild(allItem);
  }

  const scopeVal = docScopeSelect.value || "all";

  let finalDocs = [];
  if (scopeVal === "all") {
    const pDocs = personalDocs.map((d) => ({
      id: d.id,
      label: `[Personal] ${d.title || d.file_name}`,
      classification: d.document_classification, // Store classification
    }));
    const gDocs = groupDocs.map((d) => ({
      id: d.id,
      label: `[Group: ${activeGroupName}] ${d.title || d.file_name}`,
      classification: d.document_classification, // Store classification
    }));
    const pubDocs = publicDocs.map((d) => ({
      id: d.id,
      label: `[Public: ${publicWorkspaceIdToName[d.public_workspace_id] || "Unknown"}] ${d.title || d.file_name}`,
      classification: d.document_classification, // Store classification
    }));
    finalDocs = pDocs.concat(gDocs).concat(pubDocs);
  } else if (scopeVal === "personal") {
    finalDocs = personalDocs.map((d) => ({
      id: d.id,
      label: `[Personal] ${d.title || d.file_name}`,
      classification: d.document_classification,
    }));
  } else if (scopeVal === "group") {
    finalDocs = groupDocs.map((d) => ({
      id: d.id,
      label: `[Group: ${activeGroupName}] ${d.title || d.file_name}`,
      classification: d.document_classification,
    }));
  } else if (scopeVal === "public") {
    finalDocs = publicDocs.map((d) => ({
      id: d.id,
      label: `[Public: ${publicWorkspaceIdToName[d.public_workspace_id] || "Unknown"}] ${d.title || d.file_name}`,
      classification: d.document_classification,
    }));
  }

  // Add document options to the hidden select and populate the custom dropdown
  finalDocs.forEach((doc) => {
    // Add to hidden select
    const opt = document.createElement("option");
    opt.value = doc.id;
    opt.textContent = doc.label;
    opt.dataset.classification = doc.classification || ""; // Store classification or empty string
    docSelectEl.appendChild(opt);
    
    // Add to custom dropdown
    if (docDropdownItems) {
      const dropdownItem = document.createElement("button");
      dropdownItem.type = "button";
      dropdownItem.classList.add("dropdown-item");
      dropdownItem.setAttribute("data-document-id", doc.id);
      dropdownItem.textContent = doc.label;
      dropdownItem.style.display = "block";
      dropdownItem.style.width = "100%";
      dropdownItem.style.textAlign = "left";
      docDropdownItems.appendChild(dropdownItem);
    }
  });

  // Show/hide search based on number of documents
  if (docSearchInput && docDropdownItems) {
    const documentsCount = finalDocs.length;
    const searchContainer = docSearchInput.closest('.document-search-container');
    
    if (searchContainer) {
      // Always show search if there are more than 0 documents
      if (documentsCount > 0) {
        searchContainer.classList.remove('d-none');
      } else {
        searchContainer.classList.add('d-none');
      }
    }
  }

  // Try to restore previous selection if it still exists, otherwise default to "All"
  if (finalDocs.some(doc => doc.id === previousValue)) {
    docSelectEl.value = previousValue;
    if (docDropdownButton) {
      const selectedDoc = finalDocs.find(doc => doc.id === previousValue);
      if (selectedDoc) {
        docDropdownButton.querySelector(".selected-document-text").textContent = selectedDoc.label;
      }
      
      // Update active state in dropdown
      if (docDropdownItems) {
        document.querySelectorAll("#document-dropdown-items .dropdown-item").forEach(item => {
          item.classList.remove("active");
          if (item.getAttribute("data-document-id") === previousValue) {
            item.classList.add("active");
          }
        });
      }
    }
  } else {
    docSelectEl.value = ""; // Default to "All Documents"
    if (docDropdownButton) {
      docDropdownButton.querySelector(".selected-document-text").textContent = "All Documents";
      
      // Set "All Documents" as active
      if (docDropdownItems) {
        document.querySelectorAll("#document-dropdown-items .dropdown-item").forEach(item => {
          item.classList.remove("active");
          if (item.getAttribute("data-document-id") === "") {
            item.classList.add("active");
          }
        });
      }
    }
  }

  // IMPORTANT: Trigger the classification update after populating
  handleDocumentSelectChange();
}

export function getDocumentMetadata(docId) {
  if (!docId) return null;
  // Search personal docs first
  const personalMatch = personalDocs.find(doc => doc.id === docId || doc.document_id === docId); // Check common ID keys
  if (personalMatch) {
    // console.log(`Metadata found in personalDocs for ${docId}`);
    return personalMatch;
  }
  // Then search group docs
  const groupMatch = groupDocs.find(doc => doc.id === docId || doc.document_id === docId);
   if (groupMatch) {
    // console.log(`Metadata found in groupDocs for ${docId}`);
    return groupMatch;
  }
  // Finally search public docs
  const publicMatch = publicDocs.find(doc => doc.id === docId || doc.document_id === docId);
  if (publicMatch) {
    // console.log(`Metadata found in publicDocs for ${docId}`);
    return publicMatch;
  }
  // console.log(`Metadata NOT found for ${docId}`);
  return null; // Not found in any list
}

/* ---------------------------------------------------------------------------
   Loading Documents (Keep existing loadPersonalDocs, loadGroupDocs, loadAllDocs)
--------------------------------------------------------------------------- */
export function loadPersonalDocs() {
  // Use a large page_size to load all documents at once, without pagination
  return fetch("/api/documents?page_size=1000")
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        console.warn("Error fetching user docs:", data.error);
        personalDocs = [];
        return;
      }
      personalDocs = data.documents || [];
      console.log(`Loaded ${personalDocs.length} personal documents`);
    })
    .catch((err) => {
      console.error("Error loading personal docs:", err);
      personalDocs = [];
    });
}

export function loadGroupDocs() {
  // Use a large page_size to load all documents at once, without pagination
  return fetch("/api/group_documents?page_size=1000")
    .then((r) => {
      if (!r.ok) {
        // Handle 400 errors gracefully (e.g., no active group selected)
        if (r.status === 400) {
          console.log("No active group selected for group documents");
          groupDocs = [];
          return { documents: [] }; // Return empty result to avoid further errors
        }
        throw new Error(`HTTP ${r.status}: ${r.statusText}`);
      }
      return r.json();
    })
    .then((data) => {
      if (data.error) {
        console.warn("Error fetching group docs:", data.error);
        groupDocs = [];
        return;
      }
      groupDocs = data.documents || [];
      console.log(`Loaded ${groupDocs.length} group documents`);
    })
    .catch((err) => {
      console.error("Error loading group docs:", err);
      groupDocs = [];
    });
}

export function loadPublicDocs() {
  // Use a large page_size to load all documents at once, without pagination
  return fetch("/api/public_workspace_documents?page_size=1000")
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        console.warn("Error fetching public workspace docs:", data.error);
        publicDocs = [];
        activePublicWorkspaceName = "";
        publicWorkspaceIdToName = {};
        return;
      }
      // Fetch user settings to determine visible workspaces
      return fetch("/api/user/settings")
        .then((r) => r.json())
        .then((settingsData) => {
          const userSettings = settingsData && settingsData.settings ? settingsData.settings : {};
          const publicDirectorySettings = userSettings.publicDirectorySettings || {};
          // Only include documents from visible public workspaces
          publicDocs = (data.documents || []).filter(
            (doc) => publicDirectorySettings[doc.public_workspace_id] === true
          );
          // Now fetch the workspace list to build the ID->name mapping
          return fetch("/api/public_workspaces/discover")
            .then((r) => r.json())
            .then((workspaces) => {
              publicWorkspaceIdToName = {};
              (workspaces || []).forEach(ws => {
                publicWorkspaceIdToName[ws.id] = ws.name;
              });
              // Determine if only one public workspace is visible
              const visibleWorkspaceIds = Object.keys(publicDirectorySettings).filter(
                id => publicDirectorySettings[id] === true
              );
              visiblePublicWorkspaceIds = visibleWorkspaceIds; // Store for use in scope label updates
              if (visibleWorkspaceIds.length === 1) {
                activePublicWorkspaceName = publicWorkspaceIdToName[visibleWorkspaceIds[0]] || "Unknown";
              } else {
                activePublicWorkspaceName = "All Public Workspaces";
              }
              console.log(
                `Loaded ${publicDocs.length} public workspace documents from user-visible public workspaces`
              );
            })
            .catch((err) => {
              // If workspace list can't be loaded, fallback to generic label
              publicWorkspaceIdToName = {};
              activePublicWorkspaceName = "All Public Workspaces";
              console.warn("Could not load public workspace names:", err);
            });
        })
        .catch((err) => {
          // If user settings can't be loaded, default to showing all documents
          console.warn("Could not load user settings, showing all public workspace documents:", err);
          publicDocs = data.documents || [];
          publicWorkspaceIdToName = {};
          activePublicWorkspaceName = "All Public Workspaces";
          visiblePublicWorkspaceIds = []; // Reset visible workspace IDs
        });
    })
    .catch((err) => {
      console.error("Error loading public workspace docs:", err);
      publicDocs = [];
      publicWorkspaceIdToName = {};
      activePublicWorkspaceName = "";
      visiblePublicWorkspaceIds = []; // Reset visible workspace IDs
    });
}

/**
 * Updates the scope option labels to show dynamic workspace names
 */
function updateScopeLabels() {
  if (!docScopeSelect) return;
  
  // Update public option text based on visible workspaces
  const publicOption = docScopeSelect.querySelector('option[value="public"]');
  if (publicOption) {
    // Get names of visible public workspaces
    const visibleWorkspaceNames = visiblePublicWorkspaceIds
      .map(id => publicWorkspaceIdToName[id])
      .filter(name => name && name !== "Unknown");
    
    let publicLabel = "Public";
    
    if (visibleWorkspaceNames.length === 0) {
      publicLabel = "Public";
    } else if (visibleWorkspaceNames.length === 1) {
      publicLabel = `Public: ${visibleWorkspaceNames[0]}`;
    } else if (visibleWorkspaceNames.length <= 3) {
      publicLabel = `Public: ${visibleWorkspaceNames.join(", ")}`;
    } else {
      publicLabel = `Public: ${visibleWorkspaceNames.slice(0, 3).join(", ")}, 3+`;
    }
    
    publicOption.textContent = publicLabel;
    console.log(`Updated public scope label to: ${publicLabel}`);
  }
}

export function loadAllDocs() {
  const hasDocControls = searchDocumentsBtn || docScopeSelect || docSelectEl;
  
  // Use the toBoolean helper for consistent checking
  const classificationEnabled = toBoolean(window.enable_document_classification);

  if (!hasDocControls) {
    return Promise.resolve();
  }
  // Only hide the classification container if feature disabled
  if (classificationContainer && !classificationEnabled) {
      classificationContainer.style.display = 'none';
  }
  // Ensure container is visible if feature is enabled
  if (classificationContainer && classificationEnabled) classificationContainer.style.display = '';

  // Initialize custom document dropdown if available
  if (docDropdownButton && docDropdownItems) {
    // Ensure the custom dropdown is properly initialized
    const documentSearchContainer = document.querySelector('.document-search-container');
    if (documentSearchContainer) {
      // Initially show the search field as it will be useful for filtering
      documentSearchContainer.classList.remove('d-none');
    }
    
    console.log("Setting up document dropdown event listeners...");
    
    // Make sure dropdown shows when button is clicked
    docDropdownButton.addEventListener('click', function(e) {
      console.log("Dropdown button clicked");
      // Initialize dropdown after a short delay to ensure DOM is ready
      setTimeout(() => {
        initializeDocumentDropdown();
      }, 100);
    });
    
    // Additionally listen for the bootstrap shown.bs.dropdown event
    const dropdownEl = document.querySelector('#document-dropdown');
    if (dropdownEl) {
      dropdownEl.addEventListener('shown.bs.dropdown', function(e) {
        console.log("Dropdown shown event fired");
        // Focus the search input for immediate searching
        if (docSearchInput) {
          setTimeout(() => {
            docSearchInput.focus();
            initializeDocumentDropdown();
          }, 100);
        } else {
          initializeDocumentDropdown();
        }
      });
      
      // Handle dropdown hide event to clear search and reset item visibility
      dropdownEl.addEventListener('hide.bs.dropdown', function(e) {
        console.log("Dropdown hide event fired");
        if (docSearchInput) {
          docSearchInput.value = '';
          // Reset all items to visible
          if (docDropdownItems) {
            const items = docDropdownItems.querySelectorAll('.dropdown-item');
            items.forEach(item => {
              item.style.display = 'block';
              item.removeAttribute('data-filtered');
            });
            
            // Remove any "no matches" message
            const noMatchesEl = docDropdownItems.querySelector('.no-matches');
            if (noMatchesEl) {
              noMatchesEl.remove();
            }
          }
        }
      });
    } else {
      console.error("Document dropdown element not found");
    }
  }

  return Promise.all([loadPersonalDocs(), loadGroupDocs(), loadPublicDocs()])
    .then(() => {
      console.log("All documents loaded. Personal:", personalDocs.length, "Group:", groupDocs.length, "Public:", publicDocs.length);
      // Update scope labels after loading data
      updateScopeLabels();
      // After loading, populate the select and set initial classification state
      populateDocumentSelectScope();
      // handleDocumentSelectChange(); // Called within populateDocumentSelectScope now
    })
    .catch(err => {
      console.error("Error loading documents:", err);
    });
}

// Function to ensure dropdown menu is properly displayed
function initializeDocumentDropdown() {
  if (!docDropdownMenu) return;
  
  console.log("Initializing dropdown display");
  
  // Make sure dropdown menu is visible and has proper z-index
  docDropdownMenu.classList.add('show');
  docDropdownMenu.style.zIndex = "1050"; // Ensure it's above other elements
  
  // Reset visibility of items if no search term is active
  if (!docSearchInput || !docSearchInput.value.trim()) {
    console.log("Resetting item visibility");
    const items = docDropdownItems.querySelectorAll('.dropdown-item');
    items.forEach(item => {
      // Only reset items that aren't already filtered by an active search
      if (!item.hasAttribute('data-filtered')) {
        item.style.display = 'block';
      }
    });
  }
  
  // If there's a search term in the input, apply filtering immediately
  if (docSearchInput && docSearchInput.value.trim()) {
    console.log("Search term detected, triggering filter");
    // Create and dispatch both events for maximum browser compatibility
    docSearchInput.dispatchEvent(new Event('input', { bubbles: true }));
    docSearchInput.dispatchEvent(new Event('keyup', { bubbles: true }));
  }
  
  // Set a fixed narrower width for the dropdown
  let maxWidth = 400; // Updated to 400px width
  
  // Calculate parent container width (we want dropdown to fit inside right pane)
  const parentContainer = docDropdownButton.closest('.flex-grow-1');
  if (parentContainer) {
    const parentWidth = parentContainer.offsetWidth;
    // Use the smaller of our fixed width or 90% of parent width
    maxWidth = Math.min(maxWidth, parentWidth * 0.9);
  }
  
  docDropdownMenu.style.maxWidth = `${maxWidth}px`;
  docDropdownMenu.style.width = `${maxWidth}px`;
  
  // Ensure dropdown stays within viewport bounds
  const menuRect = docDropdownMenu.getBoundingClientRect();
  const viewportHeight = window.innerHeight;
  
  // If dropdown extends beyond viewport, adjust position or max-height
  if (menuRect.bottom > viewportHeight) {
    // Option 1: Adjust max-height to fit
    const maxPossibleHeight = viewportHeight - menuRect.top - 10; // 10px buffer
    docDropdownMenu.style.maxHeight = `${maxPossibleHeight}px`;
    
    // Also adjust the items container
    if (docDropdownItems) {
      // Account for search box height including its margin
      const searchContainer = docDropdownMenu.querySelector('.document-search-container');
      const searchHeight = searchContainer ? searchContainer.offsetHeight : 40;
      docDropdownItems.style.maxHeight = `${maxPossibleHeight - searchHeight}px`;
    }
  }
}
/* ---------------------------------------------------------------------------
   UI Event Listeners
--------------------------------------------------------------------------- */
if (docScopeSelect) {
  docScopeSelect.addEventListener("change", populateDocumentSelectScope);
}

if (searchDocumentsBtn) {
  searchDocumentsBtn.addEventListener("click", function () {
    this.classList.toggle("active");

    if (!searchDocumentsContainer) return;

    if (this.classList.contains("active")) {
      searchDocumentsContainer.style.display = "block";
      // Ensure initial population and state is correct when opening
      loadAllDocs().then(() => {
        // Force Bootstrap to update the Popper positioning
        try {
          const dropdownInstance = bootstrap.Dropdown.getInstance(docDropdownButton);
          if (dropdownInstance) {
            dropdownInstance.update();
          } else {
            // Initialize dropdown if not already done
            new bootstrap.Dropdown(docDropdownButton, {
              boundary: 'viewport',
              reference: 'toggle',
              autoClose: 'outside',
              popperConfig: {
                strategy: 'fixed',
                modifiers: [
                  {
                    name: 'preventOverflow',
                    options: {
                      boundary: 'viewport',
                      padding: 10
                    }
                  }
                ]
              }
            });
          }
        } catch (err) {
          console.error("Error initializing dropdown:", err);
        }
        // handleDocumentSelectChange() is called by populateDocumentSelectScope within loadAllDocs
      });
    } else {
      searchDocumentsContainer.style.display = "none";
      // Optional: Reset classification state when hiding?
      // resetClassificationState(); // You might want a function for this
    }
  });
}

if (docSelectEl) {
  // Listen for changes on the document select dropdown (this is now hidden and used as state keeper)
  docSelectEl.addEventListener("change", handleDocumentSelectChange);
}

// Add event listeners for custom document dropdown
if (docDropdownMenu) {
  // Prevent dropdown menu from closing when clicking inside
  docDropdownMenu.addEventListener('click', function(e) {
    e.stopPropagation();
  });
  
  // Additional event handlers to prevent dropdown from closing
  docDropdownMenu.addEventListener('keydown', function(e) {
    e.stopPropagation();
  });
  
  docDropdownMenu.addEventListener('keyup', function(e) {
    e.stopPropagation();
  });
}

if (docDropdownItems) {
  // Prevent dropdown menu from closing when clicking inside items container
  docDropdownItems.addEventListener('click', function(e) {
    e.stopPropagation();
  });
  
  // Directly attach click handler to the container for better delegation
  docDropdownItems.addEventListener('click', function(e) {
    // Find closest dropdown-item whether clicked directly or on a child
    const item = e.target.closest('.dropdown-item');
    if (!item) return; // Exit if click wasn't on/in a dropdown item
    
    const docId = item.getAttribute('data-document-id');
    console.log("Document item clicked:", docId, item.textContent);
    
    // Update hidden select
    if (docSelectEl) {
      docSelectEl.value = docId;
      
      // Trigger change event
      const event = new Event('change', { bubbles: true });
      docSelectEl.dispatchEvent(event);
    }
    
    // Update dropdown button text
    if (docDropdownButton) {
      docDropdownButton.querySelector('.selected-document-text').textContent = item.textContent;
    }
    
    // Update active state
    document.querySelectorAll('#document-dropdown-items .dropdown-item').forEach(i => {
      i.classList.remove('active');
    });
    item.classList.add('active');
    
    // Close dropdown
    try {
      const dropdownInstance = bootstrap.Dropdown.getInstance(docDropdownButton);
      if (dropdownInstance) {
        dropdownInstance.hide();
      }
    } catch (err) {
      console.error("Error closing dropdown:", err);
    }
  });
}

// Add search functionality
if (docSearchInput) {
  // Define our filtering function to ensure consistent filtering logic
  const filterDocumentItems = function(searchTerm) {
    console.log("Filtering documents with search term:", searchTerm);
    
    if (!docDropdownItems) {
      console.error("Document dropdown items container not found");
      return;
    }
    
    // Get all dropdown items directly from the items container
    const items = docDropdownItems.querySelectorAll('.dropdown-item');
    console.log(`Found ${items.length} document items to filter`);
    
    // Keep track if any items matched
    let matchFound = false;
    
    // Process each item
    items.forEach(item => {
      // Get the text content for comparison
      const docName = item.textContent.toLowerCase();
      
      // Check if the document name includes the search term
      if (docName.includes(searchTerm)) {
        // Show matching item
        item.style.display = 'block';
        item.setAttribute('data-filtered', 'visible');
        matchFound = true;
      } else {
        // Hide non-matching item
        item.style.display = 'none';
        item.setAttribute('data-filtered', 'hidden');
      }
    });
    
    console.log(`Filter results: ${matchFound ? 'Matches found' : 'No matches found'}`);
    
    // Show a message if no matches found
    const noMatchesEl = docDropdownItems.querySelector('.no-matches');
    if (!matchFound && searchTerm.length > 0) {
      if (!noMatchesEl) {
        const noMatchesMsg = document.createElement('div');
        noMatchesMsg.className = 'no-matches text-center text-muted py-2';
        noMatchesMsg.textContent = 'No matching documents found';
        docDropdownItems.appendChild(noMatchesMsg);
      }
    } else {
      // Remove the "no matches" message if it exists
      if (noMatchesEl) {
        noMatchesEl.remove();
      }
    }
    
    // Make sure dropdown stays open and visible
    if (docDropdownMenu) {
      docDropdownMenu.classList.add('show');
    }
  };
  
  // Attach input event directly 
  docSearchInput.addEventListener('input', function() {
    const searchTerm = this.value.toLowerCase().trim();
    filterDocumentItems(searchTerm);
  });
  
  // Also attach keyup event as a fallback
  docSearchInput.addEventListener('keyup', function() {
    const searchTerm = this.value.toLowerCase().trim();
    filterDocumentItems(searchTerm);
  });
  
  // Clear search when dropdown closes
  document.addEventListener('hidden.bs.dropdown', function(e) {
    if (e.target.id === 'document-dropdown') {
      docSearchInput.value = ''; // Clear search input
      
      // Reset visibility of all items
      if (docDropdownItems) {
        const items = docDropdownItems.querySelectorAll('.dropdown-item');
        items.forEach(item => {
          item.style.display = 'block';
          item.removeAttribute('data-filtered');
        });
      }
      
      // Remove any "no matches" message
      const noMatchesEl = docDropdownItems?.querySelector('.no-matches');
      if (noMatchesEl) {
        noMatchesEl.remove();
      }
    }
  });
  
  // Prevent dropdown from closing when clicking in search input
  docSearchInput.addEventListener('click', function(e) {
    e.stopPropagation();
    e.preventDefault();
  });
  
  // Prevent dropdown from closing when pressing keys in search input
  docSearchInput.addEventListener('keydown', function(e) {
    e.stopPropagation();
  });
}

/* ---------------------------------------------------------------------------
   Handle Document Selection & Update Classification UI
--------------------------------------------------------------------------- */
export function handleDocumentSelectChange() {
  // Only require docSelectEl for document selection logic
  if (!docSelectEl) {
      console.error("Document select element not found, cannot update UI.");
      return;
  }

  // Update custom dropdown button text to match selected document
  if (docDropdownButton) {
    const selectedOption = docSelectEl.options[docSelectEl.selectedIndex];
    if (selectedOption) {
      docDropdownButton.querySelector(".selected-document-text").textContent = selectedOption.textContent;
      
      // Update active state in dropdown
      if (docDropdownItems) {
        document.querySelectorAll("#document-dropdown-items .dropdown-item").forEach(item => {
          item.classList.remove("active");
          if (item.getAttribute("data-document-id") === selectedOption.value) {
            item.classList.add("active");
          }
        });
      }
    }
  }

  // Classification UI logic (optional, only if elements exist)
  const classificationEnabled = toBoolean(window.enable_document_classification);

  if (classificationContainer) {
    if (classificationEnabled) {
      classificationContainer.style.display = '';
    } else {
      classificationContainer.style.display = 'none';
    }
  }

  // If classification is not enabled, skip classification UI logic, but allow document selection to work
  if (!classificationEnabled) {
    return;
  }

  if (!classificationSelectInput || !classificationMultiselectDropdown || !classificationDropdownBtn || !classificationDropdownMenu) {
    // If classification elements are missing, skip classification UI logic
    return;
  }

  const selectedOption = docSelectEl.options[docSelectEl.selectedIndex];
  const docId = selectedOption.value;

  // Case 1: "All Documents" is selected (value is empty string)
  if (!docId) {
    classificationSelectInput.style.display = "none"; // Hide the single display input
    classificationSelectInput.value = ""; // Clear its value just in case

    classificationMultiselectDropdown.style.display = "block"; // Show the dropdown wrapper

    // Build the checkbox list (this function will also set the initial state)
    buildClassificationCheckboxDropdown();
  }
  // Case 2: A specific document is selected
  else {
    classificationMultiselectDropdown.style.display = "none"; // Hide the dropdown wrapper

    // Get the classification stored on the selected option element
    const classification = selectedOption.dataset.classification || "N/A"; // Use "N/A" or similar if empty

    classificationSelectInput.value = classification; // Set the input's value
    classificationSelectInput.style.display = "block"; // Show the input
    // Input is already readonly via HTML, no need to disable JS-side unless you want extra safety
  }
}

/* ---------------------------------------------------------------------------
   Build and Manage Classification Checkbox Dropdown (for "All Documents")
--------------------------------------------------------------------------- */
function buildClassificationCheckboxDropdown() {
  if (!classificationDropdownMenu || !classificationDropdownBtn || !classificationSelectInput) return;

  classificationDropdownMenu.innerHTML = ""; // Clear previous items

  // Stop propagation on menu clicks to prevent closing when clicking labels/checkboxes
  classificationDropdownMenu.addEventListener('click', (e) => {
        e.stopPropagation();
  });


  if (classificationCategories.length === 0) {
      classificationDropdownMenu.innerHTML = '<li class="dropdown-item text-muted small">No categories defined</li>';
      classificationDropdownBtn.textContent = "No categories";
      classificationDropdownBtn.disabled = true;
      classificationSelectInput.value = ""; // Ensure hidden value is empty
      return;
  }

  classificationDropdownBtn.disabled = false;

  // Create a checkbox item for each classification category
  classificationCategories.forEach((cat) => {
    // Use cat.label assuming cat is {label: 'Name', color: '#...'}
    const categoryLabel = cat.label || cat; // Handle if it's just an array of strings
    if (!categoryLabel) return; // Skip empty categories

    const li = document.createElement("li");
    const label = document.createElement("label");
    label.classList.add("dropdown-item", "d-flex", "align-items-center", "gap-2"); // Use flex for spacing
    label.style.cursor = 'pointer'; // Make it clear the whole item is clickable

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = categoryLabel.trim();
    checkbox.checked = true; // Default to checked
    checkbox.classList.add('form-check-input', 'mt-0'); // Bootstrap class, mt-0 for alignment

    label.appendChild(checkbox);
    label.appendChild(document.createTextNode(` ${categoryLabel.trim()}`)); // Add label text

    li.appendChild(label);
    classificationDropdownMenu.appendChild(li);

    // Add listener to the checkbox itself
    checkbox.addEventListener("change", () => {
      updateClassificationDropdownLabelAndValue();
    });
  });

  // Initialize the button label and the hidden input value after building
  updateClassificationDropdownLabelAndValue();
}

// Single function to update both the button label and the hidden input's value
function updateClassificationDropdownLabelAndValue() {
  if (!classificationDropdownMenu || !classificationDropdownBtn || !classificationSelectInput) return;

  const checkboxes = classificationDropdownMenu.querySelectorAll("input[type='checkbox']");
  const checkedCheckboxes = classificationDropdownMenu.querySelectorAll("input[type='checkbox']:checked");

  const totalCount = checkboxes.length;
  const checkedCount = checkedCheckboxes.length;

  // Update Button Label
  if (checkedCount === 0) {
    classificationDropdownBtn.textContent = "None selected";
  } else if (checkedCount === totalCount) {
    classificationDropdownBtn.textContent = "All selected";
  } else if (checkedCount === 1) {
    // Find the single selected label
    classificationDropdownBtn.textContent = checkedCheckboxes[0].value; // Show the actual label if only one selected
    // classificationDropdownBtn.textContent = "1 selected"; // Alternative: Keep generic count
  } else {
    classificationDropdownBtn.textContent = `${checkedCount} selected`;
  }

  // Update Hidden Input Value (comma-separated string)
  const checkedValues = [];
  checkedCheckboxes.forEach((cb) => checkedValues.push(cb.value));
  classificationSelectInput.value = checkedValues.join(","); // Store comma-separated list
}

// Helper function (optional) to reset state if needed
// function resetClassificationState() {
//     if (!docSelectEl || !classificationContainer) return;
//     // Potentially reset docSelectEl to "All"
//     // docSelectEl.value = "";
//     // Then trigger the update
//     handleDocumentSelectChange();
// }


// --- Ensure initial state is set after documents are loaded ---
// The call within loadAllDocs -> populateDocumentSelectScope handles the initial setup.

// Initialize the dropdown on page load
document.addEventListener('DOMContentLoaded', function() {
  // If search documents button exists, it needs to be clicked to show controls
  if (searchDocumentsBtn && docScopeSelect && docDropdownButton) {
    try {
      // Get the dropdown element
      const dropdownEl = document.getElementById('document-dropdown');
      
      if (dropdownEl) {
        console.log("Initializing Bootstrap dropdown with search functionality");
        
        // Initialize Bootstrap dropdown with the right configuration
        new bootstrap.Dropdown(docDropdownButton, {
          boundary: 'viewport',
          reference: 'toggle',
          autoClose: 'outside', // Close when clicking outside, stay open when clicking inside
          popperConfig: {
            strategy: 'fixed',
            modifiers: [
              {
                name: 'preventOverflow',
                options: {
                  boundary: 'viewport',
                  padding: 10
                }
              }
            ]
          }
        });
        
        // Listen for dropdown show event
        dropdownEl.addEventListener('shown.bs.dropdown', function() {
          console.log("Dropdown shown - making sure items are visible");
          initializeDocumentDropdown();
          
          // Focus the search input when dropdown is shown
          if (docSearchInput) {
            setTimeout(() => {
              docSearchInput.focus();
            }, 100);
          }
        });
        
        // Re-initialize the search filter every time the dropdown is shown
        if (docSearchInput) {
          // Clear any previous search when opening the dropdown
          dropdownEl.addEventListener('show.bs.dropdown', function() {
            docSearchInput.value = '';
          });
          
          // Ensure the search filter is properly initialized when the dropdown is shown
          dropdownEl.addEventListener('shown.bs.dropdown', function() {
            // Explicitly focus and activate the search input
            setTimeout(() => {
              docSearchInput.focus();
              
              // Add click handler for search input to prevent dropdown from closing
              docSearchInput.onclick = function(e) {
                e.stopPropagation();
                e.preventDefault();
              };
            }, 150);
          });
        }
      }
    } catch (err) {
      console.error("Error initializing bootstrap dropdown:", err);
    }
  }
});