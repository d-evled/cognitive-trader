"""Setup cards: templated text snapshots of a ticker's technical state.

Raw price numbers don't embed well, so each (ticker, day) is rendered as
a short natural-language card (ARCHITECTURE.md §5.2). Similar market states
produce similar text and therefore embed near each other — one retrieval
mechanism (text similarity) serves every collection, and the cards are
human-readable in the UI, so you can *show* the evidence.

Each stored card also carries FORWARD returns (fwd_5d/10d/20d) as metadata,
so retrieving the nearest historical cards yields an empirical base rate:
"in the 10 most similar past setups, median 10-day return was +1.9%."

Everything here is pure: it reads an enriched DataFrame (see
signals/indicators.enrich) and returns text / numbers. No embeddings, no
Chroma — those live in embedder.py.
"""
import pandas as pd

# How many rows back we look to call a moving average "rising" vs "falling".
_SLOPE_LOOKBACK = 5
# Horizons (trading days) for forward-return metadata.
FORWARD_HORIZONS = (5, 10, 20)
_NEEDED = ["sma_fast", "sma_slow", "rsi", "atr", "vol_avg"]


def card_id(ticker: str, date: str) -> str:
    """Stable id for a card, e.g. 'S-AAPL-2026-07-06'. Used as the Chroma
    document id and as the citation token the LLM must reference."""
    return f"S-{ticker}-{date}"


def _renderable(df: pd.DataFrame, i: int) -> bool:
    if i < _SLOPE_LOOKBACK:
        return False
    row = df.iloc[i]
    if row[_NEEDED].isna().any():
        return False
    # need a warmed-up MA `_SLOPE_LOOKBACK` rows back too, to judge slope
    return not df.iloc[i - _SLOPE_LOOKBACK][["sma_fast", "sma_slow"]].isna().any()


def card_text(ticker: str, df: pd.DataFrame, i: int) -> str:
    """Render the card for row `i` of an enriched DataFrame.

    Raises ValueError if indicators haven't warmed up at that row — callers
    backfilling history simply skip early rows.
    """
    if not _renderable(df, i):
        raise ValueError(f"indicators not warmed up at row {i}")

    row = df.iloc[i]
    date = df.index[i].strftime("%Y-%m-%d")
    close = float(row["close"])
    sma_fast, sma_slow = float(row["sma_fast"]), float(row["sma_slow"])
    fast_back = float(df.iloc[i - _SLOPE_LOOKBACK]["sma_fast"])
    slow_back = float(df.iloc[i - _SLOPE_LOOKBACK]["sma_slow"])

    above = "above" if close >= sma_fast else "below"
    fast_slope = "rising" if sma_fast >= fast_back else "falling"
    slow_slope = "rising" if sma_slow >= slow_back else "falling"
    extension = 100 * (close / sma_fast - 1)
    atr_pct = 100 * float(row["atr"]) / close
    vol_mult = float(row["volume"]) / float(row["vol_avg"])

    return (
        f"{ticker} {date}. "
        f"Trend: {above} a {fast_slope} 50d MA, 200d MA {slow_slope}. "
        f"Momentum: RSI-14 at {row['rsi']:.0f}. "
        f"Volatility: ATR {atr_pct:.1f}% of price. "
        f"Volume: {vol_mult:.1f}x 20d average. "
        f"Extension: {extension:+.1f}% above 50d MA."
    )


def build_cards(ticker: str, df: pd.DataFrame):
    """Every storable card for one ticker's enriched history.

    Yields (ids, texts, metadatas) ready for KnowledgeBase.add_setups. Only
    rows that are BOTH renderable (indicators warmed up) AND have complete
    forward returns are included — a card with no known outcome is useless
    as a base-rate sample, so the most recent ~20 days are naturally
    excluded until data arrives.
    """
    ids, texts, metadatas = [], [], []
    for i in range(len(df)):
        if not _renderable(df, i):
            continue
        fr = forward_returns(df, i)
        if fr is None:
            continue
        date = df.index[i].strftime("%Y-%m-%d")
        ids.append(card_id(ticker, date))
        texts.append(card_text(ticker, df, i))
        metadatas.append({"date": date, "ticker": ticker, **fr})
    return ids, texts, metadatas


def forward_returns(df: pd.DataFrame, i: int,
                    horizons=FORWARD_HORIZONS) -> dict | None:
    """Percent close-to-close returns from row i to i+h for each horizon.

    Returns None if the longest horizon runs past the end of the data —
    a card without complete forward returns isn't useful as a base-rate
    sample, so the backfill simply skips it (and revisits as data arrives).
    """
    if i + max(horizons) >= len(df):
        return None
    entry = float(df["close"].iloc[i])
    if entry <= 0:
        return None
    return {
        f"fwd_{h}d": round(100 * (float(df["close"].iloc[i + h]) / entry - 1), 3)
        for h in horizons
    }
