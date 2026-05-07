# test_local_agent_cognitive_services_scope.py
#!/usr/bin/env python3
"""
Functional test for local agent cognitive services scope resolution.
Version: 0.241.007
Implemented in: 0.241.007

This test ensures local agents inherit cognitive_services_scope from config.py
while Foundry agents continue using provider-specific scope resolution.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOADER_FILE = ROOT / "application" / "single_app" / "semantic_kernel_loader.py"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
FIX_DOC_FILE = (
    ROOT
    / "docs"
    / "explanation"
    / "fixes"
    / "v0.241.007"
    / "LOCAL_AGENT_COGNITIVE_SERVICES_SCOPE_FIX.md"
)


def read_text(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8")


def test_local_agent_cognitive_services_scope() -> None:
    print("🔍 Validating local agent cognitive services scope resolution...")

    loader_content = read_text(LOADER_FILE)
    config_content = read_text(CONFIG_FILE)
    fix_doc_content = read_text(FIX_DOC_FILE)

    assert "from config import cognitive_services_scope" in loader_content, (
        "The loader should import cognitive_services_scope from config.py."
    )
    assert "def resolve_aoai_scope():" in loader_content, (
        "The loader should centralize Azure OpenAI scope resolution in a shared helper."
    )
    assert "return str(cognitive_services_scope or \"\").strip()" in loader_content, (
        "The Azure OpenAI scope helper should use config.py as the source of truth."
    )
    assert 'scope = "https://cognitiveservices.azure.com/.default"' not in loader_content, (
        "The loader must not hardcode the commercial cognitive services scope for local agents."
    )
    assert 'scope = resolve_foundry_scope(auth_settings, endpoint=endpoint)' in loader_content, (
        "Foundry providers should continue to resolve scope through the Foundry-specific helper."
    )
    assert "scope = resolve_aoai_scope()" in loader_content, (
        "Azure OpenAI token providers should use the shared config-backed scope helper."
    )
    assert 'load_single_agent_for_kernel(kernel, agent_cfg, settings, g, redis_client=redis_client, mode_label="per-user", group_scope_id=effective_group_id)' in loader_content, (
        "Per-user agent loading should keep routing personal and group local agents through the shared loader path."
    )
    assert "load_single_agent_for_kernel(kernel, global_selected_agent_cfg, settings, builtins" in loader_content, (
        "Global local agents should also use the shared loader path."
    )
    assert 'VERSION = "0.241.007"' in config_content, (
        "config.py should be updated to version 0.241.007 for this fix."
    )
    assert "Fixed/Implemented in version: **0.241.007**" in fix_doc_content, (
        "Fix documentation should record the implementation version."
    )
    assert "personal, group, and global local agents all resolve through the same shared loader helper" in fix_doc_content, (
        "Fix documentation should explain how the shared loader path covers all local agent scopes."
    )

    print("✅ Local agent cognitive services scope checks passed.")


if __name__ == "__main__":
    try:
        test_local_agent_cognitive_services_scope()
        success = True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback

        traceback.print_exc()
        success = False

    raise SystemExit(0 if success else 1)