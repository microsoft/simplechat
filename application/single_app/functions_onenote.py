# functions_onenote.py
"""Bounded local OneNote extraction, independent of application bootstrap.

The document processor owns logging, settings, authorization, and persistence.
This module never initializes Azure clients or sends document content over a network.
"""

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO


ONENOTE_PARSER_REVISION = "d0d3330f9674f07903664329f50434d997eced8c"
ONENOTE_PROTOCOL_VERSION = 1
ONENOTE_MAX_INPUT_BYTES = 128 * 1024 * 1024
ONENOTE_MAX_TEXT_BYTES = 16 * 1024 * 1024
ONENOTE_MAX_OUTPUT_BYTES = 32 * 1024 * 1024
ONENOTE_MAX_PAGES = 10000
ONENOTE_MAX_CHUNKS = 10000
ONENOTE_MAX_MEMBERS = 1024
ONENOTE_MAX_DEPTH = 16
ONENOTE_TIMEOUT_SECONDS = 150
ONENOTE_STDERR_LIMIT_BYTES = 32 * 1024
_EXTRACTION_SLOT = threading.BoundedSemaphore(1)

_ERROR_MESSAGES = {
    "invalid_file": "The file is not a valid OneNote section or notebook package.",
    "unsupported_file": "This OneNote format is not supported. Export a current .one or .onepkg file.",
    "encrypted_file": "Encrypted or password-protected OneNote content is not supported.",
    "unsafe_package": "The OneNote package contains unsafe or ambiguous file references.",
    "limit_exceeded": "The OneNote file exceeds processing limits. Upload smaller sections instead.",
    "incomplete_notebook": "The complete OneNote notebook could not be read. No content was indexed.",
    "no_text": "No searchable typed text was found. Handwriting, images, and attachments are not extracted.",
    "extraction_failed": "Unable to extract this OneNote file. Try exporting it again.",
    "invalid_output": "The OneNote extractor returned an invalid or incompatible result.",
    "runtime_unavailable": "The OneNote extractor is unavailable. Install the native component or use the current application container.",
    "file_too_large": "The OneNote file exceeds the configured upload limit or the 128 MiB extractor limit.",
    "timeout": "OneNote extraction timed out. Upload smaller sections instead.",
    "busy": "OneNote extraction is busy. Please retry this upload.",
    "indexing_failed": "Unable to finish indexing the OneNote document. Please retry processing.",
}


class OneNoteExtractionError(RuntimeError):
    """A stable error safe for document status messages; never includes parser diagnostics."""

    def __init__(self, code: str):
        self.code = code if code in _ERROR_MESSAGES else "extraction_failed"
        super().__init__(_ERROR_MESSAGES[self.code])


@dataclass(frozen=True)
class OneNotePage:
    section_path: tuple[str, ...]
    page_id: str
    title: str
    level: int
    text: str


@dataclass(frozen=True)
class OneNoteExtraction:
    sections: int
    pages: tuple[OneNotePage, ...]
    excluded_content: dict[str, int]


@dataclass
class _PipeCapture:
    data: bytearray = field(default_factory=bytearray)
    exceeded: bool = False
    failed: bool = False


def _stop_worker(process: subprocess.Popen) -> None:
    try:
        process.kill()
    except ProcessLookupError:
        pass


def _capture_pipe(
    pipe: BinaryIO, limit: int, capture: _PipeCapture, process: subprocess.Popen
) -> None:
    try:
        while block := pipe.read(16 * 1024):
            if capture.exceeded:
                continue
            if len(capture.data) + len(block) > limit:
                capture.exceeded = True
                _stop_worker(process)
            else:
                capture.data.extend(block)
    except OSError:
        capture.failed = True
        _stop_worker(process)


def _extractor_path() -> Path:
    configured = os.environ.get("SIMPLECHAT_ONENOTE_EXTRACTOR")
    if configured:
        candidate = Path(configured)
        if candidate.is_absolute() and candidate.is_file():
            return candidate
        raise OneNoteExtractionError("runtime_unavailable")

    executable = "simplechat-onenote-extractor"
    if os.name == "nt":
        executable = f"{executable}.exe"
    root = Path(__file__).resolve().parent / "native" / "onenote_extractor"
    for candidate in (root / "bin" / executable, root / "target" / "release" / executable):
        if candidate.is_file():
            return candidate
    raise OneNoteExtractionError("runtime_unavailable")


def _worker_environment() -> dict[str, str]:
    environment = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "RUST_BACKTRACE": "0"}
    if os.name == "nt":
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            value = os.environ.get(name)
            if value:
                environment[name] = value
    return environment


def _run_extractor(
    executable: Path, source: Path, original_filename: str | None = None
) -> tuple[int, bytes]:
    stdout_capture = _PipeCapture()
    stderr_capture = _PipeCapture()
    command = [str(executable), str(source)]
    if original_filename is not None:
        command.append(original_filename)
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=_worker_environment(),
            cwd=str(source.parent),
        )
    except OSError as exc:
        raise OneNoteExtractionError("runtime_unavailable") from exc

    readers = [
        threading.Thread(
            target=_capture_pipe,
            args=(process.stdout, ONENOTE_MAX_OUTPUT_BYTES, stdout_capture, process),
            daemon=True,
        ),
        threading.Thread(
            target=_capture_pipe,
            args=(process.stderr, ONENOTE_STDERR_LIMIT_BYTES, stderr_capture, process),
            daemon=True,
        ),
    ]
    try:
        for reader in readers:
            reader.start()
        try:
            return_code = process.wait(timeout=ONENOTE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            _stop_worker(process)
            process.wait()
            raise OneNoteExtractionError("timeout") from exc
    finally:
        if process.poll() is None:
            _stop_worker(process)
            process.wait()
        for reader in readers:
            if reader.ident is not None:
                reader.join()
        process.stdout.close()
        process.stderr.close()

    if stdout_capture.exceeded or stderr_capture.exceeded:
        raise OneNoteExtractionError("limit_exceeded")
    if stdout_capture.failed or stderr_capture.failed:
        raise OneNoteExtractionError("extraction_failed")
    return return_code, bytes(stdout_capture.data)


def _count(value, maximum: int, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _text(value, maximum: int) -> bool:
    return isinstance(value, str) and len(value) <= maximum and "\0" not in value


def _validate_result(return_code: int, output: bytes) -> OneNoteExtraction:
    try:
        payload = json.loads(output)
    except (ValueError, UnicodeError, RecursionError) as exc:
        code = "extraction_failed" if return_code else "invalid_output"
        raise OneNoteExtractionError(code) from exc
    if not isinstance(payload, dict):
        raise OneNoteExtractionError("invalid_output")
    if type(payload.get("protocol_version")) is not int or payload["protocol_version"] != ONENOTE_PROTOCOL_VERSION:
        raise OneNoteExtractionError("invalid_output")
    if return_code != 0:
        error = payload.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        raise OneNoteExtractionError(code if isinstance(code, str) else "extraction_failed")
    if payload.get("error") is not None or payload.get("parser_revision") != ONENOTE_PARSER_REVISION:
        raise OneNoteExtractionError("invalid_output")

    sections = payload.get("sections")
    source_pages = payload.get("source_pages")
    pages_data = payload.get("pages")
    if (
        not _count(sections, ONENOTE_MAX_MEMBERS, 1)
        or not _count(source_pages, ONENOTE_MAX_PAGES, 1)
        or not isinstance(pages_data, list)
        or source_pages != len(pages_data)
    ):
        raise OneNoteExtractionError("invalid_output")

    excluded = payload.get("excluded_content")
    if not isinstance(excluded, dict) or set(excluded) != {"images", "ink", "attachments", "empty_pages"}:
        raise OneNoteExtractionError("invalid_output")
    if any(not _count(value, ONENOTE_MAX_TEXT_BYTES) for value in excluded.values()):
        raise OneNoteExtractionError("invalid_output")

    pages = []
    text_bytes = 0
    for page in pages_data:
        if not isinstance(page, dict):
            raise OneNoteExtractionError("invalid_output")
        section_path = page.get("section_path")
        if (
            not isinstance(section_path, list)
            or not 1 <= len(section_path) <= ONENOTE_MAX_DEPTH
            or any(not _text(part, 1024) or not part.strip() for part in section_path)
            or not _text(page.get("id"), 128)
            or not page["id"]
            or not _text(page.get("title"), 4096)
            or not _count(page.get("level"), ONENOTE_MAX_DEPTH, 1)
            or not _text(page.get("text"), ONENOTE_MAX_TEXT_BYTES)
        ):
            raise OneNoteExtractionError("invalid_output")
        try:
            text_bytes += len(page["text"].encode("utf-8"))
            for label in [*section_path, page["title"], page["id"]]:
                label.encode("utf-8")
        except UnicodeError as exc:
            raise OneNoteExtractionError("invalid_output") from exc
        if text_bytes > ONENOTE_MAX_TEXT_BYTES:
            raise OneNoteExtractionError("limit_exceeded")
        pages.append(OneNotePage(tuple(section_path), page["id"], page["title"], page["level"], page["text"]))

    empty_pages = sum(not page.text.strip() for page in pages)
    if excluded["empty_pages"] != empty_pages or len({page.section_path for page in pages}) > sections:
        raise OneNoteExtractionError("invalid_output")
    if empty_pages == len(pages):
        raise OneNoteExtractionError("no_text")
    return OneNoteExtraction(sections, tuple(pages), dict(excluded))


def extract_onenote(
    source_path: str | Path, max_file_size_bytes: int, *, original_filename: str | None = None
) -> OneNoteExtraction:
    """Extract all current typed content, or fail before any content is indexed."""
    if type(max_file_size_bytes) is not int or max_file_size_bytes <= 0:
        raise OneNoteExtractionError("file_too_large")
    try:
        source = Path(source_path).resolve(strict=True)
        if not source.is_file() or source.suffix.lower() not in {".one", ".onepkg"}:
            raise OneNoteExtractionError("invalid_file")
        size = source.stat().st_size
    except (OSError, TypeError, ValueError) as exc:
        raise OneNoteExtractionError("invalid_file") from exc
    if size <= 0:
        raise OneNoteExtractionError("invalid_file")
    if size > min(max_file_size_bytes, ONENOTE_MAX_INPUT_BYTES):
        raise OneNoteExtractionError("file_too_large")
    if original_filename is not None:
        if (
            not isinstance(original_filename, str)
            or not original_filename
            or any(character in original_filename for character in ("/", "\\", ":", "\0"))
            or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in original_filename)
            or not original_filename.lower().endswith(source.suffix.lower())
            or not original_filename[:-len(source.suffix)].strip()
        ):
            raise OneNoteExtractionError("invalid_file")
        if len(original_filename) > 1024:
            raise OneNoteExtractionError("limit_exceeded")
        try:
            original_filename.encode("utf-8")
        except UnicodeError as exc:
            raise OneNoteExtractionError("invalid_file") from exc

    executable = _extractor_path()
    if not _EXTRACTION_SLOT.acquire(timeout=ONENOTE_TIMEOUT_SECONDS):
        raise OneNoteExtractionError("busy")
    try:
        return_code, output = _run_extractor(executable, source, original_filename)
        return _validate_result(return_code, output)
    finally:
        _EXTRACTION_SLOT.release()
