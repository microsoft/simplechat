// test_v2_conversation_export_logic.ts
// Behavioural checks for the V2 conversation export logic.
//
// Version: 0.261.040
// Implemented in: 0.261.040
//
// The V2 interface has no unit test runner, so this follows test_v2_visual_style_logic.ts: it
// is bundled with the esbuild Vite already brings in and run under node by
// test_v2_conversation_export.py, which skips it when the front-end toolchain is absent.
//
// What it protects, in rough order of importance:
//
//   - The four summary model fields must travel together and must be remapped onto their
//     `summary_` names. Sending a deployment name alone makes the server fall back to a
//     different endpoint silently, with no error and no sign in the exported file.
//   - Summary fields must be cleared when no intro was asked for, so the request cannot
//     describe something other than what the user chose.
//   - A JSON export must not rasterize, because its diagrams stay as markdown source.
//   - The step list must lose exactly the review step when one conversation is exported.
//   - The download name must come from the server's own header when it sends one, so a V2
//     export is named identically to a classic one.

import {
    buildConversationExportRequest,
    defaultPackaging,
    exportSteps,
    needsVisualAssets,
    summaryModelFields,
} from '../application/v2_ui/src/lib/conversationExport';
import {
    conversationExportExtension,
    filenameFromContentDisposition,
} from '../application/v2_ui/src/lib/endpoints';
import type { ModelCatalogEntry } from '../application/v2_ui/src/lib/models';

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail ?? '');
    }
}

/* ---- steps ---- */

const bulkSteps = exportSteps(false).map((step) => step.id);
const singleSteps = exportSteps(true).map((step) => step.id);

check(
    'a bulk export reviews the selection first',
    JSON.stringify(bulkSteps) ===
        JSON.stringify(['select', 'format', 'packaging', 'summary', 'download']),
    bulkSteps,
);
check(
    'a single-conversation export skips only the review step',
    JSON.stringify(singleSteps) ===
        JSON.stringify(['format', 'packaging', 'summary', 'download']),
    singleSteps,
);
check('skipping removes exactly one step', bulkSteps.length - singleSteps.length === 1);

/* ---- packaging default ---- */

check('one conversation defaults to a single file', defaultPackaging(1) === 'single');
check('several conversations default to a zip', defaultPackaging(4) === 'zip');
check('an empty selection still has a valid default', defaultPackaging(0) === 'single');

/* ---- extensions ---- */

check('json is .json', conversationExportExtension('json', 'single') === '.json');
check('markdown is .md', conversationExportExtension('markdown', 'single') === '.md');
check('pdf is .pdf', conversationExportExtension('pdf', 'single') === '.pdf');
check(
    'zip packaging overrides the format extension',
    conversationExportExtension('pdf', 'zip') === '.zip',
);

/* ---- rasterizing ---- */

check('json exports keep their markdown fences', needsVisualAssets('json') === false);
check('markdown exports need pictures', needsVisualAssets('markdown') === true);
check('pdf exports need pictures', needsVisualAssets('pdf') === true);

/* ---- summary model identity ---- */

// A catalog with the same deployment name on two endpoints, which is the case that makes
// sending the deployment name alone ambiguous.
const models: ModelCatalogEntry[] = [
    {
        selection_key: 'personal:me:endpoint-a:gpt-4o',
        deployment_name: 'gpt-4o',
        model_id: 'gpt-4o',
        endpoint_id: 'endpoint-a',
        provider: 'azure_openai',
        display_name: 'GPT-4o (A)',
    },
    {
        selection_key: 'personal:me:endpoint-b:gpt-4o',
        deployment_name: 'gpt-4o',
        model_id: 'gpt-4o',
        endpoint_id: 'endpoint-b',
        provider: 'azure_openai',
        display_name: 'GPT-4o (B)',
    },
];

const secondEndpoint = summaryModelFields(models, 'personal:me:endpoint-b:gpt-4o');
check(
    'the chosen endpoint is carried, not just the deployment name',
    secondEndpoint.summary_model_endpoint_id === 'endpoint-b',
    secondEndpoint,
);
check('the model id is carried', secondEndpoint.summary_model_id === 'gpt-4o', secondEndpoint);
check(
    'the provider is carried',
    secondEndpoint.summary_model_provider === 'azure_openai',
    secondEndpoint,
);
check(
    'the deployment name is carried',
    secondEndpoint.summary_model_deployment === 'gpt-4o',
    secondEndpoint,
);
check(
    'every summary field uses its summary_ name',
    Object.keys(secondEndpoint).every((key) => key.startsWith('summary_model_')),
    Object.keys(secondEndpoint),
);

const unknownModel = summaryModelFields(models, 'no-such-model');
check(
    'an unknown selection nulls every field rather than guessing',
    unknownModel.summary_model_deployment === null &&
        unknownModel.summary_model_endpoint_id === null &&
        unknownModel.summary_model_id === null &&
        unknownModel.summary_model_provider === null,
    unknownModel,
);

/* ---- request assembly ---- */

const withSummary = buildConversationExportRequest({
    conversationIds: ['c1', 'c2'],
    format: 'markdown',
    packaging: 'zip',
    includeSummaryIntro: true,
    models,
    summaryModelKey: 'personal:me:endpoint-a:gpt-4o',
    visualAssets: [{ kind: 'diagram', source: 'graph TD;A-->B;', data_uri: 'data:image/png;base64,AA' }],
});

check('conversation ids are passed through', JSON.stringify(withSummary.conversation_ids) === JSON.stringify(['c1', 'c2']));
check('the format is passed through', withSummary.format === 'markdown');
check('the packaging is passed through', withSummary.packaging === 'zip');
check('the intro flag is passed through', withSummary.include_summary_intro === true);
check(
    'the summary model reaches the request',
    withSummary.summary_model_endpoint_id === 'endpoint-a',
    withSummary,
);
check('visual assets reach the request', withSummary.visual_assets?.length === 1);

const withoutSummary = buildConversationExportRequest({
    conversationIds: ['c1'],
    format: 'json',
    packaging: 'single',
    includeSummaryIntro: false,
    models,
    // Deliberately still set: leaving a stale picker value must not leak into the request.
    summaryModelKey: 'personal:me:endpoint-a:gpt-4o',
});

check(
    'no intro means no summary model is sent',
    withoutSummary.summary_model_deployment === null &&
        withoutSummary.summary_model_endpoint_id === null &&
        withoutSummary.summary_model_id === null &&
        withoutSummary.summary_model_provider === null,
    withoutSummary,
);
check(
    'visual assets default to an empty list rather than undefined',
    Array.isArray(withoutSummary.visual_assets) && withoutSummary.visual_assets.length === 0,
    withoutSummary.visual_assets,
);

/* ---- download naming ---- */

check(
    'a quoted filename is read',
    filenameFromContentDisposition('attachment; filename="conversations_20240101_120000.zip"') ===
        'conversations_20240101_120000.zip',
);
check(
    'an unquoted filename is read',
    filenameFromContentDisposition('attachment; filename=export.md') === 'export.md',
);
check(
    'a UTF-8 filename* is read and decoded',
    filenameFromContentDisposition("attachment; filename*=UTF-8''caf%C3%A9.md") === 'café.md',
);
check('a missing header yields no name', filenameFromContentDisposition(null) === null);
check(
    'a header with no filename yields no name',
    filenameFromContentDisposition('attachment') === null,
);
check(
    'a stray percent does not throw away an already-built download',
    filenameFromContentDisposition('attachment; filename="report 100%.md"') ===
        'report 100%.md',
);

console.log(failures === 0 ? '\nAll checks passed.' : `\n${failures} check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
