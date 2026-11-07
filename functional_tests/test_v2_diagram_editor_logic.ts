// test_v2_diagram_editor_logic.ts
// Behavioural checks for the diagram layout transforms and edit validation.
//
// Version: 0.261.043
// Implemented in: 0.261.043
//
// The V2 interface has no unit test runner, so this follows test_v2_diagram_viewer_logic.ts:
// bundled with the esbuild Vite already brings in, run under node by
// test_v2_diagram_editor.py, and skipped when the front-end toolchain is not installed.
//
// The layout transforms are the honest answer to "move that box". Mermaid computes node
// positions, so what a reader can actually change is the direction and the spacing — and both
// have to be real edits to the source, because they become revisions like any other and have
// to survive a round trip through the source editor.

import {
    FLOW_DIRECTIONS,
    readFlowDirection,
    readSpacingPreset,
    setFlowDirection,
    setSpacingPreset,
    supportsFlowDirection,
    type FlowDirection,
} from '../application/v2_ui/src/lib/mermaidLayout';
import { describeSourceProblem, MAX_BLOCK_SOURCE_LENGTH } from '../application/v2_ui/src/lib/blockRevisions';

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
    if (condition) {
        console.log(`  ok  ${name}`);
    } else {
        failures += 1;
        console.log(`FAIL  ${name}`, detail ?? '');
    }
}

/* ---- flow direction ---- */

const FLOWCHART = 'graph TD\n  A[Start] --> B[End]';

check('a flowchart reports its direction', readFlowDirection(FLOWCHART) === 'TD');
check(
    'TB is reported as TD, since mermaid treats them as the same',
    readFlowDirection('graph TB\n  A --> B') === 'TD',
);
check(
    'the flowchart keyword is recognised as well as graph',
    readFlowDirection('flowchart LR\n  A --> B') === 'LR',
);
check(
    'a leading init directive does not hide the declaration',
    readFlowDirection('%%{init: {"theme":"dark"}}%%\ngraph RL\n  A --> B') === 'RL',
);

check(
    'a sequence diagram has no direction to change',
    readFlowDirection('sequenceDiagram\n  A->>B: hi') === null,
);
check(
    'and the control knows not to offer itself',
    supportsFlowDirection('sequenceDiagram\n  A->>B: hi') === false &&
        supportsFlowDirection(FLOWCHART),
);

for (const direction of FLOW_DIRECTIONS) {
    const rewritten = setFlowDirection(FLOWCHART, direction as FlowDirection);
    check(
        `the direction can be set to ${direction}`,
        readFlowDirection(rewritten) === direction,
        rewritten,
    );
    check(
        `setting ${direction} leaves the diagram body alone`,
        rewritten.includes('A[Start] --> B[End]'),
        rewritten,
    );
}

check(
    'a diagram with no declaration is returned unchanged rather than corrupted',
    setFlowDirection('sequenceDiagram\n  A->>B: hi', 'LR') === 'sequenceDiagram\n  A->>B: hi',
);

check(
    'indentation on the declaration survives',
    setFlowDirection('  graph TD\n  A --> B', 'LR') === '  graph TD\n  A --> B'.replace('TD', 'LR'),
);

check(
    'a node label containing the word graph is not mistaken for the declaration',
    setFlowDirection('graph TD\n  A["graph TD is a declaration"] --> B', 'LR') ===
        'graph LR\n  A["graph TD is a declaration"] --> B',
);

/* ---- spacing ---- */

check('an untouched diagram reads as normal spacing', readSpacingPreset(FLOWCHART) === 'normal');

const compact = setSpacingPreset(FLOWCHART, 'compact');
check('spacing can be made compact', readSpacingPreset(compact) === 'compact', compact);
check('the compact directive is a real init directive', compact.startsWith('%%{init:'), compact);
check('the diagram body survives a spacing change', compact.includes('A[Start] --> B[End]'));

const roomy = setSpacingPreset(compact, 'roomy');
check('spacing can be changed again', readSpacingPreset(roomy) === 'roomy', roomy);
check(
    'changing spacing does not stack up directives',
    (roomy.match(/%%\{init:/g) ?? []).length === 1,
    roomy,
);

const backToNormal = setSpacingPreset(roomy, 'normal');
check('spacing can be reset', readSpacingPreset(backToNormal) === 'normal', backToNormal);
check(
    'resetting removes the directive rather than leaving an empty one behind',
    !backToNormal.includes('%%{init:'),
    backToNormal,
);
check(
    'and the diagram is back to what it was',
    backToNormal.trim() === FLOWCHART.trim(),
    backToNormal,
);

const themed = '%%{init: {"theme":"forest"}}%%\ngraph TD\n  A --> B';
const themedCompact = setSpacingPreset(themed, 'compact');
check(
    'an unrelated setting in the directive is preserved',
    themedCompact.includes('"theme"') && themedCompact.includes('"forest"'),
    themedCompact,
);
check('and the spacing still applies', readSpacingPreset(themedCompact) === 'compact');

const themedNormal = setSpacingPreset(themedCompact, 'normal');
check(
    'resetting spacing keeps a directive that still has something in it',
    themedNormal.includes('"theme"') && readSpacingPreset(themedNormal) === 'normal',
    themedNormal,
);

check(
    'direction and spacing compose without fighting',
    (() => {
        const both = setFlowDirection(setSpacingPreset(FLOWCHART, 'roomy'), 'LR');
        return readFlowDirection(both) === 'LR' && readSpacingPreset(both) === 'roomy';
    })(),
);

check(
    'an unparseable directive does not throw',
    (() => {
        try {
            const broken = '%%{init: not json at all}%%\ngraph TD\n  A --> B';
            readSpacingPreset(broken);
            setSpacingPreset(broken, 'compact');
            return true;
        } catch {
            return false;
        }
    })(),
);

/* ---- edit validation ---- */

check('a valid diagram has no problem', describeSourceProblem(FLOWCHART) === null);
check('an empty diagram is refused', describeSourceProblem('   \n  ') !== null);
check(
    'a source that would close its own fence is refused',
    describeSourceProblem('graph TD\n```\n\n# Injected') !== null,
);
check(
    'a tilde fence is refused too',
    describeSourceProblem('graph TD\n~~~\n\nInjected') !== null,
);
check(
    'an indented fence is still a fence',
    describeSourceProblem('graph TD\n   ```\n\nInjected') !== null,
);
check(
    'a diagram longer than the server will store is refused',
    describeSourceProblem('graph TD\n' + 'x'.repeat(MAX_BLOCK_SOURCE_LENGTH)) !== null,
);
check(
    'backticks inside a label are fine, since they do not start a line',
    describeSourceProblem('graph TD\n  A["a ``` b"] --> B') === null,
);

console.log(failures === 0 ? '\nAll checks passed.' : `\n${failures} check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
