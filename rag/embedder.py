"""
Transfer & Conversion Intelligence Platform :: embeddings, with the model kept swappable.

The default is a deterministic hashed bag-of-words vectoriser. That is a real
choice, not a shortcut:

  * it needs no model download and no network, so retrieval is testable in CI and
    the demo runs on a train;
  * it is deterministic, so a retrieval regression is reproducible rather than
    "the model felt different today";
  * and it keeps the honest claim visible -- retrieval quality here is adequate
    for a glossary of ~40 governed documents, and would be swapped for
    sentence-transformers or an API embedder the moment the corpus grew.

Set TRANSFEROPS_EMBEDDER=sentence-transformers to use a real model if it is
installed. Nothing else in the stack changes: the store and retriever only ever
see vectors.
"""
import hashlib
import math
import os
import re

DIM = 384                    # matches all-MiniLM-L6-v2, so swapping is a no-op
MODE = os.environ.get("TRANSFEROPS_EMBEDDER", "hashed").lower()

_TOKEN = re.compile(r"[a-z0-9_]+")

# Stopwords matter more here than in a trained model. Without them, "what is the
# capital of France?" overlaps every document in the corpus on function words
# alone and clears the relevance floor -- retrieval then answers questions the
# knowledge base knows nothing about, which is precisely the behaviour the floor
# exists to prevent. A trained embedder learns to discount these; a hashed one
# has to be told.
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "of", "in", "on", "at", "to", "for", "with", "by", "from", "as", "into",
    "and", "or", "but", "if", "then", "than", "that", "this", "these", "those",
    "it", "its", "we", "our", "you", "your", "i", "me", "my", "they", "their",
    "what", "which", "who", "whom", "how", "why", "when", "where", "does", "do",
    "did", "can", "could", "should", "would", "will", "shall", "may", "might",
    "have", "has", "had", "not", "no", "so", "such", "there", "here", "about",
    "mean", "means", "meaning", "show", "tell", "explain", "give", "get",
}

# Domain terms that carry most of the signal in this corpus. Weighting them is
# the cheap equivalent of what a trained model would learn from the domain.
BOOSTED = {
    "cycle", "time", "schedule", "deviation", "baseline", "forecast", "error",
    "variance", "throughput", "on", "rate", "stage", "milestone", "fiscal",
    "portfolio", "transfer", "completion", "distribution", "horizon", "replan",
    "cancelled", "population", "governed", "metric", "definition",
}

_MODEL = None


def _stem(token):
    """
    Crude plural stripping. Applied to queries and documents alike, so it only
    has to be *consistent*, not linguistically correct -- "status" becoming
    "statu" is harmless when both sides do it. Without this, "which filters can
    I use?" misses a document that says "filter dimensions", which is the kind
    of near-miss that makes a retrieval layer feel unreliable.
    """
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(text):
    return [_stem(t) for t in _TOKEN.findall(text.lower())
            if len(t) > 1 and t not in STOPWORDS]


def _hashed(text):
    """Hashed bag of words with sublinear term weighting, L2-normalised."""
    counts = {}
    for tok in _tokens(text):
        idx = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16) % DIM
        weight = 2.0 if tok in BOOSTED else 1.0
        counts[idx] = counts.get(idx, 0.0) + weight

    vec = [0.0] * DIM
    for idx, raw in counts.items():
        vec[idx] = 1.0 + math.log(raw)          # sublinear: repetition saturates
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _sentence_transformer(text):
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _MODEL.encode(text, normalize_embeddings=True).tolist()


def embed(text):
    if MODE.startswith("sentence"):
        return _sentence_transformer(text)
    return _hashed(text)


def embed_all(texts):
    return [embed(t) for t in texts]
