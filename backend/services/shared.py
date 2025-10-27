"""Shared service instances to prevent multiple initializations.

This module provides singleton instances of services to improve startup performance
by preventing duplicate model loading and database connections.
"""

import logging
from typing import Optional

from .vector_store import VectorStore
from .pdf_processor import PDFProcessor
from .quantum_search import QuantumSearch

logger = logging.getLogger(__name__)

# Global service instances
_vector_store: Optional[VectorStore] = None
_pdf_processor: Optional[PDFProcessor] = None
_quantum_search: Optional[QuantumSearch] = None

def get_vector_store() -> VectorStore:
    """Get the shared VectorStore instance.
    
    Returns:
        VectorStore: Singleton instance
    """
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
        logger.info("Created shared VectorStore instance")
    return _vector_store

def get_pdf_processor() -> PDFProcessor:
    """Get the shared PDFProcessor instance.
    
    Returns:
        PDFProcessor: Singleton instance
    """
    global _pdf_processor
    if _pdf_processor is None:
        _pdf_processor = PDFProcessor()
        logger.info("Created shared PDFProcessor instance")
    return _pdf_processor

def get_quantum_search() -> QuantumSearch:
    """Get the shared QuantumSearch instance.
    
    Returns:
        QuantumSearch: Singleton instance
    """
    global _quantum_search
    if _quantum_search is None:
        _quantum_search = QuantumSearch()
        logger.info("Created shared QuantumSearch instance")
    return _quantum_search

async def initialize_services():
    """Initialize all shared services.
    
    This function should be called during application startup to
    initialize all services and warm up models.
    """
    logger.info("Initializing shared services...")
    
    # Initialize VectorStore
    vector_store = get_vector_store()
    await vector_store.initialize()
    
    # Initialize PDFProcessor (models will be loaded)
    pdf_processor = get_pdf_processor()
    
    # Initialize QuantumSearch
    quantum_search = get_quantum_search()
    
    logger.info("All shared services initialized successfully")

async def cleanup_services():
    """Cleanup all shared services.
    
    This function should be called during application shutdown.
    """
    global _vector_store, _pdf_processor, _quantum_search
    
    logger.info("Cleaning up shared services...")
    
    if _vector_store:
        await _vector_store.close()
        _vector_store = None
    
    # Reset other services
    _pdf_processor = None
    _quantum_search = None
    
    logger.info("All shared services cleaned up")