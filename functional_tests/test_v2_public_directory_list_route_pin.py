# test_v2_public_directory_list_route_pin.py
"""
Static pin: the V2 client lists public workspaces only through the native directory route.
Version: 0.261.175
Implemented in: 0.261.175

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


def _source_files():
    return sorted(path for path in V2_SRC.rglob("*") if path.suffix in (".ts", ".tsx"))


def test_no_v2_string_addresses_the_bare_public_list():
    """Every V2 string that names the public-workspaces route uses a `/`-delimited sub-route."""
    offenders = []
    for path in _source_files():
        for match in STRING_USAGE.finditer(path.read_text(encoding="utf-8")):
            if match.group(1) != "/":
                offenders.append(f"{path.relative_to(V2_SRC)}: {match.group(0)!r}")
    assert not offenders, (
        "A V2 string addresses the retired bare public list instead of a directory sub-route: "
        + "; ".join(offenders)
    )


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
