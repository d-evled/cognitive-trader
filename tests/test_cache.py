"""Tests for the LLM response cache (keyed on candidate + prompt version)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.cache import ResponseCache, candidate_hash
from src.signals.rules import Candidate


def cand(**over):
    d = dict(ticker="AAPL", date="2026-07-06", rule_name="trend_pullback",
             direction="long", entry_price=312.66, stop_price=295.41,
             target_price=338.54, context={"rsi": 62.4})
    d.update(over)
    return Candidate(**d)


class TestCandidateHash:
    def test_same_candidate_same_hash(self):
        assert candidate_hash(cand()) == candidate_hash(cand())

    def test_differs_when_a_field_changes(self):
        assert candidate_hash(cand()) != candidate_hash(cand(entry_price=313.0))
        assert candidate_hash(cand()) != candidate_hash(cand(ticker="MSFT"))


class TestResponseCache:
    def test_put_then_get_roundtrips(self, tmp_path):
        c = ResponseCache(str(tmp_path / "cache.db"))
        h = candidate_hash(cand())
        assert c.get(h, "vet_v1") is None
        c.put(h, "vet_v1", '{"verdict": "approve"}', model="claude-haiku-4-5")
        assert c.get(h, "vet_v1") == '{"verdict": "approve"}'

    def test_prompt_version_is_part_of_the_key(self, tmp_path):
        c = ResponseCache(str(tmp_path / "cache.db"))
        h = candidate_hash(cand())
        c.put(h, "vet_v1", "old", model="m")
        assert c.get(h, "vet_v2") is None      # different prompt version = miss
        c.put(h, "vet_v2", "new", model="m")
        assert c.get(h, "vet_v1") == "old"     # versions don't collide
        assert c.get(h, "vet_v2") == "new"
