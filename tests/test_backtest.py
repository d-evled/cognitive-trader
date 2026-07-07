"""Tests for the backtest engine's pure pieces: bar-by-bar trade simulation
and summary statistics. The portfolio replay loop is exercised by an
integration test on synthetic data.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.engine import simulate_trade, summary_stats


def bar(d, o, h, l, c):
    return {"date": d, "open": o, "high": h, "low": l, "close": c}


class TestSimulateTrade:
    def test_entry_fills_at_next_open(self):
        bars = [bar("d1", 101.0, 102.0, 100.5, 101.5),
                bar("d2", 101.5, 110.0, 101.0, 109.0)]  # target hit d2
        r = simulate_trade(bars, stop_price=95.0, target_price=108.0, time_stop_days=20)
        assert r.entry_fill == 101.0

    def test_target_hit_exits_at_target(self):
        bars = [bar("d1", 100.0, 103.0, 99.0, 102.0),
                bar("d2", 102.0, 109.0, 101.0, 108.0)]
        r = simulate_trade(bars, stop_price=90.0, target_price=108.0, time_stop_days=20)
        assert r.reason == "target"
        assert r.exit_price == 108.0
        assert r.hold_days == 2

    def test_stop_hit_exits_at_stop(self):
        bars = [bar("d1", 100.0, 101.0, 94.0, 95.0)]  # low pierces stop day 1
        r = simulate_trade(bars, stop_price=95.0, target_price=120.0, time_stop_days=20)
        assert r.reason == "stop"
        assert r.exit_price == 95.0
        assert r.hold_days == 1

    def test_stop_wins_ties_within_a_bar(self):
        # one bar spans both stop and target — assume the stop hit first (conservative)
        bars = [bar("d1", 100.0, 130.0, 80.0, 100.0)]
        r = simulate_trade(bars, stop_price=90.0, target_price=120.0, time_stop_days=20)
        assert r.reason == "stop"

    def test_time_stop_exits_at_close_of_last_allowed_bar(self):
        bars = [bar(f"d{i}", 100.0, 101.0, 99.0, 100.0 + i) for i in range(30)]
        r = simulate_trade(bars, stop_price=50.0, target_price=200.0, time_stop_days=20)
        assert r.reason == "time"
        assert r.hold_days == 20
        assert r.exit_price == bars[19]["close"]

    def test_runs_out_of_data_exits_at_last_close(self):
        bars = [bar("d1", 100.0, 101.0, 99.0, 100.5),
                bar("d2", 100.5, 101.0, 99.5, 100.8)]
        r = simulate_trade(bars, stop_price=50.0, target_price=200.0, time_stop_days=20)
        assert r.reason == "time"
        assert r.exit_price == 100.8
        assert r.hold_days == 2


class TestSummaryStats:
    def _trades(self):
        return [
            {"rule_name": "breakout", "pnl": 200.0, "pnl_pct": 2.0},
            {"rule_name": "breakout", "pnl": -100.0, "pnl_pct": -1.0},
            {"rule_name": "trend_pullback", "pnl": 300.0, "pnl_pct": 3.0},
            {"rule_name": "trend_pullback", "pnl": 400.0, "pnl_pct": 4.0},
        ]

    def test_headline_numbers(self):
        s = summary_stats(self._trades(), starting_equity=100_000)
        assert s["n"] == 4
        assert s["wins"] == 3 and s["losses"] == 1
        assert s["win_rate"] == pytest.approx(75.0)
        assert s["final_equity"] == pytest.approx(100_800.0)
        assert s["total_return_pct"] == pytest.approx(0.8)

    def test_avg_win_and_loss(self):
        s = summary_stats(self._trades(), starting_equity=100_000)
        assert s["avg_win_pct"] == pytest.approx((2.0 + 3.0 + 4.0) / 3)
        assert s["avg_loss_pct"] == pytest.approx(-1.0)

    def test_max_drawdown(self):
        # equity path: 100k -> 100.2k -> 100.1k (dip) -> ... only one dip of 100
        trades = [
            {"rule_name": "r", "pnl": 200.0, "pnl_pct": 0.2},
            {"rule_name": "r", "pnl": -500.0, "pnl_pct": -0.5},  # peak 100.2k -> 99.7k
            {"rule_name": "r", "pnl": 100.0, "pnl_pct": 0.1},
        ]
        s = summary_stats(trades, starting_equity=100_000)
        # drawdown from peak 100200 to trough 99700 = 500/100200 (stored to 3dp)
        assert s["max_drawdown_pct"] == pytest.approx(100 * 500 / 100_200, abs=1e-3)

    def test_per_rule_breakdown(self):
        s = summary_stats(self._trades(), starting_equity=100_000)
        assert s["per_rule"]["breakout"]["n"] == 2
        assert s["per_rule"]["breakout"]["win_rate"] == pytest.approx(50.0)
        assert s["per_rule"]["trend_pullback"]["win_rate"] == pytest.approx(100.0)

    def test_empty_is_reported_not_crashed(self):
        s = summary_stats([], starting_equity=100_000)
        assert s["n"] == 0
        assert s["win_rate"] is None
        assert s["final_equity"] == 100_000
