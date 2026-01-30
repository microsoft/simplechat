// agent_templates_gallery.js
// Dynamically renders the agent template gallery within the agent builder

import { showToast } from "./chat/chat-toast.js";

const gallerySelector = ".agent-template-gallery";
let cachedTemplates = null;
let loadingPromise = null;

function getGalleryElements(container) {
  return {
    spinner: container.querySelector(".agent-template-gallery-loading"),
    emptyState: container.querySelector(".agent-template-gallery-empty"),
    disabledState: container.querySelector(".agent-template-gallery-disabled"),
    errorState: container.querySelector(".agent-template-gallery-error"),
    errorText: container.querySelector(".agent-template-gallery-error-text"),
    accordion: container.querySelector(".accordion"),
  };
}

async function fetchTemplates() {
  if (cachedTemplates) {
    return cachedTemplates;
  }
  if (loadingPromise) {
    return loadingPromise;
  }
  loadingPromise = fetch("/api/agent-templates")
    .then(async (response) => {
      if (!response.ok) {
        throw new Error("Failed to load templates.");
      }
      const data = await response.json();
      cachedTemplates = data.templates || [];
      return cachedTemplates;
    })
    .catch((error) => {
      cachedTemplates = [];
      throw error;
    })
    .finally(() => {
      loadingPromise = null;
    });
  return loadingPromise;
}

function renderAccordion(accordion, templates, options = {}) {
  const accordionId = options.accordionId || "agentTemplates";
  const showCopy = options.showCopy !== "false";
  const showCreate = options.showCreate !== "false";

  accordion.innerHTML = "";

  templates.forEach((template, index) => {
    const collapseId = `${accordionId}-collapse-${index}`;
    const headingId = `${accordionId}-heading-${index}`;
    const instructionsId = `${accordionId}-instructions-${index}`;

    const accordionItem = document.createElement("div");
    accordionItem.className = "accordion-item";

    const header = document.createElement("h2");
    header.className = "accordion-header";
    header.id = headingId;

    const headerButton = document.createElement("button");
    headerButton.className = `accordion-button${index === 0 ? "" : " collapsed"}`;
    headerButton.type = "button";
    headerButton.setAttribute("data-bs-toggle", "collapse");
    headerButton.setAttribute("data-bs-target", `#${collapseId}`);
    headerButton.textContent = template.title || template.display_name || "Agent Template";
    header.appendChild(headerButton);

    const collapse = document.createElement("div");
    collapse.id = collapseId;
    collapse.className = `accordion-collapse collapse${index === 0 ? " show" : ""}`;
    collapse.setAttribute("aria-labelledby", headingId);
    collapse.setAttribute("data-bs-parent", `#${accordionId}`);

    const body = document.createElement("div");
    body.className = "accordion-body";

    const headerRow = document.createElement("div");
    headerRow.className = "d-flex flex-wrap justify-content-between align-items-start gap-2 mb-3";

    const helper = document.createElement("div");
    helper.className = "small text-muted";
    helper.textContent = template.helper_text || template.description || "Reusable agent template";
    headerRow.appendChild(helper);

    const buttonGroup = document.createElement("div");
    buttonGroup.className = "d-flex gap-2 flex-wrap";

    if (showCopy) {
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "btn btn-sm btn-outline-secondary";
      copyBtn.innerHTML = '<i class="bi bi-clipboard"></i> Copy';
      copyBtn.addEventListener("click", () => copyInstructions(instructionsId));
      buttonGroup.appendChild(copyBtn);
    }

    if (showCreate) {
      const createBtn = document.createElement("button");
      createBtn.type = "button";
      createBtn.className = "btn btn-sm btn-success agent-example-create-btn";
      createBtn.innerHTML = '<i class="bi bi-plus-circle"></i> Use Template';
      const payload = {
        display_name: template.display_name || template.title || "Agent Template",
        description: template.description || template.helper_text || "",
        instructions: template.instructions || "",
        additional_settings: template.additional_settings || "",
        actions_to_load: template.actions_to_load || [],
      };
      createBtn.dataset.agentExample = JSON.stringify(payload);
      buttonGroup.appendChild(createBtn);
    }

    headerRow.appendChild(buttonGroup);
    body.appendChild(headerRow);

    const metaList = document.createElement("div");
    metaList.className = "mb-3";

    const helperLine = document.createElement("p");
    helperLine.className = "mb-1 text-muted small";
    helperLine.innerHTML = `<strong>Suggested display name:</strong> ${escapeHtml(template.display_name || template.title || "Agent Template")}`;
    metaList.appendChild(helperLine);

    if (Array.isArray(template.tags) && template.tags.length) {
      const tagList = document.createElement("div");
      tagList.className = "mb-1";
      template.tags.slice(0, 5).forEach((tag) => {
        const badge = document.createElement("span");
        badge.className = "badge bg-secondary-subtle text-secondary-emphasis me-1 mb-1";
        badge.textContent = tag;
        tagList.appendChild(badge);
      });
      metaList.appendChild(tagList);
    }

    if (Array.isArray(template.actions_to_load) && template.actions_to_load.length) {
      const actionLine = document.createElement("p");
      actionLine.className = "mb-0 text-muted small";
      actionLine.innerHTML = `<strong>Recommended actions:</strong> ${template.actions_to_load.join(", ")}`;
      metaList.appendChild(actionLine);
    }

    body.appendChild(metaList);

    const description = document.createElement("p");
    description.className = "mb-3";
    description.textContent = template.description || template.helper_text || "No description provided.";
    body.appendChild(description);

    const instructions = document.createElement("pre");
    instructions.className = "bg-dark text-white p-3 rounded";
    instructions.id = instructionsId;
    instructions.textContent = template.instructions || "";
    body.appendChild(instructions);

    if (template.additional_settings) {
      const advancedBlock = document.createElement("pre");
      advancedBlock.className = "bg-light border rounded p-3 mt-3";
      advancedBlock.textContent = template.additional_settings;
      const advancedLabel = document.createElement("p");
      advancedLabel.className = "text-muted small mb-1";
      advancedLabel.textContent = "Additional settings";
      body.appendChild(advancedLabel);
      body.appendChild(advancedBlock);
    }

    collapse.appendChild(body);
    accordionItem.appendChild(header);
    accordionItem.appendChild(collapse);
    accordion.appendChild(accordionItem);
  });
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value || "";
  return div.innerHTML;
}

function copyInstructions(instructionsId) {
  const target = document.getElementById(instructionsId);
  if (!target) {
    return;
  }
  if (typeof window.copyAgentInstructionSample === "function") {
    window.copyAgentInstructionSample(instructionsId);
    return;
  }
  const text = target.textContent || "";
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      showToast("Instructions copied to clipboard", "success");
    }).catch(() => {
      fallbackCopyText(text);
    });
  } else {
    fallbackCopyText(text);
  }
}

function fallbackCopyText(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.top = "-1000px";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try {
    document.execCommand("copy");
    showToast("Instructions copied to clipboard", "success");
  } catch (err) {
    console.error("Clipboard copy failed", err);
    showToast("Unable to copy instructions", "error");
  } finally {
    document.body.removeChild(textarea);
  }
}

async function initializeGallery(container) {
  const elements = getGalleryElements(container);

  if (!window.appSettings?.enable_agent_template_gallery) {
    if (elements.spinner) elements.spinner.classList.add("d-none");
    if (elements.disabledState) elements.disabledState.classList.remove("d-none");
    return;
  }

  try {
    const templates = await fetchTemplates();
    if (elements.spinner) elements.spinner.classList.add("d-none");

    if (!templates.length) {
      if (elements.emptyState) elements.emptyState.classList.remove("d-none");
      return;
    }

    if (elements.accordion) {
      elements.accordion.classList.remove("d-none");
      renderAccordion(elements.accordion, templates, {
        accordionId: container.dataset.accordionId,
        showCopy: container.dataset.showCopy,
        showCreate: container.dataset.showCreate,
      });
    }
  } catch (error) {
    console.error("Failed to render agent templates", error);
    if (elements.spinner) elements.spinner.classList.add("d-none");
    if (elements.errorState) {
      elements.errorState.classList.remove("d-none");
      if (elements.errorText) {
        elements.errorText.textContent = error.message || "Unexpected error";
      }
    }
  }
}

function initAgentTemplateGalleries() {
  const containers = document.querySelectorAll(gallerySelector);
  if (!containers.length) {
    return;
  }
  containers.forEach((container) => {
    initializeGallery(container);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAgentTemplateGalleries);
} else {
  initAgentTemplateGalleries();
}
