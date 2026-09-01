// composerGating.ts
// Which composer controls are relevant right now.
//
// Rules mirrored from `updateComposerActionVisibility` and
// `updateDeepResearchAvailability` in static/js/chat/chat-input-actions.js. Two of the
// controls are gated on what is currently typed, not only on settings:
//
//   - Read URLs appears only when the prompt actually contains a URL.
//   - Deep research appears only when there is something for it to research.
//
// Showing every capability at all times is what makes the row crowded, and offering
// "Read URLs" when there is no URL to read is an invitation to a confusing result.

/** Matches the URL detection in the classic client. */
const URL_PATTERN = /https?:\/\/[^\s<>'"]+/gi;

/** URLs currently present in the prompt. */
export function promptUrls(prompt: string): string[] {
    return String(prompt || '').match(URL_PATTERN) ?? [];
}

export interface GatingInput {
    prompt: string;
    /** Admin capability flags from the bootstrap payload. */
    features: Record<string, unknown>;
    webSearchActive: boolean;
    urlAccessActive: boolean;
    imageGenerationActive: boolean;
}

export interface ControlGating {
    showDocuments: boolean;
    showWeb: boolean;
    showImage: boolean;
    showUrlAccess: boolean;
    showDeepResearch: boolean;
    showFileUpload: boolean;
    /**
     * Image generation is mutually exclusive with the retrieval controls: while it is on,
     * the others are disabled and the model picker is hidden, because the request goes to
     * an image endpoint that ignores them.
     */
    disabledByImageGeneration: boolean;
    showModelPicker: boolean;
}

function enabled(features: Record<string, unknown>, key: string): boolean {
    return features?.[key] === true;
}

export function resolveGating(input: GatingInput): ControlGating {
    const { prompt, features, webSearchActive, urlAccessActive, imageGenerationActive } = input;
    const urls = promptUrls(prompt);
    const hasUrls = urls.length > 0;

    // Read URLs needs both the capability and something to read.
    const showUrlAccess = enabled(features, 'enable_url_access') && hasUrls;

    // Deep research needs a source to work from: the web, or URLs that have been provided.
    const showDeepResearch =
        enabled(features, 'enable_source_review') &&
        (webSearchActive || (urlAccessActive && hasUrls) || hasUrls);

    return {
        showDocuments: true,
        showWeb: enabled(features, 'enable_web_search'),
        showImage: enabled(features, 'enable_image_generation'),
        showUrlAccess,
        showDeepResearch,
        showFileUpload: enabled(features, 'enable_chat_file_uploads'),
        disabledByImageGeneration: imageGenerationActive,
        showModelPicker: !imageGenerationActive,
    };
}
