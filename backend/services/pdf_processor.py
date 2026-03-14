"""PDF processing service for chunking and embedding generation.

This service handles:
- PDF text extraction using PyPDF
- Text chunking with LangChain
- Embedding generation using HuggingFace
- Document metadata extraction
"""

import os
import hashlib
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import asyncio

# PDF processing
import pypdf
from pypdf import PdfReader

# LangChain for text processing
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document

# Embeddings
from langchain_community.embeddings import HuggingFaceEmbeddings

# Configuration
from config import settings, get_embedding_config

logger = logging.getLogger(__name__)

class PDFProcessor:
    """Service for processing PDF documents and generating embeddings."""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """Singleton pattern to ensure only one instance exists."""
        if cls._instance is None:
            cls._instance = super(PDFProcessor, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize the PDF processor with embedding service."""
        if self._initialized:
            return
            
        self.embedding_config = get_embedding_config()
        self.embeddings = None  # Initialize lazily when needed
        
        # Initialize text splitter for chunking
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            length_function=len,
            separators=["\n\n", "\n", " ", ""]
        )
        
        PDFProcessor._initialized = True
        
        logger.info(f"PDFProcessor initialized (embeddings will be loaded when needed)")
    
    def _initialize_embeddings(self):
        """Initialize HuggingFace embedding service."""
        try:
            # Use HuggingFace embeddings
            self.embeddings = HuggingFaceEmbeddings(
                model_name=self.embedding_config["model"]
            )
            logger.info("HuggingFace embeddings initialized")
        except Exception as e:
            logger.error(f"Failed to initialize embeddings: {e}")
            raise
    
    async def extract_text_from_pdf(self, file_path: str) -> Dict[str, Any]:
        """Extract text content from a PDF file.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            dict: Extracted text and metadata
        """
        try:
            logger.info(f"Extracting text from PDF: {file_path}")
            
            # Read PDF file
            with open(file_path, 'rb') as file:
                pdf_reader = PdfReader(file)
                
                # Extract metadata
                metadata = {
                    "file_path": file_path,
                    "file_name": os.path.basename(file_path),
                    "num_pages": len(pdf_reader.pages),
                    "processed_at": datetime.utcnow().isoformat(),
                    "file_size": os.path.getsize(file_path)
                }
                
                # Extract PDF metadata if available
                if pdf_reader.metadata:
                    metadata.update({
                        "title": pdf_reader.metadata.get("/Title", ""),
                        "author": pdf_reader.metadata.get("/Author", ""),
                        "subject": pdf_reader.metadata.get("/Subject", ""),
                        "creator": pdf_reader.metadata.get("/Creator", "")
                    })
                
                # Extract text from all pages
                full_text = ""
                page_texts = []
                
                for page_num, page in enumerate(pdf_reader.pages):
                    try:
                        page_text = page.extract_text()
                        if page_text.strip():  # Only add non-empty pages
                            page_texts.append({
                                "page_number": page_num + 1,
                                "text": page_text.strip()
                            })
                            full_text += f"\n\n--- Page {page_num + 1} ---\n\n{page_text}"
                    except Exception as e:
                        logger.warning(f"Failed to extract text from page {page_num + 1}: {e}")
                        continue
                
                # Generate file hash for deduplication
                file_hash = self._generate_file_hash(file_path)
                metadata["file_hash"] = file_hash
                
                result = {
                    "full_text": full_text.strip(),
                    "page_texts": page_texts,
                    "metadata": metadata
                }
                
                logger.info(f"Successfully extracted {len(page_texts)} pages from PDF")
                return result
                
        except Exception as e:
            logger.error(f"Failed to extract text from PDF {file_path}: {e}")
            raise
    
    async def chunk_text(self, text: str, metadata: Dict[str, Any]) -> List[Document]:
        """Split text into chunks using LangChain text splitter.
        
        Args:
            text: Full text content to chunk
            metadata: Document metadata to attach to chunks
            
        Returns:
            List[Document]: List of text chunks as LangChain documents
        """
        try:
            logger.info(f"Chunking text of length {len(text)}")
            
            # Create LangChain document
            document = Document(page_content=text, metadata=metadata)
            
            # Split into chunks
            chunks = self.text_splitter.split_documents([document])
            
            # Add chunk-specific metadata
            for i, chunk in enumerate(chunks):
                chunk.metadata.update({
                    "chunk_id": i,
                    "chunk_size": len(chunk.page_content),
                    "total_chunks": len(chunks)
                })
            
            logger.info(f"Created {len(chunks)} chunks")
            return chunks
            
        except Exception as e:
            logger.error(f"Failed to chunk text: {e}")
            raise
    
    async def generate_embeddings(self, chunks: List[Document]) -> List[Dict[str, Any]]:
        """Generate embeddings for text chunks.
        
        Args:
            chunks: List of text chunks as LangChain documents
            
        Returns:
            List[Dict]: List of chunks with embeddings and metadata
        """
        try:
            logger.info(f"Generating embeddings for {len(chunks)} chunks")
            
            # Extract texts for embedding
            texts = [chunk.page_content for chunk in chunks]
            
            # Generate embeddings using HuggingFace
            embeddings = await self._generate_huggingface_embeddings(texts)
            
            # Combine chunks with embeddings
            embedded_chunks = []
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                # Create unique ID using file hash, filename, timestamp, and chunk index
                file_hash = chunk.metadata.get('file_hash', 'unknown')
                file_name = chunk.metadata.get('file_name', 'unknown')
                processed_at = chunk.metadata.get('processed_at', datetime.utcnow().isoformat())
                
                # Create a more unique ID to prevent overwrites
                unique_id = f"{file_hash}_{file_name}_{processed_at}_{i}".replace(' ', '_').replace(':', '-')
                
                embedded_chunk = {
                    "id": unique_id,
                    "text": chunk.page_content,
                    "embedding": embedding,
                    "metadata": chunk.metadata
                }
                embedded_chunks.append(embedded_chunk)
            
            logger.info(f"Successfully generated embeddings for {len(embedded_chunks)} chunks")
            return embedded_chunks
            
        except Exception as e:
            logger.error(f"Failed to generate embeddings: {e}")
            raise
    
    async def _generate_huggingface_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using HuggingFace models."""
        try:
            # Initialize embeddings if not already done
            if self.embeddings is None:
                self._initialize_embeddings()
            
            # Use LangChain's HuggingFace embeddings
            embeddings = await asyncio.to_thread(
                self.embeddings.embed_documents, texts
            )
            return embeddings
        except Exception as e:
            logger.error(f"HuggingFace embedding generation failed: {e}")
            raise
    
    async def process_pdf(self, file_path: str) -> Dict[str, Any]:
        """Complete PDF processing pipeline: extract, chunk, and embed.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            dict: Processing results with embedded chunks
        """
        try:
            logger.info(f"Starting complete PDF processing for: {file_path}")
            
            # Step 1: Extract text from PDF
            extraction_result = await self.extract_text_from_pdf(file_path)
            
            if not extraction_result["full_text"].strip():
                raise ValueError("No text content found in PDF")
            
            # Step 2: Chunk the text
            chunks = await self.chunk_text(
                extraction_result["full_text"],
                extraction_result["metadata"]
            )
            
            # Step 3: Generate embeddings
            embedded_chunks = await self.generate_embeddings(chunks)
            
            # Prepare final result
            result = {
                "success": True,
                "file_metadata": extraction_result["metadata"],
                "chunks_count": len(embedded_chunks),
                "embedded_chunks": embedded_chunks,
                "processing_time": datetime.utcnow().isoformat()
            }
            
            logger.info(f"PDF processing completed successfully: {len(embedded_chunks)} chunks created")
            return result
            
        except Exception as e:
            logger.error(f"PDF processing failed for {file_path}: {e}")
            return {
                "success": False,
                "error": str(e),
                "file_path": file_path
            }
    
    def _generate_file_hash(self, file_path: str) -> str:
        """Generate SHA-256 hash of file for deduplication.
        
        Args:
            file_path: Path to the file
            
        Returns:
            str: SHA-256 hash of the file
        """
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
    
    async def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a search query.
        
        Args:
            query: Search query text
            
        Returns:
            List[float]: Query embedding vector
        """
        try:
            # Initialize embeddings if not already done
            if self.embeddings is None:
                self._initialize_embeddings()
            
            # Generate embedding using HuggingFace
            embedding = await asyncio.to_thread(
                self.embeddings.embed_query, query
            )
            
            return embedding
            
        except Exception as e:
            logger.error(f"Failed to generate query embedding: {e}")
            raise