"""Hard-coded risk gates. These run BEFORE the LLM ever sees a candidate,
and their limits can never be exceeded by anything downstream
(ARCHITECTURE.md §6: risk lives in code, not prompts).

Gates do two jobs:
  1. Reject candidates that would violate portfolio limits.
  2. Compute the MAXIMUM allowed size for survivors — later, the LLM may
     size below this cap, never above it.
"""
from dataclasses import dataclass, field

from src.signals.rules import Candidate


@dataclass
class PortfolioState:
    """The little slice of portfolio reality the gates need."""
    equity: float
    open_tickers: list[str] = field(default_factory=list)
    open_sectors: list[str] = field(default_factory=list)  # one entry per open position


@dataclass
class GateResult:
    candidate: Candidate
    passed: bool
    max_size_pct: float = 0.0   # cap as % of equity; LLM sizes at or below this
    reject_reason: str = ""


def _risk_capped_size(c: Candidate, risk_cfg: dict) -> float:
    """Position size cap implied by the 2%-risk rule.

    If the stop is hit, we lose (entry - stop)/entry of the position.
    Keep that loss under max_risk_per_trade_pct of equity:
        size_pct <= max_risk / risk_fraction
    A wide stop therefore forces a small position — volatility-aware
    sizing for free.
    """
    risk_frac = (c.entry_price - c.stop_price) / c.entry_price
    if risk_frac <= 0:  # malformed bracket; treat as unsizeable
        return 0.0
    return risk_cfg["max_risk_per_trade_pct"] / risk_frac


def apply_gates(candidates: list[Candidate], state: PortfolioState,
                cfg: dict, sector_lookup) -> list[GateResult]:
    """Check every candidate against the portfolio. Order matters: earlier
    candidates in the list claim slots first (callers can pre-sort by
    preference later; v1 keeps scan order).
    """
    risk_cfg = cfg["risk"]
    results: list[GateResult] = []
    # Track slots we hand out within this batch too, not just existing positions.
    open_count = len(state.open_tickers)
    tickers_held = list(state.open_tickers)
    sectors_held = list(state.open_sectors)

    for c in candidates:
        sector = sector_lookup(c.ticker)

        if open_count >= risk_cfg["max_open_positions"]:
            results.append(GateResult(c, False, reject_reason="max_open_positions reached"))
            continue
        if tickers_held.count(c.ticker) >= risk_cfg["max_per_ticker"]:
            results.append(GateResult(c, False, reject_reason=f"already holding {c.ticker}"))
            continue
        if sectors_held.count(sector) >= risk_cfg["max_per_sector"]:
            results.append(GateResult(c, False, reject_reason=f"sector limit reached ({sector})"))
            continue

        size_cap = min(risk_cfg["max_position_pct"], _risk_capped_size(c, risk_cfg))
        if size_cap <= 0:
            results.append(GateResult(c, False, reject_reason="unsizeable (bad bracket)"))
            continue

        results.append(GateResult(c, True, max_size_pct=round(size_cap, 2)))
        open_count += 1
        tickers_held.append(c.ticker)
        sectors_held.append(sector)

    return results
