"""Simple local policy retrieval (BM25 keyword scoring, no embeddings, no network).

Why not embeddings yet? The brief says to start simple and add them only if the evaluation
shows a real need. This retriever is the baseline: it is fast, explainable and free. Its
weakness is vocabulary mismatch (a customer says "charged twice", the policy says
"duplicate"); a small synonym table covers the common cases, and the evaluation reports
where it still misses.
"""

import logging
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

logger = logging.getLogger(__name__)

STOPWORDS = frozenset(
    """a about after again all also am an and any are as at be because been but by can could did
    do does for from get got had has have hello help hi how i if in into is it its just like me
    more my no not of on one only or our out please she so some still than thank thanks that the
    their them then there these they this to too up us very was we were what when where which who
    why will with would you your t s ve ll re d m is it's since""".split()
)

# Words customers use -> the word the policies use. Applied before stemming.
SYNONYMS = {
    "twice": "duplicate",
    "double": "duplicate",
    "doubled": "duplicate",
    "duplicated": "duplicate",
    "duplicates": "duplicate",
    "lockout": "lock",
    "lockouts": "lock",
    "unlock": "lock",
    "unlocked": "lock",
    "unlocking": "lock",
    "logged": "login",
    "signin": "login",
    "hacked": "unauthorized",
    "hack": "unauthorized",
    "hacker": "unauthorized",
    "stolen": "unauthorized",
    "breach": "unauthorized",
    "breached": "unauthorized",
    "compromised": "unauthorized",
    "unauthorised": "unauthorized",
    "fraud": "unauthorized",
    "fraudulent": "unauthorized",
    "down": "outage",
    "downtime": "outage",
    "outages": "outage",
    "slowness": "slow",
    "laggy": "slow",
    "lag": "slow",
    "cancellation": "cancel",
    "cancelled": "cancel",
    "cancelling": "cancel",
    "canceling": "cancel",
    "download": "export",
    "downloads": "export",
    "exports": "export",
    "deletion": "delete",
    "deleted": "delete",
    "erase": "delete",
    "erasure": "delete",
    "teammate": "member",
    "colleague": "member",
    "mfa": "multifactor",
    "2fa": "multifactor",
    "authenticator": "multifactor",
    "throttled": "limit",
    "limits": "limit",
    "limited": "limit",
    "receipts": "receipt",
    "unrecognized": "unrecognized",
    "unrecognised": "unrecognized",
}

_PHRASES = [
    (re.compile(r"\blog[- ]?in\b"), "login"),
    (re.compile(r"\bsign[- ]?in\b"), "login"),
    (re.compile(r"\btwo[- ]factor\b"), "multifactor"),
    (re.compile(r"\bmulti[- ]factor\b"), "multifactor"),
    (re.compile(r"\be-mail\b"), "email"),
    (re.compile(r"\bdon'?t recogni[sz]e\b"), "unrecognized"),
]


def stem(word: str) -> str:
    """A very small stemmer: enough to match charge/charged/charging, lock/locked/locks."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            if suffix == "s" and word.endswith("ss"):
                break
            word = word[: -len(suffix)]
            break
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    text = text.lower().replace("’", "'")
    for pattern, replacement in _PHRASES:
        text = pattern.sub(replacement, text)
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9]+", text):
        if word in STOPWORDS:
            continue
        word = SYNONYMS.get(word, word)
        word = stem(word)
        if len(word) >= 2:
            tokens.append(word)
    return tokens


@dataclass(frozen=True)
class Passage:
    source_id: str
    title: str
    section: str
    text: str
    score: float = 0.0


def parse_document(source_id: str, markdown: str) -> list[Passage]:
    """Split a policy file into one passage per '## ' section."""
    title = source_id
    section = "Overview"
    buffer: list[str] = []
    passages: list[Passage] = []

    def flush() -> None:
        body = " ".join(line.strip() for line in buffer if line.strip())
        if body:
            passages.append(Passage(source_id, title, section, body))
        buffer.clear()

    for line in markdown.splitlines():
        if line.startswith("## "):
            flush()
            section = line[3:].strip()
        elif line.startswith("# "):
            title = line[2:].strip()
        else:
            buffer.append(line)
    flush()
    return passages


class Retriever:
    """BM25 over policy passages. Build once at startup, search many times."""

    K1 = 1.5
    B = 0.75

    def __init__(self, passages: Sequence[Passage]) -> None:
        self._passages = list(passages)
        self._tokens = [tokenize(f"{p.title} {p.section} {p.text}") for p in self._passages]
        self._lengths = [len(t) for t in self._tokens]
        total = len(self._passages)
        self._avg_len = (sum(self._lengths) / total) if total else 0.0
        doc_freq: Counter[str] = Counter()
        for tokens in self._tokens:
            doc_freq.update(set(tokens))
        self._idf = {
            term: math.log(1 + (total - df + 0.5) / (df + 0.5)) for term, df in doc_freq.items()
        }
        self._counts = [Counter(tokens) for tokens in self._tokens]

    @classmethod
    def from_directory(cls, directory: str | Path) -> "Retriever":
        path = Path(directory)
        passages: list[Passage] = []
        if not path.is_dir():
            logger.warning("knowledge base directory not found: %s", path)
            return cls([])
        for file in sorted(path.glob("*.md")):
            passages.extend(parse_document(file.stem, file.read_text(encoding="utf-8")))
        if not passages:
            logger.warning("knowledge base is empty: %s", path)
        return cls(passages)

    @property
    def passage_count(self) -> int:
        return len(self._passages)

    @property
    def source_ids(self) -> set[str]:
        return {p.source_id for p in self._passages}

    def search(self, query: str, k: int = 3, min_score: float = 0.0) -> list[Passage]:
        """Return up to k passages scoring at least min_score, best first."""
        if not self._passages:
            return []
        query_terms = set(tokenize(query))
        scored: list[Passage] = []
        for index, passage in enumerate(self._passages):
            score = self._score(query_terms, index)
            if score >= min_score and score > 0:
                scored.append(replace(passage, score=round(score, 3)))
        scored.sort(key=lambda p: (-p.score, p.source_id, p.section))
        return scored[:k]

    def _score(self, query_terms: set[str], index: int) -> float:
        counts = self._counts[index]
        length = self._lengths[index] or 1
        total = 0.0
        for term in query_terms:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            norm = frequency + self.K1 * (1 - self.B + self.B * length / (self._avg_len or 1))
            total += self._idf[term] * frequency * (self.K1 + 1) / norm
        return total
