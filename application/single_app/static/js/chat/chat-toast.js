// chat-toast.js

const preferredToastContainerSelector = '[data-toast-container="preferred"]';
const syncedToastContainers = new WeakSet();

function getToastContainer() {
  return document.querySelector(preferredToastContainerSelector) || document.getElementById("toast-container");
}

function getToastAnchor(container) {
  const anchorId = container?.dataset.toastAnchor;
  if (!anchorId) {
    return null;
  }

  return document.getElementById(anchorId);
}

function syncToastContainerPosition(container) {
  if (!container) {
    return;
  }

  if (!container.dataset.toastAnchor) {
    return;
  }

  const defaultTop = container.dataset.toastDefaultTop || "16px";
  const anchor = getToastAnchor(container);

  if (!anchor || anchor.offsetParent === null || !anchor.classList.contains("is-ready")) {
    container.style.top = defaultTop;
    return;
  }

  const gap = Number.parseInt(container.dataset.toastGap || "12", 10);
  const containerPaddingTop = Number.parseFloat(window.getComputedStyle(container).paddingTop || "0");
  const anchorRect = anchor.getBoundingClientRect();
  const anchoredTop = Math.max(16, Math.ceil(anchorRect.bottom + gap - containerPaddingTop));

  container.style.top = `${anchoredTop}px`;
}

function ensureToastContainerAnchorSync(container) {
  if (!container || !container.dataset.toastAnchor || syncedToastContainers.has(container)) {
    return;
  }

  syncedToastContainers.add(container);

  const reposition = () => syncToastContainerPosition(container);
  const anchor = getToastAnchor(container);

  window.addEventListener("resize", reposition);

  if (window.ResizeObserver && anchor) {
    const resizeObserver = new ResizeObserver(reposition);
    resizeObserver.observe(anchor);
  }

  if (window.MutationObserver && anchor) {
    const mutationObserver = new MutationObserver(reposition);
    mutationObserver.observe(anchor, {
      attributes: true,
      attributeFilter: ["class", "style"],
    });
  }

  reposition();
}

export function showToast(message, variant = "danger") {
  const container = getToastContainer();
  if (!container) {
    return;
  }

  ensureToastContainerAnchorSync(container);
  syncToastContainerPosition(container);

  const id = "toast-" + Date.now();
  const toastEl = document.createElement("div");
  toastEl.id = id;
  toastEl.className = `toast align-items-center text-bg-${variant}`;
  toastEl.setAttribute("role", "alert");
  toastEl.setAttribute("aria-live", "assertive");
  toastEl.setAttribute("aria-atomic", "true");

  const contentEl = document.createElement("div");
  contentEl.className = "d-flex";

  const bodyEl = document.createElement("div");
  bodyEl.className = "toast-body";
  if (message instanceof Node) {
    bodyEl.appendChild(message);
  } else {
    bodyEl.textContent = String(message ?? "");
  }

  const closeButtonEl = document.createElement("button");
  closeButtonEl.type = "button";
  closeButtonEl.className = "btn-close btn-close-white me-2 m-auto";
  closeButtonEl.setAttribute("data-bs-dismiss", "toast");
  closeButtonEl.setAttribute("aria-label", "Close");

  contentEl.appendChild(bodyEl);
  contentEl.appendChild(closeButtonEl);
  toastEl.appendChild(contentEl);
  container.appendChild(toastEl);

  const bsToast = new bootstrap.Toast(toastEl, { delay: 5000 });
  bsToast.show();
}