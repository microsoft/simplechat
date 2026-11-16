# math_plugin.py

from decimal import (
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    ROUND_HALF_EVEN,
    Subnormal,
    Underflow,
    localcontext,
)
import math
import re
from typing import Annotated

from semantic_kernel.core_plugins.math_plugin import MathPlugin as SKMathPlugin
from semantic_kernel.functions.kernel_function_decorator import kernel_function

from semantic_kernel_plugins.plugin_invocation_logger import auto_wrap_plugin_functions


MATH_PRECISION = 64
MATH_MAX_INPUT_LENGTH = 1024
MATH_MAX_EXPONENT = 10000
MATH_MAX_POWER_EXPONENT = 10000
_DECIMAL_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_MATH_CONTEXT = Context(
    prec=MATH_PRECISION,
    rounding=ROUND_HALF_EVEN,
    Emin=-MATH_MAX_EXPONENT,
    Emax=MATH_MAX_EXPONENT,
    traps=[InvalidOperation, DivisionByZero, Overflow, Underflow, Subnormal],
)
_BINARY_OPERATIONS = {
    "Add": "add",
    "Subtract": "subtract",
    "Multiply": "multiply",
    "Divide": "divide",
    "Power": "power",
}
_RESULT_DESCRIPTION = (
    "Finite decimal or scientific-notation text. Inexact results are explicitly marked "
    f"approximate, rounded half-even to {MATH_PRECISION} significant digits. "
    f"Inputs support {MATH_PRECISION} significant digits and decimal exponents "
    f"from {-MATH_MAX_EXPONENT} to {MATH_MAX_EXPONENT}; use strings to preserve digits."
)


class MathPlugin(SKMathPlugin):
    """Bounded real-number decimal calculations with JSON-safe textual results."""

    def __init__(self):
        super().__init__()
        auto_wrap_plugin_functions(self, self.__class__.__name__)

    def _parse_number(self, val: int | float | str) -> Decimal:
        if isinstance(val, bool) or not isinstance(val, (int, float, str)):
            raise ValueError("Math inputs must be finite decimal numbers.")
        if isinstance(val, float) and not math.isfinite(val):
            raise ValueError("Math inputs must be finite decimal numbers.")
        if isinstance(val, int) and val.bit_length() > MATH_MAX_INPUT_LENGTH * 4:
            raise ValueError("Math input exceeds the supported length.")
        text = str(val).strip()
        if len(text) > MATH_MAX_INPUT_LENGTH:
            raise ValueError("Math input exceeds the supported length.")
        if not _DECIMAL_PATTERN.fullmatch(text):
            raise ValueError("Math inputs must be finite decimal numbers without separators.")
        try:
            with localcontext(_MATH_CONTEXT):
                number = Decimal(text)
        except DecimalException as exc:
            raise ValueError("Math input exceeds the supported numeric range.") from exc
        digits = number.as_tuple().digits
        significant_digits = len(digits)
        while significant_digits > 1 and digits[significant_digits - 1] == 0:
            significant_digits -= 1
        if significant_digits > MATH_PRECISION:
            raise ValueError(f"Math inputs support at most {MATH_PRECISION} significant digits.")
        if (
            not -MATH_MAX_EXPONENT <= number.as_tuple().exponent <= MATH_MAX_EXPONENT
            or not -MATH_MAX_EXPONENT <= number.adjusted() <= MATH_MAX_EXPONENT
        ):
            raise ValueError("Math input exceeds the supported numeric range.")
        return number

    def _calculate(self, operation: str, input: int | float | str, amount: int | float | str = 0) -> str:
        x = self._parse_number(input)
        y = self._parse_number(amount)
        if operation in ("Divide", "Modulus") and y.is_zero():
            raise ValueError("Cannot divide by zero.")
        if operation == "SquareRoot" and x < 0:
            raise ValueError("Cannot calculate a real square root of a negative number.")
        if operation == "Power":
            if y.copy_abs() > MATH_MAX_POWER_EXPONENT:
                raise ValueError("Power exponent exceeds the supported calculation limit.")
            if x < 0 and y != y.to_integral_value():
                raise ValueError("A negative base requires an integer exponent for real-number calculations.")
            if x.is_zero() and y < 0:
                raise ValueError("Cannot raise zero to a negative exponent.")
        try:
            with localcontext(_MATH_CONTEXT) as context:
                if operation == "Power" and x.is_zero() and y.is_zero():
                    # Retain the previous calculator's programming convention for zero to zero.
                    result = Decimal(1)
                elif operation == "SquareRoot":
                    result = context.sqrt(x)
                elif operation == "Modulus":
                    # Decimal remainder truncates toward zero; preserve Python's divisor-sign modulus.
                    with localcontext(context) as remainder_context:
                        remainder_context.prec = max(MATH_PRECISION, x.adjusted() - y.adjusted() + 2)
                        result = remainder_context.remainder(x, y)
                    if not result.is_zero() and result.is_signed() != y.is_signed():
                        result = context.add(result, y)
                    else:
                        result = context.plus(result)
                else:
                    result = getattr(context, _BINARY_OPERATIONS[operation])(x, y)
                if not result.is_finite():
                    raise ValueError("Calculation did not produce a finite real-number result.")
                approximate = context.flags[Inexact]
                normalized = result.normalize(context)
                if normalized.is_zero():
                    text = "0"
                elif -6 <= normalized.adjusted() <= 20:
                    text = format(normalized, "f")
                else:
                    text = str(normalized)
                if approximate:
                    return f"{text} (approximate; rounded half-even to {MATH_PRECISION} significant digits)"
                return text
        except DecimalException as exc:
            raise ValueError(
                "Calculation exceeds the supported numeric range or real-number domain. "
                "This is a calculator limitation, not a result of mathematical infinity."
            ) from exc

    @kernel_function(name="Add", description=f"Add two real numbers using bounded decimal arithmetic. {_RESULT_DESCRIPTION}")
    def add(
        self,
        input: Annotated[int | float | str, "First number; use decimal text to preserve digits"],
        amount: Annotated[int | float | str, "Second number; use decimal text to preserve digits"],
    ) -> Annotated[str, _RESULT_DESCRIPTION]:
        return self._calculate("Add", input, amount)

    @kernel_function(name="Subtract", description=f"Subtract two real numbers using bounded decimal arithmetic. {_RESULT_DESCRIPTION}")
    def subtract(
        self,
        input: Annotated[int | float | str, "Number to subtract from; decimal text preserves digits"],
        amount: Annotated[int | float | str, "Number to subtract; decimal text preserves digits"],
    ) -> Annotated[str, _RESULT_DESCRIPTION]:
        return self._calculate("Subtract", input, amount)

    @kernel_function(name="Multiply", description=f"Multiply two real numbers using bounded decimal arithmetic. {_RESULT_DESCRIPTION}")
    def multiply(
        self,
        input: Annotated[int | float | str, "The first number to multiply"],
        amount: Annotated[int | float | str, "The second number to multiply"],
    ) -> Annotated[str, _RESULT_DESCRIPTION]:
        return self._calculate("Multiply", input, amount)

    @kernel_function(name="Divide", description=f"Divide two real numbers using bounded decimal arithmetic. {_RESULT_DESCRIPTION}")
    def divide(
        self,
        input: Annotated[int | float | str, "The numerator"],
        amount: Annotated[int | float | str, "The denominator"],
    ) -> Annotated[str, _RESULT_DESCRIPTION]:
        return self._calculate("Divide", input, amount)

    @kernel_function(name="Power", description=f"Raise a real base to a bounded exponent using decimal arithmetic. {_RESULT_DESCRIPTION}")
    def power(
        self,
        input: Annotated[int | float | str, "The base number"],
        exponent: Annotated[
            int | float | str,
            "The exponent, from -10000 to 10000; negative bases require an integer exponent",
        ],
    ) -> Annotated[str, _RESULT_DESCRIPTION]:
        return self._calculate("Power", input, exponent)

    @kernel_function(name="SquareRoot", description=f"Calculate the real square root of a nonnegative number. {_RESULT_DESCRIPTION}")
    def square_root(
        self,
        input: Annotated[int | float | str, "The number to calculate the square root of"],
    ) -> Annotated[str, _RESULT_DESCRIPTION]:
        return self._calculate("SquareRoot", input)

    @kernel_function(name="Modulus", description=f"Calculate the remainder with the divisor's sign using decimal arithmetic. {_RESULT_DESCRIPTION}")
    def modulus(
        self,
        input: Annotated[int | float | str, "The dividend"],
        amount: Annotated[int | float | str, "The divisor"],
    ) -> Annotated[str, _RESULT_DESCRIPTION]:
        return self._calculate("Modulus", input, amount)