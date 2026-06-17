// chat-inline-videos.js
import {
    fetchAgentCitationArtifact,
    parseDocIdAndPage,
} from "./chat-citations.js";
import { escapeHtml } from "./chat-utils.js";

const INLINE_VIDEO_GALLERY_RENDER_TYPE = "inline_video_gallery";
const MAX_INLINE_VIDEO_ITEMS = 5;
const VIDEO_FILE_NAME_PATTERN = /\.(?:3gp|avi|flv|m4v|mkv|mov|mp4|mpe?g|ogv|webm|wmv)(?:$|[?#])/i;

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

    if (candidate.render_type && (candidate.video_gallery || candidate.video_url || candidate.videos)) {
        return candidate;
    }

    const parsedResult = parseJsonValue(candidate.function_result);
    if (parsedResult && typeof parsedResult === "object") {
        return parsedResult;
    }

    return null;
}

function resolveVideoUrlValue(candidate) {
    if (typeof candidate === "string") {
        return candidate.trim();
    }

    if (!candidate || typeof candidate !== "object") {
        return "";
    }

    return toNonEmptyString(candidate.url || candidate.video_url || candidate.src);
}

function buildWorkspaceVideoUrl(docId) {
    const normalizedDocId = toNonEmptyString(docId);
    if (!normalizedDocId) {
        return "";
    }

    return `/api/enhanced_citations/video?doc_id=${encodeURIComponent(normalizedDocId)}`;
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

function deriveSourceLabel(docId, videoUrl, explicitLabel = "") {
    const normalizedLabel = toNonEmptyString(explicitLabel);
    if (normalizedLabel) {
        return normalizedLabel;
    }

    if (toNonEmptyString(docId)) {
        return "Workspace video";
    }

    if (toNonEmptyString(videoUrl).startsWith("data:video/")) {
        return "Embedded video";
    }

    const hostname = getUrlHostname(videoUrl);
    if (hostname) {
        return `External video (${hostname})`;
    }

    return "Video";
}

function isLikelyVideoFileName(fileName) {
    return VIDEO_FILE_NAME_PATTERN.test(toNonEmptyString(fileName));
}

function isLikelyVideoUrl(urlValue) {
    const normalizedUrl = toNonEmptyString(urlValue);
    if (!normalizedUrl) {
        return false;
    }

    if (normalizedUrl.startsWith("data:video/")) {
        return true;
    }

    return VIDEO_FILE_NAME_PATTERN.test(normalizedUrl);
}

function getItemIdentityKey(item) {
    if (!item || typeof item !== "object") {
        return "";
    }

    return toNonEmptyString(
        item.doc_id
        || item.source_url
        || item.full_video_url
        || item.preview_video_url
        || item.title
    );
}

function pushUniqueVideoItem(targetItems, seenKeys, item) {
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

function normalizeVideoItem(rawItem, index = 0) {
    const normalizedRawItem = typeof rawItem === "string" ? { video_url: rawItem } : rawItem;
    if (!normalizedRawItem || typeof normalizedRawItem !== "object") {
        return null;
    }

    const citationReference = parseDocIdAndPage(
        toNonEmptyString(normalizedRawItem.citation_id || normalizedRawItem.citationId)
    );
    const docId = toNonEmptyString(normalizedRawItem.doc_id || normalizedRawItem.docId || citationReference.docId);
    const fileName = toNonEmptyString(normalizedRawItem.file_name || normalizedRawItem.fileName);
    const previewVideoUrl = resolveVideoUrlValue(normalizedRawItem.preview_video_url || normalizedRawItem.previewVideoUrl);
    const fullVideoUrl = resolveVideoUrlValue(
        normalizedRawItem.full_video_url
        || normalizedRawItem.fullVideoUrl
        || normalizedRawItem.video_url
        || normalizedRawItem.videoUrl
        || normalizedRawItem.url
    );
    const workspaceVideoUrl = buildWorkspaceVideoUrl(docId);
    const resolvedPreviewVideoUrl = previewVideoUrl || fullVideoUrl || workspaceVideoUrl;
    const resolvedFullVideoUrl = fullVideoUrl || previewVideoUrl || workspaceVideoUrl;
    const mimeType = toNonEmptyString(normalizedRawItem.mime).toLowerCase();
    const resultType = toNonEmptyString(normalizedRawItem.type).toLowerCase();
    const hasVideoHint = Boolean(
        isLikelyVideoUrl(resolvedPreviewVideoUrl)
        || isLikelyVideoUrl(resolvedFullVideoUrl)
        || isLikelyVideoFileName(fileName)
        || mimeType.startsWith("video/")
        || resultType === "video_url"
    );

    if (!hasVideoHint || (!docId && !resolvedPreviewVideoUrl && !resolvedFullVideoUrl)) {
        return null;
    }

    const title = toNonEmptyString(normalizedRawItem.title || normalizedRawItem.name || fileName)
        || `Video ${index + 1}`;

    return {
        id: toNonEmptyString(
            normalizedRawItem.id
            || normalizedRawItem.citation_id
            || normalizedRawItem.citationId
            || docId
            || resolvedFullVideoUrl
            || title
        ) || `video-${index + 1}`,
        title,
        description: toNonEmptyString(
            normalizedRawItem.description
            || normalizedRawItem.summary
            || normalizedRawItem.caption
        ),
        file_name: fileName,
        doc_id: docId,
        poster_url: resolveVideoUrlValue(
            normalizedRawItem.poster_url
            || normalizedRawItem.posterUrl
            || normalizedRawItem.thumbnail_url
            || normalizedRawItem.thumbnailUrl
        ),
        preview_video_url: resolvedPreviewVideoUrl,
        full_video_url: resolvedFullVideoUrl,
        source_label: deriveSourceLabel(
            docId,
            resolvedFullVideoUrl || resolvedPreviewVideoUrl,
            normalizedRawItem.source_label || normalizedRawItem.sourceLabel
        ),
        source_url: toNonEmptyString(
            normalizedRawItem.source_url
            || normalizedRawItem.sourceUrl
            || normalizedRawItem.url
        ),
    };
}

function normalizeWorkspaceCitationVideoItem(rawCitation, index = 0) {
    if (!rawCitation || typeof rawCitation !== "object") {
        return null;
    }

    const fileName = toNonEmptyString(rawCitation.file_name || rawCitation.fileName);
    if (!isLikelyVideoFileName(fileName)) {
        return null;
    }

    const citationReference = parseDocIdAndPage(
        toNonEmptyString(rawCitation.citation_id || rawCitation.citationId)
    );
    const docId = toNonEmptyString(rawCitation.doc_id || rawCitation.docId || citationReference.docId);
    if (!docId) {
        return null;
    }

    const workspaceVideoUrl = buildWorkspaceVideoUrl(docId);

    return {
        id: docId || `workspace-video-${index + 1}`,
        title: fileName || `Workspace video ${index + 1}`,
        description: "",
        file_name: fileName,
        doc_id: docId,
        poster_url: "",
        preview_video_url: workspaceVideoUrl,
        full_video_url: workspaceVideoUrl,
        source_label: deriveSourceLabel(
            docId,
            workspaceVideoUrl,
            rawCitation.source_label || rawCitation.sourceLabel
        ),
        source_url: "",
    };
}

function extractWorkspaceCitationVideoItems(hybridCitations = [], seenKeys = new Set()) {
    const items = [];
    if (!Array.isArray(hybridCitations) || hybridCitations.length === 0) {
        return items;
    }

    hybridCitations.forEach((citation, index) => {
        pushUniqueVideoItem(items, seenKeys, normalizeWorkspaceCitationVideoItem(citation, index));
    });

    return items;
}

function normalizeWebCitationVideoItem(rawCitation, index = 0) {
    const normalizedCitation = typeof rawCitation === "string" ? { url: rawCitation } : rawCitation;
    if (!normalizedCitation || typeof normalizedCitation !== "object") {
        return null;
    }

    const videoUrl = resolveVideoUrlValue(
        normalizedCitation.video_url
        || normalizedCitation.videoUrl
        || normalizedCitation.url
    );
    const fileName = toNonEmptyString(normalizedCitation.file_name || normalizedCitation.fileName);
    if (!isLikelyVideoUrl(videoUrl) && !isLikelyVideoFileName(fileName)) {
        return null;
    }

    const title = toNonEmptyString(normalizedCitation.title || normalizedCitation.name || fileName)
        || `Video ${index + 1}`;

    return {
        id: toNonEmptyString(normalizedCitation.id || videoUrl || title) || `linked-video-${index + 1}`,
        title,
        description: toNonEmptyString(
            normalizedCitation.description
            || normalizedCitation.summary
            || normalizedCitation.snippet
        ),
        file_name: fileName,
        doc_id: "",
        poster_url: resolveVideoUrlValue(
            normalizedCitation.poster_url
            || normalizedCitation.posterUrl
            || normalizedCitation.thumbnail_url
            || normalizedCitation.thumbnailUrl
        ),
        preview_video_url: videoUrl,
        full_video_url: videoUrl,
        source_label: deriveSourceLabel(
            "",
            videoUrl,
            normalizedCitation.source_label || normalizedCitation.sourceLabel
        ),
        source_url: toNonEmptyString(
            normalizedCitation.source_url
            || normalizedCitation.sourceUrl
            || normalizedCitation.url
        ),
    };
}

function extractLinkedVideoItems(webCitations = [], seenKeys = new Set()) {
    const items = [];
    if (!Array.isArray(webCitations) || webCitations.length === 0) {
        return items;
    }

    webCitations.forEach((citation, index) => {
        pushUniqueVideoItem(items, seenKeys, normalizeWebCitationVideoItem(citation, index));
    });

    return items;
}

function buildVideoGalleryResult(title, summary, items, sourceActionName, totalCount = items.length) {
    const renderedItems = Array.isArray(items) ? items.slice(0, MAX_INLINE_VIDEO_ITEMS) : [];
    if (renderedItems.length === 0) {
        return null;
    }

    return {
        success: true,
        render_type: INLINE_VIDEO_GALLERY_RENDER_TYPE,
        video_gallery: {
            title,
            summary,
            items: renderedItems,
            total_count: Number(totalCount) || renderedItems.length,
            rendered_count: renderedItems.length,
            source_action_name: sourceActionName,
        },
    };
}

function extractRawVideoItems(candidate) {
    if (!candidate || typeof candidate !== "object") {
        return [];
    }

    if (candidate.video_gallery && typeof candidate.video_gallery === "object") {
        const galleryItems = candidate.video_gallery.items;
        return Array.isArray(galleryItems) ? galleryItems : [];
    }

    if (Array.isArray(candidate.items)) {
        return candidate.items;
    }

    if (Array.isArray(candidate.videos)) {
        return candidate.videos;
    }

    if (Array.isArray(candidate.video_urls)) {
        return candidate.video_urls;
    }

    const directVideoUrl = resolveVideoUrlValue(candidate.video_url || candidate.url);
    const directMime = toNonEmptyString(candidate.mime).toLowerCase();
    const directType = toNonEmptyString(candidate.type).toLowerCase();
    if (directVideoUrl || directType === "video_url" || directMime.startsWith("video/")) {
        return [{
            video_url: directVideoUrl,
            title: candidate.title,
            description: candidate.description || candidate.summary,
            file_name: candidate.file_name || candidate.fileName,
            source_label: candidate.source_label || candidate.sourceLabel,
            source_url: candidate.source_url || candidate.sourceUrl || candidate.url,
            mime: candidate.mime,
            type: candidate.type,
            poster_url: candidate.poster_url || candidate.posterUrl || candidate.thumbnail_url || candidate.thumbnailUrl,
        }];
    }

    return [];
}

function normalizeVideoGalleryResult(result, maxItems = MAX_INLINE_VIDEO_ITEMS) {
    if (!result || typeof result !== "object" || result.success === false || maxItems <= 0) {
        return null;
    }

    const galleryCandidate = result.video_gallery && typeof result.video_gallery === "object"
        ? result.video_gallery
        : result;
    const rawItems = extractRawVideoItems(result);
    if (!Array.isArray(rawItems) || rawItems.length === 0) {
        return null;
    }

    const normalizedItems = rawItems
        .map((item, index) => normalizeVideoItem(item, index))
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
        || (totalCount === 1 ? "Video result" : "Video results");
    const gallerySummary = toNonEmptyString(galleryCandidate.summary || galleryCandidate.description || result.summary)
        || (renderedItems.length === 1
            ? "Relevant video returned for this result."
            : "Relevant videos returned for this result.");

    return {
        ...result,
        render_type: result.render_type || INLINE_VIDEO_GALLERY_RENDER_TYPE,
        video_gallery: {
            title: galleryTitle,
            summary: gallerySummary,
            items: renderedItems,
            total_count: totalCount,
            rendered_count: renderedItems.length,
            source_action_name: toNonEmptyString(
                galleryCandidate.source_action_name || galleryCandidate.sourceActionName || result.source_action_name
            ),
        },
    };
}

async function hydrateInlineVideoGalleryCitation(conversationId, artifactId) {
    try {
        const hydratedCitation = await fetchAgentCitationArtifact(conversationId, artifactId);
        return normalizeVideoGalleryResult(getCitationResult(hydratedCitation));
    } catch (error) {
        console.warn("Failed to hydrate inline video gallery citation artifact", error);
        return null;
    }
}

async function resolveInlineVideoGallery(citation, conversationId, maxItems = MAX_INLINE_VIDEO_ITEMS) {
    const shouldPreferArtifact = Boolean(
        citation?.raw_payload_externalized
        && citation?.artifact_id
        && conversationId
    );

    if (shouldPreferArtifact) {
        const hydratedResult = await hydrateInlineVideoGalleryCitation(conversationId, citation.artifact_id);
        const normalizedHydratedResult = normalizeVideoGalleryResult(hydratedResult, maxItems);
        if (normalizedHydratedResult) {
            return normalizedHydratedResult;
        }

        if (hydratedResult) {
            return hydratedResult;
        }
    }

    const localResult = normalizeVideoGalleryResult(getCitationResult(citation), maxItems);
    if (localResult) {
        return localResult;
    }

    if (!citation?.artifact_id || !conversationId || shouldPreferArtifact) {
        return null;
    }

    const fallbackHydratedResult = await hydrateInlineVideoGalleryCitation(conversationId, citation.artifact_id);
    return normalizeVideoGalleryResult(fallbackHydratedResult, maxItems);
}

function buildVideoDetailsRows(item) {
    const rows = [];

    if (item.source_label) {
        rows.push(`
            <div class="inline-video-modal-meta-row">
                <span class="inline-video-modal-meta-label">Source</span>
                <span class="inline-video-modal-meta-value">${escapeHtml(item.source_label)}</span>
            </div>
        `);
    }

    if (item.file_name) {
        rows.push(`
            <div class="inline-video-modal-meta-row">
                <span class="inline-video-modal-meta-label">File</span>
                <span class="inline-video-modal-meta-value">${escapeHtml(item.file_name)}</span>
            </div>
        `);
    }

    if (item.doc_id) {
        rows.push(`
            <div class="inline-video-modal-meta-row">
                <span class="inline-video-modal-meta-label">Document ID</span>
                <span class="inline-video-modal-meta-value text-break">${escapeHtml(item.doc_id)}</span>
            </div>
        `);
    }

    const safeSourceUrl = sanitizeHttpUrl(item.source_url);
    if (safeSourceUrl) {
        rows.push(`
            <div class="inline-video-modal-meta-row">
                <span class="inline-video-modal-meta-label">Link</span>
                <span class="inline-video-modal-meta-value">
                    <a href="${escapeHtml(safeSourceUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(safeSourceUrl)}</a>
                </span>
            </div>
        `);
    }

    return rows.join("");
}

function getInlineVideoDetailsModal() {
    let modalContainer = document.getElementById("inline-video-details-modal");
    if (modalContainer) {
        return modalContainer;
    }

    modalContainer = document.createElement("div");
    modalContainer.id = "inline-video-details-modal";
    modalContainer.className = "modal fade";
    modalContainer.tabIndex = -1;
    modalContainer.setAttribute("aria-hidden", "true");
    modalContainer.innerHTML = `
        <div class="modal-dialog modal-dialog-scrollable modal-xl modal-fullscreen-sm-down">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="inline-video-details-title">Video details</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                    <div class="inline-video-modal-stage mb-3">
                        <video id="inline-video-details-preview" class="w-100" controls playsinline preload="metadata"></video>
                    </div>
                    <p id="inline-video-details-description" class="inline-video-modal-description d-none"></p>
                    <div id="inline-video-details-meta" class="inline-video-modal-meta"></div>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modalContainer);
    return modalContainer;
}

function showInlineVideoDetailsModal(item) {
    const modalContainer = getInlineVideoDetailsModal();
    const titleEl = modalContainer.querySelector("#inline-video-details-title");
    const previewEl = modalContainer.querySelector("#inline-video-details-preview");
    const descriptionEl = modalContainer.querySelector("#inline-video-details-description");
    const metaEl = modalContainer.querySelector("#inline-video-details-meta");

    if (titleEl) {
        titleEl.textContent = item.title || "Video details";
    }

    if (previewEl) {
        previewEl.pause();
        previewEl.src = item.full_video_url || item.preview_video_url;
        if (item.poster_url) {
            previewEl.setAttribute("poster", item.poster_url);
        } else {
            previewEl.removeAttribute("poster");
        }
        previewEl.load();
    }

    if (descriptionEl) {
        const hasDescription = Boolean(item.description);
        descriptionEl.classList.toggle("d-none", !hasDescription);
        descriptionEl.textContent = item.description || "";
    }

    if (metaEl) {
        metaEl.innerHTML = buildVideoDetailsRows(item);
    }

    modalContainer.addEventListener("hidden.bs.modal", () => {
        if (previewEl) {
            previewEl.pause();
            previewEl.currentTime = 0;
        }
    }, { once: true });

    const modal = new bootstrap.Modal(modalContainer);
    modal.show();
}

function createBadge(label, value) {
    const badge = document.createElement("span");
    badge.className = "inline-video-gallery-badge";
    badge.textContent = `${label}: ${value}`;
    return badge;
}

function createVideoTile(item) {
    const tile = document.createElement("article");
    tile.className = "inline-video-gallery-item";
    tile.innerHTML = `
        <div class="inline-video-gallery-stage">
            <video class="inline-video-gallery-item-video" controls playsinline preload="metadata"></video>
            <button type="button" class="inline-video-gallery-info-btn" aria-label="Show video details">
                <i class="bi bi-info-circle-fill"></i>
            </button>
        </div>
        <div class="inline-video-gallery-item-copy">
            <div class="inline-video-gallery-item-meta">${escapeHtml(item.source_label)}</div>
            <div class="inline-video-gallery-item-title">${escapeHtml(item.title || "Video")}</div>
            ${item.description ? `<div class="inline-video-gallery-item-description">${escapeHtml(item.description)}</div>` : ""}
        </div>
    `;

    const videoEl = tile.querySelector(".inline-video-gallery-item-video");
    const infoButton = tile.querySelector(".inline-video-gallery-info-btn");
    if (videoEl) {
        videoEl.src = item.preview_video_url || item.full_video_url;
        if (item.poster_url) {
            videoEl.setAttribute("poster", item.poster_url);
        }
    }

    if (infoButton) {
        infoButton.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            showInlineVideoDetailsModal(item);
        });
    }

    return tile;
}

function createVideoGalleryCard(result) {
    const payload = result.video_gallery || {};
    const card = document.createElement("section");
    card.className = "inline-video-gallery-card";

    const renderedCount = Number(payload.rendered_count || (payload.items || []).length || 0);
    const totalCount = Number(payload.total_count || renderedCount || 0);
    const summaryText = payload.summary || result.summary || "Relevant video results.";

    card.innerHTML = `
        <div class="inline-video-gallery-header">
            <div class="inline-video-gallery-copy">
                <div class="inline-video-gallery-title-row">
                    <span class="inline-video-gallery-icon"><i class="bi bi-camera-video"></i></span>
                    <h6 class="inline-video-gallery-title mb-0">${escapeHtml(payload.title || "Video results")}</h6>
                </div>
                <p class="inline-video-gallery-summary mb-0">${escapeHtml(summaryText)}</p>
            </div>
            <div class="inline-video-gallery-badges" aria-label="Video gallery details"></div>
        </div>
        <div class="inline-video-gallery-grid"></div>
        <div class="inline-video-gallery-footer">
            <span>Inline videos</span>
            ${payload.source_action_name ? `<span class="inline-video-gallery-footer-separator">•</span><span>${escapeHtml(payload.source_action_name)}</span>` : ""}
        </div>
    `;

    const badgesContainer = card.querySelector(".inline-video-gallery-badges");
    if (badgesContainer) {
        badgesContainer.appendChild(createBadge("Videos", renderedCount));
        if (totalCount > renderedCount) {
            badgesContainer.appendChild(createBadge("Showing", `${renderedCount} of ${totalCount}`));
        }
    }

    const grid = card.querySelector(".inline-video-gallery-grid");
    if (grid) {
        (payload.items || []).forEach((item) => {
            grid.appendChild(createVideoTile(item));
        });
    }

    return { card };
}

export async function renderInlineVideoGalleries(
    messageElement,
    hybridCitations = [],
    webCitations = [],
    agentCitations = [],
    conversationId = ""
) {
    if (!messageElement) {
        return;
    }

    const container = messageElement.querySelector(".inline-visualizations-container");
    if (!container) {
        return;
    }

    container.querySelectorAll(".inline-video-gallery-card").forEach((card) => card.remove());

    const hasHybridCitations = Array.isArray(hybridCitations) && hybridCitations.length > 0;
    const hasWebCitations = Array.isArray(webCitations) && webCitations.length > 0;
    const hasAgentCitations = Array.isArray(agentCitations) && agentCitations.length > 0;
    if (!hasHybridCitations && !hasWebCitations && !hasAgentCitations) {
        container.classList.toggle("d-none", container.children.length === 0);
        return;
    }

    let remainingSlots = MAX_INLINE_VIDEO_ITEMS;
    const seenVideoKeys = new Set();

    const workspaceItems = extractWorkspaceCitationVideoItems(hybridCitations, seenVideoKeys);
    if (workspaceItems.length > 0 && remainingSlots > 0) {
        const workspaceGallery = buildVideoGalleryResult(
            "Workspace videos",
            "Video sources cited from workspace content.",
            workspaceItems.slice(0, remainingSlots),
            "Workspace citations",
            workspaceItems.length
        );
        if (workspaceGallery) {
            const { card } = createVideoGalleryCard(workspaceGallery);
            container.appendChild(card);
            remainingSlots -= workspaceGallery.video_gallery.rendered_count || 0;
        }
    }

    const linkedItems = extractLinkedVideoItems(webCitations, seenVideoKeys);
    if (linkedItems.length > 0 && remainingSlots > 0) {
        const linkedGallery = buildVideoGalleryResult(
            "Linked videos",
            "Direct video links returned with this response.",
            linkedItems.slice(0, remainingSlots),
            "Linked sources",
            linkedItems.length
        );
        if (linkedGallery) {
            const { card } = createVideoGalleryCard(linkedGallery);
            container.appendChild(card);
            remainingSlots -= linkedGallery.video_gallery.rendered_count || 0;
        }
    }

    for (let index = 0; index < agentCitations.length && remainingSlots > 0; index += 1) {
        const citation = agentCitations[index];
        const result = await resolveInlineVideoGallery(citation, conversationId, remainingSlots);
        if (!result) {
            continue;
        }

        const normalizedItems = Array.isArray(result?.video_gallery?.items)
            ? result.video_gallery.items.filter((item) => {
                const identityKey = getItemIdentityKey(item);
                if (!identityKey || seenVideoKeys.has(identityKey)) {
                    return false;
                }

                seenVideoKeys.add(identityKey);
                return true;
            })
            : [];
        if (normalizedItems.length === 0) {
            continue;
        }

        result.video_gallery.items = normalizedItems;
        result.video_gallery.rendered_count = normalizedItems.length;

        const { card } = createVideoGalleryCard(result);
        container.appendChild(card);
        remainingSlots -= normalizedItems.length;
    }

    container.classList.toggle("d-none", container.children.length === 0);
}