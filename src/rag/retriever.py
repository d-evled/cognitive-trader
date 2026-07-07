"""The retrieval layer: assemble the evidence bundle for one candidate.

`build_retrieval_bundle(candidate, store)` produces exactly what the LLM
vetting stage (Week 4) will read:

  * setups — the k nearest historical setup cards, plus base-rate stats
    computed from their forward returns ("median 10d return +1.9%, 7/10
    positive")
  * journal — past journal entries about similar trades (same-rule filter)
  * news — deferred to Week 5

The `store` argument is any object with the query methods below — the real
one is Chroma-backed (embedder.py); tests inject a fake. Crucially, the
setups query passes the candidate's date as an as-of cutoff so retrieval
never sees data from the future (the no-lookahead guarantee that keeps
backtests honest — ARCHITECTURE.md §8).
"""
from statistics import median

from src.rag.setup_cards import FORWARD_HORIZONS
from src.signals.rules import Candidate

N_SETUPS = 10
N_JOURNAL = 4
_HORIZON_KEYS = tuple(f"fwd_{h}d" for h in FORWARD_HORIZONS)


def candidate_description(c: Candidate) -> str:
    """A short natural-language description of the candidate, embedded to
    find similar historical setup cards. Mirrors the setup-card vocabulary
    so the query lands near real cards in embedding space."""
    ctx = c.context or {}
    rsi = ctx.get("rsi")
    rsi_part = f", RSI-14 at {rsi:.0f}" if isinstance(rsi, (int, float)) else ""
    return (f"{c.ticker} {c.date}. {c.rule_name} long setup{rsi_part}. "
            f"Entry {c.entry_price}, stop {c.stop_price}, target {c.target_price}.")


def forward_return_stats(cards: list, horizon: str = "fwd_10d") -> dict:
    """Empirical base rate over retrieved cards' forward returns.

    `cards` is a list of metadata dicts (or hit objects with .metadata).
    Returns n, median return, and % positive for the horizon. An empty set
    is reported (n=0, None stats), never an exception — a candidate with no
    similar history is a valid, informative outcome for the LLM to weigh.
    """
    vals = []
    for c in cards:
        md = getattr(c, "metadata", c)
        v = md.get(horizon)
        if v is not None:
            vals.append(float(v))
    if not vals:
        return {"n": 0, "median": None, "pct_positive": None}
    return {
        "n": len(vals),
        "median": round(median(vals), 3),
        "pct_positive": round(100 * sum(v > 0 for v in vals) / len(vals), 1),
    }


def build_retrieval_bundle(candidate: Candidate, store,
                           n_setups: int = N_SETUPS,
                           n_journal: int = N_JOURNAL) -> dict:
    query = candidate_description(candidate)

    # No lookahead: only cards dated on/before the candidate's date.
    setups = store.query_setups(query, as_of_date=candidate.date, k=n_setups)
    journal = store.query_journal(query, rule_name=candidate.rule_name, k=n_journal)

    setup_stats = {h: forward_return_stats(setups, horizon=h) for h in _HORIZON_KEYS}

    return {
        "candidate": candidate,
        "query": query,
        "setups": setups,
        "setup_stats": setup_stats,
        "journal": journal,
        "news": [],  # Phase 3 (Week 5)
    }
