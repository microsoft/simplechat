// test_v2_tabular_parity_logic.ts
//
// Runtime test for the V2 tabular parity rules.
// Version: 0.261.056
// Implemented in: 0.261.056
//
// The companion test, test_v2_tabular_parity.py, asserts that the pieces are wired together:
// the client reads the metadata keys the server writes, calls the routes that exist, and
// those routes carry their decorators. Those are source assertions and prove connection, not
// behaviour.
//
// This file executes the behaviour, because every failure here is a silent one:
//
//   - An artifact rejected by the normaliser is a file that exists in storage and has no
//     control anywhere in the interface, which is exactly the bug this work fixes.
//   - A tabular export is written to *both* metadata collections, so a reader that does not
//     de-duplicate shows every export twice.
//   - The download target chooses between a conversation copy and a workspace copy; picking
//     the wrong one 404s, and picking neither renders a card with a dead button.
//   - The run progress bar ratchets. Recomputed naively it runs backwards when a new activity
//     starts, which reads as the run having lost work it has not lost.
//   - Polling that does not stop on a terminal state hammers the runs endpoint forever; one
//     that stops on a *retryable* failure abandons a run the worker would have resumed.
//   - The large-run confirmation must fire on the expensive prompts and stay silent on
//     ordinary ones. A confirmation that appears too often gets clicked through unread.
//
// Run by test_v2_tabular_parity.py, which bundles this with the esbuild Vite already brings
// in and executes it under node, skipping it when the front-end toolchain is absent.

import assert from 'node:assert/strict';
import {
    approvalBlocksDownload,
    artifactDownloadPath,
    artifactFileName,
    artifactOutputFormat,
    artifactStorageNote,
    artifactTitle,
    canCancelRun,
    canResumeRun,
    describeArtifactApproval,
    formatArtifactRowCount,
    formatPreviewValue,
    hasArtifactPreview,
    isCompletedTabularArtifact,
    isMarkdownArtifact,
    isRunArtifactSetComplete,
    normalizeGeneratedArtifact,
    previewTableModel,
    readArtifactApproval,
    readGeneratedArtifacts,
    readRunArtifactSetMembers,
    runProgressPercent,
    runStatusLabel,
    runStatusTone,
    runTypeLabel,
    shouldCollapsePreview,
    shouldPollRun,
    suppressesAssistantText,
    type GeneratedArtifact,
} from '../application/v2_ui/src/lib/generatedArtifacts';
import { buildLaneProgress } from '../application/v2_ui/src/lib/activityLanes';
import { estimateLargeTabularRun } from '../application/v2_ui/src/lib/tabularRunEstimate';
import {
    buildToolResultView,
    isTabularToolResult,
    rowLimitFor,
} from '../application/v2_ui/src/lib/agentCitationRows';
import { parseCsvLine, parseCsvPreview } from '../application/v2_ui/src/lib/csvPreview';

const checks: [string, () => void][] = [];
function check(name: string, fn: () => void) {
    checks.push([name, fn]);
}

/** A normalised artifact, for the readers that require one. */
function artifact(raw: Record<string, unknown>): GeneratedArtifact {
    const normalized = normalizeGeneratedArtifact(raw);
    assert.ok(normalized, 'the fixture should normalise');
    return normalized;
}

/* --------------------------- reading the metadata --------------------------- */

check('an artifact on a chat message is read', () => {
    const found = readGeneratedArtifacts({
        generated_tabular_outputs: [
            { artifact_message_id: 'm1', file_name: 'rows.csv', output_format: 'CSV' },
        ],
    });
    assert.equal(found.length, 1);
    assert.equal(found[0].capability, 'tabular');
    assert.equal(found[0].artifact_message_id, 'm1');
    assert.equal(artifactOutputFormat(found[0]), 'csv');
});

check('an artifact saved to the workspace is read', () => {
    const found = readGeneratedArtifacts({
        generated_analysis_artifacts: [{ document_id: 'd1', file_name: 'summary.md' }],
    });
    assert.equal(found.length, 1);
    assert.equal(found[0].capability, 'analysis');
    assert.equal(found[0].document_id, 'd1');
});

check('an export written to both collections appears once', () => {
    // This is what the server actually does: `_build_generated_analysis_metadata` appends a
    // tabular artifact to the general list *and* the tabular one. Without de-duplication the
    // same export is offered twice, which reads as two different files.
    const shared = { artifact_message_id: 'm1', file_name: 'rows.csv', capability: 'tabular' };
    const found = readGeneratedArtifacts({
        generated_analysis_artifacts: [shared],
        generated_tabular_outputs: [shared],
    });
    assert.equal(found.length, 1);
    assert.equal(found[0].capability, 'tabular');
});

check('an artifact naming nowhere to fetch it from is rejected', () => {
    assert.equal(normalizeGeneratedArtifact({ file_name: 'nothing.csv' }), null);
    assert.equal(normalizeGeneratedArtifact(null), null);
    assert.equal(normalizeGeneratedArtifact('rows.csv'), null);
    assert.deepEqual(readGeneratedArtifacts(undefined), []);
    assert.deepEqual(readGeneratedArtifacts({ generated_tabular_outputs: 'nope' }), []);
});

check('a run still producing its file is kept', () => {
    const found = readGeneratedArtifacts({
        generated_tabular_outputs: [
            { export_run_id: 'r1', background_export: true, file_name: 'rows.csv' },
        ],
    });
    assert.equal(found.length, 1);
    assert.equal(found[0].background_export, true);
    assert.equal(found[0].run_id, 'r1');
});

check('a failed run that replaced the reply is kept even with nothing to download', () => {
    // The turn suppressed its own table in favour of a file that never arrived. Dropping the
    // record would leave a reply that silently lost both.
    const found = readGeneratedArtifacts({
        generated_tabular_outputs: [
            { status: 'failed', suppress_assistant_table_export: true, file_name: 'rows.csv' },
        ],
    });
    assert.equal(found.length, 1);
    assert.equal(found[0].background_export, true);
});

check('a finished run replaces the reply text, a running one does not', () => {
    const running = artifact({
        export_run_id: 'r1',
        background_export: true,
        suppress_assistant_text: true,
    });
    const done = artifact({ artifact_message_id: 'm1', suppress_assistant_text: true });

    // While it runs the holding sentence is still true, so it stays.
    assert.equal(suppressesAssistantText([running]), false);
    assert.equal(suppressesAssistantText([done]), true);
    assert.equal(suppressesAssistantText([]), false);
});

/* ------------------------------ download target ----------------------------- */

check('the conversation copy is preferred over the workspace copy', () => {
    const both = artifact({
        artifact_message_id: 'm1',
        conversation_id: 'c1',
        document_id: 'd1',
    });
    assert.equal(
        artifactDownloadPath(both),
        '/api/chat_artifacts/download?conversation_id=c1&message_id=m1',
    );
});

check('the conversation id falls back to the message being rendered', () => {
    const noConversation = artifact({ artifact_message_id: 'm1' });
    assert.equal(
        artifactDownloadPath(noConversation, 'c9'),
        '/api/chat_artifacts/download?conversation_id=c9&message_id=m1',
    );
});

check('a workspace-only artifact downloads by document id', () => {
    assert.equal(
        artifactDownloadPath(artifact({ document_id: 'd1' })),
        '/api/workspace_documents/download?doc_id=d1',
    );
});

check('an artifact with no target yields no download url', () => {
    const runOnly = artifact({ export_run_id: 'r1', background_export: true });
    assert.equal(artifactDownloadPath(runOnly), '');
});

check('download targets are url-encoded', () => {
    const awkward = artifact({ document_id: 'a b&c' });
    assert.equal(artifactDownloadPath(awkward), '/api/workspace_documents/download?doc_id=a%20b%26c');
});

/* --------------------------------- the card --------------------------------- */

check('the compact layout is used only for finished row-level exports', () => {
    assert.equal(
        isCompletedTabularArtifact(
            artifact({ artifact_message_id: 'm', capability: 'tabular', output_format: 'csv' }),
        ),
        true,
    );
    // Still running, so the progress card owns the layout.
    assert.equal(
        isCompletedTabularArtifact(
            artifact({
                export_run_id: 'r',
                background_export: true,
                capability: 'tabular',
                output_format: 'csv',
            }),
        ),
        false,
    );
    // Prose, not rows.
    assert.equal(
        isCompletedTabularArtifact(
            artifact({ artifact_message_id: 'm', capability: 'analyze', output_format: 'md' }),
        ),
        false,
    );
});

check('long prose previews are collapsed and row previews are not', () => {
    assert.equal(shouldCollapsePreview(artifact({ document_id: 'd', capability: 'analyze' })), true);
    assert.equal(
        shouldCollapsePreview(artifact({ document_id: 'd', capability: 'comparison' })),
        true,
    );
    assert.equal(shouldCollapsePreview(artifact({ document_id: 'd', capability: 'tabular' })), false);
});

check('titles name the capability that produced the file', () => {
    assert.equal(
        artifactTitle(artifact({ document_id: 'd', capability: 'analyze', output_format: 'md' })),
        'Analyze MD artifact',
    );
    assert.equal(
        artifactTitle(artifact({ document_id: 'd', capability: 'comparison', output_format: 'xlsx' })),
        'Comparison XLSX artifact',
    );
    assert.equal(
        artifactTitle(artifact({ document_id: 'd', capability: 'tabular', output_format: 'csv' })),
        'Generated CSV export',
    );
    assert.equal(
        artifactTitle(artifact({ document_id: 'd', artifact_id: 'analysis-summary' })),
        'Analyze Markdown summary',
    );
});

check('markdown is recognised by format or by file name', () => {
    assert.equal(isMarkdownArtifact(artifact({ document_id: 'd', output_format: 'md' })), true);
    assert.equal(
        isMarkdownArtifact(artifact({ document_id: 'd', file_name: 'notes.MARKDOWN' })),
        true,
    );
    assert.equal(isMarkdownArtifact(artifact({ document_id: 'd', output_format: 'csv' })), false);
});

check('the storage note says where the file actually went', () => {
    assert.match(
        artifactStorageNote(artifact({ export_run_id: 'r', background_export: true })),
        /background/i,
    );
    assert.match(
        artifactStorageNote(artifact({ document_id: 'd', storage_scope: 'chat' })),
        /this chat/i,
    );
    assert.match(
        artifactStorageNote(artifact({ document_id: 'd', storage_scope: 'workspace' })),
        /personal workspace/i,
    );
});

check('a missing or nonsense row count renders as nothing', () => {
    assert.equal(formatArtifactRowCount(undefined), '');
    assert.equal(formatArtifactRowCount('not a number'), '');
    assert.equal(formatArtifactRowCount(-1), '');
    assert.equal(formatArtifactRowCount(0), '0');
});

check('a file name is always available for the download control', () => {
    assert.equal(artifactFileName(artifact({ document_id: 'd', file_name: 'rows.csv' })), 'rows.csv');
    assert.equal(
        artifactFileName(artifact({ document_id: 'd', output_format: 'json' })),
        'generated-output.json',
    );
});

/* -------------------------------- previews ---------------------------------- */

check('a preview table takes declared columns first, then any extras', () => {
    const model = previewTableModel(
        [
            { b: 2, a: 1 },
            { a: 3, c: 4 },
        ],
        { columns: ['a', 'b'], maxColumns: 10 },
    );
    assert.ok(model);
    assert.deepEqual(model.columns, ['a', 'b', 'c']);
    assert.equal(model.hiddenColumnCount, 0);
});

check('a preview table reports the columns it had to hide', () => {
    const model = previewTableModel([{ a: 1, b: 2, c: 3, d: 4, e: 5 }], { maxColumns: 2 });
    assert.ok(model);
    assert.deepEqual(model.columns, ['a', 'b']);
    assert.equal(model.hiddenColumnCount, 3);
});

check('rows that are not uniform objects refuse to become a table', () => {
    // The fallback is raw JSON. Forcing these into columns would invent a structure the data
    // does not have.
    assert.equal(previewTableModel(['a', 'b']), null);
    assert.equal(previewTableModel([[1, 2]]), null);
    assert.equal(previewTableModel([]), null);
    assert.equal(previewTableModel(null), null);
    assert.equal(previewTableModel([{}]), null);
});

check('preview cells are stringified and truncated', () => {
    assert.equal(formatPreviewValue(null), '');
    assert.equal(formatPreviewValue(undefined), '');
    assert.equal(formatPreviewValue(12), '12');
    assert.equal(formatPreviewValue(true), 'true');
    assert.equal(formatPreviewValue({ a: 1 }), '{"a":1}');
    assert.equal(formatPreviewValue('abcdef', 4), 'abc…');
    assert.equal(formatPreviewValue('abc', 4), 'abc');
});

check('any of the four preview shapes counts as a preview', () => {
    assert.equal(hasArtifactPreview(artifact({ document_id: 'd', preview_rows: [{ a: 1 }] })), true);
    assert.equal(hasArtifactPreview(artifact({ document_id: 'd', preview_items: [{ a: 1 }] })), true);
    assert.equal(hasArtifactPreview(artifact({ document_id: 'd', preview_lines: ['x'] })), true);
    assert.equal(hasArtifactPreview(artifact({ document_id: 'd', preview_text: 'x' })), true);
    assert.equal(hasArtifactPreview(artifact({ document_id: 'd' })), false);
});

/* ------------------------------- durable runs -------------------------------- */

check("the server's own percentage wins over the batch count", () => {
    assert.equal(runProgressPercent({ progress_percent: 42, completed_batches: 1, batch_count: 4 }), 42);
    assert.equal(runProgressPercent({ completed_batches: 1, batch_count: 4 }), 25);
    assert.equal(runProgressPercent({}), 0);
    assert.equal(runProgressPercent({ progress_percent: 900 }), 100);
    assert.equal(runProgressPercent({ progress_percent: -5 }), 0);
});

check('run status is labelled and toned', () => {
    assert.equal(runStatusLabel({ status: 'running' }), 'Running');
    assert.equal(runStatusLabel({ status: 'completed' }), 'Complete');
    assert.equal(runStatusLabel({ status: 'canceled' }), 'Canceled');
    assert.equal(runStatusLabel({}), 'Queued');
    assert.equal(runStatusLabel({ status: 'running', status_label: 'Rebuilding' }), 'Rebuilding');
    assert.equal(runStatusTone({ status_tone: 'danger' }), 'danger');
    assert.equal(runStatusTone({}), 'info');
});

check('the run type is named so the wait is explicable', () => {
    assert.equal(runTypeLabel({ task_type: 'combined' }), 'Background analysis + export');
    assert.equal(runTypeLabel({ task_type: 'hierarchical_analysis' }), 'Background analysis');
    assert.equal(runTypeLabel({}), 'Background export');
});

check('resume and cancel follow the server, not the client', () => {
    // `can_resume` and `can_cancel` are the server's decision. Inferring them from the status
    // would offer a control the endpoint then rejects with a 409.
    assert.equal(canResumeRun({ background_export: true, can_resume: true }), true);
    assert.equal(canResumeRun({ background_export: true }), false);
    assert.equal(canResumeRun({ can_resume: true }), false);
    assert.equal(canCancelRun({ background_export: true, can_cancel: true }), true);
    assert.equal(canCancelRun({ background_export: true }), false);
});

check('polling stops on a terminal state and continues on a retryable one', () => {
    assert.equal(shouldPollRun({ background_export: true, status: 'running' }), true);
    assert.equal(shouldPollRun({ background_export: true, status: 'queued' }), true);
    assert.equal(shouldPollRun({ background_export: true, status: 'completed' }), false);
    assert.equal(shouldPollRun({ background_export: true, status: 'canceled' }), false);
    assert.equal(shouldPollRun({ background_export: true, status: 'failed' }), false);
    // The worker will pick this one up again by itself.
    assert.equal(
        shouldPollRun({ background_export: true, status: 'failed', retryable_failure: true }),
        true,
    );
    assert.equal(shouldPollRun({ status: 'running' }), false);
});

check('a completed run is only finished once its artifact set is valid', () => {
    assert.equal(isRunArtifactSetComplete({ status: 'completed' }), true);
    assert.equal(isRunArtifactSetComplete({ status: 'running' }), false);
    assert.equal(
        isRunArtifactSetComplete({
            status: 'completed',
            artifact_set: { lifecycle_state: 'publishing' },
        }),
        false,
    );
    assert.equal(
        isRunArtifactSetComplete({
            status: 'completed',
            artifact_set: { lifecycle_state: 'completed', validation_state: 'rolled_back' },
        }),
        false,
    );
});

check('a finished run yields downloadable members that inherit the run context', () => {
    const source = artifact({ export_run_id: 'r1', background_export: true, capability: 'tabular' });
    const members = readRunArtifactSetMembers(
        {
            run_id: 'r1',
            status: 'completed',
            conversation_id: 'c1',
            artifact_set: { lifecycle_state: 'completed' },
            // The real payload shape. `artifact_set` is a summary and carries no member list.
            generated_artifacts: [{ artifact_message_id: 'm1', file_name: 'rows.csv' }],
        },
        source,
    );
    assert.equal(members.length, 1);
    assert.equal(members[0].background_export, false);
    assert.equal(members[0].capability, 'tabular');
    assert.equal(
        artifactDownloadPath(members[0]),
        '/api/chat_artifacts/download?conversation_id=c1&message_id=m1',
    );
});

check('a combined run yields every file it produced, not just one', () => {
    // A combined run writes a Markdown analysis *and* a structured export. Reading members
    // from `artifact_set.members` — which the server never sends — silently reduced this to
    // a single card and dropped the other file entirely.
    const source = artifact({ export_run_id: 'r1', background_export: true, capability: 'tabular' });
    const members = readRunArtifactSetMembers(
        {
            run_id: 'r1',
            status: 'completed',
            conversation_id: 'c1',
            artifact_set: { lifecycle_state: 'completed', primary_artifact_id: 'analysis-summary' },
            generated_artifacts: [
                { artifact_message_id: 'm2', file_name: 'rows.csv', output_format: 'csv' },
                {
                    artifact_message_id: 'm1',
                    artifact_id: 'analysis-summary',
                    file_name: 'summary.md',
                    output_format: 'md',
                },
            ],
        },
        source,
    );
    assert.equal(members.length, 2);
    // The summary is what the reply is about, so it leads.
    assert.equal(members[0].artifact_message_id, 'm1');
    assert.equal(members[1].artifact_message_id, 'm2');
});

check('the singular and legacy member shapes are still read', () => {
    const source = artifact({ export_run_id: 'r1', background_export: true });
    const singular = readRunArtifactSetMembers(
        {
            run_id: 'r1',
            status: 'completed',
            conversation_id: 'c1',
            generated_artifact: { artifact_message_id: 'm1', file_name: 'rows.csv' },
        },
        source,
    );
    assert.equal(singular.length, 1);
    assert.equal(singular[0].artifact_message_id, 'm1');

    const legacy = readRunArtifactSetMembers(
        {
            run_id: 'r1',
            status: 'completed',
            conversation_id: 'c1',
            generated_tabular_outputs: [{ artifact_message_id: 'm9', file_name: 'rows.csv' }],
        },
        source,
    );
    assert.equal(legacy.length, 1);
    assert.equal(legacy[0].artifact_message_id, 'm9');
});

check('a run member does not re-advertise the run as its own artifact', () => {
    // The run payload is spread onto each member. Carrying its collections through would
    // make every member look like it had produced the whole set again.
    const source = artifact({ export_run_id: 'r1', background_export: true });
    const members = readRunArtifactSetMembers(
        {
            run_id: 'r1',
            status: 'completed',
            conversation_id: 'c1',
            generated_artifacts: [{ artifact_message_id: 'm1', file_name: 'rows.csv' }],
        },
        source,
    );
    assert.equal(members.length, 1);
    assert.deepEqual(readGeneratedArtifacts(members[0]), []);
});

check('a completed run with no member list still promotes its own artifact', () => {
    // Otherwise the card sits at a full progress bar forever with no download.
    const source = artifact({
        export_run_id: 'r1',
        background_export: true,
        artifact_message_id: 'm1',
        conversation_id: 'c1',
    });
    const members = readRunArtifactSetMembers({ run_id: 'r1', status: 'completed' }, source);
    assert.equal(members.length, 1);
    assert.equal(members[0].background_export, false);
    assert.equal(members[0].artifact_message_id, 'm1');
});

check('an unfinished run yields no members', () => {
    const source = artifact({ export_run_id: 'r1', background_export: true });
    assert.deepEqual(readRunArtifactSetMembers({ run_id: 'r1', status: 'running' }, source), []);
});

/* ------------------------------ progress lanes ------------------------------- */

check('ordinary reasoning steps do not become a progress card', () => {
    assert.equal(buildLaneProgress([{ step_type: 'generation', content: 'Thinking' }]), null);
    assert.equal(buildLaneProgress([]), null);
    assert.equal(buildLaneProgress(undefined), null);
});

check('a tabular step opens the tabular lane', () => {
    const progress = buildLaneProgress([
        { step_type: 'tabular_analysis', content: 'Starting tabular analysis across 2 file(s)' },
    ]);
    assert.ok(progress);
    assert.equal(progress.lane.key, 'tabular');
    assert.equal(progress.lane.title, 'Tabular analysis');
});

check('a lane is also opened by the activity payload alone', () => {
    // The lane is keyed off the payload rather than the step type, which is what lets a new
    // kind of staged work join without touching the renderer.
    for (const activity of [
        { kind: 'tabular_tool_invocation' },
        { lane_key: 'tabular' },
        { plugin_name: 'TabularProcessingPlugin' },
    ]) {
        const progress = buildLaneProgress([{ step_type: 'other', content: 'x', activity }]);
        assert.ok(progress, `${JSON.stringify(activity)} should open a lane`);
        assert.equal(progress.lane.key, 'tabular');
    }
});

check('activities are counted by their status', () => {
    const progress = buildLaneProgress([
        {
            step_type: 'tabular_analysis',
            content: 'a',
            activity: { activity_key: 'a', kind: 'tabular_tool_invocation', status: 'completed' },
        },
        {
            step_type: 'tabular_analysis',
            content: 'b',
            activity: { activity_key: 'b', kind: 'tabular_tool_invocation', status: 'running' },
        },
        {
            step_type: 'tabular_analysis',
            content: 'c',
            activity: { activity_key: 'c', kind: 'tabular_tool_invocation', status: 'failed' },
        },
    ]);
    assert.ok(progress);
    assert.match(progress.summary, /2\/3 tool calls/);
    assert.match(progress.summary, /1 running/);
    assert.match(progress.summary, /1 failed/);
    assert.equal(progress.failedCount, 1);
    assert.equal(progress.completed, false);
});

check('an activity reported twice is one activity, not two', () => {
    // Every tool call is emitted at least twice — running, then completed — keyed by
    // `activity_key`. Counting frames instead of activities would double every total.
    const progress = buildLaneProgress([
        {
            step_type: 'tabular_analysis',
            content: 'a',
            activity: { activity_key: 'a', kind: 'tabular_tool_invocation', status: 'running' },
        },
        {
            step_type: 'tabular_analysis',
            content: 'a done',
            activity: { activity_key: 'a', kind: 'tabular_tool_invocation', status: 'completed' },
        },
    ]);
    assert.ok(progress);
    assert.match(progress.summary, /1\/1 tool call/);
});

check('the progress bar never runs backwards', () => {
    // Two of two finished reads as 80%. A third activity starting would compute as 50%, and
    // a bar that falls looks like lost work.
    const finishedTwo = [
        {
            step_type: 'tabular_analysis',
            content: 'a',
            activity: { activity_key: 'a', kind: 'tabular_tool_invocation', status: 'completed' },
        },
        {
            step_type: 'tabular_analysis',
            content: 'b',
            activity: { activity_key: 'b', kind: 'tabular_tool_invocation', status: 'completed' },
        },
    ];
    const before = buildLaneProgress(finishedTwo);
    const after = buildLaneProgress([
        ...finishedTwo,
        {
            step_type: 'tabular_analysis',
            content: 'c',
            activity: { activity_key: 'c', kind: 'tabular_tool_invocation', status: 'running' },
        },
    ]);
    assert.ok(before && after);
    assert.ok(after.percent >= 80, `expected the bar to hold at >= 80, saw ${after.percent}`);
});

check('an unfinished lane never shows a full bar', () => {
    const progress = buildLaneProgress([
        {
            step_type: 'tabular_analysis',
            content: 'a',
            activity: { activity_key: 'a', kind: 'tabular_tool_invocation', status: 'running' },
        },
    ]);
    assert.ok(progress);
    assert.equal(progress.completed, false);
    assert.ok(progress.percent < 100, `an unfinished run showed ${progress.percent}%`);
});

check('post-processing changes the wording and completes the lane', () => {
    const progress = buildLaneProgress([
        {
            step_type: 'tabular_analysis',
            content: 'Writing workbook',
            activity: {
                activity_key: 'p',
                kind: 'tabular_post_processing',
                status: 'completed',
            },
        },
    ]);
    assert.ok(progress);
    assert.equal(progress.completed, true);
    assert.equal(progress.percent, 100);
    assert.match(progress.summary, /export ready/i);
    // Non-tool work is counted in steps, not tool calls.
    assert.match(progress.summary, /step/);
});

check('a tabular lane is not complete merely because its tool calls have settled', () => {
    // Every invocation is reported running and then completed, so between one finishing and
    // the next starting there are momentarily no running activities. Treating that as done
    // announced "Tabular analysis complete" at 100% mid-run, and the bar then fell back.
    const progress = buildLaneProgress([
        {
            step_type: 'tabular_analysis',
            content: 'a',
            activity: { activity_key: 'a', kind: 'tabular_tool_invocation', status: 'running' },
        },
        {
            step_type: 'tabular_analysis',
            content: 'a done',
            activity: { activity_key: 'a', kind: 'tabular_tool_invocation', status: 'completed' },
        },
    ]);
    assert.ok(progress);
    assert.equal(progress.completed, false);
    assert.ok(progress.percent < 100, `showed ${progress.percent}% between tool calls`);
});

check('the agent lane still completes when its tools settle', () => {
    // The agent lane declares no post-processing, so the plain rule applies to it.
    const progress = buildLaneProgress([
        { step_type: 'agent_tool_call', content: 'Sending to agent' },
        {
            step_type: 'agent_tool_call',
            content: 'a',
            activity: { activity_key: 'a', status: 'completed' },
        },
    ]);
    assert.ok(progress);
    assert.equal(progress.lane.key, 'agent');
    assert.equal(progress.completed, true);
});

check('a tabular run completes once the reply is generated', () => {
    const progress = buildLaneProgress([
        {
            step_type: 'tabular_analysis',
            content: 'a',
            activity: { activity_key: 'a', kind: 'tabular_tool_invocation', status: 'completed' },
        },
        { step_type: 'generation', content: 'Agent responded' },
    ]);
    assert.ok(progress);
    assert.equal(progress.completed, true);
    assert.equal(progress.percent, 100);
});

/* -------------------------------- approval ---------------------------------- */

check('an ungated artifact has no approval state', () => {
    assert.equal(readArtifactApproval(artifact({ document_id: 'd' })), null);
    assert.equal(readArtifactApproval(artifact({ document_id: 'd', approval: {} })), null);
    assert.equal(approvalBlocksDownload(artifact({ document_id: 'd' })), false);
});

check('a staged file is withheld from everyone, including whoever asked for it', () => {
    // The server enforces this and returns 403, so leaving the download control visible
    // renders a button that cannot work and says nothing about why.
    const pending = artifact({
        artifact_message_id: 'm1',
        conversation_id: 'c1',
        approval: { state: 'pending_approval', viewer_is_requester: true },
    });
    assert.equal(approvalBlocksDownload(pending), true);
    const state = readArtifactApproval(pending);
    assert.ok(state);
    assert.equal(state.isPending, true);
    assert.match(describeArtifactApproval(state), /waiting for the conversation owner/i);
});

check('an approver is told what they are approving', () => {
    const state = readArtifactApproval(
        artifact({
            artifact_message_id: 'm1',
            approval: {
                state: 'pending_approval',
                viewer_can_approve: true,
                requested_by_name: 'Ada',
            },
        }),
    );
    assert.ok(state);
    assert.equal(state.viewerCanApprove, true);
    assert.match(describeArtifactApproval(state), /^Ada generated this file/);
});

check('a denied or expired file explains itself and stays withheld', () => {
    const denied = artifact({
        artifact_message_id: 'm1',
        approval: { state: 'denied', resolved_by_name: 'Grace' },
    });
    assert.equal(approvalBlocksDownload(denied), true);
    assert.match(describeArtifactApproval(readArtifactApproval(denied)!), /Grace declined/);

    const expired = artifact({ artifact_message_id: 'm1', approval: { state: 'auto_denied' } });
    assert.equal(approvalBlocksDownload(expired), true);
    assert.match(describeArtifactApproval(readArtifactApproval(expired)!), /expired/i);
});

check('an approved file is downloadable again', () => {
    const approved = artifact({
        artifact_message_id: 'm1',
        conversation_id: 'c1',
        approval: { state: 'approved', resolved_by_name: 'Grace' },
    });
    assert.equal(approvalBlocksDownload(approved), false);
    assert.match(describeArtifactApproval(readArtifactApproval(approved)!), /Approved by Grace/);
    assert.notEqual(artifactDownloadPath(approved), '');
});

check('the running activity is named as the current step', () => {
    const progress = buildLaneProgress(
        [
            {
                step_type: 'tabular_analysis',
                content: 'x',
                activity: {
                    activity_key: 'a',
                    kind: 'tabular_tool_invocation',
                    status: 'running',
                    title: 'query_workbook',
                },
            },
        ],
        { live: true },
    );
    assert.ok(progress);
    assert.equal(progress.currentStep, 'Current tabular step: query_workbook');
});

check('a tabular run that dispatched an agent is still reported as tabular', () => {
    // A tabular turn opens with the agent hand-off sentence. Latching onto the agent lane
    // would label a workbook run "Agent progress".
    const progress = buildLaneProgress([
        { step_type: 'agent_tool_call', content: 'Sending to agent' },
        { step_type: 'tabular_analysis', content: 'Starting tabular analysis' },
    ]);
    assert.ok(progress);
    assert.equal(progress.lane.key, 'tabular');
});

/* --------------------------- large-run confirmation -------------------------- */

check('an exhaustive export over the threshold asks first', () => {
    const estimate = estimateLargeTabularRun(
        'Generate a CSV with one row per record for all 4000 rows',
    );
    assert.equal(estimate.shouldConfirm, true);
    assert.equal(estimate.estimatedRows, 4000);
    assert.equal(estimate.estimatedBatches, 80);
});

check('ordinary questions are never interrupted', () => {
    // Each of these is missing exactly one of the three conditions.
    const quiet = [
        'What is in this spreadsheet?',
        'Summarise all rows in this workbook',
        'Generate a CSV of the top 10 rows',
        'Export every row',
        '',
    ];
    for (const prompt of quiet) {
        assert.equal(
            estimateLargeTabularRun(prompt).shouldConfirm,
            false,
            `should not have prompted for: ${prompt}`,
        );
    }
});

check('a small exhaustive export is under the threshold', () => {
    const estimate = estimateLargeTabularRun('Create a CSV with one row per 100 records');
    assert.equal(estimate.estimatedRows, 100);
    assert.equal(estimate.shouldConfirm, false);
});

check('the batch threshold catches a run with small batches', () => {
    // 600 rows is over the row threshold anyway; the point is that a tiny batch size makes
    // the batch count the binding constraint.
    const estimate = estimateLargeTabularRun('Export a CSV for every row of these 600 rows', {
        tabular_generated_output_max_batch_rows: 1,
        tabular_durable_run_confirmation_threshold_rows: 100000,
        tabular_durable_run_confirmation_threshold_batches: 75,
    });
    assert.equal(estimate.estimatedBatches, 600);
    assert.equal(estimate.shouldConfirm, true);
});

check('thousands separators in the prompt are understood', () => {
    const estimate = estimateLargeTabularRun('Export a CSV for each row of these 12,500 records');
    assert.equal(estimate.estimatedRows, 12500);
    assert.equal(estimate.shouldConfirm, true);
});

check('an administrator can turn the confirmation off', () => {
    const estimate = estimateLargeTabularRun(
        'Generate a CSV with one row per record for all 4000 rows',
        { enable_tabular_durable_run_confirmation: false },
    );
    assert.equal(estimate.shouldConfirm, false);
});

check('an unwritten setting still confirms', () => {
    // A missing key means the setting has never been saved, not that it is off.
    const estimate = estimateLargeTabularRun(
        'Generate a CSV with one row per record for all 4000 rows',
        {},
    );
    assert.equal(estimate.shouldConfirm, true);
    assert.equal(estimate.rowThreshold, 500);
    assert.equal(estimate.batchThreshold, 75);
    assert.equal(estimate.maxBatchRows, 50);
});

/* --------------------------- tabular tool results ---------------------------- */

check('a tabular tool result is recognised by shape, not by tool name', () => {
    assert.equal(isTabularToolResult({ data: [], total_matches: 0 }), true);
    assert.equal(isTabularToolResult({ data: [], returned_rows: 0 }), true);
    assert.equal(isTabularToolResult({ data: [], filename: 'a.xlsx' }), true);
    // `data` alone is not a table; plenty of results carry an unrelated one.
    assert.equal(isTabularToolResult({ data: [] }), false);
    assert.equal(isTabularToolResult({ total_matches: 3 }), false);
    assert.equal(isTabularToolResult(null), false);
    assert.equal(isTabularToolResult([1, 2]), false);
});

check('row bands cap what is rendered', () => {
    assert.equal(rowLimitFor('preview', 1000), 3);
    assert.equal(rowLimitFor('expanded25', 1000), 25);
    assert.equal(rowLimitFor('all', 1000), 1000);
    // A band never invents rows that are not there.
    assert.equal(rowLimitFor('expanded25', 2), 2);
});

check('a large tabular result is truncated and says so', () => {
    const rows = Array.from({ length: 400 }, (_, index) => ({ id: index }));
    const view = buildToolResultView({ data: rows, total_matches: 4000, returned_rows: 400 }, 'preview');
    const parsed = JSON.parse(view.resultText) as Record<string, unknown>;

    assert.equal((parsed.data as unknown[]).length, 3);
    assert.equal(parsed.data_rows_limited, true);
    assert.equal(parsed.displayed_rows, 3);
    // The counts the truncation would otherwise hide.
    assert.match(view.summaryText, /total_matches: 4000/);
    assert.match(view.summaryText, /returned_rows: 400/);
    assert.match(view.summaryText, /showing 3 rows/);
    assert.deepEqual(
        view.controls.map((control) => control.mode),
        ['expanded25', 'all'],
    );
});

check('a short tabular result offers nothing to expand', () => {
    const view = buildToolResultView({ data: [{ id: 1 }], total_matches: 1 }, 'preview');
    assert.deepEqual(view.controls, []);
    assert.match(view.summaryText, /showing 1 row$/);
});

check('a non-tabular result is left alone', () => {
    const view = buildToolResultView({ answer: 42 }, 'preview');
    assert.equal(view.summaryText, '');
    assert.deepEqual(view.controls, []);
    assert.equal(JSON.parse(view.resultText).answer, 42);
    assert.equal(buildToolResultView('plain text', 'preview').resultText, 'plain text');
    assert.equal(buildToolResultView(undefined, 'preview').resultText, '');
});

/* ------------------------------- csv previews -------------------------------- */

check('quoted csv fields survive commas and escaped quotes', () => {
    assert.deepEqual(parseCsvLine('a,b,c'), ['a', 'b', 'c']);
    assert.deepEqual(parseCsvLine('"a,b",c'), ['a,b', 'c']);
    assert.deepEqual(parseCsvLine('"say ""hi""",c'), ['say "hi"', 'c']);
    assert.deepEqual(parseCsvLine(''), ['']);
});

check('a csv preview is bounded and pads short rows', () => {
    const preview = parseCsvPreview('a,b\n1,2\n3\n', 10);
    assert.ok(preview);
    assert.deepEqual(preview.columns, ['a', 'b']);
    // A trailing empty cell is far likelier than a malformed file, so the row is kept.
    assert.deepEqual(preview.rows, [
        ['1', '2'],
        ['3', ''],
    ]);
    assert.equal(preview.hiddenRowCount, 0);
});

check('a csv preview reports the rows it withheld', () => {
    const body = Array.from({ length: 50 }, (_, index) => String(index)).join('\n');
    const preview = parseCsvPreview(`id\n${body}`, 10);
    assert.ok(preview);
    assert.equal(preview.rows.length, 10);
    assert.equal(preview.hiddenRowCount, 40);
});

check('empty csv content yields no table', () => {
    assert.equal(parseCsvPreview(''), null);
    assert.equal(parseCsvPreview('   \n  '), null);
});

/* ----------------------------------- runner ---------------------------------- */

let passed = 0;
let failed = 0;

for (const [name, fn] of checks) {
    try {
        fn();
        console.log(`  ok  ${name}`);
        passed += 1;
    } catch (error) {
        console.log(`FAIL  ${name}`);
        console.log(`      ${(error as Error).message}`);
        failed += 1;
    }
}

console.log(
    failed === 0
        ? `\nAll ${passed} checks passed.`
        : `\n${failed} of ${passed + failed} check(s) failed.`,
);
process.exit(failed > 0 ? 1 : 0);
