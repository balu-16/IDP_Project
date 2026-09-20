"""Validated runtime configuration. Secrets are excluded from experiment manifests."""
import json
from pathlib import Path
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).parent / '.env', extra='ignore')
    APP_NAME: str = 'QubitChat'
    VERSION: str = '2.0.0'
    ENVIRONMENT: str = 'development'
    DEBUG: bool = False
    HOST: str = '0.0.0.0'
    PORT: int = 8000
    ALLOWED_ORIGINS: str = 'http://localhost:5173,http://localhost:8080'
    SUPABASE_URL: str | None = None
    SUPABASE_ANON_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = 'gemini-2.5-flash'
    GENERATION_TIMEOUT_SECONDS: int = Field(default=60, ge=1, le=300)
    HUGGINGFACE_API_KEY: str | None = None
    HUGGINGFACE_MODEL: str = 'sentence-transformers/all-MiniLM-L6-v2'
    HUGGINGFACE_REVISION: str = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
    MODEL_CACHE_DIR: str = './model_cache'
    EMBEDDING_DIMENSION: int = 384
    EMBEDDING_BATCH_SIZE: int = Field(default=8, ge=1, le=128)
    CPU_THREADS: int = Field(default=2, ge=1, le=32)
    CHUNK_TOKENS: int = Field(default=192, ge=16, le=254)
    CHUNK_OVERLAP_TOKENS: int = Field(default=32, ge=0)
    CHROMA_DB_PATH: str = './chroma_db'
    CHROMA_COLLECTION_NAME: str = 'pdf_documents'
    DOCUMENT_STORE_PATH: str = './documents'
    MAX_FILE_SIZE: int = Field(default=10 * 1024 * 1024, ge=1)
    MAX_DOCUMENT_PAGES: int = Field(default=100, ge=1, le=1000)
    MAX_PAGE_PIXELS: int = Field(default=20_000_000, ge=1)
    DOCUMENT_TIMEOUT_SECONDS: int = Field(default=120, ge=1, le=600)
    OCR_LANGUAGE: str = 'eng'
    WORKER_LIMIT: int = Field(default=2, ge=1, le=8)
    QUANTUM_SHOTS: int = Field(default=1024, ge=1, le=100_000)
    QUANTUM_MAX_QUBITS: int = Field(default=10, ge=1, le=18)
    QUANTUM_MAX_ITERATIONS: int = Field(default=64, ge=0, le=1000)
    QUANTUM_BOOST_FACTOR: float = Field(default=2.0, ge=0)
    QUANTUM_SEED: int = Field(default=0, ge=0)
    CANDIDATE_LIMIT: int = Field(default=64, ge=1, le=1024)
    MAX_SEARCH_RESULTS: int = 5
    SIMILARITY_THRESHOLD: float = Field(default=0.5, ge=0, le=1)
    LOG_LEVEL: str = 'INFO'

    @field_validator('DEBUG', mode='before')
    @classmethod
    def normalize_debug(cls, value):
        if isinstance(value, str):
            if value.lower() in {'release', 'prod', 'production', 'off', 'false', '0'}:
                return False
            if value.lower() in {'development', 'dev', 'debug', 'on', 'true', '1'}:
                return True
        return value

    @model_validator(mode='after')
    def validate_processing(self):
        if self.CHUNK_OVERLAP_TOKENS >= self.CHUNK_TOKENS:
            raise ValueError('Chunk overlap must be smaller than chunk size')
        return self

    @property
    def allowed_origins_list(self):
        raw = self.ALLOWED_ORIGINS.strip()
        values = json.loads(raw) if raw.startswith('[') else raw.split(',')
        return sorted({str(x).strip().rstrip('/') for x in values if str(x).strip()})

    def path(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else Path(__file__).parent / path


settings = Settings()


def get_embedding_config():
    return {'service': 'huggingface', 'model': settings.HUGGINGFACE_MODEL,
            'revision': settings.HUGGINGFACE_REVISION, 'dimension': settings.EMBEDDING_DIMENSION}
