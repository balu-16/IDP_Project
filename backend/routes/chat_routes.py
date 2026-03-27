"""Chat routes for the FastAPI backend.

This module handles:
- Chat endpoint for conversational responses
- Integration with Gemini API
- Context-aware responses using document search
- Document search and AI responses only
"""

import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

# FastAPI imports
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Google Generative AI
import google.generativeai as genai

# Services
from services.shared import get_pdf_processor, get_vector_store, get_quantum_search
from services.retrieval import retrieve_ranked_documents
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
    retrieval_time_ms: float
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
    processing_start = time.perf_counter()
    
    try:
        logger.info(f"Received chat message from user {request.user_id}: '{request.message[:100]}...'")
        
        # Validate Gemini API availability
        if not settings.GEMINI_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="Gemini API is not configured. Please set GEMINI_API_KEY environment variable."
            )
        
        # Use explicit chat/session scope from client. Do not perform context retrieval without scope.
        session_id = request.session_id or (str(request.chat_id) if request.chat_id is not None else None)
        chat_id = request.chat_id or session_id or f"session_{datetime.utcnow().timestamp()}"
        
        # Initialize context variables
        context_sources = []
        context_text = ""
        context_used = False
        retrieval_time_ms = 0.0
        retrieval_method = "none"
        fallback_reason = None
        candidate_count = 0
        
        # Search for relevant context if requested and not forcing general mode
        if request.use_context and not request.force_general:
            try:
                if not session_id:
                    logger.info("No session_id/chat_id provided; skipping context retrieval to enforce chat isolation")
                    raise ValueError("missing_session_scope")

                # Check if vector store has data
                stats = await vector_store.get_collection_stats()
                if stats["has_data"]:
                    logger.info("Searching for relevant document context...")
                    
                    # Generate query embedding
                    query_embedding = await pdf_processor.embed_query(request.message)
                    
                    search_result = await retrieve_ranked_documents(
                        query_embedding=query_embedding,
                        vector_store=vector_store,
                        quantum_search=quantum_search,
                        top_k=request.max_context_results,
                        similarity_threshold=0.3,
                        use_quantum=True,
                        session_id=session_id,
                        user_id=request.user_id,
                    )
                    results = search_result["results"]
                    retrieval_time_ms = search_result["retrieval_time_ms"]
                    retrieval_method = search_result["search_method"]
                    fallback_reason = search_result.get("fallback_reason")
                    candidate_count = search_result.get("candidate_count", 0)
                    logger.info(
                        "Chat retrieval completed (session: %s, user: %s, candidates: %s, results: %s, method: %s, fallback: %s)",
                        session_id,
                        request.user_id,
                        candidate_count,
                        len(results),
                        retrieval_method,
                        fallback_reason,
                    )
                    
                    if results:
                        context_used = True
                        context_sources = results
                        # Combine context from top results
                        context_text = "\n\n".join([
                            (
                                f"Source: "
                                f"{result.get('metadata', {}).get('title') or result.get('metadata', {}).get('file_name') or result.get('metadata', {}).get('filename') or 'Unknown'}\n"
                                f"{result['document']}"
                            )
                            for result in results[:request.max_context_results]
                        ])
                        logger.info(f"Found {len(results)} relevant context sources")
                        logger.info(f"Context text length: {len(context_text)} characters")
                        logger.info(f"First 200 chars of context: {context_text[:200]}...")
                        logger.info(f"Sample result structure: {results[0] if results else 'No results'}")
                    else:
                        logger.info(
                            "No relevant context found for session-scoped retrieval (session: %s, user: %s, candidates: %s, fallback: %s)",
                            session_id,
                            request.user_id,
                            candidate_count,
                            fallback_reason,
                        )
                else:
                    logger.info("No documents in vector store for context")
            except ValueError as e:
                if str(e) != "missing_session_scope":
                    logger.warning(f"Context search skipped: {e}")
            except Exception as e:
                logger.warning(f"Context search failed: {e}. Proceeding without context.")
        
        # Generate AI response using Gemini
        response_text = await _generate_gemini_response(
            user_message=request.message,
            context=context_text,
            temperature=request.temperature
        )
        
        processing_time_ms = (time.perf_counter() - processing_start) * 1000
        
        # Chat history is now handled by frontend - no database save needed
        
        # Prepare response
        response_data = {
            "success": True,
            "response": response_text,
            "chat_id": chat_id,
            "session_id": session_id or str(chat_id),
            "context_used": context_used,
            "context_sources": context_sources,
            "retrieval_time_ms": round(retrieval_time_ms, 2),
            "processing_time_ms": round(processing_time_ms, 2),
            "metadata": {
                "model": "gemini-2.5-flash",
                "temperature": request.temperature,
                "context_documents": len(context_sources),
                "candidate_count": candidate_count,
                "retrieval_method": retrieval_method,
                "fallback_reason": fallback_reason,
                "timestamp": datetime.now(timezone.utc).isoformat()
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

# Export router
__all__ = ["router"]
