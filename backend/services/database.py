"""Database service for Supabase integration.

This module handles:
- Supabase client initialization
- User management
- Database queries and mutations

Note: Chat history operations have been moved to frontend local storage.
"""

import logging
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import HTTPException
from supabase import create_client, Client
from config import settings

logger = logging.getLogger(__name__)


SUPABASE_PROXY_MISMATCH = "unexpected keyword argument 'proxy'"


def _is_supabase_dependency_mismatch(exc: Exception) -> bool:
    """Detect known Supabase/httpx incompatibility seen in container builds."""
    return SUPABASE_PROXY_MISMATCH in str(exc)


class DatabaseService:
    """Service for handling Supabase database operations."""
    
    def __init__(self):
        """Initialize the database service."""
        self.client: Optional[Client] = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize Supabase client."""
        try:
            supabase_url = self._resolve_env_value("SUPABASE_URL")
            supabase_key = self._resolve_env_value("SUPABASE_ANON_KEY")
            
            if not supabase_url or not supabase_key:
                raise RuntimeError(
                    "SUPABASE_URL and SUPABASE_ANON_KEY must be set for authentication endpoints"
                )

            if not (supabase_url.startswith("http://") or supabase_url.startswith("https://")):
                raise RuntimeError("SUPABASE_URL must start with http:// or https://")
            
            self.client = create_client(supabase_url, supabase_key)
            self._initialized = True
            logger.info(
                "Supabase client initialized",
                extra={"supabase_url": supabase_url, "has_supabase_key": bool(supabase_key)},
            )
            
        except Exception as e:
            logger.exception(f"Failed to initialize Supabase client: {e}")
            raise

    @staticmethod
    def _clean_env_value(value: Optional[str]) -> Optional[str]:
        """Trim common formatting artifacts from injected env values."""
        if value is None:
            return None

        cleaned = str(value).strip().strip('"').strip("'").strip()
        return cleaned or None

    @staticmethod
    def _resolve_env_value(*names: str) -> Optional[str]:
        """Return the first populated value from settings or process env."""
        for name in names:
            cleaned = DatabaseService._clean_env_value(os.getenv(name))
            if cleaned:
                return cleaned

        for name in names:
            cleaned = DatabaseService._clean_env_value(getattr(settings, name, None))
            if cleaned:
                return cleaned

        return None
    
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
        try:
            await _database_service.initialize()
        except RuntimeError as exc:
            logger.exception("Database service initialization failed: %s", exc)
            _database_service = None
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            )
        except Exception as exc:
            logger.exception("Unexpected database initialization failure: %s", exc)
            _database_service = None
            if _is_supabase_dependency_mismatch(exc):
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Authentication backend initialization failed: incompatible "
                        "Supabase/httpx dependency versions in the deployed container"
                    ),
                )
            raise HTTPException(
                status_code=503,
                detail="Authentication backend initialization failed: invalid Supabase configuration",
            )
    
    return _database_service
