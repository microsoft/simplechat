// contextUsage.ts
// Reads how much of the model's context window a conversation's latest request used.
//
// Two facts are stored on each assistant reply. `metadata.token_usage` is the provider's own
// count for the request. `metadata.history_context.context_usage` is the server's estimate of
// the same request split by where the text came from, plus the selected model's limits.
// The provider's count is the truth for the total; the estimate supplies the split. Where the
// two disagree the difference is shown as its own row rather than hidden.

import type { ChatMessage } from './types';

export type ContextCategoryId =
    | 'messages'
    | 'summary'
    | 'files'
    | 'search'
    | 'web'
    | 'memory'
    | 'instructions'
    | 'other';

export interface ContextCategory {
    id: ContextCategoryId;
    label: string;
    detail: string;
    size: number;
    /** Share of what was used, 0 to 1. */
    share: number;
}

export interface ContextFile {
    label: string;
    size: number;
}

export interface ContextHistoryWindow {
    limit: number;
    recentCount: number;
    olderCount: number;
    summaryUsed: boolean;
}

export type ContextLevel = 'ok' | 'warn' | 'full';

export interface ContextUsageView {
    /** The reply these numbers describe. */
    messageId: string;
    model: string;
    used: number;
    /** True when `used` is the provider's count, false when it is the server's estimate. */
    measured: boolean;
    /** What a request may fill: the window less the space held back for the reply. */
    limit: number | null;
    window: number | null;
    replyReserve: number | null;
    free: number | null;
    /** Whole percent of `limit`, or null when the model's limits are not known. */
    percent: number | null;
    level: ContextLevel;
    categories: ContextCategory[];
    files: ContextFile[];
    history: ContextHistoryWindow | null;
    /**
     * True when the limit is that of the model now selected in the composer, which is not the
     * model the measured reply ran on. The size is still the last reply's.
     */
    rebased: boolean;
}

/** The composer's selected model and the limits the server resolved for it. */
export interface SelectedContextModel {
    /** Deployment name, compared with the model a reply ran on. */
    model: string;
    label: string;
    limits: unknown;
}

export interface ContextTurn {
    messageId: string;
    /** 1-based position among the conversation's questions. */
    index: number;
    question: string;
    used: number;
    measured: boolean;
    /**
     * True for a reply an orchestration plan produced. Its number is everything the plan spent
     * across planning and its steps, not the size of a request, so it has no bar.
     */
    plan: boolean;
    /** For a plan, what each model it ran on spent, largest first. Empty otherwise. */
    models: ContextPlanModel[];
    /** Share of the largest request, 0 to 1, for the bar. Always 0 for a plan. */
    share: number;
}

/** One model's part of a plan: its steps can run on different models. */
export interface ContextPlanModel {
    label: string;
    total: number;
    stepCount: number;
    /** True when this model also planned and wrote the final answer. */
    answered: boolean;
}

type Bag = Record<string, unknown>;

const CATEGORY_ORDER: ContextCategoryId[] = [
    'messages',
    'summary',
    'files',
    'search',
    'web',
    'memory',
    'instructions',
    'other',
];

const CATEGORY_TEXT: Record<ContextCategoryId, { label: string; detail: string }> = {
    messages: { label: 'Messages', detail: 'The recent messages sent with each request' },
    summary: { label: 'Summary of earlier messages', detail: 'Older messages, shortened' },
    files: { label: 'Attached files', detail: 'Files and images uploaded to this chat' },
    search: { label: 'Workspace results', detail: 'Document passages found for this question' },
    web: { label: 'Web results', detail: 'Web search results and pages read for this question' },
    memory: { label: 'Memory', detail: 'Saved facts and instructions' },
    instructions: { label: 'Instructions', detail: 'System prompt and guidance for this request' },
    other: { label: 'Agent, tools and overhead', detail: 'Tool definitions and request formatting' },
};

export const CONTEXT_WARN_PERCENT = 75;
export const CONTEXT_FULL_PERCENT = 90;

function bag(value: unknown): Bag {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Bag) : {};
}

function positive(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.round(value) : null;
}

function isActiveReply(message: ChatMessage): boolean {
    if (message.role !== 'assistant') {
        return false;
    }
    const thread = bag(bag(message.metadata).thread_info);
    return thread.active_thread !== false;
}

/** The provider's input count, only when one request produced it. */
/** A reply produced by an orchestration plan rather than by one chat request. */
function isPlanReply(metadata: Bag): boolean {
    return Object.keys(bag(metadata.orchestration)).length > 0;
}

/** Everything a plan spent: planning, each step and the final answer, added together. */
function planSpend(metadata: Bag): number | null {
    const usage = bag(metadata.token_usage);
    return positive(usage.total_tokens) ?? positive(usage.prompt_tokens);
}

function planModels(metadata: Bag): ContextPlanModel[] {
    if (!Array.isArray(metadata.usage_by_model)) {
        return [];
    }
    const models: ContextPlanModel[] = [];
    for (const entry of metadata.usage_by_model) {
        const row = bag(entry);
        const total = positive(row.total_tokens);
        const label = (typeof row.label === 'string' && row.label) || (typeof row.model === 'string' && row.model) || '';
        if (total === null || !label) {
            continue;
        }
        models.push({
            label,
            total,
            stepCount: positive(row.step_count) ?? 0,
            answered: Array.isArray(row.roles) && row.roles.includes('planning_and_answer'),
        });
    }
    return models;
}

function measuredInput(metadata: Bag): number | null {
    // A plan's counts are added up over many separate requests. None of them is the
    // conversation's context, and only the plan's answer is carried into later requests.
    if (isPlanReply(metadata)) {
        return null;
    }
    const usage = bag(metadata.token_usage);
    const prompt = positive(usage.prompt_tokens);
    if (prompt === null) {
        return null;
    }
    // An agent that called tools made several requests and the counts were added together,
    // which is spend, not the size of any one request.
    const requests = positive(usage.request_count) ?? 1;
    return requests <= 1 ? prompt : null;
}

function replyUsage(message: ChatMessage): { used: number; measured: boolean; estimate: Bag } | null {
    const metadata = bag(message.metadata);
    const estimate = bag(bag(metadata.history_context).context_usage);
    const measured = measuredInput(metadata);
    if (measured !== null) {
        return { used: measured, measured: true, estimate };
    }
    const estimated = positive(estimate.estimated_total);
    return estimated === null ? null : { used: estimated, measured: false, estimate };
}

function buildCategories(estimate: Bag, used: number, measured: boolean): ContextCategory[] {
    const sizes = bag(estimate.categories);
    const estimatedTotal = positive(estimate.estimated_total);
    if (estimatedTotal === null) {
        return [];
    }
    const rows: Array<{ id: ContextCategoryId; size: number }> = [];
    for (const id of CATEGORY_ORDER) {
        const size = positive(sizes[id]);
        if (size !== null) {
            rows.push({ id, size });
        }
    }
    if (measured && used > estimatedTotal) {
        // What the provider counted beyond the listed text: tool definitions, an agent's own
        // instructions and the request's formatting.
        rows.push({ id: 'other', size: used - estimatedTotal });
    } else if (measured && used < estimatedTotal) {
        // The estimate ran high. Scale it so the rows add up to the provider's count.
        const scale = used / estimatedTotal;
        for (const row of rows) {
            row.size = Math.max(1, Math.round(row.size * scale));
        }
    }
    return rows.map((row) => ({
        id: row.id,
        ...CATEGORY_TEXT[row.id],
        size: row.size,
        share: used > 0 ? Math.min(1, row.size / used) : 0,
    }));
}

function buildFiles(estimate: Bag): ContextFile[] {
    if (!Array.isArray(estimate.items)) {
        return [];
    }
    const files: ContextFile[] = [];
    for (const entry of estimate.items) {
        const item = bag(entry);
        const size = positive(item.size);
        if (item.category === 'files' && typeof item.label === 'string' && item.label && size !== null) {
            files.push({ label: item.label, size });
        }
    }
    return files;
}

function buildHistory(metadata: Bag): ContextHistoryWindow | null {
    const history = bag(metadata.history_context);
    const limit = positive(history.history_limit);
    if (limit === null) {
        return null;
    }
    return {
        limit,
        recentCount: positive(history.recent_message_count) ?? 0,
        olderCount: positive(history.older_message_count) ?? 0,
        summaryUsed: history.summary_used === true,
    };
}

export function contextLevel(percent: number | null): ContextLevel {
    if (percent === null) {
        return 'ok';
    }
    if (percent >= CONTEXT_FULL_PERCENT) {
        return 'full';
    }
    return percent >= CONTEXT_WARN_PERCENT ? 'warn' : 'ok';
}

/** Context usage of the most recent reply that recorded any, or null when none has. */
export function readContextUsage(
    messages: ChatMessage[],
    selected?: SelectedContextModel | null,
): ContextUsageView | null {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
        const message = messages[index];
        if (!isActiveReply(message)) {
            continue;
        }
        const usage = replyUsage(message);
        if (!usage) {
            continue;
        }
        const metadata = bag(message.metadata);
        const replyModel =
            (typeof usage.estimate.model === 'string' && usage.estimate.model) ||
            message.model_deployment_name ||
            '';
        // The next message goes to the model selected now. When its limits are known they
        // replace the last reply's, so switching models moves the ring at once.
        const selectedLimits = bag(selected?.limits);
        const useSelected = Boolean(selected) && positive(selectedLimits.input_ceiling) !== null;
        const limits = useSelected ? selectedLimits : bag(usage.estimate.limits);
        const limit = positive(limits.input_ceiling);
        const percent = limit === null ? null : Math.min(100, Math.round((usage.used / limit) * 100));
        const rebased = useSelected && Boolean(replyModel) && selected?.model !== replyModel;
        const model = useSelected ? selected?.label || selected?.model || replyModel : replyModel;
        return {
            messageId: message.id,
            model,
            rebased,
            used: usage.used,
            measured: usage.measured,
            limit,
            window: positive(limits.window),
            replyReserve: positive(limits.reply_reserve),
            free: limit === null ? null : Math.max(0, limit - usage.used),
            percent,
            level: contextLevel(percent),
            categories: buildCategories(usage.estimate, usage.used, usage.measured),
            files: buildFiles(usage.estimate),
            history: buildHistory(metadata),
        };
    }
    return null;
}

/** A plan step's fullest single request against the limit of the model it ran on. */
export interface StepContextFill {
    model: string;
    peakRequest: number;
    limit: number | null;
    percent: number | null;
    level: ContextLevel;
}

/** Read a step record's `context_fill`, or undefined when the step recorded no request size. */
export function normalizeStepContextFill(raw: unknown): StepContextFill | undefined {
    const fill = bag(raw);
    const peakRequest = positive(fill.peak_request);
    if (peakRequest === null) {
        return undefined;
    }
    const limit = positive(fill.limit);
    const percent = limit === null ? null : Math.min(100, Math.round((peakRequest / limit) * 100));
    return {
        model: typeof fill.model === 'string' ? fill.model : '',
        peakRequest,
        limit,
        percent,
        level: contextLevel(percent),
    };
}

/** "Largest request: 82% of GPT-4o's window (92K of 112K tokens)", or sizes alone. */
export function describeStepContextFill(fill: StepContextFill): string {
    const size = `${formatContextSize(fill.peakRequest)} tokens`;
    if (fill.limit === null || fill.percent === null) {
        return fill.model ? `Largest request: ${size} on ${fill.model}` : `Largest request: ${size}`;
    }
    const window = fill.model ? `${fill.model}'s window` : "the model's window";
    return `Largest request: ${fill.percent}% of ${window} (${formatContextSize(fill.peakRequest)} of ${formatContextSize(fill.limit)} tokens)`;
}

/** How large the request behind each reply was, oldest first. */
export function readContextTurns(messages: ChatMessage[]): ContextTurn[] {
    const turns: Array<Omit<ContextTurn, 'share'>> = [];
    let question = '';
    let questionIndex = 0;
    for (const message of messages) {
        if (message.role === 'user') {
            question = typeof message.content === 'string' ? message.content : '';
            questionIndex += 1;
            continue;
        }
        if (!isActiveReply(message)) {
            continue;
        }
        const metadata = bag(message.metadata);
        if (isPlanReply(metadata)) {
            const spent = planSpend(metadata);
            if (spent !== null) {
                turns.push({
                    messageId: message.id,
                    index: Math.max(1, questionIndex),
                    question,
                    used: spent,
                    measured: true,
                    plan: true,
                    models: planModels(metadata),
                });
            }
            continue;
        }
        const usage = replyUsage(message);
        if (!usage) {
            continue;
        }
        turns.push({
            messageId: message.id,
            index: Math.max(1, questionIndex),
            question,
            used: usage.used,
            measured: usage.measured,
            plan: false,
            models: [],
        });
    }
    const largest = turns.reduce((max, turn) => (turn.plan ? max : Math.max(max, turn.used)), 0);
    return turns.map((turn) => ({
        ...turn,
        share: turn.plan || largest <= 0 ? 0 : turn.used / largest,
    }));
}

/** 950 -> "950", 8240 -> "8.2K", 82600 -> "82.6K", 1200000 -> "1.2M". */
export function formatContextSize(value: number): string {
    if (!Number.isFinite(value) || value <= 0) {
        return '0';
    }
    if (value < 1000) {
        return String(Math.round(value));
    }
    const trim = (text: string) => text.replace(/\.0$/, '');
    if (value < 999_950) {
        return `${trim((value / 1000).toFixed(1))}K`;
    }
    return `${trim((value / 1_000_000).toFixed(1))}M`;
}

/** One line for a tooltip or a screen reader. */
export function describeContextUsage(view: ContextUsageView): string {
    const used = `${formatContextSize(view.used)} tokens`;
    if (view.limit === null || view.percent === null) {
        return `Context: ${used} in the last request`;
    }
    return `Context: ${view.percent}% used, ${used} of ${formatContextSize(view.limit)}`;
}
