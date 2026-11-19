# simplechat_playwright_node.py
"""Launch the pinned Playwright Node driver without App Service auto-instrumentation."""

import os
from pathlib import Path
import re
import sys
import sysconfig


_APP_SERVICE_LOADER = "/agents/nodejs/build/src/Loader.js"
_LOADER_PATTERN = re.escape(_APP_SERVICE_LOADER)
# Node separates options on unquoted spaces and interprets escapes within double quotes.
_OPTION = re.compile(
    rf'(?P<agent>(?:--require|-r)(?: +|=)(?:{_LOADER_PATTERN}|"{_LOADER_PATTERN}")(?= |$))'
    r'|(?:[^ "]+|"(?:[^"\\]|\\[\s\S])*")+'
)


def _without_app_service_loader(options: str) -> str:
    if _APP_SERVICE_LOADER not in options:
        return options

    kept = []
    end = 0
    removed = False
    for token in _OPTION.finditer(options):
        if options[end:token.start()].strip(" "):
            return options  # Let Node report malformed quoting.
        end = token.end()
        if token.lastgroup == "agent":
            removed = True
        else:
            kept.append(token.group())
    if not removed or options[end:].strip(" "):
        return options
    return " ".join(kept)


def main() -> None:
    node = str(Path(sysconfig.get_path("purelib")) / "playwright" / "driver" / "node")
    env = os.environ.copy()
    options = env.get("NODE_OPTIONS")
    if options is not None:
        env["NODE_OPTIONS"] = _without_app_service_loader(options)
    os.execve(node, [node, *sys.argv[1:]], env)


if __name__ == "__main__":
    main()
