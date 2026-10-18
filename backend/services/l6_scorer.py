"""Lazy, serialized local inference with explicit token and model boundaries."""
import logging
import threading
import time

import numpy as np

from config import settings
from .gas_profile import L6_MODEL, L6_REVISION

logger = logging.getLogger(__name__)


class L6Unavailable(RuntimeError):
    """The pinned reranker cannot serve a request; never substitute a model."""


class L6Scorer:
    def __init__(self):
        self._lock = threading.RLock()
        self._model = None
        self._activation = None

    def _load(self):
        if self._model is not None:
            return 0.0, 0.0
        begin = time.perf_counter()
        try:
            import torch
            from huggingface_hub import snapshot_download
            from sentence_transformers import CrossEncoder
            # Research caches use the default HF location; standalone application
            # installations may instead place the same pinned model in MODEL_CACHE_DIR.
            path = None
            for cache in (None, str(settings.path(settings.MODEL_CACHE_DIR))):
                try:
                    path = snapshot_download(repo_id=L6_MODEL, revision=L6_REVISION,
                        cache_dir=cache, local_files_only=True,
                        allow_patterns=['*.json', '*.txt', '*.safetensors', 'pytorch_model.bin', '*.model'],
                        ignore_patterns=['onnx/*', 'openvino/*'])
                    break
                except OSError:
                    continue
            if path is None:
                raise OSError('Pinned L6 snapshot is not cached')
            torch.set_num_threads(settings.CPU_THREADS)
            model = CrossEncoder(path, device='cpu', max_length=512, trust_remote_code=False)
            model.model.eval()
            activation = torch.nn.Identity()
            loading_ms = (time.perf_counter() - begin) * 1000
            begin = time.perf_counter()
            model.predict([('A short question.', 'A short source passage.')],
                batch_size=1, show_progress_bar=False, activation_fct=activation)
            warmup_ms = (time.perf_counter() - begin) * 1000
            self._model, self._activation = model, activation
            return loading_ms, warmup_ms
        except Exception as exc:
            logger.warning('Pinned L6 initialization unavailable (%s)', type(exc).__name__)
            raise L6Unavailable('L6-guided GAS is unavailable; the pinned reranker could not load') from None

    def score(self, query, passages):
        if not passages:
            return np.empty(0), {'model_loading_ms': 0.0, 'model_warmup_ms': 0.0,
                                 'l6_queue_ms': 0.0, 'inference_ms': 0.0}
        queued = time.perf_counter()
        with self._lock:
            queue_ms = (time.perf_counter() - queued) * 1000
            loading_ms, warmup_ms = self._load()
            start = time.perf_counter()
            pairs = [(query, passage) for passage in passages]
            try:
                tokens = self._model.tokenizer([query] * len(passages), passages,
                    add_special_tokens=True, truncation=False, padding=False)['input_ids']
                if any(len(ids) > 512 for ids in tokens):
                    raise ValueError('Question and passage exceed the L6 512-token input budget')
                scores = np.asarray(self._model.predict(pairs, batch_size=8,
                    show_progress_bar=False, activation_fct=self._activation), dtype=np.float64).reshape(-1)
                if scores.shape != (len(passages),) or not np.isfinite(scores).all():
                    raise L6Unavailable('The pinned reranker returned invalid scores')
            except ValueError:
                raise
            except Exception as exc:
                logger.warning('Pinned L6 inference unavailable (%s)', type(exc).__name__)
                raise L6Unavailable('L6-guided GAS scoring is temporarily unavailable') from None
            return scores, {'model_loading_ms': loading_ms, 'model_warmup_ms': warmup_ms,
                'l6_queue_ms': queue_ms, 'inference_ms': (time.perf_counter() - start) * 1000}


_scorer = L6Scorer()


def get_l6_scorer():
    return _scorer
