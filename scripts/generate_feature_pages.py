# generate_feature_pages.py
"""Generate thin Jekyll feature collection pages from docs/_data/features.yml."""

import argparse
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
FEATURES_DATA_PATH = REPO_ROOT / "docs" / "_data" / "features.yml"
FEATURES_DIR = REPO_ROOT / "docs" / "_features"


def load_features():
    """Load the feature catalog data."""
    with FEATURES_DATA_PATH.open("r", encoding="utf-8") as data_file:
        features = yaml.safe_load(data_file) or {}
    if not isinstance(features, dict):
        raise ValueError("docs/_data/features.yml must contain a mapping of feature slugs.")
    return features


def render_stub(slug, title):
    """Render one deterministic feature page stub."""
    escaped_title = str(title).replace("\\", "\\\\").replace('"', '\\"')
    return f'---\nslug: {slug}\ntitle: "{escaped_title}"\n---\n'


def build_expected_files(features):
    """Return expected repo-relative page paths and contents."""
    expected_files = {}
    for slug in sorted(features):
        entry = features[slug] or {}
        title = entry.get("name") or slug.replace("-", " ").title()
        expected_files[FEATURES_DIR / f"{slug}.md"] = render_stub(slug, title)
    return expected_files


def find_existing_stubs():
    """Return existing generated feature stubs."""
    if not FEATURES_DIR.exists():
        return set()
    return {path for path in FEATURES_DIR.glob("*.md") if path.is_file()}


def check_files(expected_files):
    """Return paths that would change if the generator ran."""
    existing_files = find_existing_stubs()
    expected_paths = set(expected_files)
    changed_paths = []

    for path, expected_content in expected_files.items():
        if not path.exists() or path.read_text(encoding="utf-8") != expected_content:
            changed_paths.append(path)

    changed_paths.extend(sorted(existing_files - expected_paths))
    return sorted(changed_paths)


def write_files(expected_files):
    """Write expected stubs and delete stale stubs."""
    FEATURES_DIR.mkdir(parents=True, exist_ok=True)
    existing_files = find_existing_stubs()
    expected_paths = set(expected_files)
    written_count = 0
    deleted_count = 0

    for path, expected_content in expected_files.items():
        if not path.exists() or path.read_text(encoding="utf-8") != expected_content:
            path.write_text(expected_content, encoding="utf-8", newline="\n")
            written_count += 1

    for stale_path in sorted(existing_files - expected_paths):
        stale_path.unlink()
        deleted_count += 1

    return written_count, deleted_count


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if feature stubs differ from generated output.",
    )
    return parser.parse_args()


def main():
    """Run the feature page generator."""
    args = parse_args()
    features = load_features()
    expected_files = build_expected_files(features)

    if args.check:
        changed_paths = check_files(expected_files)
        if changed_paths:
            print("Feature stubs are out of date:")
            for path in changed_paths:
                print(path.relative_to(REPO_ROOT))
            return 1
        print(f"Feature stubs are up to date: {len(expected_files)} files.")
        return 0

    written_count, deleted_count = write_files(expected_files)
    print(
        "Generated feature stubs: "
        f"{len(expected_files)} expected, {written_count} written, {deleted_count} deleted."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
