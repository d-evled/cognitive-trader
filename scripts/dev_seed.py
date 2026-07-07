"""DEV ONLY: seed the DB with synthetic price data.

Lets you exercise the whole pipeline (rules, gates, run_daily --no-fetch)
without network access or a real backfill. The fake series are built to
make some rules fire: trending walks with engineered pullbacks, breakouts,
and washouts. Never mix this DB with real data — it writes to a separate
file (data/dev_seed.db) unless --db is given.
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import REPO_ROOT, load_config, universe_tickers
from src.data.db import get_conn, upsert_prices


def synthetic_series(seed: int, days: int = 800) -> pd.DataFrame:
    """A plausible daily-bar series: geometric random walk with drift,
    plus an engineered final stretch chosen by seed % 3:
      0 -> uptrend then sharp 4-day pullback that ticks up (trend_pullback bait)
      1 -> tight range then a high-volume pop to new highs (breakout bait)
      2 -> long uptrend then a brutal washout, still above 200d (reversion bait)
    """
    rng = np.random.default_rng(seed)
    drift = rng.uniform(0.0002, 0.0009)
    vol = rng.uniform(0.010, 0.022)
    rets = rng.normal(drift, vol, days)

    shape = seed % 3
    if shape == 0:
        rets[-40:-5] = np.abs(rng.normal(0.004, 0.004, 35))      # grind up
        rets[-5:-1] = -np.abs(rng.normal(0.012, 0.004, 4))       # sharp dip
        rets[-1] = abs(rng.normal(0.008, 0.002))                 # tick up
    elif shape == 1:
        rets[-25:-1] = rng.normal(0.0, 0.004, 24)                # tight range
        rets[-1] = abs(rng.normal(0.03, 0.005))                  # pop
    else:
        rets[-200:-12] = np.abs(rng.normal(0.003, 0.003, 188))   # long grind up
        rets[-12:] = -np.abs(rng.normal(0.011, 0.003, 12))       # washout

    close = 100 * np.exp(np.cumsum(rets))
    spread = np.abs(rng.normal(0.008, 0.003, days))
    high = close * (1 + spread)
    low = close * (1 - spread)
    open_ = np.concatenate([[100.0], close[:-1]]) * (1 + rng.normal(0, 0.003, days))
    volume = rng.integers(2_000_000, 8_000_000, days).astype(float)
    if shape == 1:
        volume[-1] *= 3  # conviction volume on the breakout day

    end = date.today()
    idx = pd.bdate_range(end=end, periods=days)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "dev_seed.db"))
    args = parser.parse_args()

    cfg = load_config()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn(args.db)
    for i, t in enumerate(universe_tickers(cfg)):
        upsert_prices(conn, t, synthetic_series(seed=i))
    print(f"Seeded synthetic data -> {args.db}")
    print("Run against it with:")
    print("  CT_DB_OVERRIDE=" + args.db + " python scripts/run_daily.py --dry-run --no-fetch")


if __name__ == "__main__":
    main()
