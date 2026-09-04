#!/usr/bin/env python3
"""
Functional test for orchestration treating a selected prompt as an instruction.
Version: 0.261.090
Implemented in: 0.261.090

A saved prompt is a standing instruction: it says what kind of work this is. Orchestration used
to be told only its name. "Quarterly review" says nothing about whether the work involves
reading documents, searching the web, or comparing two things -- which is exactly what the plan
has to decide -- and `triage_request` did not count a selected prompt as a signal at all, so
reaching for a stored set of instructions could still be triaged as a remark to answer off the
cuff.

Three things follow, and this test holds each of them:

  1. The planner is shown the prompt's wording, capped so an unbounded saved prompt cannot
     consume the planner's budget.
  2. A selected prompt makes a request non-trivial, alongside a chosen document or agent.
  3. The stored plan names the prompt rather than quoting it. The plan document is kept and
     shown, and the wording is already in the message the plan was built from.

The orchestration modules import `config`, which builds Azure clients at import time, so the
functions under test are extracted and executed rather than imported.
"""

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

CONTEXT_PY = APP_DIR / "functions_orchestration_context.py"
PLANNER_PY = APP_DIR / "functions_orchestration_planner.py"
SCHEMA_PY = APP_DIR / "functions_orchestration_schema.py"


def _extract(path, names, seed=None):
    """Execute selected top-level definitions from a module without importing it.

    ``functions_orchestration_context`` imports ``config``, which constructs Azure clients on
    import. Only the pure helpers are needed here, so they are lifted out of the parsed module
    and executed against a namespace this function controls.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wanted = set(names)
    body = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            body.append(node)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            # Module constants the extracted functions close over.
            if any(name.isupper() for name in targets):
                body.append(node)

    namespace = dict(seed or {})
    # The extracted constants are built from module-level imports this deliberately does not
    # provide, so the few they actually need are supplied here.
    namespace.setdefault("re", re)
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), namespace)

    missing = wanted - set(namespace)
    assert not missing, f"could not extract {missing} from {path.name}"
    return namespace


def test_version_is_at_least_the_implementing_release():
    print("Testing version...")
    assert_app_version_at_least("0.261.090")
    print("  ok  version is at or past the implementing release")
    return True


def test_the_planner_is_shown_the_prompts_wording():
    """A name alone does not say what kind of work the plan has to arrange."""
    print("Testing planner context...")

    module = _extract(CONTEXT_PY, {"_text", "_selected_prompt"})
    selected_prompt = module["_selected_prompt"]
    limit = module["SELECTED_PROMPT_LENGTH"]

    resolved = selected_prompt({"prompt": {"name": "Quarterly review", "content": "Compare A to B."}})
    assert resolved == {"name": "Quarterly review", "content": "Compare A to B."}, (
        f"the planner must see both the name and the wording, got {resolved}"
    )

    # Capped rather than sent whole: a saved prompt has no length limit, the planner's budget
    # does, and a prompt long enough to be cut has said what kind of work it is well before it.
    long_prompt = selected_prompt({"prompt": {"name": "Long", "content": "x" * (limit + 500)}})
    assert len(long_prompt["content"]) <= limit, (
        f"the prompt wording must be capped at {limit} characters"
    )

    print("  ok  the planner is shown the wording, capped")
    return True


def test_no_prompt_reads_as_no_prompt():
    """`triage_request` tests this the same way it tests the other selections."""
    print("Testing absent prompts...")

    module = _extract(CONTEXT_PY, {"_text", "_selected_prompt"})
    selected_prompt = module["_selected_prompt"]

    assert selected_prompt({}) is None, "no prompt must read as None, not an empty dict"
    assert selected_prompt({"prompt": None}) is None
    assert selected_prompt({"prompt": "not a dict"}) is None, (
        "a malformed seed must not become a truthy selection"
    )
    assert selected_prompt({"prompt": {"name": "", "content": "  "}}) is None, (
        "an empty prompt must not read as a selection"
    )

    print("  ok  an absent or empty prompt reads as none")
    return True


def test_a_selected_prompt_makes_the_request_non_trivial():
    """Reaching for stored instructions is a statement that this work has a shape."""
    print("Testing triage...")

    module = _extract(
        PLANNER_PY,
        {"triage_request"},
        seed={
            "COMPLEXITY_TRIVIAL": "trivial",
            "COMPLEXITY_SIMPLE": "simple",
            "COMPLEXITY_COMPLEX": "complex",
        },
    )
    triage = module["triage_request"]

    bare = {"user_selected": {}}
    assert triage("hi", bare) == "trivial", (
        "a remark with nothing selected must still be trivial, or every message plans"
    )

    with_prompt = {"user_selected": {"prompt": {"name": "Quarterly review", "content": "..."}}}
    assert triage("hi", with_prompt) == "complex", (
        "a selected prompt must count as pointing at something, like a document or an agent"
    )

    # The signals it already honoured must not have been displaced by the new one.
    for signal, value in (
        ("documents", ["doc-1"]),
        ("agent", "Researcher"),
        ("web_search", True),
    ):
        assert triage("hi", {"user_selected": {signal: value}}) == "complex", (
            f"the existing {signal} signal must still make a request complex"
        )

    print("  ok  a selected prompt makes the request complex")
    return True


def test_the_stored_plan_names_the_prompt_rather_than_quoting_it():
    """The plan document is kept and shown; the wording is already in the message."""
    print("Testing plan inputs...")

    module = _extract(SCHEMA_PY, {"build_plan_inputs"})
    build_plan_inputs = module["build_plan_inputs"]

    seeds = {
        "prompt": {
            "id": "p1",
            "name": "Quarterly review",
            "content": "A very long standing instruction." * 50,
            "user_text": "For Q3.",
        }
    }
    inputs = build_plan_inputs({"steps": []}, seeds=seeds)

    assert inputs["prompt"] == {"id": "p1", "name": "Quarterly review"}, (
        f"the plan must name the prompt and nothing more, got {inputs['prompt']}"
    )

    assert build_plan_inputs({"steps": []}, seeds={})["prompt"] is None, (
        "a plan built without a prompt must not claim one"
    )

    print("  ok  the stored plan names the prompt")
    return True


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_the_planner_is_shown_the_prompts_wording,
        test_no_prompt_reads_as_no_prompt,
        test_a_selected_prompt_makes_the_request_non_trivial,
        test_the_stored_plan_names_the_prompt_rather_than_quoting_it,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as error:  # noqa: BLE001
            print(f"  FAIL  {test.__name__}: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
