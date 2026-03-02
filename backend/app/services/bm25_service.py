"""Traditional BM25 sparse vector service using jieba tokenization.

Produces TF-based sparse vectors keyed by CRC32 hash of tokens.
Qdrant applies IDF weighting at query time via SparseVectorParams(modifier=IDF).
"""

from __future__ import annotations

import logging
import re
import zlib

logger = logging.getLogger(__name__)

# Vocabulary size: hash space is [0, 2^20)
_VOCAB_SIZE = 1_048_576

# Lazy-loaded jieba module
_jieba = None

# ── Default stopwords: ~200 common Chinese + English + punctuation ──
_DEFAULT_STOPWORDS: set[str] = {
    # English stopwords
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "dare", "ought", "used", "it", "its", "i", "me", "my", "we", "our",
    "you", "your", "he", "him", "his", "she", "her", "they", "them",
    "their", "this", "that", "these", "those", "what", "which", "who",
    "whom", "when", "where", "why", "how", "all", "each", "every", "both",
    "few", "more", "most", "other", "some", "such", "no", "not", "only",
    "own", "same", "so", "than", "too", "very", "just", "because",
    "about", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "if", "also", "up", "down",
    # Chinese stopwords
    "\u7684", "\u4e86", "\u5728", "\u662f", "\u6211", "\u6709", "\u548c",
    "\u5c31", "\u4e0d", "\u4eba", "\u90fd", "\u4e00", "\u4e00\u4e2a",
    "\u4e0a", "\u4e5f", "\u5f88", "\u5230", "\u8bf4", "\u8981", "\u53bb",
    "\u4f60", "\u4f1a", "\u7740", "\u6ca1\u6709", "\u770b", "\u597d",
    "\u81ea\u5df1", "\u8fd9", "\u4ed6", "\u5979", "\u4ec0\u4e48",
    "\u90a3", "\u6211\u4eec", "\u4f60\u4eec", "\u4ed6\u4eec",
    "\u5b83", "\u5b83\u4eec", "\u800c", "\u4e3a", "\u4e0e", "\u6216",
    "\u5176", "\u53ca", "\u5f88", "\u6bd4", "\u6700", "\u66f4",
    "\u5df2", "\u5df2\u7ecf", "\u8fd8", "\u53c8", "\u624d",
    "\u5374", "\u5e76", "\u7136\u540e", "\u4f46", "\u4f46\u662f",
    "\u56e0\u4e3a", "\u6240\u4ee5", "\u5982\u679c", "\u867d\u7136",
    "\u8fd8\u662f", "\u53ea", "\u53ea\u662f", "\u6b63\u5728",
    "\u8fc7", "\u8d77\u6765", "\u8fdb\u884c", "\u4e4b", "\u4ece",
    "\u5f53", "\u5bf9", "\u4ee5", "\u5c06", "\u628a",
    "\u88ab", "\u7ed9", "\u6bcf", "\u4e0b", "\u91cc",
    "\u5916", "\u524d", "\u540e", "\u95f4", "\u4e2d",
    "\u591a", "\u5c11", "\u5927", "\u5c0f", "\u65b0",
    "\u65e7", "\u597d", "\u574f", "\u9ad8", "\u4f4e",
    "\u957f", "\u77ed", "\u5feb", "\u6162",
    # Punctuation & symbols
    "\uff0c", "\u3002", "\uff01", "\uff1f", "\uff1b", "\uff1a",
    "\u2018", "\u2019", "\u201c", "\u201d", "\u3001", "\uff08",
    "\uff09", "\u3010", "\u3011", "\u300a", "\u300b", "\u2014",
    "\u2026", "\u00b7",
    ",", ".", "!", "?", ";", ":", "'", "\"", "(", ")", "[", "]",
    "{", "}", "<", ">", "/", "\\", "|", "-", "_", "+", "=", "*",
    "&", "^", "%", "$", "#", "@", "~", "`",
}

# Regex for splitting English tokens (letters/digits sequences)
_EN_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def _ensure_jieba():
    """Lazy-load jieba to avoid import overhead when not needed."""
    global _jieba
    if _jieba is None:
        import jieba
        jieba.setLogLevel(logging.WARNING)
        _jieba = jieba
    return _jieba


class BM25Service:
    """Generates TF-based sparse vectors for traditional BM25 retrieval.

    Uses jieba for Chinese segmentation and CRC32 hashing for token indices.
    Qdrant applies IDF weighting server-side via SparseVectorParams(modifier=IDF).
    """

    def __init__(
        self,
        vocab_size: int = _VOCAB_SIZE,
        stopwords: set[str] | None = None,
    ):
        self._vocab_size = vocab_size
        self._stopwords = stopwords if stopwords is not None else _DEFAULT_STOPWORDS

    def tokenize(self, text: str) -> list[str]:
        """Segment text into tokens using jieba, filtering stopwords and punctuation."""
        if not text or not text.strip():
            return []

        jieba = _ensure_jieba()
        raw_tokens = jieba.lcut(text)

        tokens = []
        for token in raw_tokens:
            token = token.strip()
            if not token:
                continue
            # Skip pure whitespace / single punctuation
            if len(token) == 1 and not (token.isalnum() or ord(token) > 0x4E00):
                continue
            # For multi-char tokens that are purely punctuation/symbols, skip
            if all(c in _DEFAULT_STOPWORDS or not (c.isalnum() or ord(c) > 0x2E80) for c in token):
                if token in self._stopwords:
                    continue
            # Lowercase for English
            token_lower = token.lower()
            if token_lower in self._stopwords:
                continue
            tokens.append(token_lower)

        return tokens

    def _hash_token(self, token: str) -> int:
        """Hash a token to an index in [0, vocab_size) using CRC32."""
        return zlib.crc32(token.encode("utf-8")) % self._vocab_size

    def text_to_sparse_vector(self, text: str) -> dict:
        """Convert text to a sparse vector dict with 'indices' and 'values' (TF counts).

        Returns:
            {"indices": [int, ...], "values": [float, ...]} sorted by index.
        """
        tokens = self.tokenize(text)
        if not tokens:
            return {"indices": [], "values": []}

        # Count term frequencies by hash index
        tf: dict[int, float] = {}
        for token in tokens:
            idx = self._hash_token(token)
            tf[idx] = tf.get(idx, 0) + 1.0

        # Sort by index for Qdrant
        sorted_indices = sorted(tf.keys())
        return {
            "indices": sorted_indices,
            "values": [tf[i] for i in sorted_indices],
        }

    def batch_to_sparse_vectors(self, texts: list[str]) -> list[dict]:
        """Convert a batch of texts to sparse vectors."""
        return [self.text_to_sparse_vector(t) for t in texts]
