import numpy as np
import pandas as pd

from src.signals.indicators import atr, enrich, rsi, rolling_high, sma
from tests.conftest import make_df


def test_sma_known_values():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = sma(s, 3)
    assert np.isnan(out.iloc[1])          # window not filled yet
    assert out.iloc[2] == 2.0             # mean(1,2,3)
    assert out.iloc[4] == 4.0             # mean(3,4,5)


def test_rsi_bounds_and_direction():
    rng = np.random.default_rng(1)
    s = pd.Series(100 + np.cumsum(rng.normal(0, 1, 200)))
    out = rsi(s).dropna()
    assert ((out >= 0) & (out <= 100)).all()

    up = pd.Series(np.linspace(100, 200, 60))     # only gains
    assert rsi(up).iloc[-1] > 95
    down = pd.Series(np.linspace(200, 100, 60))   # only losses
    assert rsi(down).iloc[-1] < 5


def test_rsi_warmup_is_nan():
    s = pd.Series(np.linspace(100, 110, 30))
    assert rsi(s, 14).iloc[:13].isna().all()


def test_atr_positive_and_scales_with_volatility():
    calm = make_df(100 * np.cumprod(np.full(100, 1.0005)))
    calm_atr = atr(calm).iloc[-1]
    assert calm_atr > 0
    # Same path but 5x the daily band -> ATR must be clearly larger.
    wild = calm.copy()
    wild["high"] = wild["close"] * 1.05
    wild["low"] = wild["close"] * 0.95
    assert atr(wild).iloc[-1] > 3 * calm_atr


def test_rolling_high():
    s = pd.Series([1.0, 5.0, 3.0, 2.0, 4.0])
    out = rolling_high(s, 3)
    assert out.iloc[2] == 5.0
    assert out.iloc[4] == 4.0


def test_enrich_adds_all_columns(cfg):
    df = enrich(make_df(np.linspace(100, 120, 300)), cfg["indicators"])
    for col in ["sma_fast", "sma_slow", "rsi", "atr", "prior_high", "vol_avg"]:
        assert col in df.columns
        assert not np.isnan(df[col].iloc[-1])


def test_prior_high_excludes_today(cfg):
    closes = np.concatenate([np.full(299, 100.0), [150.0]])
    df = enrich(make_df(closes), cfg["indicators"])
    # Today's 150 spike must NOT be inside its own breakout reference.
    assert df["prior_high"].iloc[-1] < 150.0
