# test_v2_public_directory_list_route_pin.py
"""
Static pin: the V2 client lists public workspaces only through the native directory route.
Version: 0.261.179
Implemented in: 0.261.175
Create POST exception added in: 0.261.179

M9A unifies both public-workspace listings in the V2 SPA -- the directory page's own adapter and the
public workspace picker -- onto `GET /api/public_workspaces/directory`, and retires the bare classic
list `GET /api/public_workspaces`, which discloses more than the directory should (an owner email on
every row). A regression that pointed either reader back at the bare list would still pass its own
mocked browser test while leaking, so this pin reads the real source and fails if any V2 string
addresses `/api/public_workspaces` with anything but a `/`-delimited sub-route (`/directory`,
`/setActive`, `/<id>/logo`). It also proves both the picker and the directory adapter name the
directory route, so a swap back to the bare list fails here first.

This is a source pin, not a runtime test: it parses the strings the bundle would ship, so it holds
even for a code path a browser suite does not happen to exercise.

One bare-route string is allowed: from 0.261.179 the directory's Create dialog reuses the classic
create route, `POST /api/public_workspaces`, which creates rather than lists and answers `{ id, name }`.
Only that exact POST call in the directory adapter is exempt, and the pin requires there to be exactly
one, so the exception can't spread to a listing call.
"""

import re
from pathlib import Path

import pytest


V2_SRC = Path(__file__).resolve().parents[1] / "application" / "v2_ui" / "src"
PICKER_FILE = V2_SRC / "lib" / "workspaces.ts"
ADAPTER_FILE = V2_SRC / "lib" / "publicDirectory.ts"

# A public-workspaces URL written as a code string: a quote or backtick, the path, then one more
# character. Comments write the path without a leading quote, so only real string literals match.
STRING_USAGE = re.compile(r"""['"`]/api/public_workspaces(.)""")

DIRECTORY_ROUTE = "/api/public_workspaces/directory"

# The one allowed bare-route string: the Create dialog's POST to the classic create route.
CREATE_POST = "'/api/public_workspaces', { method: 'POST'"


def _is_create_post(path, text, match):
    return path == ADAPTER_FILE and text.startswith(CREATE_POST, match.start())


def _source_files():
    return sorted(path for path in V2_SRC.rglob("*") if path.suffix in (".ts", ".tsx"))


def test_no_v2_string_addresses_the_bare_public_list():
    """Every V2 string that names the public-workspaces route uses a `/`-delimited sub-route."""
    offenders = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        for match in STRING_USAGE.finditer(text):
            if match.group(1) != "/" and not _is_create_post(path, text, match):
                offenders.append(f"{path.relative_to(V2_SRC)}: {match.group(0)!r}")
    assert not offenders, (
        "A V2 string addresses the retired bare public list instead of a directory sub-route: "
        + "; ".join(offenders)
    )


def test_the_only_bare_route_string_is_the_create_post():
    """Exactly one V2 string uses the bare route, and it's the directory adapter's create POST."""
    creates = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        creates += [path for match in STRING_USAGE.finditer(text) if _is_create_post(path, text, match)]
    assert creates == [ADAPTER_FILE], f"Expected one create POST in the directory adapter, found {creates}"


def test_the_picker_lists_through_the_directory_route():
    """The public workspace picker reads the native directory route, not the classic list."""
    source = PICKER_FILE.read_text(encoding="utf-8")
    assert DIRECTORY_ROUTE in source, "The public workspace picker must list through the directory route."


def test_the_directory_adapter_reads_the_directory_route():
    """The directory page's own adapter reads the native directory route."""
    source = ADAPTER_FILE.read_text(encoding="utf-8")
    assert DIRECTORY_ROUTE in source, "The public directory adapter must read the directory route."


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
