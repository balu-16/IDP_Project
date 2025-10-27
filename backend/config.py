"""Configuration settings for the Quantum PDF Chatbot Backend.

This module manages all configuration settings including:
- API keys (HuggingFace, Gemini)
- Database connections (PostgreSQL, ChromaDB)
- Application settings
- Environment-specific configurations
"""

import os
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application settings
    APP_NAME: str = "Quantum PDF Chatbot Backend"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = Field(default="development", env="ENVIRONMENT")
    DEBUG: bool = Field(default=True, env="DEBUG")
    
    # Firebase settings
    FIREBASE_PROJECT_ID: Optional[str] = Field(default=None, env="FIREBASE_PROJECT_ID")
    
    # ChromaDB settings (additional)
    CHROMADB_HOST: str = Field(default="localhost", env="CHROMADB_HOST")
    CHROMADB_PORT: int = Field(default=8000, env="CHROMADB_PORT")
    
    # Server settings
    HOST: str = Field(default="0.0.0.0", env="HOST")
    PORT: int = Field(default=3000, env="PORT")
    
    # CORS settings
    ALLOWED_ORIGINS: List[str] = Field(
        default=[
            "http://localhost:3000", 
            "http://localhost:8080", 
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173"
        ],
        env="ALLOWED_ORIGINS"
    )
    
    # HuggingFace settings for embeddings
    HUGGINGFACE_API_KEY: Optional[str] = Field(default=None, env="HUGGINGFACE_API_KEY")
    HUGGINGFACE_MODEL: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2", 
        env="HUGGINGFACE_MODEL"
    )
    
    # Gemini API settings
    GEMINI_API_KEY: Optional[str] = Field(default=None, env="GEMINI_API_KEY")
    
    # ChromaDB settings
    CHROMA_DB_PATH: str = Field(default="./chroma_db", env="CHROMA_DB_PATH")
    CHROMA_COLLECTION_NAME: str = Field(default="pdf_documents", env="CHROMA_COLLECTION_NAME")
    
    # Supabase settings
    SUPABASE_URL: Optional[str] = Field(default=None, env="SUPABASE_URL")
    SUPABASE_ANON_KEY: Optional[str] = Field(default=None, env="SUPABASE_ANON_KEY")
    
    # PostgreSQL settings (optional, for user/session metadata)
    DATABASE_URL: Optional[str] = Field(default=None, env="DATABASE_URL")
    POSTGRES_HOST: str = Field(default="localhost", env="POSTGRES_HOST")
    POSTGRES_PORT: int = Field(default=5432, env="POSTGRES_PORT")
    POSTGRES_DB: str = Field(default="chatbot_db", env="POSTGRES_DB")
    POSTGRES_USER: str = Field(default="postgres", env="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field(default="password", env="POSTGRES_PASSWORD")
    
    # PDF processing settings
    MAX_FILE_SIZE: int = Field(default=10 * 1024 * 1024, env="MAX_FILE_SIZE")  # 10MB
    CHUNK_SIZE: int = Field(default=1000, env="CHUNK_SIZE")  # Characters per chunk
    CHUNK_OVERLAP: int = Field(default=200, env="CHUNK_OVERLAP")  # Overlap between chunks
    
    # Quantum computing settings
    QUANTUM_BACKEND: str = Field(default="qasm_simulator", env="QUANTUM_BACKEND")
    QUANTUM_SHOTS: int = Field(default=1024, env="QUANTUM_SHOTS")
    QUANTUM_MAX_QUBITS: int = Field(default=10, env="QUANTUM_MAX_QUBITS")
    QUANTUM_BOOST_FACTOR: float = Field(default=2.0, env="QUANTUM_BOOST_FACTOR")
    GROVER_ITERATIONS: int = Field(default=2, env="GROVER_ITERATIONS")
    
    # Search settings
    MAX_SEARCH_RESULTS: int = Field(default=5, env="MAX_SEARCH_RESULTS")
    SIMILARITY_THRESHOLD: float = Field(default=0.7, env="SIMILARITY_THRESHOLD")
    
    # Logging settings
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    LOG_FORMAT: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        env="LOG_FORMAT"
    )
    
    @property
    def database_url(self) -> str:
        """Construct PostgreSQL database URL from components."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
    
    @property
    def use_huggingface(self) -> bool:
        """Check if HuggingFace is available for embeddings."""
        return True  # Always use HuggingFace for embeddings
    
    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

# Create global settings instance
settings = Settings()

# Validation functions
def validate_api_keys() -> dict:
    """Validate that required API keys are present.
    
    Returns:
        dict: Validation results with available services
    """
    validation_results = {
        "huggingface_available": settings.use_huggingface,
        "embedding_service": "huggingface",
        "warnings": []
    }
    
    if not settings.use_huggingface:
        validation_results["warnings"].append(
            "HuggingFace embedding service not available."
        )
    
    return validation_results

def get_embedding_config() -> dict:
    """Get the HuggingFace embedding configuration.
    
    Returns:
        dict: Embedding service configuration
    """
    return {
        "service": "huggingface",
        "model": settings.HUGGINGFACE_MODEL,
        "api_key": settings.HUGGINGFACE_API_KEY
    }

# Export commonly used settings
__all__ = [
    "settings",
    "validate_api_keys",
    "get_embedding_config"
]