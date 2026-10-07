// agentEditorAssist.ts
// How the agent editor describes its draft to Ask AI, and how it applies Ask AI's changes.
//
// The view lists only fields a person can set in the editor, with the same limits the editor
// enforces. Connection details, keys and the raw settings JSON are never described. Applying a
// patch goes through the editor's own helpers (renaming, model choice, knowledge), so a change
// from Ask AI is the same change the person could have made by hand.

import type {
    EditorAssistField, EditorAssistOption, EditorAssistSection, EditorAssistValues, EditorAssistView,
} from './editorAssist';
import type { ActionConfiguration, AgentConfiguration, AgentEditorOptions } from './workspaceAuthoring';
import {
    agentModelChoices, agentText, clearAgentDraftFields, renameAgentDraft, selectAgentModel, selectedAgentModel,
} from './workspaceAgentAuthoring';
import { agentActionLabel, agentActionUnavailableReason, resolveAgentAction } from './workspaceAgentActions';
import {
    KNOWLEDGE_LIMITS, knowledgeSourceKey, normalizeAgentKnowledgeUrl, readAgentKnowledge, selectedKnowledgeSources,
    updateAgentKnowledge, type AgentKnowledgeCatalog, type AgentWebSource,
} from './workspaceAgentKnowledge';
import type { AgentTargetCatalog } from './agentDelegation';

/** The editor's sections, in the order the editor shows them. */
export const AGENT_ASSIST_SECTIONS: readonly EditorAssistSection[] = [
    { id: 'identity', label: 'Identity' },
    { id: 'model', label: 'Model & connection' },
    { id: 'actions', label: 'Actions' },
    { id: 'knowledge', label: 'Assigned knowledge' },
    { id: 'instructions', label: 'Instructions' },
    { id: 'advanced', label: 'Advanced' },
];

const MAX_DOCUMENT_OPTIONS = 500;
const MAX_TAG_OPTIONS = 200;
const MAX_ACTION_OPTIONS = 500;
const DESCRIPTION_LIMIT = 1000;
const INSTRUCTIONS_LIMIT = 20000;
const DISPLAY_NAME_LIMIT = 100;
const MAX_TOKENS = 512000;

export interface AgentAssistContext {
    readonly options: AgentEditorOptions;
    readonly actions: readonly ActionConfiguration[];
    readonly targets: AgentTargetCatalog | null;
    readonly knowledge: AgentKnowledgeCatalog | null;
    /** The knowledge source scopes this agent may use, such as personal and public. */
    readonly knowledgeScopes: readonly string[];
    /** Reasoning levels the selected model supports. */
    readonly reasoningLevels: readonly string[];
    readonly ownerId: string;
    readonly isNew: boolean;
}

function webSourcesValue(sources: readonly AgentWebSource[]): { url: string; mode: string }[] {
    return sources.map((source) => ({ url: source.url, mode: source.mode === 'deep_research' ? 'deep_research' : 'url_review' }));
}

/** The reference an action is assigned by, matching toggleAgentAction. */
function actionReference(action: ActionConfiguration): string {
    return action.id || action.name;
}

/** Every value the assistant may read, keyed by path. */
export function agentAssistValues(draft: AgentConfiguration, context: AgentAssistContext): EditorAssistValues {
    const values: Record<string, unknown> = {
        '/display_name': draft.display_name,
        '/description': draft.description,
        '/instructions': draft.instructions,
        '/agent_type': draft.agent_type,
    };
    if (draft.agent_type !== 'local') return values;
    const model = selectedAgentModel(draft, agentModelChoices(context.options));
    values['/model'] = model?.key ?? null;
    values['/actions'] = [...draft.actions_to_load];
    values['/reasoning_effort'] = draft.reasoning_effort || null;
    values['/max_completion_tokens'] = Number.isFinite(draft.max_completion_tokens) ? draft.max_completion_tokens : null;
    const knowledge = readAgentKnowledge(draft);
    values['/knowledge/enabled'] = knowledge.enabled;
    values['/knowledge/web_sources'] = webSourcesValue(knowledge.web_sources);
    if (context.knowledge) {
        values['/knowledge/sources'] = selectedKnowledgeSources(knowledge);
        values['/knowledge/documents'] = [...knowledge.document_ids];
        values['/knowledge/tags'] = [...knowledge.tags];
    }
    return values;
}

function actionOptions(draft: AgentConfiguration, context: AgentAssistContext): EditorAssistOption[] {
    const actions = [...context.actions];
    const seen = new Set<string>();
    const options: EditorAssistOption[] = [];
    for (const action of actions) {
        // An assigned action keeps the reference the draft already uses, which may be its name.
        const assignedAs = draft.actions_to_load.find((item) => resolveAgentAction(item, actions) === action);
        const reference = assignedAs ?? actionReference(action);
        if (!reference || seen.has(reference)) continue;
        // An action that can't be newly assigned is offered only when it is already assigned,
        // so the assistant can keep or remove it but never add it.
        const blocked = agentActionUnavailableReason(draft, action, context.targets, context.ownerId);
        if (blocked && !assignedAs) continue;
        seen.add(reference);
        const type = agentText(action.type);
        const description = agentText(action.description).slice(0, 900);
        options.push({
            value: reference,
            label: agentActionLabel(action),
            description: [type ? `Type: ${type}.` : '', description].filter(Boolean).join(' ') || undefined,
        });
        if (options.length >= MAX_ACTION_OPTIONS) break;
    }
    return options;
}

/** The draft as Ask AI sees it. */
export function buildAgentAssistView(draft: AgentConfiguration, context: AgentAssistContext): EditorAssistView {
    const local = draft.agent_type === 'local';
    const fields: EditorAssistField[] = [
        {
            path: '/display_name', label: 'Display name', section: 'identity', kind: 'text', required: true,
            max_length: DISPLAY_NAME_LIMIT, help: 'The name people see when they choose this agent.',
        },
        {
            path: '/description', label: 'Description', section: 'identity', kind: 'textarea', required: true,
            max_length: DESCRIPTION_LIMIT, help: 'What this agent does and when someone should choose it.',
        },
        {
            path: '/agent_type', label: 'Agent type', section: 'identity', kind: 'select', read_only: true,
            options: context.options.agent_types.map((type) => ({ value: type.value, label: type.label })),
            help: 'Change the agent type in the editor yourself; Foundry types need connection details.',
        },
        {
            path: '/instructions', label: 'Instructions', section: 'instructions', kind: 'textarea',
            required: local, max_length: INSTRUCTIONS_LIMIT,
            help: local ? "The agent's system prompt." : 'Kept for a local agent. A Foundry agent uses its own instructions.',
        },
    ];
    const notes: string[] = [];
    if (local) {
        const models = agentModelChoices(context.options);
        if (models.length) {
            fields.push({
                path: '/model', label: 'Model', section: 'model', kind: 'select',
                options: models.map((choice) => ({ value: choice.key, label: choice.label })),
                help: 'The model that answers for this agent.',
            });
        }
        const actions = actionOptions(draft, context);
        if (actions.length || draft.actions_to_load.length) {
            fields.push({
                path: '/actions', label: 'Actions', section: 'actions', kind: 'choices', max_items: MAX_ACTION_OPTIONS,
                options: actions, help: 'The actions this agent may call.',
            });
        } else {
            notes.push('No actions are available to assign yet.');
        }
        fields.push({
            path: '/max_completion_tokens', label: 'Completion token limit', section: 'advanced', kind: 'number',
            min: -1, max: MAX_TOKENS, integer: true, required: true, help: '-1 uses the model default.',
        });
        const levels = [...context.reasoningLevels];
        if (draft.reasoning_effort && !levels.includes(draft.reasoning_effort)) levels.push(draft.reasoning_effort);
        if (levels.length) {
            fields.push({
                path: '/reasoning_effort', label: 'Reasoning effort', section: 'advanced', kind: 'select',
                options: levels.map((level) => ({ value: level, label: level[0].toUpperCase() + level.slice(1) })),
                help: 'Leave empty (null) to use the configured default.',
            });
        }
        fields.push({
            path: '/knowledge/enabled', label: 'Use assigned knowledge', section: 'knowledge', kind: 'boolean',
            help: 'When on, the agent answers from the knowledge chosen below.',
        });
        if (context.knowledge) {
            const sources = context.knowledge.sources.filter((source) => context.knowledgeScopes.includes(source.scope));
            fields.push({
                path: '/knowledge/sources', label: 'Knowledge workspaces', section: 'knowledge', kind: 'choices',
                max_items: KNOWLEDGE_LIMITS.sources,
                options: sources.slice(0, KNOWLEDGE_LIMITS.sources * 4).map((source) => ({
                    value: knowledgeSourceKey(source), label: source.label || source.id, description: `${source.scope} workspace`,
                })),
                help: 'The workspaces the agent may search.',
            });
            const documents = context.knowledge.documents.filter((document) =>
                context.knowledgeScopes.includes(document.scope)).slice(0, MAX_DOCUMENT_OPTIONS);
            if (documents.length) {
                fields.push({
                    path: '/knowledge/documents', label: 'Specific documents', section: 'knowledge', kind: 'choices',
                    max_items: KNOWLEDGE_LIMITS.documents,
                    options: documents.map((document) => ({
                        value: document.id,
                        label: document.title || document.file_name || document.id,
                        description: [document.source_name, document.tags.length ? `Tags: ${document.tags.join(', ')}` : '']
                            .filter(Boolean).join('. ').slice(0, 900) || undefined,
                    })),
                    help: "Leave empty to use every document in the chosen workspaces. A document's workspace must be chosen too.",
                });
            }
            const tags = context.knowledge.tags.slice(0, MAX_TAG_OPTIONS);
            if (tags.length) {
                fields.push({
                    path: '/knowledge/tags', label: 'Document tags', section: 'knowledge', kind: 'choices',
                    max_items: KNOWLEDGE_LIMITS.tags,
                    options: tags.map((tag) => ({ value: tag.name, label: tag.name, description: `${tag.count} documents` })),
                    help: 'Limit the agent to documents with every chosen tag.',
                });
            }
        } else {
            notes.push("The knowledge catalogue hasn't loaded, so workspaces, documents and tags can't be chosen yet.");
        }
        fields.push({
            path: '/knowledge/web_sources', label: 'Web pages', section: 'knowledge', kind: 'web_sources',
            max_items: KNOWLEDGE_LIMITS.urls, help: 'Only add pages the person named.',
        });
    } else {
        notes.push('This is a Foundry agent: its model, tools and knowledge are managed in Foundry, so only identity and description can change here.');
    }
    return {
        sections: AGENT_ASSIST_SECTIONS,
        fields,
        values: agentAssistValues(draft, context),
        notes,
    };
}

function strings(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

/**
 * The draft with a patch applied, or null when the patch can't be applied, such as a model
 * that is no longer offered.
 */
export function applyAgentAssistPatch(
    draft: AgentConfiguration,
    patch: Readonly<Record<string, unknown>>,
    context: AgentAssistContext,
): AgentConfiguration | null {
    let next = draft;
    for (const [path, value] of Object.entries(patch)) {
        switch (path) {
            case '/display_name':
                next = renameAgentDraft(next, agentText(value), context.isNew);
                break;
            case '/description':
                next = { ...next, description: agentText(value) };
                break;
            case '/instructions':
                next = { ...next, instructions: agentText(value) };
                break;
            case '/model': {
                const choice = agentModelChoices(context.options).find((item) => item.key === value);
                if (!choice) return null;
                next = selectAgentModel(next, choice);
                break;
            }
            case '/actions':
                next = { ...next, actions_to_load: [...new Set(strings(value))] };
                break;
            case '/reasoning_effort': {
                const effort = agentText(value);
                const updated = { ...next };
                if (effort) updated.reasoning_effort = effort;
                else delete updated.reasoning_effort;
                next = updated;
                break;
            }
            case '/max_completion_tokens': {
                if (typeof value !== 'number' || !Number.isInteger(value)) return null;
                next = clearAgentDraftFields({ ...next, max_completion_tokens: value }, '_editor_completion_text');
                break;
            }
            case '/knowledge/enabled':
                next = updateAgentKnowledge(next, { enabled: value === true });
                break;
            case '/knowledge/sources': {
                const keys = strings(value);
                const scopes = { ...readAgentKnowledge(next).scopes };
                scopes.personal = keys.some((key) => key.startsWith('personal:'));
                scopes.group_ids = keys.filter((key) => key.startsWith('group:')).map((key) => key.slice('group:'.length));
                scopes.public_workspace_ids = keys.filter((key) => key.startsWith('public:')).map((key) => key.slice('public:'.length));
                next = updateAgentKnowledge(next, { scopes });
                break;
            }
            case '/knowledge/documents':
                next = updateAgentKnowledge(next, { document_ids: [...new Set(strings(value))] });
                break;
            case '/knowledge/tags':
                next = updateAgentKnowledge(next, { tags: [...new Set(strings(value))] });
                break;
            case '/knowledge/web_sources': {
                if (!Array.isArray(value)) return null;
                const existing = new Map(readAgentKnowledge(next).web_sources.map((source) => [source.url, source]));
                const sources: AgentWebSource[] = [];
                for (const item of value) {
                    if (!item || typeof item !== 'object') return null;
                    const raw = agentText((item as Record<string, unknown>).url);
                    const url = existing.has(raw) ? raw : normalizeAgentKnowledgeUrl(raw);
                    if (!url) return null;
                    const mode = (item as Record<string, unknown>).mode === 'deep_research' ? 'deep_research' : 'url_review';
                    sources.push({ ...(existing.get(url) ?? {}), url, mode });
                }
                next = updateAgentKnowledge(next, { web_sources: sources });
                break;
            }
            default:
                return null;
        }
    }
    return next;
}
