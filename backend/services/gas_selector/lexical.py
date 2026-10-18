"""BM25 passage scoring, matching the research tokenization and parameters."""
import math
import re
from collections import Counter
import numpy as np

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


class BM25:
    def __init__(self, corpus: dict[str, str], k1: float = 0.9, b: float = 0.4):
        self.doc_ids = list(corpus.keys())
        self.docs = [tokenize(corpus[d]) for d in self.doc_ids]
        self.doc_len = np.array([len(d) for d in self.docs], dtype=float)
        self.avgdl = float(self.doc_len.mean()) if len(self.doc_len) else 1.0
        df: Counter = Counter()
        for d in self.docs:
            for t in set(d):
                df[t] += 1
        n = max(1, len(self.docs))
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tfs = [Counter(d) for d in self.docs]
        self.k1, self.b = k1, b
        self.settings = {"k1": k1, "b": b}

    def scores(self, query: str) -> dict[str, float]:
        qterms = tokenize(query)
        out: dict[str, float] = {}
        for i, did in enumerate(self.doc_ids):
            s = 0.0
            dl = self.doc_len[i]
            tf = self.tfs[i]
            for t in qterms:
                f = tf.get(t, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / denom
            out[did] = s
        return out

