// conversationGeneratedFiles.ts
// Every file a conversation produced, for the Generated section of the Documents drawer.
//
// A file reaches a thread as a card under the reply that produced it: a file an orchestration
// plan rendered (CSV, Excel, Word, PDF, PowerPoint, Markdown, text, JSON, XML or YAML), or an
// export, Analyze summary, comparison workbook or research ledger a turn wrote. The reply's
// metadata is the only place the interface learns that such a file exists, so without this list
// the drawer that gathers what a conversation used and made would report "No documents" under a
// reply that plainly made one.
//
// The thread's own readers are reused, so the drawer lists exactly what the thread shows: the
// same artifact normaliser, the same committed-output check, the same masking, saved-analysis and
// workflow-reply rules, and the live orchestration state the file cards poll.
//
// Documents an agent created with the SimpleChat upload actions are listed by the server instead
// (generatedDocuments.ts), because the server reads their ids from the tool results it stored.
// `mergeGeneratedEntries` puts both kinds in conversation order.
//
// Everything in this module is pure, so it can be tested without a DOM.

import type { GeneratedDocument } from './collaboration';
import { formatFileSize } from './documentExplorer';
import {
    artifactDownloadPath,
    artifactTitle,
    readArtifactApproval,
    readGeneratedArtifacts,
    type GeneratedArtifact,
} from './generatedArtifacts';
import { readMaskState } from './masking';
import { normalizeOrchestrationAttempt } from './orchestration';
import {
    committedOrchestrationArtifact,
    isOrchestrationOutputArtifact,
    orchestrationOutputTypeLabel,
    type OrchestrationOutput,
} from './orchestrationOutputs';
import { readSavedAnalysis } from './savedAnalysis';
import { isSupersededByWorkflowReply } from './sharedMessage';
import type { ChatMessage, ConversationMetadata } from './types';

/**
 * Where a generated file stands, as far as the reader can act on it.
 *
 * Only `ready` can be downloaded. The rest are listed anyway, so a file that is still being
 * written, failed, or waits for an owner's approval is not mistaken for one that was never made.
 */
export type GeneratedFileStatus =
    | 'ready'
    | 'pending'
    | 'failed'
    | 'cancelled'
    | 'withheld'
    | 'unavailable';

export interface ConversationGeneratedFile {
    /** Unique per file, so one advertised under several replies, such as a reused retry output, is listed once. */
    key: string;
    fileName: string;
    /** Lower-case format such as `csv` or `pptx`, or '' when neither the record nor the name says. */
    format: string;
    /** What a person calls the file, such as "CSV file" or "Word document". */
    typeLabel: string;
    /** The reply whose card shows the file, for Show in conversation. */
    messageId: string;
    status: GeneratedFileStatus;
    /** Short status text for the drawer; empty when the file is ready. */
    statusLabel: string;
    rowCount: number | null;
    sizeBytes: number | null;
    /** The workspace document the file was saved as, when it was saved to one. */
    documentId: string;
    /** What Download and Preview read. Set only while the file is ready. */
    artifact: GeneratedArtifact | null;
}

/** What the drawer reads of a plan run's live record: the fields the thread's file cards read. */
export interface GeneratedFileRunState {
    outputs?: readonly OrchestrationOutput[];
    generated_artifacts?: readonly GeneratedArtifact[];
    outputAccessDenied?: boolean;
}

/**
 * A background export's progress as the card that polls it last saw it.
 *
 * The card keeps a finished run's files in its own state, so this is how the drawer learns the
 * run finished without the conversation being read again.
 */
export interface GeneratedExportRunState {
    status?: string;
    retryableFailure?: boolean;
    members?: readonly GeneratedArtifact[];
}

export interface GeneratedFileSources {
    /** Live plan runs by run id, as the orchestration store holds them. */
    runs?: Readonly<Record<string, GeneratedFileRunState | undefined>>;
    /** Background exports by run id, as their cards last reported them. */
    exportRuns?: Readonly<Record<string, GeneratedExportRunState | undefined>>;
}

/** One row of the Generated section: a file a reply produced, or a document an agent created. */
export type GeneratedEntry =
    | { kind: 'file'; key: string; messageId: string; file: ConversationGeneratedFile }
    | { kind: 'document'; key: string; messageId: string; document: GeneratedDocument };

/** The same words the plan's own file cards use, so the drawer and the thread agree. */
const OUTPUT_STATE_LABELS = {
    waiting: 'Waiting',
    rendering: 'Rendering',
    retry_scheduled: 'Automatic retry scheduled',
    failed: 'Failed',
    cancelled: 'Cancelled',
} as const;

/** Spellings a format arrives under, mapped to the one the type labels know. */
const FORMAT_ALIASES: Readonly<Record<string, string>> = {
    markdown: 'md',
    text: 'txt',
    yml: 'yaml',
};

/** The SimpleChat actions that create a workspace document. Mirrors GENERATED_DOCUMENT_FUNCTIONS on the server. */
const GENERATED_DOCUMENT_FUNCTIONS = new Set([
    'upload_markdown_document',
    'upload_word_document',
    'upload_powerpoint_document',
]);

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function count(value: unknown): number | null {
    const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
    return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null;
}

/** The file's format: the one its record declares, otherwise its extension. */
function fileFormat(declared: unknown, fileName: string): string {
    const format = text(declared).replace(/^\./, '').toLowerCase();
    const resolved = format || (/\.([a-z0-9]{1,8})$/i.exec(fileName)?.[1] ?? '').toLowerCase();
    return FORMAT_ALIASES[resolved] ?? resolved;
}

function artifactKey(artifact: GeneratedArtifact, fileName: string, format: string): string {
    if (artifact.artifact_message_id) {
        return `artifact:${artifact.artifact_message_id}`;
    }
    if (artifact.document_id) {
        return `document:${artifact.document_id}`;
    }
    if (artifact.export_run_id) {
        return `run:${artifact.export_run_id}`;
    }
    return `file:${fileName}:${format}`;
}

/** A file a plan was asked to produce, described exactly as its card in the thread describes it. */
function outputFile(
    output: OrchestrationOutput,
    committed: readonly GeneratedArtifact[],
    message: ChatMessage,
    runId: string,
    index: number,
    accessDenied: boolean,
): ConversationGeneratedFile {
    const unavailable = output.available === false || accessDenied;
    const artifact = unavailable
        ? undefined
        : committedOrchestrationArtifact(output, committed, text(message.conversation_id));
    const completed = output.state === 'completed' && !unavailable;
    const fileName = output.file_name || 'Unnamed file';
    const format = fileFormat(output.output_format, fileName);

    let status: GeneratedFileStatus;
    let statusLabel: string;
    if (accessDenied || (output.available === false && output.state !== 'cancelled')) {
        status = 'unavailable';
        statusLabel = 'Unavailable';
    } else if (output.state === 'completed') {
        // A completed status is not a download descriptor: without the committed record there is
        // nothing to fetch, which the thread's card also says rather than offering a dead button.
        status = artifact ? 'ready' : 'unavailable';
        statusLabel = artifact ? '' : 'Download details unavailable';
    } else if (output.state === 'waiting' || output.state === 'rendering' || output.state === 'retry_scheduled') {
        status = 'pending';
        statusLabel = OUTPUT_STATE_LABELS[output.state];
    } else if (output.state === 'failed' || output.state === 'cancelled') {
        status = output.state;
        statusLabel = OUTPUT_STATE_LABELS[output.state];
    } else {
        status = 'unavailable';
        statusLabel = 'Status unavailable';
    }

    return {
        key: artifact
            ? `artifact:${artifact.artifact_message_id}`
            : `output:${runId}:${output.output_id || `#${index}`}`,
        fileName,
        format,
        typeLabel: orchestrationOutputTypeLabel(format),
        messageId: message.id,
        status,
        statusLabel,
        rowCount: completed ? output.row_count : null,
        sizeBytes: completed ? output.size_bytes : null,
        documentId: '',
        artifact: artifact ?? null,
    };
}

/** An export, analysis or research file advertised on a reply. */
function artifactFile(
    artifact: GeneratedArtifact,
    message: ChatMessage,
    exportRuns: Readonly<Record<string, GeneratedExportRunState | undefined>>,
): ConversationGeneratedFile {
    const namedFile = text(artifact.file_name);
    // A background export that has not finished may not know its file name yet.
    const fileName = namedFile || artifactTitle(artifact);
    const format = fileFormat(artifact.output_format, namedFile);
    const approval = readArtifactApproval(artifact);

    let status: GeneratedFileStatus;
    let statusLabel: string;
    if (artifact.background_export) {
        const run = exportRuns[artifact.export_run_id];
        const runStatus = text(run?.status ?? artifact.status).toLowerCase();
        const retryable = run?.retryableFailure ?? Boolean(artifact.retryable_failure);
        if (runStatus === 'failed' && !retryable) {
            status = 'failed';
            statusLabel = 'Failed';
        } else if (runStatus === 'canceled' || runStatus === 'cancelled') {
            status = 'cancelled';
            statusLabel = 'Cancelled';
        } else {
            status = 'pending';
            statusLabel = 'Generating';
        }
    } else if (approval?.isPending) {
        status = 'withheld';
        statusLabel = 'Awaiting approval';
    } else if (approval?.isAutoDenied) {
        status = 'withheld';
        statusLabel = 'Expired';
    } else if (approval?.isDenied) {
        status = 'withheld';
        statusLabel = 'Declined';
    } else if (!artifactDownloadPath(artifact, text(message.conversation_id))) {
        status = 'unavailable';
        statusLabel = 'Unavailable';
    } else {
        status = 'ready';
        statusLabel = '';
    }

    const running = artifact.background_export;
    return {
        key: artifactKey(artifact, fileName, format),
        fileName,
        format,
        typeLabel: orchestrationOutputTypeLabel(format),
        messageId: message.id,
        status,
        statusLabel,
        rowCount: running ? null : count(artifact.row_count),
        sizeBytes: running ? null : count(artifact.size_bytes),
        documentId: text(artifact.document_id),
        artifact: status === 'ready' ? artifact : null,
    };
}

/**
 * The files one message shows a card for, in the order the thread draws them: the plan's files
 * first, then the reply's other generated files.
 */
export function messageGeneratedFiles(
    message: ChatMessage,
    sources: GeneratedFileSources = {},
): ConversationGeneratedFile[] {
    if (!message?.id || message.role !== 'assistant' || isSupersededByWorkflowReply(message)) {
        return [];
    }
    const masks = readMaskState(message);
    if (masks.fullyMasked) {
        return [];
    }

    const metadata: Record<string, unknown> = isRecord(message.metadata) ? message.metadata : {};
    const runs = sources.runs ?? {};
    const exportRuns = sources.exportRuns ?? {};
    const artifacts = readGeneratedArtifacts({ ...message, ...metadata });
    const orchestration = normalizeOrchestrationAttempt(metadata.orchestration);
    const runId = orchestration.run_id ?? '';
    const live = runId ? runs[runId] : undefined;
    // When the plan's file cards own its files, its committed records are not listed twice.
    const managedOutputs = orchestration.outputs !== undefined || live?.outputs !== undefined;
    const files: ConversationGeneratedFile[] = [];

    // The thread hides a plan's file cards while any part of the reply is masked.
    if (runId && masks.ranges.length === 0) {
        const outputs = live?.outputs ?? orchestration.outputs ?? [];
        const committed = live?.generated_artifacts ?? orchestration.generated_artifacts ?? artifacts;
        outputs.forEach((output, index) => {
            files.push(outputFile(output, committed, message, runId, index, Boolean(live?.outputAccessDenied)));
        });
    }

    // A reply with saved Analyze findings shows its downloads only while those findings are.
    if (metadata.saved_analysis != null) {
        const saved = readSavedAnalysis(metadata);
        if (!saved || saved.available === false || saved.conversation_id !== text(message.conversation_id)
            || masks.ranges.length > 0) {
            return files;
        }
    }

    for (const artifact of artifacts) {
        if (managedOutputs && isOrchestrationOutputArtifact(artifact)) {
            continue;
        }
        // A finished background export is replaced by the files it produced, as its card is.
        const members = artifact.background_export ? exportRuns[artifact.export_run_id]?.members : undefined;
        for (const entry of members?.length ? members : [artifact]) {
            files.push(artifactFile(entry, message, exportRuns));
        }
    }
    return files;
}

/** Every file the conversation produced, oldest first, each file once. */
export function collectConversationGeneratedFiles(
    messages: readonly ChatMessage[],
    sources: GeneratedFileSources = {},
): ConversationGeneratedFile[] {
    const seen = new Set<string>();
    const files: ConversationGeneratedFile[] = [];
    for (const message of messages) {
        for (const file of messageGeneratedFiles(message, sources)) {
            if (!seen.has(file.key)) {
                seen.add(file.key);
                files.push(file);
            }
        }
    }
    return files;
}

/** "CSV file · 50 rows · 1006 B", as the file's card in the thread describes it. */
export function generatedFileDetails(file: ConversationGeneratedFile): string {
    return [
        file.typeLabel,
        file.rowCount !== null ? `${file.rowCount.toLocaleString()} ${file.rowCount === 1 ? 'row' : 'rows'}` : '',
        // An empty file is still a finished file; the shared formatter reserves its dash for unknown sizes.
        file.sizeBytes !== null ? (file.sizeBytes === 0 ? '0 B' : formatFileSize(file.sizeBytes)) : '',
    ].filter(Boolean).join(' · ');
}

function isGeneratedDocumentCitation(citation: unknown): boolean {
    return isRecord(citation) && GENERATED_DOCUMENT_FUNCTIONS.has(text(citation.function_name));
}

/**
 * Whether the conversation may hold documents an agent created with the SimpleChat upload actions.
 *
 * Decides whether the server is asked for them at all. A reply whose tool calls have been read
 * answers exactly. A reply that finished in this tab carries no tool calls until the
 * conversation is read again, and only an agent can run those actions, so an agent's reply in
 * that state counts as a maybe.
 */
export function mayHaveGeneratedDocuments(messages: readonly ChatMessage[]): boolean {
    return messages.some((message) => {
        if (message?.role !== 'assistant') {
            return false;
        }
        if (Array.isArray(message.agent_citations)) {
            return message.agent_citations.some(isGeneratedDocumentCitation);
        }
        return Boolean(text(message.agent_display_name));
    });
}

/**
 * What the server's list of agent documents depends on in the thread, as one comparable key.
 *
 * The server reads the replies the thread shows and skips a fully masked one, so the list is
 * read again whenever those change: a reply arrives or is deleted, another attempt of an answer
 * is shown, or a reply is masked or unmasked. Counting replies is not enough, because showing
 * another attempt or masking a reply leaves the count unchanged. A person's own message cannot
 * hold such a document, so sending one does not cost a request.
 */
export function generatedDocumentsThreadKey(messages: readonly ChatMessage[]): string {
    return JSON.stringify(
        messages
            .filter((message) => message?.id && message.role !== 'user')
            .map((message) => [message.id, readMaskState(message).fullyMasked]),
    );
}

/**
 * The agent documents whose reply the thread shows.
 *
 * The server's list describes the thread as it was read, so it can briefly describe a thread the
 * reader is no longer looking at, such as another attempt of an answer or a reply just masked.
 * A document is kept only while its reply is shown and not fully masked, which is also what
 * Show in conversation needs to scroll to.
 */
export function visibleGeneratedDocuments(
    documents: readonly GeneratedDocument[],
    messages: readonly ChatMessage[],
): GeneratedDocument[] {
    const shown = new Set(
        messages
            .filter((message) => message?.id && !isSupersededByWorkflowReply(message)
                && !readMaskState(message).fullyMasked)
            .map((message) => message.id),
    );
    return documents.filter((document) => shown.has(text(document?.message_id)));
}

/**
 * Files the replies produced and documents agents created, as one list in conversation order.
 *
 * A file saved to a workspace and a document an agent created are the same thing when their
 * document ids agree, so it is listed once. Documents are expected to have been narrowed to the
 * replies the thread shows (`visibleGeneratedDocuments`).
 */
export function mergeGeneratedEntries(
    files: readonly ConversationGeneratedFile[],
    documents: readonly GeneratedDocument[],
    messages: readonly ChatMessage[],
): GeneratedEntry[] {
    const position = new Map<string, number>();
    messages.forEach((message, index) => {
        if (message?.id && !position.has(message.id)) {
            position.set(message.id, index);
        }
    });

    const seen = new Set<string>();
    const entries: GeneratedEntry[] = [];
    for (const file of files) {
        const identity = file.documentId ? `document:${file.documentId}` : file.key;
        if (!seen.has(identity)) {
            seen.add(identity);
            entries.push({ kind: 'file', key: file.key, messageId: file.messageId, file });
        }
    }
    for (const document of documents) {
        const documentId = text(document?.document_id);
        const identity = `document:${documentId}`;
        if (documentId && !seen.has(identity)) {
            seen.add(identity);
            entries.push({ kind: 'document', key: identity, messageId: text(document.message_id), document });
        }
    }

    // A message the thread no longer holds sorts last rather than disappearing.
    const order = (entry: GeneratedEntry) => position.get(entry.messageId) ?? Number.MAX_SAFE_INTEGER;
    return entries
        .map((entry, index) => ({ entry, index }))
        .sort((left, right) => order(left.entry) - order(right.entry) || left.index - right.index)
        .map(({ entry }) => entry);
}

/**
 * How many documents the Documents button counts: the ones answers used and the ones the
 * conversation produced, each once. Media is not counted; it has its own section.
 */
export function countConversationDocuments(
    metadata: Pick<ConversationMetadata, 'used_documents' | 'legacy_used_documents' | 'linked_workspace_documents'>
        | null
        | undefined,
    files: readonly ConversationGeneratedFile[],
    documents: readonly GeneratedDocument[],
): number {
    const keys = new Set<string>();
    for (const list of [
        metadata?.used_documents,
        metadata?.legacy_used_documents,
        metadata?.linked_workspace_documents,
    ]) {
        for (const document of list ?? []) {
            const documentId = String(document?.document_id ?? '').trim();
            if (documentId) {
                keys.add(`document:${documentId}`);
            }
        }
    }
    for (const file of files) {
        keys.add(file.documentId ? `document:${file.documentId}` : file.key);
    }
    for (const document of documents) {
        const documentId = text(document?.document_id);
        if (documentId) {
            keys.add(`document:${documentId}`);
        }
    }
    return keys.size;
}
