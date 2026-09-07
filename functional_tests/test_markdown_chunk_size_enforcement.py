#!/usr/bin/env python3
# test_markdown_chunk_size_enforcement.py
"""
Functional test for bounding Markdown chunks to the embedding token limit.
Version: 0.261.002
Implemented in: 0.261.002

Markdown was the only ingestion path with no maximum chunk size. MarkdownHeaderTextSplitter
splits on headings, and the post-processing loop only ever merged chunks that were too small, so
a heading section with no nested subheading became a single arbitrarily large chunk. That chunk
was sent to the embedding endpoint whole, exceeded the model's context window, and failed the
entire document upload.

This test runs the real process_md against a stubbed namespace and ensures that:
  - every emitted chunk stays inside both the word target and the character budget,
  - no source content is lost while doing so,
  - ordinary Markdown still splits on headings rather than being reflowed,
  - the chunk size cap is unit-aware, so a word field and a character field get different limits,
  - save_chunks clamps only the embedding input and still stores the full chunk text.
"""

import ast
import logging
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(APP_ROOT))

from langchain_text_splitters import (  # noqa: E402
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_IN_VERSION = "0.261.002"


def load_functions(source_path, function_names, namespace):
    """Exec selected functions and module constants from a source file into a namespace.

    The application modules import the full Azure configuration at load time, so the pure
    chunking functions are extracted and run against the real repository source instead of
    importing the module.
    """
    tree = ast.parse(Path(source_path).read_text(encoding="utf-8"))
    wanted = set(function_names)
    found = set()

    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [getattr(t, "id", "") for t in node.targets]
            if any(n.startswith(("EMBEDDING_", "CHUNK_SIZE_", "CHUNK_SPLIT_")) for n in names):
                exec(compile(ast.Module(body=[node], type_ignores=[]), str(source_path), "exec"), namespace)
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(source_path), "exec"), namespace)
            found.add(node.name)

    missing = wanted - found
    if missing:
        raise AssertionError(f"Could not locate functions in {source_path}: {sorted(missing)}")

    return namespace


def build_content_namespace():
    """Load the splitting helpers from functions_content.py."""
    namespace = {"RecursiveCharacterTextSplitter": RecursiveCharacterTextSplitter}
    return load_functions(
        APP_ROOT / "functions_content.py",
        ["count_words", "split_text_by_word_limit", "split_oversized_chunks"],
        namespace,
    )


def build_settings_namespace():
    """Load the embedding budget helpers from functions_settings.py."""
    namespace = {"WORD_CHUNK_SIZE": 400, "get_settings": lambda: {}}
    return load_functions(
        APP_ROOT / "functions_settings.py",
        [
            "get_embedding_context_tokens",
            "get_embedding_usable_tokens",
            "get_embedding_safe_chunk_characters",
            "get_embedding_safe_chunk_words",
            "get_chunk_size_cap",
            "get_chunk_size_caps_by_key",
            "get_chunk_size_defaults",
            "get_chunk_size_config",
        ],
        namespace,
    )


def run_process_md(md_content, target_chunk_words=1200, max_chunk_characters=None):
    """Run the real process_md against stubbed dependencies and return the saved chunks."""
    content_ns = build_content_namespace()
    settings_ns = build_settings_namespace()

    if max_chunk_characters is None:
        max_chunk_characters = settings_ns["get_embedding_safe_chunk_characters"]({})

    saved_chunks = []

    def fake_save_chunks(page_text_content, page_number, file_name, user_id, document_id, **kwargs):
        saved_chunks.append({"page_number": page_number, "content": page_text_content})
        return {"total_tokens": 1, "model_deployment_name": "test-embedding"}

    namespace = {
        "MarkdownHeaderTextSplitter": MarkdownHeaderTextSplitter,
        "estimate_word_count": content_ns["count_words"],
        "split_text_by_word_limit": content_ns["split_text_by_word_limit"],
        "split_oversized_chunks": content_ns["split_oversized_chunks"],
        "get_settings": lambda: {},
        "get_chunk_size_config": lambda settings=None: {"md": {"value": target_chunk_words, "unit": "words"}},
        "get_embedding_safe_chunk_characters": lambda settings=None: max_chunk_characters,
        "save_chunks": fake_save_chunks,
        "upload_to_blob": lambda **kwargs: None,
        "extract_document_metadata": lambda **kwargs: None,
        "log_event": lambda *args, **kwargs: None,
        "logging": logging,
    }

    load_functions(APP_ROOT / "functions_documents.py", ["process_md"], namespace)

    handle, temp_path = tempfile.mkstemp(suffix=".md")
    os.close(handle)
    Path(temp_path).write_text(md_content, encoding="utf-8")

    try:
        namespace["process_md"](
            document_id="doc-1",
            user_id="user-1",
            temp_file_path=temp_path,
            original_filename="test.md",
            enable_enhanced_citations=False,
            update_callback=lambda **kwargs: None,
        )
    finally:
        os.unlink(temp_path)

    return saved_chunks, max_chunk_characters


def normalized(text):
    """Collapse whitespace so comparisons survive the splitter trimming chunk edges."""
    return " ".join(str(text).split())


def test_oversized_section_is_bounded():
    """A huge single-heading section must not produce one oversized chunk."""
    print("Testing oversized Markdown section...")

    paragraph = "This release corrects embedding and chunking behavior across the pipeline. " * 12
    body = "\n\n".join(f"Paragraph {i}. {paragraph}" for i in range(120))
    md_content = f"#### New Features\n\n{body}\n"

    content_ns = build_content_namespace()
    count_words = content_ns["count_words"]

    target_words = 1200
    chunks, max_chars = run_process_md(md_content, target_chunk_words=target_words)

    if not chunks:
        raise AssertionError("process_md produced no chunks.")

    # Without the fix this is a single chunk of roughly 19,000 words.
    if len(chunks) < 2:
        raise AssertionError(f"Oversized section was not split, got {len(chunks)} chunk(s).")

    oversized_chars = [c for c in chunks if len(c["content"]) > max_chars]
    if oversized_chars:
        raise AssertionError(
            f"{len(oversized_chars)} chunk(s) exceeded the {max_chars} character budget; "
            f"largest was {max(len(c['content']) for c in oversized_chars)}."
        )

    # The merge loop can carry a small trailing chunk onto a full one, so allow that documented
    # 1.5x inflation but nothing beyond it.
    word_ceiling = int(target_words * 1.5)
    oversized_words = [c for c in chunks if count_words(c["content"]) > word_ceiling]
    if oversized_words:
        raise AssertionError(
            f"{len(oversized_words)} chunk(s) exceeded {word_ceiling} words; "
            f"largest was {max(count_words(c['content']) for c in oversized_words)}."
        )

    print(f"   {len(chunks)} chunks, max chars {max(len(c['content']) for c in chunks)}, "
          f"max words {max(count_words(c['content']) for c in chunks)}")
    print("Oversized section test passed!")
    return True


def test_no_content_is_lost():
    """Splitting an oversized section must not drop any source content."""
    print("Testing content preservation...")

    paragraphs = [f"Paragraph {i}. " + ("Some durable sentence about chunking. " * 20) for i in range(80)]
    md_content = "#### New Features\n\n" + "\n\n".join(paragraphs) + "\n"

    chunks, _ = run_process_md(md_content, target_chunk_words=600)
    haystack = [normalized(c["content"]) for c in chunks]

    missing = [p for p in paragraphs if not any(normalized(p) in h for h in haystack)]
    if missing:
        raise AssertionError(f"{len(missing)} paragraph(s) were lost, first: {missing[0][:80]!r}")

    print(f"   all {len(paragraphs)} paragraphs preserved across {len(chunks)} chunks")
    print("Content preservation test passed!")
    return True


def test_normal_markdown_still_splits_on_headings():
    """Ordinary Markdown must keep heading-based chunking, not be reflowed by the size cap."""
    print("Testing heading-based splitting is preserved...")

    sections = []
    for i in range(6):
        sections.append(f"## Section {i}\n\nShort body for section {i} with enough words to stand alone. " * 30)
    md_content = "\n\n".join(sections)

    chunks, _ = run_process_md(md_content, target_chunk_words=1200)

    if len(chunks) < 2:
        raise AssertionError(f"Expected heading-based chunks, got {len(chunks)}.")

    joined = normalized(" ".join(c["content"] for c in chunks))
    for i in range(6):
        if f"Short body for section {i}" not in joined:
            raise AssertionError(f"Section {i} content missing from chunks.")

    print(f"   {len(chunks)} chunks produced from 6 headed sections")
    print("Heading split test passed!")
    return True


def test_small_markdown_is_untouched():
    """A small document must still produce a single chunk."""
    print("Testing small Markdown document...")

    md_content = "# Title\n\nA short paragraph that comfortably fits in one chunk.\n"
    chunks, _ = run_process_md(md_content, target_chunk_words=1200)

    if len(chunks) != 1:
        raise AssertionError(f"Expected exactly 1 chunk for a small document, got {len(chunks)}.")
    if "short paragraph" not in chunks[0]["content"]:
        raise AssertionError("Small document content was altered.")

    print("Small document test passed!")
    return True


def test_chunk_size_cap_is_unit_aware():
    """Word and character fields must not share a single numeric cap."""
    print("Testing unit-aware chunk size cap...")

    ns = build_settings_namespace()
    settings = {}

    word_cap = ns["get_chunk_size_cap"](settings, "words")
    char_cap = ns["get_chunk_size_cap"](settings, "characters")
    page_cap = ns["get_chunk_size_cap"](settings, "pages")

    if word_cap >= char_cap:
        raise AssertionError(f"Word cap ({word_cap}) must be smaller than character cap ({char_cap}).")

    usable_tokens = ns["get_embedding_usable_tokens"](settings)
    if word_cap * ns["EMBEDDING_TOKENS_PER_WORD"] > usable_tokens:
        raise AssertionError(f"Word cap {word_cap} can exceed the usable token budget {usable_tokens}.")
    if char_cap / ns["EMBEDDING_CHARS_PER_TOKEN"] > usable_tokens:
        raise AssertionError(f"Character cap {char_cap} can exceed the usable token budget {usable_tokens}.")

    # Before the fix this permitted 16,384 words, which can never embed.
    if word_cap >= 16384:
        raise AssertionError(f"Word cap {word_cap} is still the unit-blind structural cap.")
    if page_cap != ns["CHUNK_SIZE_STRUCTURAL_FALLBACK_CAP"]:
        raise AssertionError(f"Structural units should keep the historical cap, got {page_cap}.")

    over = {
        "enable_chunk_size_override": True,
        "chunk_size": {
            "md": {"value": 16384, "unit": "words"},
            "json": {"value": 999999, "unit": "characters"},
        },
    }
    config = ns["get_chunk_size_config"](over)
    if config["md"]["value"] != word_cap:
        raise AssertionError(f"Markdown override should clamp to {word_cap}, got {config['md']['value']}.")
    if config["json"]["value"] != char_cap:
        raise AssertionError(f"JSON override should clamp to {char_cap}, got {config['json']['value']}.")

    # Shipping defaults must be unaffected by the new caps.
    if ns["get_chunk_size_config"]({}) != ns["get_chunk_size_defaults"]():
        raise AssertionError("Default chunk sizes changed, which was not intended.")

    print(f"   words {word_cap}, characters {char_cap}, pages {page_cap}; defaults unchanged")
    print("Unit-aware cap test passed!")
    return True


def test_save_chunks_clamps_only_the_embedding_input():
    """The embed-time guard must bound the vector input while storing the full chunk text."""
    print("Testing save_chunks embedding guard...")

    source = (APP_ROOT / "functions_documents.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    save_chunks_node = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "save_chunks"),
        None,
    )
    if save_chunks_node is None:
        raise AssertionError("save_chunks not found in functions_documents.py")

    body_src = ast.get_source_segment(source, save_chunks_node)

    if "generate_embedding(embedding_input)" not in body_src:
        raise AssertionError("save_chunks must embed the clamped input, not the raw chunk text.")
    if "embedding_input = embedding_input[:max_embedding_characters]" not in body_src:
        raise AssertionError("save_chunks must clamp the embedding input to the character budget.")

    # The stored text must remain the untouched chunk, so citations keep the full content.
    if "page_text_content = page_text_content[:" in body_src:
        raise AssertionError("save_chunks must not truncate the stored chunk text.")
    if "enhanced_chunk_text = page_text_content" not in body_src:
        raise AssertionError("save_chunks should still store the full page_text_content.")

    print("save_chunks guard test passed!")
    return True


def test_process_md_wires_both_bounds():
    """process_md must cap sections before merging and apply the character backstop after."""
    print("Testing process_md wiring...")

    source = (APP_ROOT / "functions_documents.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "process_md"), None)
    if node is None:
        raise AssertionError("process_md not found in functions_documents.py")

    body_src = ast.get_source_segment(source, node)

    word_cap_at = body_src.find("split_text_by_word_limit(")
    merge_at = body_src.find("buffer_chunk = \"\"")
    backstop_at = body_src.find("split_oversized_chunks(")

    if word_cap_at == -1:
        raise AssertionError("process_md does not cap header sections by word count.")
    if backstop_at == -1:
        raise AssertionError("process_md does not apply the character backstop.")
    if not word_cap_at < merge_at < backstop_at:
        raise AssertionError(
            "Ordering is wrong: sections must be capped before the merge loop and the character "
            f"backstop applied after it (cap={word_cap_at}, merge={merge_at}, backstop={backstop_at})."
        )

    print("process_md wiring test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version must be at or beyond the version this fix shipped in."""
    print("Testing application version...")
    assert_app_version_at_least(IMPLEMENTED_IN_VERSION)
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_oversized_section_is_bounded,
        test_no_content_is_lost,
        test_normal_markdown_still_splits_on_headings,
        test_small_markdown_is_untouched,
        test_chunk_size_cap_is_unit_aware,
        test_save_chunks_clamps_only_the_embedding_input,
        test_process_md_wires_both_bounds,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
