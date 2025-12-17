# functions_security.py
"""Security-related helper functions."""

import re


SAFE_STORAGE_NAME_PATTERN = re.compile(r"^(?!.*\.\.)[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$")
SAFE_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def is_valid_storage_name(name: str) -> bool:
	"""Validate storage file names to prevent traversal and unsafe patterns."""
	if not name:
		return False
	if '/' in name or '\\' in name:
		return False
	return bool(SAFE_STORAGE_NAME_PATTERN.fullmatch(name))


def is_safe_slug(value: str) -> bool:
	"""Allowlist check for simple slug values (alnum, underscore, hyphen)."""
	if not value:
		return False
	return bool(SAFE_SLUG_PATTERN.fullmatch(value))
