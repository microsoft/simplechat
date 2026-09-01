// ThoughtsList.tsx
// The one way reasoning steps are drawn, whether they arrived on a live stream or were read
// back from storage afterwards.
//
// Historical reasoning deliberately looks identical to reasoning being generated. A separate
// "timeline" treatment for the stored version would make the same information feel like a
// different feature depending on when you looked at it.

import type { PersistedThought, ThoughtEntry } from '../../lib/types';

/**
 * Normalise a stored reasoning step into the shape the live stream produces.
 *
 * The two are not the same record: a stream frame carries `title` and `content`, while
 * `route_backend_thoughts.py` returns `step_type`, `content`, `detail`, `activity` and
 * timing. Mapping them here is what lets a single renderer serve both.
 */
export function normalizePersistedThought(
    thought: PersistedThought,
    index: number,
): ThoughtEntry & { duration?: string } {
    const title =
        String(thought.step_type ?? '').trim() ||
        String(thought.activity ?? '').trim() ||
        `Step ${index + 1}`;

    const content = String(thought.content ?? '').trim();
    const detail = String(thought.detail ?? '').trim();

    return {
        id: String(thought.id ?? `${thought.message_id ?? 'thought'}-${index}`),
        title,
        // `detail` elaborates on `content` when they differ; showing both without repeating
        // the same sentence twice.
        content: detail && detail !== content ? `${content}\n${detail}`.trim() : content,
        duration:
            typeof thought.duration_ms === 'number' && thought.duration_ms > 0
                ? `${(thought.duration_ms / 1000).toFixed(1)}s`
                : undefined,
    };
}

export function ThoughtsList({
    thoughts,
}: {
    thoughts: Array<ThoughtEntry & { duration?: string }>;
}) {
    return (
        <ol className="space-y-1.5 border-l border-edge-strong pl-3">
            {thoughts.map((thought) => (
                <li key={thought.id} className="text-xs text-text-3">
                    <span className="font-medium text-text-2">{thought.title}</span>
                    {thought.duration && (
                        <span className="ml-2 font-mono text-[10px] text-text-3">
                            {thought.duration}
                        </span>
                    )}
                    {thought.content && (
                        <p className="mt-0.5 whitespace-pre-wrap">{thought.content}</p>
                    )}
                </li>
            ))}
        </ol>
    );
}
