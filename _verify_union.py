"""Assert the merged schema is exactly the union of both sides, with no duplicates.

Written for the merge; the duplicate-key half is worth keeping as a permanent
check, so it is folded into test_v2_admin_settings_schema.py afterwards.
"""

import ast
import subprocess
import sys
from pathlib import Path

SCHEMA = Path("application/single_app/admin_settings_fields.py")


def dict_keys_with_duplicates(source, name):
    """Return (unique keys, duplicate keys) for a module-level dict literal."""
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if name not in targets or not isinstance(node.value, ast.Dict):
            continue

        keys = [
            key.value
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        ]
        seen, duplicates = set(), []
        for key in keys:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        return seen, duplicates
    raise AssertionError(f"{name} not found")


def side(ref):
    return subprocess.run(
        ["git", "show", f"{ref}:application/single_app/admin_settings_fields.py"],
        capture_output=True,
        text=True,
        check=True,
        shell=(sys.platform == "win32"),
    ).stdout


merged_source = SCHEMA.read_text(encoding="utf-8")
mine, mine_dupes = dict_keys_with_duplicates(side("HEAD"), "ADMIN_SETTINGS_FIELDS")
theirs, their_dupes = dict_keys_with_duplicates(
    side("origin/paullizer-react-v2-ui"), "ADMIN_SETTINGS_FIELDS"
)
merged, merged_dupes = dict_keys_with_duplicates(merged_source, "ADMIN_SETTINGS_FIELDS")

print(f"mine:   {len(mine)} sections (duplicates: {mine_dupes or 'none'})")
print(f"theirs: {len(theirs)} sections (duplicates: {their_dupes or 'none'})")
print(f"merged: {len(merged)} sections (duplicates: {merged_dupes or 'none'})")

expected = mine | theirs
missing = sorted(expected - merged)
extra = sorted(merged - expected)

print(f"\nlost in the merge: {missing or 'none'}")
print(f"invented by the merge: {extra or 'none'}")

failed = bool(missing or extra or merged_dupes)

# The same check for every settings key, which is where a silent override would
# actually cost an administrator a control.
def field_keys(source):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ADMIN_SETTINGS_FIELDS"
            for t in node.targets
        ):
            found = []
            for value in node.value.values:
                if not isinstance(value, ast.List):
                    continue
                for item in value.elts:
                    if not isinstance(item, ast.Dict):
                        continue
                    for key, val in zip(item.keys, item.values):
                        if (
                            isinstance(key, ast.Constant)
                            and key.value == "key"
                            and isinstance(val, ast.Constant)
                        ):
                            found.append(val.value)
            return found
    return []


merged_field_keys = field_keys(merged_source)
duplicate_fields = sorted(
    {key for key in merged_field_keys if merged_field_keys.count(key) > 1}
)
print(f"\nfields declared twice: {duplicate_fields or 'none'}")
if duplicate_fields:
    failed = True

sys.exit(1 if failed else 0)
