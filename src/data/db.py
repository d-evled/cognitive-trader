"""SQLite setup and access.

SQLite is the single source of truth for the whole system (see
ARCHITECTURE.md §4). The vector store, added in Week 3, is only a
derived index rebuilt from these tables.
"""
import sqlite3

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT, date TEXT, open REAL, high REAL, low REAL,
    close REAL, volume INTEGER,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    date TEXT, ticker TEXT, rule_name TEXT,
    direction TEXT,
    context_json TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY,
    signal_id INTEGER REFERENCES signals(id),
    date TEXT, verdict TEXT,
    size_pct REAL, confidence REAL,
    reasoning TEXT, citations_json TEXT,
    model TEXT, prompt_version TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    decision_id INTEGER REFERENCES decisions(id),
    ticker TEXT, direction TEXT,
    entry_date TEXT, entry_price REAL, qty REAL,
    stop_price REAL, target_price REAL,
    exit_date TEXT, exit_price REAL, exit_reason TEXT,
    pnl REAL, pnl_pct REAL,
    status TEXT
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY,
    trade_id INTEGER REFERENCES trades(id),
    date TEXT, kind TEXT, text TEXT,
    embedded INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY,
    date TEXT, ticker TEXT, source TEXT, url TEXT,
    headline TEXT, summary TEXT,
    embedded INTEGER DEFAULT 0
);
"""


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["ticker"]
    conn.executescript(SCHEMA)  # idempotent thanks to IF NOT EXISTS
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive, idempotent schema tweaks. Week 5 stores the full retrieval
    bundle with each decision so the dashboard can render exactly what the
    model saw (ARCHITECTURE §5.4)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(decisions)")}
    if "bundle_json" not in cols:
        conn.execute("ALTER TABLE decisions ADD COLUMN bundle_json TEXT")
        conn.commit()


def upsert_prices(conn: sqlite3.Connection, ticker: str, df: pd.DataFrame) -> int:
    """Insert-or-replace daily bars. Safe to call twice with the same data,
    which is what makes the daily ingest idempotent.

    Expects a DataFrame indexed by date with columns open/high/low/close/volume.
    """
    rows = [
        (ticker, idx.strftime("%Y-%m-%d"),
         float(r["open"]), float(r["high"]), float(r["low"]),
         float(r["close"]), int(r["volume"]))
        for idx, r in df.iterrows()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return len(rows)


def load_history(conn: sqlite3.Connection, ticker: str) -> pd.DataFrame:
    """All stored bars for a ticker, oldest first, date-indexed."""
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM prices "
        "WHERE ticker = ? ORDER BY date",
        conn, params=(ticker,), index_col="date", parse_dates=["date"],
    )
    return df


def record_signal(conn: sqlite3.Connection, date: str, ticker: str,
                  rule_name: str, direction: str, context_json: str) -> int:
    cur = conn.execute(
        "INSERT INTO signals (date, ticker, rule_name, direction, context_json) "
        "VALUES (?,?,?,?,?)",
        (date, ticker, rule_name, direction, context_json),
    )
    conn.commit()
    return cur.lastrowid


# --------------------------------------------------------------------------
# Trade lifecycle (Week 2). Every trade hangs off a decision, and every
# decision off a signal — so a filled order can always be traced back to
# the rule that fired. In rules-only mode the "decision" row is a stand-in
# (model='rules-only'); Week 4 swaps in real LLM verdicts, same shape.
# --------------------------------------------------------------------------

def record_decision(conn: sqlite3.Connection, signal_id: int, date: str,
                    verdict: str, size_pct: float, reasoning: str, model: str,
                    confidence: float | None = None,
                    citations_json: str | None = None,
                    prompt_version: str | None = None,
                    bundle_json: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO decisions (signal_id, date, verdict, size_pct, confidence,"
        " reasoning, citations_json, model, prompt_version, bundle_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (signal_id, date, verdict, size_pct, confidence,
         reasoning, citations_json, model, prompt_version, bundle_json),
    )
    conn.commit()
    return cur.lastrowid


def record_trade(conn: sqlite3.Connection, decision_id: int, candidate,
                 qty: float, entry_date: str,
                 entry_price: float | None = None) -> int:
    """Open a trade row. entry_price defaults to the signal close; pass the
    actual fill price once known (fills happen at next open)."""
    cur = conn.execute(
        "INSERT INTO trades (decision_id, ticker, direction, entry_date,"
        " entry_price, qty, stop_price, target_price, status)"
        " VALUES (?,?,?,?,?,?,?,?, 'open')",
        (decision_id, candidate.ticker, candidate.direction, entry_date,
         entry_price if entry_price is not None else candidate.entry_price,
         qty, candidate.stop_price, candidate.target_price),
    )
    conn.commit()
    return cur.lastrowid


def open_trades(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Open trades joined back to the rule that produced them (the journal
    post-mortem wants the rule name)."""
    return conn.execute(
        "SELECT t.*, s.rule_name FROM trades t"
        " JOIN decisions d ON t.decision_id = d.id"
        " JOIN signals s ON d.signal_id = s.id"
        " WHERE t.status = 'open'"
    ).fetchall()


def close_trade(conn: sqlite3.Connection, trade_id: int, exit_date: str,
                exit_price: float, exit_reason: str) -> None:
    row = conn.execute(
        "SELECT entry_price, qty FROM trades WHERE id = ?", (trade_id,)).fetchone()
    pnl = (exit_price - row["entry_price"]) * row["qty"]
    pnl_pct = 100 * (exit_price / row["entry_price"] - 1)
    conn.execute(
        "UPDATE trades SET exit_date=?, exit_price=?, exit_reason=?,"
        " pnl=?, pnl_pct=?, status='closed' WHERE id=?",
        (exit_date, exit_price, exit_reason, pnl, pnl_pct, trade_id),
    )
    conn.commit()


def trading_days_between(conn: sqlite3.Connection, start_date: str,
                         end_date: str) -> int:
    """Trading days strictly after start_date up to and including end_date,
    using SPY's stored bars as the market calendar (SPY is always in the
    universe, so its dates ARE the trading days we know about)."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM prices"
        " WHERE ticker='SPY' AND date > ? AND date <= ?",
        (start_date, end_date),
    ).fetchone()
    return row["n"]


def add_journal_row(conn: sqlite3.Connection, trade_id: int | None, date: str,
                    kind: str, text: str) -> int:
    """embedded stays 0 — Week 3's sync job embeds these rows into Chroma."""
    cur = conn.execute(
        "INSERT INTO journal_entries (trade_id, date, kind, text) VALUES (?,?,?,?)",
        (trade_id, date, kind, text),
    )
    conn.commit()
    return cur.lastrowid
