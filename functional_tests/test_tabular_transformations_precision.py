# test_tabular_transformations_precision.py
"""
Functional tests for versioned bounded tabular calculation precision.
Version: 0.261.109
Implemented in: 0.261.109

Validate Decimal dependencies, explicit rounding, exact thresholds, numeric
projection limits, bounded work, and saved tabular-transform-v1 compatibility.
These tests exercise only the trusted interpreter, without model or service calls.
"""

from copy import deepcopy
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
import json
from pathlib import Path
import sys

import pytest


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# Standalone functional tests must establish the application import path first.
import functions_tabular_transformations as transformations  # noqa: E402


V1 = "tabular-transform-v1"
V2 = "tabular-transform-v2"


def _op(name, *values):
    return {"op": name, "values": list(values)}


def _round(value, scale=2, mode="half_up"):
    return {"op": "round", "value": value, "scale": scale, "mode": mode}


def _comparison(name, left, right, value_type="number"):
    return {"op": name, "left": left, "right": right, "value_type": value_type}


def _field(name, expression, field_type="number", **options):
    return {
        "name": name,
        "mode": "deterministic",
        "type": field_type,
        "expression": expression,
        **options,
    }


def _spec(expression, field_type="number", version=V2, **options):
    return {"version": version, "fields": [_field("result", expression, field_type, **options)]}


def _evaluate(expression, row=None, field_type="number", version=V2, **options):
    return transformations.evaluate_tabular_transformation_row(
        _spec(expression, field_type, version, **options),
        row or {},
    )["result"]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (_op("add", "0.1", "0.2"), 0.3),
        (_op("subtract", "1.2", "0.1", "0.2"), 0.9),
        (_op("multiply", "0.1", "0.2", "5"), 0.1),
        (_op("divide", "1.2", "2", "3"), 0.2),
        (_op("subtract", _op("add", "10000000000000000", "0.1"), "10000000000000000"), 0.1),
        (
            _op(
                "subtract",
                _op("multiply", _op("divide", "9007199254740992.5", 2), 2),
                "9007199254740992",
            ),
            0.5,
        ),
        (
            {
                "op": "subtract",
                "left": {"op": "add", "left": "10000000000000000", "right": "0.1"},
                "right": "10000000000000000",
            },
            0.1,
        ),
    ],
)
def test_v2_nested_arithmetic_preserves_decimal_values(expression, expected):
    assert _evaluate(expression) == expected


def test_v2_dependent_decimal_text_preserves_threshold_and_rounding_stage():
    raw_expression = _op("add", "1.004999999999999998", "0.000000000000000001")
    spec = {
        "version": V2,
        "fields": [
            _field(
                "label",
                {
                    "op": "case",
                    "branches": [{
                        "when": _comparison("gte", {"field": "raw"}, "1.005"),
                        "then": "at_or_above",
                    }],
                    "else": "below",
                },
                "string",
            ),
            _field("rounded", _round({"field": "raw"})),
            _field("raw", raw_expression, "string"),
        ],
    }
    normalized = transformations.normalize_tabular_transformation_spec(spec)
    order = normalized["deterministic_field_order"]
    assert order.index("raw") < order.index("rounded")
    assert order.index("raw") < order.index("label")
    result = transformations.evaluate_tabular_transformation_row(normalized, {})
    assert result == {"label": "below", "rounded": 1, "raw": "1.004999999999999999"}
    assert list(result) == ["label", "rounded", "raw"]
    assert _evaluate(_round(raw_expression)) == 1


@pytest.mark.parametrize("source_value", ["0.1", "0.100000000000000005"])
def test_v2_numeric_fields_are_projected_only_after_all_dependencies(monkeypatch, source_value):
    validated_values = {}
    projected_values = []
    original_validate = transformations._validate_evaluated_field_value
    original_project = transformations._decimal_to_json_value

    def record_validation(descriptor, value, precise=False):
        validated = original_validate(descriptor, value, precise=precise)
        validated_values[descriptor["name"]] = validated
        return validated

    def record_projection(value, precise=False):
        assert set(validated_values) == {"raw", "rounded", "above"}
        assert isinstance(validated_values["raw"], Decimal)
        projected_values.append(value)
        return original_project(value, precise=precise)

    monkeypatch.setattr(transformations, "_validate_evaluated_field_value", record_validation)
    monkeypatch.setattr(transformations, "_decimal_to_json_value", record_projection)
    spec = {
        "version": V2,
        "fields": [
            _field("rounded", _round({"field": "raw"})),
            _field("above", _comparison("gt", {"field": "raw"}, "0.1"), "boolean"),
            _field("raw", {"source": "value"}),
        ],
    }
    if source_value == "0.1":
        assert transformations.evaluate_tabular_transformation_row(spec, {"value": source_value}) == {
            "rounded": 0.1,
            "above": False,
            "raw": 0.1,
        }
    else:
        with pytest.raises(transformations.TabularTransformationEvaluationError, match="precision loss"):
            transformations.evaluate_tabular_transformation_row(spec, {"value": source_value})
    assert validated_values["raw"] == Decimal(source_value)
    assert validated_values["rounded"] == Decimal("0.10")
    assert validated_values["above"] is (source_value != "0.1")
    assert all(isinstance(value, Decimal) for value in projected_values)


def test_v2_weighted_totals_and_declared_threshold_share_final_values():
    spec = {
        "version": V2,
        "fields": [
            _field("meets_threshold", _comparison("gte", {"field": "total"}, "85.99"), "boolean"),
            _field("total", _round(_op("divide", {"field": "weighted"}, {"field": "weights"}))),
            _field("weighted", _op("add", {"field": "first"}, {"field": "second"})),
            _field("weights", _op("add", {"source": "first_weight"}, {"source": "second_weight"})),
            _field("first", _op("multiply", {"source": "first_score"}, {"source": "first_weight"})),
            _field("second", _op("multiply", {"source": "second_score"}, {"source": "second_weight"})),
        ],
    }
    row = {"first_score": "89.95", "first_weight": "0.6", "second_score": "80.05", "second_weight": "0.4"}
    result = transformations.evaluate_tabular_transformation_row(spec, row)
    assert result == {
        "meets_threshold": True,
        "total": 85.99,
        "weighted": 85.99,
        "weights": 1,
        "first": 53.97,
        "second": 32.02,
    }
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_v2_threshold_can_explicitly_follow_the_rounded_field():
    spec = {
        "version": V2,
        "fields": [
            _field("after_rounding", _comparison("gte", {"field": "rounded"}, "2.68"), "boolean"),
            _field("before_rounding", _comparison("gte", {"source": "amount"}, "2.68"), "boolean"),
            _field("rounded", _round({"source": "amount"})),
        ],
    }
    result = transformations.evaluate_tabular_transformation_row(spec, {"amount": "2.675"})
    assert result == {"after_rounding": True, "before_rounding": False, "rounded": 2.68}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.099999999999999999999", [False, True, True, True, False, False]),
        ("0.1", [True, False, False, True, False, True]),
        ("0.100000000000000000001", [False, True, False, False, True, True]),
    ],
)
def test_v2_exact_threshold_boundaries(value, expected):
    operations = ["eq", "ne", "lt", "lte", "gt", "gte"]
    spec = {
        "version": V2,
        "fields": [
            _field(op, _comparison(op, _op("add", {"source": "value"}, 0), "0.1"), "boolean")
            for op in operations
        ],
    }
    result = transformations.evaluate_tabular_transformation_row(spec, {"value": value})
    assert list(result.values()) == expected


@pytest.mark.parametrize(
    ("value", "scale", "half_up", "half_even"),
    [
        ("2.675", 2, 2.68, 2.68),
        ("2.685", 2, 2.69, 2.68),
        ("-2.675", 2, -2.68, -2.68),
        ("-2.685", 2, -2.69, -2.68),
        ("2.5", 0, 3, 2),
        ("-2.5", 0, -3, -2),
        ("-0.005", 2, -0.01, 0),
        ("0", 12, 0, 0),
        ("0.0000000000015", 12, 0.000000000002, 0.000000000002),
    ],
)
def test_v2_explicit_rounding_ties(value, scale, half_up, half_even):
    assert _evaluate(_round(value, scale, "half_up")) == half_up
    assert _evaluate(_round(value, scale, "half_even")) == half_even


@pytest.mark.parametrize(
    ("operands", "scale", "mode", "expected"),
    [
        ([1, 3], 2, "half_up", 0.33),
        ([2, 3], 2, "half_even", 0.67),
        ([-1, 6], 2, "half_even", -0.17),
        (["2.01", 2], 2, "half_up", 1.01),
        (["2.01", 2], 2, "half_even", 1),
        (["-2.01", 2], 2, "half_up", -1.01),
        (["-2.01", 2], 2, "half_even", -1),
        ([1, 3, 2], 2, "half_up", 0.17),
        ([1, -3, -2], 2, "half_even", 0.17),
        (["0." + "9" * 64, 2], 0, "half_up", 0),
        (["1." + "0" * 62 + "1", 2], 0, "half_even", 1),
    ],
)
def test_v2_rounded_division_is_exact_without_double_rounding(operands, scale, mode, expected):
    assert _evaluate(_round(_op("divide", *operands), scale, mode)) == expected


def test_v2_rounding_stage_is_not_inferred():
    raw = _op("add", "1.004999999999999998", "0.000000000000000001")
    assert _evaluate(raw, field_type="string") == "1.004999999999999999"
    for expression in (
        _op("divide", 1, 3),
        _round(_op("add", _op("divide", 1, 3), 1)),
        _op("add", 1, "1e-128"),
    ):
        with pytest.raises(transformations.TabularTransformationEvaluationError, match="not exact"):
            _evaluate(expression)
    spec = {
        "version": V2,
        "fields": [
            _field("rounded", _round({"field": "raw"})),
            _field("raw", _op("divide", 1, 3), "string"),
        ],
    }
    with pytest.raises(transformations.TabularTransformationEvaluationError, match="not exact"):
        transformations.evaluate_tabular_transformation_row(spec, {})


def test_v2_precision_is_independent_of_ambient_decimal_context():
    expression = _round(_op("add", "123.456", "0.009"), 2, "half_even")
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        before = (context.prec, context.rounding, dict(context.traps), dict(context.flags))
        assert _evaluate(expression) == 123.46
        assert _evaluate(_round(_op("divide", 2, 3))) == 0.67
        assert (context.prec, context.rounding, dict(context.traps), dict(context.flags)) == before


@pytest.mark.parametrize("value", [None, "", 0, "0", False])
def test_v2_null_zero_and_false_remain_distinct(value):
    expression = {"op": "is_null", "value": {"source": "value"}}
    assert _evaluate(expression, {"value": value}, "boolean") is (value is None or value == "")
    coalesce = {"op": "coalesce", "values": [{"source": "value"}, 7]}
    result = _evaluate(coalesce, {"value": value}, "")
    expected = 7 if value is None or value == "" else value
    assert result == expected
    assert type(result) is type(expected)


def test_v2_nullability_and_guarded_zero_denominators_survive_saved_normalization():
    spec = _spec(None, nullable=True)
    normalized = transformations.normalize_tabular_transformation_spec(spec)
    assert transformations.evaluate_tabular_transformation_rows(normalized, [{}, {}]) == [
        {"result": None},
        {"result": None},
    ]
    with pytest.raises(transformations.TabularTransformationEvaluationError, match="Non-nullable"):
        _evaluate({"value": None}, nullable=False)
    for value in (None, "", False):
        with pytest.raises(transformations.TabularTransformationEvaluationError):
            _evaluate(_round({"source": "value"}), {"value": value})
    expression = {
        "op": "case",
        "branches": [{
            "when": _comparison("eq", {"source": "denominator"}, 0),
            "then": None,
        }],
        "else": _op("divide", 1, {"source": "denominator"}),
    }
    assert _evaluate(expression, {"denominator": 0}, nullable=True) is None
    assert _evaluate(expression, {"denominator": 2}, nullable=True) == 0.5


@pytest.mark.parametrize(
    "value",
    [
        None, "", " ", True, False, "not-a-number", "1_000", "NaN", "sNaN", "Infinity", "-Infinity",
        float("nan"), float("inf"), Decimal("NaN"), Decimal("sNaN"), "1e19",
        "1" * 257, "1e-129", "1." + "1" * 64, "1e9999999999", [], {}, object(),
    ],
)
def test_v2_invalid_numeric_inputs_fail_with_evaluation_errors(value):
    with pytest.raises(transformations.TabularTransformationEvaluationError):
        _evaluate(_op("add", {"source": "value"}, 0), {"value": value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 10 ** 19])
def test_v2_invalid_numeric_literals_fail_before_evaluation(value):
    with pytest.raises(transformations.TabularTransformationSpecError):
        transformations.normalize_tabular_transformation_spec(_spec(value))


@pytest.mark.parametrize("denominator", [0, "0", "-0.0", Decimal("-0")])
def test_v2_zero_denominators_are_rejected_even_with_rounding(denominator):
    quotient = _op("divide", 1, {"source": "denominator"})
    for expression in (quotient, _round(quotient)):
        with pytest.raises(transformations.TabularTransformationEvaluationError, match="Division by zero"):
            _evaluate(expression, {"denominator": denominator})


@pytest.mark.parametrize(
    ("expression", "field_type"),
    [
        (_op("add", "0.100000000000000005", 0), "number"),
        (_op("add", "0.100000000000000005", 0), ""),
        ({"source": "value"}, "number"),
        ({"source": "value"}, "integer"),
    ],
)
def test_v2_public_numbers_reject_unrepresentable_values(expression, field_type):
    with pytest.raises(transformations.TabularTransformationEvaluationError, match="JSON"):
        _evaluate(expression, {"value": "9007199254740992"}, field_type)


def test_v2_explicit_rounding_or_text_projection_avoids_precision_loss():
    expression = _op("add", "0.100000000000000005", 0)
    assert _evaluate(expression, field_type="string") == "0.100000000000000005"
    assert _evaluate(_round(expression, 12)) == 0.1
    assert _evaluate("9007199254740992", field_type="string") == "9007199254740992"
    assert _evaluate("9007199254740991", field_type="integer") == 9007199254740991
    assert _evaluate(_round("-0.001"), field_type="string") == "-0.00"
    assert _evaluate(_round(_op("divide", "-0.001", 1)), field_type="string") == "-0.00"


def test_v2_public_collections_are_json_compatible_and_do_not_mutate_sources():
    value = {"numbers": [Decimal("0.1"), 2, True, None], "text": "unchanged"}
    original = deepcopy(value)
    result = _evaluate({"source": "value"}, {"value": value}, "object")
    assert result == {"numbers": [0.1, 2, True, None], "text": "unchanged"}
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert value == original
    assert isinstance(value["numbers"][0], Decimal)
    for invalid in ({"number": float("nan")}, {"number": Decimal("0.100000000000000005")}, {1: "invalid"}):
        with pytest.raises(transformations.TabularTransformationEvaluationError):
            _evaluate({"source": "value"}, {"value": invalid}, "object")


def test_v2_numeric_comparisons_membership_and_allowed_values_preserve_decimal_equality():
    expression = _op("add", "0.1", "0.2")
    assert _evaluate(expression, allowed_values=[None, 0.1, 0.3]) == 0.3
    assert _evaluate(expression, allowed_values=["0.3"]) == 0.3
    assert _evaluate(_comparison("eq", expression, 0.3, ""), field_type="boolean") is True
    assert _evaluate({"op": "in", "value": expression, "values": [0.1, 0.3]}, field_type="boolean") is True
    with pytest.raises(transformations.TabularTransformationEvaluationError, match="outside allowed"):
        _evaluate(expression, allowed_values=[0.1])
    with pytest.raises(transformations.TabularTransformationSpecError, match="allowed numeric"):
        transformations.normalize_tabular_transformation_spec(_spec(expression, allowed_values=[True]))
    with pytest.raises(transformations.TabularTransformationEvaluationError, match="boolean"):
        _evaluate(_comparison("eq", 1, True), field_type="boolean")


@pytest.mark.parametrize("scale", [-1, 13, True, False, "2", 2.0, None])
def test_round_scale_is_a_bounded_integer(scale):
    with pytest.raises(transformations.TabularTransformationSpecError, match="scale"):
        transformations.normalize_tabular_transformation_spec(_spec(_round(1, scale)))


@pytest.mark.parametrize("mode", ["up", "floor", "ceiling", "ROUND_HALF_UP", "", None])
def test_round_requires_an_enumerated_mode(mode):
    with pytest.raises(transformations.TabularTransformationSpecError, match="mode"):
        transformations.normalize_tabular_transformation_spec(_spec(_round(1, mode=mode)))


@pytest.mark.parametrize(
    "expression",
    [
        {"op": "round", "value": 1, "scale": 2},
        {"op": "round", "value": 1, "mode": "half_up"},
        {**_round(1), "precision": 8},
        {"op": "eval", "value": "1 + 1"},
        {"op": "exec", "value": "return 1"},
        {"op": "sqrt", "value": 4},
        {"op": "add", "values": [1, 2], "left": 3, "right": 4},
        {"op": "copy", "source": "known", "path": ["nested"]},
    ],
)
def test_v2_unsupported_or_ambiguous_operations_are_rejected(expression):
    with pytest.raises(transformations.TabularTransformationSpecError):
        transformations.normalize_tabular_transformation_spec(_spec(expression))


def test_v2_round_dependencies_reject_cycles_unknown_fields_and_model_outputs():
    cyclic = {
        "version": V2,
        "fields": [_field("first", _round({"field": "second"})), _field("second", {"field": "first"})],
    }
    with pytest.raises(transformations.TabularTransformationSpecError, match="cycle"):
        transformations.normalize_tabular_transformation_spec(cyclic)
    with pytest.raises(transformations.TabularTransformationSpecError, match="unknown output"):
        transformations.normalize_tabular_transformation_spec(_spec(_round({"field": "missing"})))
    with pytest.raises(transformations.TabularTransformationSpecError, match="unknown source"):
        transformations.normalize_tabular_transformation_spec(
            _spec(_round({"source": "missing"})), source_schema=["known"]
        )
    for mode in ("semantic", "hybrid"):
        spec = {
            "version": V2,
            "fields": [
                _field("derived", _round({"field": "judgment"})),
                {"name": "judgment", "mode": mode, "type": "number"},
            ],
        }
        with pytest.raises(transformations.TabularTransformationSpecError, match="semantic output"):
            transformations.normalize_tabular_transformation_spec(spec)


def test_v2_model_owned_fields_are_not_evaluated_or_changed():
    spec = {
        "version": V2,
        "fields": [
            {"name": "judgment", "mode": "semantic", "type": "object"},
            _field("computed", _round(_op("divide", 2, 3))),
            {"name": "review", "mode": "hybrid", "type": "array"},
        ],
    }
    original = deepcopy(spec)
    normalized = transformations.normalize_tabular_transformation_spec(spec)
    assert transformations.get_tabular_transformation_model_fields(normalized) == ["judgment", "review"]
    assert transformations.get_tabular_transformation_deterministic_fields(normalized) == ["computed"]
    assert transformations.is_tabular_transformation_deterministic_only(normalized) is False
    assert transformations.evaluate_tabular_transformation_row(normalized, {}) == {"computed": 0.67}
    assert spec == original


def test_v2_bounds_include_literals_and_unexecuted_branches():
    deep_expression = 1
    deep_literal = 1
    for _ in range(transformations.TABULAR_TRANSFORMATION_MAX_EXPRESSION_DEPTH + 1):
        deep_expression = _op("add", deep_expression, 0)
        deep_literal = [deep_literal]
    cyclic_literal = []
    cyclic_literal.append(cyclic_literal)
    large_unexecuted = {
        "op": "case",
        "branches": [{"when": False, "then": _op("add", *([0] * 200))} for _ in range(6)],
        "else": 1,
    }
    for expression in (
        deep_expression,
        {"value": deep_literal},
        {"value": cyclic_literal},
        _op("add", *([0] * 201)),
        {"value": "x" * 4097},
        large_unexecuted,
    ):
        with pytest.raises(transformations.TabularTransformationSpecError):
            transformations.normalize_tabular_transformation_spec(_spec(expression))
    with pytest.raises(transformations.TabularTransformationSpecError, match="too many fields"):
        transformations.normalize_tabular_transformation_spec({
            "version": V2,
            "fields": [_field(f"field_{index}", 0) for index in range(201)],
        })


def test_v2_bounds_include_row_projection_and_rounded_division_work():
    cyclic_value = []
    cyclic_value.append(cyclic_value)
    for value in ([[0] * 200] * 200, [0] * 201, cyclic_value):
        with pytest.raises(transformations.TabularTransformationEvaluationError):
            _evaluate({"source": "value"}, {"value": value}, "array")
    with pytest.raises(transformations.TabularTransformationEvaluationError, match="work limit"):
        _evaluate(_round(_op("divide", 1, *(["0." + "9" * 64] * 30))))
    for expression in (
        _op("multiply", "1e-128", "0.1"),
        _op("multiply", "1e18", "1e18", 0),
    ):
        with pytest.raises(transformations.TabularTransformationEvaluationError):
            _evaluate(expression)


def test_v1_remains_the_default_version_and_rounding_is_version_gated():
    assert transformations.TABULAR_TRANSFORMATION_SPEC_VERSION == V1
    assert transformations.TABULAR_TRANSFORMATION_PRECISE_SPEC_VERSION == V2
    for version in (V1, "tabular-transform-v3", ""):
        with pytest.raises(transformations.TabularTransformationSpecError):
            transformations.normalize_tabular_transformation_spec(_spec(_round(1), version=version))
    normalized = transformations.normalize_tabular_transformation_spec(_spec(_round(1)))
    assert normalized["version"] == V2
    assert transformations.normalize_tabular_transformation_spec(json.loads(json.dumps(normalized))) == normalized
    assert transformations.evaluate_tabular_transformation_row(normalized, {}) == {"result": 1}


def test_v1_saved_plans_keep_intermediate_float_behavior():
    expression = _op("subtract", _op("add", "10000000000000000", "0.1"), "10000000000000000")
    spec = _spec(expression, version=V1)
    normalized = transformations.normalize_tabular_transformation_spec(spec)
    saved = json.loads(json.dumps(normalized))
    assert transformations.normalize_tabular_transformation_spec(saved) == normalized
    assert transformations.evaluate_tabular_transformation_row(saved, {}) == {"result": 0}
    assert _evaluate(expression, version=V2) == 0.1
    assert _evaluate(_op("divide", 1, 3), version=V1) == 1 / 3
    assert _evaluate("1000000000000000000", version=V1) == 10 ** 18
    assert _evaluate({"op": "add", "values": [1, 2], "left": 3, "right": 4}, version=V1) == 3


@pytest.mark.parametrize("value", [True, None, float("nan"), "NaN", "sNaN", float("inf")])
def test_v1_invalid_numeric_inputs_raise_the_same_public_error_type(value):
    with pytest.raises(transformations.TabularTransformationEvaluationError):
        _evaluate(_op("add", {"source": "value"}, 0), {"value": value}, version=V1)
