// conversationExport.ts
// The decisions a conversation export makes, kept out of the dialog that presents them.
//
// The wizard is mostly presentation, but three things in it are easy to get wrong in ways no
// type checker would catch, so they live here where they can be tested directly:
//
//   - which steps exist, since exporting one conversation skips the review step;
//   - what packaging to start on, which depends on how many conversations were picked;
//   - how a chosen summary model becomes request fields, which the server is strict about.

import { modelIdentityForSelection, type ModelCatalogEntry } from './models';
import type {
    ConversationExportFormat,
    ConversationExportPackaging,
    ConversationExportRequest,
} from './endpoints';
import type { ExportVisualAsset } from './exportVisuals';

export type ExportStepId = 'select' | 'format' | 'packaging' | 'summary' | 'download';

export interface ExportStep {
    id: ExportStepId;
    label: string;
}

const ALL_STEPS: readonly ExportStep[] = Object.freeze([
    { id: 'select', label: 'Select' },
    { id: 'format', label: 'Format' },
    { id: 'packaging', label: 'Packaging' },
    { id: 'summary', label: 'Summary' },
    { id: 'download', label: 'Download' },
]);

/**
 * The steps this export runs through.
 *
 * Exporting from a single conversation's own menu has nothing to review — the user picked it
 * by opening its menu — so that export starts at the format choice, exactly as the classic
 * wizard does.
 */
export function exportSteps(skipSelection: boolean): ExportStep[] {
    return ALL_STEPS.filter((step) => !(skipSelection && step.id === 'select'));
}

/**
 * Where packaging starts.
 *
 * One conversation is almost always wanted as a plain file, and several are almost always
 * wanted as separate files, so the default follows the count rather than being fixed. Either
 * can still be changed on the packaging step.
 */
export function defaultPackaging(conversationCount: number): ConversationExportPackaging {
    return conversationCount > 1 ? 'zip' : 'single';
}

/** The `summary_*` request fields for a chosen model, or empty when none is chosen. */
export function summaryModelFields(
    models: ModelCatalogEntry[] | undefined,
    selectionKey: string | undefined,
): Pick<
    ConversationExportRequest,
    | 'summary_model_deployment'
    | 'summary_model_endpoint_id'
    | 'summary_model_id'
    | 'summary_model_provider'
> {
    // Reuses the chat picker's own mapping rather than repeating it, so a model selected for
    // a summary resolves to the same endpoint it would have resolved to in the composer.
    const identity = modelIdentityForSelection(models, selectionKey);

    return {
        summary_model_deployment: identity.model_deployment ?? null,
        summary_model_endpoint_id: identity.model_endpoint_id ?? null,
        summary_model_id: identity.model_id ?? null,
        summary_model_provider: identity.model_provider ?? null,
    };
}

export interface ConversationExportOptions {
    conversationIds: string[];
    format: ConversationExportFormat;
    packaging: ConversationExportPackaging;
    includeSummaryIntro: boolean;
    models?: ModelCatalogEntry[];
    summaryModelKey?: string;
    visualAssets?: ExportVisualAsset[];
}

/**
 * Assemble the export request.
 *
 * The summary fields are nulled unless an intro was actually asked for. Sending a model with
 * `include_summary_intro` false would be harmless today, but it would also mean the request
 * no longer describes what the user chose, which is how the two drift apart.
 */
export function buildConversationExportRequest(
    options: ConversationExportOptions,
): ConversationExportRequest {
    const {
        conversationIds,
        format,
        packaging,
        includeSummaryIntro,
        models,
        summaryModelKey,
        visualAssets = [],
    } = options;

    return {
        conversation_ids: conversationIds,
        format,
        packaging,
        include_summary_intro: includeSummaryIntro,
        ...(includeSummaryIntro
            ? summaryModelFields(models, summaryModelKey)
            : {
                  summary_model_deployment: null,
                  summary_model_endpoint_id: null,
                  summary_model_id: null,
                  summary_model_provider: null,
              }),
        visual_assets: visualAssets,
    };
}

/**
 * Whether an export of this format needs its diagrams turned into pictures first.
 *
 * A JSON export carries the original markdown, fences and all, so rasterizing for one would
 * be wasted work: the diagrams are still there as source for whatever reads the file.
 */
export function needsVisualAssets(format: ConversationExportFormat): boolean {
    return format !== 'json';
}
