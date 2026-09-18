// WorkflowLoopSelectionDetails.tsx
// Display only the public selection capture, never the underlying query or journal.

import type { WorkflowLoopSelection } from '../../lib/workflowEditor';

export function WorkflowLoopSelectionDetails({ selection, frozen = false }: {
    selection?: WorkflowLoopSelection;
    frozen?: boolean;
}) {
    if (!selection || !Object.keys(selection).length) return null;
    const modes: Record<string, string> = {
        all_matches: 'All matches',
        best_n: 'Best N documents',
        saved_output: 'Complete saved collection',
    };
    const rankings: Record<string, string> = {
        qualified_document_identity: 'Qualified document identity',
        max_chunk_score: 'Maximum matched chunk score',
        candidate_round_then_max_chunk_score: 'Candidate round, then maximum chunk score',
    };
    const limited = selection.query_mode === 'best_n' || selection.exhaustive === false;
    return (
        <section aria-label={frozen ? 'Frozen selection details' : 'Preview selection details'}
            className="min-w-0 space-y-2 rounded-lg border border-edge p-3 text-xs text-text-3">
            <p className="font-medium text-text-2">{frozen ? 'Frozen selection method' : 'Advisory selection method'}</p>
            {selection.query_mode ? <p>Selection: {Object.hasOwn(modes, selection.query_mode) ? modes[selection.query_mode] : selection.query_mode}</p> : null}
            {selection.ranking ? <p className="break-words">Ordering / ranking: {Object.hasOwn(rankings, selection.ranking) ? rankings[selection.ranking] : selection.ranking}</p> : null}
            {limited ? <p className="rounded-lg bg-warn-soft p-2 text-warn">
                This is a limited document selection, not exhaustive relevance across the corpus.
                {' '}{selection.query_mode === 'best_n'
                    ? 'Finishing every selected item does not turn Best N into exhaustive search coverage.'
                    : 'These capture details do not certify exhaustive matching coverage.'}
            </p> : selection.exhaustive === true ? <p>
                Exhaustive eligible matches for the captured metadata / keyword query. This does not claim that unindexed content was searched.
            </p> : null}
            {selection.candidate_window !== undefined ? <p>Candidate window: {selection.candidate_window} chunks per round.</p> : null}
            {selection.semantic_rerank_window !== undefined ? <p>Semantic reranking window: {selection.semantic_rerank_window} chunks.</p> : null}
            {selection.candidate_expansion ? <p className="break-words">Candidate expansion: {selection.candidate_expansion === 'exclude_processed_document_ids'
                ? 'Distinct-document backfill excludes previously processed candidate documents.' : selection.candidate_expansion}</p> : null}
            {selection.candidate_expansion_rounds !== undefined ? <p>Reported candidate expansion rounds: {selection.candidate_expansion_rounds}.</p> : null}
            {selection.candidate_limitations?.length ? <div role="note" aria-label="Candidate limitations" className="space-y-1 rounded-lg bg-warn-soft p-2 text-warn">
                <p className="font-medium">Candidate limitations</p>
                <ul className="list-inside list-disc space-y-1">
                    {selection.candidate_limitations.map((notice, index) => <li key={index} className="break-words">{notice}</li>)}
                </ul>
            </div> : null}
            <p>{frozen
                ? 'These capture details belong to this frozen loop instance; later query or administrator changes do not rewrite them.'
                : 'Preview details are advisory. The loop captures and validates its selection again before any body task is admitted.'}</p>
        </section>
    );
}
