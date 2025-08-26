# json_schema_validation.py
# Utility for loading and validating JSON schemas for agents and plugins
import os
import json
from functools import lru_cache
from jsonschema import validate, ValidationError, Draft7Validator, Draft6Validator

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), 'static', 'json', 'schemas')

@lru_cache(maxsize=8)
def load_schema(schema_name):
    path = os.path.join(SCHEMA_DIR, schema_name)
    with open(path, encoding='utf-8') as f:
        schema = json.load(f)
    return schema

def validate_agent(agent):
    schema = load_schema('agent.schema.json')
    validator = Draft7Validator(schema['definitions']['Agent'])
    errors = sorted(validator.iter_errors(agent), key=lambda e: e.path)
    if errors:
        return '; '.join([e.message for e in errors])
    return None

def validate_plugin(plugin):
    schema = load_schema('plugin.schema.json')
    validator = Draft7Validator(schema['definitions']['Plugin'])
    errors = sorted(validator.iter_errors(plugin), key=lambda e: e.path)
    if errors:
        return '; '.join([e.message for e in errors])
    return None
