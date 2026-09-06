// AgentKnowledgeFields.tsx

import { useState, type Dispatch, type SetStateAction } from 'react';
import { Plus, RefreshCw, Trash2 } from 'lucide-react';
import type { AgentConfiguration } from '../../lib/workspaceAuthoring';
import { AGENT_INPUT_CLASS } from '../../lib/workspaceAgentAuthoring';
import {
    KNOWLEDGE_LIMITS, USER_KNOWLEDGE_ACTIONS, knowledgeSourceKey, normalizeAgentKnowledgeUrl,
    readAgentKnowledge, resolvedAgentDocuments, selectedKnowledgeSources, toggleAgentKnowledgeSource,
    toggleString, updateAgentKnowledge, type AgentKnowledgeCatalog, type AgentKnowledgeSource,
} from '../../lib/workspaceAgentKnowledge';
import { GlassButton, Toggle } from '../ui/primitives';
import { SectionSearch } from '../workspace/primitives';
import { AgentField, AgentNotice, AgentTextField } from './AgentFields';

export function AgentKnowledgeFields({
    draft, setDraft, catalog, loading, error, onRefresh, readOnly,
}: {
    draft: AgentConfiguration;
    setDraft: Dispatch<SetStateAction<AgentConfiguration>>;
    catalog: AgentKnowledgeCatalog | null;
    loading: boolean;
    error: string | null;
    onRefresh: () => void;
    readOnly: boolean;
}) {
    const [sourceQuery, setSourceQuery] = useState('');
    const [documentQuery, setDocumentQuery] = useState('');
    const [tagQuery, setTagQuery] = useState('');
    const [documentLimit, setDocumentLimit] = useState(25);
    const [activeLimit, setActiveLimit] = useState(20);
    const [url, setUrl] = useState('');
    const [mode, setMode] = useState('url_review');
    const [inputError, setInputError] = useState<string | null>(null);
    const config = readAgentKnowledge(draft);
    const selectedKeys = new Set(selectedKnowledgeSources(config));
    const sources = (catalog?.sources ?? []).filter((source) => ['personal', 'public'].includes(source.scope));
    const documents = (catalog?.documents ?? []).filter((document) =>
        sources.some((source) => source.scope === document.scope && source.id === document.source_id));
    const unavailableSourceKeys = [...selectedKeys].filter((key) => !sources.some((source) => knowledgeSourceKey(source) === key));
    const unavailableDocuments = config.document_ids.filter((id) => !documents.some((document) => document.id === id));
    const tags = catalog?.tags ?? [];
    const unavailableTags = config.tags.filter((tag) => !tags.some((item) => item.name === tag));
    const visibleDocuments = documents.filter((document) =>
        `${document.title} ${document.file_name} ${document.source_name} ${document.id}`.toLowerCase().includes(documentQuery.toLowerCase()) &&
        (!selectedKeys.size || selectedKeys.has(`${document.scope}:${document.source_id}`) || config.document_ids.includes(document.id)));
    const active = catalog ? resolvedAgentDocuments(config, catalog) : [];

    const toggleSource = (source: AgentKnowledgeSource, enabled: boolean) => {
        setInputError(null);
        if (enabled && source.scope === 'public' && config.scopes.public_workspace_ids.length >= KNOWLEDGE_LIMITS.sources) {
            setInputError('You can assign at most 50 public workspaces.');
            return;
        }
        setDraft((current) => toggleAgentKnowledgeSource(current, source, enabled));
    };
    const addUrl = () => {
        setInputError(null);
        const normalized = normalizeAgentKnowledgeUrl(url);
        if (!normalized) {
            setInputError('Enter a valid HTTP or HTTPS URL without embedded credentials.');
            return;
        }
        if (config.web_sources.length >= KNOWLEDGE_LIMITS.urls && !config.web_sources.some((source) => source.url === normalized)) {
            setInputError('You can assign at most 50 URLs.');
            return;
        }
        setDraft((current) => {
            const next = readAgentKnowledge(current);
            const webSources = next.web_sources.filter((source) => source.url !== normalized);
            return updateAgentKnowledge(current, { web_sources: [...webSources, { url: normalized, mode }] });
        });
        setUrl('');
    };
    if (draft.agent_type !== 'local') {
        return <AgentNotice>Knowledge assigned to a local agent is retained but is not applied to this Foundry type. Configure knowledge in Foundry. Workflow document context is controlled in Model &amp; connection.</AgentNotice>;
    }
    return (
        <div className="space-y-4">
            <Toggle label="Restrict to assigned knowledge" checked={config.enabled}
                description="Ground this agent in selected authorized workspaces and URLs. Turning this off retains the configuration for later."
                onChange={(enabled) => setDraft((current) => updateAgentKnowledge(current, { enabled }))} />
            {!config.enabled && error ? <AgentNotice error>{error} <GlassButton type="button" size="sm" onClick={onRefresh}>Retry knowledge catalogue</GlassButton></AgentNotice> : null}
            {config.enabled ? (
                <>
                    <div className="flex flex-wrap items-center gap-3">
                        <GlassButton type="button" size="sm" disabled={loading} onClick={onRefresh}><RefreshCw size={14} />Refresh knowledge</GlassButton>
                        <span className="text-xs text-text-3">{selectedKeys.size} sources · {config.document_ids.length} explicit documents · {config.tags.length} tags · {config.web_sources.length} URLs</span>
                    </div>
                    {loading ? <p role="status" className="text-sm text-text-3">Loading authorized knowledge sources…</p> : null}
                    {error ? <AgentNotice error>{error} Existing selections are preserved.</AgentNotice> : null}
                    {inputError ? <AgentNotice error>{inputError}</AgentNotice> : null}
                    <fieldset className="space-y-3">
                        <legend className="mb-2 text-sm font-medium text-text-1">Source workspaces</legend>
                        <p className="text-xs text-text-3">Only your personal workspace and permitted public workspaces can be newly assigned. Removing a source does not silently remove stored document references.</p>
                        <SectionSearch value={sourceQuery} onChange={setSourceQuery} placeholder="Search knowledge workspaces" />
                        <div className="grid gap-2 sm:grid-cols-2">
                            {sources.filter((source) => `${source.label} ${source.id}`.toLowerCase().includes(sourceQuery.toLowerCase())).map((source) => (
                                <label key={knowledgeSourceKey(source)} className="flex items-start gap-2 rounded-xl border border-edge p-3 text-sm text-text-2">
                                    <input type="checkbox" className="mt-1 accent-accent" checked={selectedKeys.has(knowledgeSourceKey(source))}
                                        disabled={readOnly} onChange={(event) => toggleSource(source, event.target.checked)} />
                                    <span className="min-w-0 break-words">{source.label}<span className="block break-all text-xs text-text-3">{source.scope} · {source.id}</span></span>
                                </label>
                            ))}
                        </div>
                        {!sources.length && !loading && !error ? <p className="text-xs text-text-3">No authorized workspace sources are available. You may still assign URLs.</p> : null}
                        {unavailableSourceKeys.map((key) => (
                            <div key={key} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-warn/30 p-2">
                                <span className="break-all text-xs text-warn">Saved source unavailable here: {key}</span>
                                {!readOnly ? <GlassButton type="button" size="sm" aria-label={`Remove knowledge source ${key}`} onClick={() => {
                                    setDraft((current) => {
                                        const currentConfig = readAgentKnowledge(current);
                                        return updateAgentKnowledge(current, { scopes: {
                                            ...currentConfig.scopes,
                                            personal: key === 'personal:personal' ? false : currentConfig.scopes.personal,
                                            group_ids: currentConfig.scopes.group_ids.filter((id) => `group:${id}` !== key),
                                            public_workspace_ids: currentConfig.scopes.public_workspace_ids.filter((id) => `public:${id}` !== key),
                                        } });
                                    });
                                }}>Remove reference</GlassButton> : null}
                            </div>
                        ))}
                    </fieldset>
                    <fieldset className="space-y-3">
                        <legend className="mb-2 text-sm font-medium text-text-1">Documents and tags</legend>
                        <p className="text-xs text-text-3">With no document or tag limits, all indexed documents in selected sources are active. Otherwise, explicit documents are included alongside documents matching every selected tag.</p>
                        <SectionSearch value={documentQuery} onChange={(value) => { setDocumentQuery(value); setDocumentLimit(25); }} placeholder="Search knowledge documents" />
                        <div className="space-y-2">
                            {visibleDocuments.slice(0, documentLimit).map((document) => {
                                const checked = config.document_ids.includes(document.id);
                                const inSources = selectedKeys.has(`${document.scope}:${document.source_id}`);
                                return (
                                    <label key={`${document.scope}:${document.id}`} className="flex items-start gap-2 rounded-xl border border-edge p-3 text-sm text-text-2">
                                        <input type="checkbox" className="mt-1 accent-accent" checked={checked}
                                            disabled={readOnly || (!checked && (config.document_ids.length >= KNOWLEDGE_LIMITS.documents ||
                                                (!inSources && document.scope === 'public' && config.scopes.public_workspace_ids.length >= KNOWLEDGE_LIMITS.sources)))}
                                            onChange={(event) => setDraft((current) => {
                                                let next = current;
                                                if (event.target.checked) {
                                                    const source = sources.find((item) => item.scope === document.scope && item.id === document.source_id);
                                                    if (source) next = toggleAgentKnowledgeSource(current, source, true);
                                                }
                                                return updateAgentKnowledge(next, {
                                                    document_ids: toggleString(readAgentKnowledge(next).document_ids, document.id, event.target.checked),
                                                });
                                            })} />
                                        <span className="min-w-0 break-words">{document.title || document.file_name}
                                            <span className="block break-all text-xs text-text-3">{document.source_name} · {document.id}</span>
                                            {document.tags.length ? <span className="block text-xs text-text-3">{document.tags.join(', ')}</span> : null}
                                            {checked && !inSources ? <span className="block text-xs text-warn">Saved reference retained; its workspace is not selected.</span> : null}
                                        </span>
                                    </label>
                                );
                            })}
                        </div>
                        {visibleDocuments.length > documentLimit ? <GlassButton type="button" size="sm" onClick={() => setDocumentLimit((value) => value + 25)}>Show more documents ({visibleDocuments.length - documentLimit} remaining)</GlassButton> : null}
                        {unavailableDocuments.map((id) => (
                            <div key={id} className="flex flex-wrap items-center justify-between gap-2">
                                <code className="break-all text-xs text-warn">Unavailable document: {id}</code>
                                {!readOnly ? <GlassButton type="button" size="sm" aria-label={`Remove document reference ${id}`}
                                    onClick={() => setDraft((current) => updateAgentKnowledge(current, { document_ids: readAgentKnowledge(current).document_ids.filter((item) => item !== id) }))}>Remove reference</GlassButton> : null}
                            </div>
                        ))}
                        <SectionSearch value={tagQuery} onChange={setTagQuery} placeholder="Search knowledge tags" />
                        <div className="flex flex-wrap gap-3">
                            {tags.filter((tag) => tag.name.toLowerCase().includes(tagQuery.toLowerCase())).map((tag) => (
                                <label key={tag.name} className="flex items-center gap-2 text-sm text-text-2">
                                    <input type="checkbox" className="accent-accent" checked={config.tags.includes(tag.name)}
                                        disabled={readOnly || (!config.tags.includes(tag.name) && config.tags.length >= KNOWLEDGE_LIMITS.tags)}
                                        onChange={(event) => setDraft((current) => updateAgentKnowledge(current, {
                                            tags: toggleString(readAgentKnowledge(current).tags, tag.name, event.target.checked),
                                        }))} />
                                    {tag.name} <span className="text-xs text-text-3">({tag.count})</span>
                                </label>
                            ))}
                        </div>
                        {unavailableTags.map((tag) => (
                            <div key={tag} className="flex flex-wrap items-center justify-between gap-2">
                                <span className="break-all text-xs text-warn">Saved tag not in current catalogue: {tag}</span>
                                {!readOnly ? <GlassButton type="button" size="sm" aria-label={`Remove knowledge tag ${tag}`}
                                    onClick={() => setDraft((current) => updateAgentKnowledge(current, { tags: readAgentKnowledge(current).tags.filter((item) => item !== tag) }))}>Remove reference</GlassButton> : null}
                            </div>
                        ))}
                    </fieldset>
                    <details className="rounded-xl border border-edge p-3" open>
                        <summary className="cursor-pointer text-sm font-medium text-text-1">Active documents ({active.length})</summary>
                        <p className="mt-2 text-xs text-text-3">Preview from the authorized catalogue. Catalogue queries are limited to 1000 documents; runtime authorization and indexing determine the final context.</p>
                        {catalog ? (
                            <ul className="mt-2 space-y-1 text-xs text-text-2">
                                {active.slice(0, activeLimit).map((document) => <li key={document.id} className="break-words">{document.title || document.file_name} · {document.source_name}{config.document_ids.includes(document.id) ? ' · explicit' : ''}</li>)}
                            </ul>
                        ) : <p className="mt-2 text-xs text-text-3">Load the catalogue to resolve active documents.</p>}
                        {active.length > activeLimit ? <GlassButton type="button" size="sm" onClick={() => setActiveLimit((value) => value + 50)}>Show more active documents</GlassButton> : null}
                    </details>
                    <div className="space-y-3 rounded-xl border border-edge p-3">
                        <Toggle label="Allow user-added workspace context" checked={config.allow_user_workspace_context}
                            description="Let chat users supplement the assigned sources within their own permissions."
                            onChange={(value) => setDraft((current) => updateAgentKnowledge(current, { allow_user_workspace_context: value }))} />
                        <fieldset disabled={!config.allow_user_workspace_context} className="flex flex-wrap gap-4">
                            <legend className="mb-2 text-xs text-text-3">Allowed user-added context actions</legend>
                            {USER_KNOWLEDGE_ACTIONS.map((action) => (
                                <label key={action} className="flex items-center gap-2 text-sm text-text-2">
                                    <input type="checkbox" className="accent-accent" checked={config.allowed_user_workspace_actions.includes(action)}
                                        onChange={(event) => setDraft((current) => updateAgentKnowledge(current, {
                                            allowed_user_workspace_actions: toggleString(readAgentKnowledge(current).allowed_user_workspace_actions, action, event.target.checked),
                                        }))} />
                                    {action[0].toUpperCase() + action.slice(1)}
                                </label>
                            ))}
                        </fieldset>
                    </div>
                    <fieldset className="space-y-3">
                        <legend className="mb-2 text-sm font-medium text-text-1">Assigned URLs</legend>
                        <p className="text-xs text-text-3">URL review targets the assigned page. Deep research allows research from that source. Requests still follow the application’s web access policy.</p>
                        {!readOnly ? <div className="grid items-end gap-3 sm:grid-cols-[minmax(0,1fr)_10rem_auto]">
                            <AgentTextField label="Assigned URL" value={url} onChange={setUrl} placeholder="https://example.org/page" />
                            <AgentField id="agent-new-url-mode" label="URL mode">
                                <select id="agent-new-url-mode" value={mode} onChange={(event) => setMode(event.target.value)} className={AGENT_INPUT_CLASS}>
                                    <option value="url_review">URL review</option><option value="deep_research">Deep research</option>
                                </select>
                            </AgentField>
                            <GlassButton type="button" size="sm" onClick={addUrl}><Plus size={14} />Add URL</GlassButton>
                        </div> : null}
                        {config.web_sources.map((source, index) => (
                            <div key={`${source.url}:${index}`} className="grid gap-2 rounded-xl border border-edge p-3 sm:grid-cols-[minmax(0,1fr)_10rem_auto]">
                                <span className="break-all text-sm text-text-2">{source.url}</span>
                                <select aria-label={`Mode for ${source.url}`} value={source.mode} className={AGENT_INPUT_CLASS}
                                    onChange={(event) => setDraft((current) => updateAgentKnowledge(current, {
                                        web_sources: readAgentKnowledge(current).web_sources.map((item, at) => at === index ? { ...item, mode: event.target.value } : item),
                                    }))}>
                                    {!['url_review', 'deep_research'].includes(source.mode) ? <option value={source.mode}>Unrecognized: {source.mode}</option> : null}
                                    <option value="url_review">URL review</option><option value="deep_research">Deep research</option>
                                </select>
                                {!readOnly ? <GlassButton type="button" size="sm" aria-label={`Remove URL ${source.url}`}
                                    onClick={() => setDraft((current) => updateAgentKnowledge(current, {
                                        web_sources: readAgentKnowledge(current).web_sources.filter((_, at) => at !== index),
                                    }))}><Trash2 size={14} /></GlassButton> : null}
                            </div>
                        ))}
                    </fieldset>
                </>
            ) : <p className="text-sm text-text-3">This agent follows the normal chat context policy. Enable the restriction to define its assigned knowledge.</p>}
        </div>
    );
}
