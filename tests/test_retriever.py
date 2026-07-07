"""Tests for retrieval-bundle assembly and forward-return base rates.

We inject a FakeStore with the same method surface the real Chroma-backed
store exposes, so these run offline. The no-lookahead guarantee (date
filtering) is asserted here — it's the subtlest correctness property in
the whole system.
"""
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.retriever import build_retrieval_bundle, forward_return_stats
from src.signals.rules import Candidate


def make_candidate(ticker="MSFT", date="2026-07-06"):
    return Candidate(ticker=ticker, date=date, rule_name="trend_pullback",
                     direction="long", entry_price=500.0, stop_price=482.0,
                     target_price=527.0, context={"rsi": 38.0})


@dataclass
class Hit:
    id: str
    text: str
    metadata: dict
    distance: float = 0.1


@dataclass
class FakeStore:
    """Records the as_of_date it was queried with so tests can assert the
    no-lookahead filter is actually passed through."""
    setups: list = field(default_factory=list)
    journal: list = field(default_factory=list)
    seen_as_of: dict = field(default_factory=dict)

    def query_setups(self, text, as_of_date, k):
        self.seen_as_of["setups"] = as_of_date
        return self.setups[:k]

    def query_journal(self, text, rule_name, k):
        self.seen_as_of["journal"] = (rule_name,)
        return self.journal[:k]


class TestForwardReturnStats:
    def test_median_and_hit_rate_over_similar_cards(self):
        cards = [
            {"fwd_10d": 2.0}, {"fwd_10d": 1.0}, {"fwd_10d": -1.0},
            {"fwd_10d": 3.0}, {"fwd_10d": 5.0},
        ]
        s = forward_return_stats(cards, horizon="fwd_10d")
        assert s["n"] == 5
        assert s["median"] == pytest.approx(2.0)
        assert s["pct_positive"] == pytest.approx(80.0)  # 4 of 5 > 0

    def test_empty_is_reported_not_crashed(self):
        s = forward_return_stats([], horizon="fwd_10d")
        assert s["n"] == 0
        assert s["median"] is None
        assert s["pct_positive"] is None


class TestBundle:
    def test_bundle_has_journal_setups_and_stats(self):
        store = FakeStore(
            setups=[Hit(f"S-{i}", f"card {i}", {"fwd_5d": 1.0, "fwd_10d": 2.0, "fwd_20d": 3.0})
                    for i in range(10)],
            journal=[Hit(f"J-{i}", f"entry {i}", {"outcome": "win"}) for i in range(4)],
        )
        bundle = build_retrieval_bundle(make_candidate(), store)

        assert len(bundle["setups"]) == 10
        assert len(bundle["journal"]) == 4
        assert bundle["setup_stats"]["fwd_10d"]["median"] == pytest.approx(2.0)
        assert bundle["setup_stats"]["fwd_10d"]["pct_positive"] == pytest.approx(100.0)

    def test_no_lookahead_passes_candidate_date_as_cutoff(self):
        store = FakeStore()
        build_retrieval_bundle(make_candidate(date="2026-07-06"), store)
        assert store.seen_as_of["setups"] == "2026-07-06"

    def test_journal_filtered_to_same_rule(self):
        store = FakeStore()
        build_retrieval_bundle(make_candidate(), store)
        assert store.seen_as_of["journal"] == ("trend_pullback",)

    def test_query_text_is_the_candidate_description(self):
        """The setups query embeds a description of the candidate; it should
        mention the ticker and the rule so similarity is meaningful."""
        captured = {}

        class CapturingStore(FakeStore):
            def query_setups(self, text, as_of_date, k):
                captured["text"] = text
                return []

        build_retrieval_bundle(make_candidate(ticker="NVDA"), CapturingStore())
        assert "NVDA" in captured["text"]
        assert "trend_pullback" in captured["text"]
