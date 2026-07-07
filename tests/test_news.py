"""Tests for news storage/dedup and its inclusion in the retrieval bundle."""
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.db import get_conn
from src.data.news import store_news_items, sync_news
from src.rag.retriever import build_retrieval_bundle
from src.signals.rules import Candidate


@pytest.fixture
def conn(tmp_path):
    return get_conn(str(tmp_path / "t.db"))


class TestStoreNews:
    def test_stores_items_and_dedupes_by_url(self, conn):
        items = [{"ticker": "AAPL", "date": "2026-07-06", "source": "yf",
                  "url": "http://x/1", "headline": "AAPL up", "summary": "s1"},
                 {"ticker": "AAPL", "date": "2026-07-06", "source": "yf",
                  "url": "http://x/2", "headline": "AAPL down", "summary": "s2"}]
        assert store_news_items(conn, items) == 2
        # re-storing the same urls inserts nothing new
        assert store_news_items(conn, items) == 0
        n = conn.execute("SELECT COUNT(*) AS n FROM news_items").fetchone()["n"]
        assert n == 2

    def test_new_items_land_unembedded(self, conn):
        store_news_items(conn, [{"ticker": "AAPL", "date": "2026-07-06",
                                 "source": "yf", "url": "http://x/1",
                                 "headline": "h", "summary": "s"}])
        row = conn.execute("SELECT embedded FROM news_items").fetchone()
        assert row["embedded"] == 0


@dataclass
class FakeKB:
    added: list = field(default_factory=list)

    def add_news(self, ids, texts, metadatas):
        self.added.append((ids, texts, metadatas))


class TestSyncNews:
    def test_embeds_unembedded_and_marks_them(self, conn):
        store_news_items(conn, [{"ticker": "AAPL", "date": "2026-07-06",
                                 "source": "yf", "url": "http://x/1",
                                 "headline": "AAPL beats earnings", "summary": "big"}])
        kb = FakeKB()
        assert sync_news(conn, kb) == 1
        ids, texts, metas = kb.added[0]
        assert ids[0].startswith("N-")
        assert "AAPL beats earnings" in texts[0]
        assert metas[0]["ticker"] == "AAPL"
        assert sync_news(conn, FakeKB()) == 0   # idempotent


@dataclass
class Hit:
    id: str
    text: str
    metadata: dict
    distance: float = 0.1


@dataclass
class NewsStore:
    news: list = field(default_factory=list)
    seen: dict = field(default_factory=dict)

    def query_setups(self, text, as_of_date, k):
        return []

    def query_journal(self, text, rule_name, k):
        return []

    def query_news(self, text, ticker, as_of_date, k):
        self.seen["news"] = (ticker, as_of_date)
        return self.news[:k]


class TestBundleNews:
    def test_bundle_includes_ticker_filtered_news(self):
        store = NewsStore(news=[Hit("N-1", "AAPL beats", {"ticker": "AAPL"})])
        c = Candidate(ticker="AAPL", date="2026-07-06", rule_name="breakout",
                      direction="long", entry_price=1, stop_price=1, target_price=1)
        bundle = build_retrieval_bundle(c, store)
        assert len(bundle["news"]) == 1
        assert store.seen["news"] == ("AAPL", "2026-07-06")  # ticker + no-lookahead
