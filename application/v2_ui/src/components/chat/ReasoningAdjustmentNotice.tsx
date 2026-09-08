// ReasoningAdjustmentNotice.tsx
import { normalizeReasoningAdjustments, reasoningAdjustmentMessage } from '../../lib/reasoning';

export function ReasoningAdjustmentNotice({ adjustments }: { adjustments: unknown }) {
    const messages = [...new Set(normalizeReasoningAdjustments(adjustments).map((resolution) =>
        reasoningAdjustmentMessage(
            resolution, typeof resolution.model_name === 'string' ? resolution.model_name : undefined,
        ),
    ))];
    if (!messages.length) return null;
    return (
        <div role="status" className="my-2 rounded-xl bg-warn-soft px-3 py-2 text-xs text-warn">
            {messages.map((message) => <p key={message}>{message}</p>)}
        </div>
    );
}
