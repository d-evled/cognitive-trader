"""Integration test for the backtest replay loop on synthetic data.

Builds a tiny price DB with a clean breakout that resolves to its target,
then replays it rules-only and with a rejecting vetter — checking the loop
opens/sizes/closes trades and that vetting can veto them.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.runner import run_backtest
from src.data.db import get_conn, upsert_prices


@pytest.fixture
def cfg():
    from src.config import load_config
    return load_config()


def seed(conn, ticker, closes, volumes=None):
    closes = np.asarray(closes, float)
    n = len(closes)
    if volumes is None:
        volumes = np.full(n, 1_000_000.0)
    idx = pd.bdate_range(end="2026-07-06", periods=n)
    df = pd.DataFrame({"open": closes, "high": closes * 1.02,
                       "low": closes * 0.98, "close": closes,
                       "volume": np.asarray(volumes, float)}, index=idx)
    upsert_prices(conn, ticker, df)
    return idx


@pytest.fixture
def db(tmp_path, cfg):
    conn = get_conn(str(tmp_path / "bt.db"))
    # Flat ~100 for 260 bars, then a breakout pop to 108 on 3x volume that
    # keeps climbing to the target. SPY seeded flat as the trading calendar.
    rng = np.random.default_rng(0)
    flat = 100 + rng.normal(0, 0.2, 260)
    pop = np.array([108, 110, 113, 116, 119, 122, 125, 128])  # marches to target
    closes = np.concatenate([flat, pop])
    vols = np.full(len(closes), 1_000_000.0)
    vols[260] = 3_000_000.0
    idx = seed(conn, "AAPL", closes, vols)
    seed(conn, "SPY", np.full(len(closes), 400.0))  # calendar only
    return conn, idx


class TestRunBacktest:
    def test_rules_only_opens_and_closes_a_trade(self, db, cfg):
        conn, idx = db
        start, end = idx[255].strftime("%Y-%m-%d"), idx[-1].strftime("%Y-%m-%d")
        stats, trades = run_backtest(conn, cfg, start, end, vet_fn=None)
        assert stats["n"] >= 1
        # the breakout marches up to its target — a winning, target-reason exit
        assert any(t["exit_reason"] == "target" for t in trades)
        assert any(t["rule_name"] == "breakout" for t in trades)

    def test_rejecting_vetter_produces_no_trades(self, db, cfg):
        conn, idx = db
        start, end = idx[255].strftime("%Y-%m-%d"), idx[-1].strftime("%Y-%m-%d")

        class Reject:
            verdict = "reject"
            size_pct = 0.0

        stats, trades = run_backtest(conn, cfg, start, end,
                                     vet_fn=lambda cand, cap: Reject())
        assert stats["n"] == 0

    def test_approving_vetter_sizes_below_cap(self, db, cfg):
        conn, idx = db
        start, end = idx[255].strftime("%Y-%m-%d"), idx[-1].strftime("%Y-%m-%d")

        class Approve:
            verdict = "approve"
            size_pct = 3.0  # below the 10% gate cap

        seen = {}

        def vet_fn(cand, cap):
            seen["cap"] = cap
            return Approve()

        stats, trades = run_backtest(conn, cfg, start, end, vet_fn=vet_fn)
        assert stats["n"] >= 1
        assert seen["cap"] > 0  # the gate cap was passed to the vetter
