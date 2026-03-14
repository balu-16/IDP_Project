"""Query routes for the FastAPI backend.

This module handles:
- Query endpoint for searching processed PDFs
- Integration with quantum search service
- Vector similarity search
- Response formatting and error handling
"""

import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

# FastAPI imports
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Services
from services.shared import get_pdf_processor, get_vector_store, get_quantum_search
from services.retrieval import retrieve_ranked_documents
from services.vector_store import VectorStore
from services.quantum_search import QuantumSearch

# Configuration
from config import settings

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(tags=["query"])

# PDF processor will be accessed via shared services

# Pydantic models for request/response
class QueryRequest(BaseModel):
    """Request model for search queries."""
    query: str = Field(..., min_length=1, max_length=1000, description="Search query text")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of results to return")
    similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="Minimum similarity threshold for quantum marking")
    use_quantum: bool = Field(default=True, description="Whether to use quantum-enhanced search")
    filter_metadata: Optional[Dict[str, str]] = Field(default=None, description="Optional metadata filters")

class QueryResponse(BaseModel):
    """Response model for search results."""
    success: bool
    query: str
    results_count: int
    search_method: str
    retrieval_time_ms: float
    processing_time_ms: float
    results: List[Dict[str, Any]]
    metadata: Dict[str, Any]

@router.post("/query", response_model=QueryResponse)
async def search_query(
    request: QueryRequest,
    vector_store: VectorStore = Depends(get_vector_store),
    quantum_search: QuantumSearch = Depends(get_quantum_search),
    pdf_processor = Depends(get_pdf_processor)
) -> JSONResponse:
    processing_start = time.perf_counter()
    
    try:
        logger.info(f"Received search query: '{request.query[:100]}...'")
        
        # Validate query
        if not request.query.strip():
            raise HTTPException(
                status_code=400,
                detail="Query cannot be empty"
            )
        
        # Check if vector store has data
        stats = await vector_store.get_collection_stats()
        if not stats["has_data"]:
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "query": request.query,
                    "results_count": 0,
                    "search_method": "none",
                    "retrieval_time_ms": 0,
                    "processing_time_ms": 0,
                    "results": [],
                    "metadata": {
                        "message": "No documents found in vector store. Please upload PDFs first.",
                        "total_documents": 0
                    }
                }
            )
        
        # Generate query embedding
        logger.info("Generating query embedding...")
        query_embedding = await pdf_processor.embed_query(request.query)

        search_result = await retrieve_ranked_documents(
            query_embedding=query_embedding,
            vector_store=vector_store,
            quantum_search=quantum_search,
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
            use_quantum=request.use_quantum,
            metadata_filter=request.filter_metadata,
        )
        results = search_result["results"]
        retrieval_time_ms = search_result["retrieval_time_ms"]
        search_method = search_result["search_method"]

        processing_time_ms = (time.perf_counter() - processing_start) * 1000
        
        # Prepare response
        response_data = {
            "success": True,
            "query": request.query,
            "results_count": len(results),
            "search_method": search_method,
            "retrieval_time_ms": round(retrieval_time_ms, 2),
            "processing_time_ms": round(processing_time_ms, 2),
            "results": results,
            "metadata": {
                "total_documents_in_store": stats["total_documents"],
                "similarity_threshold": request.similarity_threshold,
                "quantum_requested": request.use_quantum,
                "quantum_enabled": search_method == "quantum_enhanced",
                "retrieval_method": search_method,
                "fallback_reason": search_result.get("fallback_reason"),
                "candidate_count": search_result.get("candidate_count", 0),
                "embedding_model": pdf_processor.embedding_config["model"],
                "search_timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
        
        logger.info(f"Search completed: {len(results)} results in {processing_time_ms:.2f}ms")
        return JSONResponse(
            status_code=200,
            content=response_data
        )
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Search query failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during search: {str(e)}"
        )

@router.get("/search_stats")
async def get_search_stats(
    vector_store: VectorStore = Depends(get_vector_store),
    quantum_search: QuantumSearch = Depends(get_quantum_search),
    pdf_processor = Depends(get_pdf_processor),
) -> JSONResponse:
    """Get search service statistics and capabilities.
    
    Args:
        vector_store: ChromaDB vector store instance
        quantum_search: Quantum search service instance
        
    Returns:
        JSONResponse: Search service statistics
    """
    try:
        logger.info("Retrieving search service statistics")
        
        # Get vector store stats
        vector_stats = await vector_store.get_collection_stats()
        
        # Get quantum search stats
        quantum_stats = await quantum_search.get_quantum_stats()
        
        # Combine statistics
        combined_stats = {
            "vector_store": vector_stats,
            "quantum_search": quantum_stats,
            "embedding_service": {
                "provider": pdf_processor.embedding_config["service"],
                "model": pdf_processor.embedding_config["model"]
            },
            "search_capabilities": {
                "classical_search": True,
                "quantum_enhanced_search": True,
                "metadata_filtering": True,
                "max_quantum_documents": 2**settings.QUANTUM_MAX_QUBITS,
                "max_results_per_query": 20
            },
            "performance": {
                "chunk_size": settings.CHUNK_SIZE,
                "chunk_overlap": settings.CHUNK_OVERLAP,
                "quantum_boost_factor": settings.QUANTUM_BOOST_FACTOR
            }
        }
        
        return JSONResponse(
            status_code=200,
            content=combined_stats
        )
        
    except Exception as e:
        logger.error(f"Failed to get search stats: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve search statistics: {str(e)}"
        )

# Additional utility endpoints
@router.get("/similar_documents/{document_id}")
async def find_similar_documents(
    document_id: str,
    top_k: int = Query(default=5, ge=1, le=10),
    vector_store: VectorStore = Depends(get_vector_store)
) -> JSONResponse:
    """Find documents similar to a specific document.
    
    Args:
        document_id: ID of the reference document
        top_k: Number of similar documents to return
        vector_store: Vector store instance
        
    Returns:
        JSONResponse: Similar documents
    """
    try:
        logger.info(f"Finding documents similar to: {document_id}")
        
        # Get all embeddings to find the reference document
        all_embeddings = await vector_store.get_all_embeddings()
        
        # Find the reference document
        reference_doc = None
        for doc in all_embeddings:
            if doc["id"] == document_id:
                reference_doc = doc
                break
        
        if not reference_doc:
            raise HTTPException(
                status_code=404,
                detail=f"Document with ID '{document_id}' not found"
            )
        
        # Use the reference document's embedding as query
        results = await vector_store.similarity_search(
            query_embedding=reference_doc["embedding"],
            n_results=top_k + 1  # +1 to exclude the reference document itself
        )
        
        # Filter out the reference document
        similar_docs = [r for r in results if r["id"] != document_id][:top_k]
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "reference_document_id": document_id,
                "similar_documents_count": len(similar_docs),
                "similar_documents": similar_docs
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to find similar documents: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

# Export router
__all__ = ["router"]
