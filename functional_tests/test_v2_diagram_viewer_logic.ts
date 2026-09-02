// test_v2_diagram_viewer_logic.ts
// Behavioural checks for the V2 diagram source repair and diagram sizing logic.
//
// Version: 0.261.034
// Implemented in: 0.261.034
//
// The V2 interface has no unit test runner, so this follows test_v2_visual_style_logic.ts:
// bundled with the esbuild Vite already brings in, run under node by
// test_v2_diagram_viewer_controls.py, and skipped when the front-end toolchain is not
// installed.
//
// Every "broken source" below was reproduced as a real mermaid 11.17.2 parse failure in
// Chromium, configured exactly as MermaidDiagram.tsx configures it, and every repaired form
// was confirmed to render. What is asserted here is the repair's behaviour, which is what can
// be checked without a browser:
//
//   - a source mermaid accepts is never rewritten, because the repair only ever runs after a
//     failure and rewriting working output would be a regression with no upside;
//   - each reproduced failure is actually changed, and changed in the specific way that made
//     it render;
//   - nothing outside a flowchart is touched, since every rule is flowchart grammar;
//   - the natural size read back out of mermaid's SVG is the size the panel is built from.

import {
    describeMermaidError,
    isRepairWorthTrying,
    repairMermaidSource,
} from '../application/v2_ui/src/lib/mermaidSource';
import {
    clampStageHeight,
    clampZoom,
    defaultStageHeight,
    DEFAULT_MAX_STAGE_HEIGHT,
    MAX_STAGE_HEIGHT,
    MAX_ZOOM,
    MIN_STAGE_HEIGHT,
    MIN_ZOOM,
    readDiagramSize,
} from '../application/v2_ui/src/components/chat/DiagramStage';

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail ?? '');
    }
}

/* ---- sources mermaid already renders must never be rewritten ---- */

const RENDERS = {
    'flowchart with <br/> labels': [
        'flowchart TD',
        '    browser["Browser<br/>User IP present in normal HTTP"]',
        '',
        '    subgraph azure["Azure compliance boundary"]',
        '        app["Simple Chat App Service<br/>Sees: user IP, Entra identity"]',
        '    end',
        '',
        '    browser --> app',
        '    app -->|"Authorization: Bearer token<br/>Content-Type: application/json"| browser',
    ].join('\n'),
    'flowchart with parentheses in a quoted label': [
        'flowchart TD',
        '    a["Logs: App Insights / App Service logs (your compliance boundary)"]',
        '    b["App Service"]',
        '    a --> b',
    ].join('\n'),
    'flowchart with an equals sign in a label': [
        'flowchart TD',
        '    a["market=en-us, set_lang=en, count=10"]',
        '    b["B"]',
        '    a --> b',
    ].join('\n'),
    sequenceDiagram: [
        'sequenceDiagram',
        '    participant Browser',
        '    participant App',
        '    Browser->>App: request',
        '    App-->>Browser: response',
    ].join('\n'),
    'stateDiagram-v2': ['stateDiagram-v2', '    [*] --> Idle', '    Idle --> [*]: done'].join('\n'),
    erDiagram: ['erDiagram', '    USER ||--o{ ORDER : places'].join('\n'),
    classDiagram: ['classDiagram', '    class User {', '        +login()', '    }'].join('\n'),
};

for (const [name, source] of Object.entries(RENDERS)) {
    check(`repair is a no-op for ${name}`, !isRepairWorthTrying(source), {
        repaired: repairMermaidSource(source),
    });
}

/* ---- each reproduced failure is repaired in the way that made it render ---- */

const reserved = repairMermaidSource(
    'flowchart TD\n    start["Start"]\n    end["End"]\n    start --> end\n',
);
check('a reserved node id is renamed at its declaration', reserved.includes('end_node["End"]'), reserved);
check('a reserved node id is renamed at its uses too', reserved.includes('start --> end_node'), reserved);
check('renaming a reserved id leaves no bare declaration', !/\bend\s*\[/.test(reserved), reserved);

for (const word of ['graph', 'class', 'style']) {
    const renamed = repairMermaidSource(
        `flowchart TD\n    ${word}["X"]\n    b["B"]\n    ${word} --> b\n`,
    );
    check(`the reserved id "${word}" is renamed`, renamed.includes(`${word}_node["X"]`), renamed);
}

check(
    'a word that merely contains a reserved word is left alone',
    repairMermaidSource(
        'flowchart TD\n    frontend["Front"]\n    backend["Back"]\n    frontend --> backend\n',
    ).includes('frontend["Front"]'),
);

const miscased = repairMermaidSource(
    'flowchart TD\n    subgraph s["S"]\n        a["A"]\n    End\n    b["B"]\n    a --> b\n',
);
check('a capitalised End becomes the lowercase terminator', /^\s*end\s*$/m.test(miscased), miscased);

const unclosed = repairMermaidSource(
    'flowchart TD\n    subgraph s["Azure"]\n        a["App"]\n    b["B"]\n    a --> b\n',
);
check(
    'an unclosed subgraph gains its terminator',
    unclosed.split('\n').filter((line) => /^\s*end\s*$/.test(line)).length === 1,
    unclosed,
);

const emptyLabel = repairMermaidSource('flowchart TD\n    a[""]\n    b["B"]\n    a --> b\n');
check('an empty label becomes a space rather than being dropped', emptyLabel.includes('a[" "]'), emptyLabel);

const bareParens = repairMermaidSource('flowchart TD\n    a[App (main)]\n    b["B"]\n    a --> b\n');
check('an unquoted label containing parentheses is quoted', bareParens.includes('a["App (main)"]'), bareParens);

const bareBraces = repairMermaidSource(
    'flowchart TD\n    a["A"]\n    b["B"]\n    a -->|metadata: {}| b\n',
);
check('braces in an edge label are quoted and escaped', bareBraces.includes('|"metadata: &#123;&#125;"|'), bareBraces);

const innerQuotes = repairMermaidSource(
    'flowchart TD\n    a["He said "hello" loudly"]\n    b["B"]\n    a --> b\n',
);
check(
    'a quote inside a label is escaped rather than ending it early',
    innerQuotes.includes('a["He said &quot;hello&quot; loudly"]'),
    innerQuotes,
);

const angles = repairMermaidSource(
    'flowchart TD\n    a["Bearer <random GUID>" ]\n    b["B"]\n    a -->|x| b\n',
);
check('an angle-bracketed placeholder is escaped, not dropped', angles.includes('&lt;random GUID&gt;'), angles);

const brKept = repairMermaidSource('flowchart TD\n    a["One<br/>Two{}"]\n    b["B"]\n    a --> b\n');
check('a line break survives escaping around it', brKept.includes('One<br/>Two'), brKept);

for (const variant of ['<br>', '<br />', '<BR/>']) {
    const normalised = repairMermaidSource(
        `flowchart TD\n    a["One${variant}Two{}"]\n    b["B"]\n    a --> b\n`,
    );
    check(`"${variant}" is normalised to <br/>`, normalised.includes('One<br/>Two'), normalised);
}

const runTogether = repairMermaidSource('flowchart TD\n    a["A"] b["B"]\n    a --> b\n');
check(
    'two declarations on one line are split',
    runTogether.split('\n').filter((line) => /^\s*[\w-]+\["/.test(line)).length === 2,
    runTogether,
);

const dangling = repairMermaidSource('flowchart TD\n    a["A"]\n    b["B"]\n    a --> b\n    b -->\n');
check('a dangling edge is dropped', !/-->\s*$/m.test(dangling), dangling);

/* ---- a reserved node id must not eat the subgraph terminators ---- */

// `end` as a node id and `subgraph` are both common, and they interact: renaming every `end`
// would rewrite the terminators too, moving everything after them inside the group. The result
// still parses, so it would show the wrong structure rather than failing.
const endAndSubgraph = repairMermaidSource(
    [
        'flowchart TD',
        '  subgraph grp["Group"]',
        '    a["A"]',
        '  end',
        '  end["Finish"]',
        '  a --> end',
    ].join('\n'),
);
check(
    'the subgraph terminator survives a reserved-id rename',
    endAndSubgraph.split('\n').filter((line) => /^\s*end\s*$/.test(line)).length === 1,
    endAndSubgraph,
);
check(
    'the node called end is still renamed alongside it',
    endAndSubgraph.includes('end_node["Finish"]') && endAndSubgraph.includes('a --> end_node'),
    endAndSubgraph,
);
check(
    'no terminator is appended, because none was missing',
    endAndSubgraph.trimEnd().endsWith('a --> end_node'),
    endAndSubgraph,
);

/* ---- a pipe inside a node label is not an edge-label delimiter ---- */

const pipeInLabel = repairMermaidSource(
    'flowchart TD\n    a["A|B"] --> |"yes"| b["B"]\n    c[Bad (label)]\n',
);
check('a pipe inside a quoted label is left alone', pipeInLabel.includes('a["A|B"]'), pipeInLabel);
check('the arrow beside it is not escaped', pipeInLabel.includes('--> |"yes"|'), pipeInLabel);
check(
    'the genuinely broken node on another line is still repaired',
    pipeInLabel.includes('c["Bad (label)"]'),
    pipeInLabel,
);

check(
    'an odd number of pipes is left alone rather than paired by guesswork',
    repairMermaidSource('flowchart TD\n    a["A"] -->|x b["B"]\n').includes('-->|x'),
);

check(
    'a byte-order mark is stripped',
    !repairMermaidSource('\ufeffflowchart TD\n    a["A"]\n').includes('\ufeff'),
);
check(
    'a non-breaking space becomes an ordinary one',
    !repairMermaidSource('flowchart TD\n\u00a0\u00a0  a["A"]\n').includes('\u00a0'),
);
check(
    'smart double quotes become straight ones',
    repairMermaidSource('flowchart TD\n    a[\u201cBrowser\u201d]\n').includes('"Browser"'),
);

/* ---- nothing outside a flowchart is rewritten ---- */

const erCardinality = repairMermaidSource('erDiagram\n    USER ||--o{ ORDER : places\n');
check('erDiagram cardinality is untouched', erCardinality.includes('||--o{ ORDER : places'), erCardinality);

const sequenceKeyword = repairMermaidSource(
    'sequenceDiagram\n    participant end\n    end->>end: loop\n',
);
check(
    'a sequence diagram is not rewritten with flowchart rules',
    !sequenceKeyword.includes('end_node'),
    sequenceKeyword,
);

check(
    'a comment line is left alone',
    repairMermaidSource('flowchart TD\n    %% end["not a node"]\n    a["A"]\n').includes(
        '%% end["not a node"]',
    ),
);

/* ---- error descriptions ---- */

check(
    'a parse error is reduced to its first line',
    describeMermaidError(new Error('Parse error on line 3:\n...caret art...\nExpecting SEMI')) ===
        'Parse error on line 3:',
);
check(
    'the edge limit is reworded',
    describeMermaidError(new Error('Edge limit exceeded. 500 edges found, but the limit is 500.')) ===
        'The diagram has too many connections to draw.',
);
check(
    'the text size limit is reworded',
    describeMermaidError(new Error('Maximum text size in diagram exceeded')) ===
        'The diagram source is too large to draw.',
);
check(
    'a missing diagram type is reworded',
    describeMermaidError(new Error('No diagram type detected matching given configuration')) ===
        'The first line does not name a diagram type mermaid recognises.',
);
check('a non-error is still described', describeMermaidError(undefined).length > 0);

/* ---- natural size, read out of what mermaid actually emits ---- */

// The exact shape mermaid 11.17.2 emits with useMaxWidth: no height attribute, a percentage
// width, and the natural width in a max-width declaration.
const emitted =
    '<svg aria-roledescription="flowchart-v2" viewBox="0 0 1094 541" width="100%" ' +
    'style="max-width: 1094px; background-color: white;"><g></g></svg>';

const size = readDiagramSize(emitted);
check('the natural width is read from max-width', size?.width === 1094, size);
check('the natural height is read from the viewBox', size?.height === 541, size);
check(
    'a percentage width is never mistaken for a size',
    readDiagramSize('<svg width="100%" height="100%"></svg>') === null,
);
check('markup with no size at all reports none', readDiagramSize('<svg></svg>') === null);

const viewBoxOnly = readDiagramSize('<svg viewBox="0 0 400 200" width="100%"></svg>');
check('the viewBox alone is enough', viewBoxOnly?.width === 400 && viewBoxOnly?.height === 200, viewBoxOnly);

/* ---- stage sizing ---- */

check('a stage cannot be dragged below the minimum', clampStageHeight(10) === MIN_STAGE_HEIGHT);
check('a stage cannot be dragged above the maximum', clampStageHeight(99999) === MAX_STAGE_HEIGHT);
check('a stage height is rounded to whole pixels', clampStageHeight(300.6) === 301);

check('zoom is bounded below', clampZoom(0.01) === MIN_ZOOM);
check('zoom is bounded above', clampZoom(100) === MAX_ZOOM);

// The tree diagram from the report: wide and short. Fitted to a narrower panel it is shorter
// still, so its stage should be no taller than it needs.
const wideAndShort = defaultStageHeight({ width: 1094, height: 541 }, 700);
check(
    'a wide, short diagram gets a stage that fits it',
    wideAndShort < DEFAULT_MAX_STAGE_HEIGHT && wideAndShort > MIN_STAGE_HEIGHT,
    wideAndShort,
);

// The label-heavy diagram from the report: narrow and very tall. Its stage must be capped, or
// it becomes a thousand-pixel block in the middle of the thread.
check(
    'a tall diagram is capped rather than filling the thread',
    defaultStageHeight({ width: 497, height: 867 }, 497) === DEFAULT_MAX_STAGE_HEIGHT,
    defaultStageHeight({ width: 497, height: 867 }, 497),
);

// 500 edges measured 50,466px tall. Nothing that size may ever reach the scroll container.
check(
    'an enormous diagram is capped',
    defaultStageHeight({ width: 111, height: 50466 }, 800) === DEFAULT_MAX_STAGE_HEIGHT,
);

check(
    'an unmeasured diagram still gets a usable stage',
    defaultStageHeight(null, 800) === MIN_STAGE_HEIGHT,
);

console.log(failures === 0 ? '\nAll checks passed.' : `\n${failures} check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
