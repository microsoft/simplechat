# templates.py
"""Shared helpers for reading composed SimpleChat templates in functional tests.

Admin Settings is assembled from per-tab partials under
``templates/admin/``. Any test that asserts on the rendered structure has to
read the fully composed markup instead of the parent template alone, so these
helpers inline ``{% include %}`` directives before the markup is parsed.
"""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "application" / "single_app" / "templates"
ADMIN_SETTINGS_TEMPLATE = TEMPLATE_DIR / "admin_settings.html"

INCLUDE_PATTERN = re.compile(
    r'^(?P<indent>[ \t]*)\{%-?\s*include\s+["\'](?P<target>[^"\']+)["\'].*?%\}',
    flags=re.MULTILINE,
)

# Only the Admin Settings tab partials are inlined by default. Unrelated
# includes (info modals and shared widgets) carry their own tab markup, and
# pulling them in would silently widen assertions that are meant to describe
# the Admin Settings panes alone.
DEFAULT_INCLUDE_PREFIX = "admin/"


def resolve_template_includes(
    source,
    template_dir=None,
    include_prefix=DEFAULT_INCLUDE_PREFIX,
    _seen=None,
):
    """Return ``source`` with resolvable ``{% include %}`` directives inlined.

    Only includes whose target starts with ``include_prefix`` are expanded;
    pass ``include_prefix=""`` to inline every resolvable include. Includes
    that cannot be found on disk, and includes that would recurse into a
    template already being expanded, are left untouched so the original markup
    is still visible to the caller.
    """
    directory = Path(template_dir) if template_dir else TEMPLATE_DIR
    seen = set() if _seen is None else _seen

    def _replace(match):
        target = match.group("target")
        partial = directory / target
        if include_prefix and not target.startswith(include_prefix):
            return match.group(0)
        if target in seen or not partial.is_file():
            return match.group(0)

        nested = resolve_template_includes(
            partial.read_text(encoding="utf-8"),
            directory,
            include_prefix,
            seen | {target},
        )
        indent = match.group("indent")
        return "\n".join(
            f"{indent}{line}" if line.strip() else line
            for line in nested.split("\n")
        )

    return INCLUDE_PATTERN.sub(_replace, source)


def read_composed_template(path, template_dir=None, include_prefix=DEFAULT_INCLUDE_PREFIX):
    """Read a template file with its Admin Settings includes inlined."""
    template_path = Path(path)
    directory = Path(template_dir) if template_dir else template_path.parent
    return resolve_template_includes(
        template_path.read_text(encoding="utf-8"),
        directory,
        include_prefix,
    )


def compose_if_admin_settings(path, content):
    """Inline Admin Settings partials when ``path`` is the admin template.

    Functional tests read many repository files through a single helper. Only
    admin_settings.html is composed from partials, so this leaves every other
    file untouched and keeps those tests reading exactly what is on disk.
    """
    template_path = Path(path)
    if template_path.name != "admin_settings.html":
        return content
    return resolve_template_includes(content, template_path.parent)


def read_admin_settings_template():
    """Read the fully composed Admin Settings template."""
    return read_composed_template(ADMIN_SETTINGS_TEMPLATE, TEMPLATE_DIR)
