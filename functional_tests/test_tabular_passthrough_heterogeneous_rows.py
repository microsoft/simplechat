# test_tabular_passthrough_heterogeneous_rows.py
#!/usr/bin/env python3
"""
Functional test for heterogeneous passthrough rows in background CSV exports.
Version: 0.260.004
Implemented in: 0.260.004

Chat and workflow CSV artifacts queue already-final rows with
passthrough_input_rows=True. When those rows come from more than one action
result -- or from records with optional fields -- the per-row field sets
differ. The background export used to derive its schema from the first row
only, hard-fail with "Generated output schema mismatch at row 2", requeue the
run as a model-validation failure, and eventually fail permanently even though
no model is involved in a passthrough run.

This test calls the *real* queue_tabular_generated_output_run() and the *real*
_build_passthrough_batch_results() (extracted from
functions_tabular_generated_exports.py via AST, with only genuine I/O
boundaries stubbed) to ensure the union output schema is pinned at queue time
and sparse rows are padded instead of rejected.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_tabular_queue_run_output_schema_end_to_end import (  # noqa: E402
    EXPORT_MODULE,
    _build_namespace,
    _collect_local_closure,
    _module_node_name,
    _resolve_cross_module_names,
)

IMPLEMENTED_VERSION = "0.260.004"

LINEAGE_SCHEMA = ["source_row_number", "source_row_identity"]

# Two action results merged into one chat CSV artifact: the first group carries a
# "facts" column, the second carries an entirely different telemetry envelope.
HETEROGENEOUS_ROWS = [
    {"name": "simulator", "facts": "1 instance online"},
    {
        "application": "yamcs",
        "schema_version": "1.0",
        "runtime": "realtime",
        "message_metadata": "BatteryVoltage1",
    },
    {"name": "simulator", "facts": "still online", "runtime": "realtime"},
]

EXPECTED_PUBLIC_SCHEMA = [
    "name",
    "facts",
    "application",
    "schema_version",
    "runtime",
    "message_metadata",
]


def _build_passthrough_namespace():
    """Extend the real queue-function namespace with the real passthrough helpers."""
    namespace, fake_container = _build_namespace()
    tree = ast.parse(EXPORT_MODULE.read_text(encoding="utf-8"), filename=str(EXPORT_MODULE))
    included, unresolved = _collect_local_closure(
        tree,
        {"_build_passthrough_batch_results", "_prepare_tabular_source_rows"},
    )
    still_needed = {name for name in unresolved if name not in namespace}
    resolved_cross_module, still_unresolved = _resolve_cross_module_names(still_needed)
    namespace.update(resolved_cross_module)
    if still_unresolved:
        raise AssertionError(
            f"Could not resolve required names for the passthrough checkpoint test: {sorted(still_unresolved)}"
        )

    included_names = set(included)
    ordered_nodes = [node for node in tree.body if _module_node_name(node) in included_names]
    module = ast.Module(body=ordered_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(EXPORT_MODULE), "exec"), namespace)
    return namespace, fake_container


def _queue_passthrough_run(namespace, row_batches):
    return namespace["queue_tabular_generated_output_run"](
        user_id="user-1",
        conversation_id="conversation-1",
        user_question="generate a csv",
        source_candidate={
            "filename": "generated_output_20260819_152402.csv",
            "selected_sheet": "",
            "source_authorization": {"source": "chat"},
        },
        output_format="csv",
        row_batches=row_batches,
        gpt_model="",
        settings={},
        passthrough_input_rows=True,
    )


def test_queue_pins_union_schema_for_heterogeneous_passthrough_rows():
    """The union of every staged passthrough column must be locked before batch 1 runs."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    namespace, fake_container = _build_passthrough_namespace()

    run = _queue_passthrough_run(namespace, [HETEROGENEOUS_ROWS[:2], HETEROGENEOUS_ROWS[2:]])

    assert fake_container.created_items, "the real queue function must create one Cosmos run item"
    persisted_run = fake_container.created_items[0]
    assert persisted_run["passthrough_input_rows"] is True
    assert persisted_run["public_output_schema"] == EXPECTED_PUBLIC_SCHEMA, (
        "columns from every staged batch must be unioned, not taken from the first row; "
        f"got {persisted_run['public_output_schema']!r}"
    )
    assert persisted_run["output_schema"] == LINEAGE_SCHEMA + EXPECTED_PUBLIC_SCHEMA
    assert persisted_run["internal_checkpoint_schema"] == LINEAGE_SCHEMA + EXPECTED_PUBLIC_SCHEMA
    assert run["output_schema"] == persisted_run["output_schema"]


def test_model_backed_runs_still_defer_schema_discovery():
    """Non-passthrough runs must keep deferring to batch-1 schema discovery."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    namespace, fake_container = _build_passthrough_namespace()

    namespace["queue_tabular_generated_output_run"](
        user_id="user-1",
        conversation_id="conversation-1",
        user_question="summarize each row as a csv",
        source_candidate={"filename": "source_rows.csv", "selected_sheet": ""},
        output_format="csv",
        row_batches=[HETEROGENEOUS_ROWS],
        gpt_model="gpt-5.6-luna",
        settings={},
        passthrough_input_rows=False,
    )

    persisted_run = fake_container.created_items[0]
    assert persisted_run["output_schema"] is None, (
        "model-generated runs must still discover their schema from batch 1; "
        f"got {persisted_run['output_schema']!r}"
    )
    assert persisted_run["public_output_schema"] == []


def test_passthrough_checkpoints_pad_sparse_rows():
    """Sparse passthrough rows must be padded to the pinned schema, never rejected."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    namespace, _ = _build_passthrough_namespace()
    run = _queue_passthrough_run(namespace, [HETEROGENEOUS_ROWS])

    prepared_rows = namespace["_prepare_tabular_source_rows"](
        HETEROGENEOUS_ROWS,
        start_row=0,
        token_namespace=run["id"],
    )
    generated_results = namespace["_build_passthrough_batch_results"](
        run,
        [{"batch_number": 1, "rows": prepared_rows}],
    )

    assert len(generated_results) == 1
    batch_entries = generated_results[0]["batch_entries"]
    assert generated_results[0]["output_schema"] == run["output_schema"]
    assert len(batch_entries) == len(HETEROGENEOUS_ROWS)
    for row_index, entry in enumerate(batch_entries, start=1):
        assert list(entry) == run["output_schema"], (
            f"row {row_index} must be checkpointed with the exact pinned schema; got {list(entry)!r}"
        )
        assert entry["source_row_number"] == row_index

    assert batch_entries[0]["facts"] == "1 instance online"
    assert batch_entries[0]["application"] == "", "missing columns must be padded, not dropped"
    assert batch_entries[1]["message_metadata"] == "BatteryVoltage1"
    assert batch_entries[1]["facts"] == ""
    assert batch_entries[2]["runtime"] == "realtime"


def test_passthrough_batch_unions_rows_when_schema_is_not_pinned():
    """Runs queued before the fix have no pinned schema and must still checkpoint cleanly."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    namespace, _ = _build_passthrough_namespace()
    legacy_run = {"output_schema": None}

    prepared_rows = namespace["_prepare_tabular_source_rows"](
        HETEROGENEOUS_ROWS,
        start_row=0,
        token_namespace="legacy-run",
    )
    generated_results = namespace["_build_passthrough_batch_results"](
        legacy_run,
        [{"batch_number": 1, "rows": prepared_rows}],
    )

    output_schema = generated_results[0]["output_schema"]
    assert output_schema == LINEAGE_SCHEMA + EXPECTED_PUBLIC_SCHEMA
    for entry in generated_results[0]["batch_entries"]:
        assert list(entry) == output_schema


if __name__ == "__main__":
    tests = [
        test_queue_pins_union_schema_for_heterogeneous_passthrough_rows,
        test_model_backed_runs_still_defer_schema_discovery,
        test_passthrough_checkpoints_pad_sparse_rows,
        test_passthrough_batch_unions_rows_when_schema_is_not_pinned,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("  passed")
            results.append(True)
        except Exception as exc:
            print(f"  failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
