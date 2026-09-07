// chat-citation-tracking.js
/**
 * Browser mirror of functions_citation_tracking.py tracking detection.
 *
 * Assistant messages carry both the complete retrieved source arrays
 * (hybrid_citations, web_search_citations) and the smaller subsets that the
 * final response explicitly cited (cited_hybrid_citations,
 * cited_web_search_citations). Surfaces that present media or references as
 * supporting the answer must read the cited subsets, while the Sources
 * disclosure keeps showing everything that was retrieved.
 *
 * Messages saved before citation tracking existed carry no cited arrays. Those
 * fall back to the full source arrays rather than being parsed at read time,
 * matching get_message_reference_citation_buckets() on the server.
 */

const MIN_CITATION_TRACKING_VERSION = 1;

function toCitationArray(value) {
    return Array.isArray(value) ? value : [];
}

export function messageHasCitationTracking(message) {
    if (!message || typeof message !== "object") {
        return false;
    }

    const trackingVersion = Number(message.citation_tracking_version);
    if (Number.isInteger(trackingVersion) && trackingVersion >= MIN_CITATION_TRACKING_VERSION) {
        return true;
    }

    return "cited_hybrid_citations" in message || "cited_web_search_citations" in message;
}

export function getCitedHybridCitations(message, sourceCitations = []) {
    if (!messageHasCitationTracking(message)) {
        return toCitationArray(sourceCitations);
    }

    return toCitationArray(message.cited_hybrid_citations);
}

export function getCitedWebCitations(message, sourceCitations = []) {
    if (!messageHasCitationTracking(message)) {
        return toCitationArray(sourceCitations);
    }

    return toCitationArray(message.cited_web_search_citations);
}
