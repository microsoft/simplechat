# math_plugin.py

from typing import Annotated

from semantic_kernel.core_plugins.math_plugin import MathPlugin as SKMathPlugin
from semantic_kernel.functions.kernel_function_decorator import kernel_function

from semantic_kernel_plugins.plugin_invocation_logger import auto_wrap_plugin_functions


class MathPlugin(SKMathPlugin):
    """Description: MathPlugin provides a set of functions to make Math calculations.

    Usage:
        kernel.add_plugin(MathPlugin(), plugin_name="math")

    Examples:
        {{math.Add}} => Returns the sum of input and amount (provided in the KernelArguments)
        {{math.Subtract}} => Returns the difference of input and amount (provided in the KernelArguments)
    """

    def __init__(self):
        super().__init__()
        auto_wrap_plugin_functions(self, self.__class__.__name__)

    @kernel_function(name="Multiply")
    def multiply(
        self,
        input: Annotated[int | float | str, "The first number to multiply"],
        amount: Annotated[int | float | str, "The second number to multiply"],
    ) -> Annotated[float, "The result"]:
        """Returns the multiplication result of the values provided (supports float and int)."""
        x = self._parse_number(input)
        y = self._parse_number(amount)
        return x * y

    @kernel_function(name="Divide")
    def divide(
        self,
        input: Annotated[int | float | str, "The numerator"],
        amount: Annotated[int | float | str, "The denominator"],
    ) -> Annotated[float, "The result"]:
        """Returns the division result of the values provided (supports float and int)."""
        x = self._parse_number(input)
        y = self._parse_number(amount)
        if y == 0:
            raise ValueError("Cannot divide by zero")
        return x / y

    @kernel_function(name="Power")
    def power(
        self,
        input: Annotated[int | float | str, "The base number"],
        exponent: Annotated[int | float | str, "The exponent"],
    ) -> Annotated[float, "The result"]:
        """Returns the power result of the values provided (supports float and int)."""
        x = self._parse_number(input)
        y = self._parse_number(exponent)
        return x**y

    @kernel_function(name="SquareRoot")
    def square_root(
        self,
        input: Annotated[int | float | str, "The number to calculate the square root of"],
    ) -> Annotated[float, "The result"]:
        """Returns the square root of the value provided (supports float and int)."""
        x = self._parse_number(input)
        if x < 0:
            raise ValueError("Cannot calculate square root of a negative number")
        return x**0.5
    
    @kernel_function(name="Modulus")
    def modulus(
        self,
        input: Annotated[int | float | str, "The dividend"],
        amount: Annotated[int | float | str, "The divisor"],
    ) -> Annotated[float, "The result"]:
        """Returns the modulus of the values provided (supports float and int)."""
        x = self._parse_number(input)
        y = self._parse_number(amount)
        if y == 0:
            raise ValueError("Cannot divide by zero for modulus operation")
        return x % y