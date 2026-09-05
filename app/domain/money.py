"""Money utilities for generic minor-unit monetary representation.

ARIV uses integer minor units (e.g., paise for INR, cents for USD, yen for JPY)
for all authoritative monetary fields. This avoids floating-point precision issues
and aligns with financial ledger standards.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Union, Dict, Optional

# ISO-4217 currency exponent/precision mapping
# 0 decimal places: JPY, KRW, CLP, PYG, UGX, VND, etc.
# 3 decimal places: BHD, KWD, OMR, JOD, TND
# 2 decimal places: INR, USD, EUR, GBP, AUD, CAD, SGD, and default
CURRENCY_PRECISION: Dict[str, int] = {
    "JPY": 0,
    "KRW": 0,
    "CLP": 0,
    "VND": 0,
    "BHD": 3,
    "KWD": 3,
    "OMR": 3,
    "JOD": 3,
    "TND": 3,
    "INR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "AUD": 2,
    "CAD": 2,
    "SGD": 2,
}

DEFAULT_PRECISION = 2


def get_currency_precision(currency: str = "INR") -> int:
    """Return the number of decimal places for a given ISO currency code."""
    if not currency:
        return DEFAULT_PRECISION
    return CURRENCY_PRECISION.get(currency.upper().strip(), DEFAULT_PRECISION)


def to_minor_units(
    amount: Union[Decimal, float, str, int],
    currency: str = "INR"
) -> int:
    """Convert a major-unit monetary amount to integer minor units.

    Validates that the input does not exceed the allowed fractional precision
    for the currency. For example, 100.555 for INR (2 decimals) will raise a ValueError.

    Args:
        amount: The monetary value (e.g. 100.50, "100.50", Decimal("100.50")).
        currency: The ISO currency code (default "INR").

    Returns:
        Integer representing minor units (e.g. 10050 paise).

    Raises:
        ValueError: If amount is invalid or has invalid fractional precision.
    """
    scale = get_currency_precision(currency)
    try:
        dec = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid monetary amount: {amount}") from exc

    # Check for excess fractional precision
    if dec.as_tuple().exponent < -scale:
        # Check if the excess digits are non-zero
        quantized = dec.quantize(Decimal(10) ** -scale, rounding=ROUND_HALF_UP)
        if dec != quantized:
            raise ValueError(
                f"Invalid fractional precision for currency {currency}: "
                f"{amount} has more than {scale} decimal places"
            )

    factor = Decimal(10) ** scale
    return int((dec * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_minor_units(
    amount_minor: int,
    currency: str = "INR"
) -> Decimal:
    """Convert integer minor units back to a Decimal in major units.

    Args:
        amount_minor: Integer amount in minor units (e.g. 10050).
        currency: The ISO currency code.

    Returns:
        Decimal in major units (e.g. Decimal("100.50")).
    """
    if not isinstance(amount_minor, int):
        raise TypeError(f"amount_minor must be an integer, got {type(amount_minor)}")
    scale = get_currency_precision(currency)
    factor = Decimal(10) ** scale
    if scale == 0:
        return Decimal(amount_minor)
    return (Decimal(amount_minor) / factor).quantize(Decimal(10) ** -scale)


def format_money(
    amount_minor: int,
    currency: str = "INR"
) -> str:
    """Format an integer minor-unit amount into a currency-aware display string."""
    dec = from_minor_units(amount_minor, currency)
    scale = get_currency_precision(currency)
    if scale == 0:
        return f"{currency.upper()} {int(dec):,d}"
    return f"{currency.upper()} {dec:,.{scale}f}"


@dataclass(frozen=True)
class Money:
    """Immutable, currency-aware monetary value stored in integer minor units.

    Ensures arithmetic correctness and prevents floating-point inaccuracies.
    """
    amount_minor: int
    currency: str = "INR"

    def __post_init__(self):
        if not isinstance(self.amount_minor, int):
            raise TypeError(f"amount_minor must be an integer, got {type(self.amount_minor)}")
        object.__setattr__(self, "currency", self.currency.upper().strip())

    @property
    def amount_cents(self) -> int:
        """Backward-compatible alias for minor units."""
        return self.amount_minor

    @classmethod
    def from_major(
        cls,
        amount: Union[Decimal, float, str, int],
        currency: str = "INR"
    ) -> "Money":
        """Create Money from major units (validating fractional precision)."""
        minor = to_minor_units(amount, currency)
        return cls(amount_minor=minor, currency=currency)

    @classmethod
    def from_decimal(
        cls,
        amount: Decimal,
        currency: str = "INR"
    ) -> "Money":
        """Create Money from a Decimal major-unit value."""
        return cls.from_major(amount, currency)

    @classmethod
    def from_minor(
        cls,
        amount_minor: int,
        currency: str = "INR"
    ) -> "Money":
        """Create Money directly from integer minor units."""
        return cls(amount_minor=amount_minor, currency=currency)

    @classmethod
    def zero(cls, currency: str = "INR") -> "Money":
        """Return a zero-value Money for the currency."""
        return cls(amount_minor=0, currency=currency)

    def to_decimal(self) -> Decimal:
        """Return the major-unit amount as a Decimal."""
        return from_minor_units(self.amount_minor, self.currency)

    def __str__(self) -> str:
        return format_money(self.amount_minor, self.currency)

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")
        return Money(amount_minor=self.amount_minor + other.amount_minor, currency=self.currency)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")
        return Money(amount_minor=self.amount_minor - other.amount_minor, currency=self.currency)

    def __lt__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")
        return self.amount_minor < other.amount_minor

    def __le__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")
        return self.amount_minor <= other.amount_minor

    def __gt__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")
        return self.amount_minor > other.amount_minor

    def __ge__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")
        return self.amount_minor >= other.amount_minor

    def is_zero(self) -> bool:
        return self.amount_minor == 0

    def is_positive(self) -> bool:
        return self.amount_minor > 0

    def is_negative(self) -> bool:
        return self.amount_minor < 0
