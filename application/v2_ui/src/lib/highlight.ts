// highlight.ts
// Curated syntax-highlighting language set for chat responses.
//
// rehype-highlight defaults to lowlight's "common" bundle of ~37 grammars, which was the
// single largest contributor to the JS bundle. These are the languages that actually show
// up in SimpleChat answers; anything else still renders as a plain code block.

import bash from 'highlight.js/lib/languages/bash';
import csharp from 'highlight.js/lib/languages/csharp';
import css from 'highlight.js/lib/languages/css';
import diff from 'highlight.js/lib/languages/diff';
import dockerfile from 'highlight.js/lib/languages/dockerfile';
import go from 'highlight.js/lib/languages/go';
import ini from 'highlight.js/lib/languages/ini';
import java from 'highlight.js/lib/languages/java';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import markdown from 'highlight.js/lib/languages/markdown';
import powershell from 'highlight.js/lib/languages/powershell';
import python from 'highlight.js/lib/languages/python';
import sql from 'highlight.js/lib/languages/sql';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';
import yaml from 'highlight.js/lib/languages/yaml';

export const highlightLanguages = {
    bash,
    csharp,
    css,
    diff,
    dockerfile,
    go,
    ini,
    java,
    javascript,
    json,
    markdown,
    powershell,
    python,
    sql,
    typescript,
    xml,
    yaml,
};
