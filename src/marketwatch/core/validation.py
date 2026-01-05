"""Input validation utilities for MarketWatch.

This module provides validation functions for financial data inputs.
All validation functions raise ValidationError on invalid input.
"""

from __future__ import annotations

import math


class ValidationError(ValueError):
    """Raised when input validation fails."""

    pass


def validate_finite(value: float, field_name: str = "value") -> float:
    """
    Validate that a value is finite (not NaN or infinity).

    Args:
        value: The value to validate
        field_name: Name of the field for error messages

    Returns:
        The validated value

    Raises:
        ValidationError: If value is NaN or infinity
    """
    if not math.isfinite(value):
        raise ValidationError(
            f"{field_name} must be finite (not NaN or infinity), got {value}"
        )
    return value


def validate_positive(value: float, field_name: str = "value") -> float:
    """
    Validate that a value is positive (> 0) and finite.

    Args:
        value: The value to validate
        field_name: Name of the field for error messages

    Returns:
        The validated value

    Raises:
        ValidationError: If value is not positive or not finite
    """
    if not math.isfinite(value):
        raise ValidationError(
            f"{field_name} must be finite (not NaN or infinity), got {value}"
        )
    if value <= 0:
        raise ValidationError(f"{field_name} must be positive, got {value}")
    return value


def validate_non_negative(value: float, field_name: str = "value") -> float:
    """
    Validate that a value is non-negative (>= 0) and finite.

    Args:
        value: The value to validate
        field_name: Name of the field for error messages

    Returns:
        The validated value

    Raises:
        ValidationError: If value is negative or not finite
    """
    if not math.isfinite(value):
        raise ValidationError(
            f"{field_name} must be finite (not NaN or infinity), got {value}"
        )
    if value < 0:
        raise ValidationError(f"{field_name} must be non-negative, got {value}")
    return value


def validate_price(value: float, field_name: str = "price") -> float:
    """
    Validate a price value (must be positive and finite).

    Args:
        value: The price to validate
        field_name: Name of the field for error messages

    Returns:
        The validated price

    Raises:
        ValidationError: If price is not positive or not finite
    """
    return validate_positive(value, field_name)


def validate_quantity_for_init(value: float, field_name: str = "quantity") -> float:
    """
    Validate a quantity for init_position (must be positive).

    For initial position setup, quantity must be positive.

    Args:
        value: The quantity to validate
        field_name: Name of the field for error messages

    Returns:
        The validated quantity

    Raises:
        ValidationError: If quantity is not positive or not finite
    """
    return validate_positive(value, field_name)


def validate_quantity_delta(value: float, field_name: str = "quantity") -> float:
    """
    Validate a quantity delta for trades (can be negative for sells).

    For trade_add events, negative values indicate sells.
    The value must be finite but can be positive or negative.

    Args:
        value: The quantity delta to validate
        field_name: Name of the field for error messages

    Returns:
        The validated quantity delta

    Raises:
        ValidationError: If quantity is not finite or is zero
    """
    if not math.isfinite(value):
        raise ValidationError(
            f"{field_name} must be finite (not NaN or infinity), got {value}"
        )
    if value == 0:
        raise ValidationError(f"{field_name} cannot be zero")
    return value


def validate_weight(value: float, field_name: str = "weight") -> float:
    """
    Validate a weight value (must be between 0 and 1 inclusive).

    Args:
        value: The weight to validate
        field_name: Name of the field for error messages

    Returns:
        The validated weight

    Raises:
        ValidationError: If weight is not in [0, 1] or not finite
    """
    if not math.isfinite(value):
        raise ValidationError(
            f"{field_name} must be finite (not NaN or infinity), got {value}"
        )
    if not (0.0 <= value <= 1.0):
        raise ValidationError(f"{field_name} must be between 0 and 1, got {value}")
    return value


def validate_targets(
    buy_target: float | None, sell_target: float | None
) -> None:
    """
    Validate buy/sell target prices.

    If both are provided, sell_target must be greater than buy_target.

    Args:
        buy_target: The buy target price (or None)
        sell_target: The sell target price (or None)

    Raises:
        ValidationError: If targets are invalid or sell <= buy
    """
    if buy_target is not None:
        validate_positive(buy_target, "buy_target")
    if sell_target is not None:
        validate_positive(sell_target, "sell_target")

    if buy_target is not None and sell_target is not None:
        if sell_target <= buy_target:
            raise ValidationError(
                f"sell_target ({sell_target}) must be greater than "
                f"buy_target ({buy_target})"
            )


def validate_rate(value: float, field_name: str = "rate") -> float:
    """
    Validate a rate value (must be between 0 and 1, typically for interest rates).

    Args:
        value: The rate to validate
        field_name: Name of the field for error messages

    Returns:
        The validated rate

    Raises:
        ValidationError: If rate is not in [0, 1] or not finite
    """
    return validate_weight(value, field_name)


def validate_positive_int(value: int, field_name: str = "value") -> int:
    """
    Validate a positive integer value.

    Args:
        value: The integer to validate
        field_name: Name of the field for error messages

    Returns:
        The validated integer

    Raises:
        ValidationError: If value is not positive
    """
    if value <= 0:
        raise ValidationError(f"{field_name} must be positive, got {value}")
    return value
