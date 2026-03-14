"""Database service for Supabase integration.

This module handles:
- Supabase client initialization
- User management
- Database queries and mutations

Note: Chat history operations have been moved to frontend local storage.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import os
from supabase import create_client, Client
from config import settings

logger = logging.getLogger(__name__)

class DatabaseService:
    """Service for handling Supabase database operations."""
    
    def __init__(self):
        """Initialize the database service."""
        self.client: Optional[Client] = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize Supabase client."""
        try:
            supabase_url = os.getenv('SUPABASE_URL')
            supabase_key = os.getenv('SUPABASE_ANON_KEY')
            
            if not supabase_url or not supabase_key:
                raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment variables")
            
            self.client = create_client(supabase_url, supabase_key)
            self._initialized = True
            logger.info("✅ Supabase client initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Supabase client: {e}")
            raise
    
    def _ensure_initialized(self) -> None:
        """Ensure the database service is initialized."""
        if not self._initialized or not self.client:
            raise RuntimeError("Database service not initialized. Call initialize() first.")
    
    async def create_user(self, full_name: str, email: str, password: str, phone_number: Optional[str] = None) -> Dict[str, Any]:
        """Create a new user in the signup_users table.
        
        Args:
            full_name: User's full name
            email: User's email address
            password: User's password (should be hashed)
            phone_number: Optional phone number
            
        Returns:
            Dict containing user data or error
        """
        self._ensure_initialized()
        
        try:
            result = self.client.table('signup_users').insert({
                'full_name': full_name,
                'email': email,
                'password': password,
                'phone_number': phone_number
            }).execute()
            
            if result.data:
                logger.info(f"User created successfully: {email}")
                return {'success': True, 'user': result.data[0]}
            else:
                logger.error(f"Failed to create user: {email}")
                return {'success': False, 'error': 'Failed to create user'}
                
        except Exception as e:
            logger.error(f"Error creating user {email}: {e}")
            return {'success': False, 'error': str(e)}
    
    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email address.
        
        Args:
            email: User's email address
            
        Returns:
            User data if found, None otherwise
        """
        self._ensure_initialized()
        
        try:
            result = self.client.table('signup_users').select('*').eq('email', email).execute()
            
            if result.data:
                return result.data[0]
            return None
            
        except Exception as e:
            logger.error(f"Error getting user by email {email}: {e}")
            return None
    
    async def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID.
        
        Args:
            user_id: User's ID
            
        Returns:
            User data if found, None otherwise
        """
        self._ensure_initialized()
        
        try:
            result = self.client.table('signup_users').select('*').eq('id', user_id).execute()
            
            if result.data:
                return result.data[0]
            return None
            
        except Exception as e:
            logger.error(f"Error getting user by ID {user_id}: {e}")
            return None
    
    async def update_user(self, user_id: int, full_name: Optional[str] = None, 
                         email: Optional[str] = None, phone_number: Optional[str] = None) -> Dict[str, Any]:
        """Update user information.
        
        Args:
            user_id: User's ID
            full_name: Updated full name (optional)
            email: Updated email (optional)
            phone_number: Updated phone number (optional)
            
        Returns:
            Dict containing updated user data or error
        """
        self._ensure_initialized()
        
        try:
            # Build update data
            update_data = {}
            if full_name is not None:
                update_data['full_name'] = full_name
            if email is not None:
                update_data['email'] = email
            if phone_number is not None:
                update_data['phone_number'] = phone_number
            
            if not update_data:
                return {'success': False, 'error': 'No data to update'}
            
            result = self.client.table('signup_users').update(update_data).eq('id', user_id).execute()
            
            if result.data:
                logger.info(f"User updated successfully: {user_id}")
                return {'success': True, 'user': result.data[0]}
            else:
                logger.error(f"Failed to update user: {user_id}")
                return {'success': False, 'error': 'Failed to update user'}
                
        except Exception as e:
            logger.error(f"Error updating user {user_id}: {e}")
            return {'success': False, 'error': str(e)}
    
    async def delete_user(self, user_id: int) -> Dict[str, Any]:
        """Delete a user account.
        
        Args:
            user_id: User's ID
            
        Returns:
            Dict containing success status or error
        """
        self._ensure_initialized()
        
        try:
            result = self.client.table('signup_users').delete().eq('id', user_id).execute()
            
            if result.data:
                logger.info(f"User deleted successfully: {user_id}")
                return {'success': True, 'message': 'User deleted successfully'}
            else:
                logger.error(f"Failed to delete user: {user_id}")
                return {'success': False, 'error': 'Failed to delete user'}
                
        except Exception as e:
            logger.error(f"Error deleting user {user_id}: {e}")
            return {'success': False, 'error': str(e)}
    
    # Chat-related methods removed - chat history now handled by frontend
    
    # All chat-related methods removed - chat history now handled by frontend
    
    async def close(self) -> None:
        """Close database connections."""
        if self.client:
            # Supabase client doesn't need explicit closing
            self.client = None
            self._initialized = False
            logger.info("Database service closed")

# Global database service instance
_database_service: Optional[DatabaseService] = None

async def get_database_service() -> DatabaseService:
    """Get or create the global database service instance.
    
    Returns:
        DatabaseService instance
    """
    global _database_service
    
    if _database_service is None:
        _database_service = DatabaseService()
        await _database_service.initialize()
    
    return _database_service