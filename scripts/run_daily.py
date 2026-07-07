"""The daily loop entrypoint (ARCHITECTURE.md §2).

Week 1 scope: ingest -> rules -> gates -> print. Execution, retrieval,
and vetting are wired in over Weeks 2-4; this script grows, its shape
doesn't change.

Usage:
    python scripts/run_daily.py --dry-run              # fetch fresh data, show candidates
    python scripts/run_daily.py --dry-run --no-fetch   # use data already in the DB
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config, sector_of, universe_tickers
from src.data.db import get_conn, load_history, record_signal
from src.data.ingest import daily_update
from src.risk.gates import PortfolioState, apply_gates
from src.signals.indicators import enrich
from src.signals.rules import scan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would happen; place no orders (Week 1: always on)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip the data pull; scan whatever is already stored")
    args = parser.parse_args()

    cfg = load_config()
    conn = get_conn(cfg["data"]["db_path"])
    tickers = universe_tickers(cfg)

    if not args.no_fetch:
        print("Fetching latest bars...")
        daily_update(conn, tickers)

    # --- Scan every ticker ------------------------------------------------
    candidates = []
    skipped = []
    for t in tickers:
        df = load_history(conn, t)
        if len(df) < cfg["data"]["min_history_rows"]:
            skipped.append(t)
            continue
        candidates.extend(scan(t, enrich(df, cfg["indicators"]), cfg))

    if skipped:
        print(f"Skipped (insufficient history): {', '.join(skipped)}")

    if not candidates:
        print("No rules fired today. That's normal — most days are quiet.")
        return

    # --- Risk gates -------------------------------------------------------
    # Week 2 will read real positions from Alpaca; for now: flat portfolio.
    state = PortfolioState(equity=cfg["risk"]["starting_equity"])
    results = apply_gates(candidates, state, cfg, lambda t: sector_of(cfg, t))

    # --- Report -----------------------------------------------------------
    print(f"\n{'='*74}")
    print(f"{'ticker':7s}{'rule':20s}{'entry':>8s}{'stop':>8s}{'target':>8s}"
          f"{'cap%':>6s}  verdict")
    print(f"{'-'*74}")
    for r in results:
        c = r.candidate
        verdict = f"PASS (max {r.max_size_pct}%)" if r.passed else f"gate: {r.reject_reason}"
        print(f"{c.ticker:7s}{c.rule_name:20s}{c.entry_price:8.2f}{c.stop_price:8.2f}"
              f"{c.target_price:8.2f}{r.max_size_pct:6.1f}  {verdict}")
        record_signal(conn, c.date, c.ticker, c.rule_name, c.direction, c.context_json())
    print(f"{'='*74}")
    print(f"{len(results)} candidate(s); {sum(r.passed for r in results)} passed gates. "
          f"Signals logged to DB.")
    if args.dry_run:
        print("Dry run: no orders placed.")


if __name__ == "__main__":
    main()
