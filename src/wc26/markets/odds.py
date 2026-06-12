"""Odds parsing at the boundary (CLAUDE.md invariant: decimal-only internals).

Accepted input formats, decided by the string itself:
- explicit sign  -> American ("-110", "+120"); magnitude must be >= 100
- unsigned       -> decimal ("1.91", "2.5"); must be > 1.0

An unsigned integer like "110" is therefore decimal odds of 110.0, never
American — American quotes always carry their sign at every book.
"""


class OddsError(ValueError):
    pass


def parse_odds(text: str | float) -> float:
    """Parse a book quote into decimal odds.

    Floats pass through as decimal (so programmatic callers can skip the
    string round-trip); strings follow the sign rule above.
    """
    if isinstance(text, float | int):
        return _check_decimal(float(text), str(text))
    raw = str(text).strip().replace(",", ".")
    if not raw:
        raise OddsError("empty odds field")
    if raw[0] in "+-":
        return american_to_decimal(raw)
    try:
        value = float(raw)
    except ValueError as exc:
        raise OddsError(f"unparseable odds {text!r}") from exc
    return _check_decimal(value, raw)


def american_to_decimal(raw: str) -> float:
    try:
        am = float(raw)
    except ValueError as exc:
        raise OddsError(f"unparseable American odds {raw!r}") from exc
    if abs(am) < 100:
        raise OddsError(
            f"American odds must have magnitude >= 100, got {raw!r} "
            f"(for decimal odds, drop the sign)"
        )
    if am > 0:
        return 1.0 + am / 100.0
    return 1.0 + 100.0 / -am


def _check_decimal(value: float, raw: str) -> float:
    if value <= 1.0:
        raise OddsError(f"decimal odds must be > 1.0, got {raw!r}")
    return value
