"""The daily loop entrypoint (ARCHITECTURE.md §2).

Week 2 scope: ingest -> reconcile -> rules -> gates -> execute on the
Alpaca paper account (rules-only mode: no LLM yet, so approved = passed
gates, sized at the gate cap). Retrieval and vetting arrive in Weeks 3-4;
this script grows, its shape doesn't change.

Usage:
    python scripts/run_daily.py                 # dry run: show candidates, no orders
    python scripts/run_daily.py --execute       # place real paper orders
    python scripts/run_daily.py --no-fetch      # skip the data pull

Run it each evening after market close. Orders queue for the next open.
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config, sector_of, universe_tickers
from src.data.db import (
    get_conn, load_history, record_decision, record_signal, record_trade,
)
from src.data.ingest import daily_update
from src.journal.journaler import entry_text, write_journal_entry
from src.risk.gates import PortfolioState, apply_gates
from src.signals.indicators import enrich
from src.signals.rules import scan


def connect_broker(require: bool):
    """Real Alpaca paper broker if keys exist; None otherwise (dry runs can
    still work off a flat assumed portfolio)."""
    from src.broker.alpaca_client import AlpacaBroker
    try:
        return AlpacaBroker()
    except RuntimeError as e:
        if require:
            sys.exit(f"Cannot execute: {e}")
        print(f"Note: no broker connection ({e})")
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true",
                        help="place real orders on the Alpaca paper account")
    parser.add_argument("--dry-run", action="store_true",
                        help="(default) show what would happen; place no orders")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip the data pull; scan whatever is already stored")
    args = parser.parse_args()
    executing = args.execute and not args.dry_run

    cfg = load_config()
    conn = get_conn(cfg["data"]["db_path"])
    tickers = universe_tickers(cfg)
    today = date.today().isoformat()

    if not args.no_fetch:
        print("Fetching latest bars...")
        daily_update(conn, tickers)

    # --- Reconcile: sync DB with what actually happened at the broker ------
    broker = connect_broker(require=executing)
    if broker is not None:
        from src.broker.reconcile import reconcile
        for event in reconcile(conn, broker, today,
                               cfg["risk"]["time_stop_days"]):
            print(event)

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

    # --- Risk gates against the REAL portfolio -----------------------------
    if broker is not None:
        positions = broker.open_positions()
        state = PortfolioState(
            equity=broker.equity(),
            open_tickers=[p.ticker for p in positions],
            open_sectors=[sector_of(cfg, p.ticker) for p in positions],
        )
    else:
        state = PortfolioState(equity=cfg["risk"]["starting_equity"])
    results = apply_gates(candidates, state, cfg, lambda t: sector_of(cfg, t))

    # --- Report + log signals ----------------------------------------------
    signal_ids = {}
    print(f"\n{'='*74}")
    print(f"{'ticker':7s}{'rule':20s}{'entry':>8s}{'stop':>8s}{'target':>8s}"
          f"{'cap%':>6s}  verdict")
    print(f"{'-'*74}")
    for r in results:
        c = r.candidate
        verdict = f"PASS (max {r.max_size_pct}%)" if r.passed else f"gate: {r.reject_reason}"
        print(f"{c.ticker:7s}{c.rule_name:20s}{c.entry_price:8.2f}{c.stop_price:8.2f}"
              f"{c.target_price:8.2f}{r.max_size_pct:6.1f}  {verdict}")
        signal_ids[id(c)] = record_signal(
            conn, c.date, c.ticker, c.rule_name, c.direction, c.context_json())
    print(f"{'='*74}")
    print(f"{len(results)} candidate(s); {sum(r.passed for r in results)} passed gates. "
          f"Signals logged to DB.")

    if not executing:
        print("Dry run: no orders placed. Use --execute to trade on paper.")
        return

    # --- Execute (rules-only mode: size at the gate cap) -------------------
    from src.broker.alpaca_client import shares_for
    pending = broker.open_order_tickers()
    for r in results:
        if not r.passed:
            continue
        c = r.candidate
        if c.ticker in pending:
            print(f"SKIP {c.ticker}: an order is already pending for it")
            continue
        qty = shares_for(state.equity, r.max_size_pct, c.entry_price)
        if qty < 1:
            print(f"SKIP {c.ticker}: size cap buys less than one share")
            continue
        order_id = broker.submit_bracket(c.ticker, qty, c.stop_price, c.target_price)
        decision_id = record_decision(
            conn, signal_ids[id(c)], today, verdict="approve",
            size_pct=r.max_size_pct,
            reasoning="rules-only mode (no LLM): passed all risk gates, sized at cap",
            model="rules-only")
        # entry_price = signal close for now; reconcile adopts the actual
        # fill price once the position appears at the broker.
        trade_id = record_trade(conn, decision_id, c, qty=qty, entry_date=today)
        write_journal_entry(conn, trade_id, today, "entry",
                            entry_text(c, qty, r.max_size_pct))
        print(f"ORDER {c.ticker}: bracket buy {qty} @ market "
              f"(stop {c.stop_price}, target {c.target_price}) — Alpaca id {order_id}")


if __name__ == "__main__":
    main()
