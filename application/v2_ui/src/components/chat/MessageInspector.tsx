// MessageInspector.tsx
// The expandable panel below a message showing its details, sources and reasoning.
//
// One panel with three sections rather than three separate panels: a user comparing what a
// response cited against how it was generated should not have to close one to open another.

import { useEffect, useState } from 'react';
import { clsx } from 'clsx';
import {
    Braces,
    ExternalLink,
    FileText,
    Globe,
    Loader2,
    Tags,
    TriangleAlert,
    X,
} from 'lucide-react';
import { fetchMessageMetadata, fetchMessageThoughts } from '../../lib/endpoints';
import {
    buildDetailGroups,
    describeDocumentCitation,
    readSources,
    renderToolValue,
    type DetailGroup,
    type MessageSources,
} from '../../lib/messageDetails';
import type { ChatMessage, Json, PersistedThought } from '../../lib/types';
import { buildToolResultView, type RowMode } from '../../lib/agentCitationRows';
import { GlassButton } from '../ui/primitives';
import { normalizePersistedThought, ThoughtsList } from './ThoughtsList';

export type InspectorSection = 'details' | 'sources' | 'reasoning';

const SECTION_LABEL: Record<InspectorSection, string> = {
    details: 'Details',
    sources: 'Sources',
    reasoning: 'Reasoning',
};

function Empty({ children }: { children: React.ReactNode }) {
    return <p className="px-1 py-3 text-sm text-text-3">{children}</p>;
}

function Loading({ label }: { label: string }) {
    return (
        <p className="flex items-center gap-2 px-1 py-3 text-sm text-text-3">
            <Loader2 size={14} className="animate-spin" />
            {label}
        </p>
    );
}

function Failed({ message }: { message: string }) {
    return (
        <p className="flex items-start gap-2 px-1 py-3 text-sm text-warn">
            <TriangleAlert size={14} className="mt-0.5 shrink-0" />
            {message}
        </p>
    );
}

function DetailsSection({ message }: { message: ChatMessage }) {
    const [groups, setGroups] = useState<DetailGroup[] | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        setGroups(null);
        setError(null);

        void (async () => {
            try {
                const payload = await fetchMessageMetadata(message.id, controller.signal);
                if (!controller.signal.aborted) {
                    setGroups(buildDetailGroups(payload as Json));
                }
            } catch (failure) {
                if (!controller.signal.aborted) {
                    setError(
                        failure instanceof Error
                            ? failure.message
                            : 'Message details could not be loaded.',
                    );
                }
            }
        })();

        return () => controller.abort();
    }, [message.id]);

    if (error) {
        return <Failed message={error} />;
    }
    if (!groups) {
        return <Loading label="Loading message details…" />;
    }
    if (groups.length === 0) {
        return <Empty>No diagnostics were recorded for this message.</Empty>;
    }

    return (
        <div className="grid gap-4 sm:grid-cols-2">
            {groups.map((group) => (
                <div key={group.title}>
                    <h4 className="mb-1.5 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                        {group.title}
                    </h4>
                    <dl className="space-y-1">
                        {group.rows.map((row) => (
                            <div key={row.label} className="flex gap-2 text-xs">
                                <dt className="w-40 shrink-0 text-text-3">{row.label}</dt>
                                <dd
                                    className={clsx(
                                        'min-w-0 flex-1 break-words text-text-1',
                                        row.mono && 'font-mono text-[11px]',
                                    )}
                                >
                                    {row.value}
                                </dd>
                            </div>
                        ))}
                    </dl>
                </div>
            ))}
        </div>
    );
}

function SourcesSection({ sources }: { sources: MessageSources }) {
    if (sources.total === 0) {
        return <Empty>This response did not cite any sources.</Empty>;
    }

    return (
        <div className="space-y-4">
            {sources.documents.length > 0 && (
                <div>
                    <h4 className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                        <FileText size={12} /> Documents ({sources.documents.length})
                    </h4>
                    <ul className="space-y-1">
                        {sources.documents.map((citation, index) => {
                            const described = describeDocumentCitation(citation);
                            return (
                                <li
                                    key={`${citation.citation_id ?? index}`}
                                    className="flex items-start gap-2 rounded-lg bg-surface-sunken px-2.5 py-1.5 text-xs"
                                >
                                    {described.isSummary ? (
                                        <Tags size={13} className="mt-0.5 shrink-0 text-text-3" />
                                    ) : (
                                        <FileText
                                            size={13}
                                            className="mt-0.5 shrink-0 text-text-3"
                                        />
                                    )}
                                    <span className="min-w-0 flex-1">
                                        <span className="block truncate text-text-1">
                                            {described.title}
                                        </span>
                                        {(described.location || described.isSummary) && (
                                            <span className="text-text-3">
                                                {described.isSummary
                                                    ? 'Document summary'
                                                    : described.location}
                                            </span>
                                        )}
                                    </span>
                                </li>
                            );
                        })}
                    </ul>
                </div>
            )}

            {sources.web.length > 0 && (
                <div>
                    <h4 className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                        <Globe size={12} /> Web ({sources.web.length})
                    </h4>
                    <ul className="space-y-1">
                        {sources.web.map((citation, index) => {
                            const url = String(citation.url ?? '').trim();
                            // Only http(s) is linkable; anything else is shown as text so a
                            // javascript: or data: URL can never become a live link.
                            const safe = /^https?:\/\//i.test(url) ? url : '';
                            const label = String(citation.title ?? '').trim() || url;
                            return (
                                <li key={`${url}-${index}`} className="text-xs">
                                    {safe ? (
                                        <a
                                            href={safe}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="flex items-start gap-2 rounded-lg bg-surface-sunken px-2.5 py-1.5 text-accent hover:bg-surface-2"
                                        >
                                            <ExternalLink
                                                size={13}
                                                className="mt-0.5 shrink-0"
                                            />
                                            <span className="min-w-0 flex-1 break-all">
                                                {label}
                                            </span>
                                        </a>
                                    ) : (
                                        <span className="block rounded-lg bg-surface-sunken px-2.5 py-1.5 text-text-2">
                                            {label}
                                        </span>
                                    )}
                                </li>
                            );
                        })}
                    </ul>
                </div>
            )}

            {sources.tools.length > 0 && (
                <div>
                    <h4 className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-text-3 uppercase">
                        <Braces size={12} /> Tool calls ({sources.tools.length})
                    </h4>
                    <ul className="space-y-1">
                        {sources.tools.map((tool, index) => (
                            <li
                                key={`${tool.tool_name ?? 'tool'}-${index}`}
                                className="rounded-lg bg-surface-sunken px-2.5 py-1.5 text-xs"
                            >
                                <details>
                                    <summary className="cursor-pointer text-text-1">
                                        {String(tool.tool_name ?? `Tool ${index + 1}`)}
                                    </summary>
                                    <ToolCallBody tool={tool} />
                                </details>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
}

/**
 * One tool call's arguments and result.
 *
 * Split into its own component because the result needs state: a tabular result is shown a
 * few rows at a time and the reader chooses how many, which cannot live in a `.map()`.
 */
function ToolCallBody({ tool }: { tool: MessageSources['tools'][number] }) {
    const [rowMode, setRowMode] = useState<RowMode>('preview');
    const args = renderToolValue(tool.function_arguments);
    const view = buildToolResultView(tool.function_result, rowMode);

    return (
        <>
            {args && (
                <div className="mt-1.5">
                    <span className="text-text-3">Arguments</span>
                    <pre className="mt-0.5 max-h-40 overflow-auto rounded bg-surface-2 p-2 font-mono text-[11px] text-text-2">
                        {args}
                    </pre>
                </div>
            )}
            {view.resultText && (
                <div className="mt-1.5">
                    <span className="text-text-3">Result</span>
                    {view.summaryText && (
                        <p className="mt-0.5 text-[11px] text-text-3">{view.summaryText}</p>
                    )}
                    <pre className="mt-0.5 max-h-40 overflow-auto rounded bg-surface-2 p-2 font-mono text-[11px] text-text-2">
                        {view.resultText}
                    </pre>
                    {view.controls.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                            {view.controls.map((control) => (
                                <GlassButton
                                    key={control.mode}
                                    size="sm"
                                    variant="subtle"
                                    onClick={() => setRowMode(control.mode)}
                                >
                                    {control.label}
                                </GlassButton>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </>
    );
}

function ReasoningSection({ message }: { message: ChatMessage }) {
    const [thoughts, setThoughts] = useState<PersistedThought[] | null>(null);
    const [enabled, setEnabled] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        setThoughts(null);
        setError(null);

        void (async () => {
            try {
                const response = await fetchMessageThoughts(
                    message.conversation_id,
                    message.id,
                    controller.signal,
                );
                if (!controller.signal.aborted) {
                    setThoughts(response?.thoughts ?? []);
                    setEnabled(response?.enabled !== false);
                }
            } catch (failure) {
                if (!controller.signal.aborted) {
                    setError(
                        failure instanceof Error
                            ? failure.message
                            : 'Reasoning steps could not be loaded.',
                    );
                }
            }
        })();

        return () => controller.abort();
    }, [message.conversation_id, message.id]);

    if (error) {
        return <Failed message={error} />;
    }
    if (!thoughts) {
        return <Loading label="Loading reasoning…" />;
    }
    if (!enabled) {
        return <Empty>Reasoning capture is turned off for this deployment.</Empty>;
    }
    if (thoughts.length === 0) {
        return <Empty>No reasoning steps were recorded for this response.</Empty>;
    }

    // Drawn exactly as reasoning is drawn while it streams, so the same information does
    // not feel like a different feature after the fact.
    return <ThoughtsList thoughts={thoughts.map(normalizePersistedThought)} />;
}

export function MessageInspector({
    message,
    section,
    onSection,
    onClose,
}: {
    message: ChatMessage;
    section: InspectorSection;
    onSection: (next: InspectorSection) => void;
    onClose: () => void;
}) {
    const sources = readSources(message as unknown as Json);

    // Reasoning and sources only exist for a generated response.
    const available: InspectorSection[] =
        message.role === 'user'
            ? ['details']
            : ['details', 'sources', 'reasoning'];
    const active = available.includes(section) ? section : 'details';

    return (
        <div className="glass-flat mt-1.5 w-full max-w-[min(64rem,92%)] rounded-xl border border-edge">
            <div className="flex items-center gap-1 border-b border-edge px-2 py-1.5">
                {available.map((entry) => (
                    <button
                        key={entry}
                        type="button"
                        onClick={() => onSection(entry)}
                        aria-pressed={active === entry}
                        className={clsx(
                            'rounded-lg px-2.5 py-1 text-xs font-medium transition-colors',
                            active === entry
                                ? 'bg-accent-soft text-accent'
                                : 'text-text-3 hover:bg-surface-2 hover:text-text-1',
                        )}
                    >
                        {SECTION_LABEL[entry]}
                        {entry === 'sources' && sources.total > 0 && (
                            <span className="ml-1 opacity-70">{sources.total}</span>
                        )}
                    </button>
                ))}
                <button
                    type="button"
                    onClick={onClose}
                    aria-label="Close message details"
                    className="ml-auto rounded-lg p-1 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    <X size={14} />
                </button>
            </div>

            <div className="max-h-96 overflow-y-auto px-3 py-2">
                {active === 'details' && <DetailsSection message={message} />}
                {active === 'sources' && <SourcesSection sources={sources} />}
                {active === 'reasoning' && <ReasoningSection message={message} />}
            </div>
        </div>
    );
}
