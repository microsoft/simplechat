# settings_cache.py
APP_SETTINGS_CACHE = {}

def update_settings_cache(new_settings):
    global APP_SETTINGS_CACHE
    APP_SETTINGS_CACHE = new_settings

def get_settings_cache():
    return APP_SETTINGS_CACHE