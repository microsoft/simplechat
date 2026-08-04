# functions_generated_file_exports.py
"""Shared helpers for generated downloadable file exports."""

import json
import re
from typing import Any, Iterable
from xml.etree import ElementTree


SUPPORTED_GENERATED_EXPORT_FORMATS = {'csv', 'json', 'xml'}
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'
XML_ROOT_PATTERN = re.compile(r'<(?P<tag>[A-Za-z_][A-Za-z0-9_.:-]*)(?:\s[^<>]*)?>')


def normalize_generated_output_format(output_format, default='json'):
    """Normalize generated artifact output formats supported by the export framework."""
    normalized_format = str(output_format or '').strip().lower().lstrip('.')
    if normalized_format in SUPPORTED_GENERATED_EXPORT_FORMATS:
        return normalized_format

    normalized_default = str(default or 'json').strip().lower().lstrip('.')
    if normalized_default in SUPPORTED_GENERATED_EXPORT_FORMATS:
        return normalized_default
    return 'json'


def strip_markdown_code_fence(text):
    """Remove a single surrounding Markdown code fence while preserving content."""
    normalized_text = str(text or '').strip()
    if not normalized_text.startswith('```'):
        return normalized_text

    code_fence_match = re.fullmatch(
        r'```(?:[a-zA-Z0-9_-]+)?\s*(.*?)\s*```',
        normalized_text,
        re.DOTALL,
    )
    if not code_fence_match:
        return normalized_text

    return str(code_fence_match.group(1) or '').strip()


def _iter_xml_candidates(text) -> Iterable[str]:
    normalized_text = strip_markdown_code_fence(text)
    if not normalized_text:
        return

    yield normalized_text

    first_xml_index = normalized_text.find('<?xml')
    if first_xml_index > 0:
        yield normalized_text[first_xml_index:].strip()

    first_tag_index = normalized_text.find('<')
    if first_tag_index > 0:
        yield normalized_text[first_tag_index:].strip()

    for root_match in XML_ROOT_PATTERN.finditer(normalized_text):
        root_tag = root_match.group('tag')
        root_start = root_match.start()
        root_open = root_match.group(0)
        if root_open.rstrip().endswith('/>'):
            yield normalized_text[root_start:root_match.end()].strip()
            continue

        closing_tag = f'</{root_tag}>'
        root_end = normalized_text.rfind(closing_tag)
        if root_end <= root_start:
            continue

        yield normalized_text[root_start:root_end + len(closing_tag)].strip()


def normalize_xml_artifact_payload(text):
    """Return a complete XML document extracted from model output, or an empty string."""
    seen_candidates = set()
    for candidate in _iter_xml_candidates(text):
        if candidate in seen_candidates:
            continue
        seen_candidates.add(candidate)
        try:
            ElementTree.fromstring(candidate.encode('utf-8'))
        except ElementTree.ParseError:
            continue
        return candidate
    return ''


def normalize_json_artifact_payload(text):
    """Return parsed JSON extracted from model output, or None when no JSON is present."""
    normalized_text = strip_markdown_code_fence(text)
    if not normalized_text:
        return None

    decoder = json.JSONDecoder()
    try:
        parsed_value, _ = decoder.raw_decode(normalized_text)
        return parsed_value
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    for start_index, character in enumerate(normalized_text):
        if character not in '[{':
            continue
        try:
            parsed_value, _ = decoder.raw_decode(normalized_text[start_index:])
            return parsed_value
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    return None


def _sanitize_xml_tag_name(value, fallback_value):
    normalized_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(value or '').strip())
    normalized_name = normalized_name.strip('._-')
    if not normalized_name:
        normalized_name = fallback_value
    if not re.match(r'^[A-Za-z_]', normalized_name):
        normalized_name = f'{fallback_value}_{normalized_name}'
    return normalized_name


def _append_xml_value(parent, value, item_name):
    if isinstance(value, dict):
        for key, child_value in value.items():
            child = ElementTree.SubElement(
                parent,
                _sanitize_xml_tag_name(key, 'Field'),
            )
            _append_xml_value(child, child_value, item_name)
        return

    if isinstance(value, (list, tuple)):
        for item in value:
            child = ElementTree.SubElement(
                parent,
                _sanitize_xml_tag_name(item_name, 'Item'),
            )
            _append_xml_value(child, item, item_name)
        return

    if value is None:
        parent.text = ''
        return

    if isinstance(value, bool):
        parent.text = 'true' if value else 'false'
        return

    parent.text = str(value)


def build_xml_from_value(value: Any, root_name='GeneratedOutput', item_name='Item'):
    """Serialize a Python value into a deterministic XML document."""
    root = ElementTree.Element(_sanitize_xml_tag_name(root_name, 'GeneratedOutput'))
    _append_xml_value(root, value, item_name)
    ElementTree.indent(root, space='  ')
    xml_body = ElementTree.tostring(root, encoding='unicode', short_empty_elements=True)
    return f'{XML_DECLARATION}\n{xml_body}'


def serialize_generated_xml(value: Any, root_name='GeneratedOutput', item_name='Item'):
    """Serialize generated content to XML, preserving valid XML model output when present."""
    if isinstance(value, str):
        xml_payload = normalize_xml_artifact_payload(value)
        if xml_payload:
            return xml_payload

    return build_xml_from_value(value, root_name=root_name, item_name=item_name)


def serialize_generated_json(value: Any, *, indent=2):
    """Serialize generated content to JSON using the export framework defaults."""
    return json.dumps(value, indent=indent, ensure_ascii=False, default=str)
