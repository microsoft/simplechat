# cosmos_document_utils.py
"""Bootstrap-free normalization of Cosmos point document responses."""

from collections.abc import Mapping


def normalize_cosmos_document(value):
    """Return a plain top-level document, preserving fields and conditional ETags.

    Nested values belong to the domain contract and are deliberately unchanged.
    This is not a JSON validator, authorization check, or metadata sanitizer.
    """
    if not isinstance(value, Mapping):
        raise TypeError("A Cosmos document response must be a mapping.")
    return dict(value)
