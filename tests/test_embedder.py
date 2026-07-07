"""Integration tests for the real Chroma-backed KnowledgeBase.

These use a real temp Chroma dir and the real embedding model (no mocks —
mocking a vector store would test the mock, not retrieval). They're a bit
slower because the model loads once; that's the price of testing the thing
that actually ships. Skipped cleanly if the heavy deps aren't installed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("chromadb")
pytest.importorskip("sentence_transformers")

from src.rag.embedder import KnowledgeBase, date_ord


def test_date_ord_is_chronological():
    assert date_ord("2026-07-06") == 20260706
    assert date_ord("2025-12-31") < date_ord("2026-01-01")


@pytest.fixture(scope="module")
def kb(tmp_path_factory):
    path = tmp_path_factory.mktemp("chroma")
    return KnowledgeBase(str(path))


def test_setup_query_respects_no_lookahead_cutoff(kb):
    # Three cards on three dates; a query as-of the middle date must not
    # return the future card, no matter how similar it is.
    kb.add_setups(
        ids=["S-AAA-2026-01-01", "S-AAA-2026-06-01", "S-AAA-2026-12-01"],
        texts=["AAA uptrend pullback setup", "AAA uptrend pullback setup",
               "AAA uptrend pullback setup"],
        metadatas=[{"date": "2026-01-01", "ticker": "AAA", "fwd_10d": 1.0},
                   {"date": "2026-06-01", "ticker": "AAA", "fwd_10d": 2.0},
                   {"date": "2026-12-01", "ticker": "AAA", "fwd_10d": 3.0}],
    )
    hits = kb.query_setups("AAA uptrend pullback setup",
                           as_of_date="2026-06-15", k=10)
    dates = {h.metadata["date"] for h in hits}
    assert dates == {"2026-01-01", "2026-06-01"}
    assert "2026-12-01" not in dates  # the future must stay invisible


def test_journal_prefers_same_rule_then_falls_back(kb):
    kb.add_journal(
        ids=["J-1", "J-2"],
        texts=["Closed BBB long, breakout worked", "Closed CCC long, pullback worked"],
        metadatas=[{"rule_name": "breakout", "outcome": "win"},
                   {"rule_name": "trend_pullback", "outcome": "win"}],
    )
    same = kb.query_journal("breakout long", rule_name="breakout", k=4)
    assert [h.id for h in same] == ["J-1"]

    # a rule with no entries yet falls back to unfiltered similarity
    fallback = kb.query_journal("some long setup", rule_name="oversold_reversion", k=4)
    assert len(fallback) == 2
