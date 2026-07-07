"""Shared test fixtures: hand-built price histories with known properties."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config


@pytest.fixture(scope="session")
def cfg():
    return load_config()


def make_df(closes, volumes=None) -> pd.DataFrame:
    """Build a daily-bar DataFrame from a close series; highs/lows are a
    fixed 1% band so ATR is predictable."""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    if volumes is None:
        volumes = np.full(n, 1_000_000.0)
    idx = pd.bdate_range(end="2026-07-06", periods=n)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": np.asarray(volumes, dtype=float),
        },
        index=idx,
    )


@pytest.fixture
def uptrend_pullback_df():
    """250 bars grinding up ~0.4%/day, then a 4-day sharp dip, then an
    up-tick on the final bar. Should trigger trend_pullback."""
    base = 100 * np.cumprod(np.full(245, 1.004))
    dip = base[-1] * np.cumprod(np.full(4, 0.978))
    last = dip[-1] * 1.02
    return make_df(np.concatenate([base, dip, [last]]))


@pytest.fixture
def breakout_df():
    """Flat around 100 for 250 bars, then a close at 106 on 3x volume.
    Should trigger breakout (new 20d high + volume)."""
    rng = np.random.default_rng(7)
    flat = 100 + rng.normal(0, 0.3, 250)
    closes = np.concatenate([flat, [106.0]])
    volumes = np.full(251, 1_000_000.0)
    volumes[-1] = 3_000_000.0
    return make_df(closes, volumes)


@pytest.fixture
def washout_df():
    """Long strong uptrend then a 10-day slide: RSI pinned low but price
    still far above the 200d MA. Should trigger oversold_reversion."""
    base = 100 * np.cumprod(np.full(240, 1.005))
    slide = base[-1] * np.cumprod(np.full(11, 0.985))
    return make_df(np.concatenate([base, slide]))


@pytest.fixture
def boring_df():
    """Gentle drift, no drama: no rule should fire."""
    closes = 100 * np.cumprod(np.full(251, 1.0005))
    return make_df(closes)
