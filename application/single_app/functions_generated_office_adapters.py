# functions_generated_office_adapters.py
"""Explicit-source bridges to the headless Office services, without publication."""

import io
import math
import re
from contextlib import ExitStack
from dataclasses import fields, replace
from typing import Any, Callable, Optional

from jsonschema import Draft202012Validator, ValidationError

import functions_office_file_renderers as office
from functions_export_cleanup import ClosingExportResource
from functions_generated_export_contracts import (
    GeneratedFileExportError,
    GeneratedFileExportLimits,
    GeneratedFileExportStream,
)
from functions_generated_export_registry import (
    GENERATED_IMAGE_REFERENCE_PATTERN,
    PREPARED_SLIDE_DECK_VERSION,
    get_prepared_slide_deck_schema,
    resolve_generated_file_export_format,
)
from functions_structured_file_renderers import (
    _INVALID_XML_CHARACTERS,
    _OutputWriter,
    _SourceChecks,
    _iter_records,
    _render_text,
    _validate_column_names,
    _validate_export_limits,
    _validate_source_limits,
    _validate_value,
)


class _PreparationChecks:
    def __init__(self, check):
        if check is not None and not callable(check):
            raise GeneratedFileExportError('invalid_options', 'An execution check must be callable.')
        self.check = check

    def run(self):
        if self.check is not None:
            self.check()


class _SourceFailureBoundary:
    """Remember escaping caller failures before an Office helper classifies them.

    In particular, InterruptedError is an OSError, not a retryable source outage.
    Checks still raise through the helper's normal cleanup path; only the adapter
    restores the original exception after that cleanup has completed.
    """

    def __init__(self):
        self.failure = None
        self.traceback = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if (
            exc_value is not None
            and not isinstance(exc_value, (StopIteration, GeneratorExit))
            and self.failure is None
        ):
            self.failure = exc_value
            self.traceback = traceback
        return False

    def call(self, callback, *args):
        with self:
            return callback(*args)

    def rows(self, records):
        with ClosingExportResource(records):
            while True:
                try:
                    record = self.call(next, records)
                except StopIteration:
                    return
                yield record

    def invoke(self, renderer, prepared, **kwargs):
        try:
            return renderer(prepared, **kwargs)
        except office.OfficeRenderError:
            if self.failure is None:
                raise
        # Re-raise outside the handler so the helper wrapper cannot replace the
        # caller's exception cause, identity, or cancellation classification.
        raise self.failure.with_traceback(self.traceback)


def _office_limits(limits, export_limits, max_output_bytes=None):
    limits = office.OfficeRenderLimits() if limits is None else limits
    if not isinstance(limits, office.OfficeRenderLimits) or any(
        type(getattr(limits, field.name)) is not int or getattr(limits, field.name) <= 0
        for field in fields(office.OfficeRenderLimits)
    ):
        raise GeneratedFileExportError('invalid_limit', 'Positive Office renderer limits are required.')
    return replace(
        limits,
        max_output_bytes=limits.max_output_bytes if max_output_bytes is None else min(
            max_output_bytes, limits.max_output_bytes,
        ),
        max_rows=min(export_limits.max_records, limits.max_rows),
    )


def _deck_text(value):
    if _INVALID_XML_CHARACTERS.search(value):
        raise GeneratedFileExportError('invalid_data', 'Prepared slide text must be valid XML text.')
    return value


def _validate_slide_geometry(box, occupied, width, height):
    if box.left + box.width > width + 0.001 or box.top + box.height > height + 0.001:
        raise office.OfficeRenderError('layout_overflow')
    if any(
        min(box.left + box.width, other.left + other.width) > max(box.left, other.left) + 0.001
        and min(box.top + box.height, other.top + other.height) > max(box.top, other.top) + 0.001
        for other in occupied
    ):
        raise office.OfficeRenderError('layout_overflow')
    occupied.append(box)


def prepare_generated_slide_deck(
    value: Any, *, limits: Optional[GeneratedFileExportLimits] = None,
    office_limits: Optional[office.OfficeRenderLimits] = None,
    check: Optional[Callable[[], Any]] = None,
) -> office.PreparedDeck:
    """Validate composition JSON before persistence; never compose or render slides.

    Structural, count, geometry and configured-size validation happens here.
    The headless renderer additionally validates physical text fit and image
    content. Image references remain opaque server-resolved asset identifiers.
    """
    limits = GeneratedFileExportLimits() if limits is None else limits
    _validate_export_limits(limits, 1)
    renderer_limits = _office_limits(office_limits, limits)
    checks = _PreparationChecks(check)
    checks.run()
    _validate_value(value, limits, checks, PREPARED_SLIDE_DECK_VERSION)
    try:
        Draft202012Validator(get_prepared_slide_deck_schema()).validate(value)
    except ValidationError as exc:
        raise GeneratedFileExportError('invalid_data', 'The prepared slide deck does not match its JSON schema.') from exc
    if value['slide_count'] != len(value['slides']):
        raise GeneratedFileExportError('count_mismatch', 'The declared slide count does not match the prepared slides.')
    if len(value['slides']) > renderer_limits.max_slides:
        raise office.OfficeRenderError('limit_exceeded')
    size = value.get('size', 'wide')
    width, height = (40 / 3, 7.5) if size == 'wide' else (10, 7.5)
    slides = []
    shape_count = 0
    cell_count = 0
    image_count = 0
    for slide in value['slides']:
        checks.run()
        occupied = [office.SlideBox(0.5, 0.25, width - 1, 1)] if slide['layout'] == 'title_and_content' else []
        shapes = []
        shape_count += len(slide['shapes'])
        if shape_count > renderer_limits.max_shapes:
            raise office.OfficeRenderError('limit_exceeded')
        for shape in slide['shapes']:
            box = office.SlideBox(**shape['box'])
            _validate_slide_geometry(box, occupied, width, height)
            if shape['type'] == 'text_box':
                paragraphs = []
                for paragraph in shape['paragraphs']:
                    _deck_text(paragraph['text'])
                    if paragraph.get('url') is not None:
                        _deck_text(paragraph['url'])
                    paragraphs.append(office.SlideParagraph(**paragraph))
                prepared = office.SlideTextBox(box, tuple(paragraphs), shape.get('font_size', 18))
            elif shape['type'] == 'table':
                columns = len(shape['rows'][0])
                if any(len(row) != columns for row in shape['rows']):
                    raise GeneratedFileExportError('invalid_data', 'Prepared slide tables must be rectangular.')
                cell_count += len(shape['rows']) * columns
                if cell_count > renderer_limits.max_cells or columns > renderer_limits.max_columns:
                    raise office.OfficeRenderError('limit_exceeded')
                rows = tuple(tuple(_deck_text(cell) for cell in row) for row in shape['rows'])
                prepared = office.SlideTable(box, rows, shape.get('header', True), shape.get('font_size', 12))
            else:
                image_count += 1
                if image_count > renderer_limits.max_images:
                    raise office.OfficeRenderError('limit_exceeded')
                if re.fullmatch(GENERATED_IMAGE_REFERENCE_PATTERN, shape['source']) is None:
                    raise GeneratedFileExportError('invalid_data', 'Prepared images require an opaque asset reference.')
                prepared = office.SlideImage(box, shape['source'], _deck_text(shape.get('alt', '')))
            shapes.append(prepared)
            checks.run()
        slides.append(office.PreparedSlide(
            _deck_text(slide['title']), tuple(shapes), _deck_text(slide.get('notes', '')), slide['layout'],
        ))
    checks.run()
    return office.PreparedDeck(
        tuple(slides), value['slide_count'], title=_deck_text(value.get('title', '')), size=size,
    )


def _collect_report_text(source, request, limits, checks, renderer_limits):
    byte_limit = min(limits.max_value_bytes, renderer_limits.max_input_bytes)
    if source.character_count > byte_limit:
        raise GeneratedFileExportError('value_limit', 'The complete report exceeds the input byte limit.')
    with io.BytesIO() as buffer:
        writer = _OutputWriter(
            buffer, byte_limit, checks, limit_code='value_limit',
            limit_message='The complete report exceeds the input byte limit.',
        )
        _render_text(writer, source, request, limits, checks)
        checks.run()
        return buffer.getvalue().decode('utf-8')


def _workbook_records(source, request, columns, limits, checks):
    expected_keys = set(columns)
    with ClosingExportResource(_iter_records(source, limits, checks, request.profile)) as records:
        for record in records:
            if set(record) != expected_keys:
                raise GeneratedFileExportError('invalid_data', 'Every workbook row must match the declared columns.')
            for value in record.values():
                if type(value) not in (str, int, float, bool, type(None)):
                    raise office.OfficeRenderError('unsupported_content')
                if type(value) is float and (
                    (value == 0 and math.copysign(1, value) < 0)
                    or float(format(value, '.15g')) != value
                ):
                    raise office.OfficeRenderError('unsupported_content')
            yield record


def _image_resolver(callback, checks, boundary):
    if callback is None:
        return None

    def resolve(reference):
        if type(reference) is not str or re.fullmatch(GENERATED_IMAGE_REFERENCE_PATTERN, reference) is None:
            raise GeneratedFileExportError('invalid_data', 'Images require an opaque server-resolved asset reference.')
        boundary.call(checks.run)
        content = boundary.call(callback, reference)
        boundary.call(checks.run)
        return content

    return resolve


def _render_generated_office_source(
    source, request, *, max_output_bytes, check=None, limits=None, office_limits=None,
    image_resolver=None,
):
    entry = resolve_generated_file_export_format(request, getattr(source, 'kind', None))
    if entry.renderer_id != 'office':
        raise GeneratedFileExportError('unsupported_format', 'This Office export format is not supported.')
    if image_resolver is not None and (not entry.rich_media or not callable(image_resolver)):
        raise GeneratedFileExportError('invalid_options', 'This export does not accept the supplied image resolver.')
    limits = GeneratedFileExportLimits() if limits is None else limits
    _validate_source_limits(source, limits, max_output_bytes, check)
    renderer_limits = _office_limits(office_limits, limits, max_output_bytes)
    checks = _SourceChecks(source, check)
    checks.run()
    boundary = _SourceFailureBoundary()
    renderer_checks = office.OfficeRenderChecks(source_check=lambda: boundary.call(checks.run))
    arguments = {'limits': renderer_limits, 'checks': renderer_checks}
    rows = None
    with ExitStack() as resources:
        if entry.format_id == 'xlsx':
            columns = _validate_column_names(request.columns, limits, checks, label='XLSX')
            rows = resources.enter_context(ClosingExportResource(
                boundary.rows(_workbook_records(source, request, columns, limits, checks)),
            ))
            prepared = office.PreparedWorkbook((
                office.PreparedSheet(request.sheet_name, columns, rows, checks.expected_count),
            ))
            renderer = office.render_prepared_xlsx
        elif entry.format_id in ('docx', 'pdf'):
            content = _collect_report_text(source, request, limits, checks, renderer_limits)
            prepared = office.PreparedReport(
                content, content_format='markdown' if source.kind == 'markdown' else 'text',
                title=request.title if request.title is not None else '',
            )
            renderer = office.render_prepared_docx if entry.format_id == 'docx' else office.render_prepared_pdf
        elif entry.format_id == 'pptx':
            value = source.read_value()
            prepared = prepare_generated_slide_deck(
                value, limits=limits, office_limits=renderer_limits, check=checks.run,
            )
            renderer = office.render_prepared_pptx
        else:
            raise GeneratedFileExportError('unsupported_format', 'This Office renderer is not supported.')
        if entry.rich_media:
            arguments['image_resolver'] = _image_resolver(image_resolver, checks, boundary)
        checks.run()
        rendered = resources.enter_context(ClosingExportResource(
            boundary.invoke(renderer, prepared, **arguments),
        ))
        if rows is not None:
            rows.close()
        checks.run()
        expected_count = checks.expected_count
        if entry.format_id == 'xlsx' and rendered.metadata.get('record_count') != expected_count:
            raise GeneratedFileExportError('count_mismatch', 'The rendered workbook count is inconsistent.')
        if source.kind in ('text', 'markdown') and rendered.metadata.get('content_char_count') != expected_count:
            raise GeneratedFileExportError('count_mismatch', 'The rendered report character count is inconsistent.')
        result = GeneratedFileExportStream(
            file_content=rendered.file_content, output_format=entry.format_id, media_type=rendered.media_type,
            size_bytes=rendered.size_bytes, content_sha256=rendered.content_sha256,
            record_count=expected_count if source.kind == 'records' else 0,
            profile=request.profile, source_kind=source.kind, file_extension=entry.file_extension,
            character_count=expected_count if source.kind in ('text', 'markdown') else None,
            metadata={**rendered.metadata, 'renderer_profile': rendered.profile},
        )
        resources.pop_all()
        return result
