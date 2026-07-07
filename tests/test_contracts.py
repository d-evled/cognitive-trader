"""Tests for the LLM vetting contract — the code that turns a model's raw
JSON into a trusted, safe decision (ARCHITECTURE.md §7).

All pure: no API calls. This is where the safety properties live —
citations are validated against the bundle, size is clamped to the gate
cap, and malformed output degrades to an auto-reject rather than crashing.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.contracts import (
    ContractError, error_decision, parse_response, validate_decision,
)


def good(**over):
    d = {"verdict": "approve", "size_pct": 6.5, "confidence": 0.62,
         "reasoning": "Setup resembles [S-1] and [J-2].",
         "citations": ["S-1", "J-2"], "risk_notes": "earnings in 12d"}
    d.update(over)
    return d


VALID_IDS = {"S-1", "S-2", "J-2", "J-3"}


class TestParseResponse:
    def test_parses_plain_json(self):
        assert parse_response('{"verdict": "reject"}')["verdict"] == "reject"

    def test_strips_markdown_code_fence(self):
        text = '```json\n{"verdict": "approve"}\n```'
        assert parse_response(text)["verdict"] == "approve"

    def test_raises_on_non_json(self):
        with pytest.raises(ValueError):
            parse_response("I cannot help with that.")


class TestValidateDecision:
    def test_valid_approve_within_cap(self):
        d = validate_decision(good(), VALID_IDS, size_cap=10.0)
        assert d.verdict == "approve"
        assert d.size_pct == 6.5
        assert d.citations == ["S-1", "J-2"]

    def test_size_clamped_to_gate_cap(self):
        # The model is never allowed to exceed the gate cap — safety in code.
        d = validate_decision(good(size_pct=25.0), VALID_IDS, size_cap=10.0)
        assert d.size_pct == 10.0

    def test_reject_forces_zero_size(self):
        d = validate_decision(good(verdict="reject", size_pct=5.0), VALID_IDS, size_cap=10.0)
        assert d.verdict == "reject"
        assert d.size_pct == 0.0

    def test_hallucinated_citation_auto_rejects(self):
        d = validate_decision(good(citations=["S-1", "S-999"]), VALID_IDS, size_cap=10.0)
        assert d.verdict == "reject"
        assert d.size_pct == 0.0
        assert d.auto_reason == "hallucinated_citation"

    def test_confidence_clamped_to_unit_interval(self):
        assert validate_decision(good(confidence=1.5), VALID_IDS, 10.0).confidence == 1.0
        assert validate_decision(good(confidence=-0.2), VALID_IDS, 10.0).confidence == 0.0

    def test_missing_required_field_raises(self):
        bad = good()
        del bad["verdict"]
        with pytest.raises(ContractError):
            validate_decision(bad, VALID_IDS, 10.0)

    def test_unknown_verdict_raises(self):
        with pytest.raises(ContractError):
            validate_decision(good(verdict="maybe"), VALID_IDS, 10.0)

    def test_non_numeric_size_raises(self):
        with pytest.raises(ContractError):
            validate_decision(good(size_pct="a lot"), VALID_IDS, 10.0)

    def test_empty_citations_ok_for_reject(self):
        d = validate_decision(good(verdict="reject", citations=[]), VALID_IDS, 10.0)
        assert d.verdict == "reject"


class TestErrorDecision:
    def test_error_decision_is_safe(self):
        d = error_decision("parse failed after retry")
        assert d.verdict == "error"
        assert d.size_pct == 0.0          # never trades on an error
        assert "parse failed" in d.reasoning
