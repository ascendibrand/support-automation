"""
RAG retrieval using TF-IDF similarity with recency decay.

Score formula: score = tfidf_similarity * exp(-decay * days_old)
  decay = 0.005
  At 90 days: 64% of a fresh score
  At 365 days: 16% of a fresh score

No external embedding dependencies — pure stdlib math + collections.
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import TypedDict


DECAY = 0.005


class KBEntry(TypedDict):
    thread_id: str
    subject: str
    question: str
    answer: str
    replied_at: str


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _compute_tf(tokens: list[str]) -> dict[str, float]:
    counts = Counter(tokens)
    total = len(tokens) or 1
    return {t: c / total for t, c in counts.items()}


def _build_idf(documents: list[list[str]]) -> dict[str, float]:
    n = len(documents)
    df: dict[str, int] = {}
    for doc in documents:
        for term in set(doc):
            df[term] = df.get(term, 0) + 1
    return {term: math.log((n + 1) / (freq + 1)) + 1 for term, freq in df.items()}


def _tfidf_vec(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf = _compute_tf(tokens)
    return {t: tf[t] * idf.get(t, 1.0) for t in tf}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(a[t] * b.get(t, 0.0) for t in a)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _days_old(replied_at: str) -> float:
    dt = datetime.fromisoformat(replied_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(tz=timezone.utc) - dt
    return max(0.0, delta.total_seconds() / 86400)


class RAGRetriever:
    def __init__(self, kb_path: str = "kb.json") -> None:
        if not os.path.exists(kb_path):
            raise FileNotFoundError(
                f"Knowledge base not found: {kb_path}\n"
                "Run 'python scripts/build_kb.py' first."
            )
        with open(kb_path) as f:
            self.entries: list[KBEntry] = json.load(f)

        # Pre-tokenize and build IDF over question+subject text
        self._tokens: list[list[str]] = [
            _tokenize(e["subject"] + " " + e["question"]) for e in self.entries
        ]
        self._idf = _build_idf(self._tokens)
        self._vecs = [_tfidf_vec(toks, self._idf) for toks in self._tokens]

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Return top_k KB entries most relevant to query, with recency decay."""
        query_tokens = _tokenize(query)
        query_vec = _tfidf_vec(query_tokens, self._idf)

        scored = []
        for i, entry in enumerate(self.entries):
            sim = _cosine(query_vec, self._vecs[i])
            days = _days_old(entry["replied_at"])
            score = sim * math.exp(-DECAY * days)
            scored.append((score, i))

        scored.sort(reverse=True)
        results = []
        for score, i in scored[:top_k]:
            if score > 0:
                entry = self.entries[i]
                results.append({
                    "score": round(score, 4),
                    "subject": entry["subject"],
                    "question": entry["question"],
                    "answer": entry["answer"],
                    "replied_at": entry["replied_at"],
                })
        return results


def format_context(results: list[dict]) -> str:
    """Format retrieved results into a prompt context block."""
    if not results:
        return "No relevant past replies found."
    parts = []
    for r in results:
        parts.append(
            f"[Past reply — {r['replied_at'][:10]}, relevance {r['score']}]\n"
            f"Subject: {r['subject']}\n"
            f"Question: {r['question'][:500]}\n"
            f"Our reply: {r['answer']}"
        )
    return "\n\n---\n\n".join(parts)
