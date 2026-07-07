"""Tests for the trade-lifecycle DB helpers added in Week 2."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.db import (
    close_trade,
    get_conn,
    open_trades,
    record_decision,
    record_signal,
    record_trade,
    trading_days_between,
)
from src.signals.rules import Candidate


@pytest.fixture
def conn(tmp_path):
    return get_conn(str(tmp_path / "test.db"))


def make_candidate(ticker="AAPL", entry=200.0, stop=190.0, target=215.0):
    return Candidate(
        ticker=ticker, date="2026-07-06", rule_name="trend_pullback",
        direction="long", entry_price=entry, stop_price=stop,
        target_price=target, context={"rsi": 38.0},
    )


class TestTradeLifecycle:
    def test_record_and_load_open_trade(self, conn):
        c = make_candidate()
        sig_id = record_signal(conn, c.date, c.ticker, c.rule_name, c.direction, c.context_json())
        dec_id = record_decision(conn, sig_id, c.date, verdict="approve", size_pct=6.5,
                                 reasoning="rules-only mode", model="rules-only")
        trade_id = record_trade(conn, dec_id, c, qty=30, entry_date="2026-07-07")

        trades = open_trades(conn)
        assert len(trades) == 1
        t = trades[0]
        assert t["id"] == trade_id
        assert t["ticker"] == "AAPL"
        assert t["status"] == "open"
        assert t["qty"] == 30
        assert t["stop_price"] == 190.0
        # the journal post-mortem needs the rule that fired
        assert t["rule_name"] == "trend_pullback"

    def test_close_trade_computes_pnl(self, conn):
        c = make_candidate(entry=200.0)
        sig_id = record_signal(conn, c.date, c.ticker, c.rule_name, c.direction, c.context_json())
        dec_id = record_decision(conn, sig_id, c.date, verdict="approve", size_pct=5.0,
                                 reasoning="rules-only mode", model="rules-only")
        trade_id = record_trade(conn, dec_id, c, qty=10, entry_date="2026-07-07",
                                entry_price=201.0)  # actual fill differs from signal close

        close_trade(conn, trade_id, exit_date="2026-07-20", exit_price=211.05, exit_reason="target")

        assert open_trades(conn) == []
        row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        assert row["status"] == "closed"
        assert row["exit_reason"] == "target"
        assert row["pnl"] == pytest.approx((211.05 - 201.0) * 10)
        assert row["pnl_pct"] == pytest.approx(100 * (211.05 / 201.0 - 1))


class TestTradingCalendar:
    def test_counts_trading_days_from_spy_calendar(self, conn):
        # Seed a 5-row SPY calendar: Mon Jul 6 .. Fri Jul 10 (2026)
        for d in ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10"]:
            conn.execute("INSERT INTO prices VALUES ('SPY', ?, 1, 1, 1, 1, 1)", (d,))
        conn.commit()
        # Entered on the 6th: days AFTER entry through as_of count as held days
        assert trading_days_between(conn, "2026-07-06", "2026-07-08") == 2
        assert trading_days_between(conn, "2026-07-06", "2026-07-06") == 0
