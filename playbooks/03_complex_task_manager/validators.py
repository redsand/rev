"""
Input validators for task execution.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional, List, Type


class ValidationError(Exception):
    """Raised when input validation fails."""

    def __init__(self, field_name: str, value: Any, reason: str):
        self.field_name = field_name
        self.value = value
        self.reason = reason
        super().__init__(f"Validation failed for '{field_name}': {reason}")


class Validator(ABC):
    """Base class for validators."""

    @abstractmethod
    def validate(self, value: Any, field_name: str) -> Any:
        """Validate the value.

        Args:
            value: Value to validate
            field_name: Name of the field being validated

        Returns:
            Validated value (possibly converted)

        Raises:
            ValidationError: If validation fails
        """
        # TODO: Implement in subclasses
        pass


class RangeValidator(Validator):
    """Validates that a numeric value is within a range."""

    def __init__(self, min_val: Optional[float] = None, max_val: Optional[float] = None):
        # TODO: Implement
        pass

    def validate(self, value: Any, field_name: str) -> Any:
        # TODO: Implement
        pass


class TypeValidator(Validator):
    """Validates that a value is of the expected type."""

    def __init__(self, expected_type: Type, allow_none: bool = False):
        # TODO: Implement
        pass

    def validate(self, value: Any, field_name: str) -> Any:
        # TODO: Implement
        pass


class LengthValidator(Validator):
    """Validates string length or collection size."""

    def __init__(self, min_length: int = 0, max_length: Optional[int] = None):
        # TODO: Implement
        pass

    def validate(self, value: Any, field_name: str) -> Any:
        # TODO: Implement
        pass


class RegexValidator(Validator):
    """Validates string against regex pattern."""

    def __init__(self, pattern: str, flags: int = 0):
        # TODO: Implement
        pass

    def validate(self, value: Any, field_name: str) -> Any:
        # TODO: Implement
        pass


class CustomValidator(Validator):
    """Validates using a custom validation function."""

    def __init__(self, validator_func: Callable[[Any], bool], error_message: str = "Validation failed"):
        # TODO: Implement
        pass

    def validate(self, value: Any, field_name: str) -> Any:
        # TODO: Implement
        pass


class ChoiceValidator(Validator):
    """Validates that value is in allowed choices."""

    def __init__(self, choices: List[Any], case_sensitive: bool = True):
        # TODO: Implement
        pass

    def validate(self, value: Any, field_name: str) -> Any:
        # TODO: Implement
        pass