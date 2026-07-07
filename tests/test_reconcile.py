"""Tests for reconciliation: keeping the DB in sync with the broker.

Uses a FakeBroker (same method surface as AlpacaBroker) so tests run
offline and deterministically.
"""
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.broker.alpaca_client import BrokerPosition, ExitFill
from src.broker.reconcile import reconcile
from src.data.db import get_conn, open_trades, record_decision, record_signal, record_trade
from src.signals.rules import Candidate


@dataclass
class FakeBroker:
    positions: list = field(default_factory=list)
    exit_fills: dict = field(default_factory=dict)   # ticker -> ExitFill
    market_closes: list = field(default_factory=list)  # tickers we were asked to close

    def open_positions(self):
        return self.positions

    def latest_exit_fill(self, ticker):
        return self.exit_fills.get(ticker)

    def close_position_market(self, ticker):
        self.market_closes.append(ticker)


@pytest.fixture
def conn(tmp_path):
    conn = get_conn(str(tmp_path / "test.db"))
    # SPY calendar: 30 business days ending 2026-07-06 (so time-stop math works)
    import pandas as pd
    for d in pd.bdate_range(end="2026-07-06", periods=30):
        conn.execute("INSERT INTO prices VALUES ('SPY', ?, 1, 1, 1, 1, 1)",
                     (d.strftime("%Y-%m-%d"),))
    conn.commit()
    return conn


def seed_open_trade(conn, ticker="AAPL", entry_date="2026-07-01", entry_price=200.0):
    c = Candidate(ticker=ticker, date=entry_date, rule_name="trend_pullback",
                  direction="long", entry_price=entry_price, stop_price=190.0,
                  target_price=215.0, context={})
    sig = record_signal(conn, c.date, c.ticker, c.rule_name, c.direction, c.context_json())
    dec = record_decision(conn, sig, c.date, verdict="approve", size_pct=5.0,
                          reasoning="rules-only mode", model="rules-only")
    return record_trade(conn, dec, c, qty=10, entry_date=entry_date)


class TestReconcile:
    def test_vanished_position_closes_trade_and_writes_exit_journal(self, conn):
        trade_id = seed_open_trade(conn, entry_date="2026-07-01", entry_price=200.0)
        broker = FakeBroker(
            positions=[],  # AAPL no longer held: its stop leg filled
            exit_fills={"AAPL": ExitFill(price=190.0, date="2026-07-03", order_type="stop")},
        )

        events = reconcile(conn, broker, today="2026-07-06", time_stop_days=20)

        assert open_trades(conn) == []
        row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        assert row["exit_reason"] == "stop"
        assert row["exit_price"] == 190.0
        journal = conn.execute(
            "SELECT * FROM journal_entries WHERE trade_id=? AND kind='exit'", (trade_id,)
        ).fetchone()
        assert journal is not None
        assert "AAPL" in journal["text"] and "trend_pullback" in journal["text"]
        assert len(events) == 1

    def test_position_still_held_stays_open(self, conn):
        seed_open_trade(conn, entry_date="2026-07-01")
        broker = FakeBroker(positions=[
            BrokerPosition(ticker="AAPL", qty=10, avg_entry_price=200.0,
                           market_value=2050.0, unrealized_pl=50.0)])

        reconcile(conn, broker, today="2026-07-06", time_stop_days=20)

        assert len(open_trades(conn)) == 1
        assert broker.market_closes == []

    def test_time_stop_requests_market_close(self, conn):
        # Entered 29 business days before 2026-07-06 -> way past the 20-day stop
        entry = "2026-05-26"
        seed_open_trade(conn, entry_date=entry)
        broker = FakeBroker(positions=[
            BrokerPosition(ticker="AAPL", qty=10, avg_entry_price=200.0,
                           market_value=1900.0, unrealized_pl=-100.0)])

        reconcile(conn, broker, today="2026-07-06", time_stop_days=20)

        assert broker.market_closes == ["AAPL"]
        # trade stays open until the close order actually fills (next run picks it up)
        assert len(open_trades(conn)) == 1

    def test_held_position_syncs_actual_fill_price(self, conn):
        """We record entry_price = signal close when submitting; the real
        fill happens at next open. Once the position shows up at the broker,
        adopt its avg_entry_price so P&L is computed off reality."""
        trade_id = seed_open_trade(conn, entry_date="2026-07-01", entry_price=200.0)
        broker = FakeBroker(positions=[
            BrokerPosition(ticker="AAPL", qty=10, avg_entry_price=201.35,
                           market_value=2013.5, unrealized_pl=0.0)])

        reconcile(conn, broker, today="2026-07-02", time_stop_days=20)

        row = conn.execute("SELECT entry_price FROM trades WHERE id=?", (trade_id,)).fetchone()
        assert row["entry_price"] == 201.35

    def test_vanished_position_with_no_fill_found_is_left_alone(self, conn):
        """If Alpaca has no position AND no exit fill (e.g. API hiccup),
        don't guess — leave the trade open and report it."""
        seed_open_trade(conn)
        broker = FakeBroker(positions=[], exit_fills={})

        events = reconcile(conn, broker, today="2026-07-06", time_stop_days=20)

        assert len(open_trades(conn)) == 1
        assert any("no exit fill" in e.lower() for e in events)
