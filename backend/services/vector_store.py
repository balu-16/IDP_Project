"""Vector store service using ChromaDB with persistent storage.

This service handles:
- ChromaDB persistent client initialization
- Collection management for embeddings
- Document storage and retrieval
- Similarity search operations
- Metadata filtering and querying
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import asyncio
from pathlib import Path

# ChromaDB for vector storage
import chromadb
from chromadb.config import Settings

# Configuration
from config import settings

logger = logging.getLogger(__name__)

class VectorStore:
    """Service for managing vector embeddings with ChromaDB persistent storage."""
    
    _instance = None
    _initialized = False
    
    def __new__(cls, db_path: Optional[str] = None):
        """Singleton pattern to ensure only one instance exists."""
        if cls._instance is None:
            cls._instance = super(VectorStore, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize ChromaDB persistent client.
        
        Args:
            db_path: Path to ChromaDB persistent storage directory
        """
        if self._initialized:
            return
            
        self.db_path = self._resolve_db_path(db_path or settings.CHROMA_DB_PATH)
        self.client = None
        self.collection = None
        self.collection_name = settings.CHROMA_COLLECTION_NAME
        
        VectorStore._initialized = True
        logger.info(f"VectorStore initialized with path: {self.db_path}")

    def _resolve_db_path(self, configured_path: str) -> str:
        """Resolve and ensure a writable ChromaDB path.

        Falls back to `<backend>/chroma_db` when the configured path is not writable
        (for example `/app/chroma_db` during local development).
        """
        backend_root = Path(__file__).resolve().parent.parent
        candidate_path = Path(configured_path).expanduser()

        if not candidate_path.is_absolute():
            candidate_path = backend_root / candidate_path

        try:
            candidate_path.mkdir(parents=True, exist_ok=True)
            return str(candidate_path)
        except PermissionError:
            fallback_path = backend_root / "chroma_db"
            fallback_path.mkdir(parents=True, exist_ok=True)
            logger.warning(
                "Configured CHROMA_DB_PATH '%s' is not writable. Falling back to '%s'.",
                str(candidate_path),
                str(fallback_path),
            )
            return str(fallback_path)
    
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

    @staticmethod
    def _normalize_filter_value(value: Any) -> str:
        """Normalize metadata filter values to match stored Chroma metadata."""
        return str(value)

    @classmethod
    def _build_chroma_where(
        cls,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build a Chroma-compatible metadata filter.

        Chroma accepts either a single field filter like `{"session_id": "9"}`
        or an operator expression like `{"$and": [{"session_id": "9"}, {"user_id": "1"}]}`.
        """
        # Preserve prebuilt operator filters and only add scope clauses around them.
        operator_filter = None
        raw_metadata = {
            key: value
            for key, value in (metadata or {}).items()
            if value is not None
        }
        if raw_metadata and any(str(key).startswith("$") for key in raw_metadata):
            operator_filter = raw_metadata
            raw_metadata = {}

        normalized_metadata = {
            key: cls._normalize_filter_value(value)
            for key, value in raw_metadata.items()
        }

        clauses: List[Dict[str, Any]] = [
            {key: value}
            for key, value in normalized_metadata.items()
        ]

        if session_id is not None:
            clauses.append({"session_id": cls._normalize_filter_value(session_id)})

        if user_id is not None:
            clauses.append({"user_id": cls._normalize_filter_value(user_id)})

        if operator_filter:
            if not clauses:
                return operator_filter
            clauses.append(operator_filter)

        if not clauses:
            return None

        if len(clauses) == 1:
            return clauses[0]

        return {"$and": clauses}
    
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

                # Canonical source fields for downstream citation/source answers.
                source_file_name = (
                    metadata.get("source_file_name")
                    or metadata.get("original_file_name")
                    or metadata.get("file_name")
                    or metadata.get("filename")
                )
                if source_file_name:
                    metadata["source_file_name"] = source_file_name
                    metadata["original_file_name"] = metadata.get("original_file_name", source_file_name)
                    metadata["file_name"] = metadata.get("file_name", source_file_name)
                    metadata["filename"] = metadata.get("filename", source_file_name)

                source_title = metadata.get("title", "")
                metadata["source"] = source_title if source_title else metadata.get("source_file_name", "Unknown")
                
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
            
            chroma_where = self._build_chroma_where(metadata=where)
            logger.info(f"Performing similarity search for {n_results} results")
            logger.info("Similarity search Chroma filter: %s", chroma_where)
            
            # Perform query
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=chroma_where,
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
    
    async def get_all_embeddings(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve all embeddings from the collection for quantum search.
        
        Args:
            session_id: Optional session ID to filter results
            user_id: Optional user ID to filter results
        
        Returns:
            List[Dict]: All documents with embeddings and metadata
        """
        try:
            if not self.collection:
                await self.initialize()
            
            logger.info(
                "Retrieving embeddings for quantum search (session: %s, user: %s)",
                session_id,
                user_id,
            )
            
            where_filter = self._build_chroma_where(
                session_id=session_id,
                user_id=user_id,
            )
            logger.info("Quantum retrieval Chroma filter: %s", where_filter)
            
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
            
            logger.info(
                "Retrieved %s embeddings for quantum search (session: %s, user: %s)",
                len(all_embeddings),
                session_id,
                user_id,
            )
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
            
            chroma_where = self._build_chroma_where(metadata=where)
            logger.info(f"Searching by metadata: {where}")
            logger.info("Metadata search Chroma filter: %s", chroma_where)
            
            # Perform metadata search
            results = self.collection.get(
                where=chroma_where,
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
