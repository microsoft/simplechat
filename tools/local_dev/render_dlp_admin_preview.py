# render_dlp_admin_preview.py
#!/usr/bin/env python3
"""
Extract the DLP admin settings card from a captured SimpleChat admin page.

Usage:
    python tools/local_dev/render_dlp_admin_preview.py .codex-local/admin-settings.html .codex-local
"""

import sys
from pathlib import Path

from bs4 import BeautifulSoup


def _wrap_preview(section_html):
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css" rel="stylesheet">
<style>
body {{ background:#f6f7fb; padding:32px; }}
.preview {{ max-width:1100px; margin:0 auto; }}
.card {{ box-shadow:0 1px 2px rgba(16,24,40,.06); }}
.d-none {{ display:none!important; }}
</style>
</head>
<body>
<main class="preview">
{section_html}
</main>
</body>
</html>
"""


def _expand_dlp_controls(section):
    for checkbox_id in [
        "enable_dlp_control_plane",
        "enable_web_search_dlp",
        "enable_upload_dlp",
    ]:
        node = section.select_one(f"#{checkbox_id}")
        if node:
            node["checked"] = ""

    for visible_id in [
        "dlp_control_plane_settings",
        "web_search_dlp_mode_settings",
        "upload_dlp_mode_settings",
    ]:
        node = section.select_one(f"#{visible_id}")
        if node and node.has_attr("class"):
            node["class"] = [class_name for class_name in node.get("class", []) if class_name != "d-none"]


def render_previews(source_path, output_dir):
    source_html = source_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(source_html, "html.parser")
    section = soup.select_one("#dlp-section")
    if section is None:
        raise ValueError("Could not find #dlp-section in captured admin settings HTML.")

    output_dir.mkdir(parents=True, exist_ok=True)
    collapsed_path = output_dir / "admin-dlp-preview.html"
    expanded_path = output_dir / "admin-dlp-preview-expanded.html"

    collapsed_path.write_text(_wrap_preview(str(section)), encoding="utf-8")
    _expand_dlp_controls(section)
    expanded_path.write_text(_wrap_preview(str(section)), encoding="utf-8")
    return collapsed_path, expanded_path


def main(argv):
    if len(argv) != 3:
        print("Usage: render_dlp_admin_preview.py <captured-admin-settings.html> <output-dir>")
        return 2

    source_path = Path(argv[1])
    output_dir = Path(argv[2])
    collapsed_path, expanded_path = render_previews(source_path, output_dir)
    print(f"Wrote {collapsed_path}")
    print(f"Wrote {expanded_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
