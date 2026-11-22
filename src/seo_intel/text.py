"""Tokens, shingles and sentences for English and Hindi."""
from __future__ import annotations

import re
import unicodedata
import zlib
from typing import List, Set, Tuple

import numpy as np

from seo_intel import config

# Latin words, or Devanagari words with vowel signs
_TOKEN = re.compile(r"[0-9a-zß-ɏ]+|[ऀ-ॣ०-ॿ]+")
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")
_SPACES = re.compile(r"\s+")
_PRIME = 4294967311


def clean(text: str) -> str:
    """Collapse whitespace and normalise Unicode."""
    return _SPACES.sub(" ", unicodedata.normalize("NFC", text)).strip()


def tokenize(text: str) -> List[str]:
    return _TOKEN.findall(unicodedata.normalize("NFC", text).lower())


def token_spans(text: str) -> List[Tuple[str, int, int]]:
    """Tokens with their positions in the text."""
    lowered = text.lower()
    # Lowercasing must not shift positions
    if len(lowered) != len(text):
        return []
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(lowered)]


def sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def shingles(tokens: List[str]) -> Set[int]:
    """Hashed runs of neighbouring tokens."""
    size = config.SHINGLE_TOKENS
    if len(tokens) < size:
        return set()
    return {
        zlib.crc32(" ".join(tokens[i : i + size]).encode("utf-8"))
        for i in range(len(tokens) - size + 1)
    }


def jaccard(a: Set[int], b: Set[int]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class MinHasher:
    """MinHash signatures with seeded hash functions."""

    def __init__(self, seed: int):
        rng = np.random.RandomState(seed)
        count = config.MINHASH_PERMUTATIONS
        self.a = rng.randint(1, 2**31 - 1, size=count).astype(np.uint64)[:, None]
        self.b = rng.randint(0, 2**31 - 1, size=count).astype(np.uint64)[:, None]

    def signature(self, shingle_set: Set[int]) -> np.ndarray:
        values = np.fromiter(sorted(shingle_set), dtype=np.uint64)[None, :]
        return ((self.a * values + self.b) % _PRIME).min(axis=1)
