# test_orchestration_export_sources.py
"""
Authorized retained-result to shared-export integration.
Version: 0.261.126
Implemented in: 0.261.126

Uses real result persistence/readers and serializers with external storage and
source access doubled. Verifies full consumption, exact counts, explicit public
projections, revocation, and no replacement of authoritative data with previews.
"""

import csv
import hashlib
import io
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from functions_analysis_access import AnalysisResultUnavailable
from functions_generated_file_exports import GeneratedFileExportRequest, build_generated_file_export
from functions_generated_export_contracts import GeneratedFileExportError
from functions_orchestration_export_sources import (
    build_orchestration_export_source,
    build_saved_analysis_export_source,
    open_orchestration_export_source,
)
from functions_orchestration_result_contracts import RecordColumn, ResultContractError
from functions_orchestration_results import NamedOutput, SavedAnalysisRecordSource
from test_support.orchestration_results import (
    COLUMNS, ROWS, SOURCE_FREE_VALUE, ResultFixture, complete, native_analysis, source,
)


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"


def render(source_reader, output_format="json", profile="exact_records_v1", **kwargs):
    return build_generated_file_export(
        source=source_reader,
        export_request=GeneratedFileExportRequest(output_format, profile, **kwargs),
        max_output_bytes=32 * 1024 * 1024,
    )


def test_restart_reader_exports_complete_records_without_using_preview(monkeypatch):
    fixture = ResultFixture(blob=True)
    saved = fixture.save()
    reference = saved.output("findings")
    reader = fixture.restart().open_result(reference)

    def forbid_preview(*args, **kwargs):
        raise AssertionError("A preview is not an export source.")

    monkeypatch.setattr(reader, "preview", forbid_preview)
    bound = build_orchestration_export_source(reader)
    initial_uploads = len(fixture.blobs.uploads)
    with render(bound) as output:
        data = output.file_content.read()
        records = json.loads(data)
        bound.require_complete_consumption()
        actual_digest = hashlib.sha256(data).hexdigest()
        assert output.record_count == len(ROWS)
        assert output.content_sha256 == actual_digest
    assert records == ROWS
    assert records[-1]["id"] == "last"
    assert bound.reference == reference
    assert bound.columns == tuple(column.name for column in COLUMNS)
    assert bound.record_columns == COLUMNS
    assert bound.integrity_verified is True
    assert len(fixture.blobs.uploads) == initial_uploads


def test_column_selection_is_explicit_ordered_and_does_not_modify_the_result():
    fixture = ResultFixture()
    saved = fixture.save()
    columns = ["enabled", "id", "amount"]
    bound = open_orchestration_export_source(
        fixture.restart(), saved.output("findings"), columns=columns,
    )
    columns.reverse()
    with render(bound, "csv", "tabular_records_v1", columns=bound.columns) as output:
        rows = list(csv.reader(io.StringIO(output.file_content.read().decode("utf-8"))))
        bound.require_complete_consumption()
    original_reader = fixture.restart().open_result(saved.output("findings"))
    original = list(original_reader.iter_records())
    assert rows[0] == ["enabled", "id", "amount"]
    assert rows[1] == ["false", "001", "0"]
    assert rows[2][1].startswith("'=SUM(")
    assert rows[-1] == ["false", "last", ""]
    assert original == ROWS


@pytest.mark.parametrize("columns", [[], "id", ["id", "id"], ["missing"], [1], [" id"], {"id"}])
def test_invalid_column_selection_fails_without_inference(columns):
    fixture = ResultFixture()
    saved = fixture.save()
    with pytest.raises(GeneratedFileExportError) as failure:
        open_orchestration_export_source(
            fixture.service, saved.output("findings"), columns=columns,
        )
    assert failure.value.code == "invalid_options"


@pytest.mark.parametrize(
    ("kind", "output_format", "text"),
    [
        ("text-v1", "txt", "first\r\n  last \u4e2d\u6587 \U0001f30d\n"),
        ("markdown-v1", "md", "# Findings\n\n**last**: caf\u00e9\n"),
        ("text-v1", "txt", ""),
    ],
)
def test_prepared_text_uses_verified_character_count_not_a_counting_pass(
    kind, output_format, text, monkeypatch,
):
    fixture = ResultFixture(blob=True)
    saved = fixture.save(
        grounded=False, outputs=[NamedOutput("content", kind, text, complete(1))],
    )
    reader = fixture.restart().open_result(saved.output("content"))
    original = reader.iter_text
    calls = []

    def iterate():
        calls.append("read")
        yield from original()

    monkeypatch.setattr(reader, "iter_text", iterate)
    bound = build_orchestration_export_source(reader)
    assert calls == []
    assert bound.character_count == len(text)
    with render(bound, output_format, "prepared_text_v1") as output:
        actual = output.file_content.read().decode("utf-8")
        bound.require_complete_consumption()
        assert output.character_count == len(text)
    assert actual == text
    assert calls == ["read"]


@pytest.mark.parametrize("value", [SOURCE_FREE_VALUE, None, [], {}])
def test_structured_values_keep_their_exact_public_types(value):
    fixture = ResultFixture()
    saved = fixture.save(
        grounded=False,
        outputs=[NamedOutput("configuration", "structured-v1", value, complete(1))],
    )
    bound = open_orchestration_export_source(fixture.restart(), saved.output("configuration"))
    with render(bound, "json", "structured_value_v1") as output:
        actual = json.loads(output.file_content.read())
        bound.require_complete_consumption()
    assert actual == value
    assert bound.kind == "structured_value"


def test_value_materialization_limit_and_nonrecord_projection_fail_explicitly():
    fixture = ResultFixture()
    saved = fixture.save(
        grounded=False,
        outputs=[NamedOutput("value", "structured-v1", {"value": "x" * 2000}, complete(1))],
    )
    reference = saved.output("value")
    bound = open_orchestration_export_source(fixture.service, reference, max_value_bytes=100)
    with pytest.raises(ResultContractError) as failure:
        bound.read_value()
    assert failure.value.code == "result_requires_streaming"
    assert bound.integrity_verified is False
    with pytest.raises(GeneratedFileExportError) as failure:
        open_orchestration_export_source(fixture.service, reference, columns=["value"])
    assert failure.value.code == "invalid_options"


def test_preview_or_untrusted_reference_cannot_enter_the_export_boundary():
    fixture = ResultFixture()
    saved = fixture.save()
    reader = fixture.service.open_result(saved.output("findings"))
    preview = reader.preview()
    with pytest.raises(GeneratedFileExportError):
        build_orchestration_export_source(preview)
    with pytest.raises(GeneratedFileExportError):
        open_orchestration_export_source(fixture.service, saved.output("findings").to_dict())


def test_allowed_partial_reader_cannot_be_relabelled_as_complete_for_export():
    fixture = ResultFixture()
    saved = fixture.save(
        status="partial",
        outputs=[NamedOutput("findings", "records-v1", ROWS, complete(3, status="partial", expected=5), COLUMNS)],
    )
    reader = fixture.service.open_result(saved.output("findings"), allow_partial=True)
    with pytest.raises(GeneratedFileExportError) as failure:
        build_orchestration_export_source(reader)
    assert failure.value.code == "incomplete_source"


def test_a_partial_iteration_is_not_an_integrity_receipt():
    fixture = ResultFixture()
    saved = fixture.save()
    bound = open_orchestration_export_source(fixture.service, saved.output("findings"))
    records = bound.iter_records()
    first = next(records)
    records.close()
    assert first == ROWS[0]
    assert bound.integrity_verified is False
    with pytest.raises(GeneratedFileExportError) as failure:
        bound.require_complete_consumption()
    assert failure.value.code == "incomplete_source"
    complete_records = list(bound.iter_records())
    bound.require_complete_consumption()
    assert complete_records == ROWS


def test_access_revocation_prevents_render_and_invalidates_an_existing_receipt():
    fixture = ResultFixture()
    saved = fixture.save()
    bound = open_orchestration_export_source(fixture.service, saved.output("findings"))
    records = list(bound.iter_records())
    bound.require_complete_consumption()
    fixture.denied.add("document-1")
    with pytest.raises(PermissionError):
        bound.require_complete_consumption()
    with pytest.raises(PermissionError):
        render(bound)
    assert records == ROWS


def test_revocation_during_iteration_is_detected_at_exhaustion():
    fixture = ResultFixture()
    saved = fixture.save()
    bound = open_orchestration_export_source(fixture.service, saved.output("findings"))
    records = bound.iter_records()
    first = next(records)
    fixture.denied.add("document-1")
    with pytest.raises(PermissionError):
        list(records)
    assert first == ROWS[0]
    assert bound.integrity_verified is False


@pytest.mark.parametrize("field", ["record_count", "columns", "reference", "result_kind"])
def test_rebinding_reader_metadata_fails_instead_of_changing_the_export(field):
    fixture = ResultFixture()
    saved = fixture.save()
    reader = fixture.service.open_result(saved.output("findings"))
    bound = build_orchestration_export_source(reader)
    values = {
        "record_count": 2,
        "columns": COLUMNS[:2],
        "reference": replace(reader.reference, output_name="different"),
        "result_kind": "text-v1",
    }
    setattr(reader, field, values[field])
    with pytest.raises(GeneratedFileExportError):
        render(bound)
    assert bound.integrity_verified is False


def test_current_source_requirement_does_not_silently_replace_a_saved_snapshot():
    fixture = ResultFixture()
    saved = fixture.save(source_policy="snapshot")
    fixture.sources["document-1"]["source_revision"] = "revision-2"
    bound = open_orchestration_export_source(fixture.service, saved.output("findings"))
    records = list(bound.iter_records())
    bound.require_complete_consumption()
    assert records == ROWS
    with pytest.raises(AnalysisResultUnavailable):
        open_orchestration_export_source(
            fixture.service, saved.output("findings"), require_current_sources=True,
        )


@pytest.mark.parametrize("extra", [False, True])
def test_reader_count_mismatch_cannot_create_a_consumption_receipt(monkeypatch, extra):
    fixture = ResultFixture()
    saved = fixture.save()
    reader = fixture.service.open_result(saved.output("findings"))
    bound = build_orchestration_export_source(reader)

    def changed_rows():
        yield from ROWS if extra else ROWS[:-1]
        if extra:
            yield ROWS[-1]

    monkeypatch.setattr(reader, "iter_records", changed_rows)
    with pytest.raises(GeneratedFileExportError) as failure:
        list(bound.iter_records())
    assert failure.value.code == "count_mismatch"
    assert bound.integrity_verified is False


@pytest.mark.parametrize("fragments", [["short"], ["far too much text"], [None]])
def test_inexact_text_never_creates_a_consumption_receipt(monkeypatch, fragments):
    fixture = ResultFixture()
    saved = fixture.save(
        grounded=False, outputs=[NamedOutput("text", "text-v1", "complete", complete(1))],
    )
    reader = fixture.service.open_result(saved.output("text"))
    bound = build_orchestration_export_source(reader)

    def changed_text():
        yield from fragments

    monkeypatch.setattr(reader, "iter_text", changed_text)
    with pytest.raises(GeneratedFileExportError):
        list(bound.iter_text())
    assert bound.integrity_verified is False


@pytest.mark.parametrize("fail_read", [False, True])
def test_iterator_cleanup_does_not_hide_a_primary_access_failure(monkeypatch, fail_read):
    fixture = ResultFixture()
    saved = fixture.save()
    reader = fixture.service.open_result(saved.output("findings"))
    bound = build_orchestration_export_source(reader)
    closes = []

    class FailingCloseIterator:
        def __init__(self):
            self.rows = iter(ROWS)

        def __iter__(self):
            return self

        def __next__(self):
            if fail_read:
                raise PermissionError("Access was revoked.")
            return next(self.rows)

        def close(self):
            closes.append("closed")
            raise OSError("Cleanup failed.")

    monkeypatch.setattr(reader, "iter_records", FailingCloseIterator)
    expected_error = PermissionError if fail_read else OSError
    with pytest.raises(expected_error) as failure:
        list(bound.iter_records())
    assert closes == ["closed"]
    assert bound.integrity_verified is False
    if fail_read:
        assert "cleanup" in failure.value.__notes__[0]


@pytest.mark.parametrize("limit", [0, -1, True, "100", 8 * 1024 * 1024 + 1])
def test_structured_read_limits_are_explicit_not_coerced(limit):
    fixture = ResultFixture()
    saved = fixture.save()
    with pytest.raises(GeneratedFileExportError) as failure:
        open_orchestration_export_source(
            fixture.service, saved.output("findings"), max_value_bytes=limit,
        )
    assert failure.value.code == "invalid_limit"


def test_30000_retained_rows_render_twice_after_restart_without_rerunning_production():
    fixture = ResultFixture(blob=True)
    produced = []

    def rows():
        produced.append("once")
        for index in range(30000):
            yield {"id": f"{index:05}", "amount": index, "enabled": False, "detail": f"row-{index} " + "x" * 320}

    saved = fixture.save(
        grounded=False,
        outputs=[NamedOutput("dataset", "records-v1", rows(), complete(30000), COLUMNS)],
    )
    reference = saved.output("dataset")
    json_source = open_orchestration_export_source(fixture.restart(), reference)
    with render(json_source) as output:
        data = output.file_content.read()
        records = json.loads(data)
        json_source.require_complete_consumption()
        assert output.size_bytes == len(data)
        assert output.content_sha256 == hashlib.sha256(data).hexdigest()
    csv_source = open_orchestration_export_source(
        fixture.restart(), reference, columns=["amount", "id"],
    )
    with render(csv_source, "csv", "tabular_records_v1", columns=csv_source.columns) as output:
        table = list(csv.reader(io.StringIO(output.file_content.read().decode("utf-8"))))
        csv_source.require_complete_consumption()
        assert output.record_count == 30000
    assert reference.size_bytes > 8 * 1024 * 1024
    assert len(records) == 30000 and len(table) == 30001
    assert records[0]["id"] == "00000" and records[-1]["detail"].startswith("row-29999 ")
    assert table[1] == ["0", "00000"] and table[-1] == ["29999", "29999"]
    assert produced == ["once"]


def test_native_saved_analyze_keeps_its_reader_and_requires_explicit_coverage():
    # Import the saved-result owner only for this legacy integration, never in the bridge.
    from functions_saved_analysis import load_orchestration_analysis_input, save_orchestration_analysis

    fixture = ResultFixture()
    native = native_analysis(150)

    def authorize(user_id, binding):
        fixture.service.access.authorize_producer(fixture.producer)
        expected = {
            "kind": "orchestration", "user_id": "owner", "conversation_id": "conversation-1",
            "run_id": "run-1", "step_id": "analyze",
        }
        if user_id != "owner" or binding != expected:
            raise PermissionError("Unexpected native producer.")

    def save_result(user_id, conversation_id, run_id, step_id, value, *, settings):
        return fixture.service.store.save_orchestration(
            user_id, conversation_id, run_id, step_id, value,
        )

    descriptor = save_orchestration_analysis(
        {"analysis_result": native}, user_id="owner", conversation_id="conversation-1",
        run_id="run-1", step_id="analyze", settings={}, authorize_run=authorize,
        source_resolver=fixture.resolve, save_result=save_result,
    )
    reader, _ = load_orchestration_analysis_input(
        "owner", descriptor, authorize_run=authorize,
        load_result=fixture.restart().store.load_orchestration,
        source_resolver=fixture.resolve, bounded=True,
    )
    native_source = SavedAnalysisRecordSource(
        reader, columns=(RecordColumn("finding", "string"), RecordColumn("detail", "string")),
    )
    bound = build_saved_analysis_export_source(
        native_source, completeness=complete(150), columns=["finding"],
    )
    with render(bound, "csv", "tabular_records_v1", columns=bound.columns) as output:
        rows = list(csv.reader(io.StringIO(output.file_content.read().decode("utf-8"))))
        bound.require_complete_consumption()
    metadata = native_source.metadata()
    assert len(rows) == 151 and rows[-1] == ["Complete finding 149"]
    assert bound.reference is None
    assert metadata["sources"] == [source()]
    assert metadata["coverage"] == native["coverage"]
    with pytest.raises(GeneratedFileExportError):
        build_saved_analysis_export_source(
            native_source, completeness=complete(150, status="partial", expected=200),
        )
    with pytest.raises(GeneratedFileExportError):
        build_saved_analysis_export_source(native_source, completeness=complete(149))


@pytest.mark.parametrize("optimized", [False, True])
def test_cold_bridge_performs_required_reads_without_network_models_or_publication(optimized):
    probe = r'''
import builtins
import socket
import sys
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
real_import = builtins.__import__
forbidden = {"config", "functions_settings", "functions_saved_analysis", "functions_simplechat_operations", "functions_artifact_publication"}
attempts = []
def no_network(*args, **kwargs):
    attempts.append(True)
    raise AssertionError("Unexpected external I/O")
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and (name in forbidden or name.startswith("route_")):
        raise AssertionError("Unexpected owner or publication import: " + name)
    return real_import(name, globals, locals, fromlist, level)
with patch.object(socket.socket, "connect", no_network), patch.object(builtins, "__import__", guarded_import):
    from test_support.orchestration_results import ResultFixture, ROWS
    from functions_orchestration_export_sources import open_orchestration_export_source
    from functions_generated_file_exports import GeneratedFileExportRequest, build_generated_file_export
    fixture = ResultFixture(blob=True)
    saved = fixture.save(grounded=False)
    source = open_orchestration_export_source(fixture.restart(), saved.output("findings"))
    output = build_generated_file_export(
        source=source, export_request=GeneratedFileExportRequest("json"), max_output_bytes=100000,
    )
    import json
    with output:
        records = json.loads(output.file_content.read())
        source.require_complete_consumption()
    if records != ROWS or not source.integrity_verified or not fixture.blobs.uploads:
        raise AssertionError("Required full persistence/read/validation disappeared")
    fixture.conversation["orchestration_deleted"] = True
    try:
        source.require_complete_consumption()
    except PermissionError:
        pass
    else:
        raise AssertionError("Deleted conversation remained authorized")
    if attempts or forbidden.intersection(sys.modules):
        raise AssertionError("A forbidden dependency or network attempt was hidden")
print("PASS: complete, authorized exports without implicit publication")
'''
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    process = subprocess.run(
        [*command, "-c", probe, str(APP), str(TESTS)],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert process.returncode == 0, process.stdout[-8000:] + process.stderr[-8000:]
    assert "PASS:" in process.stdout
