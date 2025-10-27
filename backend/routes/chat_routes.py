"""Chat routes for the FastAPI backend.

This module handles:
- Chat endpoint for conversational responses
- Integration with Gemini API
- Context-aware responses using document search
- Document search and AI responses only
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

# FastAPI imports
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Google Generative AI
import google.generativeai as genai

# Services
from services.shared import get_pdf_processor, get_vector_store, get_quantum_search
# Database service removed - chat history now handled by frontend
from services.vector_store import VectorStore
from services.quantum_search import QuantumSearch

# Configuration
from config import settings

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(tags=["chat"])

# PDF processor will be accessed via shared services

# Configure Gemini API
if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)
    logger.info("Gemini API configured successfully")
else:
    logger.warning("Gemini API key not found. Chat functionality will be limited.")

# Pydantic models for request/response
class ChatRequest(BaseModel):
    """Request model for chat messages."""
    message: str = Field(..., min_length=1, max_length=2000, description="User message")
    user_id: int = Field(..., description="User ID from signup_users table")
    chat_id: Optional[int] = Field(default=None, description="Chat session ID (auto-generated if not provided)")
    session_id: Optional[str] = Field(default=None, description="Legacy session ID (deprecated)")
    use_context: bool = Field(default=True, description="Whether to use document context for relevant queries")
    force_general: bool = Field(default=False, description="Force general conversation mode without document context")
    max_context_results: int = Field(default=3, ge=1, le=10, description="Max context documents")
    temperature: float = Field(default=0.7, ge=0.0, le=1.0, description="Response creativity")

class ChatResponse(BaseModel):
    """Response model for chat messages."""
    success: bool
    response: str
    chat_id: int
    session_id: str
    context_used: bool
    context_sources: List[Dict[str, Any]]
    processing_time_ms: float
    metadata: Dict[str, Any]

@router.post("/chat", response_model=ChatResponse)
async def chat_message(
    request: ChatRequest,
    vector_store: VectorStore = Depends(get_vector_store),
    quantum_search: QuantumSearch = Depends(get_quantum_search),
    pdf_processor = Depends(get_pdf_processor)
) -> JSONResponse:
    """Process chat message and generate AI response.
    
    This endpoint:
    1. Validates the chat message
    2. Optionally searches for relevant document context
    3. Generates AI response using Gemini API
    4. Returns response with context sources
    
    Args:
        request: Chat request with message and options
        vector_store: ChromaDB vector store instance
        quantum_search: Quantum search service instance
        
    Returns:
        JSONResponse: AI response with metadata
    """
    start_time = datetime.utcnow()
    
    try:
        logger.info(f"Received chat message from user {request.user_id}: '{request.message[:100]}...'")
        
        # Validate Gemini API availability
        if not settings.GEMINI_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="Gemini API is not configured. Please set GEMINI_API_KEY environment variable."
            )
        
        # Generate session ID if not provided (for backward compatibility)
        session_id = request.session_id or f"session_{datetime.utcnow().timestamp()}"
        chat_id = request.chat_id or session_id  # Use session_id as chat_id if not provided
        
        # Initialize context variables
        context_sources = []
        context_text = ""
        context_used = False
        
        # Search for relevant context if requested and not forcing general mode
        if request.use_context and not request.force_general:
            try:
                # Check if vector store has data
                stats = await vector_store.get_collection_stats()
                if stats["has_data"]:
                    logger.info("Searching for relevant document context...")
                    
                    # Generate query embedding
                    query_embedding = await pdf_processor.embed_query(request.message)
                    
                    # Determine search method based on data size
                    use_quantum = stats["total_documents"] <= 2**settings.QUANTUM_MAX_QUBITS
                    
                    if use_quantum:
                        # Quantum-enhanced search with session filtering
                        results = await _quantum_context_search(
                            query_embedding=query_embedding,
                            vector_store=vector_store,
                            quantum_search=quantum_search,
                            top_k=request.max_context_results,
                            session_id=session_id
                        )
                    else:
                        # Classical similarity search with session filtering
                        results = await _classical_context_search(
                            query_embedding=query_embedding,
                            vector_store=vector_store,
                            top_k=request.max_context_results,
                            session_id=session_id
                        )
                    
                    if results:
                        context_used = True
                        context_sources = results
                        # Combine context from top results
                        context_text = "\n\n".join([
                            f"Source: {result.get('metadata', {}).get('filename', 'Unknown')}\n{result['document']}"
                            for result in results[:request.max_context_results]
                        ])
                        logger.info(f"Found {len(results)} relevant context sources")
                        logger.info(f"Context text length: {len(context_text)} characters")
                        logger.info(f"First 200 chars of context: {context_text[:200]}...")
                        logger.info(f"Sample result structure: {results[0] if results else 'No results'}")
                    else:
                        logger.info("No relevant context found")
                else:
                    logger.info("No documents in vector store for context")
            except Exception as e:
                logger.warning(f"Context search failed: {e}. Proceeding without context.")
        
        # Generate AI response using Gemini
        response_text = await _generate_gemini_response(
            user_message=request.message,
            context=context_text,
            temperature=request.temperature
        )
        
        # Calculate processing time
        end_time = datetime.utcnow()
        processing_time_ms = (end_time - start_time).total_seconds() * 1000
        
        # Chat history is now handled by frontend - no database save needed
        
        # Prepare response
        response_data = {
            "success": True,
            "response": response_text,
            "chat_id": chat_id,
            "session_id": session_id,
            "context_used": context_used,
            "context_sources": context_sources,
            "processing_time_ms": round(processing_time_ms, 2),
            "metadata": {
                "model": "gemini-2.5-flash",
                "temperature": request.temperature,
                "context_documents": len(context_sources),
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        
        logger.info(f"Chat response generated in {processing_time_ms:.2f}ms")
        return JSONResponse(
            status_code=200,
            content=response_data
        )
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Chat message processing failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during chat processing: {str(e)}"
        )

async def _generate_gemini_response(
    user_message: str,
    context: str = "",
    temperature: float = 0.7
) -> str:
    """Generate response using Gemini API.
    
    Args:
        user_message: User's message
        context: Relevant document context
        temperature: Response creativity level
        
    Returns:
        str: Generated response
    """
    try:
        # Initialize Gemini model
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Prepare prompt with context
        if context:
            prompt = f"""You are QubitChat AI, an intelligent and friendly assistant. You can help with both document-based questions and general conversations.

I have found some relevant information from uploaded documents:

Context from documents:
{context}

User question: {user_message}

Instructions:
1. If the user's question is directly related to the document content, use the context to provide a detailed answer and mention the source.
2. If the user's question is general (like greetings, general knowledge, casual conversation), respond naturally without forcing document references.
3. If the question is partially related to documents, combine both document insights and general knowledge as appropriate.
4. Always be helpful, conversational, and engaging."""
        else:
            prompt = f"""You are QubitChat AI, an intelligent and friendly assistant. You can help with general questions, casual conversation, and various topics.

User question: {user_message}

Please provide a helpful, engaging response. Feel free to have natural conversations on any topic. If the user wants document-specific help, let them know they can upload documents for more targeted assistance."""
        
        # Generate response
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=4000,
                top_p=0.8,
                top_k=40
            )
        )
        
        return response.text
        
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        # Fallback response
        return "I apologize, but I'm having trouble generating a response right now. Please try again later."

async def _quantum_context_search(
    query_embedding: List[float],
    vector_store: VectorStore,
    quantum_search: QuantumSearch,
    top_k: int,
    session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Perform quantum-enhanced context search with session filtering.
    
    Args:
        query_embedding: Query embedding vector
        vector_store: Vector store instance
        quantum_search: Quantum search instance
        top_k: Number of results to return
        session_id: Optional session ID to filter results
        
    Returns:
        List[Dict]: Search results
    """
    try:
        # Get all embeddings from vector store (optionally filtered by session)
        all_embeddings = await vector_store.get_all_embeddings(session_id=session_id)
        
        if not all_embeddings:
            return []
        
        # Perform quantum-enhanced search
        results = await quantum_search.quantum_enhanced_search(
            query_embedding=query_embedding,
            document_embeddings=all_embeddings,
            similarity_threshold=0.3,  # Lower threshold for better context retrieval
            top_k=top_k
        )
        
        return results
        
    except Exception as e:
        logger.error(f"Quantum context search failed: {e}")
        return []

async def _classical_context_search(
    query_embedding: List[float],
    vector_store: VectorStore,
    top_k: int,
    session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Perform classical context search with session filtering.
    
    Args:
        query_embedding: Query embedding vector
        vector_store: Vector store instance
        top_k: Number of results to return
        session_id: Optional session ID to filter results
        
    Returns:
        List[Dict]: Search results
    """
    try:
        # Build where filter for session
        where_filter = None
        if session_id:
            where_filter = {"session_id": session_id}
            logger.info(f"Filtering documents by session_id: {session_id}")
        
        # Perform similarity search with optional session filtering
        results = await vector_store.similarity_search(
            query_embedding=query_embedding,
            n_results=top_k,
            where=where_filter
        )
        
        # Format results to match quantum search format
        formatted_results = []
        for result in results:
            formatted_result = {
                "id": result["id"],
                "document": result["document"],
                "metadata": result["metadata"],
                "similarity_score": result["similarity_score"],
                "distance": result["distance"],
                "search_method": "classical"
            }
            formatted_results.append(formatted_result)
        
        return formatted_results
        
    except Exception as e:
        logger.error(f"Classical context search failed: {e}")
        return []

# Export router
__all__ = ["router"]