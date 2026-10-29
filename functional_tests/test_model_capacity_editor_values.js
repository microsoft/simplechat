// test_model_capacity_editor_values.js
/**
 * Model capacity editor input validation.
 * Version: 0.261.035
 * Implemented in: 0.261.035
 *
 * Run with node --test. Uses the real shared browser parser without a DOM or
 * external dependencies; browser workflows are covered in ui_tests.
 */

import assert from "node:assert/strict";
import test from "node:test";
import {
    ModelBudgetValidationError,
    normalizeTokenCapacity
} from "../application/single_app/static/js/model_budget_editor.js";

test("blank capacity inherits and valid counts stay exact", () => {
    for (const value of [null, undefined, "", " \t "]) {
        const normalized = normalizeTokenCapacity(value);
        assert.equal(normalized, null);
    }
    for (const [value, expected] of [
        [1, 1],
        [" 00042 ", 42],
        [9007199254740991, 9007199254740991],
        ["9007199254740991", 9007199254740991]
    ]) {
        const normalized = normalizeTokenCapacity(value);
        assert.equal(normalized, expected);
    }
});

test("non-integers, booleans, malformed strings and unsafe counts are rejected", () => {
    for (const value of [
        true, false, 0, -1, 1.5, NaN, Infinity, -Infinity, {}, [], [1],
        "0", "-1", "+1", "1.0", "1e3", "1E3", "0x10", "1,000", "1 000",
        "NaN", "Infinity", "true", "\uff11\uff12", 9007199254740992, "9007199254740992"
    ]) {
        assert.throws(() => normalizeTokenCapacity(value), ModelBudgetValidationError);
    }
});
