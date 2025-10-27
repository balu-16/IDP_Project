"""Vector store service using ChromaDB with persistent storage.

This service handles:
- ChromaDB persistent client initialization
- Collection management for embeddings
- Document storage and retrieval
- Similarity search operations
- Metadata filtering and querying
"""

import os
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import asyncio

# ChromaDB for vector storage
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

# Configuration
from config import settings

logger = logging.getLogger(__name__)

class VectorStore:
    """Service for managing vector embeddings with ChromaDB persistent storage."""
    
    _instance = None
    _initialized = False
    
    def __new__(cls, db_path: str = "./chroma_db"):
        """Singleton pattern to ensure only one instance exists."""
        if cls._instance is None:
            cls._instance = super(VectorStore, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, db_path: str = "./chroma_db"):
        """Initialize ChromaDB persistent client.
        
        Args:
            db_path: Path to ChromaDB persistent storage directory
        """
        if self._initialized:
            return
            
        self.db_path = db_path
        self.client = None
        self.collection = None
        self.collection_name = settings.CHROMA_COLLECTION_NAME
        
        # Ensure database directory exists
        os.makedirs(self.db_path, exist_ok=True)
        
        VectorStore._initialized = True
        logger.info(f"VectorStore initialized with path: {self.db_path}")
    
    async def initialize(self):
        """Initialize ChromaDB client and collection."""
        try:
            logger.info("Initializing ChromaDB persistent client...")
            
            # Create persistent client
            self.client = chromadb.PersistentClient(
                path=self.db_path,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            
            # Get or create collection
            try:
                self.collection = self.client.get_collection(
                    name=self.collection_name
                )
                logger.info(f"Loaded existing collection: {self.collection_name}")
            except Exception:
                # Collection doesn't exist, create it
                self.collection = self.client.create_collection(
                    name=self.collection_name,
                    metadata={"description": "PDF document embeddings for chatbot"},
                    embedding_function=None  # We'll provide embeddings directly
                )
                logger.info(f"Created new collection: {self.collection_name}")
            
            # Log collection stats
            count = self.collection.count()
            logger.info(f"Collection '{self.collection_name}' contains {count} documents")
            
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
            raise
    
    async def add_documents(self, embedded_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Add embedded document chunks to the vector store.
        
        Args:
            embedded_chunks: List of chunks with embeddings and metadata
            
        Returns:
            dict: Operation result with statistics
        """
        try:
            if not self.collection:
                await self.initialize()
            
            logger.info(f"Adding {len(embedded_chunks)} documents to vector store")
            
            # Prepare data for ChromaDB
            ids = []
            embeddings = []
            documents = []
            metadatas = []
            
            for chunk in embedded_chunks:
                ids.append(chunk["id"])
                embeddings.append(chunk["embedding"])
                documents.append(chunk["text"])
                
                # Prepare metadata (ChromaDB requires string values)
                metadata = {}
                for key, value in chunk["metadata"].items():
                    if isinstance(value, (str, int, float, bool)):
                        metadata[key] = str(value)
                    elif value is not None:
                        metadata[key] = str(value)
                
                # Add timestamp
                metadata["added_at"] = datetime.utcnow().isoformat()
                metadatas.append(metadata)
            
            # Add to collection
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
            
            # Get updated collection stats
            total_count = self.collection.count()
            
            result = {
                "success": True,
                "added_count": len(embedded_chunks),
                "total_documents": total_count,
                "collection_name": self.collection_name
            }
            
            logger.info(f"Successfully added {len(embedded_chunks)} documents. Total: {total_count}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to add documents to vector store: {e}")
            return {
                "success": False,
                "error": str(e),
                "added_count": 0
            }
    
    async def similarity_search(
        self, 
        query_embedding: List[float], 
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Perform similarity search using query embedding.
        
        Args:
            query_embedding: Query embedding vector
            n_results: Number of results to return
            where: Optional metadata filter conditions
            
        Returns:
            List[Dict]: Search results with documents and metadata
        """
        try:
            if not self.collection:
                await self.initialize()
            
            logger.info(f"Performing similarity search for {n_results} results")
            
            # Perform query
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"]
            )
            
            # Format results
            formatted_results = []
            if results["documents"] and results["documents"][0]:
                for i in range(len(results["documents"][0])):
                    result = {
                        "id": results["ids"][0][i],
                        "document": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i],
                        "similarity_score": 1 - results["distances"][0][i]  # Convert distance to similarity
                    }
                    formatted_results.append(result)
            
            logger.info(f"Found {len(formatted_results)} similar documents")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Similarity search failed: {e}")
            return []
    
    async def get_all_embeddings(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve all embeddings from the collection for quantum search.
        
        Args:
            session_id: Optional session ID to filter results
        
        Returns:
            List[Dict]: All documents with embeddings and metadata
        """
        try:
            if not self.collection:
                await self.initialize()
            
            logger.info(f"Retrieving embeddings for quantum search (session: {session_id})")
            
            # Build where filter
            where_filter = None
            if session_id:
                where_filter = {"session_id": session_id}
            
            # Get documents (filtered by session if provided)
            results = self.collection.get(
                where=where_filter,
                include=["embeddings", "documents", "metadatas"]
            )
            
            # Format results
            all_embeddings = []
            if results["embeddings"]:
                for i in range(len(results["embeddings"])):
                    embedding_data = {
                        "id": results["ids"][i],
                        "embedding": results["embeddings"][i],
                        "document": results["documents"][i],
                        "metadata": results["metadatas"][i]
                    }
                    all_embeddings.append(embedding_data)
            
            logger.info(f"Retrieved {len(all_embeddings)} embeddings")
            return all_embeddings
            
        except Exception as e:
            logger.error(f"Failed to retrieve all embeddings: {e}")
            return []
    
    async def delete_documents(self, document_ids: List[str]) -> Dict[str, Any]:
        """Delete documents from the vector store.
        
        Args:
            document_ids: List of document IDs to delete
            
        Returns:
            dict: Deletion result
        """
        try:
            if not self.collection:
                await self.initialize()
            
            logger.info(f"Deleting {len(document_ids)} documents")
            
            # Delete documents
            self.collection.delete(ids=document_ids)
            
            # Get updated count
            remaining_count = self.collection.count()
            
            result = {
                "success": True,
                "deleted_count": len(document_ids),
                "remaining_documents": remaining_count
            }
            
            logger.info(f"Successfully deleted {len(document_ids)} documents")
            return result
            
        except Exception as e:
            logger.error(f"Failed to delete documents: {e}")
            return {
                "success": False,
                "error": str(e),
                "deleted_count": 0
            }
    
    async def search_by_metadata(
        self, 
        where: Dict[str, Any], 
        n_results: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Search documents by metadata filters.
        
        Args:
            where: Metadata filter conditions
            n_results: Maximum number of results (None for all)
            
        Returns:
            List[Dict]: Filtered documents
        """
        try:
            if not self.collection:
                await self.initialize()
            
            logger.info(f"Searching by metadata: {where}")
            
            # Perform metadata search
            results = self.collection.get(
                where=where,
                limit=n_results,
                include=["documents", "metadatas"]
            )
            
            # Format results
            formatted_results = []
            if results["documents"]:
                for i in range(len(results["documents"])):
                    result = {
                        "id": results["ids"][i],
                        "document": results["documents"][i],
                        "metadata": results["metadatas"][i]
                    }
                    formatted_results.append(result)
            
            logger.info(f"Found {len(formatted_results)} documents matching metadata")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Metadata search failed: {e}")
            return []
    
    async def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the vector store collection.
        
        Returns:
            dict: Collection statistics
        """
        try:
            if not self.collection:
                await self.initialize()
            
            count = self.collection.count()
            
            # Get sample metadata to understand data structure
            sample = self.collection.peek(limit=1)
            
            stats = {
                "collection_name": self.collection_name,
                "total_documents": count,
                "db_path": self.db_path,
                "has_data": count > 0
            }
            
            if sample["metadatas"] and len(sample["metadatas"]) > 0:
                stats["sample_metadata_keys"] = list(sample["metadatas"][0].keys())
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            return {
                "collection_name": self.collection_name,
                "total_documents": 0,
                "db_path": self.db_path,
                "has_data": False,
                "error": str(e)
            }
    
    async def reset_collection(self) -> Dict[str, Any]:
        """Reset (clear) the entire collection.
        
        Returns:
            dict: Reset operation result
        """
        try:
            if not self.collection:
                await self.initialize()
            
            logger.warning("Resetting collection - all data will be lost!")
            
            # Delete the collection
            self.client.delete_collection(name=self.collection_name)
            
            # Recreate empty collection
            self.collection = self.client.create_collection(
                name=self.collection_name,
                metadata={"description": "PDF document embeddings for chatbot"},
                embedding_function=None
            )
            
            result = {
                "success": True,
                "message": "Collection reset successfully",
                "collection_name": self.collection_name
            }
            
            logger.info("Collection reset completed")
            return result
            
        except Exception as e:
            logger.error(f"Failed to reset collection: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def close(self):
        """Close the vector store connection."""
        try:
            if self.client:
                # ChromaDB doesn't require explicit closing
                logger.info("Vector store connection closed")
        except Exception as e:
            logger.error(f"Error closing vector store: {e}")