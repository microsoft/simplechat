#!/usr/bin/env python3
"""
Functional test for the chat orchestration elicitation contract.
Version: 0.261.085
Implemented in: 0.261.085

When the orchestrator cannot plan without more information it asks in an inline card
rather than in the chat thread. The card is driven by a JSON Schema, and that schema is
deliberately shaped to the MCP elicitation specification: a flat object whose properties
are primitives, so any client can render it without implementing JSON Schema in general,
and so a future MCP server asking a question reuses the identical card.

This test ensures the restriction is enforced rather than merely intended, that our own
paging stays outside the schema so the schema remains MCP-clean, and that a response is
validated against the schema that was actually asked.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import stubbed_app_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _question():
    return {
        'message': 'Which documents should I look at?',
        'requested_schema': {
            'type': 'object',
            'properties': {
                'documents': {
                    'type': 'array',
                    'items': {'type': 'string', 'enum': ['docA', 'docB']},
                    'title': 'Documents',
                },
                'timeframe': {
                    'type': 'string',
                    'enum': ['Last quarter', 'Last year'],
                    'title': 'Period',
                },
            },
            'required': ['documents'],
        },
        'ui_hints': {'pages': [['documents']]},
    }


def test_enforces_the_mcp_restriction():
    """Nested and non-primitive fields are removed, not merely discouraged."""
    print("Testing orchestration elicitation schema restriction...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_schema as schema

            raw = _question()
            raw['requested_schema']['properties']['nested'] = {
                'type': 'object',
                'properties': {'inner': {'type': 'string'}},
            }
            raw['requested_schema']['properties']['objects'] = {
                'type': 'array',
                'items': {'type': 'object'},
            }

            question = schema.normalize_elicitation(raw, run_id='run1')
            properties = question['requested_schema']['properties']

            assert 'nested' not in properties, (
                "A nested object would reach a card that cannot draw it"
            )
            assert 'objects' not in properties, "An array of objects is not renderable"
            assert set(properties) == {'documents', 'timeframe'}

            for name, rules in properties.items():
                field_type = rules['type']
                if field_type == 'array':
                    assert rules['items']['type'] in schema.ELICITATION_PRIMITIVE_TYPES
                else:
                    assert field_type in schema.ELICITATION_PRIMITIVE_TYPES, (
                        f"{name} kept a non-primitive type"
                    )

            # A question with nothing renderable left is refused rather than shown empty.
            try:
                schema.normalize_elicitation(
                    {'requested_schema': {'properties': {'a': {'type': 'object'}}}},
                    run_id='run1',
                )
                raise AssertionError("An unrenderable question set was accepted")
            except schema.PlanValidationError:
                pass

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_paging_stays_outside_the_schema():
    """Our next/next/finish paging must not pollute the MCP schema."""
    print("Testing orchestration elicitation paging...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_schema as schema

            question = schema.normalize_elicitation(_question(), run_id='run1')

            assert set(question['requested_schema'].keys()) == {
                'type', 'properties', 'required'
            }, (
                f"The schema gained keys MCP does not define: "
                f"{sorted(question['requested_schema'].keys())}"
            )
            assert 'ui_hints' in question, "Paging has to live somewhere"

            pages = question['ui_hints']['pages']
            paged = [name for page in pages for name in page]
            assert sorted(paged) == ['documents', 'timeframe'], (
                f"Every field must appear on exactly one page: {pages}"
            )
            assert len(paged) == len(set(paged)), "A field was paged twice"
            assert question['ui_hints']['order']

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_response_validation():
    """A response is validated against the schema that was actually asked."""
    print("Testing orchestration elicitation responses...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_schema as schema

            question = schema.normalize_elicitation(_question(), run_id='run1')

            accepted, errors = schema.validate_elicitation_response(
                question,
                {'action': 'accept',
                 'content': {'documents': ['docA'], 'timeframe': 'Last year'}},
            )
            assert not errors, errors
            assert accepted['action'] == 'accept'
            assert accepted['content']['documents'] == ['docA']

            # A value that was never offered is refused rather than passed through.
            refused, errors = schema.validate_elicitation_response(
                question, {'action': 'accept', 'content': {'documents': ['docZ']}}
            )
            assert refused is None and errors

            # A required field cannot be omitted.
            missing, errors = schema.validate_elicitation_response(
                question, {'action': 'accept', 'content': {'timeframe': 'Last year'}}
            )
            assert missing is None and errors

            # Declining carries no content; reading any would be a way to smuggle answers
            # past the user's refusal.
            declined, errors = schema.validate_elicitation_response(
                question, {'action': 'decline', 'content': {'documents': ['docA']}}
            )
            assert not errors
            assert declined == {'action': 'decline', 'content': {}}

            unknown, errors = schema.validate_elicitation_response(
                question, {'action': 'proceed'}
            )
            assert unknown is None and errors

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    assert_app_version_at_least("0.261.085")

    tests = [
        test_enforces_the_mcp_restriction,
        test_paging_stays_outside_the_schema,
        test_response_validation,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
