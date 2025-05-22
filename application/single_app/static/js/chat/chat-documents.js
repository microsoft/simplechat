// chat-documents.js

import { showToast } from "./chat-toast.js"; // Assuming you have this

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

// We'll store personalDocs/groupDocs in memory once loaded:
let personalDocs = [];
let groupDocs = [];
let activeGroupName = "";

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
    finalDocs = pDocs.concat(gDocs);
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
      dropdownItems.appendChild(dropdownItem);
    }
  });

  // Show/hide search based on number of documents
  if (docSearchInput && docDropdownItems) {
    const documentsCount = finalDocs.length;
    const searchContainer = docSearchInput.closest('.document-search-container');
    
    if (searchContainer) {
      if (documentsCount > 10) {
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
  // console.log(`Metadata NOT found for ${docId}`);
  return null; // Not found in either list
}

/* ---------------------------------------------------------------------------
   Loading Documents (Keep existing loadPersonalDocs, loadGroupDocs, loadAllDocs)
--------------------------------------------------------------------------- */
export function loadPersonalDocs() {
  return fetch("/api/documents")
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        console.warn("Error fetching user docs:", data.error);
        personalDocs = [];
        return;
      }
      personalDocs = data.documents || [];
    })
    .catch((err) => {
      console.error("Error loading personal docs:", err);
      personalDocs = [];
    });
}

export function loadGroupDocs() {
  return fetch("/api/group_documents")
    .then((r) => r.json())
    .then((data) => {
      if (data.error) {
        console.warn("Error fetching user docs:", data.error);
        groupDocs = [];
        return;
      }
      groupDocs  = data.documents || [];
    })
    .catch((err) => {
      console.error("Error loading personal docs:", err);
      groupDocs = [];
    });
}


export function loadAllDocs() {
  const hasDocControls = searchDocumentsBtn || docScopeSelect || docSelectEl;

  if (!hasDocControls || !window.enable_document_classification) { // Only load if feature enabled
    // Hide classification container entirely if feature disabled
    if (classificationContainer && !window.enable_document_classification) {
        classificationContainer.style.display = 'none';
    }
    return Promise.resolve();
  }
   // Ensure container is visible if feature is enabled
   if (classificationContainer) classificationContainer.style.display = '';

  // Initialize custom document dropdown if available
  if (docDropdownButton && docDropdownItems) {
    // Ensure the custom dropdown is properly initialized
    const documentSearchContainer = document.querySelector('.document-search-container');
    if (documentSearchContainer) {
      // Hide search by default, it will be shown based on document count
      documentSearchContainer.classList.add('d-none');
    }
    
    console.log("Initializing document dropdown...");
    
    // Make sure dropdown shows when button is clicked
    docDropdownButton.addEventListener('click', function() {
      // Keep dropdown open for interaction
      setTimeout(() => {
        initializeDocumentDropdown();
      }, 100);
    });
  }

  return Promise.all([loadPersonalDocs(), loadGroupDocs()])
    .then(() => {
      console.log("All documents loaded. Personal:", personalDocs.length, "Group:", groupDocs.length);
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
  
  // Make sure dropdown menu is visible
  docDropdownMenu.classList.add('show');
  
  // Make sure dropdown menu has proper position
  const buttonRect = docDropdownButton.getBoundingClientRect();
  docDropdownMenu.style.position = 'absolute';
  docDropdownMenu.style.inset = '0px auto auto 0px';
  docDropdownMenu.style.transform = `translate(0px, ${buttonRect.height}px)`;
  
  // Make sure all items are visible
  const items = docDropdownItems.querySelectorAll('.dropdown-item');
  items.forEach(item => {
    item.style.display = '';
  });
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
  docSearchInput.addEventListener('input', function() {
    const searchTerm = this.value.toLowerCase().trim();
    
    if (!docDropdownItems) return;
    
    document.querySelectorAll('#document-dropdown-items .dropdown-item').forEach(item => {
      const docName = item.textContent.toLowerCase();
      if (docName.includes(searchTerm)) {
        item.style.display = '';
      } else {
        item.style.display = 'none';
      }
    });
  });
  
  // Prevent dropdown from closing when clicking in search input
  docSearchInput.addEventListener('click', function(e) {
    e.stopPropagation();
  });
}

/* ---------------------------------------------------------------------------
   Handle Document Selection & Update Classification UI
--------------------------------------------------------------------------- */
export function handleDocumentSelectChange() {
  // Guard clauses for missing elements
  if (!docSelectEl || !classificationSelectInput || !classificationMultiselectDropdown || !classificationDropdownBtn || !classificationDropdownMenu || !classificationContainer) {
      console.error("Classification elements not found, cannot update UI.");
      return;
  }
   // Ensure classification container is visible (might be hidden if feature was disabled)
   if (window.enable_document_classification) {
        classificationContainer.style.display = '';
   } else {
        classificationContainer.style.display = 'none';
        return; // Don't proceed if feature disabled
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