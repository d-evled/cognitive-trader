"""Sync journal rows from SQLite into the Chroma `journal` collection.

Journal entries are written to SQLite first (source of truth) with
embedded=0. This job embeds the un-synced ones and flips the flag, so the
retrieval layer can surface them as evidence. It's idempotent: rows are
only embedded once, and re-running does nothing until new entries appear.

Each entry's metadata carries the rule that produced the trade (for the
same-rule retrieval filter), the ticker, kind, date, and — for exits — the
outcome and P&L, so retrieved journal evidence can be filtered and shown
with its result. Chroma rejects null metadata, so None values are dropped.
"""
import sqlite3


def _clean(md: dict) -> dict:
    return {k: v for k, v in md.items() if v is not None}


def sync_journal(conn: sqlite3.Connection, kb) -> int:
    """Embed every journal_entries row with embedded=0. Returns how many."""
    rows = conn.execute(
        "SELECT je.id, je.trade_id, je.date, je.kind, je.text,"
        "       t.ticker, t.pnl_pct, t.exit_reason, s.rule_name"
        "  FROM journal_entries je"
        "  LEFT JOIN trades t   ON je.trade_id = t.id"
        "  LEFT JOIN decisions d ON t.decision_id = d.id"
        "  LEFT JOIN signals s   ON d.signal_id = s.id"
        " WHERE je.embedded = 0"
    ).fetchall()
    if not rows:
        return 0

    ids, texts, metadatas = [], [], []
    for r in rows:
        ids.append(f"J-{r['id']}")
        texts.append(r["text"])
        md = {
            "kind": r["kind"],
            "date": r["date"],
            "ticker": r["ticker"],
            "rule_name": r["rule_name"],
            "exit_reason": r["exit_reason"],
            "pnl_pct": r["pnl_pct"],
        }
        if r["kind"] == "exit" and r["pnl_pct"] is not None:
            md["outcome"] = "win" if r["pnl_pct"] >= 0 else "loss"
        metadatas.append(_clean(md))

    kb.add_journal(ids, texts, metadatas)

    conn.executemany(
        "UPDATE journal_entries SET embedded=1 WHERE id=?",
        [(int(i.split("-", 1)[1]),) for i in ids],
    )
    conn.commit()
    return len(ids)
