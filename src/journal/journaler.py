"""Journal text templates + writes.

The journal is the system's memory: in Week 3 these rows get embedded
into Chroma, and future vetting retrieves them as evidence ("the last
four times you took this kind of trade, here's what happened"). So the
templates pack the facts a future reader — human or LLM — needs, in
plain prose that embeds well.
"""
import sqlite3

from src.data.db import add_journal_row
from src.signals.rules import Candidate


def entry_text(candidate: Candidate, qty: int, size_pct: float) -> str:
    c = candidate
    return (
        f"{c.date} — Opened {c.ticker} long: {qty} shares ({size_pct}% of equity) "
        f"on the {c.rule_name} rule. Entry ~{c.entry_price}, stop {c.stop_price}, "
        f"target {c.target_price}. Context at signal: {c.context}."
    )


_LESSONS = {
    ("win", "target"): "The bracket worked as designed — setup reached its target.",
    ("win", "time"): "Positive but slow; the time stop freed the capital.",
    ("win", "stop"): "Net positive stop exit (stop above entry is unusual — check the data).",
    ("loss", "stop"): "Stopped out — the setup failed; the stop capped the damage as designed.",
    ("loss", "time"): "Went nowhere for the full hold; time stop cut the dead weight.",
    ("loss", "target"): "Loss at target exit is unusual — check the data.",
}


def exit_text(trade: dict | sqlite3.Row, hold_days: int) -> str:
    """Exit post-mortem: ticker, rule, hold days, outcome, reason, lesson."""
    t = dict(trade)
    outcome = "win" if t["pnl_pct"] >= 0 else "loss"
    lesson = _LESSONS.get((outcome, t["exit_reason"]),
                          "Manual exit — note why in a follow-up entry.")
    return (
        f"{t['exit_date']} — Closed {t['ticker']} long after {hold_days} trading "
        f"day(s), {t['pnl_pct']:+.1f}% ({outcome}). Entered {t['entry_date']} at "
        f"{t['entry_price']} on the {t['rule_name']} rule; exited at "
        f"{t['exit_price']} via {t['exit_reason']}. Lesson: {lesson}"
    )


def write_journal_entry(conn: sqlite3.Connection, trade_id: int | None,
                        date: str, kind: str, text: str) -> int:
    return add_journal_row(conn, trade_id, date, kind, text)
