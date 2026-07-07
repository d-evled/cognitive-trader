"""Reconciliation: make the DB agree with what actually happened at the broker.

Runs at the top of every daily loop, before any new signals:
  1. A trade we think is open but the broker no longer holds -> its stop or
     target leg filled (or it was closed manually). Record the exit, compute
     P&L, write the exit journal entry.
  2. A position held past the time-stop limit -> ask the broker to
     market-close it. The close fills at the next open, so the trade row
     stays open until the NEXT run sees the position gone (case 1).

The broker argument is anything with the AlpacaBroker method surface —
tests pass a fake, production passes the real thing.
"""
import sqlite3

from src.broker.alpaca_client import exit_reason
from src.data.db import close_trade, open_trades, trading_days_between
from src.journal.journaler import exit_text, write_journal_entry


def reconcile(conn: sqlite3.Connection, broker, today: str,
              time_stop_days: int) -> list[str]:
    """Returns human-readable event lines for the daily report."""
    events: list[str] = []
    held = {p.ticker for p in broker.open_positions()}

    for t in open_trades(conn):
        ticker = t["ticker"]

        if ticker not in held:
            fill = broker.latest_exit_fill(ticker)
            if fill is None:
                # Position gone but no sell fill visible — API lag or a
                # corporate action. Don't guess; a later run will see it.
                events.append(
                    f"WARNING {ticker}: position gone but no exit fill found; "
                    f"leaving trade open")
                continue
            hold_days = trading_days_between(conn, t["entry_date"], fill.date)
            reason = exit_reason(fill.order_type, hold_days, time_stop_days)
            close_trade(conn, t["id"], exit_date=fill.date,
                        exit_price=fill.price, exit_reason=reason)
            closed = conn.execute(
                "SELECT t.*, s.rule_name FROM trades t"
                " JOIN decisions d ON t.decision_id = d.id"
                " JOIN signals s ON d.signal_id = s.id WHERE t.id = ?",
                (t["id"],)).fetchone()
            write_journal_entry(conn, t["id"], fill.date, "exit",
                                exit_text(closed, hold_days))
            events.append(
                f"CLOSED {ticker}: {closed['pnl_pct']:+.1f}% via {reason} "
                f"after {hold_days} trading day(s); exit journal written")
        else:
            # We recorded entry_price = signal close at submit time; the
            # real fill happened at the next open. Adopt the broker's
            # actual average fill so P&L is computed off reality.
            actual = next(p for p in broker.open_positions() if p.ticker == ticker)
            if actual.avg_entry_price != t["entry_price"]:
                conn.execute("UPDATE trades SET entry_price=? WHERE id=?",
                             (actual.avg_entry_price, t["id"]))
                conn.commit()
            hold_days = trading_days_between(conn, t["entry_date"], today)
            if hold_days >= time_stop_days:
                broker.close_position_market(ticker)
                events.append(
                    f"TIME STOP {ticker}: held {hold_days} trading days "
                    f"(limit {time_stop_days}); market close submitted")

    return events
