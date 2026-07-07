"""Print the retrieval bundle for today's candidate(s).

This is Week 3's done-when check made runnable: for each candidate the rules
fire today, show exactly what evidence the LLM vetting stage (Week 4) will
see — the nearest historic setup cards with forward-return base rates, and
similar journal entries — all correctly date-filtered (no lookahead).

Usage:
    python scripts/rebuild_index.py     # build the index first
    python scripts/show_bundle.py [--no-fetch]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config, universe_tickers
from src.data.db import get_conn, load_history
from src.data.ingest import daily_update
from src.rag.retriever import build_retrieval_bundle
from src.signals.indicators import enrich
from src.signals.rules import scan


def print_bundle(bundle: dict) -> None:
    c = bundle["candidate"]
    print(f"\n{'='*74}")
    print(f"CANDIDATE  {c.ticker}  {c.rule_name}  (entry {c.entry_price}, "
          f"stop {c.stop_price}, target {c.target_price})")
    print(f"query: {bundle['query']}")

    print(f"\n-- similar historic setups (top {len(bundle['setups'])}, "
          f"date-filtered <= {c.date}) --")
    for h in bundle["setups"]:
        fr = h.metadata
        print(f"  [{h.id}] fwd_10d={fr.get('fwd_10d')}%  dist={h.distance:.3f}")
        print(f"      {h.text}")
    stats = bundle["setup_stats"]
    for hz in ("fwd_5d", "fwd_10d", "fwd_20d"):
        s = stats[hz]
        if s["n"]:
            print(f"  base rate {hz}: median {s['median']}%, "
                  f"{s['pct_positive']}% positive over {s['n']} setups")

    print(f"\n-- similar journal entries (top {len(bundle['journal'])}, "
          f"rule={c.rule_name} preferred) --")
    if not bundle["journal"]:
        print("  (journal empty — it fills as trades close)")
    for h in bundle["journal"]:
        print(f"  [{h.id}] {h.metadata.get('outcome','')}: {h.text}")
    print(f"{'='*74}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-fetch", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    conn = get_conn(cfg["data"]["db_path"])
    tickers = universe_tickers(cfg)

    if not args.no_fetch:
        print("Fetching latest bars...")
        daily_update(conn, tickers)

    candidates = []
    for t in tickers:
        df = load_history(conn, t)
        if len(df) < cfg["data"]["min_history_rows"]:
            continue
        candidates.extend(scan(t, enrich(df, cfg["indicators"]), cfg))

    if not candidates:
        print("No rules fired today — nothing to retrieve for.")
        return

    from src.rag.embedder import KnowledgeBase
    kb = KnowledgeBase(cfg["data"]["chroma_path"], cfg["rag"]["embedding_model"])

    for c in candidates:
        print_bundle(build_retrieval_bundle(
            c, kb, n_setups=cfg["rag"]["n_setups"], n_journal=cfg["rag"]["n_journal"]))


if __name__ == "__main__":
    main()
