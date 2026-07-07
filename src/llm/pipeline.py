"""Wiring that assembles the vetting stage from its parts.

Kept out of vetter.py so the pure vetter stays free of Chroma/config
imports (and easy to unit-test). These helpers are the glue the daily loop
and the backtester use to get a ready-to-call vetter and a per-candidate
`vet_fn`.
"""
from pathlib import Path

from src.config import REPO_ROOT
from src.llm.cache import ResponseCache
from src.llm.vetter import Vetter, load_prompt
from src.rag.retriever import build_retrieval_bundle


def build_vetter(cfg: dict, client, model_key: str = "daily_model") -> Vetter:
    """Assemble a Vetter from config. `model_key` is 'daily_model' for the
    live loop or 'backtest_model' for bulk backtests. Load .env (for
    ANTHROPIC_API_KEY) BEFORE constructing `client` — the SDK reads the key
    at construction and stores None if it isn't set yet."""
    llm = cfg["llm"]
    prompt_text, version = load_prompt(str(REPO_ROOT / llm["prompt_path"]))
    cache_path = Path(llm["cache_path"])
    if not cache_path.is_absolute():
        cache_path = REPO_ROOT / cache_path
    cache = ResponseCache(str(cache_path))
    return Vetter(client, llm[model_key], prompt_text, version, cache)


def make_vet_fn(kb, vetter: Vetter, cfg: dict):
    """A `vet_fn(candidate, size_cap) -> VetDecision` that retrieves the
    date-filtered bundle and vets it. Used by both the backtester and the
    live loop; the bundle is available on the decision's provenance via
    the vetter's stored prompt_version."""
    def vet_fn(candidate, size_cap: float):
        bundle = build_retrieval_bundle(
            candidate, kb,
            n_setups=cfg["rag"]["n_setups"], n_journal=cfg["rag"]["n_journal"])
        return vetter.vet(candidate, bundle, size_cap)
    return vet_fn
