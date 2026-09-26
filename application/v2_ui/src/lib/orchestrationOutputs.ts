// orchestrationOutputs.ts

import type { GeneratedArtifact } from './generatedArtifacts';

export type OrchestrationOutputState =
    | 'waiting'
    | 'rendering'
    | 'retry_scheduled'
    | 'completed'
    | 'failed'
    | 'cancelled';

/** The allowlisted public_output projection. Nulls fail closed for malformed wire values. */
export interface OrchestrationOutput {
    output_id: string;
    step_id: string;
    file_name: string;
    output_format: string;
    profile: string;
    state: OrchestrationOutputState | null;
    attempt_count: number | null;
    automatic_attempts: number | null;
    max_automatic_attempts: number | null;
    next_retry_at: string | null;
    can_retry: boolean;
    available?: boolean;
    error_code: string | null;
    message: string;
    artifact_message_id: string | null;
    row_count: number | null;
    character_count: number | null;
    size_bytes: number | null;
}

/** Browser request state, not another file lifecycle or execution attempt. */
export interface OrchestrationOutputRetry {
    submitting?: boolean;
    submissionId?: string;
    baselineAttemptCount?: number;
    uncertain?: boolean;
    blocked?: boolean;
    error?: string | null;
}

function text(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

function count(value: unknown): number | null {
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

export function normalizeOrchestrationOutputs(value: unknown): OrchestrationOutput[] | undefined {
    if (!Array.isArray(value)) return undefined;
    return value.map((raw) => {
        const data: Record<string, unknown> = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
        const state = data.state;
        const knownState = state === 'waiting' || state === 'rendering' || state === 'retry_scheduled'
            || state === 'completed' || state === 'failed' || state === 'cancelled' ? state : null;
        const outputId = text(data.output_id);
        return {
            output_id: outputId,
            step_id: text(data.step_id),
            file_name: text(data.file_name),
            output_format: text(data.output_format),
            profile: text(data.profile),
            state: knownState,
            attempt_count: count(data.attempt_count),
            automatic_attempts: count(data.automatic_attempts),
            max_automatic_attempts: count(data.max_automatic_attempts),
            next_retry_at: text(data.next_retry_at) || null,
            can_retry: Boolean(outputId) && knownState === 'failed' && data.can_retry === true
                && data.available !== false,
            ...(typeof data.available === 'boolean' ? { available: data.available } : {}),
            error_code: text(data.error_code) || null,
            message: text(data.message),
            artifact_message_id: knownState === 'completed' && data.available !== false
                ? text(data.artifact_message_id) || null : null,
            row_count: count(data.row_count),
            character_count: count(data.character_count),
            size_bytes: count(data.size_bytes),
        };
    });
}

/** Step frames can describe one file; they must not remove its siblings. */
export function mergeOrchestrationOutputs(
    previous: readonly OrchestrationOutput[] = [],
    updates: readonly OrchestrationOutput[],
): OrchestrationOutput[] {
    const remaining = [...updates];
    const merged = previous.map((output) => {
        const index = remaining.findIndex((entry) => entry.output_id && entry.output_id === output.output_id);
        return index < 0 ? output : remaining.splice(index, 1)[0];
    });
    return [...merged, ...remaining];
}

export function hasPendingOrchestrationOutputs(outputs?: readonly OrchestrationOutput[]): boolean {
    return Boolean(outputs?.some((output) => output.available !== false
        && (output.state === 'waiting' || output.state === 'rendering' || output.state === 'retry_scheduled')));
}

const OUTPUT_TYPE_LABELS: Readonly<Record<string, string>> = {
    csv: 'CSV file',
    docx: 'Word document',
    json: 'JSON file',
    md: 'Markdown file',
    pdf: 'PDF document',
    pptx: 'PowerPoint deck',
    txt: 'Text file',
    xlsx: 'Excel workbook',
    xml: 'XML file',
    yaml: 'YAML file',
};

/** What a person calls the file, rather than its wire format. */
export function orchestrationOutputTypeLabel(outputFormat: string): string {
    const format = outputFormat.trim().replace(/^\./, '').toLowerCase();
    return OUTPUT_TYPE_LABELS[format] ?? (format ? `${format.toUpperCase()} file` : 'File');
}

export function isOrchestrationOutputArtifact(artifact: GeneratedArtifact): boolean {
    return artifact.capability === 'render_file';
}

/** A completed status is not a download descriptor. Both server identities must agree. */
export function committedOrchestrationArtifact(
    output: OrchestrationOutput,
    artifacts: readonly GeneratedArtifact[],
    conversationId: string,
): GeneratedArtifact | undefined {
    if (output.state !== 'completed' || output.available === false || !output.output_id
        || !output.artifact_message_id) return undefined;
    return artifacts.find((artifact) => isOrchestrationOutputArtifact(artifact)
        && artifact.source_kind === 'orchestration_retained_output'
        && artifact.output_id === output.output_id
        && artifact.artifact_message_id === output.artifact_message_id
        && artifact.conversation_id === conversationId
        && (artifact.source_conversation_id === undefined || artifact.source_conversation_id === conversationId)
        && artifact.storage_scope === 'chat'
        && typeof artifact.file_name === 'string' && Boolean(artifact.file_name)
        && typeof artifact.output_format === 'string' && Boolean(artifact.output_format)
        && typeof artifact.profile === 'string' && Boolean(artifact.profile)
        && !artifact.background_export);
}
