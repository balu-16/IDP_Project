"""FastAPI backend for AI-powered PDF chatbot with quantum-enhanced search.

This is the main entry point for the FastAPI application that provides:
- PDF upload and processing endpoints
- Quantum-enhanced vector search using Grover's Algorithm
- ChromaDB persistent vector storage
- HuggingFace embeddings integration
"""

import os
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
from datetime import datetime

# Import configuration
from config import settings

# Import route modules
from routes.pdf_routes import router as pdf_router
from routes.query_routes import router as query_router
from routes.chat_routes import router as chat_router
from routes.auth_routes import router as auth_router
# Chat history routes removed - now handled by frontend

# Import services for initialization
from services.shared import initialize_services, cleanup_services, get_vector_store

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    # Startup
    logger.info("🚀 Starting Quantum PDF Chatbot Backend...")
    
    try:
        # Initialize all shared services (VectorStore, PDFProcessor, etc.)
        await initialize_services()
        logger.info("✅ All services initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize services: {e}")
        raise
    
    # Create chroma_db directory if it doesn't exist
    os.makedirs("./chroma_db", exist_ok=True)
    logger.info("📁 ChromaDB directory ensured")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Quantum PDF Chatbot Backend...")
    await cleanup_services()

# Create FastAPI application
app = FastAPI(
    title="Quantum PDF Chatbot Backend",
    description="AI-powered PDF chatbot with quantum-enhanced search using Grover's Algorithm",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint to verify the API is running.
    
    Returns:
        dict: Status information including timestamp and service health
    """
    try:
        # Check if vector store is initialized
        vector_store = get_vector_store()
        vector_store_status = "healthy" if vector_store and vector_store.client else "not_initialized"
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0",
            "services": {
                "vector_store": vector_store_status,
                "quantum_search": "available",
                "pdf_processor": "available"
            },
            "environment": settings.ENVIRONMENT
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail="Service unhealthy")

# Include routers
app.include_router(pdf_router, prefix="/api/v1", tags=["PDF Processing"])
app.include_router(query_router, prefix="/api/v1", tags=["Query & Search"])
app.include_router(chat_router, prefix="/api", tags=["Chat & Conversation"])
app.include_router(auth_router, tags=["Authentication"])
# Chat history routes removed - now handled by frontend

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled errors."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)}
    )

# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Quantum PDF Chatbot Backend API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }

if __name__ == "__main__":
    # Run the application
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
        log_level="info"
    )