"""Market data ingest via yfinance.

Both entry points are idempotent: they INSERT OR REPLACE, so running
them twice (or re-running after a partial failure) is always safe.
"""
import sqlite3
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from src.data.db import upsert_prices


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance returns capitalized columns (and sometimes a MultiIndex);
    flatten to the lowercase open/high/low/close/volume our DB expects."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(axis=1, level=1)
    df = df.rename(columns=str.lower)
    return df[["open", "high", "low", "close", "volume"]].dropna()


def fetch_ticker(ticker: str, start: str) -> pd.DataFrame:
    """Daily bars from `start` to today. auto_adjust folds splits/dividends
    into the prices, which is what you want for indicator math."""
    df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
    if df is None or df.empty:
        return pd.DataFrame()
    return _normalize(df)


def backfill(conn: sqlite3.Connection, tickers: list[str], years: int) -> dict:
    """Pull `years` of history for every ticker. Returns {ticker: n_rows}."""
    start = (date.today() - timedelta(days=365 * years)).isoformat()
    report = {}
    for t in tickers:
        df = fetch_ticker(t, start)
        report[t] = upsert_prices(conn, t, df) if not df.empty else 0
    return report


def daily_update(conn: sqlite3.Connection, tickers: list[str]) -> dict:
    """Refresh the last ~10 calendar days for every ticker. Overlap with
    already-stored rows is intentional — REPLACE makes it harmless, and it
    heals any gaps from days the script didn't run."""
    start = (date.today() - timedelta(days=10)).isoformat()
    report = {}
    for t in tickers:
        df = fetch_ticker(t, start)
        report[t] = upsert_prices(conn, t, df) if not df.empty else 0
    return report
