"""One-time historical backfill. Run this first, on your machine:

    python scripts/backfill.py

Pulls ~3 years of daily bars for the whole universe into SQLite.
Takes a couple of minutes; safe to re-run.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config, universe_tickers
from src.data.db import get_conn
from src.data.ingest import backfill


def main() -> None:
    cfg = load_config()
    conn = get_conn(cfg["data"]["db_path"])
    tickers = universe_tickers(cfg)
    print(f"Backfilling {len(tickers)} tickers, {cfg['data']['history_years']}y of daily bars...")
    report = backfill(conn, tickers, cfg["data"]["history_years"])
    for t, n in sorted(report.items()):
        flag = "" if n >= cfg["data"]["min_history_rows"] else "  <-- thin, check ticker"
        print(f"  {t:6s} {n:5d} rows{flag}")
    print(f"Done. DB: {cfg['data']['db_path']}")


if __name__ == "__main__":
    main()
