# functions_document_merge_pdf.py
"""PDF assembly for V2 file merge: ordered pages, one bookmark per source file.

Version: 0.261.221

Pages are copied with pypdf, so text, images, links and fonts stay exactly as they were.
Each source becomes a top-level bookmark that keeps the source's own bookmarks beneath
it. Encrypted PDFs are refused rather than decrypted, so a merge never removes a
document's protection. Actions that could run code, open files or programs, or submit
forms are removed wherever they appear: open actions, document, page, link and
form-field scripts, and XFA form logic. Only navigation is kept: links to a page, the
standard next, previous, first and last page commands, and http, https and mailto
addresses.

pypdf keeps every source in memory until the merged file is written, so memory grows with
the total input and callers bound it with ``max_total_input_bytes``. This module, and so
pypdf, loads only when a PDF merge runs.
"""

import io
import re

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NullObject

from functions_document_merge import (
    DocumentMergeError,
    MERGE_KIND_PDF,
    finish_output,
    new_output_spool,
    selected_indices,
)


_PDF_HEADER = b"%PDF-"
_HEADER_SEARCH_BYTES = 1024
_MAX_ACTION_CHAIN = 64
_STANDARD_NAMED_ACTIONS = frozenset({"/NextPage", "/PrevPage", "/FirstPage", "/LastPage"})
_WEB_AND_EMAIL_SCHEMES = frozenset({"http", "https", "mailto"})
# URL parsers drop control characters and spaces before they read a scheme.
_URI_IGNORED_CHARACTERS = re.compile(r"[\x00-\x20\x7f]")


def assemble_pdf(context):
    """Append every part's selected pages, in order, into one PDF."""
    writer = PdfWriter()
    total_pages = 0
    for index, part in enumerate(context.parts):
        copied, source_pages, has_form_fields = _append_part(writer, context, index, part, total_pages)
        entry = context.part_entry(index)
        entry["pages"] = copied
        entry["source_pages"] = source_pages
        total_pages += copied
        if has_form_fields:
            context.warn(
                "form_fields", "This PDF has fillable form fields; fields with the same name share one value.",
                index,
            )
        context.progress(index)

    try:
        removed = _strip_active_content(writer)
    except Exception as exc:
        if not context.blames_file(exc):
            raise
        # A file that can't be checked for scripts is not delivered.
        raise DocumentMergeError("merge_failed", "The merged PDF couldn't be checked for scripts.") from exc
    if removed:
        context.warn(
            "active_content_removed",
            "Scripts, form actions and links that open files or programs were removed; links to pages and web "
            "or email addresses were kept.",
        )
    if context.options.bookmarks:
        context.limit("Each file starts with a bookmark named after it; its own bookmarks are kept beneath it.")
    context.report["totals"]["pages"] = total_pages
    context.check_cancel()
    spool = new_output_spool()
    try:
        writer.write(spool)
    except Exception as exc:
        spool.close()
        if not context.blames_file(exc):
            raise
        raise DocumentMergeError("merge_failed", "The merged PDF couldn't be written.") from exc
    except BaseException:
        spool.close()
        raise
    return finish_output(context, spool)


def _append_part(writer, context, index, part, pages_so_far):
    """Copy one source's selected pages into the writer."""
    content = context.load(index)
    if _PDF_HEADER not in content[:_HEADER_SEARCH_BYTES]:
        raise DocumentMergeError("unreadable_document", f"{part.display_name()} isn't a valid PDF.")
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise DocumentMergeError(
                "encrypted_document",
                f"{part.display_name()} is password-protected or encrypted, so it can't be merged.",
            )
        page_count = len(reader.pages)
    except DocumentMergeError:
        raise
    except Exception as exc:
        if not context.blames_file(exc):
            raise
        raise DocumentMergeError("unreadable_document", f"{part.display_name()} couldn't be read as a PDF.") from exc
    if page_count == 0:
        raise DocumentMergeError("empty_source", f"{part.display_name()} has no pages.")
    indices = selected_indices(part, page_count, "page")
    if pages_so_far + len(indices) > context.limits.max_pages:
        raise DocumentMergeError(
            "page_limit_exceeded", f"The merged PDF would have more than {context.limits.max_pages:,} pages.",
        )
    context.check_cancel()
    try:
        writer.append(
            reader,
            outline_item=part.display_name() if context.options.bookmarks else None,
            pages=indices,
            import_outline=context.options.bookmarks,
        )
        has_form_fields = _has_form_fields(reader)
    except Exception as exc:
        if not context.blames_file(exc):
            raise
        raise DocumentMergeError("unreadable_document", f"{part.display_name()} couldn't be read as a PDF.") from exc
    finally:
        # pypdf keys its copy table by id(reader); dropping it means a later source can't reuse it.
        writer.reset_translation(reader)
    return len(indices), page_count, has_form_fields


def _has_form_fields(reader):
    try:
        root = reader.trailer["/Root"]
        return "/AcroForm" in root
    except (KeyError, TypeError):
        return False


def _strip_active_content(writer):
    """Remove actions that could run code, open programs or submit forms; return how many."""
    root = writer.root_object
    removed = _drop_keys(root, ("/OpenAction", "/AA"))
    names = _resolved(root.get("/Names"))
    if isinstance(names, DictionaryObject):
        removed += _drop_keys(names, ("/JavaScript",))
    for page in writer.pages:
        removed += _strip_actions(page)
        annotations = _resolved(page.get("/Annots"))
        if isinstance(annotations, ArrayObject):
            for annotation in annotations:
                annotation = _resolved(annotation)
                if isinstance(annotation, DictionaryObject):
                    removed += _strip_actions(annotation)
    form = _resolved(root.get("/AcroForm"))
    if isinstance(form, DictionaryObject):
        removed += _drop_keys(form, ("/XFA",))
        removed += _strip_tree(form.get("/Fields"), ("/Kids",))
    outlines = _resolved(root.get("/Outlines"))
    if isinstance(outlines, DictionaryObject):
        removed += _strip_tree(outlines.get("/First"), ("/First", "/Next"))
    return removed


def _strip_tree(start, child_keys):
    """Strip actions from every node reachable through child_keys, visiting each node once."""
    removed = 0
    pending = [start]
    seen = set()
    while pending:
        node = _resolved(pending.pop())
        if not isinstance(node, (ArrayObject, DictionaryObject)) or id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, ArrayObject):
            pending.extend(node)
            continue
        removed += _strip_actions(node)
        pending.extend(node.get(key) for key in child_keys if key in node)
    return removed


def _strip_actions(item):
    removed = _drop_keys(item, ("/AA",))
    if "/A" in item and not _is_safe_action(item.get("/A")):
        del item["/A"]
        removed += 1
    return removed


def _is_safe_action(action):
    """True when an action, and every action chained after it, only navigates."""
    pending = [action]
    visited = 0
    while pending:
        current = _resolved(pending.pop())
        visited += 1
        if visited > _MAX_ACTION_CHAIN or not isinstance(current, DictionaryObject) or not _navigates(current):
            return False
        following = _resolved(current.get("/Next"))
        if isinstance(following, ArrayObject):
            pending.extend(following)
        elif following is not None:
            pending.append(following)
    return True


def _navigates(action):
    """Only a page in this file, a standard page command, or a web or email address."""
    action_type = _resolved(action.get("/S"))
    if action_type == "/GoTo":
        return True
    if action_type == "/Named":
        command = _resolved(action.get("/N"))
        return isinstance(command, str) and command in _STANDARD_NAMED_ACTIONS
    if action_type == "/URI":
        return _is_web_or_email(_resolved(action.get("/URI")))
    return False


def _is_web_or_email(value):
    if isinstance(value, bytes):
        value = value.decode("latin-1", "replace")
    if not isinstance(value, str):
        return False
    text = "".join(_URI_IGNORED_CHARACTERS.sub("", value).split())
    scheme, separator, _rest = text.partition(":")
    return bool(separator) and scheme.lower() in _WEB_AND_EMAIL_SCHEMES


def _drop_keys(item, keys):
    removed = 0
    for key in keys:
        if key in item:
            del item[key]
            removed += 1
    return removed


def _resolved(value):
    if value is None:
        return None
    try:
        value = value.get_object()
    except Exception:
        return None
    return None if value is None or isinstance(value, NullObject) else value


__all__ = ["MERGE_KIND_PDF", "assemble_pdf"]
