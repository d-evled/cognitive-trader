"""Load config.yaml once and hand it to whoever asks.

The repo root is wherever config.yaml lives, so relative paths in the
config (like the DB path) always resolve correctly no matter which
directory you run a script from.
"""
import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    # Resolve the DB path against the repo root and make sure its folder exists.
    # CT_DB_OVERRIDE lets dev tooling (scripts/dev_seed.py) point at a
    # synthetic-data DB without touching real data.
    db_path = Path(os.environ.get("CT_DB_OVERRIDE") or REPO_ROOT / cfg["data"]["db_path"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg["data"]["db_path"] = str(db_path)
    return cfg


def universe_tickers(cfg: dict) -> list[str]:
    return list(cfg["universe"].keys())


def sector_of(cfg: dict, ticker: str) -> str:
    return cfg["universe"].get(ticker, "unknown")
