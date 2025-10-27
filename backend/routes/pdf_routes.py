"""PDF upload routes for the FastAPI backend.

This module handles:
- PDF file upload endpoint
- File validation and processing
- Integration with PDF processor service
- Vector store operations for embeddings
- Error handling and response formatting
"""

import os
import tempfile
import logging
from typing import Dict, Any
from datetime import datetime

# FastAPI imports
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import Optional

# Services
from services.shared import get_vector_store, get_pdf_processor
from services.vector_store import VectorStore

# Configuration
from config import settings

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(tags=["pdf"])

# Get shared service instances
pdf_processor = get_pdf_processor()

@router.post("/upload_pdf")
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    vector_store: VectorStore = Depends(get_vector_store)
) -> JSONResponse:
    """Upload and process a PDF file with session tracking.
    
    This endpoint:
    1. Validates the uploaded PDF file
    2. Saves it temporarily
    3. Extracts text and creates chunks
    4. Generates embeddings
    5. Stores embeddings in ChromaDB with session_id metadata
    6. Returns processing results
    
    Args:
        background_tasks: FastAPI background tasks
        file: Uploaded PDF file
        session_id: Optional chat session ID to associate with this PDF
        user_id: Optional user ID
        vector_store: ChromaDB vector store instance
        
    Returns:
        JSONResponse: Processing results and metadata
    """
    temp_file_path = None
    
    try:
        logger.info(f"Received PDF upload request: {file.filename} (session_id: {session_id}, user_id: {user_id})")
        
        # Validate file
        validation_result = await _validate_pdf_file(file)
        if not validation_result["valid"]:
            raise HTTPException(
                status_code=400,
                detail=validation_result["error"]
            )
        
        # Save uploaded file temporarily
        temp_file_path = await _save_temp_file(file)
        
        # Process PDF in background for better performance
        processing_task = _process_pdf_background(
            temp_file_path, 
            file.filename, 
            vector_store,
            session_id=session_id,
            user_id=user_id
        )
        
        # For now, process synchronously to return results immediately
        # In production, you might want to use background processing with job IDs
        result = await processing_task
        
        # Clean up temp file
        background_tasks.add_task(_cleanup_temp_file, temp_file_path)
        
        if result["success"]:
            response_data = {
                "success": True,
                "message": "PDF processed successfully",
                "file_name": file.filename,
                "file_size": result["file_metadata"].get("file_size", 0),
                "pages_processed": result["file_metadata"].get("num_pages", 0),
                "chunks_created": result["chunks_count"],
                "embeddings_stored": result["chunks_count"],
                "processing_time": result["processing_time"],
                "file_hash": result["file_metadata"].get("file_hash"),
                "metadata": {
                    "title": result["file_metadata"].get("title", ""),
                    "author": result["file_metadata"].get("author", ""),
                    "processed_at": result["file_metadata"].get("processed_at")
                }
            }
            
            logger.info(f"PDF processing completed successfully: {file.filename}")
            return JSONResponse(
                status_code=200,
                content=response_data
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"PDF processing failed: {result.get('error', 'Unknown error')}"
            )
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected error in PDF upload: {e}")
        
        # Clean up temp file on error
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as cleanup_error:
                logger.error(f"Failed to cleanup temp file: {cleanup_error}")
        
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during PDF processing: {str(e)}"
        )

@router.get("/pdf_stats")
async def get_pdf_stats(
    vector_store: VectorStore = Depends(get_vector_store)
) -> JSONResponse:
    """Get statistics about processed PDFs in the vector store.
    
    Args:
        vector_store: ChromaDB vector store instance
        
    Returns:
        JSONResponse: Vector store statistics
    """
    try:
        logger.info("Retrieving PDF processing statistics")
        
        # Get collection statistics
        stats = await vector_store.get_collection_stats()
        
        # Add processing service info
        stats.update({
            "pdf_processor": {
                "embedding_service": pdf_processor.embedding_config["service"],
                "embedding_model": pdf_processor.embedding_config["model"],
                "chunk_size": settings.CHUNK_SIZE,
                "chunk_overlap": settings.CHUNK_OVERLAP
            },
            "supported_formats": ["pdf"],
            "max_file_size_mb": settings.MAX_FILE_SIZE // (1024 * 1024)
        })
        
        return JSONResponse(
            status_code=200,
            content=stats
        )
        
    except Exception as e:
        logger.error(f"Failed to get PDF stats: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve statistics: {str(e)}"
        )

@router.delete("/clear_pdfs")
async def clear_all_pdfs(
    vector_store: VectorStore = Depends(get_vector_store)
) -> JSONResponse:
    """Clear all PDF data from the vector store.
    
    WARNING: This will delete all processed PDFs and embeddings!
    
    Args:
        vector_store: ChromaDB vector store instance
        
    Returns:
        JSONResponse: Deletion result
    """
    try:
        logger.warning("Clearing all PDF data from vector store")
        
        # Reset the collection
        result = await vector_store.reset_collection()
        
        if result["success"]:
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": "All PDF data cleared successfully",
                    "collection_reset": True
                }
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to clear PDF data: {result.get('error', 'Unknown error')}"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to clear PDF data: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

async def _validate_pdf_file(file: UploadFile) -> Dict[str, Any]:
    """Validate uploaded PDF file.
    
    Args:
        file: Uploaded file to validate
        
    Returns:
        dict: Validation result with success status and error message
    """
    try:
        # Check file extension
        if not file.filename or not file.filename.lower().endswith('.pdf'):
            return {
                "valid": False,
                "error": "File must be a PDF (.pdf extension required)"
            }
        
        # Check content type
        if file.content_type and not file.content_type.startswith('application/pdf'):
            logger.warning(f"Unexpected content type: {file.content_type}")
            # Don't fail on content type as it can be unreliable
        
        # Check file size
        if hasattr(file, 'size') and file.size:
            if file.size > settings.MAX_FILE_SIZE:
                return {
                    "valid": False,
                    "error": f"File size exceeds maximum limit of {settings.MAX_FILE_SIZE // (1024 * 1024)}MB"
                }
        
        # Basic filename validation
        if len(file.filename) > 255:
            return {
                "valid": False,
                "error": "Filename too long (maximum 255 characters)"
            }
        
        return {"valid": True}
        
    except Exception as e:
        logger.error(f"File validation error: {e}")
        return {
            "valid": False,
            "error": f"File validation failed: {str(e)}"
        }

async def _save_temp_file(file: UploadFile) -> str:
    """Save uploaded file to temporary location.
    
    Args:
        file: Uploaded file to save
        
    Returns:
        str: Path to temporary file
    """
    try:
        # Create temporary file
        temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf', prefix='upload_')
        
        # Write file content
        with os.fdopen(temp_fd, 'wb') as temp_file:
            content = await file.read()
            temp_file.write(content)
        
        # Reset file position for potential re-reading
        await file.seek(0)
        
        logger.info(f"Saved temporary file: {temp_path}")
        return temp_path
        
    except Exception as e:
        logger.error(f"Failed to save temporary file: {e}")
        raise

async def _process_pdf_background(
    file_path: str, 
    filename: str, 
    vector_store: VectorStore,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Process PDF file and store embeddings with session metadata (background task).
    
    Args:
        file_path: Path to the PDF file
        filename: Original filename
        vector_store: Vector store instance
        session_id: Optional chat session ID
        user_id: Optional user ID
        
    Returns:
        dict: Processing result
    """
    try:
        logger.info(f"Starting background PDF processing: {filename} (session: {session_id})")
        
        # Process PDF through the pipeline
        processing_result = await pdf_processor.process_pdf(file_path)
        
        if not processing_result["success"]:
            return processing_result
        
        # Add session_id and user_id to all embedded chunks metadata
        if session_id or user_id:
            for chunk in processing_result["embedded_chunks"]:
                if session_id:
                    chunk["metadata"]["session_id"] = session_id
                if user_id:
                    chunk["metadata"]["user_id"] = user_id
            logger.info(f"Added session metadata to {len(processing_result['embedded_chunks'])} chunks")
        
        # Store embeddings in vector store
        storage_result = await vector_store.add_documents(
            processing_result["embedded_chunks"]
        )
        
        if not storage_result["success"]:
            return {
                "success": False,
                "error": f"Failed to store embeddings: {storage_result.get('error', 'Unknown error')}"
            }
        
        # Combine results
        final_result = processing_result.copy()
        final_result["storage_result"] = storage_result
        
        logger.info(f"Background PDF processing completed: {filename}")
        return final_result
        
    except Exception as e:
        logger.error(f"Background PDF processing failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }

def _cleanup_temp_file(file_path: str):
    """Clean up temporary file (background task).
    
    Args:
        file_path: Path to temporary file to delete
    """
    try:
        if os.path.exists(file_path):
            os.unlink(file_path)
            logger.info(f"Cleaned up temporary file: {file_path}")
    except Exception as e:
        logger.error(f"Failed to cleanup temporary file {file_path}: {e}")

# Export router
__all__ = ["router"]