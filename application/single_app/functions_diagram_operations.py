# functions_diagram_operations.py
"""Shared helpers for inline Mermaid diagram guidance and diagram intent detection.

SimpleChat renders fenced ``mermaid`` blocks as diagrams in chat, but a model has no way
to know that. Asked for "a diagram" it will otherwise draw box art in a ``text`` fence,
which renders as a code block. These helpers detect a diagram request and attach the
guidance that tells the model which fence actually renders.
"""

import re


MERMAID_BLOCK_LANGUAGE = 'mermaid'
DIAGRAM_GUIDANCE_MARKER = '[MERMAID_DIAGRAM_GUIDANCE]'

DIAGRAM_REQUEST_MARKERS = (
    'diagram',
    'flowchart',
    'flow chart',
    'sequence diagram',
    'state machine',
    'state diagram',
    'class diagram',
    'entity relationship',
    'entity-relationship',
    'erd',
    'mind map',
    'mindmap',
    'gantt',
    'swimlane',
    'swim lane',
    'org chart',
    'organization chart',
    'organizational chart',
    'topology',
    'user journey',
    'decision tree',
    'call graph',
    'sitemap',
    'site map',
    'uml',
    'data flow',
    'dataflow',
)

DIAGRAM_REQUEST_PATTERN = re.compile(
    r'\b(?:' + '|'.join(re.escape(marker) for marker in DIAGRAM_REQUEST_MARKERS) + r')\b'
)

# A structural verb paired with a structural noun. Kept narrow on purpose: "visualize
# revenue" is a chart request and must stay with the chart guidance, while "visualize the
# request flow" is a diagram request.
DIAGRAM_INTENT_PATTERN = re.compile(
    r'\b(?:draw|sketch|map\s+out|chart\s+out|graph\s+out|visuali[sz]e|illustrate|depict|outline)\b'
    r'[^.!?\n]{0,80}'
    r'\b(?:flow|flows|process|processes|architecture|pipeline|sequence|workflow|hierarchy|'
    r'relationship|relationships|dependency|dependencies|lifecycle|life cycle|journey|'
    r'topology|state machine|structure)\b'
)


def user_requested_diagram(user_message):
    """Return True when the request is for a structural diagram rather than a data chart."""
    normalized_message = re.sub(r'\s+', ' ', str(user_message or '').strip().lower())
    if not normalized_message:
        return False

    if DIAGRAM_REQUEST_PATTERN.search(normalized_message):
        return True

    return bool(DIAGRAM_INTENT_PATTERN.search(normalized_message))


def build_diagram_guidance_message():
    """Build guidance that points diagram answers at the fence the client renders."""
    return f"""{DIAGRAM_GUIDANCE_MARKER}
SimpleChat renders fenced ```{MERMAID_BLOCK_LANGUAGE}``` blocks as real diagrams in the chat transcript, and carries them into PDF, Word, and PowerPoint exports as images. When the user asks for a diagram, flowchart, sequence, architecture, data flow, hierarchy, state machine, entity relationship, or any other structural picture, answer with a ```{MERMAID_BLOCK_LANGUAGE}``` block.

Never answer a diagram request with ASCII art, box-drawing characters, indentation trees, or a ```text``` block. Those render as plain code and are unreadable to screen readers. If the user pastes ASCII art and asks you to turn it into a diagram, translate its meaning into Mermaid rather than reformatting the art.

Choose the diagram type from the intent:
- `flowchart TD` or `flowchart LR` for steps, request paths, data flow, and system architecture.
- `sequenceDiagram` for ordered exchanges between participants over time.
- `stateDiagram-v2` for states and transitions.
- `erDiagram` for entities and their relationships.
- `classDiagram` for types, fields, and inheritance.
- `gantt` for scheduled work, `mindmap` for hierarchies of ideas, `journey` for user journeys.

Keep the source valid so it renders on the first attempt:
- Give every node a quoted label, for example `app["Simple Chat App Service"]`. Unquoted parentheses, braces, angle brackets, colons, `#`, and quotes inside a label break the parser.
- Never use `end`, `graph`, `class`, `style`, `subgraph`, or `click` as a node id: they are reserved words and the diagram will not parse. Write `end_state` or `graph_node` instead.
- Close every `subgraph` with a lowercase `end` on its own line. `End` and `END` are not accepted.
- Write one statement per line, and use `%%` for comments.
- Use `<br/>` inside a quoted label for a line break; do not use raw newlines.
- Do not use `click`, `style` with URLs, or any directive that links or navigates. They are stripped before rendering.
- Prefer one clear diagram over several near-duplicates, place it directly after the prose it illustrates, and add a short sentence introducing it.

Keep it readable. A diagram is a picture, not a transcript:
- Keep each node label to a short phrase, roughly a handful of words. Split detail across several connected nodes instead of writing one node with a dozen `<br/>` lines in it, which renders as a tall column of text nobody can take in.
- When the user pastes text or ASCII art to be turned into a diagram, translate the structure and summarise the detail. Do not carry placeholders such as `<random GUID>`, literal `{{}}`, or quoted fragments into labels; describe them in words, or leave them to the prose around the diagram.
- Aim for something that fits on a screen. Beyond roughly twenty nodes, split the answer into more than one diagram, each with its own heading.

A diagram is not always the right answer. When the content is narrative, numeric, or a simple list, prose, a table, or a chart is better. Base every node and edge on the source material or the user's own description, and never invent components, systems, or relationships to fill out a picture.

Use a diagram, not a generated image, for structural content such as flows, architectures, sequences, and relationships: Mermaid output stays selectable, accessible, and editable. Reserve image generation for illustrative or pictorial visuals. Use inline chart blocks, not Mermaid, when the answer is a plot of numeric or categorical data."""


def append_diagram_guidance(prompt_text, force=False):
    """Append diagram guidance to a prompt when the request calls for a diagram."""
    normalized_prompt = str(prompt_text or '').strip()
    if not normalized_prompt:
        return build_diagram_guidance_message() if force else normalized_prompt

    if DIAGRAM_GUIDANCE_MARKER in normalized_prompt:
        return normalized_prompt

    if not force and not user_requested_diagram(normalized_prompt):
        return normalized_prompt

    return f"{normalized_prompt}\n\n{build_diagram_guidance_message()}"
