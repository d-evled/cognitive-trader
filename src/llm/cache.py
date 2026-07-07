"""Response cache for LLM vetting decisions.

Keyed on (candidate_hash, prompt_version) so backtest reruns are free and
the daily loop never pays twice for the same candidate under the same
prompt. Only successful, parseable responses are cached (see vetter.py);
errors are left uncached so a later run can retry.
"""
import hashlib
import json
import sqlite3

from src.signals.rules import Candidate

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_cache (
    candidate_hash TEXT, prompt_version TEXT,
    response_json TEXT, model TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (candidate_hash, prompt_version)
);
"""


def candidate_hash(c: Candidate) -> str:
    """Stable hash of a candidate's identity — the fields that define the
    trade the model is judging. Same candidate → same key → cache hit."""
    payload = json.dumps({
        "ticker": c.ticker, "date": c.date, "rule_name": c.rule_name,
        "direction": c.direction, "entry_price": c.entry_price,
        "stop_price": c.stop_price, "target_price": c.target_price,
        "context": c.context,
    }, sort_keys=True, default=float)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class ResponseCache:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(_SCHEMA)

    def get(self, candidate_hash: str, prompt_version: str) -> str | None:
        row = self.conn.execute(
            "SELECT response_json FROM llm_cache "
            "WHERE candidate_hash=? AND prompt_version=?",
            (candidate_hash, prompt_version)).fetchone()
        return row[0] if row else None

    def put(self, candidate_hash: str, prompt_version: str,
            response_json: str, model: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO llm_cache "
            "(candidate_hash, prompt_version, response_json, model) VALUES (?,?,?,?)",
            (candidate_hash, prompt_version, response_json, model))
        self.conn.commit()
