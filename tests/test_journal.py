"""Tests for journal text templates and DB writes."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.db import get_conn
from src.journal.journaler import entry_text, exit_text, write_journal_entry
from src.signals.rules import Candidate


def make_candidate():
    return Candidate(
        ticker="MSFT", date="2026-07-06", rule_name="breakout",
        direction="long", entry_price=500.0, stop_price=482.0,
        target_price=527.0, context={"volume_ratio": 2.1},
    )


class TestEntryText:
    def test_mentions_the_facts_a_future_reader_needs(self):
        text = entry_text(make_candidate(), qty=13, size_pct=6.5)
        for needle in ["MSFT", "breakout", "13", "500.0", "482.0", "527.0", "6.5"]:
            assert needle in text, f"entry text missing {needle!r}: {text}"


class TestExitText:
    def _trade(self, pnl_pct):
        return {
            "ticker": "MSFT", "rule_name": "breakout",
            "entry_date": "2026-07-07", "entry_price": 500.0,
            "exit_date": "2026-07-16", "exit_price": 500.0 * (1 + pnl_pct / 100),
            "exit_reason": "target", "pnl_pct": pnl_pct,
        }

    def test_win_postmortem_has_ticker_rule_days_outcome(self):
        text = exit_text(self._trade(+5.4), hold_days=7)
        for needle in ["MSFT", "breakout", "7", "+5.4", "target", "win"]:
            assert needle in text.lower() or needle in text, f"exit text missing {needle!r}: {text}"

    def test_loss_is_reported_honestly(self):
        text = exit_text(self._trade(-3.6), hold_days=2)
        assert "loss" in text.lower()
        assert "-3.6" in text


class TestWriteJournalEntry:
    def test_row_lands_unembedded_for_week3_sync(self, tmp_path):
        conn = get_conn(str(tmp_path / "t.db"))
        write_journal_entry(conn, trade_id=1, date="2026-07-07", kind="entry", text="hello")
        row = conn.execute("SELECT * FROM journal_entries").fetchone()
        assert row is not None
        assert (row["trade_id"], row["kind"], row["text"], row["embedded"]) == (1, "entry", "hello", 0)
