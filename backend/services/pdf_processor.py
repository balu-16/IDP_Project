"""Deterministic token windows and pinned, normalized CPU embeddings."""
import hashlib
import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from config import settings, get_embedding_config
from services.workers import run_blocking
from services.quantum_search import normalized_matrix


@dataclass
class TextChunk:
    page_content: str
    metadata: dict


class PDFProcessor:
    def __init__(self):
        self.embedding_config = get_embedding_config()
        self.embeddings = None
        self._lock = threading.RLock()
        self._tokenizer = None

    @property
    def processing_version(self):
        spec = {**self.embedding_config, 'chunk_tokens': settings.CHUNK_TOKENS,
                'overlap_tokens': settings.CHUNK_OVERLAP_TOKENS,
                'normalization': 'l2', 'extraction': 'page-native-tesseract-v2',
                'ocr_language': settings.OCR_LANGUAGE}
        return 'v2-' + hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]

    def tokenizer(self):
        with self._lock:
            if self._tokenizer is None:
                from transformers import AutoTokenizer
                self._tokenizer = AutoTokenizer.from_pretrained(
                    self.embedding_config['model'], revision=self.embedding_config['revision'],
                    cache_dir=str(settings.path(settings.MODEL_CACHE_DIR)), use_fast=True,
                    token=settings.HUGGINGFACE_API_KEY)
            return self._tokenizer

    def _initialize_embeddings(self):
        with self._lock:
            if self.embeddings is None:
                import torch
                from sentence_transformers import SentenceTransformer
                torch.set_num_threads(settings.CPU_THREADS)
                self.embeddings = SentenceTransformer(
                    self.embedding_config['model'], revision=self.embedding_config['revision'],
                    cache_folder=str(settings.path(settings.MODEL_CACHE_DIR)), device='cpu',
                    token=settings.HUGGINGFACE_API_KEY)
                if self.embeddings.get_sentence_embedding_dimension() != self.embedding_config['dimension']:
                    raise ValueError('Configured embedding dimension does not match the model')

    @staticmethod
    def _generate_file_hash(file_path):
        with open(file_path, 'rb') as handle:
            return hashlib.file_digest(handle, 'sha256').hexdigest()

    def _extract(self, file_path):
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'services.extract_document', str(Path(file_path).resolve())],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                timeout=settings.DOCUMENT_TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired:
            raise ValueError('Document extraction exceeded the processing timeout') from None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise ValueError('Document extraction failed') from None
        if result.returncode or 'error' in payload:
            raise ValueError(payload.get('error', 'Document extraction failed'))
        payload['metadata'].update({
            'file_hash': self._generate_file_hash(file_path),
            'file_size': Path(file_path).stat().st_size,
            'processing_version': self.processing_version,
            'embedding_model': self.embedding_config['model'],
            'embedding_revision': self.embedding_config['revision'],
            'embedding_dimension': self.embedding_config['dimension']})
        payload['full_text'] = '\n\n'.join(p['text'] for p in payload['page_texts'])
        return payload

    async def extract_text_from_pdf(self, file_path):
        return await run_blocking(self._extract, file_path)

    def split_text(self, text, metadata):
        tokenizer = self.tokenizer()
        offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True,
                            truncation=False)['offset_mapping']
        chunks, start = [], 0
        while start < len(offsets):
            end = min(start+settings.CHUNK_TOKENS, len(offsets))
            left, right = offsets[start][0], offsets[end-1][1]
            content = text[left:right]
            # Retokenizing a substring at a wordpiece boundary can change token count.
            while len(tokenizer.encode(content, add_special_tokens=False)) > settings.CHUNK_TOKENS:
                end -= 1
                right = offsets[end-1][1]
                content = text[left:right]
            if any(c.isalnum() for c in content):
                location = f"{metadata.get('page_number', 0)}:{metadata.get('paragraph_id', '')}:{left}:{right}"
                chunk_id = hashlib.sha256(
                    f"{metadata.get('document_id', metadata.get('file_hash', ''))}:{self.processing_version}:{location}".encode()
                ).hexdigest()
                chunks.append(TextChunk(content, {
                    **metadata, 'chunk_id': chunk_id, 'processing_version': self.processing_version,
                    'page_start': metadata.get('page_number', 0), 'page_end': metadata.get('page_number', 0),
                    'char_start': left, 'char_end': right,
                    'token_start': start, 'token_end': end,
                    'token_count': len(tokenizer.encode(content, add_special_tokens=False))}))
            if end == len(offsets):
                break
            start = max(start+1, end-settings.CHUNK_OVERLAP_TOKENS)
        return chunks

    async def chunk_text(self, text, metadata):
        return await run_blocking(self.split_text, text, metadata)

    def encode(self, texts):
        self._initialize_embeddings()
        tokenizer = self.tokenizer()
        maximum = self.embeddings.max_seq_length
        for text in texts:
            if len(tokenizer.encode(text, add_special_tokens=True, truncation=False)) > maximum:
                raise ValueError(f'Input exceeds the embedding model limit ({maximum} tokens); shorten the query')
        with self._lock:
            vectors = self.embeddings.encode(texts, batch_size=settings.EMBEDDING_BATCH_SIZE,
                normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        return normalized_matrix(vectors, self.embedding_config['dimension']).tolist()

    async def generate_embeddings(self, chunks):
        if not chunks:
            return []
        embeddings = await run_blocking(self.encode, [chunk.page_content for chunk in chunks])
        return [{'id': chunk.metadata['chunk_id'], 'text': chunk.page_content,
                 'embedding': embedding, 'metadata': chunk.metadata}
                for chunk, embedding in zip(chunks, embeddings)]

    async def process_pdf(self, file_path, document_id=None, filename=None):
        start = time.perf_counter()
        extracted = await self.extract_text_from_pdf(file_path)
        extraction_ms = (time.perf_counter()-start)*1000
        metadata = {**extracted['metadata'], 'document_id': document_id or extracted['metadata']['file_hash'],
                    'file_name': filename or Path(file_path).name}
        clock = time.perf_counter()
        chunks = []
        for page in extracted['page_texts']:
            chunks.extend(await self.chunk_text(page['text'], {
                **metadata, **{key: value for key, value in page.items() if key != 'text'}}))
        chunking_ms = (time.perf_counter()-clock)*1000
        clock = time.perf_counter()
        embedded = await self.generate_embeddings(chunks)
        return {'success': True, 'file_metadata': metadata, 'chunks_count': len(chunks),
                'embedded_chunks': embedded, 'processing_time_ms': (time.perf_counter()-start)*1000,
                'timings_ms': {'extraction': extraction_ms, 'chunking': chunking_ms,
                               'embedding': (time.perf_counter()-clock)*1000}}

    async def embed_query(self, query):
        if not query.strip():
            raise ValueError('Query cannot be blank')
        return (await run_blocking(self.encode, [query]))[0]
