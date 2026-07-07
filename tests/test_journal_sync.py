"""Tests for journal -> Chroma sync orchestration.

The DB is real (temp SQLite); the KnowledgeBase is a fake that records what
it was handed. We're testing OUR logic: which rows get selected, what
metadata we attach, and that synced rows are marked so they aren't
re-embedded next run.
"""
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.db import (
    add_journal_row, close_trade, get_conn, record_decision, record_signal,
    record_trade,
)
from src.rag.sync import sync_journal
from src.signals.rules import Candidate


@dataclass
class FakeKB:
    added: list = field(default_factory=list)  # (ids, texts, metadatas) per call

    def add_journal(self, ids, texts, metadatas):
        self.added.append((ids, texts, metadatas))


@pytest.fixture
def conn(tmp_path):
    return get_conn(str(tmp_path / "t.db"))


def seed_closed_trade_with_entries(conn):
    c = Candidate(ticker="AAPL", date="2026-07-01", rule_name="breakout",
                  direction="long", entry_price=200.0, stop_price=190.0,
                  target_price=215.0, context={})
    sig = record_signal(conn, c.date, c.ticker, c.rule_name, c.direction, c.context_json())
    dec = record_decision(conn, sig, c.date, verdict="approve", size_pct=5.0,
                          reasoning="rules-only", model="rules-only")
    tid = record_trade(conn, dec, c, qty=10, entry_date="2026-07-02")
    add_journal_row(conn, tid, "2026-07-02", "entry", "Opened AAPL long on breakout.")
    close_trade(conn, tid, exit_date="2026-07-10", exit_price=215.0, exit_reason="target")
    add_journal_row(conn, tid, "2026-07-10", "exit", "Closed AAPL +7.5% win via target.")
    return tid


class TestSyncJournal:
    def test_embeds_unembedded_rows_and_marks_them(self, conn):
        seed_closed_trade_with_entries(conn)
        kb = FakeKB()

        n = sync_journal(conn, kb)

        assert n == 2
        ids, texts, metas = kb.added[0]
        assert set(ids) == {"J-1", "J-2"}
        # exit entry carries the rule (for the same-rule retrieval filter)
        exit_meta = metas[ids.index("J-2")]
        assert exit_meta["rule_name"] == "breakout"
        assert exit_meta["kind"] == "exit"
        assert exit_meta["ticker"] == "AAPL"
        # metadata never contains None (Chroma rejects null values)
        for m in metas:
            assert all(v is not None for v in m.values())

    def test_second_run_is_a_noop(self, conn):
        seed_closed_trade_with_entries(conn)
        kb = FakeKB()
        sync_journal(conn, kb)

        kb2 = FakeKB()
        n = sync_journal(conn, kb2)
        assert n == 0
        assert kb2.added == []

    def test_marks_embedded_flag_in_db(self, conn):
        seed_closed_trade_with_entries(conn)
        sync_journal(conn, FakeKB())
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM journal_entries WHERE embedded=0").fetchone()
        assert remaining["n"] == 0
