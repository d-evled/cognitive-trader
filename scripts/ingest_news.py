"""Fetch recent headlines for the universe, store them, and embed into the
news collection so they show up in retrieval bundles.

Free (yfinance news). Run it alongside the daily loop, or on its own:
    python scripts/ingest_news.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config, universe_tickers
from src.data.db import get_conn
from src.data.news import fetch_news, store_news_items, sync_news


def main() -> None:
    cfg = load_config()
    conn = get_conn(cfg["data"]["db_path"])
    tickers = universe_tickers(cfg)

    print(f"Fetching news for {len(tickers)} tickers...")
    items = fetch_news(tickers)
    stored = store_news_items(conn, items)
    print(f"Fetched {len(items)} headlines; {stored} new stored.")

    from src.rag.embedder import KnowledgeBase
    kb = KnowledgeBase(cfg["data"]["chroma_path"], cfg["rag"]["embedding_model"])
    embedded = sync_news(conn, kb)
    print(f"Embedded {embedded} news items into the news collection.")


if __name__ == "__main__":
    main()
