"""The rules engine: deterministic candidate-trade generators.

Design contract (ARCHITECTURE.md §6): each rule is a pure function
    (ticker, enriched_df, cfg) -> Candidate | None
that looks only at the LAST row of an indicator-enriched DataFrame and
decides whether its pattern fired today. Rules are wide-net generators
on purpose — the judgment layer (LLM vetting, Week 4) is what narrows.

Rules never size positions and never manage risk; that belongs to
gates.py and the bracket order.
"""
import json
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Candidate:
    ticker: str
    date: str
    rule_name: str
    direction: str            # v1 is long-only
    entry_price: float        # last close; actual fill is next open
    stop_price: float         # ATR-based, set at signal time
    target_price: float
    context: dict = field(default_factory=dict)  # indicator snapshot

    def context_json(self) -> str:
        return json.dumps(self.context, default=float)


def _has_history(df: pd.DataFrame) -> bool:
    """A rule can only fire once every indicator has warmed up."""
    if len(df) < 2:
        return False
    last = df.iloc[-1]
    needed = ["sma_fast", "sma_slow", "rsi", "atr", "prior_high", "vol_avg"]
    return not last[needed].isna().any()


def _bracket(last: pd.Series, risk_cfg: dict) -> tuple[float, float]:
    """Stop and target from ATR multiples (see config: risk.*_atr_mult)."""
    entry = float(last["close"])
    stop = entry - risk_cfg["stop_atr_mult"] * float(last["atr"])
    target = entry + risk_cfg["target_atr_mult"] * float(last["atr"])
    return round(stop, 2), round(target, 2)


def _make(ticker: str, df: pd.DataFrame, rule_name: str,
          risk_cfg: dict, extra_context: dict) -> Candidate:
    last = df.iloc[-1]
    stop, target = _bracket(last, risk_cfg)
    context = {
        "close": round(float(last["close"]), 2),
        "sma_fast": round(float(last["sma_fast"]), 2),
        "sma_slow": round(float(last["sma_slow"]), 2),
        "rsi": round(float(last["rsi"]), 1),
        "atr": round(float(last["atr"]), 2),
        "atr_pct": round(100 * float(last["atr"]) / float(last["close"]), 2),
        **extra_context,
    }
    return Candidate(
        ticker=ticker,
        date=df.index[-1].strftime("%Y-%m-%d"),
        rule_name=rule_name,
        direction="long",
        entry_price=round(float(last["close"]), 2),
        stop_price=stop,
        target_price=target,
        context=context,
    )


def trend_pullback(ticker: str, df: pd.DataFrame, cfg: dict) -> Candidate | None:
    """Buy-the-dip in an uptrend.

    Fires when: close is above a RISING 50d MA, RSI dipped below the
    threshold (default 40) sometime in the last few days, and RSI turned
    up today (higher than yesterday). The idea: strong stock, short-term
    shakeout, first sign of resuming.
    """
    if not _has_history(df):
        return None
    p = cfg["rules"]["trend_pullback"]
    last, prev = df.iloc[-1], df.iloc[-2]
    lookback = df["rsi"].iloc[-p["dip_lookback"]:]

    uptrend = last["close"] > last["sma_fast"] and last["sma_fast"] > df["sma_fast"].iloc[-6]
    dipped = lookback.min() < p["rsi_dip_below"]
    turning_up = last["rsi"] > prev["rsi"]

    if uptrend and dipped and turning_up:
        return _make(ticker, df, "trend_pullback", cfg["risk"],
                     {"rsi_recent_low": round(float(lookback.min()), 1)})
    return None


def breakout(ticker: str, df: pd.DataFrame, cfg: dict) -> Candidate | None:
    """New-high breakout on conviction volume.

    Fires when: today's close exceeds the prior 20-day high (excluding
    today) AND volume is at least 1.5x its prior 20-day average. Volume
    is the filter that separates real breakouts from drift.
    """
    if not _has_history(df):
        return None
    p = cfg["rules"]["breakout"]
    last = df.iloc[-1]

    new_high = last["close"] > last["prior_high"]
    conviction = last["volume"] >= p["volume_mult"] * last["vol_avg"]

    if new_high and conviction:
        return _make(ticker, df, "breakout", cfg["risk"],
                     {"prior_high": round(float(last["prior_high"]), 2),
                      "volume_ratio": round(float(last["volume"] / last["vol_avg"]), 2)})
    return None


def oversold_reversion(ticker: str, df: pd.DataFrame, cfg: dict) -> Candidate | None:
    """Mean reversion, but only in stocks whose long-term trend is intact.

    Fires when: RSI is below 30 (washed out) while price still holds above
    the 200d MA. The 200d filter is what keeps this from catching falling
    knives — we only buy panic in stocks that are structurally fine.
    """
    if not _has_history(df):
        return None
    p = cfg["rules"]["oversold_reversion"]
    last = df.iloc[-1]

    washed_out = last["rsi"] < p["rsi_below"]
    trend_intact = last["close"] > last["sma_slow"]

    if washed_out and trend_intact:
        return _make(ticker, df, "oversold_reversion", cfg["risk"],
                     {"pct_above_sma_slow":
                      round(100 * (float(last["close"]) / float(last["sma_slow"]) - 1), 2)})
    return None


ALL_RULES = [trend_pullback, breakout, oversold_reversion]


def scan(ticker: str, df: pd.DataFrame, cfg: dict) -> list[Candidate]:
    """Run every rule against one ticker's enriched history."""
    out = []
    for rule in ALL_RULES:
        c = rule(ticker, df, cfg)
        if c is not None:
            out.append(c)
    return out
