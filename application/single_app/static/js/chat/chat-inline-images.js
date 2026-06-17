// chat-inline-images.js
import {
    fetchAgentCitationArtifact,
    parseDocIdAndPage,
    showImagePopup,
} from "./chat-citations.js";
import { escapeHtml } from "./chat-utils.js";

const INLINE_IMAGE_GALLERY_RENDER_TYPE = "inline_image_gallery";
const MAX_INLINE_IMAGE_ITEMS = 5;
const IMAGE_FILE_NAME_PATTERN = /\.(?:avif|bmp|gif|heic|heif|ico|jpe?g|png|svg|tiff?|webp)(?:$|[?#])/i;

function toNonEmptyString(value) {
    return typeof value === "string" ? value.trim() : "";
}

function sanitizeHttpUrl(value) {
    const normalizedValue = toNonEmptyString(value);
    if (!normalizedValue) {
        return "";
    }

    try {
        const parsedUrl = new URL(normalizedValue);
        if (parsedUrl.protocol === "http:" || parsedUrl.protocol === "https:") {
            return parsedUrl.toString();
        }
    } catch (error) {
        return "";
    }

    return "";
}

function parseJsonValue(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }

    if (typeof value === "object") {
        return value;
    }

    try {
        return JSON.parse(value);
    } catch (error) {
        return null;
    }
}

function getCitationResult(candidate) {
    if (!candidate || typeof candidate !== "object") {
        return null;
    }

    if (candidate.render_type && (candidate.image_gallery || candidate.image_url || candidate.images)) {
        return candidate;
    }

    const parsedResult = parseJsonValue(candidate.function_result);
    if (parsedResult && typeof parsedResult === "object") {
        return parsedResult;
    }

    return null;
}

function resolveImageUrlValue(candidate) {
    if (typeof candidate === "string") {
        return candidate.trim();
    }

    if (!candidate || typeof candidate !== "object") {
        return "";
    }

    return toNonEmptyString(candidate.url || candidate.image_url || candidate.src);
}

function buildWorkspaceImageUrl(docId) {
    const normalizedDocId = toNonEmptyString(docId);
    if (!normalizedDocId) {
        return "";
    }

    return `/api/enhanced_citations/image?doc_id=${encodeURIComponent(normalizedDocId)}`;
}

function getUrlHostname(urlValue) {
    const normalizedValue = toNonEmptyString(urlValue);
    if (!normalizedValue) {
        return "";
    }

    try {
        return new URL(normalizedValue, window.location.origin).hostname;
    } catch (error) {
        return "";
    }
}

function deriveSourceLabel(docId, imageUrl, explicitLabel = "") {
    const normalizedLabel = toNonEmptyString(explicitLabel);
    if (normalizedLabel) {
        return normalizedLabel;
    }

    if (toNonEmptyString(docId)) {
        return "Workspace image";
    }

    if (toNonEmptyString(imageUrl).startsWith("data:image/")) {
        return "Embedded image";
    }

    const hostname = getUrlHostname(imageUrl);
    if (hostname) {
        return `External image (${hostname})`;
    }

    return "Image";
}

function isLikelyImageFileName(fileName) {
    return IMAGE_FILE_NAME_PATTERN.test(toNonEmptyString(fileName));
}

function isLikelyImageUrl(urlValue) {
    const normalizedUrl = toNonEmptyString(urlValue);
    if (!normalizedUrl) {
        return false;
    }

    if (normalizedUrl.startsWith("data:image/")) {
        return true;
    }

    return IMAGE_FILE_NAME_PATTERN.test(normalizedUrl);
}

function getItemIdentityKey(item) {
    if (!item || typeof item !== "object") {
        return "";
    }

    return toNonEmptyString(
        item.doc_id
        || item.source_url
        || item.full_image_url
        || item.preview_image_url
        || item.title
    );
}

function pushUniqueImageItem(targetItems, seenKeys, item) {
    if (!item) {
        return;
    }

    const identityKey = getItemIdentityKey(item);
    if (!identityKey || seenKeys.has(identityKey)) {
        return;
    }

    seenKeys.add(identityKey);
    targetItems.push(item);
}

function normalizeImageItem(rawItem, index) {
    const item = typeof rawItem === "string"
        ? { image_url: rawItem }
        : rawItem;

    if (!item || typeof item !== "object" || Array.isArray(item)) {
        return null;
    }

    const docId = toNonEmptyString(item.doc_id || item.docId || item.document_id || item.documentId);
    const imageUrl = resolveImageUrlValue(item.image_url || item.url || item.src || item.full_url || item.fullUrl);
    const thumbnailUrl = resolveImageUrlValue(
        item.thumbnail_url || item.thumbnailUrl || item.preview_url || item.previewUrl
    ) || imageUrl;

    if (!docId && !imageUrl) {
        return null;
    }

    const fallbackTitle = docId
        ? toNonEmptyString(item.file_name || item.fileName) || `Workspace image ${index + 1}`
        : `Image ${index + 1}`;
    const title = toNonEmptyString(item.title || item.label || item.name || item.caption) || fallbackTitle;
    const description = toNonEmptyString(item.description || item.summary || item.caption || item.details);
    const fileName = toNonEmptyString(item.file_name || item.fileName);
    const previewImageUrl = docId ? buildWorkspaceImageUrl(docId) : thumbnailUrl;
    const fullImageUrl = docId ? buildWorkspaceImageUrl(docId) : imageUrl;
    const sourceUrl = toNonEmptyString(item.source_url || item.sourceUrl || item.link || item.href);

    return {
        id: toNonEmptyString(item.id) || `inline-image-${index + 1}`,
        title,
        description,
        file_name: fileName,
        doc_id: docId,
        preview_image_url: previewImageUrl,
        full_image_url: fullImageUrl,
        source_label: deriveSourceLabel(docId, imageUrl || previewImageUrl, item.source_label || item.sourceLabel),
        source_url: sourceUrl,
        alt_text: toNonEmptyString(item.alt_text || item.altText) || title,
    };
}

function normalizeWorkspaceCitationImageItem(rawCitation, index) {
    if (!rawCitation || typeof rawCitation !== "object" || rawCitation.metadata_type) {
        return null;
    }

    const fileName = toNonEmptyString(rawCitation.file_name || rawCitation.fileName || rawCitation.title);
    if (!isLikelyImageFileName(fileName)) {
        return null;
    }

    const citationId = toNonEmptyString(rawCitation.citation_id || rawCitation.chunk_id);
    const { docId } = citationId ? parseDocIdAndPage(citationId) : { docId: "" };
    const normalizedDocId = toNonEmptyString(docId || rawCitation.doc_id || rawCitation.docId);
    if (!normalizedDocId) {
        return null;
    }

    const locationLabel = toNonEmptyString(rawCitation.location_label || (rawCitation.sheet_name ? "Sheet" : "Page"));
    const locationValue = toNonEmptyString(rawCitation.location_value || rawCitation.sheet_name || rawCitation.page_number);
    const description = locationValue && locationValue !== "N/A"
        ? `${locationLabel || "Location"}: ${locationValue}`
        : "Workspace image cited in this response.";

    return {
        id: `workspace-image-${normalizedDocId}-${index + 1}`,
        title: fileName || `Workspace image ${index + 1}`,
        description,
        file_name: fileName,
        doc_id: normalizedDocId,
        preview_image_url: buildWorkspaceImageUrl(normalizedDocId),
        full_image_url: buildWorkspaceImageUrl(normalizedDocId),
        source_label: "Workspace image",
        source_url: "",
        alt_text: fileName || `Workspace image ${index + 1}`,
    };
}

function extractWorkspaceCitationImageItems(hybridCitations = [], seenKeys = new Set()) {
    const items = [];
    if (!Array.isArray(hybridCitations) || hybridCitations.length === 0) {
        return items;
    }

    hybridCitations.forEach((citation, index) => {
        pushUniqueImageItem(items, seenKeys, normalizeWorkspaceCitationImageItem(citation, index));
    });

    return items;
}

function normalizeWebCitationImageItem(rawCitation, index) {
    if (!rawCitation || typeof rawCitation !== "object") {
        return null;
    }

    const imageUrl = resolveImageUrlValue(rawCitation.image_url || rawCitation.url || rawCitation.src);
    if (!isLikelyImageUrl(imageUrl)) {
        return null;
    }

    const title = toNonEmptyString(rawCitation.title || rawCitation.label || rawCitation.name)
        || `Linked image ${index + 1}`;
    const description = toNonEmptyString(rawCitation.description || rawCitation.summary);

    return {
        id: `linked-image-${index + 1}`,
        title,
        description,
        file_name: toNonEmptyString(rawCitation.file_name || rawCitation.fileName),
        doc_id: "",
        preview_image_url: imageUrl,
        full_image_url: imageUrl,
        source_label: deriveSourceLabel("", imageUrl, rawCitation.source_label || rawCitation.sourceLabel),
        source_url: toNonEmptyString(rawCitation.source_url || rawCitation.sourceUrl || rawCitation.url),
        alt_text: toNonEmptyString(rawCitation.alt_text || rawCitation.altText) || title,
    };
}

function extractLinkedImageItems(webCitations = [], seenKeys = new Set()) {
    const items = [];
    if (!Array.isArray(webCitations) || webCitations.length === 0) {
        return items;
    }

    webCitations.forEach((citation, index) => {
        pushUniqueImageItem(items, seenKeys, normalizeWebCitationImageItem(citation, index));
    });

    return items;
}

function buildImageGalleryResult(title, summary, items, sourceActionName, totalCount = items.length) {
    const renderedItems = Array.isArray(items) ? items.slice(0, MAX_INLINE_IMAGE_ITEMS) : [];
    if (renderedItems.length === 0) {
        return null;
    }

    return {
        success: true,
        render_type: INLINE_IMAGE_GALLERY_RENDER_TYPE,
        image_gallery: {
            title,
            summary,
            items: renderedItems,
            total_count: Number(totalCount) || renderedItems.length,
            rendered_count: renderedItems.length,
            source_action_name: sourceActionName,
        },
    };
}

function extractRawImageItems(candidate) {
    if (!candidate || typeof candidate !== "object") {
        return [];
    }

    if (candidate.image_gallery && typeof candidate.image_gallery === "object") {
        const galleryItems = candidate.image_gallery.items;
        return Array.isArray(galleryItems) ? galleryItems : [];
    }

    if (Array.isArray(candidate.items)) {
        return candidate.items;
    }

    if (Array.isArray(candidate.images)) {
        return candidate.images;
    }

    if (Array.isArray(candidate.image_urls)) {
        return candidate.image_urls;
    }

    const directImageUrl = resolveImageUrlValue(candidate.image_url);
    const directMime = toNonEmptyString(candidate.mime);
    const directType = toNonEmptyString(candidate.type).toLowerCase();
    if (directImageUrl || directType === "image_url" || directMime.startsWith("image/")) {
        return [{
            image_url: directImageUrl,
            title: candidate.title,
            description: candidate.description || candidate.summary,
            file_name: candidate.file_name || candidate.fileName,
            source_label: candidate.source_label || candidate.sourceLabel,
            source_url: candidate.source_url || candidate.sourceUrl,
        }];
    }

    return [];
}

function normalizeImageGalleryResult(result, maxItems = MAX_INLINE_IMAGE_ITEMS) {
    if (!result || typeof result !== "object" || result.success === false || maxItems <= 0) {
        return null;
    }

    const galleryCandidate = result.image_gallery && typeof result.image_gallery === "object"
        ? result.image_gallery
        : result;
    const rawItems = extractRawImageItems(result);
    if (!Array.isArray(rawItems) || rawItems.length === 0) {
        return null;
    }

    const normalizedItems = rawItems
        .map((item, index) => normalizeImageItem(item, index))
        .filter(Boolean);
    if (normalizedItems.length === 0) {
        return null;
    }

    const renderedItems = normalizedItems.slice(0, Math.max(0, maxItems));
    if (renderedItems.length === 0) {
        return null;
    }
    const totalCount = Number.isFinite(Number(galleryCandidate.total_count || galleryCandidate.totalCount))
        ? Number(galleryCandidate.total_count || galleryCandidate.totalCount)
        : normalizedItems.length;
    const galleryTitle = toNonEmptyString(galleryCandidate.title || galleryCandidate.label || result.title)
        || (totalCount === 1 ? "Image result" : "Image results");
    const gallerySummary = toNonEmptyString(galleryCandidate.summary || galleryCandidate.description || result.summary)
        || (renderedItems.length === 1
            ? "Relevant image returned for this result."
            : "Relevant images returned for this result.");

    return {
        ...result,
        render_type: result.render_type || INLINE_IMAGE_GALLERY_RENDER_TYPE,
        image_gallery: {
            title: galleryTitle,
            summary: gallerySummary,
            items: renderedItems,
            total_count: totalCount,
            rendered_count: renderedItems.length,
            source_action_name: toNonEmptyString(galleryCandidate.source_action_name || galleryCandidate.sourceActionName || result.source_action_name),
        },
    };
}

async function hydrateInlineImageGalleryCitation(conversationId, artifactId) {
    try {
        const hydratedCitation = await fetchAgentCitationArtifact(conversationId, artifactId);
        return normalizeImageGalleryResult(getCitationResult(hydratedCitation));
    } catch (error) {
        console.warn("Failed to hydrate inline image gallery citation artifact", error);
        return null;
    }
}

async function resolveInlineImageGallery(citation, conversationId, maxItems = MAX_INLINE_IMAGE_ITEMS) {
    const shouldPreferArtifact = Boolean(
        citation?.raw_payload_externalized
        && citation?.artifact_id
        && conversationId
    );

    if (shouldPreferArtifact) {
        const hydratedResult = await hydrateInlineImageGalleryCitation(conversationId, citation.artifact_id);
        const normalizedHydratedResult = normalizeImageGalleryResult(hydratedResult, maxItems);
        if (normalizedHydratedResult) {
            return normalizedHydratedResult;
        }

        if (hydratedResult) {
            return hydratedResult;
        }
    }

    const localResult = normalizeImageGalleryResult(getCitationResult(citation), maxItems);
    if (localResult) {
        return localResult;
    }

    if (!citation?.artifact_id || !conversationId || shouldPreferArtifact) {
        return null;
    }

    const fallbackHydratedResult = await hydrateInlineImageGalleryCitation(conversationId, citation.artifact_id);
    return normalizeImageGalleryResult(fallbackHydratedResult, maxItems);
}

function buildImageDetailsRows(item) {
    const rows = [];

    if (item.source_label) {
        rows.push(`
            <div class="inline-image-modal-meta-row">
                <span class="inline-image-modal-meta-label">Source</span>
                <span class="inline-image-modal-meta-value">${escapeHtml(item.source_label)}</span>
            </div>
        `);
    }

    if (item.file_name) {
        rows.push(`
            <div class="inline-image-modal-meta-row">
                <span class="inline-image-modal-meta-label">File</span>
                <span class="inline-image-modal-meta-value">${escapeHtml(item.file_name)}</span>
            </div>
        `);
    }

    if (item.doc_id) {
        rows.push(`
            <div class="inline-image-modal-meta-row">
                <span class="inline-image-modal-meta-label">Document ID</span>
                <span class="inline-image-modal-meta-value text-break">${escapeHtml(item.doc_id)}</span>
            </div>
        `);
    }

    const safeSourceUrl = sanitizeHttpUrl(item.source_url);
    if (safeSourceUrl) {
        rows.push(`
            <div class="inline-image-modal-meta-row">
                <span class="inline-image-modal-meta-label">Link</span>
                <span class="inline-image-modal-meta-value">
                    <a href="${escapeHtml(safeSourceUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(safeSourceUrl)}</a>
                </span>
            </div>
        `);
    }

    return rows.join("");
}

function getInlineImageDetailsModal() {
    let modalContainer = document.getElementById("inline-image-details-modal");
    if (modalContainer) {
        return modalContainer;
    }

    modalContainer = document.createElement("div");
    modalContainer.id = "inline-image-details-modal";
    modalContainer.className = "modal fade";
    modalContainer.tabIndex = -1;
    modalContainer.setAttribute("aria-hidden", "true");
    modalContainer.innerHTML = `
        <div class="modal-dialog modal-dialog-scrollable modal-lg modal-fullscreen-sm-down">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="inline-image-details-title">Image details</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                    <div class="inline-image-modal-stage mb-3">
                        <img id="inline-image-details-preview" class="img-fluid rounded-3" alt="Inline image preview" />
                    </div>
                    <p id="inline-image-details-description" class="inline-image-modal-description d-none"></p>
                    <div id="inline-image-details-meta" class="inline-image-modal-meta"></div>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modalContainer);
    return modalContainer;
}

function showInlineImageDetailsModal(item) {
    const modalContainer = getInlineImageDetailsModal();
    const titleEl = modalContainer.querySelector("#inline-image-details-title");
    const previewEl = modalContainer.querySelector("#inline-image-details-preview");
    const descriptionEl = modalContainer.querySelector("#inline-image-details-description");
    const metaEl = modalContainer.querySelector("#inline-image-details-meta");

    if (titleEl) {
        titleEl.textContent = item.title || "Image details";
    }

    if (previewEl) {
        previewEl.src = item.full_image_url || item.preview_image_url;
        previewEl.alt = item.alt_text || item.title || "Inline image";
    }

    if (descriptionEl) {
        const hasDescription = Boolean(item.description);
        descriptionEl.classList.toggle("d-none", !hasDescription);
        descriptionEl.textContent = item.description || "";
    }

    if (metaEl) {
        metaEl.innerHTML = buildImageDetailsRows(item);
    }

    const modal = new bootstrap.Modal(modalContainer);
    modal.show();
}

function createBadge(label, value) {
    const badge = document.createElement("span");
    badge.className = "inline-image-gallery-badge";
    badge.textContent = `${label}: ${value}`;
    return badge;
}

function createImageTile(item) {
    const tile = document.createElement("article");
    tile.className = "inline-image-gallery-item";
    tile.innerHTML = `
        <div class="inline-image-gallery-stage">
            <img class="inline-image-gallery-item-image" alt="${escapeHtml(item.alt_text || item.title || "Inline image")}" loading="lazy" />
            <button type="button" class="inline-image-gallery-info-btn" aria-label="Show image details">
                <i class="bi bi-info-circle-fill"></i>
            </button>
        </div>
        <div class="inline-image-gallery-item-copy">
            <div class="inline-image-gallery-item-meta">${escapeHtml(item.source_label)}</div>
            <div class="inline-image-gallery-item-title">${escapeHtml(item.title || "Image")}</div>
            ${item.description ? `<div class="inline-image-gallery-item-description">${escapeHtml(item.description)}</div>` : ""}
        </div>
    `;

    const imageEl = tile.querySelector(".inline-image-gallery-item-image");
    const infoButton = tile.querySelector(".inline-image-gallery-info-btn");
    if (imageEl) {
        imageEl.src = item.preview_image_url || item.full_image_url;
        imageEl.addEventListener("click", () => {
            showImagePopup(item.full_image_url || item.preview_image_url);
        });
        imageEl.addEventListener("error", () => {
            imageEl.src = "/static/images/image-error.png";
            imageEl.alt = "Failed to load image";
        });
    }

    if (infoButton) {
        infoButton.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            showInlineImageDetailsModal(item);
        });
    }

    return tile;
}

function createImageGalleryCard(result, messageId, index) {
    const payload = result.image_gallery || {};
    const card = document.createElement("section");
    card.className = "inline-image-gallery-card";

    const renderedCount = Number(payload.rendered_count || (payload.items || []).length || 0);
    const totalCount = Number(payload.total_count || renderedCount || 0);
    const summaryText = payload.summary || result.summary || "Relevant image results.";

    card.innerHTML = `
        <div class="inline-image-gallery-header">
            <div class="inline-image-gallery-copy">
                <div class="inline-image-gallery-title-row">
                    <span class="inline-image-gallery-icon"><i class="bi bi-images"></i></span>
                    <h6 class="inline-image-gallery-title mb-0">${escapeHtml(payload.title || "Image results")}</h6>
                </div>
                <p class="inline-image-gallery-summary mb-0">${escapeHtml(summaryText)}</p>
            </div>
            <div class="inline-image-gallery-badges" aria-label="Image gallery details"></div>
        </div>
        <div class="inline-image-gallery-grid"></div>
        <div class="inline-image-gallery-footer">
            <span>Inline images</span>
            ${payload.source_action_name ? `<span class="inline-image-gallery-footer-separator">•</span><span>${escapeHtml(payload.source_action_name)}</span>` : ""}
        </div>
    `;

    const badgesContainer = card.querySelector(".inline-image-gallery-badges");
    if (badgesContainer) {
        badgesContainer.appendChild(createBadge("Images", renderedCount));
        if (totalCount > renderedCount) {
            badgesContainer.appendChild(createBadge("Showing", `${renderedCount} of ${totalCount}`));
        }
    }

    const grid = card.querySelector(".inline-image-gallery-grid");
    if (grid) {
        (payload.items || []).forEach((item) => {
            grid.appendChild(createImageTile(item));
        });
    }

    return { card };
}

export async function renderInlineImageGalleries(
    messageElement,
    hybridCitations = [],
    webCitations = [],
    agentCitations = [],
    messageId = "",
    conversationId = ""
) {
    if (!messageElement) {
        return;
    }

    const container = messageElement.querySelector(".inline-visualizations-container");
    if (!container) {
        return;
    }

    container.querySelectorAll(".inline-image-gallery-card").forEach((card) => card.remove());

    const hasHybridCitations = Array.isArray(hybridCitations) && hybridCitations.length > 0;
    const hasWebCitations = Array.isArray(webCitations) && webCitations.length > 0;
    const hasAgentCitations = Array.isArray(agentCitations) && agentCitations.length > 0;
    if (!hasHybridCitations && !hasWebCitations && !hasAgentCitations) {
        container.classList.toggle("d-none", container.children.length === 0);
        return;
    }

    let remainingSlots = MAX_INLINE_IMAGE_ITEMS;
    let galleryIndex = 0;
    const seenImageKeys = new Set();

    const workspaceItems = extractWorkspaceCitationImageItems(hybridCitations, seenImageKeys);
    if (workspaceItems.length > 0 && remainingSlots > 0) {
        const workspaceGallery = buildImageGalleryResult(
            "Workspace images",
            "Image sources cited from workspace content.",
            workspaceItems.slice(0, remainingSlots),
            "Workspace citations",
            workspaceItems.length
        );
        if (workspaceGallery) {
            const { card } = createImageGalleryCard(workspaceGallery, messageId, galleryIndex);
            container.appendChild(card);
            remainingSlots -= workspaceGallery.image_gallery.rendered_count || 0;
            galleryIndex += 1;
        }
    }

    const linkedItems = extractLinkedImageItems(webCitations, seenImageKeys);
    if (linkedItems.length > 0 && remainingSlots > 0) {
        const linkedGallery = buildImageGalleryResult(
            "Linked images",
            "Direct image links returned with this response.",
            linkedItems.slice(0, remainingSlots),
            "Linked sources",
            linkedItems.length
        );
        if (linkedGallery) {
            const { card } = createImageGalleryCard(linkedGallery, messageId, galleryIndex);
            container.appendChild(card);
            remainingSlots -= linkedGallery.image_gallery.rendered_count || 0;
            galleryIndex += 1;
        }
    }

    for (let index = 0; index < agentCitations.length && remainingSlots > 0; index += 1) {
        const citation = agentCitations[index];
        const result = await resolveInlineImageGallery(citation, conversationId, remainingSlots);
        if (!result) {
            continue;
        }

        const normalizedItems = Array.isArray(result?.image_gallery?.items)
            ? result.image_gallery.items.filter((item) => {
                const identityKey = getItemIdentityKey(item);
                if (!identityKey || seenImageKeys.has(identityKey)) {
                    return false;
                }

                seenImageKeys.add(identityKey);
                return true;
            })
            : [];
        if (normalizedItems.length === 0) {
            continue;
        }

        result.image_gallery.items = normalizedItems;
        result.image_gallery.rendered_count = normalizedItems.length;

        const { card } = createImageGalleryCard(result, messageId, galleryIndex);
        container.appendChild(card);
        remainingSlots -= normalizedItems.length;
        galleryIndex += 1;
    }

    container.classList.toggle("d-none", container.children.length === 0);
}