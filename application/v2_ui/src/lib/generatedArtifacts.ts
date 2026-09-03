// generatedArtifacts.ts
// The files an assistant turn produced, read off the message it produced them on.
//
// A tabular export, an Analyze summary or a comparison workbook is written to storage by the
// server and then advertised on the assistant message as metadata. Without a reader for that
// metadata the file still exists and is still downloadable, but nothing in the interface says
// so — which is indistinguishable from the export having failed.
//
// Two keys carry the same records. `generated_analysis_artifacts` is the general list and
// `generated_tabular_outputs` is the tabular subset of it, and the server writes a tabular
// artifact to both. They are merged and de-duplicated here on the same keys the server uses
// in `_build_generated_analysis_metadata`, so a tabular export appears once rather than twice.
//
// Everything in this module is pure. The rendering lives in `GeneratedArtifactCard`, and the
// split is what lets the normalising, the download-target choice and the run-progress
// arithmetic be tested without a DOM.

/**
 * One generated file as the server describes it.
 *
 * The server spreads the producing action's own metadata into this record, so the shape is
 * open. Only the fields this interface reads are relied upon; the rest is carried through
 * untouched so a future server field needs no change here to survive a round trip.
 */
export interface GeneratedArtifact {
    [key: string]: unknown;

    /** `tabular`, `analysis`, `analyze`, `comparison` or `file_export`. */
    capability: string;
    /** Set when the file lives on its own message in this conversation. */
    artifact_message_id: string;
    /** Set when the file was saved to the personal workspace. */
    document_id: string;
    export_run_id: string;
    run_id: string;
    /** True while a durable run is still producing the file. */
    background_export: boolean;
    suppress_assistant_table_export: boolean;
}

/**
 * A durable run's progress as the runs endpoint reports it.
 *
 * Deliberately untyped per field. The same record is also read straight off an artifact,
 * whose own fields are open, and every reader below coerces defensively — so naming the
 * types here would buy nothing and would stop an artifact being passed as a run. The fields
 * actually read are `status`, `status_label`, `status_tone`, `status_detail`, `last_message`,
 * `checkpoint_summary`, `task_type`, `analysis_phase`, `progress_percent`,
 * `completed_batches`, `batch_count`, `processed_rows`, `row_count`, `processed_chunk_count`,
 * `total_chunk_count`, `failed_chunk_count`, `analysis_reduce_level`, `analysis_reduce_node`,
 * `analysis_reduce_node_count`, `rows_per_minute`, `batch_concurrency`,
 * `effective_batch_concurrency`, `waiting_for_retry`, `next_attempt_at`,
 * `retry_delay_seconds`, `estimated_remaining_seconds`, `transient_failure_count`,
 * `manual_resume_count`, `updated_at`, `created_at`, `last_heartbeat_at`, `can_resume`,
 * `can_cancel`, `retryable_failure`, `background_export`, `run_id` and `artifact_set`.
 */
export type GeneratedRunStatus = Record<string, unknown>;

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : value == null ? '' : String(value).trim();
}

function lower(value: unknown): string {
    return text(value).toLowerCase();
}

function whole(value: unknown): number {
    const parsed = Number.parseInt(String(value ?? ''), 10);
    return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function decimal(value: unknown): number {
    const parsed = Number.parseFloat(String(value ?? ''));
    return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Turn one raw metadata entry into an artifact, or reject it.
 *
 * An entry is only useful if it names somewhere to fetch the file from — a message, a
 * workspace document or a run still producing it. The one exception is a run that ended
 * `failed` or `canceled` while suppressing the assistant's own table: that has nothing to
 * download but must still be shown, because the alternative is a turn that silently drops
 * both the table it replaced and the file it failed to produce.
 */
export function normalizeGeneratedArtifact(
    raw: unknown,
    defaultCapability = 'analysis',
): GeneratedArtifact | null {
    if (!isRecord(raw)) {
        return null;
    }

    const artifactMessageId = text(raw.artifact_message_id);
    const documentId = text(raw.document_id);
    const exportRunId = text(raw.export_run_id) || text(raw.run_id);
    const isBackgroundExport = Boolean(raw.background_export) && Boolean(exportRunId);
    const terminalStatus = lower(raw.status);
    const isTerminalExportStatus = Boolean(
        raw.suppress_assistant_table_export && ['failed', 'canceled'].includes(terminalStatus),
    );

    if (!artifactMessageId && !documentId && !isBackgroundExport && !isTerminalExportStatus) {
        return null;
    }

    return {
        ...raw,
        capability: lower(raw.capability) || lower(defaultCapability) || 'analysis',
        artifact_message_id: artifactMessageId,
        document_id: documentId,
        export_run_id: exportRunId,
        run_id: exportRunId,
        background_export: isBackgroundExport || isTerminalExportStatus,
        suppress_assistant_table_export: Boolean(raw.suppress_assistant_table_export),
    };
}

function dedupeKey(artifact: GeneratedArtifact): string {
    return (
        artifact.artifact_message_id ||
        artifact.document_id ||
        artifact.export_run_id ||
        `${text(artifact.file_name)}:${text(artifact.output_format)}`
    );
}

/**
 * Read every generated artifact off an assistant message's metadata.
 *
 * The general list is read first so that a tabular export arriving in both collections keeps
 * whichever capability the server assigned it, rather than being relabelled by the key it
 * happened to be found under second.
 */
export function readGeneratedArtifacts(metadata: unknown): GeneratedArtifact[] {
    if (!isRecord(metadata)) {
        return [];
    }

    const artifacts: GeneratedArtifact[] = [];
    const seen = new Set<string>();

    const append = (raw: unknown, defaultCapability: string) => {
        const artifact = normalizeGeneratedArtifact(raw, defaultCapability);
        if (!artifact) {
            return;
        }
        const key = dedupeKey(artifact);
        if (seen.has(key)) {
            return;
        }
        seen.add(key);
        artifacts.push(artifact);
    };

    const general = metadata.generated_analysis_artifacts;
    if (Array.isArray(general)) {
        general.forEach((entry) => append(entry, 'analysis'));
    }

    const tabular = metadata.generated_tabular_outputs;
    if (Array.isArray(tabular)) {
        tabular.forEach((entry) => append(entry, 'tabular'));
    }

    return artifacts;
}

export function artifactOutputFormat(artifact: GeneratedArtifact): string {
    return lower(artifact.output_format) || 'json';
}

export function artifactFileName(artifact: GeneratedArtifact): string {
    return text(artifact.file_name) || `generated-output.${artifactOutputFormat(artifact)}`;
}

/**
 * Where the file can be fetched from.
 *
 * A conversation-scoped artifact is preferred over a workspace document because it is the
 * copy this turn produced; the workspace copy may be a later revision. Returns an empty
 * string when neither target is known, which the card treats as "no download control".
 */
export function artifactDownloadPath(
    artifact: GeneratedArtifact,
    fallbackConversationId = '',
): string {
    const messageId = text(artifact.artifact_message_id);
    const conversationId = text(artifact.conversation_id) || text(fallbackConversationId);

    if (messageId && conversationId) {
        return `/api/chat_artifacts/download?conversation_id=${encodeURIComponent(
            conversationId,
        )}&message_id=${encodeURIComponent(messageId)}`;
    }

    const documentId = text(artifact.document_id);
    if (documentId) {
        return `/api/workspace_documents/download?doc_id=${encodeURIComponent(documentId)}`;
    }

    return '';
}

export function formatArtifactRowCount(rowCount: unknown): string {
    const parsed = whole(rowCount);
    if (!Number.isFinite(parsed) || parsed < 0) {
        return '';
    }
    return parsed.toLocaleString();
}

/** Where the file went, phrased so the reader knows where to look for it later. */
export function artifactStorageNote(artifact: GeneratedArtifact): string {
    if (artifact.background_export) {
        return 'Continuing in the background. Progress is checkpointed and the download will appear here when complete.';
    }
    if (lower(artifact.storage_scope) === 'chat') {
        return 'Saved to this chat for download in this conversation.';
    }
    return 'Saved to your personal workspace for reuse in future chats.';
}

export function artifactTitle(artifact: GeneratedArtifact): string {
    const outputFormat = artifactOutputFormat(artifact).toUpperCase();
    const artifactId = lower(artifact.artifact_id) || lower(artifact.member_id);

    if (artifactId === 'analysis-summary') {
        return 'Analyze Markdown summary';
    }
    if (artifactId === 'row-analysis-md') {
        return 'Row-by-row Markdown output';
    }

    const capability = lower(artifact.capability);
    if (capability === 'analyze') {
        return `Analyze ${outputFormat} artifact`;
    }
    if (capability === 'comparison') {
        return `Comparison ${outputFormat} artifact`;
    }
    return `Generated ${outputFormat} export`;
}

/**
 * Analyze and comparison previews are prose, and long enough that showing them expanded
 * pushes the assistant's own answer off screen. They open on request instead.
 */
export function shouldCollapsePreview(artifact: GeneratedArtifact): boolean {
    const capability = lower(artifact.capability);
    return capability === 'analyze' || capability === 'comparison';
}

/**
 * Whether the reply's own text should give way to the artifact cards.
 *
 * A turn that hands work off to a durable run answers with a holding sentence — "I am
 * generating this in the background" — which is actively misleading once the file has landed.
 * The server marks those turns, and the card replaces the sentence rather than sitting under
 * a stale promise. Only applies once the run is finished; while it is still going the
 * sentence is accurate.
 */
export function suppressesAssistantText(artifacts: GeneratedArtifact[]): boolean {
    return artifacts.some(
        (artifact) => !artifact.background_export && Boolean(artifact.suppress_assistant_text),
    );
}

/* -------------------------------------------------------------------------- */
/* Approval                                                                    */
/* -------------------------------------------------------------------------- */

export interface ArtifactApproval {
    state: string;
    isPending: boolean;
    isApproved: boolean;
    isDenied: boolean;
    isAutoDenied: boolean;
    viewerCanApprove: boolean;
    viewerIsRequester: boolean;
    requestedByName: string;
    resolvedByName: string;
}

/**
 * The approval a generated file is waiting on, when it is waiting on one.
 *
 * A file generated in a shared conversation would become available to every participant, so
 * the conversation's owner decides first. Artifacts produced by the owner carry no descriptor
 * and are never gated.
 */
export function readArtifactApproval(artifact: GeneratedArtifact): ArtifactApproval | null {
    const raw = artifact.approval;
    if (!isRecord(raw)) {
        return null;
    }

    const state = lower(raw.state);
    if (!state) {
        return null;
    }

    return {
        state,
        isPending: state === 'pending_approval',
        isApproved: state === 'approved',
        isDenied: state === 'denied' || state === 'auto_denied',
        isAutoDenied: state === 'auto_denied',
        viewerCanApprove: raw.viewer_can_approve === true,
        viewerIsRequester: raw.viewer_is_requester === true,
        requestedByName: text(raw.requested_by_name),
        resolvedByName: text(raw.resolved_by_name),
    };
}

/**
 * Whether the content is withheld from everyone right now.
 *
 * A staged file is withheld from the person who asked for it too, so the download and
 * preview controls must be replaced rather than left to fail with a 403 that the interface
 * would present as an unexplained dead button.
 */
export function approvalBlocksDownload(artifact: GeneratedArtifact): boolean {
    const approval = readArtifactApproval(artifact);
    return Boolean(approval && (approval.isPending || approval.isDenied));
}

/** Why the file is unavailable, phrased for whoever is reading it. */
export function describeArtifactApproval(approval: ArtifactApproval): string {
    if (approval.isApproved) {
        return approval.resolvedByName ? `Approved by ${approval.resolvedByName}.` : 'Approved.';
    }
    if (approval.isAutoDenied) {
        return 'This file expired before it was approved and is no longer available.';
    }
    if (approval.isDenied) {
        return approval.resolvedByName
            ? `${approval.resolvedByName} declined this file, so it is not available.`
            : 'This file was declined and is not available.';
    }
    if (approval.viewerCanApprove) {
        return approval.requestedByName
            ? `${approval.requestedByName} generated this file in a shared conversation. Approve it to make it available.`
            : 'A participant generated this file in a shared conversation. Approve it to make it available.';
    }
    if (approval.viewerIsRequester) {
        return 'This file is waiting for the conversation owner to approve it before it can be downloaded.';
    }
    return 'This file is waiting for approval before it can be downloaded.';
}

export function isMarkdownArtifact(artifact: GeneratedArtifact): boolean {
    const outputFormat = lower(artifact.output_format);
    if (outputFormat === 'md' || outputFormat === 'markdown') {
        return true;
    }
    const fileName = lower(artifact.file_name);
    return fileName.endsWith('.md') || fileName.endsWith('.markdown');
}

/**
 * A finished row-level export, which gets the compact layout.
 *
 * These already say everything useful in their file name and row count, so the summary,
 * source note and inline preview are traded for a "View" control that opens the preview
 * full size when it is actually wanted.
 */
export function isCompletedTabularArtifact(artifact: GeneratedArtifact): boolean {
    return Boolean(
        !artifact.background_export &&
            ['csv', 'json', 'xml'].includes(artifactOutputFormat(artifact)) &&
            ['tabular', 'file_export'].includes(lower(artifact.capability)),
    );
}

export function artifactPreviewRows(artifact: GeneratedArtifact): Record<string, unknown>[] {
    const rows = artifact.preview_rows;
    if (Array.isArray(rows) && rows.length) {
        return rows as Record<string, unknown>[];
    }
    const items = artifact.preview_items;
    if (Array.isArray(items) && items.length) {
        return items as Record<string, unknown>[];
    }
    return [];
}

/**
 * `preview_rows` and `preview_items` separately, because the card treats them differently.
 *
 * Rows are always tabular. Items are only rendered as a table when the output format is
 * row-shaped; for a JSON or XML export they are objects whose structure a flattened table
 * would misrepresent, so those fall back to raw JSON.
 */
export function artifactPreviewRowList(artifact: GeneratedArtifact): unknown[] {
    return Array.isArray(artifact.preview_rows) ? (artifact.preview_rows as unknown[]) : [];
}

export function artifactPreviewItemList(artifact: GeneratedArtifact): unknown[] {
    return Array.isArray(artifact.preview_items) ? (artifact.preview_items as unknown[]) : [];
}

export function artifactPreviewLines(artifact: GeneratedArtifact): string[] {
    return Array.isArray(artifact.preview_lines) ? (artifact.preview_lines as string[]) : [];
}

export function artifactPreviewText(artifact: GeneratedArtifact): string {
    return (
        text(artifact.preview_text) ||
        text(artifact.analysis_text) ||
        // Present in older records written before the field was renamed.
        text(artifact.panalysis_text)
    );
}

export function hasArtifactPreview(artifact: GeneratedArtifact): boolean {
    return Boolean(
        artifactPreviewRows(artifact).length ||
            artifactPreviewLines(artifact).length ||
            artifactPreviewText(artifact),
    );
}

/** Only row-shaped formats render `preview_items` as a table; the rest stay as JSON. */
export function shouldRenderPreviewItemsAsRows(artifact: GeneratedArtifact): boolean {
    return ['csv', 'tsv', 'xls', 'xlsx', 'xlsm'].includes(artifactOutputFormat(artifact));
}

export function isPreviewObjectRow(row: unknown): row is Record<string, unknown> {
    return isRecord(row);
}

export function formatPreviewValue(value: unknown, maxLength = 120): string {
    let formatted: string;

    if (value === null || typeof value === 'undefined') {
        formatted = '';
    } else if (typeof value === 'string') {
        formatted = value;
    } else if (typeof value === 'number' || typeof value === 'boolean') {
        formatted = String(value);
    } else {
        try {
            formatted = JSON.stringify(value);
        } catch {
            formatted = String(value);
        }
    }

    return formatted.length <= maxLength ? formatted : `${formatted.slice(0, maxLength - 1)}…`;
}

export interface PreviewTableModel {
    columns: string[];
    hiddenColumnCount: number;
    rows: Record<string, unknown>[];
}

/**
 * Decide the columns for a preview table, or refuse the table entirely.
 *
 * Returns null when the rows are not uniform objects, which is the signal to fall back to
 * raw JSON rather than invent a column layout for data that has none. Declared columns come
 * first so the server's ordering is honoured, with any extra keys appended in first-seen
 * order.
 */
export function previewTableModel(
    rows: unknown,
    options: { columns?: unknown; maxColumns?: number } = {},
): PreviewTableModel | null {
    if (!Array.isArray(rows) || !rows.length || !rows.every(isPreviewObjectRow)) {
        return null;
    }

    const objectRows = rows as Record<string, unknown>[];
    const columns: string[] = Array.isArray(options.columns)
        ? (options.columns as unknown[]).map((name) => text(name)).filter(Boolean)
        : [];

    objectRows.forEach((row) => {
        Object.keys(row).forEach((name) => {
            if (!columns.includes(name)) {
                columns.push(name);
            }
        });
    });

    if (!columns.length) {
        return null;
    }

    const requested = whole(options.maxColumns);
    const maxColumns = Number.isFinite(requested) && requested > 0 ? requested : 4;
    const displayed = columns.slice(0, maxColumns);

    return {
        columns: displayed,
        hiddenColumnCount: columns.length - displayed.length,
        rows: objectRows,
    };
}

/* -------------------------------------------------------------------------- */
/* Durable run progress                                                        */
/* -------------------------------------------------------------------------- */

export function clampProgress(value: unknown): number {
    const numeric = decimal(value);
    if (!Number.isFinite(numeric)) {
        return 0;
    }
    return Math.max(0, Math.min(100, numeric));
}

/**
 * How far along a durable run is.
 *
 * The server's own percentage wins when it sends one, because it knows about phases the
 * batch counter cannot see. Batches are the fallback, and an unstarted run reports zero
 * rather than nothing so the bar is present from the first render.
 */
export function runProgressPercent(run: GeneratedRunStatus): number {
    const explicit = decimal(run.progress_percent);
    if (Number.isFinite(explicit)) {
        return clampProgress(explicit);
    }

    const completed = whole(run.completed_batches);
    const total = whole(run.batch_count);
    if (Number.isFinite(completed) && Number.isFinite(total) && total > 0) {
        return clampProgress((completed / total) * 100);
    }

    return 0;
}

export function runStatusLabel(run: GeneratedRunStatus): string {
    const explicit = text(run.status_label);
    if (explicit) {
        return explicit;
    }

    switch (lower(run.status)) {
        case 'completed':
            return 'Complete';
        case 'failed':
            return 'Failed';
        case 'canceled':
            return 'Canceled';
        case 'running':
            return 'Running';
        default:
            return 'Queued';
    }
}

export type RunTone = 'success' | 'warning' | 'danger' | 'secondary' | 'info';

export function runStatusTone(run: GeneratedRunStatus): RunTone {
    const tone = lower(run.status_tone);
    if (tone === 'success' || tone === 'warning' || tone === 'danger' || tone === 'secondary') {
        return tone;
    }
    return 'info';
}

export function runTypeLabel(run: GeneratedRunStatus): string {
    switch (lower(run.task_type)) {
        case 'combined':
            return 'Background analysis + export';
        case 'hierarchical_analysis':
            return 'Background analysis';
        default:
            return 'Background export';
    }
}

export function canResumeRun(run: GeneratedRunStatus): boolean {
    return Boolean(run.background_export && run.can_resume);
}

export function canCancelRun(run: GeneratedRunStatus): boolean {
    return Boolean(run.background_export && run.can_cancel);
}

export function resumeLabel(run: GeneratedRunStatus): string {
    return run.waiting_for_retry ? 'Continue Now' : 'Continue';
}

/**
 * Whether the run is still worth asking about.
 *
 * A failure that the server marked retryable keeps polling, because the worker may pick it
 * up again without anyone intervening; a terminal failure does not.
 */
export function shouldPollRun(run: GeneratedRunStatus): boolean {
    if (!run.background_export) {
        return false;
    }

    const status = lower(run.status);
    if (status === 'completed' || status === 'canceled') {
        return false;
    }
    if (status === 'failed' && !run.retryable_failure) {
        return false;
    }
    return true;
}

export function formatRunTimestamp(value: unknown): string {
    const normalized = text(value);
    if (!normalized) {
        return '';
    }
    const parsed = new Date(normalized);
    return Number.isNaN(parsed.getTime()) ? normalized : parsed.toLocaleString();
}

export function formatRunDuration(seconds: unknown): string {
    const normalized = whole(seconds);
    if (!Number.isFinite(normalized) || normalized < 0) {
        return '';
    }
    if (normalized < 60) {
        return '<1 min';
    }

    const totalMinutes = Math.max(1, Math.round(normalized / 60));
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;

    if (!hours) {
        return `${totalMinutes} min`;
    }
    if (!minutes) {
        return `${hours} hr`;
    }
    return `${hours} hr ${minutes} min`;
}

/**
 * The one-line explanation of what the run is doing right now.
 *
 * Assembled from whichever counters the run happens to report — a row export, a hierarchical
 * analysis and a combined run each populate a different subset — so the caller never has to
 * know which kind of run it is holding.
 */
export function runDetailParts(run: GeneratedRunStatus): string[] {
    const parts: string[] = [];

    const statusDetail = text(run.status_detail) || text(run.last_message);
    if (statusDetail) {
        parts.push(statusDetail);
    }

    const completedBatches = whole(run.completed_batches);
    const batchCount = whole(run.batch_count);
    const processedRows = whole(run.processed_rows);
    const rowCount = whole(run.row_count);

    const checkpointSummary = text(run.checkpoint_summary);
    if (checkpointSummary) {
        parts.push(checkpointSummary);
    } else if (Number.isFinite(completedBatches) && Number.isFinite(batchCount) && batchCount > 0) {
        const checkpoint = [
            `${completedBatches.toLocaleString()} of ${batchCount.toLocaleString()} batches`,
        ];
        if (Number.isFinite(processedRows) && Number.isFinite(rowCount) && rowCount > 0) {
            checkpoint.push(`${processedRows.toLocaleString()} of ${rowCount.toLocaleString()} rows`);
        }
        parts.push(checkpoint.join(', '));
    }

    const taskType = lower(run.task_type);
    const analysisPhase = lower(run.analysis_phase);
    const processedChunkCount = whole(run.processed_chunk_count);
    const totalChunkCount = whole(run.total_chunk_count);
    const failedChunkCount = whole(run.failed_chunk_count);

    if (taskType === 'hierarchical_analysis' || taskType === 'combined') {
        if (analysisPhase === 'reducing') {
            const reduce = ['Reduce phase'];
            const level = whole(run.analysis_reduce_level);
            const node = whole(run.analysis_reduce_node);
            const nodeCount = whole(run.analysis_reduce_node_count);
            if (Number.isFinite(level) && level > 0) {
                reduce.push(`level ${level.toLocaleString()}`);
            }
            if (Number.isFinite(node) && Number.isFinite(nodeCount) && nodeCount > 0) {
                reduce.push(`node ${node.toLocaleString()} of ${nodeCount.toLocaleString()}`);
            }
            parts.push(reduce.join(' '));
        } else if (analysisPhase === 'publishing') {
            parts.push('Publishing final artifact');
        } else if (
            Number.isFinite(processedChunkCount) &&
            Number.isFinite(totalChunkCount) &&
            totalChunkCount > 0
        ) {
            parts.push(
                `Map phase: ${processedChunkCount.toLocaleString()} of ${totalChunkCount.toLocaleString()} chunks`,
            );
        }

        if (Number.isFinite(failedChunkCount) && failedChunkCount > 0) {
            parts.push(`Chunks needing retry: ${failedChunkCount.toLocaleString()}`);
        }
    }

    if (Number.isFinite(completedBatches) && Number.isFinite(batchCount) && batchCount > completedBatches) {
        parts.push(`Remaining batches: ${(batchCount - completedBatches).toLocaleString()}`);
    }
    if (
        Number.isFinite(processedChunkCount) &&
        Number.isFinite(totalChunkCount) &&
        totalChunkCount > processedChunkCount
    ) {
        parts.push(`Remaining chunks: ${(totalChunkCount - processedChunkCount).toLocaleString()}`);
    }

    const rowsPerMinute = decimal(run.rows_per_minute);
    if (Number.isFinite(rowsPerMinute) && rowsPerMinute > 0) {
        parts.push(
            `Throughput: ${rowsPerMinute.toLocaleString(undefined, { maximumFractionDigits: 1 })} rows/min`,
        );
    }

    const batchConcurrency = whole(run.batch_concurrency);
    const effectiveBatchConcurrency = whole(run.effective_batch_concurrency);
    if (Number.isFinite(batchConcurrency) && batchConcurrency > 0) {
        const concurrency =
            Number.isFinite(effectiveBatchConcurrency) &&
            effectiveBatchConcurrency > 0 &&
            effectiveBatchConcurrency !== batchConcurrency
                ? `${effectiveBatchConcurrency.toLocaleString()} of ${batchConcurrency.toLocaleString()}`
                : batchConcurrency.toLocaleString();
        parts.push(`Model concurrency: ${concurrency}`);
    }

    if (run.waiting_for_retry) {
        const nextAttempt = formatRunTimestamp(run.next_attempt_at);
        const retryDelay = formatRunDuration(run.retry_delay_seconds);
        if (nextAttempt && retryDelay) {
            parts.push(`Next retry: ${nextAttempt} (${retryDelay})`);
        } else if (nextAttempt) {
            parts.push(`Next retry: ${nextAttempt}`);
        }
    } else {
        const remaining = whole(run.estimated_remaining_seconds);
        if (Number.isFinite(remaining) && remaining > 0) {
            const duration = formatRunDuration(remaining);
            if (duration) {
                parts.push(`Estimated remaining: ${duration}`);
            }
        }
    }

    const transientFailureCount = whole(run.transient_failure_count);
    if (Number.isFinite(transientFailureCount) && transientFailureCount > 0) {
        parts.push(`Transient retries: ${transientFailureCount.toLocaleString()}`);
    }
    const manualResumeCount = whole(run.manual_resume_count);
    if (Number.isFinite(manualResumeCount) && manualResumeCount > 0) {
        parts.push(`Manual continues: ${manualResumeCount.toLocaleString()}`);
    }

    return parts;
}

/** "Last update" and "Heartbeat", skipping the heartbeat when it repeats the update. */
export function runTimingParts(run: GeneratedRunStatus): string[] {
    const parts: string[] = [];
    const updatedAt = formatRunTimestamp(text(run.updated_at) || text(run.created_at));
    const heartbeatAt = formatRunTimestamp(run.last_heartbeat_at);

    if (updatedAt) {
        parts.push(`Last update: ${updatedAt}`);
    }
    if (heartbeatAt && heartbeatAt !== updatedAt) {
        parts.push(`Heartbeat: ${heartbeatAt}`);
    }
    return parts;
}

/**
 * Whether a finished run has produced downloadable members.
 *
 * A run can report `completed` while its artifact set is still being validated or has been
 * rolled back, in which case the members must not be offered as downloads yet.
 */
export function isRunArtifactSetComplete(run: GeneratedRunStatus): boolean {
    if (lower(run.status) !== 'completed') {
        return false;
    }

    const artifactSet = run.artifact_set;
    if (!isRecord(artifactSet)) {
        return true;
    }

    const lifecycleState = lower(artifactSet.lifecycle_state);
    if (lifecycleState && lifecycleState !== 'completed') {
        return false;
    }

    return !['failed', 'invalid', 'rollback_required', 'rolled_back'].includes(
        lower(artifactSet.validation_state),
    );
}

/**
 * The finished files a completed run produced, ready to replace its progress card.
 *
 * Members come from `generated_artifacts`, falling back to the singular
 * `generated_artifact` and then to the legacy metadata collections. `artifact_set` is a
 * *summary* — `member_count`, `lifecycle_state`, `primary_artifact_id` — and carries no
 * member list, so reading members from it finds nothing and silently reduces a combined run
 * to a single card, dropping the other file it produced.
 *
 * Members inherit the originating artifact's fields so a member that omits, say, the source
 * file name still renders a complete card.
 */
export function readRunArtifactSetMembers(
    run: GeneratedRunStatus,
    fallback: GeneratedArtifact,
): GeneratedArtifact[] {
    if (!isRunArtifactSetComplete(run)) {
        return [];
    }

    const runId = text(run.run_id) || fallback.export_run_id;
    const rawMembers = readRawRunMembers(run);

    const members: GeneratedArtifact[] = [];
    const seen = new Set<string>();

    rawMembers.forEach((rawMember) => {
        if (!isRecord(rawMember)) {
            return;
        }
        const capability = lower(rawMember.capability) || lower(fallback.capability) || 'tabular';
        const member = normalizeGeneratedArtifact(
            {
                ...fallback,
                ...run,
                ...rawMember,
                capability,
                status: 'completed',
                export_run_id: runId,
                run_id: runId,
                background_export: false,
                // The run's own collections would otherwise be inherited by each member and
                // re-read as that member's own artifacts.
                artifact_set: undefined,
                generated_artifacts: undefined,
                generated_artifact: undefined,
                generated_analysis_artifacts: undefined,
                generated_tabular_outputs: undefined,
            },
            capability,
        );
        if (!member) {
            return;
        }
        const key = memberDedupeKey(member);
        if (key && seen.has(key)) {
            return;
        }
        if (key) {
            seen.add(key);
        }
        members.push(member);
    });

    if (members.length) {
        return sortRunMembers(members, text(isRecord(run.artifact_set) ? run.artifact_set.primary_artifact_id : ''));
    }

    // A completed run with no member list still produced the file described by the artifact
    // the card was built from, so it is promoted rather than left showing a finished bar.
    const promoted = normalizeGeneratedArtifact(
        {
            ...fallback,
            ...run,
            capability: fallback.capability,
            status: 'completed',
            export_run_id: runId,
            run_id: runId,
            background_export: false,
            artifact_set: undefined,
            generated_artifacts: undefined,
            generated_artifact: undefined,
            generated_analysis_artifacts: undefined,
            generated_tabular_outputs: undefined,
        },
        fallback.capability,
    );

    return promoted ? [promoted] : [];
}

/** Members as the run reports them, newest contract first, then the older shapes. */
function readRawRunMembers(run: GeneratedRunStatus): unknown[] {
    if (Array.isArray(run.generated_artifacts)) {
        return run.generated_artifacts;
    }
    if (isRecord(run.generated_artifact)) {
        return [run.generated_artifact];
    }
    return [
        ...(Array.isArray(run.generated_analysis_artifacts) ? run.generated_analysis_artifacts : []),
        ...(Array.isArray(run.generated_tabular_outputs) ? run.generated_tabular_outputs : []),
    ];
}

/**
 * A member's identity, which is not the same as an artifact's.
 *
 * Members of one run share its `export_run_id`, so the artifact dedupe key would collapse
 * every member of a combined run into one. Identity here is the artifact's own id.
 */
function memberDedupeKey(member: GeneratedArtifact): string {
    const messageId = text(member.artifact_message_id);
    if (messageId) {
        return `message:${messageId}`;
    }
    const artifactId =
        text(member.artifact_id) || text(member.member_id) || text(member.id) || text(member.document_id);
    if (artifactId) {
        return `artifact:${artifactId}`;
    }
    return `${text(member.file_name)}:${lower(member.output_format)}`;
}

/**
 * Put the run's primary analysis first.
 *
 * A combined run produces a Markdown summary and a structured export. The summary is what
 * the reply is about, so leading with whichever happened to be serialised first would bury
 * it under its own appendix.
 */
function sortRunMembers(members: GeneratedArtifact[], primaryArtifactId: string): GeneratedArtifact[] {
    const primaryIndex = members.findIndex((member) => {
        const role = lower(member.role) || lower(member.artifact_role);
        if (role === 'primary_analysis') {
            return true;
        }
        const id = text(member.artifact_id) || text(member.member_id) || text(member.id);
        return Boolean(primaryArtifactId && id === primaryArtifactId && isMarkdownArtifact(member));
    });

    if (primaryIndex <= 0) {
        return members;
    }

    const sorted = members.slice();
    sorted.unshift(sorted.splice(primaryIndex, 1)[0]);
    return sorted;
}
