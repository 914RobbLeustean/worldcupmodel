"""Odds parsing at the boundary: decimal-only internals (CLAUDE.md invariant)."""

import pytest

from wc26.markets.odds import OddsError, parse_odds


def test_decimal_passthrough() -> None:
    assert parse_odds("1.91") == pytest.approx(1.91)
    assert parse_odds("2,05") == pytest.approx(2.05)  # comma decimal separator
    assert parse_odds(2.5) == pytest.approx(2.5)


def test_american_negative() -> None:
    # -110: stake 110 to win 100 -> decimal 1 + 100/110
    assert parse_odds("-110") == pytest.approx(1.0 + 100.0 / 110.0)
    assert parse_odds("-250") == pytest.approx(1.4)


def test_american_positive() -> None:
    # +120: stake 100 to win 120 -> decimal 2.20
    assert parse_odds("+120") == pytest.approx(2.2)
    assert parse_odds("+100") == pytest.approx(2.0)


def test_unsigned_integer_is_decimal_not_american() -> None:
    assert parse_odds("110") == pytest.approx(110.0)


def test_rejects() -> None:
    with pytest.raises(OddsError):
        parse_odds("")  # empty
    with pytest.raises(OddsError):
        parse_odds("1.0")  # decimal must be > 1
    with pytest.raises(OddsError):
        parse_odds("0.95")
    with pytest.raises(OddsError):
        parse_odds("-50")  # American magnitude < 100
    with pytest.raises(OddsError):
        parse_odds("evens")
