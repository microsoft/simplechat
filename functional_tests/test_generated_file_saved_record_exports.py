# test_generated_file_saved_record_exports.py
"""
Functional regression tests for shared exact saved-record exports.
Version: 0.261.119
Implemented in: 0.261.119

Validate complete deterministic JSON, strict format/type/count boundaries,
bounded streaming, cancellation, and cleanup without any external service.
"""

import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_generated_file_exports import (  # noqa: E402
    GeneratedFileExportRequest,
    GeneratedFileExportStream,
    build_generated_file_export,
)


class RecordSource:
    kind = "records"

    def __init__(self, records, count):
        self.records = records
        self.record_count = count
        self.reads = 0
        self.checks = 0

    def iter_records(self):
        for record in self.records:
            self.reads += 1
            yield record

    def recheck(self):
        self.checks += 1


def render(source, *, limit=1024 * 1024, output_format="json", profile="exact_records_v1", check=None):
    return build_generated_file_export(
        source=source, export_request=GeneratedFileExportRequest(output_format, profile),
        max_output_bytes=limit, check=check,
    )


def test_exact_saved_values_order_multiplicity_and_digest():
    repeated = {"values": {"b": None, "a": [False, 0, "\u03bb", {"nested": "a\nb"}]}, "evidence": ["original"]}
    records = [repeated, {"middle-only": "\U0001f600", "integer": 9007199254740993}, repeated]
    source = RecordSource(iter(records), len(records))
    expected = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    with render(source, limit=len(expected)) as exported:
        assert isinstance(exported, GeneratedFileExportStream)
        assert exported.file_content.read() == expected
        assert exported.record_count == len(records)
        assert exported.content_sha256 == hashlib.sha256(expected).hexdigest()
        assert exported.size_bytes == len(expected)
        assert exported.media_type == "application/json"
    assert exported.file_content.closed
    assert source.reads == 3 and source.checks == 2


@pytest.mark.parametrize("count", [0, 1, 100, 101, 10001])
def test_every_record_is_streamed_without_a_preview_limit(count):
    source = RecordSource(({"ordinal": index} for index in range(count)), count)
    with render(source) as exported:
        values = json.load(exported.file_content)
        assert values == [{"ordinal": index} for index in range(count)]
        assert source.reads == count and exported.record_count == count


def test_collection_over_materialization_bound_uses_incremental_reads():
    count = 1100
    source = RecordSource(({"index": index, "value": "x" * 8192} for index in range(count)), count)
    checks = []
    with render(source, limit=10 * 1024 * 1024, check=lambda: checks.append(source.reads)) as exported:
        assert exported.size_bytes > 8 * 1024 * 1024
        digest = hashlib.sha256()
        for chunk in iter(lambda: exported.file_content.read(65536), b""):
            digest.update(chunk)
        assert digest.hexdigest() == exported.content_sha256
        assert 100 < len(checks) < 200


@pytest.mark.parametrize("output_format", ["csv", "md", "docx", "pdf", "pptx", "xml", "JSON", ""])
def test_no_unsupported_format_falls_back_to_json(output_format):
    source = RecordSource([{"a": 1}], 1)
    with pytest.raises(ValueError, match="not supported"):
        render(source, output_format=output_format)
    assert source.reads == source.checks == 0


@pytest.mark.parametrize("limit", [None, True, 0, -1, 1.5])
def test_explicit_sources_require_a_positive_integer_byte_limit(limit):
    source = RecordSource([{"value": 1}], 1)
    with pytest.raises(ValueError, match="byte limit"):
        render(source, limit=limit)
    assert source.reads == source.checks == 0


@pytest.mark.parametrize("invalid", ["missing_source", "missing_request", "competing_analysis"])
def test_explicit_source_selection_never_falls_back_to_response_rendering(invalid):
    source = RecordSource([{"value": 1}], 1)
    options = {
        "source": source, "export_request": GeneratedFileExportRequest("json"),
        "max_output_bytes": 1024,
    }
    if invalid == "missing_source":
        options.pop("source")
    elif invalid == "missing_request":
        options.pop("export_request")
    else:
        options["analysis_result"] = {}
    with pytest.raises(ValueError, match="exactly one saved source"):
        build_generated_file_export("create a CSV", "Do not export this summary.", **options)
    assert source.reads == source.checks == 0


@pytest.mark.parametrize("value", [
    {1: "not-a-string-key"}, {"value": object()}, {"value": float("nan")},
    {"value": float("inf")}, {"value": (1, 2)}, "not-an-object", None,
])
def test_non_json_or_non_record_values_are_rejected(value):
    with pytest.raises(ValueError):
        render(RecordSource([value], 1))


@pytest.mark.parametrize("records,count", [([{"a": 1}], 0), ([], 1), ([{"a": 1}], 2)])
def test_count_mismatch_never_returns_a_prefix(records, count):
    with pytest.raises(ValueError, match="count"):
        render(RecordSource(records, count))


def test_quota_counts_delimiters_and_escaped_bytes():
    records = [{"text": "\u03bb" * 20}, {"text": ""}]
    expected = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    with render(RecordSource(records, 2), limit=len(expected)) as exported:
        assert exported.size_bytes == len(expected)
    with pytest.raises(ValueError, match="size limit"):
        render(RecordSource(records, 2), limit=len(expected) - 1)
    with render(RecordSource([], 0), limit=2) as exported:
        assert exported.file_content.read() == b"[]"
    with pytest.raises(ValueError, match="size limit"):
        render(RecordSource([], 0), limit=1)


def test_failure_and_cancellation_close_private_temporary_output(monkeypatch):
    import functions_generated_file_exports as exports

    original = exports.tempfile.TemporaryFile
    opened = []

    def tracked(*args, **kwargs):
        stream = original(*args, **kwargs)
        opened.append(stream)
        return stream

    monkeypatch.setattr(exports.tempfile, "TemporaryFile", tracked)
    source = RecordSource(({"a": index} for index in range(500)), 500)

    def cancel():
        if source.reads >= 100:
            raise PermissionError("run no longer owned")

    with pytest.raises(PermissionError):
        render(source, check=cancel)
    assert source.reads == 100 and all(stream.closed for stream in opened)
    with pytest.raises(ValueError):
        render(RecordSource([{"a": "large"}], 1), limit=2)
    assert len(opened) == 2 and all(stream.closed for stream in opened)


def test_final_authorization_failure_does_not_return_artifact():
    source = RecordSource([{"a": 1}], 1)

    def revoke():
        source.checks += 1
        if source.checks > 1:
            raise PermissionError("source revoked")

    source.recheck = revoke
    with pytest.raises(PermissionError):
        render(source)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
