# offline_cosmos.py
"""Let functional tests import the real config.py when no Cosmos DB account is configured.

Version: 0.261.489
Implemented in: 0.261.489

config.py builds a Cosmos DB client and creates its containers while it is imported.
With no account configured that import fails, so every test that reaches it errors
although most only exercise application logic. ``install_offline_cosmos`` replaces
``azure.cosmos.CosmosClient`` with the in-memory client from ``offline_bootstrap`` for
the test process, for clients created with no endpoint or credential, and keeps background
tasks off. It does nothing when a Cosmos DB account is configured, unless
``SIMPLECHAT_TESTS_OFFLINE=1`` is set.

The in-memory database starts empty and its queries return no rows. A test that needs
real data must call ``require_live_cosmos`` (see ``live_services``), which still skips.
"""

import os

from test_support.live_services import missing_live_cosmos_settings


def install_offline_cosmos():
    """Install the in-memory Cosmos client; return True when it was installed."""
    if not missing_live_cosmos_settings():
        return False

    try:
        import azure.cosmos
    except ModuleNotFoundError:
        # Workflows that run only a few tests do not install the Azure SDK; nothing
        # in such a run imports config.py, so there is no client to replace.
        return False

    from test_support.offline_bootstrap import OfflineCosmos

    real_client = azure.cosmos.CosmosClient

    class UnconfiguredCosmosClient(real_client):
        """The real SDK client, except that it is in-memory when given no account to use.

        Tests that run the real SDK against their own local endpoint are unaffected.
        """

        def __new__(cls, url=None, credential=None, *args, **kwargs):
            if not url or not credential:
                return OfflineCosmos()
            return super().__new__(cls)

    azure.cosmos.CosmosClient = UnconfiguredCosmosClient
    os.environ.setdefault("SIMPLECHAT_RUN_BACKGROUND_TASKS", "0")
    os.environ.setdefault("DISABLE_FLASK_INSTRUMENTATION", "1")
    return True
