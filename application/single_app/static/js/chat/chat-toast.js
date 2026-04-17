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
  const toastHtml = `
    <div id="${id}" class="toast align-items-center text-bg-${variant}" role="alert" aria-live="assertive" aria-atomic="true">
      <div class="d-flex">
        <div class="toast-body">
          ${message}
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    </div>
  `;
    container.insertAdjacentHTML("beforeend", toastHtml);

    const toastEl = document.getElementById(id);
    const bsToast = new bootstrap.Toast(toastEl, { delay: 5000 });
    bsToast.show();
}