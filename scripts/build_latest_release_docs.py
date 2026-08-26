# build_latest_release_docs.py
"""Generate the docs-side Latest Release catalog from the in-app feature catalogs.

The app is the single source of truth. `support_menu_config.py` defines the user
catalog and the admin catalog, and this script projects the current release group
from each one onto the documentation site so the two surfaces cannot drift.

Archived release groups and their lookup entries are hand-maintained and are
round-tripped untouched.
"""

from __future__ import annotations

import argparse
import filecmp
import importlib.util
import re
import shutil
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
SUPPORT_CONFIG_PATH = APP_ROOT / "support_menu_config.py"
APP_IMAGE_DIR = APP_ROOT / "static" / "images" / "features"
DATA_PATH = REPO_ROOT / "docs" / "_data" / "latest_release_features.yml"
PAGES_DIR = REPO_ROOT / "docs" / "latest-release"
DOCS_IMAGE_DIR = REPO_ROOT / "docs" / "images" / "latest-release"

GENERATED_HEADER = (
    "# Generated in part by scripts/build_latest_release_docs.py.\n"
    "# The current_release and current_release_admin groups plus their lookup\n"
    "# entries are projected from application/single_app/support_menu_config.py.\n"
    "# Regenerate with: python scripts/build_latest_release_docs.py\n"
    "# Archived groups and their lookup entries are hand-maintained.\n"
)

ACCENT_CYCLE = (
    "blue",
    "teal",
    "violet",
    "emerald",
    "amber",
    "cyan",
    "orange",
    "rose",
    "slate",
)

USER_GROUP_KEY = "current_release"
ADMIN_GROUP_KEY = "current_release_admin"
USER_BADGE = "Current release"
ADMIN_BADGE = "Admin release"
USER_RELEASE_LABEL = "Current Release"
ADMIN_RELEASE_LABEL = "Admin Release"

VERSION_LINE_RE = re.compile(
    r"^(Current release version for .+?: \*\*)(\d+\.\d+\.\d+)(\*\*)$",
    re.MULTILINE,
)

# Pages carrying this front-matter key are rewritten from the catalog on every run.
# Hand-authored pages omit it and only have their release version line refreshed.
GENERATED_MARKER = "generated_from_catalog: true"

TIER_REFERENCE_RE = re.compile(r"(SimpleChat )(\d+\.\d+\.\d+)( latest-feature set)")
PLACEHOLDER_SECTION_RE = re.compile(
    r"^## Screenshot Placeholder\n.*?(?=^## )",
    re.MULTILINE | re.DOTALL,
)
PLACEHOLDER_IMAGE_RE = re.compile(r"`(/images/latest-release/[^`]+)`")


def load_support_config():
    """Import support_menu_config.py standalone, without booting the Flask app."""
    spec = importlib.util.spec_from_file_location(
        "support_menu_config_for_docs_generator", SUPPORT_CONFIG_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def slug_for(feature_id):
    """Map an app catalog id onto its documentation slug."""
    return str(feature_id).replace("_", "-")


def docs_image_path(app_path):
    """Map an app image path onto its published documentation path."""
    return "/images/latest-release/" + Path(str(app_path)).name


def build_lookup_entry(feature, slug, accent, release_label, release_version):
    """Project one app catalog card onto a docs lookup entry."""
    summary = feature.get("summary") or ""
    entry = {
        "title": feature.get("title") or slug,
        "description": summary,
        "summary": summary,
        "why": feature.get("why") or "",
        "icon": feature.get("icon") or "bi-stars",
        "accent": accent,
        "url": f"/latest-release/{slug}/",
        "release_label": release_label,
        "release_version": release_version,
    }

    gallery = []
    for image in feature.get("images") or []:
        gallery.append(
            {
                "path": docs_image_path(image.get("path")),
                "alt": image.get("alt") or "",
                "title": image.get("title") or "",
                "caption": image.get("caption") or "",
                "label": image.get("label") or "",
            }
        )

    if gallery:
        entry["image"] = gallery[0]["path"]
        entry["image_alt"] = gallery[0]["alt"]
        entry["images"] = gallery

    return entry


def build_group(group, badge, existing_group):
    """Build one docs release group block from an app release group."""
    return {
        "id": existing_group.get("id") if existing_group else group.get("id"),
        "label": group.get("label"),
        "description": group.get("description"),
        "badge": badge,
        "release_version": group.get("release_version"),
        "slugs": [slug_for(feature["id"]) for feature in group.get("features") or []],
    }


def load_existing_data():
    """Load the committed docs catalog so hand-maintained sections survive."""
    if not DATA_PATH.exists():
        return {}
    with DATA_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def build_data(support_config):
    """Assemble the full docs catalog mapping."""
    existing = load_existing_data()
    existing_lookup = existing.get("lookup") or {}

    user_group = support_config._SUPPORT_LATEST_FEATURE_RELEASE_GROUPS[0]
    admin_group = support_config._ADMIN_LATEST_FEATURE_RELEASE_GROUPS[0]

    data = {}
    data[USER_GROUP_KEY] = build_group(
        user_group, USER_BADGE, existing.get(USER_GROUP_KEY) or {}
    )
    data[USER_GROUP_KEY]["label"] = (
        f"SimpleChat {user_group.get('release_version')} Latest Features"
    )
    data[ADMIN_GROUP_KEY] = build_group(
        admin_group, ADMIN_BADGE, existing.get(ADMIN_GROUP_KEY) or {}
    )
    data[ADMIN_GROUP_KEY]["id"] = ADMIN_GROUP_KEY

    if existing.get("previous_release_groups"):
        data["previous_release_groups"] = existing["previous_release_groups"]

    lookup = dict(existing_lookup)
    generated_slugs = []

    for group, release_label in (
        (user_group, USER_RELEASE_LABEL),
        (admin_group, ADMIN_RELEASE_LABEL),
    ):
        for index, feature in enumerate(group.get("features") or []):
            slug = slug_for(feature["id"])
            accent = (existing_lookup.get(slug) or {}).get("accent") or ACCENT_CYCLE[
                index % len(ACCENT_CYCLE)
            ]
            lookup[slug] = build_lookup_entry(
                feature,
                slug,
                accent,
                release_label,
                group.get("release_version"),
            )
            generated_slugs.append(slug)

    data["lookup"] = {key: lookup[key] for key in sorted(lookup)}
    return data, generated_slugs, user_group.get("release_version")


def render_front_matter(title, summary):
    """Serialize page front matter as real YAML.

    Card titles and summaries contain quotes, so hand-built scalars are not safe.
    """
    front_matter = {
        "layout": "latest-release-feature",
        "title": title,
        "description": summary,
        "section": "Latest Release",
        "generated_from_catalog": True,
    }
    return yaml.safe_dump(
        front_matter,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=10**6,
    ).rstrip("\n")


def render_page(feature, slug, release_version):
    """Render a documentation page for a card that does not have one yet."""
    title = feature.get("title") or slug
    summary = feature.get("summary") or ""
    lines = [
        "---",
        render_front_matter(title, summary),
        "---",
        "",
        f"Current release version for {title}: **{release_version}**",
        "",
        feature.get("details") or summary,
        "",
        "## Why It Matters",
        "",
        feature.get("why") or "",
        "",
        "## How to Try It",
        "",
    ]

    for index, step in enumerate(feature.get("guidance") or [], start=1):
        lines.append(f"{index}. {step}")

    actions = feature.get("actions") or []
    if actions:
        lines.extend(["", "## Where to Find It", ""])
        for action in actions:
            label = action.get("label") or ""
            description = action.get("description") or ""
            lines.append(f"- **{label}** &mdash; {description}")

    lines.append("")
    return "\n".join(lines)


def collect_pages(support_config, release_version):
    """Return page paths that must exist, mapped to content for missing ones."""
    pages = {}
    groups = (
        support_config._SUPPORT_LATEST_FEATURE_RELEASE_GROUPS[0],
        support_config._ADMIN_LATEST_FEATURE_RELEASE_GROUPS[0],
    )
    for group in groups:
        for feature in group.get("features") or []:
            slug = slug_for(feature["id"])
            pages[PAGES_DIR / f"{slug}.md"] = render_page(
                feature, slug, release_version
            )
    return pages


def drop_resolved_placeholder_section(text):
    """Remove a Screenshot Placeholder section once every image it names is published.

    The layout renders the real gallery from the catalog, so the section is both
    redundant and wrong as soon as the captures land.
    """
    match = PLACEHOLDER_SECTION_RE.search(text)
    if not match:
        return text

    referenced = PLACEHOLDER_IMAGE_RE.findall(match.group(0))
    if not referenced:
        return text

    for reference in referenced:
        if not (DOCS_IMAGE_DIR / Path(reference).name).exists():
            return text

    return text[: match.start()] + text[match.end() :]


def refresh_authored_page(path, release_version):
    """Return hand-authored page text with stale release references cleaned up."""
    text = path.read_text(encoding="utf-8")
    text = VERSION_LINE_RE.sub(
        lambda match: f"{match.group(1)}{release_version}{match.group(3)}", text
    )
    text = TIER_REFERENCE_RE.sub(
        lambda match: f"{match.group(1)}{release_version}{match.group(3)}", text
    )
    return drop_resolved_placeholder_section(text)


def is_generated_page(path):
    """Return whether this page was authored by the generator rather than by hand."""
    return GENERATED_MARKER in path.read_text(encoding="utf-8")


def collect_images(support_config):
    """Return app image sources mapped to their documentation destinations."""
    images = {}
    groups = (
        support_config._SUPPORT_LATEST_FEATURE_RELEASE_GROUPS[0],
        support_config._ADMIN_LATEST_FEATURE_RELEASE_GROUPS[0],
    )
    for group in groups:
        for feature in group.get("features") or []:
            for image in feature.get("images") or []:
                name = Path(str(image.get("path"))).name
                if not name:
                    continue
                images[APP_IMAGE_DIR / name] = DOCS_IMAGE_DIR / name
    return images


def dump_data(data):
    """Serialize the docs catalog with the generated header."""
    body = yaml.safe_dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        width=120,
        allow_unicode=True,
    )
    return GENERATED_HEADER + body


def report(changes, check_only):
    """Print the outcome and return the process exit code."""
    if not changes:
        print("Latest release docs are up to date.")
        return 0

    verb = "would change" if check_only else "updated"
    print(f"{len(changes)} item(s) {verb}:")
    for item in changes:
        print(f"  - {item}")

    if check_only:
        print("\nRun: python scripts/build_latest_release_docs.py")
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report drift without writing files.",
    )
    args = parser.parse_args(argv)

    support_config = load_support_config()
    data, _generated_slugs, release_version = build_data(support_config)
    changes = []

    rendered = dump_data(data)
    if not DATA_PATH.exists() or DATA_PATH.read_text(encoding="utf-8") != rendered:
        changes.append(str(DATA_PATH.relative_to(REPO_ROOT)))
        if not args.check:
            DATA_PATH.write_text(rendered, encoding="utf-8")

    for path, content in sorted(collect_pages(support_config, release_version).items()):
        if not path.exists():
            changes.append(f"{path.relative_to(REPO_ROOT)} (new page)")
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            continue

        if is_generated_page(path):
            if path.read_text(encoding="utf-8") != content:
                changes.append(f"{path.relative_to(REPO_ROOT)} (regenerated)")
                if not args.check:
                    path.write_text(content, encoding="utf-8")
            continue

        relabelled = refresh_authored_page(path, release_version)
        if relabelled != path.read_text(encoding="utf-8"):
            changes.append(f"{path.relative_to(REPO_ROOT)} (release references)")
            if not args.check:
                path.write_text(relabelled, encoding="utf-8")

    for source, destination in sorted(collect_images(support_config).items()):
        if not source.exists():
            print(f"WARNING: missing app image {source.relative_to(REPO_ROOT)}")
            continue
        if destination.exists() and filecmp.cmp(source, destination, shallow=False):
            continue
        changes.append(f"{destination.relative_to(REPO_ROOT)} (image)")
        if not args.check:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

    return report(changes, args.check)


if __name__ == "__main__":
    sys.exit(main())
