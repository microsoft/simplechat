// test_v2_visual_style_logic.ts
// Behavioural checks for the V2 diagram and chart colour logic.
//
// Version: 0.261.033
// Implemented in: 0.261.033
//
// The V2 interface has no unit test runner, and adding one would pull in a test framework for
// a single file. This is bundled with the esbuild that Vite already brings in and run under
// node by test_v2_visual_style_controls.py, which skips it when the front-end toolchain has
// not been installed.
//
// What it protects, in rough order of importance:
//
//   - A block nobody has recoloured must produce byte-identical Chart.js configuration to
//     before this feature existed. Everything else here is cosmetic; that one is a promise
//     about existing conversations.
//   - Recolouring one series must not touch its neighbours, which is the behaviour that makes
//     per-block styling worth having.
//   - Fence ordinals must be derived from the message, since they are what a saved colour is
//     filed under and a wrong one applies someone's colours to the wrong diagram.
//   - Every value that reaches a style attribute or mermaid's configuration must be a plain
//     hex colour.
import { markPendingFences } from '../application/v2_ui/src/lib/richBlocks';
import {
    readFenceLanguage,
    readRichBlockIndex,
    rehypeRichBlockIndex,
    richFenceKind,
} from '../application/v2_ui/src/lib/rehypeRichBlockIndex';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import remarkRehype from 'remark-rehype';
import { visit } from 'unist-util-visit';
import type { Element, Root } from 'hast';
import {
    fingerprintSource,
    hexToRgba,
    mermaidThemeVariables,
    mixHex,
    normalizeHexColor,
    readableTextColor,
    resolveVisualStyle,
    sanitizeVisualStyle,
    seriesColor,
    visualStyleSignature,
    THEME_BACKGROUND,
    type VisualStyle,
} from '../application/v2_ui/src/lib/visualPalettes';
import { buildChartConfig, chartColorTargets, parseInlineChart } from '../application/v2_ui/src/lib/inlineChartSpec';

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail ?? '');
    }
}

/* ---- block numbering ---- */

interface NumberedBlock {
    kind: string;
    index: number | null;
    firstLine: string;
}

/**
 * Number the rich blocks in a message through the exact pipeline AssistantMarkdown uses.
 *
 * Running the real remark/rehype chain rather than a stand-in is the point: the bug this
 * replaced was that a hand-written scanner disagreed with the parser about what counts as a
 * fenced code block, and only the parser's answer matters.
 */
function numberBlocks(markdown: string): NumberedBlock[] {
    const tree = unified()
        .use(remarkParse)
        .use(remarkGfm)
        .use(remarkBreaks)
        .use(remarkRehype)
        .runSync(
            unified().use(remarkParse).use(remarkGfm).use(remarkBreaks).parse(markdown),
        ) as Root;

    rehypeRichBlockIndex()(tree);

    const blocks: NumberedBlock[] = [];
    visit(tree, 'element', (node: Element) => {
        const kind = richFenceKind(node);
        if (kind === null) {
            return;
        }
        const text = node.children
            .map((child) => (child.type === 'text' ? child.value : ''))
            .join('');
        blocks.push({
            kind,
            index: readRichBlockIndex(node),
            firstLine: text.trim().split('\n', 1)[0] ?? '',
        });
    });
    return blocks;
}

const message = [
    'Intro text',
    '',
    '```mermaid',
    'graph TD; A-->B;',
    '```',
    '',
    'Some prose.',
    '',
    '```simplechart',
    '{"kind":"bar"}',
    '```',
    '',
    '```mermaid',
    'graph TD; C-->D;',
    '```',
    '',
    '```python',
    'print(1)',
    '```',
].join('\n');

const blocks = numberBlocks(message);
check('finds three rich blocks', blocks.length === 3, blocks);
check(
    'mermaid ordinals are 0 and 1',
    blocks.filter((b) => b.kind === 'mermaid').map((b) => b.index).join(',') === '0,1',
    blocks,
);
check('chart ordinal is 0', blocks.find((b) => b.kind === 'simplechart')?.index === 0);
check('ordinals follow document order', blocks[0].firstLine === 'graph TD; A-->B;' && blocks[2].firstLine === 'graph TD; C-->D;', blocks);
check('an ordinary fence is not numbered', blocks.every((b) => b.kind !== 'python'));

check('tilde fences are recognised', numberBlocks('~~~mermaid\ngraph TD; A-->B;\n~~~').length === 1);

// Two diagrams with identical source must still be numbered separately: a scheme that
// identified a block by its content would give them the same slot.
const duplicates = numberBlocks(
    '```mermaid\ngraph TD; A-->B;\n```\n\n```mermaid\ngraph TD; A-->B;\n```',
);
check('identical diagrams get distinct ordinals', duplicates.map((b) => b.index).join(',') === '0,1', duplicates);

// The two containers a text scanner got wrong. A block it failed to find fell back to zero and
// overwrote the real block zero's saved colours.
const indented = numberBlocks(
    [
        '- outer',
        '  - inner',
        '',
        '    ```mermaid',
        '    graph TD; X-->Y;',
        '    ```',
        '',
        '```mermaid',
        'graph TD; TOP-->LEVEL;',
        '```',
    ].join('\n'),
);
check('a fence indented inside a nested list is numbered', indented.length === 2, indented);
check('deeply indented fence ordinals are distinct', indented.map((b) => b.index).join(',') === '0,1', indented);

const quoted = numberBlocks(
    ['> ```mermaid', '> graph TD; Q-->R;', '> ```', '', '```mermaid', 'graph TD; TOP-->LEVEL;', '```'].join('\n'),
);
check('a fence inside a blockquote is numbered', quoted.length === 2, quoted);
check('blockquote fence ordinals are distinct', quoted.map((b) => b.index).join(',') === '0,1', quoted);

const streaming = markPendingFences('text\n\n```mermaid\ngraph TD; A-->B;');
const pending = numberBlocks(streaming);
check('a still-streaming fence is numbered as its eventual kind', pending.length === 1 && pending[0].kind === 'mermaid', pending);

const mixedStreaming = markPendingFences(
    '```mermaid\ngraph TD; A-->B;\n```\n\n```mermaid\ngraph TD; C-->',
);
check(
    'numbering does not shift when a fence completes',
    numberBlocks(mixedStreaming).map((b) => b.index).join(',') === '0,1',
    numberBlocks(mixedStreaming),
);

check('language is read from the class', readFenceLanguage('language-Mermaid hljs') === 'mermaid');
check('a block with no index reads as null', readRichBlockIndex(undefined) === null);

/* ---- colours ---- */

check('short hex expands', normalizeHexColor('#ABC') === '#aabbcc');
check('bad hex falls back', normalizeHexColor('url(x)', '#123456') === '#123456');
check('rgba conversion', hexToRgba('#1c6ea4') === 'rgba(28, 110, 164, 0.18)', hexToRgba('#1c6ea4'));
check('mix midpoint', mixHex('#000000', '#ffffff', 0.5) === '#808080', mixHex('#000000', '#ffffff', 0.5));
check('dark background gets light text', readableTextColor('#101728') === '#f8fafc');
check('light background gets dark text', readableTextColor('#ffffff') === '#111827');

const sanitized = sanitizeVisualStyle({
    palette: 'vivid',
    background: '#FFEEDD',
    colors: { '0': '#123456', '99': '#000000', bad: '#111111', '1': 'nope' },
});
check('palette accepted', sanitized?.palette === 'vivid');
check('background lowercased', sanitized?.background === '#ffeedd');
check('valid colour kept', sanitized?.colors['0'] === '#123456');
check('out-of-range colour dropped', sanitized?.colors['99'] === undefined);
check('non-numeric key dropped', sanitized?.colors.bad === undefined);
check('invalid colour dropped', sanitized?.colors['1'] === undefined, sanitized?.colors);
check('unknown palette falls back', sanitizeVisualStyle({ palette: 'evil' })?.palette === 'default');
check('non-object rejected', sanitizeVisualStyle('nope') === null);

const userDefault: VisualStyle = { palette: 'calm', background: THEME_BACKGROUND, colors: {} };
const override: VisualStyle = { palette: 'warm', background: '#000000', colors: {} };
check('override wins', resolveVisualStyle(userDefault, override).palette === 'warm');
check('user default used with no override', resolveVisualStyle(userDefault, null).palette === 'calm');
check('built-in used with neither', resolveVisualStyle(null, null).palette === 'default');

check('series colour from palette', seriesColor({ palette: 'vivid', background: THEME_BACKGROUND, colors: {} }, 0) === '#dc2626');
check('series colour override wins', seriesColor({ palette: 'vivid', background: THEME_BACKGROUND, colors: { '0': '#abcdef' } }, 0) === '#abcdef');
check('series colour wraps', seriesColor({ palette: 'vivid', background: THEME_BACKGROUND, colors: {} }, 8) === '#dc2626');

check('fingerprint is stable', fingerprintSource('graph TD; A-->B;') === fingerprintSource('graph TD; A-->B;\n'));
check('fingerprint differs on change', fingerprintSource('graph TD; A-->B;') !== fingerprintSource('graph TD; A-->C;'));

const signatureA = visualStyleSignature({ palette: 'warm', background: THEME_BACKGROUND, colors: { '1': '#111111' } }, '#ffffff');
const signatureB = visualStyleSignature({ palette: 'warm', background: THEME_BACKGROUND, colors: { '1': '#111111' } }, '#ffffff');
const signatureC = visualStyleSignature({ palette: 'warm', background: THEME_BACKGROUND, colors: { '1': '#222222' } }, '#ffffff');
check('signature stable', signatureA === signatureB);
check('signature changes with colours', signatureA !== signatureC);

// A block left alone and a block explicitly set to the colour the theme happens to be showing
// resolve to the same background, but are drawn by different means: mermaid's stock theme
// versus 'base' plus theme variables. A key that could not tell them apart let one be rendered
// with the other's configuration, and made toggling between them a visual no-op.
const untouched: VisualStyle = { palette: 'default', background: THEME_BACKGROUND, colors: {} };
const explicitlyWhite: VisualStyle = { palette: 'default', background: '#ffffff', colors: {} };
check(
    'untouched and explicitly-matching styles have different signatures',
    visualStyleSignature(untouched, '#ffffff') !== visualStyleSignature(explicitlyWhite, '#ffffff'),
    [visualStyleSignature(untouched, '#ffffff'), visualStyleSignature(explicitlyWhite, '#ffffff')],
);

/* ---- mermaid theme variables ---- */

const vars = mermaidThemeVariables({ palette: 'vivid', background: '#101728', colors: {} }, '#101728');
check('background passed through', vars.background === '#101728');
check('every variable is a hex colour', Object.values(vars).every((value) => /^#[0-9a-f]{6}$/.test(value)), vars);
check('border is the palette colour', vars.primaryBorderColor === '#dc2626', vars.primaryBorderColor);
check('fill is tinted toward the background', vars.primaryColor !== '#dc2626' && vars.primaryColor !== '#101728', vars.primaryColor);
check('text readable on dark background', vars.textColor === '#f8fafc');

/* ---- chart config ---- */

const chartPayload = JSON.stringify({
    kind: 'bar',
    title: 'Fruit',
    data: {
        labels: ['A', 'B'],
        datasets: [
            { label: 'One', data: [1, 2] },
            { label: 'Two', data: [3, 4] },
        ],
    },
});
const spec = parseInlineChart(chartPayload);
check('chart parses', spec !== null);

const themeColors = { text: '#475569', grid: 'rgba(0,0,0,0.1)' };
const defaultStyle: VisualStyle = { palette: 'default', background: THEME_BACKGROUND, colors: {} };
const plain = buildChartConfig(spec!, themeColors);
const withDefault = buildChartConfig(spec!, themeColors, defaultStyle, null);
check('default style changes nothing', JSON.stringify(plain) === JSON.stringify(withDefault));
check('no background plugin by default', (plain as Record<string, unknown>).plugins === undefined);

const styled = buildChartConfig(
    spec!,
    themeColors,
    { palette: 'vivid', background: '#ffffff', colors: {} },
    '#ffffff',
);
const styledDatasets = (styled.data as { datasets: { borderColor: string }[] }).datasets;
check('palette applied to series 0', styledDatasets[0].borderColor === '#dc2626', styledDatasets[0].borderColor);
check('palette applied to series 1', styledDatasets[1].borderColor === '#ea580c', styledDatasets[1].borderColor);
check('background plugin added', Array.isArray((styled as Record<string, unknown>).plugins));
check('axis text follows background', ((styled.options as Record<string, unknown>).color) === '#111827');

const singleOverride = buildChartConfig(
    spec!,
    themeColors,
    { palette: 'default', background: THEME_BACKGROUND, colors: { '1': '#abcdef' } },
    null,
);
const overrideDatasets = (singleOverride.data as { datasets: { borderColor: string }[] }).datasets;
check(
    'untouched series keeps its payload colour',
    overrideDatasets[0].borderColor === (plain.data as { datasets: { borderColor: string }[] }).datasets[0].borderColor,
    overrideDatasets[0].borderColor,
);
check('only the chosen series changes', overrideDatasets[1].borderColor === '#abcdef', overrideDatasets[1].borderColor);

const targets = chartColorTargets(spec!, defaultStyle);
check('targets are the two series', targets.length === 2 && targets[0].label === 'One', targets);

const pieSpec = parseInlineChart(
    JSON.stringify({
        kind: 'pie',
        data: { labels: ['X', 'Y', 'Z'], datasets: [{ label: 'S', data: [1, 2, 3] }] },
    }),
);
const pieTargets = chartColorTargets(pieSpec!, defaultStyle);
check('pie targets are slices', pieTargets.length === 3 && pieTargets[0].label === 'X', pieTargets);

const styledPie = buildChartConfig(pieSpec!, themeColors, { palette: 'calm', background: THEME_BACKGROUND, colors: {} }, null);
const pieDatasets = (styledPie.data as { datasets: { backgroundColor: string[] }[] }).datasets;
check('pie slices coloured per label', Array.isArray(pieDatasets[0].backgroundColor) && pieDatasets[0].backgroundColor.length === 3, pieDatasets[0].backgroundColor);
check('first slice uses palette', pieDatasets[0].backgroundColor[0] === '#2563eb', pieDatasets[0].backgroundColor);

console.log(failures === 0 ? '\nAll checks passed.' : `\n${failures} check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);

