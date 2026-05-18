# Proactive Analytical Charts

Implemented in version: **0.241.033**

## Overview

Proactive Analytical Charts extends the conversation-level chart capability so chat responses and workflow outputs can include charts whenever the available data supports useful visualization. Users no longer need to explicitly say "make a chart" when asking for analysis, comparison, reports, Markdown output, or presentation-ready content.

## Purpose

The feature makes charts part of the generated analytical output instead of a final add-on. When the model identifies chart-worthy numeric or categorical patterns, it is guided to create inline charts near the relevant section, table, or finding.

## Dependencies

- Conversation chart plugin loaded as `conversation_charts`
- Inline chart markdown language: `simplechart`
- Tabular analysis handoff messages and workflow synthesis prompts
- PowerPoint and Markdown export paths that preserve inline chart blocks

## Technical Specifications

### Architecture

- `functions_chart_operations.py` owns reusable proactive chart guidance helpers.
- `route_backend_chats.py` applies chart guidance for explicit chart requests and analytical output requests such as reports, comparisons, Markdown, and PowerPoint prompts.
- `functions_workflow_runner.py` applies the same guidance to tabular analyze/compare synthesis and general workflow generation prompts.

### Chart Selection Guidance

- Line or area charts for time trends
- Bar charts for category comparisons
- Stacked bar or stacked line charts for composition across groups or time
- Doughnut or pie charts for small part-to-whole splits
- Scatter or bubble charts for relationships between numeric measures
- Radar charts for compact multi-metric profiles

### Output Placement

Charts should be inserted inline immediately after the section, paragraph, or table they support. Comprehensive reviews can include multiple high-value charts when multiple distinct patterns exist.

## Usage Instructions

Users can ask for natural analytical outputs such as:

- "Analyze this workbook and create an executive summary."
- "Compare these quarterly sales files."
- "Develop a PowerPoint presentation from this dataset."
- "Generate a Markdown report from these metrics."

The model should decide whether charts are useful, how many charts to include, and which chart type fits each data shape.

## Testing and Validation

Functional coverage:

- `functional_tests/test_conversation_chart_and_tabular_reuse.py`
- `functional_tests/test_chart_tool_prompt_handoff.py`

Validation focuses on:

- Core chart plugin availability in conversation paths
- Proactive chart guidance for analytical chat prompts
- Workflow prompt wiring for tabular and general workflow generation
- Kernel fallback auto tool invocation for conversation tools

## Known Limitations

Direct model-only workflow generation cannot call Semantic Kernel tools directly, so the prompt allows valid `simplechart` blocks when no chart action/tool is available. Agent-backed and kernel-backed paths should prefer chart tool calls when available.