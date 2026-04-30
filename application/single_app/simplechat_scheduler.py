# simplechat_scheduler.py

"""Dedicated scheduler entrypoint for SimpleChat background tasks."""

import logging
import os
import sys

import app_settings_cache
from background_tasks import run_scheduler_forever
from config import get_redis_cache_infrastructure_endpoint, initialize_clients
from functions_appinsights import setup_appinsights_logging
from functions_settings import get_settings


def initialize_scheduler_runtime():
    """Prepare settings cache, clients, and logging for scheduler execution."""
    print('Initializing SimpleChat scheduler runtime...')
    settings = get_settings(use_cosmos=True)
    redis_hostname = settings.get('redis_url', '').strip().split('.')[0]
    app_settings_cache.configure_app_cache(
        settings,
        get_redis_cache_infrastructure_endpoint(redis_hostname)
    )
    app_settings_cache.update_settings_cache(settings)
    initialize_clients(settings)
    setup_appinsights_logging(settings)
    logging.basicConfig(level=logging.DEBUG)
    print('SimpleChat scheduler runtime initialized.')


if __name__ == '__main__':
    try:
        initialize_scheduler_runtime()
        run_scheduler_forever()
    except KeyboardInterrupt:
        print('SimpleChat scheduler stopped.')
        sys.exit(0)