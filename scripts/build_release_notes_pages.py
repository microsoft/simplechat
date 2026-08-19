# build_release_notes_pages.py
"""Generate split Jekyll release note pages from the authoring source."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


SOURCE_PATH = Path("docs") / "explanation" / "release_notes.md"
DEFAULT_OUTPUT_DIR = Path("docs") / "explanation" / "release-notes"
VERSION_HEADING_RE = re.compile(
    r"(?m)^#{2,4}\s*\*?\*?\(?v?(\d+\.\d+\.\d+)\)?\*?\*?.*$"
)
LATEST_INLINE_RELEASES = 12
MAX_RELEASES_PER_PAGE = 40
MAX_PAGE_BYTES = 250 * 1024
EARLIER_MINOR_CUTOFF = 215
GENERATED_BANNER = (
    "<!-- Generated from docs/explanation/release_notes.md by "
    "scripts/build_release_notes_pages.py. Regenerate with: "
    "python scripts/build_release_notes_pages.py -->"
)


@dataclass(frozen=True)
class ReleaseSection:
    """A single release notes version section."""

    version: str
    content: str
    source_index: int

    @property
    def minor_series(self) -> str:
        parts = self.version.split(".")
        return f"{parts[0]}.{parts[1]}"

    @property
    def patch_number(self) -> int:
        return int(self.version.split(".")[2])


@dataclass(frozen=True)
class GeneratedPage:
    """A generated Markdown page and its release sections."""

    filename: str
    title: str
    description: str
    content: str
    releases: tuple[ReleaseSection, ...]
    permalink: str | None = None

    @property
    def size_bytes(self) -> int:
        return len(self.content.encode("utf-8"))


def read_source(repo_root: Path) -> str:
    source_file = repo_root / SOURCE_PATH
    return source_file.read_text(encoding="utf-8")


def parse_release_notes(source_text: str) -> tuple[str, list[ReleaseSection]]:
    source_text = strip_front_matter(source_text)
    matches = list(VERSION_HEADING_RE.finditer(source_text))
    if not matches:
        raise ValueError("No release version headings were found.")

    intro = source_text[: matches[0].start()].strip()
    sections: list[ReleaseSection] = []
    for index, match in enumerate(matches):
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(source_text)
        content = source_text[match.start() : section_end].strip()
        sections.append(
            ReleaseSection(
                version=match.group(1),
                content=content,
                source_index=index,
            )
        )

    return intro, sections


def strip_front_matter(source_text: str) -> str:
    if not source_text.startswith("---\n"):
        return source_text

    front_matter_end = source_text.find("\n---\n", 4)
    if front_matter_end == -1:
        return source_text

    return source_text[front_matter_end + len("\n---\n") :]


def front_matter(title: str, description: str, permalink: str | None = None) -> str:
    lines = [
        "---",
        f'title: "{escape_yaml_text(title)}"',
        f'description: "{escape_yaml_text(description)}"',
        'section: "Reference"',
        "layout: page",
    ]
    if permalink:
        lines.append(f"permalink: {permalink}")
    lines.append("---")
    return "\n".join(lines)


def escape_yaml_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def make_page_content(
    title: str,
    description: str,
    body: str,
    permalink: str | None = None,
) -> str:
    return (
        f"{front_matter(title, description, permalink)}\n\n"
        f"{GENERATED_BANNER}\n\n"
        f"{body.rstrip()}\n"
    )


def series_sort_key(series: str) -> tuple[int, int]:
    major, minor = series.split(".")
    return int(major), int(minor)


def version_sort_key(version: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in version.split("."))


def is_earlier_release(release: ReleaseSection) -> bool:
    return int(release.minor_series.split(".")[1]) <= EARLIER_MINOR_CUTOFF


def make_slug(page_name: str) -> str:
    return f"/explanation/release-notes/{page_name.removesuffix('.md')}/"


def make_range_label(releases: tuple[ReleaseSection, ...]) -> str:
    newest = releases[0].version
    oldest = releases[-1].version
    return newest if newest == oldest else f"{newest} – {oldest}"


def page_body_for_releases(
    heading: str,
    releases: tuple[ReleaseSection, ...],
    include_back_link: bool = True,
) -> str:
    body_parts = [f"# {heading}"]
    if include_back_link:
        body_parts.append("[Back to release notes index]({{ '/explanation/release_notes/' | relative_url }})")
    body_parts.extend(release.content for release in releases)
    return "\n\n".join(body_parts)


def chunk_releases(releases: list[ReleaseSection]) -> list[tuple[ReleaseSection, ...]]:
    chunks: list[tuple[ReleaseSection, ...]] = []
    current: list[ReleaseSection] = []

    for release in releases:
        candidate = [*current, release]
        candidate_body = "\n\n".join(section.content for section in candidate)
        candidate_size = len(candidate_body.encode("utf-8"))
        if (
            current
            and (
                len(candidate) > MAX_RELEASES_PER_PAGE
                or candidate_size > MAX_PAGE_BYTES
            )
        ):
            chunks.append(tuple(current))
            current = [release]
        else:
            current = candidate

    if current:
        chunks.append(tuple(current))

    return chunks


def build_archive_pages(archive_releases: list[ReleaseSection]) -> list[GeneratedPage]:
    grouped: dict[str, list[ReleaseSection]] = {}
    earlier_releases: list[ReleaseSection] = []

    for release in archive_releases:
        if is_earlier_release(release):
            earlier_releases.append(release)
        else:
            grouped.setdefault(release.minor_series, []).append(release)

    pages: list[GeneratedPage] = []
    for series in sorted(grouped, key=series_sort_key, reverse=True):
        chunks = chunk_releases(grouped[series])
        for chunk_index, chunk in enumerate(chunks, start=1):
            range_label = make_range_label(chunk)
            if len(chunks) == 1:
                filename = f"v{series}.md"
                title = f"Release notes {series} series"
            else:
                filename = f"v{series}-part-{chunk_index}.md"
                title = f"Release notes {range_label}"
            description = f"SimpleChat release notes for {range_label}."
            body = page_body_for_releases(title, chunk)
            pages.append(
                GeneratedPage(
                    filename=filename,
                    title=title,
                    description=description,
                    content=make_page_content(title, description, body),
                    releases=chunk,
                )
            )

    if earlier_releases:
        earlier_chunk = tuple(earlier_releases)
        range_label = make_range_label(earlier_chunk)
        title = "Earlier releases"
        description = f"SimpleChat release notes for earlier versions: {range_label}."
        body = page_body_for_releases(title, earlier_chunk)
        pages.append(
            GeneratedPage(
                filename="earlier-releases.md",
                title=title,
                description=description,
                content=make_page_content(title, description, body),
                releases=earlier_chunk,
            )
        )

    return pages


def build_toc_rows(
    version_to_page: dict[int, tuple[ReleaseSection, str]],
    page_titles: dict[str, str],
) -> list[str]:
    rows = [
        "| Version | Page |",
        "| --- | --- |",
    ]
    for source_index in sorted(version_to_page):
        release, filename = version_to_page[source_index]
        if filename == "index.md":
            page_link = "{{ '/explanation/release_notes/' | relative_url }}"
            page_title = "Release notes index"
        else:
            page_link = f"{{{{ '{make_slug(filename)}' | relative_url }}}}"
            page_title = page_titles[filename]
        rows.append(f"| v{release.version} | [{page_title}]({page_link}) |")
    return rows


def build_pages(source_text: str) -> list[GeneratedPage]:
    intro, sections = parse_release_notes(source_text)
    latest_releases = tuple(sections[:LATEST_INLINE_RELEASES])
    archive_releases = sections[LATEST_INLINE_RELEASES:]
    archive_pages = build_archive_pages(archive_releases)

    version_to_page: dict[int, tuple[ReleaseSection, str]] = {}
    for release in latest_releases:
        version_to_page[release.source_index] = (release, "index.md")
    for page in archive_pages:
        for release in page.releases:
            version_to_page[release.source_index] = (release, page.filename)
    page_titles = {page.filename: page.title for page in archive_pages}

    title = "Release notes"
    description = "SimpleChat release notes index with latest updates and links to archived release pages."
    latest_body = page_body_for_releases("Latest release notes", latest_releases, include_back_link=False)
    latest_body = latest_body.replace("# Latest release notes", "## Latest release notes", 1)
    toc = "\n".join(build_toc_rows(version_to_page, page_titles))
    index_body = "\n\n".join(
        [
            "# Release notes",
            intro,
            (
                "This page includes the latest release notes inline. "
                "Older release sections are split into smaller pages by minor series."
            ),
            "## Version index",
            toc,
            latest_body,
        ]
    )
    index_page = GeneratedPage(
        filename="index.md",
        title=title,
        description=description,
        content=make_page_content(
            title,
            description,
            index_body,
            permalink="/explanation/release_notes/",
        ),
        releases=latest_releases,
        permalink="/explanation/release_notes/",
    )

    pages = [index_page, *archive_pages]
    validate_pages(sections, pages)
    return pages


def validate_pages(source_sections: list[ReleaseSection], pages: list[GeneratedPage]) -> None:
    generated_sections = [release for page in pages for release in page.releases]
    source_indexes = [release.source_index for release in generated_sections]
    expected_indexes = [release.source_index for release in source_sections]
    if sorted(source_indexes) != expected_indexes:
        raise ValueError("Generated pages do not contain exactly the source release sections.")

    oversized = [page for page in pages if page.size_bytes > MAX_PAGE_BYTES]
    if oversized:
        details = ", ".join(f"{page.filename} ({page.size_bytes} bytes)" for page in oversized)
        raise ValueError(f"Generated page exceeds {MAX_PAGE_BYTES} bytes: {details}")


def get_expected_files(pages: list[GeneratedPage], output_dir: Path) -> dict[Path, bytes]:
    return {
        output_dir / page.filename: page.content.encode("utf-8")
        for page in pages
    }


def check_output(expected_files: dict[Path, bytes], output_dir: Path) -> int:
    existing_files = set(output_dir.glob("*.md")) if output_dir.exists() else set()
    expected_paths = set(expected_files)
    differences: list[str] = []

    for path in sorted(expected_paths - existing_files):
        differences.append(f"missing: {path}")
    for path in sorted(existing_files - expected_paths):
        differences.append(f"extra: {path}")
    for path in sorted(expected_paths & existing_files):
        if path.read_bytes() != expected_files[path]:
            differences.append(f"different: {path}")

    if differences:
        print("Release notes generated output is out of sync:")
        for difference in differences:
            print(f"  {difference}")
        return 1

    print("Release notes generated output is in sync.")
    return 0


def write_output(expected_files: dict[Path, bytes], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_files = set(output_dir.glob("*.md"))
    expected_paths = set(expected_files)

    for stale_file in sorted(existing_files - expected_paths):
        stale_file.unlink()

    for path, content in sorted(expected_files.items()):
        path.write_bytes(content)


def print_summary(pages: list[GeneratedPage]) -> None:
    largest_page = max(pages, key=lambda page: page.size_bytes)
    total_releases = sum(len(page.releases) for page in pages)
    print(
        f"Generated {len(pages)} pages with {total_releases} release sections "
        f"(max {MAX_RELEASES_PER_PAGE} releases/page, {MAX_PAGE_BYTES} bytes/page)."
    )
    for page in pages:
        print(f"  {page.filename}: {len(page.releases)} releases, {page.size_bytes} bytes")
    print(f"Largest page: {largest_page.filename} ({largest_page.size_bytes} bytes)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate split release notes pages for the Jekyll docs site."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if generated release notes pages are out of sync.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where generated release notes pages are written.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir

    source_text = read_source(repo_root)
    pages = build_pages(source_text)
    expected_files = get_expected_files(pages, output_dir)

    if args.check:
        return check_output(expected_files, output_dir)

    write_output(expected_files, output_dir)
    print_summary(pages)
    return 0


if __name__ == "__main__":
    sys.exit(main())
