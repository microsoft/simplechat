// FeedbackRetest.tsx
// Sends a feedback record's prompt to the current model configuration and shows the new
// answer beside the response the user rated, so a reviewer can tell whether a change since
// then already addresses the feedback.
//
// The retest runs only when asked: it calls the model, which takes time and costs tokens.
// Nothing is saved; the record keeps the response the user saw.

import { useState } from 'react';
import { FlaskConical, Loader2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { errorText, retestFeedbackPrompt } from '../../lib/reviewCenterApi';
import type { FeedbackRecord } from '../../lib/reviewCenter';
import { ReviewNotice, ReviewTextBlock } from './ReviewParts';

export function FeedbackRetest({ record, testIdPrefix }: { record: FeedbackRecord; testIdPrefix: string }) {
    const [running, setRunning] = useState(false);
    const [answer, setAnswer] = useState<string | null>(null);
    const [error, setError] = useState('');

    const run = async () => {
        setRunning(true);
        setError('');
        try {
            const result = await retestFeedbackPrompt(record.id, record.prompt ?? '');
            setAnswer(result.retestResponse || 'The model returned no response.');
        } catch (cause) {
            setError(errorText(cause, 'The prompt could not be retested.'));
        } finally {
            setRunning(false);
        }
    };

    return (
        <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
                <GlassButton
                    type="button"
                    size="sm"
                    variant="subtle"
                    onClick={() => void run()}
                    disabled={running || !record.prompt}
                    data-testid={`${testIdPrefix}-retest`}
                >
                    {running ? <Loader2 size={14} aria-hidden="true" className="animate-spin" /> : <FlaskConical size={14} aria-hidden="true" />}
                    {running ? 'Retesting…' : answer ? 'Retest again' : 'Retest the prompt'}
                </GlassButton>
                <p className="text-xs text-text-3">
                    Sends the original prompt to the current model configuration. Nothing is saved.
                </p>
            </div>
            {error ? <ReviewNotice tone="danger">{error}</ReviewNotice> : null}
            <div className="grid gap-3 @2xl:grid-cols-2">
                <ReviewTextBlock label="Original response" text={record.aiResponse} empty="No response captured." />
                <div aria-live="polite">
                    {answer !== null ? (
                        <ReviewTextBlock label="Retest response" text={answer} empty="" testId={`${testIdPrefix}-retest-answer`} />
                    ) : (
                        <div>
                            <h4 className="text-xs font-semibold text-text-3">Retest response</h4>
                            <p className="mt-1 rounded-lg border border-dashed border-edge p-3 text-sm text-text-3">
                                {running ? 'Waiting for the model…' : 'Retest the prompt to compare a current answer here.'}
                            </p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
