// ChatUploadExtraction.tsx
// What ingestion extracted from a file uploaded into a conversation.
//
// A chat upload is stored as a workspace document, so the useful answer to "what is in this
// file" is what ingestion produced for it: the text that search and chat actually read and,
// for an image, the analysis the vision model wrote. It is the same material a cited passage
// comes from, so the upload's preview and its Sources panel both show it the same way.

import { useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { Eye, Loader2, ScanText, TriangleAlert } from 'lucide-react';
import {
    fetchChatFileContent,
    type ChatFileContent,
    type WorkspaceUploadVisionAnalysis,
} from '../../lib/endpoints';

const ENGINE_LABELS: Record<string, string> = {
    content_understanding: 'Azure AI Content Understanding',
    document_intelligence: 'Azure AI Document Intelligence',
};

/** A readable name for a stored extraction engine id, or '' when none was recorded. */
export function describeExtractionEngine(engine?: string): string {
    const normalized = String(engine ?? '').trim().toLowerCase();
    if (!normalized) {
        return '';
    }
    return ENGINE_LABELS[normalized] ?? normalized.replace(/_/g, ' ');
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
    return (
        <div>
            <h4 className="mb-1 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                {label}
            </h4>
            {children}
        </div>
    );
}

function VisionAnalysisBlock({ analysis }: { analysis: WorkspaceUploadVisionAnalysis }) {
    const objects = (analysis.objects ?? []).filter((item) => String(item).trim());

    return (
        <section
            aria-label="AI vision analysis"
            className="space-y-3 rounded-xl border border-edge bg-surface-sunken p-3"
        >
            <p className="flex items-center gap-1.5 text-xs font-semibold text-text-1">
                <Eye size={13} className="shrink-0 text-text-3" />
                AI vision analysis
                {analysis.model ? (
                    <span className="font-normal text-text-3">· {analysis.model}</span>
                ) : null}
            </p>
            {analysis.description ? (
                <Field label="Description">
                    <p className="text-sm leading-relaxed whitespace-pre-wrap text-text-1">
                        {analysis.description}
                    </p>
                </Field>
            ) : null}
            {objects.length > 0 ? (
                <Field label="Objects detected">
                    <ul className="flex flex-wrap gap-1">
                        {objects.map((item, index) => (
                            <li
                                key={`${item}-${index}`}
                                className="rounded-full border border-edge bg-surface-2 px-2 py-0.5 text-[11px] text-text-2"
                            >
                                {item}
                            </li>
                        ))}
                    </ul>
                </Field>
            ) : null}
            {analysis.text ? (
                <Field label="Text visible in the image">
                    <p className="text-sm whitespace-pre-wrap text-text-1">{analysis.text}</p>
                </Field>
            ) : null}
            {analysis.analysis ? (
                <Field label="Contextual analysis">
                    <p className="text-sm leading-relaxed whitespace-pre-wrap text-text-1">
                        {analysis.analysis}
                    </p>
                </Field>
            ) : null}
        </section>
    );
}

/**
 * The extraction results for one upload.
 *
 * Content that did not come from a workspace document -- an older upload whose text lives on
 * the message -- has no extraction details, so it is shown as the plain text it always was.
 */
export function ChatUploadExtraction({ data }: { data: ChatFileContent }) {
    const text = String(data.file_content ?? '');
    const details = data.workspace_document;

    if (!details) {
        return <pre className="text-xs break-words whitespace-pre-wrap text-text-2">{text}</pre>;
    }

    const engine = describeExtractionEngine(details.extraction_engine);
    const vision = details.vision_analysis ?? null;
    const keywords = (details.keywords ?? []).filter((item) => String(item).trim());
    const indexed = data.indexed_text_available === true;

    return (
        <div className="space-y-4">
            {engine || details.extraction_engine_reason ? (
                <p className="flex items-start gap-1.5 text-xs text-text-3">
                    <ScanText size={13} className="mt-0.5 shrink-0" />
                    <span>
                        {engine ? (
                            <>
                                Extracted with <span className="text-text-2">{engine}</span>
                                {details.extraction_engine_reason ? '. ' : ''}
                            </>
                        ) : null}
                        {details.extraction_engine_reason}
                    </span>
                </p>
            ) : null}

            {details.title || details.abstract || keywords.length > 0 ? (
                <div className="space-y-3">
                    {details.title ? (
                        <Field label="Title">
                            <p className="text-sm text-text-1">{details.title}</p>
                        </Field>
                    ) : null}
                    {details.abstract ? (
                        <Field label="Summary">
                            <p className="text-sm leading-relaxed whitespace-pre-wrap text-text-1">
                                {details.abstract}
                            </p>
                        </Field>
                    ) : null}
                    {keywords.length > 0 ? (
                        <Field label="Keywords">
                            <p className="text-sm text-text-2">{keywords.join(', ')}</p>
                        </Field>
                    ) : null}
                </div>
            ) : null}

            {vision ? <VisionAnalysisBlock analysis={vision} /> : null}

            {indexed ? (
                // Collapsed when the vision analysis already says the same thing in a readable
                // form; open when it is the only account of what the file contains.
                <details open={!vision} className="group">
                    <summary className="cursor-pointer text-xs font-medium text-text-3 hover:text-text-1">
                        Indexed text
                        <span className="ml-1 font-normal">
                            (what search and chat read
                            {details.indexed_chunk_count
                                ? `, ${details.indexed_chunk_count} chunk${details.indexed_chunk_count === 1 ? '' : 's'}`
                                : ''}
                            )
                        </span>
                    </summary>
                    <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-surface-sunken p-3 text-xs break-words whitespace-pre-wrap text-text-2">
                        {text}
                    </pre>
                </details>
            ) : (
                <p className="flex items-start gap-1.5 text-xs text-warn">
                    <TriangleAlert size={13} className="mt-0.5 shrink-0" />
                    {typeof details.percentage_complete === 'number' &&
                    details.percentage_complete < 100
                        ? 'Still processing. The indexed text appears here once ingestion finishes.'
                        : 'Nothing from this file was indexed for search, so chat cannot cite it. Reprocess or re-upload the file to index it.'}
                </p>
            )}
        </div>
    );
}

/**
 * Loads and shows the extraction results for one upload.
 *
 * Kept separate from the modal preview so the message inspector can show the same content
 * inline, without a second copy of the loading and failure handling.
 */
export function ChatUploadExtractionLoader({
    conversationId,
    fileId,
    className,
}: {
    conversationId: string;
    fileId: string;
    className?: string;
}) {
    const [data, setData] = useState<ChatFileContent | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        setData(null);
        setError(null);

        fetchChatFileContent(conversationId, fileId)
            .then((result) => {
                if (cancelled) {
                    return;
                }
                if (result.error) {
                    setError(result.error);
                    return;
                }
                setData(result);
            })
            .catch((cause: unknown) => {
                if (!cancelled) {
                    setError(
                        cause instanceof Error ? cause.message : 'Could not load the file.',
                    );
                }
            });

        return () => {
            cancelled = true;
        };
    }, [conversationId, fileId]);

    return (
        <div className={clsx(className)}>
            {error ? (
                <p className="flex items-start gap-2 text-sm text-warn">
                    <TriangleAlert size={14} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            ) : !data ? (
                <p className="flex items-center gap-2 text-sm text-text-3">
                    <Loader2 size={14} className="animate-spin" />
                    Loading what was extracted…
                </p>
            ) : (
                <ChatUploadExtraction data={data} />
            )}
        </div>
    );
}
