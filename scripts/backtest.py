"""Backtest: rules-only vs rules+LLM, side by side (ARCHITECTURE.md §8).

The headline experiment — does retrieval-grounded vetting beat the raw
rules? Rules-only is free and fast (the baseline). rules+LLM adds the
vetting stage on Haiku, cached by (candidate, prompt_version) so reruns
cost nothing. Report both honestly, whichever way it goes.

Usage:
    python scripts/backtest.py                       # rules-only, last ~1yr
    python scripts/backtest.py --start 2024-07-01 --end 2026-06-30
    python scripts/backtest.py --llm                 # add rules+LLM (needs API key + built index)
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.runner import run_backtest
from src.config import load_config
from src.data.db import get_conn, load_history


def _default_window(conn) -> tuple[str, str]:
    spy = load_history(conn, "SPY")
    if spy.empty:
        sys.exit("No SPY data — run scripts/backfill.py first.")
    end = spy.index[-1].date()
    start = end - timedelta(days=365)
    return start.isoformat(), end.isoformat()


def _row(label: str, s: dict) -> str:
    if s["n"] == 0:
        return f"{label:12s}  no trades"
    return (f"{label:12s}  n={s['n']:<4d} win%={s['win_rate']:<5} "
            f"avgW%={s['avg_win_pct']:<6} avgL%={s['avg_loss_pct']:<6} "
            f"ret%={s['total_return_pct']:<7} maxDD%={s['max_drawdown_pct']:<6} "
            f"final=${s['final_equity']:,.0f}")


def _per_rule(s: dict) -> str:
    return ", ".join(f"{r}: {v['n']}@{v['win_rate']}%"
                     for r, v in sorted(s["per_rule"].items())) or "—"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--llm", action="store_true",
                        help="also run rules+LLM (Haiku); needs ANTHROPIC_API_KEY and a built index")
    args = parser.parse_args()

    cfg = load_config()
    conn = get_conn(cfg["data"]["db_path"])
    start = args.start or _default_window(conn)[0]
    end = args.end or _default_window(conn)[1]

    print(f"Backtest window: {start} → {end}\n")

    print("Running rules-only baseline...")
    ro_stats, _ = run_backtest(conn, cfg, start, end, vet_fn=None)

    llm_stats = None
    if args.llm:
        print("Running rules+LLM (Haiku vetting)...")
        import anthropic
        from dotenv import load_dotenv

        from src.config import REPO_ROOT
        from src.llm.pipeline import build_vetter, make_vet_fn
        from src.rag.embedder import KnowledgeBase
        load_dotenv(REPO_ROOT / ".env")  # ANTHROPIC_API_KEY, before the client
        import os
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("--llm needs ANTHROPIC_API_KEY in .env (see .env.example).")
        kb = KnowledgeBase(cfg["data"]["chroma_path"], cfg["rag"]["embedding_model"])
        vetter = build_vetter(cfg, anthropic.Anthropic(), model_key="backtest_model")
        vet_fn = make_vet_fn(kb, vetter, cfg)
        llm_stats, _ = run_backtest(conn, cfg, start, end, vet_fn=vet_fn)

    print(f"\n{'='*92}")
    print("RESULTS")
    print(f"{'-'*92}")
    print(_row("rules-only", ro_stats))
    print(f"{'':14s}per-rule: {_per_rule(ro_stats)}")
    if llm_stats is not None:
        print(_row("rules+LLM", llm_stats))
        print(f"{'':14s}per-rule: {_per_rule(llm_stats)}")
    else:
        print("rules+LLM     (skipped — pass --llm to run the vetting comparison)")
    print(f"{'='*92}")
    print("Decision support, not a profit guarantee. Paper-trade before trusting.")


if __name__ == "__main__":
    main()
