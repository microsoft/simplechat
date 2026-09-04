#!/usr/bin/env python3
# test_model_vision_capability_resolution.py
"""
Functional test for how the application decides a model can accept images.
Version: 0.261.072
Implemented in: 0.261.072

Multi-Modal Vision Analysis sends page images to a model, so it can only offer
models that read them. That was decided by a regular expression over the model's
name, which is wrong in both directions: it admits ``gpt-5.3-chat``, a text-only
chat variant, and it says nothing at all about a self-hosted deployment whose
name follows no OpenAI convention. Neither case could be corrected, because the
rule was in the code.

``static/json/model_capabilities.json`` has shipped here for some time carrying
real ``processesImages`` data that nothing read. These checks pin the three-tier
resolution that now uses it, and in particular the precedence between the tiers:
an administrator's explicit decision has to win, or correcting a wrong answer
would be impossible.
"""

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = (
    REPO_ROOT
    / "application"
    / "single_app"
    / "static"
    / "json"
    / "model_capabilities.json"
)

capabilities_module = import_app_module("functions_model_capabilities")
resolve = capabilities_module.resolve_model_vision_support
is_vision_capable = capabilities_module.is_vision_capable_model


def test_the_catalog_declares_vision_support_for_every_model():
    """A model missing the field falls through to a guess it should not need."""
    print("Testing catalog completeness...")

    assert_app_version_at_least("0.261.072")

    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    models = document.get("models") or []
    assert models, "The capability catalog lists no models."

    missing = [
        model.get("id")
        for model in models
        if "processesImages" not in (model.get("capabilities") or {})
    ]
    assert not missing, (
        "These catalog entries do not declare processesImages, so they would "
        "fall through to the name heuristic the catalog exists to replace:\n  "
        + "\n  ".join(str(name) for name in missing)
    )

    print(f"  All {len(models)} catalog model(s) declare processesImages.")
    return True


def test_the_catalog_is_read():
    """A catalog that fails to load silently degrades to the old guess."""
    print("\nTesting catalog loading...")

    catalog = capabilities_module.load_model_capability_catalog(force_refresh=True)
    assert catalog, (
        "The capability catalog loaded as empty. Vision support would fall back "
        "to the name heuristic for every model."
    )

    # Identifiers are indexed normalized, so a lookup and an entry agree however
    # the name was punctuated.
    assert capabilities_module._normalize_model_identifier("gpt-5.6") in catalog, (
        "The alias 'gpt-5.6' did not resolve; aliases are not being indexed."
    )

    print(f"  {len(catalog)} identifier(s) indexed from the catalog.")
    return True


def test_the_catalog_overrules_the_name_heuristic():
    """This is the point: the heuristic is wrong and the catalog is not."""
    print("\nTesting catalog precedence over the heuristic...")

    # The heuristic matches gpt-[5-9], so it calls this a vision model. The
    # catalog says it is a text-only chat variant, and the catalog is right.
    assert capabilities_module.is_vision_capable_model_name("gpt-5.3-chat"), (
        "The heuristic no longer matches gpt-5.3-chat, so this check is "
        "comparing nothing. Point it at a model the heuristic still gets wrong."
    )

    supports, source = resolve("gpt-5.3-chat")
    assert source == capabilities_module.VISION_SOURCE_CATALOG, source
    assert supports is False, (
        "gpt-5.3-chat resolved as vision-capable. The catalog declares it "
        "text-only, and offering it for image analysis would fail at runtime."
    )

    # A real vision model resolves from the catalog rather than by its name.
    supports, source = resolve("gpt-5.6-sol")
    assert supports is True, "gpt-5.6-sol should resolve as vision-capable."
    assert source == capabilities_module.VISION_SOURCE_CATALOG, source

    print("  The catalog decides where it disagrees with the heuristic.")
    return True


def test_an_explicit_flag_wins():
    """Without this an administrator cannot correct a wrong answer."""
    print("\nTesting the explicit flag...")

    # Catalog says no; the administrator says yes.
    supports, source = resolve({"modelName": "gpt-5.3-chat", "supportsVision": True})
    assert supports is True, "An explicit True was overruled by the catalog."
    assert source == capabilities_module.VISION_SOURCE_DECLARED, source

    # Catalog says yes; the administrator says no, perhaps because their
    # deployment is configured without image input.
    supports, source = resolve({"modelName": "gpt-5.6-sol", "supportsVision": False})
    assert supports is False, "An explicit False was overruled by the catalog."
    assert source == capabilities_module.VISION_SOURCE_DECLARED, source

    # A settings document written by hand may hold the form-shaped string.
    supports, source = resolve({"modelName": "some-local-model", "supportsVision": "on"})
    assert supports is True, supports
    assert source == capabilities_module.VISION_SOURCE_DECLARED, source

    # Absent means undecided, not False, or every model would need the flag set.
    _supports, source = resolve({"modelName": "gpt-5.6-sol"})
    assert source == capabilities_module.VISION_SOURCE_CATALOG, (
        "A model with no explicit flag should fall through to the catalog, not "
        "be read as an explicit False."
    )

    print("  An administrator's decision overrules the catalog in both directions.")
    return True


def test_an_unknown_model_still_falls_back_to_the_heuristic():
    """Refusing to guess would hide working models from existing deployments."""
    print("\nTesting the heuristic fallback...")

    # The catalog covers current models; gpt-4o predates it and is not listed.
    # A great many deployments still run it, so the heuristic still has to
    # recognise it rather than the model disappearing from the picker.
    supports, source = resolve("gpt-4o")
    assert supports is True, (
        "gpt-4o resolved as not vision-capable. It is absent from the catalog, "
        "so the heuristic has to carry it, or existing deployments would lose "
        "the model they are using."
    )
    assert source == capabilities_module.VISION_SOURCE_INFERRED, source

    # Something neither tier knows is reported as inferred, so a caller can say
    # the answer is a guess.
    supports, source = resolve("acme-internal-llm-v3")
    assert source == capabilities_module.VISION_SOURCE_INFERRED, source
    assert supports is False, supports

    print("  Unknown models fall back to the heuristic, reported as inferred.")
    return True


def test_a_deployment_suffix_resolves_to_its_base_model():
    """Deployments are rarely named exactly after the model they serve."""
    print("\nTesting deployment name matching...")

    supports, source = resolve("gpt-5.6-sol-2026-07-09")
    assert source == capabilities_module.VISION_SOURCE_CATALOG, (
        "A dated deployment name should match its base model in the catalog "
        f"rather than being guessed at: {source}"
    )
    assert supports is True, supports

    # The longest matching entry wins, so a specific model does not inherit a
    # more general one's capabilities. gpt-5.6-sol sees images; gpt-5.3-chat
    # does not, and both start with "gpt-5".
    catalog = capabilities_module.load_model_capability_catalog()
    normalize = capabilities_module._normalize_model_identifier
    assert normalize("gpt-5") in catalog, "gpt-5 is not in the catalog; check is stale."
    assert normalize("gpt-5.3-chat") in catalog, "gpt-5.3-chat is not in the catalog."

    supports, source = resolve("gpt-5.3-chat-eastus")
    assert source == capabilities_module.VISION_SOURCE_CATALOG, source
    assert supports is False, (
        "gpt-5.3-chat-eastus matched a shorter catalog entry than gpt-5.3-chat, "
        "so it inherited the wrong capabilities."
    )

    print("  Deployment names resolve to their longest matching base model.")
    return True


def test_the_public_surface_is_unchanged():
    """Existing callers pass records and strings and must keep working."""
    print("\nTesting the public helpers...")

    assert is_vision_capable("gpt-5.6-sol") is True
    assert is_vision_capable("acme-internal-llm-v3") is False
    assert is_vision_capable({"deploymentName": "gpt-4o-prod"}) is True
    assert is_vision_capable({"displayName": "GPT-4o"}) is True
    assert is_vision_capable({"supportsVision": True, "modelName": "anything"}) is True

    # A record with nothing recognisable must not raise.
    assert is_vision_capable({}) is False
    assert is_vision_capable(None) is False

    print("  The public helpers accept records and strings as before.")
    return True


def test_a_missing_catalog_degrades_rather_than_raising():
    """A deployment without the catalog file must still start."""
    print("\nTesting missing-catalog behaviour...")

    original = capabilities_module.CATALOG_FILENAME
    try:
        capabilities_module.CATALOG_FILENAME = "static/json/does-not-exist.json"
        catalog = capabilities_module.load_model_capability_catalog(force_refresh=True)
        assert catalog == {}, catalog

        # Falls through to the heuristic, which is what the application did
        # before the catalog was consulted at all.
        supports, source = resolve("gpt-5.6-sol")
        assert supports is True, supports
        assert source == capabilities_module.VISION_SOURCE_INFERRED, source
    finally:
        capabilities_module.CATALOG_FILENAME = original
        capabilities_module.load_model_capability_catalog(force_refresh=True)

    print("  A missing catalog degrades to the heuristic without raising.")
    return True


if __name__ == "__main__":
    tests = [
        test_the_catalog_declares_vision_support_for_every_model,
        test_the_catalog_is_read,
        test_the_catalog_overrules_the_name_heuristic,
        test_an_explicit_flag_wins,
        test_an_unknown_model_still_falls_back_to_the_heuristic,
        test_a_deployment_suffix_resolves_to_its_base_model,
        test_the_public_surface_is_unchanged,
        test_a_missing_catalog_degrades_rather_than_raising,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
