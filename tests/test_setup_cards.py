"""Tests for setup-card rendering and forward-return computation.

Pure logic over an enriched DataFrame — no Chroma, no embeddings here.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.setup_cards import build_cards, card_id, card_text, forward_returns
from src.signals.indicators import enrich

# indicator params matching config.yaml
IND = {"sma_fast": 50, "sma_slow": 200, "rsi_window": 14,
       "atr_window": 14, "breakout_window": 20, "volume_window": 20}


def make_enriched(closes, volumes=None):
    import pandas as pd
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    if volumes is None:
        volumes = np.full(n, 1_000_000.0)
    idx = pd.bdate_range(end="2026-07-06", periods=n)
    df = pd.DataFrame({"open": closes, "high": closes * 1.01,
                       "low": closes * 0.99, "close": closes,
                       "volume": np.asarray(volumes, dtype=float)}, index=idx)
    return enrich(df, IND)


@pytest.fixture
def uptrend():
    # 260 bars grinding up ~0.4%/day: above a rising 50d MA, 200d MA rising
    return make_enriched(100 * np.cumprod(np.full(260, 1.004)))


class TestCardId:
    def test_stable_and_unique_per_ticker_date(self):
        assert card_id("AAPL", "2026-07-06") == "S-AAPL-2026-07-06"


class TestCardText:
    def test_starts_with_ticker_and_date(self, uptrend):
        text = card_text("AAPL", uptrend, len(uptrend) - 1)
        assert text.startswith("AAPL 2026-07-06.")

    def test_uptrend_reads_as_above_rising_ma(self, uptrend):
        text = card_text("AAPL", uptrend, len(uptrend) - 1)
        assert "above" in text and "rising 50d MA" in text
        assert "200d MA rising" in text

    def test_reports_the_indicator_values(self, uptrend):
        text = card_text("AAPL", uptrend, len(uptrend) - 1)
        # RSI, ATR% of price, volume multiple, extension above 50d MA
        assert "RSI-14 at" in text
        assert "ATR" in text and "% of price" in text
        assert "x 20d average" in text
        assert "above 50d MA" in text

    def test_downtrend_reads_as_below_falling_ma(self):
        df = make_enriched(200 * np.cumprod(np.full(260, 0.996)))  # grind down
        text = card_text("XYZ", df, len(df) - 1)
        assert "below" in text and "falling 50d MA" in text
        assert "200d MA falling" in text

    def test_raises_before_indicators_warm_up(self, uptrend):
        # row 10 has NaN sma_slow (needs 200) -> not renderable
        with pytest.raises(ValueError):
            card_text("AAPL", uptrend, 10)


class TestForwardReturns:
    def test_computes_pct_returns_at_each_horizon(self):
        # close rises exactly 1%/day so horizons are analytically known
        df = make_enriched(100 * np.cumprod(np.full(230, 1.01)))
        i = 200  # leaves >=20 forward bars
        fr = forward_returns(df, i)  # values stored rounded to 3 decimals
        entry = df["close"].iloc[i]
        assert fr["fwd_5d"] == pytest.approx(100 * (df["close"].iloc[i + 5] / entry - 1), abs=1e-3)
        assert fr["fwd_10d"] == pytest.approx(100 * (df["close"].iloc[i + 10] / entry - 1), abs=1e-3)
        assert fr["fwd_20d"] == pytest.approx(100 * (df["close"].iloc[i + 20] / entry - 1), abs=1e-3)
        # ~1%/day compounded over 5 days ≈ 5.1%
        assert fr["fwd_5d"] == pytest.approx(5.101, abs=0.01)

    def test_returns_none_when_not_enough_forward_data(self):
        df = make_enriched(100 * np.cumprod(np.full(230, 1.01)))
        assert forward_returns(df, len(df) - 1) is None   # no forward bars
        assert forward_returns(df, len(df) - 15) is None   # <20 forward bars


class TestBuildCards:
    def test_produces_one_card_per_valid_row(self, uptrend):
        ids, texts, metas = build_cards("AAPL", uptrend)
        # sma_slow (window 200) warms at index 199; _renderable also needs a
        # valid MA 5 rows back, so the first renderable row is 204. Forward
        # returns need 20 bars ahead, so the last usable row is len-1-20=239.
        first, last = 204, len(uptrend) - 1 - 20
        expected = last - first + 1
        assert len(ids) == len(texts) == len(metas) == expected
        assert len(set(ids)) == len(ids)                      # ids unique
        assert ids[0] == card_id("AAPL", uptrend.index[first].strftime("%Y-%m-%d"))
        assert ids[-1] == card_id("AAPL", uptrend.index[last].strftime("%Y-%m-%d"))
        for m in metas:
            assert {"date", "ticker", "fwd_5d", "fwd_10d", "fwd_20d"} <= m.keys()

    def test_empty_when_history_too_short(self):
        df = make_enriched(100 * np.cumprod(np.full(60, 1.004)))  # <200 warmup
        assert build_cards("AAPL", df) == ([], [], [])
