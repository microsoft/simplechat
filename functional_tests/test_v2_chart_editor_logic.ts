// test_v2_chart_editor_logic.ts
// Behavioural checks for the chart payload transforms and edit validation.
//
// Version: 0.261.061
// Implemented in: 0.261.061
//
// The V2 interface has no unit test runner, so this follows test_v2_diagram_editor_logic.ts:
// bundled with the esbuild Vite already brings in, run under node by test_v2_chart_editor.py,
// and skipped when the front-end toolchain is not installed.
//
// Two properties are worth more than all the others here. A control must not destroy anything
// it does not understand, because the payload contains fields this client never reads. And a
// control edit must be a real edit to the source, because that is what makes it a revision that
// can be undone, exported and read in the other interface.

import {
    chartKindChoices,
    describeChartChanges,
    describeChartProblem,
    formatChartSource,
    isEditableAsGrid,
    isPointChart,
    readChartDataDraft,
    readChartPayload,
    setChartData,
    setChartKind,
    setChartOption,
    setChartText,
} from '../application/v2_ui/src/lib/chartEdits';
import { parseInlineChart } from '../application/v2_ui/src/lib/inlineChartSpec';
import { describeSourceProblem, EDITABLE_BLOCK_KINDS } from '../application/v2_ui/src/lib/blockRevisions';

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail ?? '');
    }
}

/** The compact single-line JSON the chart action emits. */
const BAR = JSON.stringify({
    version: 1,
    chartId: 'abc123',
    kind: 'bar',
    chartType: 'bar',
    title: 'Revenue',
    summary: 'Revenue by month',
    data: {
        labels: ['Jan', 'Feb', 'Mar'],
        datasets: [{ label: 'North', data: [10, 20, 30] }],
    },
    options: {},
    table: { columns: ['Label', 'North'], rows: [['Jan', 10], ['Feb', 20], ['Mar', 30]] },
});

const MULTI = JSON.stringify({
    version: 1,
    kind: 'line',
    data: {
        labels: ['Jan', 'Feb'],
        datasets: [
            { label: 'North', data: [1, 2] },
            { label: 'South', data: [3, 4] },
        ],
    },
    options: {},
});

const SCATTER = JSON.stringify({
    version: 1,
    kind: 'scatter',
    data: { datasets: [{ label: 'A', data: [{ x: 1, y: 2 }, { x: 3, y: 4 }] }] },
    options: {},
});

/* ---- the kind is editable at all ---- */

check(
    'simplechart is an editable block kind',
    (EDITABLE_BLOCK_KINDS as readonly string[]).includes('simplechart'),
);

/* ---- reading and writing the payload ---- */

const document = readChartPayload(BAR);
check('a chart payload is read as an object', Boolean(document && document.raw.kind === 'bar'));
check('the chart action writes compactly, and that is noticed', document?.compact === true);
check(
    'a payload spread over lines is not treated as compact',
    readChartPayload(formatChartSource(BAR))?.compact === false,
);
const laidOut = formatChartSource(BAR);
check(
    'laying the payload out does not change what it means',
    JSON.stringify(readChartPayload(laidOut)?.raw) === JSON.stringify(readChartPayload(BAR)?.raw),
);
check('a payload that is not an object is refused', readChartPayload('[1,2,3]') === null);
check('an empty payload is refused', readChartPayload('   ') === null);

/* ---- a control never destroys what it does not understand ---- */

const widened = setChartOption(BAR, 'barWidth', 0.4);
check('a control edit keeps the payload compact', !widened.includes('\n'));
check(
    'a control edit preserves fields this client does not model',
    readChartPayload(widened)?.raw.chartId === 'abc123'
        && readChartPayload(widened)?.raw.summary === 'Revenue by month',
);
check('the change actually reaches the payload', parseInlineChart(widened)?.options.barWidth === 0.4);
check(
    'the change survives being read back through the parser',
    parseInlineChart(setChartOption(widened, 'yMax', 99))?.options.yMax === 99,
);

/* ---- defaults are removed rather than written ---- */

check(
    'setting an option back to its default removes the key again',
    !('barWidth' in (readChartPayload(setChartOption(widened, 'barWidth', 0.9))?.raw as { options: Record<string, unknown> }).options),
);
check(
    'a null clears an option rather than storing null',
    !('yMax' in (readChartPayload(setChartOption(setChartOption(BAR, 'yMax', 5), 'yMax', null))?.raw as { options: Record<string, unknown> }).options),
);
check(
    'an untouched payload round-trips through a default-valued control unchanged',
    setChartOption(BAR, 'beginAtZero', true) === BAR,
);

/* ---- stacked and fill are written explicitly, because the kind forces them ---- */

const stackedOff = setChartOption(JSON.stringify({
    version: 1, kind: 'stacked_bar', data: { labels: ['a'], datasets: [{ label: 'x', data: [1] }] }, options: {},
}), 'stacked', false);
check(
    'turning stacking off on a stacked chart is written down, not silently dropped',
    (readChartPayload(stackedOff)?.raw as { options: Record<string, unknown> }).options.stacked === false,
);

/* ---- titles ---- */

check(
    'a title can be set',
    parseInlineChart(setChartText(BAR, 'title', ' Quarterly revenue '))?.title === 'Quarterly revenue',
);
check(
    'clearing a title removes the field',
    !('title' in (readChartPayload(setChartText(BAR, 'title', '  '))?.raw ?? {})),
);

/* ---- changing the kind ---- */

const asLine = setChartKind(BAR, 'line');
check('the kind changes', parseInlineChart(asLine)?.kind === 'line');
check(
    'chartType is rewritten with it, so the two cannot disagree',
    readChartPayload(asLine)?.raw.chartType === 'line',
);
check(
    'switching to a stacked kind writes the stacking it implies',
    parseInlineChart(setChartKind(BAR, 'stacked_bar'))?.options.stacked === true,
);
check(
    'switching away from a stacked kind stops forcing stacking',
    parseInlineChart(setChartKind(setChartKind(BAR, 'stacked_bar'), 'line'))?.options.stacked === false,
);
check(
    'switching to an area chart fills it',
    parseInlineChart(setChartKind(BAR, 'area'))?.options.fill === true,
);
check(
    'a horizontal bar chart that becomes a pie is no longer horizontal',
    parseInlineChart(setChartKind(setChartOption(BAR, 'horizontal', true), 'pie'))?.options.horizontal === false,
);

/* ---- which kinds are offered ---- */

const singleSeries = chartKindChoices(parseInlineChart(BAR)!);
check('a single-series chart may become a pie', singleSeries.kinds.includes('pie'));
check('and nothing needs explaining', singleSeries.note === null);

const multiSeries = chartKindChoices(parseInlineChart(MULTI)!);
check('a multi-series chart is not offered pie', !multiSeries.kinds.includes('pie'));
check('a multi-series chart is still offered bar', multiSeries.kinds.includes('bar'));
check('and the reason is given rather than left a mystery', Boolean(multiSeries.note));

const points = chartKindChoices(parseInlineChart(SCATTER)!);
check('a scatter chart is not offered a category chart', !points.kinds.includes('bar'));
check('a scatter chart may become a bubble chart', points.kinds.includes('bubble'));
check('and the reason is given', Boolean(points.note));
check('scatter and bubble are recognised as point charts', isPointChart('scatter') && isPointChart('bubble'));
check('a bar chart is not', !isPointChart('bar'));

/* ---- the numbers ---- */

const draft = readChartDataDraft(parseInlineChart(BAR)!);
check('the grid reads the labels', JSON.stringify(draft.labels) === '["Jan","Feb","Mar"]');
check('the grid reads the values', JSON.stringify(draft.series[0].values) === '[10,20,30]');

draft.series[0].values[1] = 25;
draft.labels[2] = 'March';
const edited = setChartData(BAR, draft, 'bar');
const editedSpec = parseInlineChart(edited)!;
check('an edited value lands in the payload', (editedSpec.data.datasets[0].data as (number | null)[])[1] === 25);
check('an edited label lands in the payload', editedSpec.data.labels[2] === 'March');
check(
    'the stored table is dropped, because it would now disagree with the chart',
    !('table' in (readChartPayload(edited)?.raw ?? {})),
);
check(
    'and the disclosure still has numbers to show, derived from the chart itself',
    JSON.stringify(editedSpec.table) === 'null',
);
check(
    'editing the numbers leaves everything else alone',
    readChartPayload(edited)?.raw.chartId === 'abc123' && editedSpec.title === 'Revenue',
);

const gapped = readChartDataDraft(parseInlineChart(BAR)!);
gapped.series[0].values[1] = null;
check(
    'an emptied cell is a gap rather than a zero',
    (parseInlineChart(setChartData(BAR, gapped, 'bar'))!.data.datasets[0].data as (number | null)[])[1] === null,
);

const grown = readChartDataDraft(parseInlineChart(BAR)!);
grown.labels.push('Apr');
grown.series[0].values.push(40);
grown.series.push({ label: 'South', values: [1, 2, 3, 4], points: [] });
const grownSpec = parseInlineChart(setChartData(BAR, grown, 'bar'))!;
check('a row can be added', grownSpec.data.labels.length === 4);
check('a series can be added', grownSpec.data.datasets.length === 2);
check('the added series keeps its name', grownSpec.data.datasets[1].label === 'South');

const shrunk = readChartDataDraft(parseInlineChart(MULTI)!);
shrunk.series.splice(0, 1);
check(
    'a series can be removed',
    parseInlineChart(setChartData(MULTI, shrunk, 'line'))!.data.datasets.length === 1,
);

// The parser trims what it reads, so anything stored untrimmed can never be read back and the
// stored value would permanently disagree with what the editor shows.
const spaced = readChartDataDraft(parseInlineChart(BAR)!);
spaced.labels[0] = '  January  ';
spaced.series[0].label = ' North ';
const trimmed = parseInlineChart(setChartData(BAR, spaced, 'bar'))!;
check('a row label is stored trimmed, so it round-trips', trimmed.data.labels[0] === 'January');
check('and so is a series name', trimmed.data.datasets[0].label === 'North');
check(
    'a label with a space inside it is left alone',
    parseInlineChart(setChartData(BAR, (() => {
        const next = readChartDataDraft(parseInlineChart(BAR)!);
        next.labels[0] = 'Early January';
        return next;
    })(), 'bar'))!.data.labels[0] === 'Early January',
);
check(
    'a multi-word title round-trips',
    parseInlineChart(setChartText(BAR, 'title', 'Revenue by region'))?.title === 'Revenue by region',
);

const scatterDraft = readChartDataDraft(parseInlineChart(SCATTER)!);
check('a point chart reads its pairs rather than labels', scatterDraft.series[0].points.length === 2);
scatterDraft.series[0].points[0] = { x: 9, y: 9 };
check(
    'an edited point lands in the payload',
    JSON.stringify(parseInlineChart(setChartData(SCATTER, scatterDraft, 'scatter'))!.data.datasets[0].data[0])
        === '{"x":9,"y":9}',
);

/* ---- a grid is not offered where it would lose data ---- */

const huge = JSON.stringify({
    version: 1,
    kind: 'bar',
    data: {
        labels: Array.from({ length: 199 }, (_, index) => `L${index}`),
        datasets: [{ label: 'A', data: Array.from({ length: 199 }, () => 1) }],
    },
    options: {},
});
check('a large but bounded chart is still editable as a grid', isEditableAsGrid(parseInlineChart(huge)!));

const enormous = JSON.stringify({
    version: 1,
    kind: 'scatter',
    data: {
        datasets: [{
            label: 'A',
            data: Array.from({ length: 400 }, (_, index) => ({ x: index, y: index })),
        }],
    },
    options: {},
});
check(
    'a chart too big for a grid is sent to the source editor instead of being truncated',
    !isEditableAsGrid(parseInlineChart(enormous)!),
);

/* ---- validation ---- */

check('a good chart has no problem to report', describeChartProblem(BAR) === null);
check('broken JSON is reported', Boolean(describeChartProblem('{"kind": "bar"')));
check(
    'JSON that is not a chart is reported',
    Boolean(describeChartProblem('{"kind":"bar","data":{"labels":[],"datasets":[]}}')),
);
check('an unknown kind is reported', Boolean(describeChartProblem(
    JSON.stringify({ kind: 'sankey', data: { labels: ['a'], datasets: [{ label: 'x', data: [1] }] } }),
)));

check(
    'the block checks reject an empty chart in chart words',
    describeSourceProblem('', 'simplechart') === 'The chart cannot be empty.',
);
check(
    'a chart that would escape its own fence is refused',
    Boolean(describeSourceProblem('```\n{"kind":"bar"}', 'simplechart')),
);
check(
    'an unreadable chart is refused before it can be stored',
    Boolean(describeSourceProblem('not a chart at all', 'simplechart')),
);
check('a good chart passes the block checks', describeSourceProblem(BAR, 'simplechart') === null);
check(
    'diagrams still get diagram wording',
    describeSourceProblem('', 'mermaid') === 'The diagram cannot be empty.',
);
check(
    'a diagram is not put through the chart check',
    describeSourceProblem('graph TD\n A --> B', 'mermaid') === null,
);

/* ---- the history note ---- */

check(
    'a bar width change is named in the history',
    describeChartChanges(BAR, setChartOption(BAR, 'barWidth', 0.4)) === 'Bar width',
);
check(
    'an axis range change is named',
    describeChartChanges(BAR, setChartOption(BAR, 'yMax', 50)) === 'Value axis',
);
check(
    'an axis name change is named',
    describeChartChanges(BAR, setChartOption(BAR, 'yAxisLabel', 'Revenue')) === 'Axis names',
);
check(
    'a type change names the type it became',
    describeChartChanges(BAR, setChartKind(BAR, 'line')) === 'Type: Line',
);
check(
    'a data change is named',
    describeChartChanges(BAR, setChartData(BAR, (() => {
        const next = readChartDataDraft(parseInlineChart(BAR)!);
        next.series[0].values[0] = 99;
        return next;
    })(), 'bar')) === 'Data',
);
check(
    'several changes at once are all named',
    describeChartChanges(BAR, setChartOption(setChartOption(BAR, 'barWidth', 0.4), 'showLegend', false))
        === 'Bar width, Legend',
);
check('an unchanged chart has nothing to say', describeChartChanges(BAR, BAR) === '');

/* ---- a hand-written payload ---- */

const LOOSE = 'kind: bar\ntitle: Sales\ndata:\n  labels: [A, B]\n  datasets:\n    - label: One\n      data: [1, 2]\n';
check('a hand-written payload is readable', Boolean(parseInlineChart(LOOSE)));
check(
    'and editing one produces JSON, because there is no writer for the other form',
    Boolean(readChartPayload(setChartOption(LOOSE, 'beginAtZero', false))?.raw)
        && parseInlineChart(setChartOption(LOOSE, 'beginAtZero', false))?.options.beginAtZero === false,
);
check(
    'without losing its data',
    parseInlineChart(setChartOption(LOOSE, 'beginAtZero', false))?.title === 'Sales',
);

/* ---- an unreadable payload is left alone ---- */

check(
    'a control given half-typed JSON changes nothing, rather than saving a misreading',
    setChartOption('{"kind": "bar"', 'barWidth', 0.4) === '{"kind": "bar"',
);
check(
    'and half-typed JSON is not quietly rewritten by the hand-written-payload parser',
    readChartPayload('{"kind": "bar"') === null,
);
check(
    'a control given something that is not a payload at all changes nothing',
    setChartOption('', 'barWidth', 0.4) === '',
);

if (failures) {
    console.log(`\n${failures} check(s) failed`);
    process.exit(1);
}
console.log('\nAll chart editor logic checks passed');
