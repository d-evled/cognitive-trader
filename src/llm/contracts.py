"""The vetting contract: turn a model's raw JSON into a trusted decision.

ARCHITECTURE.md §7 — the safety properties enforced here, in code, never
delegated to the model:
  * response must be valid JSON matching the schema (parse failure →
    the vetter retries once, then calls error_decision → verdict "error")
  * every citation id must exist in the retrieval bundle; a hallucinated
    citation auto-rejects the trade
  * size_pct is clamped to the gate cap — the model can size below it,
    never above

Everything here is pure and unit-tested; the API call lives in vetter.py.
"""
import json
from dataclasses import dataclass, field

VERDICTS = {"approve", "reject"}

# JSON schema handed to the model via output_config.format so the response
# is guaranteed to parse (contracts still re-validate — defense in depth).
VET_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "reject"]},
        "size_pct": {"type": "number"},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
        "risk_notes": {"type": "string"},
    },
    "required": ["verdict", "size_pct", "confidence", "reasoning",
                 "citations", "risk_notes"],
    "additionalProperties": False,
}


class ContractError(Exception):
    """Raised when the model output can't be coerced into a valid decision."""


@dataclass
class VetDecision:
    verdict: str                 # 'approve' | 'reject' | 'error'
    size_pct: float              # of portfolio, already clamped to the cap
    confidence: float            # 0-1
    reasoning: str
    citations: list = field(default_factory=list)
    risk_notes: str = ""
    auto_reason: str = ""        # set when code (not the model) forced a reject


def parse_response(text: str) -> dict:
    """Parse the model's text into a dict, tolerating ```json fences."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    return json.loads(s)  # raises ValueError (JSONDecodeError) on failure


def _num(x) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ContractError(f"expected a number, got {x!r}")
    return float(x)


def validate_decision(data: dict, valid_ids, size_cap: float) -> VetDecision:
    """Schema-check, citation-check, and clamp a parsed response.

    Raises ContractError on structural problems (missing/typed-wrong fields,
    unknown verdict). Citation and cap violations don't raise — they degrade
    to a safe auto-reject / clamp, because a live loop must never crash on
    model output.
    """
    for k in ("verdict", "size_pct", "confidence", "reasoning", "citations"):
        if k not in data:
            raise ContractError(f"missing field: {k}")
    verdict = data["verdict"]
    if verdict not in VERDICTS:
        raise ContractError(f"unknown verdict: {verdict!r}")
    if not isinstance(data["citations"], list):
        raise ContractError("citations must be a list")

    size = _num(data["size_pct"])
    confidence = min(1.0, max(0.0, _num(data["confidence"])))
    citations = [str(c) for c in data["citations"]]

    # Hallucinated evidence → auto-reject (caught mechanically, not trusted).
    valid = set(valid_ids)
    if any(c not in valid for c in citations):
        return VetDecision(
            verdict="reject", size_pct=0.0, confidence=confidence,
            reasoning=str(data.get("reasoning", "")),
            citations=citations, risk_notes=str(data.get("risk_notes", "")),
            auto_reason="hallucinated_citation")

    if verdict == "reject":
        size = 0.0
    else:
        size = min(size_cap, max(0.0, size))  # clamp into [0, cap]

    return VetDecision(
        verdict=verdict, size_pct=round(size, 2), confidence=confidence,
        reasoning=str(data["reasoning"]), citations=citations,
        risk_notes=str(data.get("risk_notes", "")))


def error_decision(reason: str) -> VetDecision:
    """A safe non-trading decision used when parsing/validation fails."""
    return VetDecision(verdict="error", size_pct=0.0, confidence=0.0,
                       reasoning=f"vetting error: {reason}", auto_reason="error")
