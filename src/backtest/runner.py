"""The backtest replay loop: walk history day by day through the SAME
pipeline the live loop uses — rules → gates → (vet) → simulated bracket
fills — and collect the resulting trades.

No lookahead: each day's rules see only bars up to that day (indicators are
causal, so pre-enriching the full series and slicing is equivalent), and in
rules+LLM mode the retrieval bundle is date-filtered to that day. The only
place future bars are used is `simulate_trade`, to determine the outcome of
a trade the decision was already committed to — which is legitimate.

`vet_fn(candidate, size_cap) -> decision` injects the judgment stage:
  * None            → rules-only baseline (approve at the gate cap)
  * a real vetter   → rules+LLM (production wires Vetter + retriever + kb)
  * a fake          → tests
A decision has `.verdict` ('approve'/'reject'/...) and `.size_pct`.
"""
from dataclasses import dataclass

from src.backtest.engine import ExitResult, simulate_trade, summary_stats
from src.broker.alpaca_client import shares_for
from src.config import sector_of
from src.data.db import load_history
from src.risk.gates import PortfolioState, apply_gates
from src.signals.indicators import enrich
from src.signals.rules import scan


@dataclass
class OpenPosition:
    ticker: str
    sector: str
    rule_name: str
    entry_date: str
    qty: float
    exit: ExitResult


def _bars_after(enriched, day) -> list[dict]:
    fut = enriched.loc[enriched.index > day]
    return [{"date": idx.strftime("%Y-%m-%d"), "open": float(r["open"]),
             "high": float(r["high"]), "low": float(r["low"]),
             "close": float(r["close"])}
            for idx, r in fut.iterrows()]


def run_backtest(conn, cfg, start_date: str, end_date: str, vet_fn=None):
    risk = cfg["risk"]
    tickers = list(cfg["universe"].keys())

    # Pre-enrich each ticker once (indicators are backward-looking, so a
    # day's slice of the full series equals enriching just that history).
    enriched = {}
    for t in tickers:
        df = load_history(conn, t)
        if len(df) >= cfg["data"]["min_history_rows"]:
            enriched[t] = enrich(df, cfg["indicators"])

    # Trading calendar = SPY's stored dates within the window.
    spy = load_history(conn, "SPY")
    days = [d.strftime("%Y-%m-%d") for d in spy.index
            if start_date <= d.strftime("%Y-%m-%d") <= end_date]

    equity = float(risk["starting_equity"])
    open_positions: list[OpenPosition] = []
    closed: list[dict] = []

    def close_due(day: str):
        nonlocal equity
        still_open = []
        for p in open_positions:
            if p.exit.exit_date <= day:
                pnl = (p.exit.exit_price - p.exit.entry_fill) * p.qty
                pnl_pct = 100 * (p.exit.exit_price / p.exit.entry_fill - 1)
                equity += pnl
                closed.append({
                    "ticker": p.ticker, "rule_name": p.rule_name,
                    "entry_date": p.entry_date, "exit_date": p.exit.exit_date,
                    "exit_reason": p.exit.reason, "hold_days": p.exit.hold_days,
                    "qty": p.qty, "pnl": pnl, "pnl_pct": pnl_pct})
            else:
                still_open.append(p)
        open_positions[:] = still_open

    for day in days:
        close_due(day)  # realize exits before making new decisions

        # Candidates that fire exactly on `day`.
        candidates = []
        for t, edf in enriched.items():
            sl = edf.loc[:day]
            if len(sl) < cfg["data"]["min_history_rows"]:
                continue
            if sl.index[-1].strftime("%Y-%m-%d") != day:
                continue  # no bar for this ticker today
            candidates.extend(scan(t, sl, cfg))
        if not candidates:
            continue

        state = PortfolioState(
            equity=equity,
            open_tickers=[p.ticker for p in open_positions],
            open_sectors=[p.sector for p in open_positions])
        results = apply_gates(candidates, state, cfg, lambda tk: sector_of(cfg, tk))

        for r in results:
            if not r.passed:
                continue
            c = r.candidate
            if vet_fn is None:
                size_pct = r.max_size_pct           # rules-only: size at cap
            else:
                d = vet_fn(c, r.max_size_pct)
                if d.verdict != "approve" or d.size_pct <= 0:
                    continue
                size_pct = min(d.size_pct, r.max_size_pct)

            qty = shares_for(equity, size_pct, c.entry_price)
            if qty < 1:
                continue
            future = _bars_after(enriched[c.ticker], day)
            if not future:
                continue  # signal on the last available bar — can't simulate
            exit_res = simulate_trade(future, c.stop_price, c.target_price,
                                      risk["time_stop_days"])
            open_positions.append(OpenPosition(
                ticker=c.ticker, sector=sector_of(cfg, c.ticker),
                rule_name=c.rule_name, entry_date=day, qty=qty, exit=exit_res))

    # Close anything still open at its computed exit.
    close_due("9999-12-31")
    closed.sort(key=lambda t: t["exit_date"])
    return summary_stats(closed, risk["starting_equity"]), closed
