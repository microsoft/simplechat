# test_ai_search_client_configuration.py
"""
Real-module regression coverage for Azure Search client configuration.
Version: 0.261.125
Implemented in: 0.261.125

Cold imports must expose the Search audience in every cloud, including public
Azure. External I/O is blocked; neither config nor the client factory is stubbed.
"""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import os
from pathlib import Path
import sys
from unittest.mock import patch

root = Path(sys.argv[1])
cloud = sys.argv[2]
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))
from test_support.offline_bootstrap import offline_app_imports

def check(condition, message):
    if not condition:
        raise AssertionError(message)

environment = {
    "AZURE_ENVIRONMENT": cloud,
    "CUSTOM_IDENTITY_URL_VALUE": "https://identity.example.test" if cloud == "custom" else "",
    "CUSTOM_GRAPH_AUTHORITY_URL_VALUE": "",
    "CUSTOM_SEARCH_RESOURCE_MANAGER_URL_VALUE": "https://search.example.test",
}
with patch.dict(os.environ, environment), offline_app_imports():
    import config
    import functions_embedding_compatibility as compatibility
    expected = {
        "public": "https://search.azure.com",
        "usgovernment": "https://search.azure.us",
        "custom": "https://search.example.test",
    }[cloud]
    check(config.search_resource_manager == expected, "Missing or incorrect Search audience")
    with patch.object(compatibility, "SearchIndexClient") as client:
        unconfigured = compatibility.get_embedding_search_index_client({})
        check(unconfigured is None, "Unconfigured Search unexpectedly constructs a client")
        client.assert_not_called()
        for authentication in ("key", "managed_identity"):
            settings = {
                "azure_ai_search_endpoint": "https://offline.search.windows.net",
                "azure_ai_search_authentication_type": authentication,
                "azure_ai_search_key": "synthetic-test-only",
            }
            compatibility.get_embedding_search_index_client(settings)
            options = client.call_args.kwargs
            check(options["endpoint"] == settings["azure_ai_search_endpoint"], "Wrong endpoint")
            if authentication == "managed_identity" and cloud != "public":
                check(options["audience"] == expected, "Wrong managed-identity audience")
            else:
                check("audience" not in options, "Existing public/key authentication changed")
        compatibility.get_embedding_search_index_client({
            "enable_ai_search_apim": True,
            "azure_apim_ai_search_endpoint": "https://gateway.example.test/search",
            "azure_apim_ai_search_subscription_key": "synthetic-gateway-key",
        })
        options = client.call_args.kwargs
        check(options["endpoint"] == "https://gateway.example.test/search", "Wrong APIM endpoint")
        check("audience" not in options, "APIM unexpectedly uses managed-identity authentication")
print("PASS: real Search configuration and factory; no network")
'''


@pytest.mark.parametrize("cloud", ["public", "usgovernment", "custom"])
@pytest.mark.parametrize("optimized", [False, True])
def test_real_search_configuration_and_factory(cloud, optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", PROBE, str(ROOT), cloud],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: real Search configuration" in result.stdout
