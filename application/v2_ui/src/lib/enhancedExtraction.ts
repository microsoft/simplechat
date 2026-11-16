// enhancedExtraction.ts
// Which engine backs Enhanced extraction, read from the admin settings on screen.
//
// Enhanced extraction is served by Azure AI Content Understanding when the service is
// offered in this cloud and connected, and by Document Intelligence Layout otherwise. Only
// Content Understanding describes figures and charts, so which one is in force is the thing
// an administrator turning Enhanced on needs to know -- and nothing on the card used to
// say. This mirrors `resolve_enhanced_extraction_engine` and
// `is_content_understanding_configured` in functions_settings.py so the card can say it
// before anything is uploaded.
//
// It judges configuration, not connectivity. The server stays authoritative, and the
// connection test is what proves the service answers.

import { asString } from './adminFields';

export type EnhancedExtractionEngine = 'content_understanding' | 'document_intelligence';

/** Why Enhanced extraction uses Document Intelligence Layout, when it does. */
export type EnhancedExtractionFallbackReason =
    | 'unsupported_cloud'
    | 'missing_endpoint'
    | 'missing_key';

export interface EnhancedExtractionEngineReading {
    engine: EnhancedExtractionEngine;
    reason: EnhancedExtractionFallbackReason | null;
}

export const CONTENT_UNDERSTANDING_ENDPOINT_KEY = 'azure_content_understanding_endpoint';
export const CONTENT_UNDERSTANDING_AUTHENTICATION_TYPE_KEY =
    'azure_content_understanding_authentication_type';
export const CONTENT_UNDERSTANDING_KEY_KEY = 'azure_content_understanding_key';

/** The runtime flag the settings API sends for clouds that offer Content Understanding. */
export const CONTENT_UNDERSTANDING_SUPPORTED_FLAG = 'content_understanding_supported';

/**
 * Resolve the engine a document extracted as Enhanced would use.
 *
 * `read` returns a setting's current value, preferring an unsaved edit. A stored key reaches
 * the browser as the redaction placeholder, which is a value, so an untouched credential
 * still counts as configured.
 */
export function resolveEnhancedExtractionEngine(
    read: (key: string) => unknown,
    contentUnderstandingSupported: boolean,
): EnhancedExtractionEngineReading {
    if (!contentUnderstandingSupported) {
        return { engine: 'document_intelligence', reason: 'unsupported_cloud' };
    }

    // The server trims whitespace and trailing slashes before deciding, so an endpoint of
    // only those is blank there too.
    const endpoint = asString(read(CONTENT_UNDERSTANDING_ENDPOINT_KEY)).trim().replace(/\/+$/, '');
    if (!endpoint) {
        return { engine: 'document_intelligence', reason: 'missing_endpoint' };
    }

    // Anything other than managed identity is normalised to key authentication.
    const authenticationType = asString(read(CONTENT_UNDERSTANDING_AUTHENTICATION_TYPE_KEY))
        .trim()
        .toLowerCase();
    if (authenticationType !== 'managed_identity' && !asString(read(CONTENT_UNDERSTANDING_KEY_KEY)).trim()) {
        return { engine: 'document_intelligence', reason: 'missing_key' };
    }

    return { engine: 'content_understanding', reason: null };
}
