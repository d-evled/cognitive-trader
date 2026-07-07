"""Backtest engine — pure simulation and reporting.

`simulate_trade` replays a bracket order bar-by-bar over the days that
followed a signal: entry fills at the next open, then each bar is checked
for a stop or target touch, with a 20-day time stop as the backstop. When a
bar spans both stop and target we assume the stop hit first — the honest,
conservative choice, since we can't see intraday order.

`summary_stats` turns a list of closed trades into the headline report:
win rate, average win/loss, total return, max drawdown, per-rule breakdown.

Neither function looks at anything the decision didn't already have —
lookahead is prevented upstream in the replay loop (retrieval is date
filtered); here we're only simulating the outcome of an already-made trade.
"""
from dataclasses import dataclass


@dataclass
class ExitResult:
    entry_fill: float
    exit_price: float
    reason: str        # 'stop' | 'target' | 'time'
    hold_days: int
    exit_date: str


def simulate_trade(future_bars: list[dict], stop_price: float,
                   target_price: float, time_stop_days: int) -> ExitResult:
    """Simulate a long bracket over `future_bars` (each: date/open/high/low/
    close), the bars from the day after the signal onward. The entry fills
    at future_bars[0]['open']."""
    entry_fill = float(future_bars[0]["open"])
    last = min(len(future_bars), time_stop_days)

    for i in range(last):
        b = future_bars[i]
        hit_stop = b["low"] <= stop_price
        hit_target = b["high"] >= target_price
        if hit_stop:  # stop checked first — conservative on same-bar ties
            return ExitResult(entry_fill, stop_price, "stop", i + 1, b["date"])
        if hit_target:
            return ExitResult(entry_fill, target_price, "target", i + 1, b["date"])

    # No stop/target within the window (or data ran out): exit at the close
    # of the last bar we held.
    b = future_bars[last - 1]
    return ExitResult(entry_fill, float(b["close"]), "time", last, b["date"])


def summary_stats(trades: list[dict], starting_equity: float) -> dict:
    """Aggregate closed trades (each with pnl, pnl_pct, rule_name) into the
    report. Order matters for the equity curve and drawdown."""
    n = len(trades)
    equity = starting_equity + sum(t["pnl"] for t in trades)
    if n == 0:
        return {"n": 0, "wins": 0, "losses": 0, "win_rate": None,
                "avg_win_pct": None, "avg_loss_pct": None,
                "total_return_pct": 0.0, "final_equity": starting_equity,
                "max_drawdown_pct": 0.0, "per_rule": {}}

    wins = [t for t in trades if t["pnl"] >= 0]
    losses = [t for t in trades if t["pnl"] < 0]

    # Equity curve + max peak-to-trough drawdown.
    curve, e, peak, max_dd = [], starting_equity, starting_equity, 0.0
    for t in trades:
        e += t["pnl"]
        curve.append(e)
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak)

    per_rule = {}
    for t in trades:
        r = per_rule.setdefault(t["rule_name"], {"n": 0, "wins": 0})
        r["n"] += 1
        r["wins"] += 1 if t["pnl"] >= 0 else 0
    for r in per_rule.values():
        r["win_rate"] = round(100 * r["wins"] / r["n"], 1)

    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(100 * len(wins) / n, 1),
        "avg_win_pct": round(sum(t["pnl_pct"] for t in wins) / len(wins), 3) if wins else None,
        "avg_loss_pct": round(sum(t["pnl_pct"] for t in losses) / len(losses), 3) if losses else None,
        "total_return_pct": round(100 * (equity / starting_equity - 1), 3),
        "final_equity": round(equity, 2),
        "max_drawdown_pct": round(100 * max_dd, 3),
        "per_rule": per_rule,
    }
