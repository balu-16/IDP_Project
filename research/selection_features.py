"""Extract matched candidate features without loading models or datasets here."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from .selection import CandidateFeatures


class FeatureBuilder:
    def __init__(self, vector_space, corpus: dict[str, str]):
        self.space = vector_space
        self.corpus = corpus
        self.rows: dict[str, list[int]] = defaultdict(list)
        if getattr(vector_space, "is_chunked", False):
            self.matrix = vector_space.chunk_matrix
            for index, parent in enumerate(vector_space.chunk_parents):
                self.rows[str(parent)].append(index)
        else:
            self.matrix = vector_space.matrix
            for index, parent in enumerate(vector_space.doc_ids):
                self.rows[str(parent)].append(index)

    def build(self, query: str, candidate_ids: list[str], scores: dict[str, float]) -> CandidateFeatures:
        if not candidate_ids:
            return CandidateFeatures((), [], [])
        q = self.space.query_vec(query)
        vectors, passages, representatives = [], [], []
        chunked = getattr(self.space, "is_chunked", False)
        for did in candidate_ids:
            indices = self.rows.get(did)
            if not indices:
                raise ValueError(f"No embedding rows for candidate {did!r}")
            # np.argmax picks the first row on an exact tie. Original chunk
            # indices are ordered, making the representative deterministic.
            similarities = np.asarray(self.matrix[indices]) @ q
            index = indices[int(np.argmax(similarities))]
            vectors.append(self.matrix[index])
            if chunked:
                texts = getattr(self.space, "chunk_texts", None)
                if texts is None:
                    raise ValueError("Chunked vector space must retain its exact chunk_texts")
                passages.append(texts[index])
                representatives.append(f"{did}::chunk{index}")
            else:
                passages.append(self.corpus[did])
                representatives.append(did)
        return CandidateFeatures(tuple(candidate_ids), [scores[d] for d in candidate_ids],
                                 np.asarray(vectors), tuple(passages), tuple(representatives))


@dataclass
class NeuralReranker:
    """Optional CPU baseline; model loading happens only on explicit construction."""

    model: object
    model_id: str
    revision: str
    batch_size: int = 8

    @classmethod
    def load(cls, model_id: str, revision: str = "main") -> "NeuralReranker":
        from huggingface_hub import snapshot_download
        from sentence_transformers import CrossEncoder

        path = snapshot_download(repo_id=model_id, revision=revision,
                                 allow_patterns=["*.json", "*.txt", "*.safetensors", "pytorch_model.bin", "*.model"],
                                 ignore_patterns=["onnx/*", "openvino/*"])
        from pathlib import Path

        pinned = Path(path).name
        model = CrossEncoder(path, device="cpu", max_length=512, trust_remote_code=False)
        model.model.eval()
        return cls(model, model_id, pinned)

    def rank(self, query: str, features: CandidateFeatures, count: int) -> list[str]:
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("Neural output count must be a positive integer")
        if not features.ids:
            return []
        if not features.passages:
            raise ValueError("Neural baselines require the exact representative passages")
        scores = np.asarray(self.model.predict([(query, p) for p in features.passages],
                                              batch_size=self.batch_size,
                                              show_progress_bar=False), dtype=float).reshape(-1)
        if scores.shape != (len(features.ids),) or not np.isfinite(scores).all():
            raise ValueError("Cross-encoder returned invalid scores")
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], features.ids[i]))[:count]
        return [features.ids[i] for i in order]
