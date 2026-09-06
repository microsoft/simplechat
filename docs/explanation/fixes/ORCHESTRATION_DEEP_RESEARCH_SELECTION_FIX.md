# Balanced Deep Research Selection and Multi-query Execution

Fixed/Implemented in version: **0.261.099**

Application version reference: `application/single_app/config.py`.

## Issue and root cause

Orchestration described web search as the cheap default and permitted deep research only
when a shallow search could not cover the question. That framing made it harder to
consider useful exploratory breadth without treating ordinary search as incapable of
answering at all.

There was also an execution difference: orchestrated research reviewed existing source
URLs but did not invoke manual Deep Research's multi-query discovery helper. Merely
making research more likely would not connect that missing discovery stage.

These code-level findings do not establish why any particular deployed conversation
chose web search. Effective capabilities, roles, the saved plan, and the selected planner
deployment also affect an individual turn.

## Changes

| File | Change |
| --- | --- |
| `functions_orchestration_planner.py` | Weighs useful additional coverage and discovery against cost, and preserves the caller's capability gates when retrying an invalid clarification. |
| `functions_orchestration_registry.py` | Aligns web-search and deep-research descriptions with the balanced choice and self-contained research execution. |
| `functions_orchestration_adapters.py` | Runs bounded discovery before review, rechecks permissions before searches, preserves backup planning, and merges usable evidence without success-path fallback notices. |
| `route_backend_chats.py` | Adds backward-compatible progress/cancellation hooks and structured per-query outcomes to the existing research search loop. |
| `config.py` | Advances the application patch version to `0.261.099`. |

No research-selection keywords, new capability ids, admin settings, schema migrations,
or automatic post-search escalation loop are introduced. Existing query and crawl
limits remain unchanged.

The planner's invalid-clarification retry now retains `request_context`, so a retry
cannot lose a required role restriction after the initial plan was correctly gated.

Discovery uses the current request, including its server-resolved wording for a
follow-up, without forwarding the full conversation history or substituting the
planner step's arbitrary objective. Direct review seeds retain the server-owned
user-URL provenance list; rewriting a request does not authorize additional URLs.

## Recovery and evidence handling

Existing model-planned, supplemental, and backup queries remain available. When optional
query planning is unavailable or fails, research can still collect useful data using
the backup plan. Recovery details are logged; users do not receive an additional
fallback notice merely because a working research path used backup query generation.

Individual query failures do not contaminate successful source notes with provider
errors or instructions to announce an overall search failure. Usable search and reviewed
source evidence remains available, and reviewed citation metadata takes precedence when
the same URL was already found by search.

No-data outcomes remain explicit. The answer is told not to present details as verified
when research returned no usable evidence. Failed source review can retain search
evidence without exposing raw provider errors.

## Before and after

| Before | After |
| --- | --- |
| Research was framed mainly as necessary when shallow search could not answer. | The planner can consider substantial gains in discovery or evidence coverage while retaining inexpensive paths. |
| A research step needed supplied or previously discovered URLs. | It can perform bounded multi-query discovery before reviewing sources. |
| Missing research-planner configuration stopped the adapter before useful backup work. | Expected configuration failures leave shared backup query/link planning available. |
| Empty research could suggest running web search first. | Research includes discovery and reports the actual evidence/no-results outcome. |

More genres, a long prompt, or a request for current information does not automatically
require deep research. Creative requests such as a varied road-trip playlist can justify
either approach depending on the evidence and discovery needs; research selection alone
does not prove a better recommendation.

## Validation approach and limitations

`functional_tests/test_orchestration_deep_research.py` exercises the real adapter,
query generator, and shared search loop with controlled model/search/review seams. It
covers bounded discovery without initial URLs, deduplication, preserved backups,
logs-only recovery, role/feature gates, cancellation, useful partial evidence,
no-data outcomes, current-request-only outbound queries, resolved follow-ups, and
the separation between request interpretation and authorized user URLs.

`functional_tests/test_orchestration_research_selection.py` covers planner contracts
and balanced synthetic cases. Existing registry, phase-ordering, executor, query
planning, and web-search privacy coverage also applies. The privacy regression's stale
log-marker delimiter was aligned with the current logging tag so it inspects only the
outbound metadata block.

Offline contracts do not measure a live model's judgement or final answer quality.
Baseline/candidate evaluation must use the same approved deployment and cases, measure
both underuse and overuse, and avoid forcing ambiguous requests into deep research.
Network evaluation is opt-in; no production conversations are required.

For version **0.261.099**, all 52 focused planner/evaluator and research-execution tests
and 24 conversation-context integration tests pass.
No live model comparison or final-answer quality benchmark was run.

### Running the planner comparison

List the public synthetic cases and review rubric without constructing a model client:

```powershell
python .\scripts\evaluate_orchestration_research_planning.py
```

Before changing guidance, capture a baseline to a new file outside the checkout. Output
files are never overwritten:

```powershell
$baseline = Join-Path $env:TEMP 'simplechat-research-baseline.json'
python .\scripts\evaluate_orchestration_research_planning.py --mode capture --output $baseline
```

Live comparison requires an explicitly approved evaluation deployment, authentication
variable, and request cap. For example, the following compares only the playlist case
and permits at most four SDK requests, including response-format retries:

```powershell
$comparison = Join-Path $env:TEMP 'simplechat-research-comparison.json'
python .\scripts\evaluate_orchestration_research_planning.py --mode live `
    --baseline $baseline --output $comparison `
    --endpoint https://YOUR-EVAL.openai.azure.com --deployment YOUR-PLANNER `
    --api-version 2024-10-21 --api-key-env SIMPLECHAT_EVAL_KEY `
    --case original-playlist --call-cap 4 --repeat 1
```

Set the named authentication variable through your approved credential workflow; do not
put its value in a command or report. An explicitly supplied bearer-token variable can
be selected with `--entra-token-env` instead. Omitting `--case` selects all eleven cases,
requiring 22 primary planner requests per repetition plus any retries within the cap.

The report records raw and normalized choices, rationales, repairs, request usage,
observed durations, and operational failures. A human reviews the evidence-based rubric;
there is no automatic quota or grade that rewards choosing deep research. Both variants
use the same current planner runtime with different captured guidance. Even trivial
cases exercise planning here, so this is not a measurement of end-to-end chat latency.
Snapshots must have compatible capability contracts and planner parameters; capture
a new baseline when unrelated capability changes make an older snapshot incompatible.

## Related documentation

- [Chat orchestration](../features/CHAT_ORCHESTRATION.md)
- [Orchestration settings](../../admin/orchestration.md)
- [Use deep research](../../guides/use-deep-research.md)
