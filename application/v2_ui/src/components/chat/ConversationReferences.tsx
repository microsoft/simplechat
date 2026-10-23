// ConversationReferences.tsx

import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { MessageSquare, X } from 'lucide-react';
import { chatHrefForConversation } from '../../lib/conversationUrl';
import { resolveConversationReferences, searchConversationReferences, type ConversationSource } from '../../lib/conversationReferences';

export function useConversationSuggestions(query: string | null, excludeId?: string | null) {
    const [sources, setSources] = useState<ConversationSource[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [partial, setPartial] = useState(false);
    const [hasMore, setHasMore] = useState(false);
    const [offset, setOffset] = useState(0);
    const [content, setContent] = useState(false);
    const [retry, setRetry] = useState(0);
    const nextOffset = useRef(0);
    useEffect(() => { setOffset(0); setContent(false); setSources([]); }, [query, excludeId]);
    useEffect(() => {
        let current = true;
        setError('');
        if (query === null) { setSources([]); setLoading(false); return; }
        setLoading(true);
        const timer = window.setTimeout(() => {
            searchConversationReferences(query, excludeId, offset, content).then((result) => {
                if (!current) return;
                setSources((previous) => offset ? [...previous, ...result.conversations.filter((source) =>
                    !previous.some((item) => item.id === source.id))] : result.conversations);
                setPartial(result.partial);
                setHasMore(result.has_more);
                nextOffset.current = result.next_offset;
            }).catch((reason) => { if (current) setError(reason instanceof Error ? reason.message : 'Could not load conversations. Try again.'); })
                .finally(() => { if (current) setLoading(false); });
        }, 180);
        return () => { current = false; window.clearTimeout(timer); };
    }, [query, excludeId, offset, content, retry]);
    return { sources, loading, error, partial, hasMore, content,
        retry: () => setRetry((value) => value + 1),
        more: () => setOffset(nextOffset.current),
        searchContent: () => { setOffset(0); setContent(true); },
    };
}

export function ConversationSuggestionList({ suggestions, onSelect, activeIndex = 0 }: {
    suggestions: ReturnType<typeof useConversationSuggestions>;
    onSelect: (source: ConversationSource) => void;
    activeIndex?: number;
}) {
    return <div data-conversation-picker className="max-h-64 overflow-auto p-2">
        <p className="px-2 py-1 text-xs text-text-3">Your private conversations</p>
        <div role="listbox" aria-label="Conversation sources">
            {suggestions.sources.map((source, index) => <button type="button" role="option" aria-selected={index === activeIndex}
                key={source.id} onMouseDown={(event) => event.preventDefault()} onClick={() => onSelect(source)}
                className={`flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left text-sm hover:bg-surface-2 ${index === activeIndex ? 'bg-surface-2' : ''}`}>
                <MessageSquare size={15} className="mt-0.5 shrink-0 text-accent" />
                <span className="min-w-0"><span className="block truncate text-text-1">{source.title || 'Untitled conversation'}</span>
                    <span className="block text-xs text-text-3">{source.last_updated && !Number.isNaN(Date.parse(source.last_updated))
                        ? new Date(source.last_updated).toLocaleDateString() : 'Conversation'} · {source.id.slice(-8)}</span></span>
            </button>)}
        </div>
        {suggestions.loading && <p role="status" className="p-2 text-sm text-text-3">Finding conversations…</p>}
        {suggestions.error && <p role="alert" className="p-2 text-sm text-danger">{suggestions.error} <button type="button" onClick={suggestions.retry} className="underline">Retry</button></p>}
        {!suggestions.loading && !suggestions.error && !suggestions.sources.length && <p className="p-2 text-sm text-text-3">No matching private conversations.</p>}
        {suggestions.partial && <p className="px-2 text-xs text-text-3">Partial results: only a bounded portion of history was searched.</p>}
        <div className="flex flex-wrap gap-3 px-2 py-1 text-xs text-accent">
            {!suggestions.content && <button type="button" onClick={suggestions.searchContent}>Search message content</button>}
            {suggestions.hasMore && <button type="button" disabled={suggestions.loading} onClick={suggestions.more}>Load more</button>}
        </div>
    </div>;
}

export function ConversationSourcePicker({ onSelect, excludeId, disabled = false }: {
    onSelect: (source: ConversationSource) => void; excludeId?: string | null; disabled?: boolean;
}) {
    const [query, setQuery] = useState('');
    const suggestions = useConversationSuggestions(disabled ? null : query, excludeId);
    return <div className="rounded-xl border border-edge bg-surface-1">
        <label className="block px-3 pt-2 text-xs text-text-2">Find a private conversation
            <input value={query} disabled={disabled} onChange={(event) => setQuery(event.target.value)}
                type="search" className="mt-1 w-full rounded-lg border border-edge bg-surface-1 px-2 py-2 text-sm text-text-1" />
        </label>
        <ConversationSuggestionList suggestions={suggestions} onSelect={onSelect} />
    </div>;
}

export function ConversationReferenceChips({ references, onRemove, disabled = false, preview = true }: {
    references: readonly ConversationSource[]; onRemove?: (source: ConversationSource) => void; disabled?: boolean; preview?: boolean;
}) {
    const [selected, setSelected] = useState<string | null>(null);
    const [excerpt, setExcerpt] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const request = useRef(0);
    useEffect(() => () => { request.current += 1; }, []);
    if (!references.length) return null;
    const show = async (source: ConversationSource) => {
        const sequence = ++request.current;
        setSelected(source.id); setLoading(true); setError(''); setExcerpt('');
        try {
            const result = await resolveConversationReferences([source]);
            if (sequence !== request.current) return;
            setExcerpt(result.excerpts.map((item) => `${item.role}: ${item.content}`).join('\n\n')
                || 'No visible source messages are available.');
        } catch (reason) { if (sequence === request.current) setError(reason instanceof Error ? reason.message : 'Source unavailable.'); }
        finally { if (sequence === request.current) setLoading(false); }
    };
    return <div className="mb-2 space-y-2" data-conversation-references>
        <ul aria-label="Referenced conversations" className="flex flex-wrap gap-1.5">
            {references.map((source) => <li key={source.id} className="inline-flex max-w-full items-center gap-1 rounded-lg border border-edge bg-surface-1 px-2 py-1 text-xs text-text-1">
                <MessageSquare size={12} className="shrink-0 text-accent" />
                <Link to={chatHrefForConversation(source.id)} target="_blank" rel="noopener noreferrer" title="Open source in a new tab; your draft stays here"
                    className="max-w-56 truncate underline decoration-edge underline-offset-2">{source.title || 'Conversation source'}</Link>
                {preview && <button type="button" onClick={() => void show(source)} aria-label={`Preview ${source.title}`} className="rounded px-1 text-text-2 hover:bg-surface-2">Preview</button>}
                {onRemove && <button type="button" disabled={disabled} onClick={() => onRemove(source)} aria-label={`Remove conversation ${source.title}`}
                    className="rounded p-1 hover:bg-surface-2 disabled:opacity-40"><X size={12} /></button>}
            </li>)}
        </ul>
        {selected && <div className="rounded-lg border border-edge p-3 text-sm text-text-2">
            <div className="flex justify-between gap-2"><span>Source preview</span><button type="button" onClick={() => { request.current += 1; setSelected(null); }} aria-label="Close source preview"><X size={14} /></button></div>
            {loading ? <p role="status">Loading visible excerpts…</p> : error ? <p role="alert" className="text-danger">{error}</p>
                : <p className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words">{excerpt}</p>}
        </div>}
    </div>;
}
