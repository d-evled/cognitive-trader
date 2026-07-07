"""The vector store: local embeddings + Chroma, wrapped behind the query
methods the retriever expects.

Design (ARCHITECTURE.md §5):
  * Embeddings are computed locally with sentence-transformers
    (all-MiniLM-L6-v2) — free, CPU-only, good for short text. We compute
    them ourselves and hand vectors to Chroma, so nothing phones home.
  * Chroma is a PERSISTENT but DERIVED index: SQLite is the source of
    truth, and scripts/rebuild_index.py can regenerate this whole store.
  * The no-lookahead guarantee lives here: setup cards store their date as
    an integer ordinal (YYYYMMDD) so a query can filter `date_ord <= cutoff`
    numerically. Chroma's range operators only work on numbers, which is
    exactly why we store the ordinal rather than the ISO string.

This class is the real implementation of the `store` the retriever takes;
tests inject a fake with the same query_setups / query_journal surface.
"""
from dataclasses import dataclass

import chromadb
from sentence_transformers import SentenceTransformer


def date_ord(date: str) -> int:
    """'2026-07-06' -> 20260706. Chronological order is preserved as an int,
    which lets Chroma do numeric <= filtering for the no-lookahead cutoff."""
    return int(date.replace("-", ""))


@dataclass
class Hit:
    id: str
    text: str
    metadata: dict
    distance: float


class KnowledgeBase:
    def __init__(self, chroma_path: str, model_name: str = "all-MiniLM-L6-v2"):
        self.client = chromadb.PersistentClient(path=chroma_path)
        self._model_name = model_name
        self._model = None  # lazy: loading weights takes a few seconds
        # We pass our own embeddings, so Chroma needs no embedding function.
        self.setups = self.client.get_or_create_collection(
            "setups", metadata={"hnsw:space": "cosine"})
        self.journal = self.client.get_or_create_collection(
            "journal", metadata={"hnsw:space": "cosine"})
        self.news = self.client.get_or_create_collection(
            "news", metadata={"hnsw:space": "cosine"})

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()

    # --- writes -----------------------------------------------------------

    def add_setups(self, ids: list[str], texts: list[str],
                   metadatas: list[dict]) -> None:
        """Upsert setup cards. Each metadata must carry a 'date' (ISO); we
        derive the integer 'date_ord' used for the no-lookahead filter."""
        if not ids:
            return
        for md in metadatas:
            md["date_ord"] = date_ord(md["date"])
        self.setups.upsert(ids=ids, documents=texts,
                           embeddings=self.embed(texts), metadatas=metadatas)

    def add_journal(self, ids: list[str], texts: list[str],
                    metadatas: list[dict]) -> None:
        if not ids:
            return
        self.journal.upsert(ids=ids, documents=texts,
                            embeddings=self.embed(texts), metadatas=metadatas)

    # --- reads (the retriever's `store` interface) ------------------------

    def _to_hits(self, res: dict) -> list[Hit]:
        # Chroma returns parallel lists nested one level (single query).
        ids = res["ids"][0]
        docs = res["documents"][0]
        metas = res["metadatas"][0]
        dists = res["distances"][0]
        return [Hit(i, d, m, dist) for i, d, m, dist in zip(ids, docs, metas, dists)]

    def query_setups(self, text: str, as_of_date: str, k: int) -> list[Hit]:
        """k nearest setup cards dated on or before as_of_date (no lookahead)."""
        res = self.setups.query(
            query_embeddings=self.embed([text]),
            n_results=k,
            where={"date_ord": {"$lte": date_ord(as_of_date)}},
        )
        return self._to_hits(res)

    def query_journal(self, text: str, rule_name: str, k: int) -> list[Hit]:
        """k similar journal entries, preferring the same rule. Falls back to
        an unfiltered search when there's no same-rule history yet (early on,
        the journal is sparse — ARCHITECTURE.md §5.4)."""
        res = self.journal.query(
            query_embeddings=self.embed([text]), n_results=k,
            where={"rule_name": rule_name})
        hits = self._to_hits(res)
        if not hits:
            res = self.journal.query(query_embeddings=self.embed([text]), n_results=k)
            hits = self._to_hits(res)
        return hits
