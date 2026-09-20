"""Versioned cosine Chroma index; all application operations require ownership."""
import hashlib
import json
import threading
from pathlib import Path
from config import settings, get_embedding_config
from services.workers import run_blocking
from services.quantum_search import normalized_matrix


class VectorStore:
    def __init__(self, db_path=None):
        self.db_path = str(settings.path(db_path or settings.CHROMA_DB_PATH) / 'v2')
        config = {**get_embedding_config(), 'chunk_tokens': settings.CHUNK_TOKENS,
                  'overlap_tokens': settings.CHUNK_OVERLAP_TOKENS, 'metric': 'cosine', 'version': 2}
        self.provenance = json.dumps(config, sort_keys=True)
        version = hashlib.sha256(self.provenance.encode()).hexdigest()[:12]
        self.collection_name = settings.CHROMA_COLLECTION_NAME[:40] + '_v2_' + version
        self.client = self.collection = None
        self._lock = threading.RLock()

    def _initialize(self):
        import chromadb
        from chromadb.config import Settings
        with self._lock:
            if self.collection is not None:
                return
            Path(self.db_path).mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=self.db_path,
                settings=Settings(anonymized_telemetry=False, allow_reset=False))
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name, embedding_function=None,
                metadata={'hnsw:space': 'cosine', 'provenance': self.provenance})
            if (self.collection.metadata or {}).get('provenance') != self.provenance:
                raise ValueError('Collection provenance mismatch; use a new versioned index')
            if self.collection.metadata.get('hnsw:space') != 'cosine':
                raise ValueError('Collection must explicitly use cosine distance')

    async def initialize(self):
        await run_blocking(self._initialize)

    @staticmethod
    def _build_chroma_where(metadata=None, session_id=None, user_id=None):
        clauses = []
        for key, value in (metadata or {}).items():
            if key.startswith('$') or key in {'user_id', 'session_id'}:
                raise ValueError('Only ordinary non-scope metadata filters are accepted')
            if value is not None:
                clauses.append({key: str(value)})
        if session_id is not None:
            clauses.append({'session_id': str(session_id)})
        if user_id is not None:
            clauses.append({'user_id': str(user_id)})
        return None if not clauses else clauses[0] if len(clauses) == 1 else {'$and': clauses}

    @staticmethod
    def _owner(user_id):
        if user_id is None or not str(user_id).isascii() or not str(user_id).isdecimal():
            raise ValueError('Authenticated owner scope is required')

    async def add_documents(self, chunks, *, user_id, session_id):
        self._owner(user_id)
        if not session_id:
            raise ValueError('Session scope is required')
        await self.initialize()
        if not chunks:
            raise ValueError('No chunks to index')
        vectors = normalized_matrix([x['embedding'] for x in chunks], settings.EMBEDDING_DIMENSION).tolist()
        for chunk in chunks:
            metadata = chunk['metadata']
            if metadata.get('embedding_revision') != settings.HUGGINGFACE_REVISION:
                raise ValueError('Embedding revision mismatch')
        def write():
            with self._lock:
                for offset in range(0, len(chunks), 128):
                    batch = chunks[offset:offset+128]
                    metadata = [{**{k: str(v) for k, v in x['metadata'].items() if v is not None},
                                 'user_id': str(user_id), 'session_id': str(session_id)} for x in batch]
                    # Scope is part of the vector ID even when contents are identical.
                    ids = [hashlib.sha256(f"{user_id}:{session_id}:{x['id']}".encode()).hexdigest() for x in batch]
                    self.collection.upsert(ids=ids, embeddings=vectors[offset:offset+128],
                        documents=[x['text'] for x in batch], metadatas=metadata)
        await run_blocking(write)
        return {'success': True, 'added_count': len(chunks)}

    @staticmethod
    def _rows(result):
        return [{'id': str(identifier), 'document': result['documents'][i],
                 'embedding': result['embeddings'][i], 'metadata': result['metadatas'][i] or {}}
                for i, identifier in enumerate(result['ids'])]

    async def get_all_embeddings(self, session_id=None, user_id=None, metadata=None):
        self._owner(user_id)
        await self.initialize()
        where = self._build_chroma_where(metadata, session_id, user_id)
        def read():
            rows, offset = [], 0
            while True:
                page = self.collection.get(where=where, limit=500, offset=offset,
                                            include=['embeddings', 'documents', 'metadatas'])
                rows.extend(self._rows(page))
                if len(page['ids']) < 500:
                    return rows
                offset += 500
        return await run_blocking(read)

    async def candidates(self, query_embedding, *, user_id, session_id, limit=64, metadata=None):
        self._owner(user_id)
        if not session_id:
            raise ValueError('Session scope is required')
        await self.initialize()
        query = normalized_matrix([query_embedding], settings.EMBEDDING_DIMENSION)[0].tolist()
        where = self._build_chroma_where(metadata, session_id, user_id)
        def read():
            total = self.collection.count()
            if not total:
                return []
            result = self.collection.query(query_embeddings=[query], n_results=min(limit, total),
                where=where, include=['embeddings', 'documents', 'metadatas', 'distances'])
            flat = {key: value[0] for key, value in result.items() if value is not None}
            return self._rows(flat)
        return await run_blocking(read)

    async def delete_scope(self, *, user_id, session_id=None, document_id=None):
        self._owner(user_id)
        await self.initialize()
        metadata = {'document_id': document_id} if document_id is not None else None
        where = self._build_chroma_where(metadata, session_id, user_id)
        await run_blocking(self.collection.delete, where=where)

    async def get_collection_stats(self, *, user_id, session_id=None):
        rows = await self.get_all_embeddings(user_id=user_id, session_id=session_id)
        return {'has_data': bool(rows), 'total_chunks': len(rows),
                'total_documents': len({x['metadata'].get('document_id') for x in rows}),
                'metric': 'cosine', 'collection_version': self.collection_name}

    async def close(self):
        # PersistentClient owns its connections for the process lifetime.
        self.collection = None
        self.client = None
