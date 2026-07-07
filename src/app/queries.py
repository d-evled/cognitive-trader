"""Data-access layer for the Streamlit app.

Pure SQL over the SQLite source of truth — the pages are thin rendering
over these. Kept separate (and unit-tested) so the joins and the
equity/unrealized math don't hide inside UI callbacks.
"""
import json
import sqlite3


def _latest_close(conn: sqlite3.Connection, ticker: str) -> float | None:
    row = conn.execute(
        "SELECT close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
        (ticker,)).fetchone()
    return float(row["close"]) if row else None


def open_positions(conn: sqlite3.Connection) -> list[dict]:
    """Open trades joined to the rule that produced them, with unrealized
    P&L marked against the latest stored close."""
    rows = conn.execute(
        "SELECT t.*, s.rule_name FROM trades t"
        " JOIN decisions d ON t.decision_id = d.id"
        " JOIN signals s ON d.signal_id = s.id"
        " WHERE t.status = 'open' ORDER BY t.entry_date").fetchall()
    out = []
    for t in rows:
        d = dict(t)
        last = _latest_close(conn, t["ticker"])
        if last is not None and t["entry_price"]:
            d["last_price"] = last
            d["unrealized_pnl"] = round((last - t["entry_price"]) * t["qty"], 2)
            d["unrealized_pct"] = round(100 * (last / t["entry_price"] - 1), 2)
        else:
            d["last_price"] = None
            d["unrealized_pnl"] = None
            d["unrealized_pct"] = None
        out.append(d)
    return out


def recent_decisions(conn: sqlite3.Connection, limit: int = 25) -> list[dict]:
    """Recent vetting decisions (newest first), joined to their signal, with
    citations parsed and the signal's indicator context attached — this is
    what the dashboard expands into the evidence view."""
    rows = conn.execute(
        "SELECT d.*, s.ticker, s.rule_name, s.date AS signal_date, s.context_json"
        " FROM decisions d JOIN signals s ON d.signal_id = s.id"
        " ORDER BY d.id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["citations"] = json.loads(r["citations_json"]) if r["citations_json"] else []
        d["context"] = json.loads(r["context_json"]) if r["context_json"] else {}
        d["bundle"] = json.loads(r["bundle_json"]) if r["bundle_json"] else None
        out.append(d)
    return out


def closed_trades(conn: sqlite3.Connection) -> list[dict]:
    """Closed trades with rule + P&L, oldest exit first (for the equity curve
    and per-rule stats via backtest.engine.summary_stats)."""
    rows = conn.execute(
        "SELECT t.*, s.rule_name FROM trades t"
        " JOIN decisions d ON t.decision_id = d.id"
        " JOIN signals s ON d.signal_id = s.id"
        " WHERE t.status = 'closed' ORDER BY t.exit_date").fetchall()
    return [dict(r) for r in rows]


def equity_curve(conn: sqlite3.Connection, starting_equity: float) -> list[dict]:
    """Running equity after each closed trade, in exit-date order."""
    e = float(starting_equity)
    curve = []
    for t in closed_trades(conn):
        e += t["pnl"] or 0.0
        curve.append({"date": t["exit_date"], "equity": round(e, 2)})
    return curve


def trade_log(conn: sqlite3.Connection) -> list[dict]:
    """Every trade joined to its decision and rule — the trade-log table."""
    rows = conn.execute(
        "SELECT t.*, s.rule_name, d.verdict, d.size_pct, d.confidence, d.model"
        " FROM trades t"
        " JOIN decisions d ON t.decision_id = d.id"
        " JOIN signals s ON d.signal_id = s.id"
        " ORDER BY t.entry_date DESC, t.id DESC").fetchall()
    return [dict(r) for r in rows]
