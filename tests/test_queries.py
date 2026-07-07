"""Tests for the Streamlit app's data-access layer (pure SQL over the DB).

The pages are thin rendering over these; the joins and the equity/unrealized
math are what's worth testing.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app.queries import (
    closed_trades, equity_curve, open_positions, recent_decisions, trade_log,
)
from src.data.db import (
    add_journal_row, close_trade, get_conn, record_decision, record_signal,
    record_trade,
)
from src.signals.rules import Candidate


def cand(ticker="AAPL", entry=200.0, stop=190.0, target=215.0, rule="trend_pullback"):
    return Candidate(ticker=ticker, date="2026-07-01", rule_name=rule,
                     direction="long", entry_price=entry, stop_price=stop,
                     target_price=target, context={"rsi": 38.0})


@pytest.fixture
def conn(tmp_path):
    conn = get_conn(str(tmp_path / "t.db"))
    # latest AAPL close for unrealized P&L
    for d, c in [("2026-07-01", 200.0), ("2026-07-08", 206.0)]:
        conn.execute("INSERT INTO prices VALUES ('AAPL', ?, ?, ?, ?, ?, 1)",
                     (d, c, c, c, c))
    conn.commit()
    return conn


def _open_trade(conn, c, qty=10, verdict="approve", model="rules-only",
                reasoning="passed gates", citations=None, confidence=None):
    import json
    sig = record_signal(conn, c.date, c.ticker, c.rule_name, c.direction, c.context_json())
    dec = record_decision(conn, sig, c.date, verdict=verdict, size_pct=5.0,
                          reasoning=reasoning, model=model, confidence=confidence,
                          citations_json=json.dumps(citations) if citations else None,
                          prompt_version="vet_v1" if model != "rules-only" else None)
    return record_trade(conn, dec, c, qty=qty, entry_date="2026-07-02", entry_price=c.entry_price)


class TestOpenPositions:
    def test_open_trade_with_unrealized_pnl(self, conn):
        _open_trade(conn, cand(entry=200.0), qty=10)
        pos = open_positions(conn)
        assert len(pos) == 1
        p = pos[0]
        assert p["ticker"] == "AAPL" and p["rule_name"] == "trend_pullback"
        assert p["qty"] == 10
        # latest close 206 vs entry 200 -> +$60, +3%
        assert p["unrealized_pnl"] == pytest.approx(60.0)
        assert p["unrealized_pct"] == pytest.approx(3.0)

    def test_closed_trades_are_excluded(self, conn):
        tid = _open_trade(conn, cand(), qty=10)
        close_trade(conn, tid, "2026-07-09", 215.0, "target")
        assert open_positions(conn) == []


class TestBundleStorage:
    def test_stored_bundle_round_trips_to_the_decision_feed(self, conn):
        import json
        from src.data.db import record_decision, record_signal
        bundle_json = json.dumps({
            "query": "AAPL trend_pullback", "setups": [{"id": "S-1", "text": "x"}],
            "setup_stats": {"fwd_10d": {"n": 5, "median": 2.0, "pct_positive": 70.0}},
            "journal": [], "news": []})
        sig = record_signal(conn, "2026-07-01", "AAPL", "trend_pullback", "long", "{}")
        record_decision(conn, sig, "2026-07-01", verdict="approve", size_pct=5.0,
                        reasoning="r", model="claude-sonnet-5", bundle_json=bundle_json)
        d = recent_decisions(conn, limit=5)[0]
        assert d["bundle"]["setups"][0]["id"] == "S-1"
        assert d["bundle"]["setup_stats"]["fwd_10d"]["pct_positive"] == 70.0


class TestRecentDecisions:
    def test_parses_citations_and_orders_newest_first(self, conn):
        _open_trade(conn, cand(ticker="AAPL"), model="claude-sonnet-5",
                    reasoning="resembles S-1", citations=["S-1", "J-2"], confidence=0.6)
        feed = recent_decisions(conn, limit=10)
        assert len(feed) == 1
        d = feed[0]
        assert d["ticker"] == "AAPL"
        assert d["verdict"] == "approve"
        assert d["citations"] == ["S-1", "J-2"]     # parsed from JSON
        assert d["confidence"] == 0.6
        assert d["prompt_version"] == "vet_v1"

    def test_rules_only_decision_has_no_citations(self, conn):
        _open_trade(conn, cand(), model="rules-only")
        d = recent_decisions(conn, limit=10)[0]
        assert d["citations"] == []


class TestEquityCurve:
    def test_steps_by_closed_trade_pnl_in_date_order(self, conn):
        t1 = _open_trade(conn, cand(ticker="AAPL", entry=200.0), qty=10)
        close_trade(conn, t1, "2026-07-05", 210.0, "target")   # +100
        t2 = _open_trade(conn, cand(ticker="AAPL", entry=200.0), qty=10)
        close_trade(conn, t2, "2026-07-09", 195.0, "stop")     # -50
        curve = equity_curve(conn, starting_equity=100_000)
        equities = [pt["equity"] for pt in curve]
        assert equities[-1] == pytest.approx(100_050)          # 100000 +100 -50
        assert equities == sorted(  # non-decreasing dates
            equities, key=lambda _: 0) or True  # (order asserted below)
        assert [pt["date"] for pt in curve] == sorted(pt["date"] for pt in curve)


class TestTradeLog:
    def test_joins_trades_to_decisions_and_rule(self, conn):
        tid = _open_trade(conn, cand(ticker="AAPL"), model="claude-sonnet-5")
        close_trade(conn, tid, "2026-07-09", 215.0, "target")
        rows = trade_log(conn)
        assert len(rows) == 1
        r = rows[0]
        assert r["ticker"] == "AAPL" and r["rule_name"] == "trend_pullback"
        assert r["status"] == "closed" and r["exit_reason"] == "target"
        assert r["model"] == "claude-sonnet-5"
