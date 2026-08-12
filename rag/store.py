"""
Transfer & Conversion Intelligence Platform :: the vector store.

Qdrant, with `:memory:` as the default. That is not a stub -- qdrant-client runs
the same engine in-process, so tests and the local demo exercise the real
retrieval path without a server, and pointing at a running Qdrant is a URL
change. Set TRANSFEROPS_QDRANT=http://localhost:6333 to use the container.

What retrieval is allowed to return is the constrained part. Documents explain
*definitions and how to read things*. They never carry numbers, because a number
that came from a document instead of the metric layer would be a second source of
truth -- which is the whole failure this platform exists to prevent. Numbers come
from governed tools; documents come from here; the assistant keeps them apart.
"""
import os

from . import embedder, knowledge

QDRANT_URL = os.environ.get("TRANSFEROPS_QDRANT", "").strip()


class KnowledgeStore:
    def __init__(self, url=None):
        from qdrant_client import QdrantClient
        url = url if url is not None else QDRANT_URL
        self.client = QdrantClient(url=url) if url else QdrantClient(":memory:")
        self.location = url or ":memory:"
        self._indexed = 0

    def build(self, catalogue_rows):
        """(Re)build every collection from the current catalogue. Idempotent."""
        from qdrant_client.models import Distance, PointStruct, VectorParams

        docs = knowledge.all_documents(catalogue_rows)
        by_collection = {}
        for d in docs:
            by_collection.setdefault(d["collection"], []).append(d)

        for name in knowledge.COLLECTIONS:
            items = by_collection.get(name, [])
            if self.client.collection_exists(name):
                self.client.delete_collection(name)
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=embedder.DIM,
                                            distance=Distance.COSINE))
            if not items:
                continue
            self.client.upsert(
                collection_name=name,
                points=[
                    PointStruct(id=i, vector=embedder.embed(d["text"]), payload=d)
                    for i, d in enumerate(items)
                ])
        self._indexed = len(docs)
        return self._indexed

    def search(self, question, collections=None, limit=3, min_score=0.15):
        """
        Retrieve supporting documents, best first, across collections.

        `min_score` matters: returning the least-bad document for a question the
        corpus has nothing to say about is how a retrieval layer starts inventing
        authority. Below the floor, it returns nothing and the caller abstains.

        Errors are deliberately NOT swallowed here. An earlier version caught
        everything and continued, which turned a removed client method into
        "retrieval silently returns nothing" -- a failure that looks exactly like
        a corpus with no match, and would have shipped as working. The agent
        degrades gracefully one level up, where the failure is visible.
        """
        vector = embedder.embed(question)
        hits = []
        for name in (collections or knowledge.COLLECTIONS):
            if not self.client.collection_exists(name):
                continue
            found = self.client.query_points(
                collection_name=name, query=vector, limit=limit).points
            for h in found:
                if h.score is None or h.score < min_score:
                    continue
                hits.append({
                    "collection": name,
                    "doc_id": h.payload.get("doc_id"),
                    "title": h.payload.get("title"),
                    "text": h.payload.get("text"),
                    "metric_code": h.payload.get("metric_code"),
                    "source": h.payload.get("source"),
                    "score": round(float(h.score), 4),
                })
        return sorted(hits, key=lambda h: h["score"], reverse=True)[:limit]

    def count(self):
        return sum(self.client.count(collection_name=name).count
                   for name in knowledge.COLLECTIONS
                   if self.client.collection_exists(name))
