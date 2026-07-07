"""News ingest: yfinance headlines → SQLite → Chroma `news` collection.

Same source-of-truth pattern as everything else: rows land in SQLite first
(deduped by URL, embedded=0), then sync_news embeds the un-synced ones so
the retriever can surface recent, ticker-relevant context in the bundle.
The yfinance fetch is defensive glue (its item shape drifts between
versions); the storage and sync logic is what's unit-tested.
"""
import sqlite3


def store_news_items(conn: sqlite3.Connection, items: list[dict]) -> int:
    """Insert news items, skipping any whose URL is already stored. Returns
    the count actually inserted."""
    inserted = 0
    for it in items:
        if conn.execute("SELECT 1 FROM news_items WHERE url=?",
                        (it["url"],)).fetchone():
            continue
        conn.execute(
            "INSERT INTO news_items (date, ticker, source, url, headline, summary)"
            " VALUES (?,?,?,?,?,?)",
            (it["date"], it["ticker"], it.get("source", ""), it["url"],
             it["headline"], it.get("summary", "")))
        inserted += 1
    conn.commit()
    return inserted


def sync_news(conn: sqlite3.Connection, kb) -> int:
    """Embed every news_items row with embedded=0 into the news collection."""
    rows = conn.execute(
        "SELECT * FROM news_items WHERE embedded = 0").fetchall()
    if not rows:
        return 0
    ids, texts, metadatas = [], [], []
    for r in rows:
        ids.append(f"N-{r['id']}")
        texts.append(f"{r['headline']}. {r['summary'] or ''}".strip())
        metadatas.append({"ticker": r["ticker"], "date": r["date"],
                          "source": r["source"] or ""})
    kb.add_news(ids, texts, metadatas)
    conn.executemany("UPDATE news_items SET embedded=1 WHERE id=?",
                     [(int(i.split("-", 1)[1]),) for i in ids])
    conn.commit()
    return len(ids)


def fetch_news(tickers: list[str], max_per: int = 5) -> list[dict]:
    """Best-effort recent headlines per ticker via yfinance. Tolerant of the
    library's shifting news-item shape; returns a flat list of item dicts."""
    from datetime import datetime, timezone

    import yfinance as yf

    out = []
    for t in tickers:
        try:
            items = yf.Ticker(t).news or []
        except Exception:
            continue
        for n in items[:max_per]:
            content = n.get("content", n) if isinstance(n, dict) else {}
            title = content.get("title") or (n.get("title") if isinstance(n, dict) else None)
            canon = content.get("canonicalUrl")
            url = (canon.get("url") if isinstance(canon, dict) else None) \
                or (n.get("link") if isinstance(n, dict) else None) or title
            ts = n.get("providerPublishTime") if isinstance(n, dict) else None
            date = (datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
                    if ts else datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            summary = content.get("summary") or content.get("description") or ""
            if title and url:
                out.append({"ticker": t, "date": date,
                            "source": (n.get("publisher") if isinstance(n, dict) else "") or "yfinance",
                            "url": url, "headline": title, "summary": summary})
    return out
