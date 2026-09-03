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
//
// The model and reasoning controls are gated on the agent selection for the same reason. An
// agent answers with its own deployment (`azure_openai_gpt_deployment`, read by
// semantic_kernel_loader.py), and `reasoning_effort` only ever reaches the direct-model path
// (`_resolve_reasoning_effort_for_model` in route_backend_chats.py). Leaving either control
// looking live under an agent advertises a choice the request cannot act on.

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
    /** True while an agent is selected in the composer. */
    agentActive: boolean;
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
    /**
     * The model picker is retained but overridden: an agent is selected, so it supplies the
     * deployment. The picker stays usable, because choosing a model is how the user gets
     * back out of agent mode.
     */
    modelPickerInactive: boolean;
    /**
     * Whether a reasoning level is a real choice right now. Mirrors
     * `updateReasoningButtonVisibility` in static/js/chat/chat-reasoning.js, which hides the
     * control for image generation and for agents alike. Model support is a separate
     * question, resolved from the catalog by the caller.
     */
    showReasoning: boolean;
}

function enabled(features: Record<string, unknown>, key: string): boolean {
    return features?.[key] === true;
}

export function resolveGating(input: GatingInput): ControlGating {
    const {
        prompt,
        features,
        webSearchActive,
        urlAccessActive,
        imageGenerationActive,
        agentActive,
    } = input;
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
        modelPickerInactive: agentActive,
        showReasoning: !agentActive && !imageGenerationActive,
    };
}
