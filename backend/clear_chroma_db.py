"""Utility script to clear the ChromaDB database.

This script will:
1. Delete all data from the ChromaDB collection
2. Reset the collection to empty state

Usage:
    python clear_chroma_db.py
"""

import asyncio
import logging
from config import settings
from services.vector_store import VectorStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def clear_database():
    """Clear all data from ChromaDB."""
    try:
        print("🗑️  Starting ChromaDB database cleanup...")
        logger.info("🗑️  Starting ChromaDB database cleanup...")
        
        # Initialize vector store
        vector_store = VectorStore(db_path=settings.CHROMA_DB_PATH)
        await vector_store.initialize()
        
        # Get current stats
        stats_before = await vector_store.get_collection_stats()
        print(f"📊 Current database stats: {stats_before['total_documents']} documents")
        logger.info(f"📊 Current database stats: {stats_before['total_documents']} documents")
        
        # Reset the collection
        result = await vector_store.reset_collection()
        
        if result["success"]:
            print("✅ Database cleared successfully!")
            logger.info("✅ Database cleared successfully!")
            
            # Get new stats
            stats_after = await vector_store.get_collection_stats()
            print(f"📊 New database stats: {stats_after['total_documents']} documents")
            logger.info(f"📊 New database stats: {stats_after['total_documents']} documents")
        else:
            error_msg = f"❌ Failed to clear database: {result.get('error')}"
            print(error_msg)
            logger.error(error_msg)
            
    except Exception as e:
        error_msg = f"❌ Error clearing database: {e}"
        print(error_msg)
        logger.error(error_msg)
        raise


if __name__ == "__main__":
    asyncio.run(clear_database())
