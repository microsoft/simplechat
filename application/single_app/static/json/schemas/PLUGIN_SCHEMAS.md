# Plugin Schemas

This document provides information on how plugin schemas are structured and how to define them for your plugins.

## Overview

### .plugin.schema.json files

These files define the main configuration schema for each plugin. They are written in JSON Schema [DRAFT7](https://json-schema.org/draft-07) format and provide a way to validate the configuration options available for each plugin, as well as instantiate the plugin with the correct settings in both the UI and the application code. Having accurate schemas ensures that users can configure plugins correctly and that the application can handle these configurations without errors.

Your schema SHOULD declare which of the auth types your plugin supports.
Your schema MAY declare which patterns that need to be matched for other fields, default values, etc. It should inherit from the base schema located at [`application/single_app/static/json/schemas/plugin.schema.json`](/application/single_app/static/json/schemas/plugin.schema.json).

### .additional_settings.schema.json files

These files define the additional settings required for specific plugins. They are also written in JSON Schema [DRAFT7](https://json-schema.org/draft-07) format and provide a way to validate the additional configuration options available for each plugin, as well as instantiate the plugin with the correct settings in both the UI and the application code. Having accurate schemas ensures that users can configure plugins correctly and that the application can handle these configurations without errors.

Any additional settings schema properties that end with `__Secret` (double underscore) will be treated as sensitive information and will be stored in key vault if the option is enabled.