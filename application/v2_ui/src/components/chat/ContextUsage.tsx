// ContextUsage.tsx
// How much of the model's context window the conversation's latest request used.
//
// ContextUsageButton is the ring in the composer; ContextUsageMode is the Context tab of the
// conversation drawer it opens. Both read the same numbers from the latest reply, so they can
// never disagree. Nothing is shown before a reply has recorded a request size.

import { useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { Gauge } from 'lucide-react';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useChatStore } from '../../stores/chatStore';
import { useContextUsageStore } from '../../stores/contextUsageStore';
import {
    describeContextUsage,
    formatContextSize,
    readContextTurns,
    readContextUsage,
    type ContextCategoryId,
    type ContextLevel,
    type ContextPlanModel,
    type ContextUsageView,
} from '../../lib/contextUsage';
import { EmptyState } from '../ui/primitives';
import { SectionHeading } from './DrawerAssets';

const CATEGORY_COLOR: Record<ContextCategoryId, string> = {
    messages: 'bg-accent',
    summary: 'bg-accent/50',
    files: 'bg-warn',
    search: 'bg-info',
    web: 'bg-change-ai',
    memory: 'bg-ok',
    instructions: 'bg-text-3',
    other: 'bg-text-2',
};

const LEVEL_STROKE: Record<ContextLevel, string> = {
    ok: 'stroke-accent',
    warn: 'stroke-warn',
    full: 'stroke-danger',
};

const LEVEL_TEXT: Record<ContextLevel, string> = {
    ok: 'text-accent',
    warn: 'text-warn',
    full: 'text-danger',
};

/**
 * Whether administrators let users see context usage. On unless the setting is explicitly off,
 * so a deployment whose settings predate it keeps the display. Hiding it does not stop the
 * server recording usage.
 */
export function useContextUsageEnabled(): boolean {
    return useBootstrapStore((state) => state.data?.features?.enable_context_usage_display !== false);
}

export function useContextUsage(): ContextUsageView | null {
    const enabled = useContextUsageEnabled();
    const messages = useChatStore((state) => state.messages);
    const selectedModel = useContextUsageStore((state) => state.selectedModel);
    return useMemo(
        () => (enabled ? readContextUsage(messages, selectedModel) : null),
        [enabled, messages, selectedModel],
    );
}

/** A progress ring. With no known limit it draws the empty track only. */
export function ContextRing({
    percent,
    level,
    size,
    strokeWidth = 3,
}: {
    percent: number | null;
    level: ContextLevel;
    size: number;
    strokeWidth?: number;
}) {
    const radius = 10 - strokeWidth / 2;
    const circumference = 2 * Math.PI * radius;
    const filled = percent === null ? 0 : (Math.min(100, Math.max(0, percent)) / 100) * circumference;
    return (
        <svg viewBox="0 0 20 20" width={size} height={size} aria-hidden="true" className="shrink-0">
            <circle
                cx="10"
                cy="10"
                r={radius}
                fill="none"
                strokeWidth={strokeWidth}
                className="stroke-edge-strong"
            />
            {filled > 0 && (
                <circle
                    cx="10"
                    cy="10"
                    r={radius}
                    fill="none"
                    strokeWidth={strokeWidth}
                    strokeLinecap="round"
                    strokeDasharray={`${filled} ${circumference}`}
                    transform="rotate(-90 10 10)"
                    className={LEVEL_STROKE[level]}
                />
            )}
        </svg>
    );
}

/** The composer's ring. Hovering names the numbers; clicking opens the Context tab. */
export function ContextUsageButton() {
    const usage = useContextUsage();
    const drawerMode = useChatStore((state) => state.drawerMode);
    const setDrawerMode = useChatStore((state) => state.setDrawerMode);
    if (!usage) {
        return null;
    }
    const open = drawerMode === 'context';
    const description = describeContextUsage(usage);
    return (
        <button
            type="button"
            onClick={() => setDrawerMode(open ? null : 'context')}
            aria-pressed={open}
            aria-label={`${description}. ${open ? 'Close' : 'Open'} context details`}
            title={description}
            data-context-usage={usage.percent ?? ''}
            className={clsx(
                'relative inline-flex h-9 w-9 items-center justify-center rounded-xl border transition-colors',
                open
                    ? 'border-transparent bg-accent-soft'
                    : 'border-edge bg-surface-1 hover:bg-surface-2',
            )}
        >
            <ContextRing percent={usage.percent} level={usage.level} size={30} strokeWidth={2.5} />
            <span
                className={clsx(
                    'absolute text-[9px] leading-none font-bold tabular-nums',
                    usage.percent === null ? 'text-text-2' : LEVEL_TEXT[usage.level],
                )}
                aria-hidden="true"
            >
                {usage.percent === null ? formatContextSize(usage.used) : usage.percent}
            </span>
        </button>
    );
}

function scrollToMessage(messageId: string) {
    const element = document.getElementById(`message-${messageId}`);
    if (!element) {
        return;
    }
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    element.classList.add('ring-2', 'ring-accent', 'rounded-2xl');
    window.setTimeout(() => {
        element.classList.remove('ring-2', 'ring-accent', 'rounded-2xl');
    }, 1400);
}

/** A share that rounds to nothing still used something. */
function formatShare(share: number): string {
    const percent = Math.round(share * 100);
    return percent === 0 && share > 0 ? '<1%' : `${percent}%`;
}

function SummaryCard({ usage }: { usage: ContextUsageView }) {
    const notes: string[] = [];
    if (usage.free !== null) {
        notes.push(`${formatContextSize(usage.free)} free`);
    }
    if (usage.replyReserve !== null) {
        notes.push(`${formatContextSize(usage.replyReserve)} held back for the reply`);
    }
    return (
        <div className="glass-flat rounded-xl p-3" data-context-summary>
            <div className="flex items-baseline gap-2">
                <span className={clsx('text-2xl font-semibold tabular-nums', usage.level !== 'ok' && LEVEL_TEXT[usage.level])}>
                    {usage.percent === null ? formatContextSize(usage.used) : `${usage.percent}%`}
                </span>
                <span className="min-w-0 text-[13px] text-text-2">
                    {usage.limit === null
                        ? 'tokens in the last request'
                        : `${formatContextSize(usage.used)} of ${formatContextSize(usage.limit)} tokens`}
                </span>
                {usage.model && (
                    <span className="ml-auto truncate text-xs text-text-3" title={usage.model}>
                        {usage.model}
                    </span>
                )}
            </div>
            {usage.limit !== null && (
                <div
                    role="img"
                    aria-label={`${usage.percent}% of the context window used`}
                    className="mt-2 flex h-2 gap-0.5 overflow-hidden rounded-full bg-surface-sunken"
                >
                    {usage.categories.length > 0 ? (
                        usage.categories.map((category) => (
                            <div
                                key={category.id}
                                className={CATEGORY_COLOR[category.id]}
                                style={{ width: `${(category.size / (usage.limit as number)) * 100}%` }}
                            />
                        ))
                    ) : (
                        <div className="bg-accent" style={{ width: `${usage.percent}%` }} />
                    )}
                </div>
            )}
            {notes.length > 0 && <p className="mt-1.5 text-xs text-text-3">{notes.join(' · ')}</p>}
            {usage.rebased && (
                <p className="mt-1.5 text-xs text-text-3" data-context-rebased>
                    Sized from the last reply and measured against {usage.model}, the model selected now.
                </p>
            )}
            {usage.limit === null && (
                <p className="mt-1.5 text-xs text-text-3">
                    This model's context window is not configured, so no percentage can be shown.
                </p>
            )}
        </div>
    );
}

function LevelNotice({ usage }: { usage: ContextUsageView }) {
    if (usage.level === 'ok') {
        return null;
    }
    return (
        <p
            role="status"
            className={clsx(
                'rounded-xl px-3 py-2 text-xs',
                usage.level === 'full' ? 'bg-danger-soft text-danger' : 'bg-warn-soft text-warn',
            )}
        >
            {usage.level === 'full'
                ? 'The context window is nearly full. Start a new chat to keep replies reliable.'
                : 'The context window is filling up. Large attached files use the most space.'}
        </p>
    );
}

function ByType({ usage }: { usage: ContextUsageView }) {
    if (usage.categories.length === 0) {
        return (
            <p className="px-1 text-sm text-text-3">
                This reply was made before the breakdown was recorded. Send another message to see
                what is using the context.
            </p>
        );
    }
    return (
        <>
            <ul className="space-y-2">
                {usage.categories.map((category) => (
                    <li
                        key={category.id}
                        className="glass-flat flex items-center gap-2.5 rounded-xl px-3 py-2"
                        data-context-category={category.id}
                    >
                        <span className={clsx('h-2 w-2 shrink-0 rounded-full', CATEGORY_COLOR[category.id])} />
                        <div className="min-w-0 flex-1">
                            <p className="truncate text-sm text-text-1">{category.label}</p>
                            <p className="text-xs text-text-3">{category.detail}</p>
                            {category.id === 'files' && usage.files.length > 0 && (
                                <ul className="mt-1 space-y-0.5">
                                    {usage.files.map((file) => (
                                        <li key={file.label} className="flex gap-2 text-xs text-text-2">
                                            <span className="min-w-0 flex-1 truncate" title={file.label}>
                                                {file.label}
                                            </span>
                                            <span className="shrink-0 tabular-nums">
                                                {formatContextSize(file.size)}
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                        <div className="shrink-0 self-start text-right tabular-nums">
                            <p className="text-sm text-text-1">{formatContextSize(category.size)}</p>
                            <p className="text-xs text-text-3">{formatShare(category.share)}</p>
                        </div>
                    </li>
                ))}
            </ul>
            <p className="px-1 text-xs text-text-3">
                {usage.measured
                    ? 'The total is the model provider’s count for the last request. The split is estimated.'
                    : 'These sizes are estimated. The provider reported several requests for the last reply, so no single count is available.'}
            </p>
        </>
    );
}

/** "3 steps", "planning and answer", or both. */
function describePlanModel(model: ContextPlanModel): string {
    const parts: string[] = [];
    if (model.stepCount > 0) {
        parts.push(`${model.stepCount} ${model.stepCount === 1 ? 'step' : 'steps'}`);
    }
    if (model.answered) {
        parts.push('planning and answer');
    }
    return parts.join(', ') || 'steps';
}

function ByTurn() {
    const messages = useChatStore((state) => state.messages);
    const turns = useMemo(() => readContextTurns(messages), [messages]);
    if (turns.length === 0) {
        return <p className="px-1 text-sm text-text-3">No request sizes have been recorded yet.</p>;
    }
    return (
        <>
            <ol className="space-y-1">
                {turns.map((turn) => (
                    <li key={turn.messageId}>
                        <button
                            type="button"
                            onClick={() => scrollToMessage(turn.messageId)}
                            className="flex w-full gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-surface-2"
                        >
                            <span className="mt-0.5 shrink-0 font-mono text-xs text-text-3">{turn.index}</span>
                            <span className="min-w-0 flex-1">
                                <span className="block truncate text-sm text-text-1">
                                    {turn.question || 'Reply'}
                                </span>
                                {turn.plan ? (
                                    <span className="mt-0.5 block text-xs text-text-3">
                                        Plan. Spent across planning and its steps, not held in context.
                                        {turn.models.map((model) => (
                                            <span key={model.label} className="mt-0.5 flex gap-2 text-text-2" data-context-plan-model>
                                                <span className="min-w-0 flex-1 truncate" title={model.label}>
                                                    {model.label}
                                                    <span className="text-text-3"> · {describePlanModel(model)}</span>
                                                </span>
                                                <span className="shrink-0 tabular-nums">{formatContextSize(model.total)}</span>
                                            </span>
                                        ))}
                                    </span>
                                ) : (
                                    <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-surface-sunken">
                                        <span
                                            className="block h-full rounded-full bg-accent"
                                            style={{ width: `${Math.max(2, turn.share * 100)}%` }}
                                        />
                                    </span>
                                )}
                            </span>
                            <span
                                className="shrink-0 text-[13px] text-text-2 tabular-nums"
                                data-context-turn={turn.plan ? 'plan' : 'request'}
                            >
                                {turn.measured ? '' : '~'}
                                {formatContextSize(turn.used)}
                                {turn.plan ? ' spent' : ''}
                            </span>
                        </button>
                    </li>
                ))}
            </ol>
            <p className="px-1 text-xs text-text-3">
                The size of the request behind each reply. A plan shows what it spent instead. Select
                one to jump to it.
            </p>
        </>
    );
}

function HistoryNote({ usage }: { usage: ContextUsageView }) {
    const history = usage.history;
    if (!history) {
        return null;
    }
    const older =
        history.olderCount === 0
            ? ''
            : history.summaryUsed
              ? ` ${history.olderCount} older ${history.olderCount === 1 ? 'message was' : 'messages were'} sent as a short summary.`
              : ` ${history.olderCount} older ${history.olderCount === 1 ? 'message was' : 'messages were'} left out.`;
    return (
        <p className="px-1 text-xs text-text-3" data-context-history>
            Each request sends the last {history.limit} messages.{older}
        </p>
    );
}

/** The Context tab of the conversation drawer. */
export function ContextUsageMode() {
    const usage = useContextUsage();
    const [view, setView] = useState<'type' | 'turn'>('type');
    if (!usage) {
        return (
            <EmptyState
                icon={<Gauge size={24} />}
                title="No context used yet"
                description="After the first reply, this shows how much of the model's context window the conversation uses and what is using it."
            />
        );
    }
    return (
        <div className="space-y-3 p-3">
            <SummaryCard usage={usage} />
            <LevelNotice usage={usage} />
            <div role="tablist" aria-label="Group context by" className="flex gap-1 rounded-xl bg-surface-sunken p-1">
                {(['type', 'turn'] as const).map((id) => (
                    <button
                        key={id}
                        type="button"
                        role="tab"
                        aria-selected={view === id}
                        onClick={() => setView(id)}
                        className={clsx(
                            'flex-1 rounded-lg px-2.5 py-1 text-[13px] transition-colors',
                            view === id ? 'bg-surface-3 font-medium text-text-1' : 'text-text-3 hover:text-text-1',
                        )}
                    >
                        {id === 'type' ? 'By type' : 'By turn'}
                    </button>
                ))}
            </div>
            {view === 'type' ? (
                <>
                    <SectionHeading>What is using it</SectionHeading>
                    <ByType usage={usage} />
                </>
            ) : (
                <ByTurn />
            )}
            <HistoryNote usage={usage} />
        </div>
    );
}
