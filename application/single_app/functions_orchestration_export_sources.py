# functions_orchestration_export_sources.py
"""Bind authorized retained readers to the shared export source protocols.

This boundary neither resolves model-supplied storage references nor publishes
files. Callers first open a result through its owning authorization service. A
renderer must exhaust the reader, and the publication boundary must call
``require_complete_consumption`` before accepting its output stream. Create a
fresh binding for each rendering attempt rather than sharing one across workers.
"""

from collections.abc import Iterator
from typing import Any

from functions_export_cleanup import ClosingExportResource
from functions_generated_export_contracts import (
    GeneratedFileExportError,
    GeneratedFileExportReadiness,
)
from functions_orchestration_result_contracts import (
    Completeness,
    RecordColumn,
    ResultRef,
    validate_columns,
)
from functions_orchestration_results import (
    MAX_VALUE_BYTES,
    OrchestrationResultReader,
    OrchestrationResults,
    SavedAnalysisRecordSource,
)


_SOURCE_KINDS = {
    "records-v1": "records",
    "text-v1": "text",
    "markdown-v1": "markdown",
    "structured-v1": "structured_value",
    "comparison-v1": "structured_value",
}
_Reader = OrchestrationResultReader | SavedAnalysisRecordSource


class OrchestrationExportSource:
    """Server-side source binding with a separate full-consumption receipt."""

    def __init__(self, reader: _Reader, kind: str, completeness: Completeness | None = None):
        self._reader = reader
        self._kind = kind
        self._reference = (
            reader.reference if isinstance(reader, OrchestrationResultReader) else None
        )
        self._schema = self._reference.columns if self._reference is not None else reader.columns
        self._completeness = (
            self._reference.completeness if self._reference is not None else completeness
        )
        if type(self._completeness) is not Completeness:
            raise GeneratedFileExportError(
                "invalid_source", "An explicit retained-source completeness contract is required."
            )
        self._verified = False
        self.recheck()

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def reference(self) -> ResultRef | None:
        return self._reference

    @property
    def readiness(self) -> GeneratedFileExportReadiness:
        completeness = self._completeness
        return GeneratedFileExportReadiness(
            state="ready" if completeness.status == "complete" else completeness.status,
            is_complete=completeness.status == "complete",
            is_preview=completeness.preview,
        )

    @property
    def integrity_verified(self) -> bool:
        return self._verified

    def recheck(self) -> None:
        if isinstance(self._reader, OrchestrationResultReader):
            if (
                self._reference is None
                or self._reader.reference != self._reference
                or self._reader.result_kind != self._reference.kind
                or self._reader.completeness != self._reference.completeness
                or self._reader.kind != (
                    "records" if self._reference.kind == "records-v1" else self._reference.kind
                )
            ):
                raise GeneratedFileExportError(
                    "invalid_source", "The retained source binding changed."
                )
        if self._reader.columns != self._schema:
            raise GeneratedFileExportError(
                "invalid_source", "The retained source schema changed."
            )
        readiness = self.readiness
        if (
            readiness.state != "ready"
            or readiness.is_complete is not True
            or readiness.is_preview is not False
        ):
            raise GeneratedFileExportError(
                "incomplete_source",
                "Rendering requires a complete retained result, not a partial result or preview.",
            )
        self._reader.recheck()

    def require_complete_consumption(self) -> None:
        self.recheck()
        if not self._verified:
            raise GeneratedFileExportError(
                "incomplete_source", "The complete retained input has not been consumed."
            )


class _RecordExportSource(OrchestrationExportSource):
    def __init__(self, reader: _Reader, columns, completeness: Completeness | None = None):
        reference = reader.reference if isinstance(reader, OrchestrationResultReader) else None
        self._record_count = reference.item_count if reference is not None else reader.record_count
        schema = reference.columns if reference is not None else reader.columns
        validate_columns(schema, "records-v1")
        available = {column.name: column for column in schema}
        if columns is None:
            selected = tuple(available)
        else:
            if (
                type(columns) not in (list, tuple)
                or not columns
                or any(type(name) is not str for name in columns)
                or len(set(columns)) != len(columns)
                or any(name not in available for name in columns)
            ):
                raise GeneratedFileExportError(
                    "invalid_options", "Columns must name distinct retained public fields."
                )
            selected = tuple(columns)
        self._columns = selected
        self._record_columns = tuple(available[name] for name in selected)
        super().__init__(reader, "records", completeness)

    @property
    def record_count(self) -> int:
        return self._record_count

    @property
    def columns(self) -> tuple[str, ...]:
        return self._columns

    @property
    def record_columns(self) -> tuple[RecordColumn, ...]:
        return self._record_columns

    def recheck(self) -> None:
        super().recheck()
        if (
            type(self._reader.record_count) is not int
            or self._reader.record_count < 0
            or self._reader.record_count != self._record_count
            or self._completeness.actual_count != self._record_count
        ):
            raise GeneratedFileExportError(
                "count_mismatch", "The retained source count changed."
            )

    def iter_records(self) -> Iterator[dict[str, Any]]:
        self.recheck()
        self._verified = False
        count = 0
        with ClosingExportResource(self._reader.iter_records()) as records:
            for record in records:
                count += 1
                if count > self._record_count:
                    raise GeneratedFileExportError(
                        "count_mismatch", "The retained reader returned too many records."
                    )
                yield {name: record[name] for name in self._columns}
        if count != self._record_count:
            raise GeneratedFileExportError(
                "count_mismatch", "The retained reader did not return every declared record."
            )
        self.recheck()
        self._verified = True


class _TextExportSource(OrchestrationExportSource):
    def __init__(self, reader: OrchestrationResultReader, kind: str):
        self._character_count = reader.reference.character_count
        super().__init__(reader, kind)

    @property
    def character_count(self) -> int:
        return self._character_count

    def recheck(self) -> None:
        super().recheck()
        if (
            type(self._reader.character_count) is not int
            or self._reader.character_count != self._character_count
        ):
            raise GeneratedFileExportError(
                "count_mismatch", "The retained text count changed."
            )

    def iter_text(self) -> Iterator[str]:
        self.recheck()
        self._verified = False
        count = 0
        with ClosingExportResource(self._reader.iter_text()) as fragments:
            for fragment in fragments:
                if type(fragment) is not str:
                    raise GeneratedFileExportError(
                        "invalid_data", "Retained text fragments must be strings."
                    )
                count += len(fragment)
                if count > self._character_count:
                    raise GeneratedFileExportError(
                        "count_mismatch", "The retained reader returned too much text."
                    )
                yield fragment
        if count != self._character_count:
            raise GeneratedFileExportError(
                "count_mismatch", "The retained reader did not return all declared text."
            )
        self.recheck()
        self._verified = True


class _ValueExportSource(OrchestrationExportSource):
    def __init__(self, reader: OrchestrationResultReader, max_value_bytes: int):
        self._max_value_bytes = max_value_bytes
        super().__init__(reader, "structured_value")

    def read_value(self) -> Any:
        self.recheck()
        self._verified = False
        value = self._reader.read_value(max_bytes=self._max_value_bytes)
        self.recheck()
        self._verified = True
        return value


def build_orchestration_export_source(
    reader: OrchestrationResultReader,
    *,
    columns: tuple[str, ...] | list[str] | None = None,
    max_value_bytes: int = MAX_VALUE_BYTES,
) -> OrchestrationExportSource:
    """Adapt a real reader; column selection never flattens or changes row order."""
    if not isinstance(reader, OrchestrationResultReader):
        raise GeneratedFileExportError(
            "invalid_source", "An authorized retained-result reader is required."
        )
    if type(reader.reference) is not ResultRef:
        raise GeneratedFileExportError(
            "invalid_source", "A trusted retained-result reference is required."
        )
    kind = _SOURCE_KINDS.get(reader.reference.kind)
    if kind is None:
        raise GeneratedFileExportError(
            "unsupported_source", "This result needs an explicit supported representation."
        )
    if columns is not None and kind != "records":
        raise GeneratedFileExportError(
            "invalid_options", "Only records support public-column selection."
        )
    if type(max_value_bytes) is not int or not 1 <= max_value_bytes <= MAX_VALUE_BYTES:
        raise GeneratedFileExportError(
            "invalid_limit", "The structured-value read limit must be within the retained-reader bound."
        )
    if kind == "records":
        return _RecordExportSource(reader, columns)
    if kind in {"text", "markdown"}:
        return _TextExportSource(reader, kind)
    return _ValueExportSource(reader, max_value_bytes)


def open_orchestration_export_source(
    service: OrchestrationResults,
    reference: ResultRef,
    *,
    columns: tuple[str, ...] | list[str] | None = None,
    max_value_bytes: int = MAX_VALUE_BYTES,
    require_current_sources: bool = False,
) -> OrchestrationExportSource:
    """Open under current access; never opt a partial result into a full export."""
    if not isinstance(service, OrchestrationResults) or type(reference) is not ResultRef:
        raise GeneratedFileExportError(
            "invalid_source", "A retained-result service and trusted reference are required."
        )
    reader = service.open_result(
        reference, require_current_sources=require_current_sources,
    )
    return build_orchestration_export_source(
        reader, columns=columns, max_value_bytes=max_value_bytes,
    )


def build_saved_analysis_export_source(
    source: SavedAnalysisRecordSource,
    *,
    completeness: Completeness,
    columns: tuple[str, ...] | list[str] | None = None,
) -> OrchestrationExportSource:
    """Use owner-validated native coverage without fabricating a generic ResultRef.

    A successful legacy result and its record count alone are not proof of full
    source coverage. Its owner must validate that coverage into ``completeness``.
    """
    if not isinstance(source, SavedAnalysisRecordSource):
        raise GeneratedFileExportError(
            "invalid_source", "An authorized complete saved-Analyze source is required."
        )
    return _RecordExportSource(source, columns, completeness)
