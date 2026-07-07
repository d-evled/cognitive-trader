"""Tests for the vetter orchestration: prompt building, retry-then-reject,
and caching. A FakeClient stands in for the Anthropic SDK (same surface:
client.messages.create(...) → response.content[i].text), so nothing hits
the network.
"""
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.cache import ResponseCache, candidate_hash
from src.llm.vetter import Vetter, build_user_content
from src.rag.retriever import build_retrieval_bundle
from src.signals.rules import Candidate


# --- fakes ----------------------------------------------------------------

@dataclass
class _Block:
    type: str
    text: str


@dataclass
class _Resp:
    content: list


class _Messages:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kwargs):
        self.outer.calls += 1
        self.outer.last_kwargs = kwargs
        text = self.outer.responses.pop(0)
        # mimic Sonnet: a (possibly empty) thinking block then the text block
        return _Resp([_Block("thinking", ""), _Block("text", text)])


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.last_kwargs = None
        self.messages = _Messages(self)


@dataclass
class Hit:
    id: str
    text: str
    metadata: dict
    distance: float = 0.1


@dataclass
class FakeStore:
    setups: list = field(default_factory=list)
    journal: list = field(default_factory=list)

    def query_setups(self, text, as_of_date, k):
        return self.setups[:k]

    def query_journal(self, text, rule_name, k):
        return self.journal[:k]


def make_candidate():
    return Candidate(ticker="AAPL", date="2026-07-06", rule_name="trend_pullback",
                     direction="long", entry_price=312.66, stop_price=295.41,
                     target_price=338.54, context={"rsi": 62.4})


def make_bundle():
    store = FakeStore(
        setups=[Hit("S-1", "AAPL uptrend", {"fwd_10d": 2.0, "fwd_5d": 1.0, "fwd_20d": 3.0}),
                Hit("S-2", "AAPL uptrend", {"fwd_10d": 3.0, "fwd_5d": 1.5, "fwd_20d": 4.0})],
        journal=[Hit("J-1", "Closed AAPL +3% win", {"outcome": "win"})])
    return build_retrieval_bundle(make_candidate(), store)


PROMPT = "You are a trade vetter. Output JSON per the contract."


def approve_json(size=6.5, cites=("S-1", "J-1")):
    return json.dumps({"verdict": "approve", "size_pct": size, "confidence": 0.6,
                       "reasoning": "looks like S-1", "citations": list(cites),
                       "risk_notes": "none"})


class TestBuildUserContent:
    def test_lists_the_citable_ids(self):
        content = build_user_content(make_bundle())
        assert "S-1" in content and "S-2" in content and "J-1" in content
        assert "AAPL" in content and "trend_pullback" in content
        # base-rate stats should be surfaced for the model to weigh
        assert "fwd_10d" in content or "10d" in content


class TestVet:
    def _vetter(self, client, cache):
        return Vetter(client=client, model="claude-haiku-4-5",
                      prompt_text=PROMPT, prompt_version="vet_v1", cache=cache)

    def test_returns_validated_clamped_decision(self, tmp_path):
        client = FakeClient([approve_json(size=25.0)])  # over the cap
        v = self._vetter(client, ResponseCache(str(tmp_path / "c.db")))
        d = v.vet(make_candidate(), make_bundle(), size_cap=10.0)
        assert d.verdict == "approve"
        assert d.size_pct == 10.0          # clamped
        assert client.calls == 1

    def test_cache_hit_skips_the_api(self, tmp_path):
        cache = ResponseCache(str(tmp_path / "c.db"))
        client = FakeClient([approve_json()])
        v = self._vetter(client, cache)
        v.vet(make_candidate(), make_bundle(), size_cap=10.0)
        # second identical call: served from cache, no new API call
        client2 = FakeClient([])            # would IndexError if called
        v2 = self._vetter(client2, cache)
        d = v2.vet(make_candidate(), make_bundle(), size_cap=10.0)
        assert d.verdict == "approve"
        assert client2.calls == 0

    def test_retries_once_on_bad_json_then_succeeds(self, tmp_path):
        client = FakeClient(["not json at all", approve_json()])
        v = self._vetter(client, ResponseCache(str(tmp_path / "c.db")))
        d = v.vet(make_candidate(), make_bundle(), size_cap=10.0)
        assert d.verdict == "approve"
        assert client.calls == 2

    def test_two_failures_yield_error_decision_and_no_cache(self, tmp_path):
        cache = ResponseCache(str(tmp_path / "c.db"))
        client = FakeClient(["nope", "still nope"])
        v = self._vetter(client, cache)
        d = v.vet(make_candidate(), make_bundle(), size_cap=10.0)
        assert d.verdict == "error"
        assert d.size_pct == 0.0
        # errors are not cached — a later run may succeed
        assert cache.get(candidate_hash(make_candidate()), "vet_v1") is None

    def test_hallucinated_citation_is_auto_rejected(self, tmp_path):
        client = FakeClient([approve_json(cites=("S-1", "S-404"))])
        v = self._vetter(client, ResponseCache(str(tmp_path / "c.db")))
        d = v.vet(make_candidate(), make_bundle(), size_cap=10.0)
        assert d.verdict == "reject"
        assert d.auto_reason == "hallucinated_citation"
