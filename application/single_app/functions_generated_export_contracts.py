# functions_generated_export_contracts.py
"""Pure contracts for complete, authorized generated-file serialization."""

from dataclasses import dataclass, field
from typing import Any, BinaryIO, Dict, Iterator, Optional, Protocol, Tuple, Union


@dataclass(frozen=True)
class GeneratedFileExportRequest:
    output_format: str
    profile: str = 'exact_records_v1'
    columns: Optional[Tuple[str, ...]] = None
    title: Optional[str] = None
    sheet_name: Optional[str] = None


@dataclass(frozen=True)
class GeneratedFileExportReadiness:
    """Only ready, complete, non-preview inputs have a serialization profile."""

    state: str = 'ready'
    is_complete: bool = True
    is_preview: bool = False


@dataclass(frozen=True)
class GeneratedFileExportLimits:
    """Caller-adjustable bounds, independent of application configuration."""

    max_records: int = 1_000_000
    max_value_bytes: int = 8 * 1024 * 1024
    max_value_nodes: int = 100_000
    max_depth: int = 64
    max_text_chunks: int = 1_000_000


class GeneratedFileExportError(ValueError):
    """A deterministic, non-retryable serialization or contract failure."""

    retryable = False

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class GeneratedRecordExportSource(Protocol):
    """Keep the existing reader seam; recheck must also enforce completeness.

    Legacy adapters need not expose readiness. If supplied, readiness must be a
    GeneratedFileExportReadiness and is checked throughout serialization.
    """

    kind: str
    record_count: int

    def iter_records(self) -> Iterator[Dict[str, Any]]: ...

    def recheck(self) -> None: ...


class GeneratedStructuredValueExportSource(Protocol):
    """A bounded complete JSON-domain value, read once, never reconstructed."""

    kind: str  # structured_value
    readiness: GeneratedFileExportReadiness

    def read_value(self) -> Any: ...

    def recheck(self) -> None: ...


class GeneratedTextExportSource(Protocol):
    """Prepared text/Markdown chunks with an exact Unicode character count."""

    kind: str  # text or markdown
    readiness: GeneratedFileExportReadiness
    character_count: int

    def iter_text(self) -> Iterator[str]: ...

    def recheck(self) -> None: ...


GeneratedFileExportSource = Union[
    GeneratedRecordExportSource,
    GeneratedStructuredValueExportSource,
    GeneratedTextExportSource,
]


@dataclass
class GeneratedFileExportStream:
    file_content: BinaryIO
    output_format: str
    media_type: str
    size_bytes: int
    content_sha256: str
    record_count: int
    profile: str
    source_kind: str = 'records'
    file_extension: str = ''
    character_count: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def close(self) -> None:
        self.file_content.close()

    def __enter__(self) -> "GeneratedFileExportStream":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
