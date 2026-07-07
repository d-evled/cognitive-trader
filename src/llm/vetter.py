"""The vetting call: candidate + retrieval bundle → Claude → validated decision.

ARCHITECTURE.md §7. The model receives the evidence bundle and a strict
output contract (prompts/vet_v1.md); it returns approve/reject + a size
below the gate cap + reasoning + citations. Everything safety-relevant is
enforced in contracts.py, not trusted from the model.

The Anthropic client is injected so tests use a fake; production passes a
real `anthropic.Anthropic()`. Model defaults come from config: Sonnet for
the daily loop, Haiku for bulk backtests.
"""
from pathlib import Path

from src.llm.cache import ResponseCache, candidate_hash
from src.llm.contracts import (
    VET_SCHEMA, ContractError, error_decision, parse_response, validate_decision,
)
from src.rag.retriever import candidate_description

# Headroom for the daily model (Sonnet 5) — it runs adaptive thinking by
# default, which shares this budget, so a tight cap could truncate the JSON.
# Haiku (backtests) has no thinking; this only caps its short output.
MAX_TOKENS = 4096


def load_prompt(path: str) -> tuple[str, str]:
    """Return (prompt_text, prompt_version). Version is the file stem, so
    every decision can record exactly which prompt produced it."""
    p = Path(path)
    return p.read_text(), p.stem


def build_user_content(bundle: dict) -> str:
    """Render the retrieval bundle into the user message. Every retrieved
    item is labelled with its citable id (S-… / J-…); the base-rate stats
    are spelled out so the model weighs the empirical evidence."""
    c = bundle["candidate"]
    lines = [
        f"CANDIDATE: {candidate_description(c)}",
        f"Gates already passed. Entry {c.entry_price}, stop {c.stop_price}, "
        f"target {c.target_price}.",
        "",
        "SIMILAR HISTORIC SETUPS (cite by id):",
    ]
    for h in bundle["setups"]:
        fr = h.metadata
        lines.append(f"  [{h.id}] fwd_5d={fr.get('fwd_5d')}% fwd_10d={fr.get('fwd_10d')}% "
                     f"fwd_20d={fr.get('fwd_20d')}%  — {h.text}")
    for hz, s in bundle["setup_stats"].items():
        if s["n"]:
            lines.append(f"  base rate {hz}: median {s['median']}%, "
                         f"{s['pct_positive']}% positive over {s['n']} setups")
    lines += ["", "SIMILAR JOURNAL ENTRIES (cite by id):"]
    if not bundle["journal"]:
        lines.append("  (none yet — the journal is still filling)")
    for h in bundle["journal"]:
        lines.append(f"  [{h.id}] {h.metadata.get('outcome','')}: {h.text}")
    return "\n".join(lines)


class Vetter:
    def __init__(self, client, model: str, prompt_text: str,
                 prompt_version: str, cache: ResponseCache):
        self.client = client
        self.model = model
        self.prompt_text = prompt_text
        self.prompt_version = prompt_version
        self.cache = cache

    def _extract_text(self, resp) -> str:
        return next((b.text for b in resp.content
                     if getattr(b, "type", None) == "text"), "")

    def _decide(self, raw: str, valid_ids, size_cap: float):
        return validate_decision(parse_response(raw), valid_ids, size_cap)

    def vet(self, candidate, bundle: dict, size_cap: float):
        valid_ids = ([h.id for h in bundle["setups"]]
                     + [h.id for h in bundle["journal"]])
        h = candidate_hash(candidate)

        cached = self.cache.get(h, self.prompt_version)
        if cached is not None:
            try:
                return self._decide(cached, valid_ids, size_cap)
            except (ValueError, ContractError):
                pass  # stale/corrupt cache entry — fall through and re-ask

        user = build_user_content(bundle)
        for _ in range(2):  # one retry, then auto-reject (ARCHITECTURE §7)
            resp = self.client.messages.create(
                model=self.model, max_tokens=MAX_TOKENS,
                system=self.prompt_text,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": VET_SCHEMA}},
            )
            text = self._extract_text(resp)
            try:
                decision = self._decide(text, valid_ids, size_cap)
            except (ValueError, ContractError):
                continue
            self.cache.put(h, self.prompt_version, text, self.model)
            return decision

        return error_decision("invalid model output after one retry")
