"""De-vig and edge math for two-way markets.

Definitions (D022):
- fair probability: multiplicative de-vig of the two quoted sides via
  penaltyblog (D005) — never compare model probability to raw implied.
- edge (per side) = model_p - fair_p, in probability points. This is what
  settings.edge_threshold gates on.
- ev (per side)   = model_p * decimal_odds - 1: expected profit per unit
  staked at the odds actually offered (vig included), shown for context.

The recommended side of a quote is the one with the larger edge; stakes are
flat units from settings (no Kelly — CLAUDE.md invariant).
"""

from dataclasses import dataclass

from penaltyblog.implied import calculate_implied

from wc26.markets.lines import TwoWayLine


def devig_two_way(over_odds: float, under_odds: float) -> tuple[float, float]:
    """(fair_p_over, fair_p_under) by multiplicative de-vig (D005)."""
    result = calculate_implied([over_odds, under_odds], method="multiplicative")
    p_over, p_under = (float(p) for p in result.probabilities)
    return p_over, p_under


@dataclass(frozen=True)
class Edge:
    quote: TwoWayLine
    model_p_over: float
    fair_p_over: float
    side: str  # recommended side: the one with the larger edge
    model_p: float  # model probability of the recommended side
    fair_p: float
    odds: float  # quoted decimal odds of the recommended side
    edge: float  # model_p - fair_p
    ev: float  # model_p * odds - 1

    @property
    def market_label(self) -> str:
        return f"{self.quote.team_id} {self.side[0].upper()}{self.quote.line}"


def evaluate(quote: TwoWayLine, model_p_over: float) -> Edge:
    """Score one two-way quote against the model's P(over)."""
    if not 0.0 < model_p_over < 1.0:
        raise ValueError(f"model_p_over must be in (0, 1), got {model_p_over}")
    fair_over, fair_under = devig_two_way(quote.over_odds, quote.under_odds)
    edge_over = model_p_over - fair_over
    edge_under = (1.0 - model_p_over) - fair_under
    if edge_over >= edge_under:
        side, model_p, fair_p, odds, edge = (
            "over",
            model_p_over,
            fair_over,
            quote.over_odds,
            edge_over,
        )
    else:
        side, model_p, fair_p, odds, edge = (
            "under",
            1.0 - model_p_over,
            fair_under,
            quote.under_odds,
            edge_under,
        )
    return Edge(
        quote=quote,
        model_p_over=model_p_over,
        fair_p_over=fair_over,
        side=side,
        model_p=model_p,
        fair_p=fair_p,
        odds=odds,
        edge=edge,
        ev=model_p * odds - 1.0,
    )


def rank(edges: list[Edge]) -> list[Edge]:
    """Sorted by edge, best first (ties: earlier kickoff first)."""
    return sorted(edges, key=lambda e: (-e.edge, e.quote.match_date))
