"""Rebuild the Chroma vector store entirely from SQLite.

Chroma is a DERIVED index: SQLite is the source of truth. If the store is
corrupted, the embedding model changes, or the card template is tuned, run
this to regenerate everything — setup cards from price history, and journal
entries from journal_entries. This one script is why sync-drift bugs don't
exist here (ARCHITECTURE.md §4).

Usage:
    python scripts/rebuild_index.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config, universe_tickers
from src.data.db import get_conn, load_history
from src.rag.setup_cards import build_cards
from src.rag.sync import sync_journal
from src.signals.indicators import enrich

BATCH = 500  # embed/upsert in chunks to keep memory flat


def main() -> None:
    cfg = load_config()
    conn = get_conn(cfg["data"]["db_path"])
    tickers = universe_tickers(cfg)

    # Import here so `pytest`/`run_daily --dry-run` don't need the heavy deps.
    from src.rag.embedder import KnowledgeBase

    print("Resetting Chroma collections...")
    client = __import__("chromadb").PersistentClient(path=cfg["data"]["chroma_path"])
    for name in ("setups", "journal", "news"):
        try:
            client.delete_collection(name)
        except Exception:
            pass  # first run: nothing to delete
    kb = KnowledgeBase(cfg["data"]["chroma_path"], cfg["rag"]["embedding_model"])

    # --- setup cards ------------------------------------------------------
    total_cards = 0
    for t in tickers:
        df = load_history(conn, t)
        if len(df) < cfg["data"]["min_history_rows"]:
            continue
        ids, texts, metas = build_cards(t, enrich(df, cfg["indicators"]))
        for s in range(0, len(ids), BATCH):
            kb.add_setups(ids[s:s + BATCH], texts[s:s + BATCH], metas[s:s + BATCH])
        total_cards += len(ids)
        print(f"  {t}: {len(ids)} cards")
    print(f"Setup cards embedded: {total_cards}")

    # --- journal ----------------------------------------------------------
    # Full rebuild: re-embed every journal row, so clear the synced flags.
    conn.execute("UPDATE journal_entries SET embedded=0")
    conn.commit()
    n = sync_journal(conn, kb)
    print(f"Journal entries embedded: {n}")
    print("Done. Chroma index rebuilt from SQLite.")


if __name__ == "__main__":
    main()
