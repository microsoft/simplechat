# functions_document_merge_docx.py
"""Word assembly for V2 file merge: documents appended in order into one .docx.

Version: 0.261.222

Composition uses docxcompose, which carries over each document's styles, numbering,
images, footnotes, diagrams and shapes. With ``keep_source`` formatting, a style that
shares a name with the first document's but looks different is copied under a new name,
so every document keeps its own look; with ``use_first``, the first document's styles
win. The merged file uses the first document's page setup, headers and footers, and a
fixed modified date, so the same files always give the same bytes. Comments are not
carried over. Fields, links and a linked template are copied as they are.
"""

from datetime import datetime
import io

from functions_document_merge import (
    DocumentMergeError,
    FORMATTING_KEEP_SOURCE,
    finish_output,
    guard_ooxml_package,
    new_output_spool,
    normalized_package,
)


_W_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_COMMENT_TAGS = ("commentRangeStart", "commentRangeEnd", "commentReference")
_PACKAGE_DATE = datetime(2000, 1, 1)


def assemble_docx(context):
    """Append every part's body, in order, to the first document."""
    # python-docx and docxcompose load only when a Word merge runs.
    from docx import Document
    from docxcompose.composer import Composer

    composer = None
    master = None
    for index, part in enumerate(context.parts):
        content = context.load(index)
        guard_ooxml_package(content, part, context.limits, "Word document")
        try:
            document = Document(io.BytesIO(content))
        except Exception as exc:
            if not context.blames_file(exc):
                raise
            raise DocumentMergeError(
                "unreadable_document", f"{part.display_name()} couldn't be opened as a Word document.",
            ) from exc
        entry = context.part_entry(index)
        entry["paragraphs"] = len(document.paragraphs)
        entry["tables"] = len(document.tables)
        context.check_cancel()
        try:
            if index == 0:
                master = document
                composer = Composer(master, preserve_styles=context.options.formatting == FORMATTING_KEEP_SOURCE)
                if context.options.source_headings:
                    _insert_heading(master, part.display_name(), at_start=True)
            else:
                if _remove_comment_marks(document):
                    context.warn("comments_removed", "Comments in this document were not carried over.", index)
                if context.options.page_breaks:
                    master.add_page_break()
                if context.options.source_headings:
                    _insert_heading(master, part.display_name(), at_start=False)
                composer.append(document)
        except DocumentMergeError:
            raise
        except Exception as exc:
            if not context.blames_file(exc):
                raise
            # Library errors can quote document text, so only the file's name is reported.
            raise DocumentMergeError(
                "unreadable_document", f"{part.display_name()} couldn't be combined with the other documents.",
            ) from exc
        context.progress(index)

    context.limit("The merged document uses the first document's page setup, headers and footers.")
    if context.options.formatting == FORMATTING_KEEP_SOURCE:
        context.limit(
            "Styles that share a name but look different are kept as separate copies, so each document keeps its look."
        )
    else:
        context.limit("Styles that share a name use the first document's definition.")
    return finish_output(context, _write_package(composer, master, context))


def _write_package(composer, master, context):
    """Save the composed document with a fixed modified date and ZIP metadata, then re-open it."""
    from docx import Document

    package = new_output_spool()
    spool = None
    try:
        # A document without core properties gets defaults stamped with the current time.
        master.core_properties.modified = _PACKAGE_DATE
        composer.save(package)
        spool = normalized_package(package, context)
        # Re-open the result so a malformed package fails here, not in the user's Word.
        Document(spool)
        return spool
    except Exception as exc:
        if spool is not None:
            spool.close()
        if isinstance(exc, DocumentMergeError) or not context.blames_file(exc):
            raise
        raise DocumentMergeError("merge_failed", "The merged Word document couldn't be written.") from exc
    except BaseException:
        if spool is not None:
            spool.close()
        raise
    finally:
        package.close()


def _insert_heading(document, text, *, at_start):
    """Add a heading naming a source document, using Heading 1 when the document has it."""
    try:
        paragraph = document.add_heading(text, level=1)
    except KeyError:
        paragraph = document.add_paragraph()
        paragraph.add_run(text).bold = True
    if at_start:
        element = paragraph._p
        body = element.getparent()
        body.remove(element)
        body.insert(0, element)
    return paragraph


def _remove_comment_marks(document):
    """Comments live in a part that is not carried over, so remove their anchors."""
    removed = False
    for tag in _COMMENT_TAGS:
        for element in document.element.body.iter(f"{{{_W_NAMESPACE}}}{tag}"):
            removed = True
    if not removed:
        return False
    for tag in _COMMENT_TAGS:
        for element in list(document.element.body.iter(f"{{{_W_NAMESPACE}}}{tag}")):
            parent = element.getparent()
            if tag == "commentReference" and parent is not None and parent.tag == f"{{{_W_NAMESPACE}}}r":
                run_parent = parent.getparent()
                if run_parent is not None:
                    run_parent.remove(parent)
                continue
            if parent is not None:
                parent.remove(element)
    return True


__all__ = ["assemble_docx"]
