"""Tests for the validation module."""

from __future__ import annotations

import math

import pytest

from marketwatch.core.validation import (
    ValidationError,
    validate_finite,
    validate_positive,
    validate_non_negative,
    validate_price,
    validate_quantity_for_init,
    validate_quantity_delta,
    validate_weight,
    validate_targets,
    validate_rate,
    validate_positive_int,
)


class TestValidateFinite:
    def test_accepts_normal_float(self) -> None:
        assert validate_finite(123.45) == 123.45

    def test_accepts_zero(self) -> None:
        assert validate_finite(0.0) == 0.0

    def test_accepts_negative(self) -> None:
        assert validate_finite(-123.45) == -123.45

    def test_rejects_nan(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_finite(float("nan"), "test_field")
        assert "test_field must be finite" in str(exc_info.value)
        assert "NaN" in str(exc_info.value)

    def test_rejects_positive_infinity(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_finite(float("inf"), "test_field")
        assert "test_field must be finite" in str(exc_info.value)

    def test_rejects_negative_infinity(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_finite(float("-inf"), "test_field")
        assert "test_field must be finite" in str(exc_info.value)


class TestValidatePositive:
    def test_accepts_positive(self) -> None:
        assert validate_positive(123.45) == 123.45

    def test_accepts_small_positive(self) -> None:
        assert validate_positive(0.0001) == 0.0001

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_positive(0.0, "test_field")
        assert "test_field must be positive" in str(exc_info.value)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_positive(-1.0, "test_field")
        assert "test_field must be positive" in str(exc_info.value)

    def test_rejects_nan(self) -> None:
        with pytest.raises(ValidationError):
            validate_positive(float("nan"))


class TestValidateNonNegative:
    def test_accepts_positive(self) -> None:
        assert validate_non_negative(123.45) == 123.45

    def test_accepts_zero(self) -> None:
        assert validate_non_negative(0.0) == 0.0

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_non_negative(-1.0, "test_field")
        assert "test_field must be non-negative" in str(exc_info.value)

    def test_rejects_nan(self) -> None:
        with pytest.raises(ValidationError):
            validate_non_negative(float("nan"))


class TestValidatePrice:
    def test_accepts_positive_price(self) -> None:
        assert validate_price(150.50) == 150.50

    def test_rejects_zero_price(self) -> None:
        with pytest.raises(ValidationError):
            validate_price(0.0)

    def test_rejects_negative_price(self) -> None:
        with pytest.raises(ValidationError):
            validate_price(-10.0)

    def test_rejects_nan_price(self) -> None:
        with pytest.raises(ValidationError):
            validate_price(float("nan"))


class TestValidateQuantityForInit:
    def test_accepts_positive_quantity(self) -> None:
        assert validate_quantity_for_init(100.0) == 100.0

    def test_accepts_fractional_shares(self) -> None:
        assert validate_quantity_for_init(0.5) == 0.5

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValidationError):
            validate_quantity_for_init(0.0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            validate_quantity_for_init(-10.0)


class TestValidateQuantityDelta:
    def test_accepts_positive_for_buy(self) -> None:
        assert validate_quantity_delta(100.0) == 100.0

    def test_accepts_negative_for_sell(self) -> None:
        assert validate_quantity_delta(-50.0) == -50.0

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_quantity_delta(0.0, "units")
        assert "units cannot be zero" in str(exc_info.value)

    def test_rejects_nan(self) -> None:
        with pytest.raises(ValidationError):
            validate_quantity_delta(float("nan"))

    def test_rejects_infinity(self) -> None:
        with pytest.raises(ValidationError):
            validate_quantity_delta(float("inf"))


class TestValidateWeight:
    def test_accepts_valid_weight(self) -> None:
        assert validate_weight(0.5) == 0.5

    def test_accepts_zero(self) -> None:
        assert validate_weight(0.0) == 0.0

    def test_accepts_one(self) -> None:
        assert validate_weight(1.0) == 1.0

    def test_rejects_greater_than_one(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_weight(1.5, "max_weight")
        assert "max_weight must be between 0 and 1" in str(exc_info.value)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            validate_weight(-0.1)

    def test_rejects_nan(self) -> None:
        with pytest.raises(ValidationError):
            validate_weight(float("nan"))


class TestValidateTargets:
    def test_accepts_valid_targets(self) -> None:
        # Should not raise
        validate_targets(buy_target=100.0, sell_target=150.0)

    def test_accepts_buy_only(self) -> None:
        validate_targets(buy_target=100.0, sell_target=None)

    def test_accepts_sell_only(self) -> None:
        validate_targets(buy_target=None, sell_target=150.0)

    def test_accepts_neither(self) -> None:
        validate_targets(buy_target=None, sell_target=None)

    def test_rejects_sell_less_than_buy(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_targets(buy_target=150.0, sell_target=100.0)
        assert "sell_target (100.0) must be greater than buy_target (150.0)" in str(
            exc_info.value
        )

    def test_rejects_sell_equal_to_buy(self) -> None:
        with pytest.raises(ValidationError):
            validate_targets(buy_target=100.0, sell_target=100.0)

    def test_rejects_negative_buy_target(self) -> None:
        with pytest.raises(ValidationError):
            validate_targets(buy_target=-10.0, sell_target=100.0)

    def test_rejects_zero_sell_target(self) -> None:
        with pytest.raises(ValidationError):
            validate_targets(buy_target=100.0, sell_target=0.0)


class TestValidateRate:
    def test_accepts_valid_rate(self) -> None:
        assert validate_rate(0.05, "fd_rate") == 0.05

    def test_rejects_negative_rate(self) -> None:
        with pytest.raises(ValidationError):
            validate_rate(-0.01)

    def test_rejects_rate_over_one(self) -> None:
        with pytest.raises(ValidationError):
            validate_rate(1.5)


class TestValidatePositiveInt:
    def test_accepts_positive(self) -> None:
        assert validate_positive_int(10, "days") == 10

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValidationError):
            validate_positive_int(0, "days")

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            validate_positive_int(-5, "days")
