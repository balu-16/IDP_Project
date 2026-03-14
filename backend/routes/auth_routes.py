"""Authentication routes for user management.

This module handles:
- User registration
- User authentication
- Password hashing and verification
- User profile management
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
import hashlib
import secrets

# FastAPI imports
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, EmailStr

# Services
from services.database import get_database_service, DatabaseService

# Configuration
from config import settings

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/auth", tags=["authentication"])

# Pydantic models for request/response
class UserRegistrationRequest(BaseModel):
    """Request model for user registration."""
    full_name: str = Field(..., min_length=1, max_length=100, description="User's full name")
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=6, max_length=100, description="User's password")
    phone_number: Optional[str] = Field(default=None, max_length=20, description="User's phone number")

class UserLoginRequest(BaseModel):
    """Request model for user login."""
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., description="User's password")

class UserResponse(BaseModel):
    """Response model for user data."""
    success: bool
    user: Optional[Dict[str, Any]] = None
    message: str
    token: Optional[str] = None

def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with salt.
    
    Args:
        password: Plain text password
        
    Returns:
        Hashed password string
    """
    # Generate a random salt
    salt = secrets.token_hex(16)
    # Hash the password with salt
    password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return f"{salt}:{password_hash}"

def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a password against its hash.
    
    Args:
        password: Plain text password
        hashed_password: Stored hash with salt
        
    Returns:
        True if password matches, False otherwise
    """
    try:
        salt, stored_hash = hashed_password.split(':')
        password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return password_hash == stored_hash
    except ValueError:
        return False

def generate_simple_token(user_id: int, email: str) -> str:
    """Generate a simple token for user authentication.
    
    Args:
        user_id: User's ID
        email: User's email
        
    Returns:
        Simple authentication token
    """
    # This is a simple token generation - in production, use JWT or similar
    token_data = f"{user_id}:{email}:{secrets.token_hex(16)}"
    return hashlib.sha256(token_data.encode()).hexdigest()

@router.post("/register", response_model=UserResponse)
async def register_user(
    request: UserRegistrationRequest,
    database: DatabaseService = Depends(get_database_service)
) -> JSONResponse:
    """Register a new user.
    
    Args:
        request: User registration data
        database: Database service instance
        
    Returns:
        JSONResponse: Registration result with user data
    """
    try:
        logger.info(f"Attempting to register user: {request.email}")
        
        # Check if user already exists
        existing_user = await database.get_user_by_email(request.email)
        if existing_user:
            raise HTTPException(
                status_code=409,
                detail="User with this email already exists"
            )
        
        # Hash the password
        hashed_password = hash_password(request.password)
        
        # Create the user
        result = await database.create_user(
            full_name=request.full_name,
            email=request.email,
            password=hashed_password,
            phone_number=request.phone_number
        )
        
        if result['success']:
            user_data = result['user']
            # Remove password from response
            user_data.pop('password', None)
            
            # Generate a simple token
            token = generate_simple_token(user_data['id'], user_data['email'])
            
            logger.info(f"User registered successfully: {request.email}")
            return JSONResponse(
                status_code=201,
                content={
                    "success": True,
                    "user": user_data,
                    "message": "User registered successfully",
                    "token": token
                }
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=result.get('error', 'Failed to create user')
            )
            
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"User registration failed for {request.email}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during registration: {str(e)}"
        )

@router.post("/login", response_model=UserResponse)
async def login_user(
    request: UserLoginRequest,
    database: DatabaseService = Depends(get_database_service)
) -> JSONResponse:
    """Authenticate a user.
    
    Args:
        request: User login data
        database: Database service instance
        
    Returns:
        JSONResponse: Login result with user data and token
    """
    try:
        logger.info(f"Attempting to login user: {request.email}")
        
        # Get user by email
        user = await database.get_user_by_email(request.email)
        if not user:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )
        
        # Verify password
        if not verify_password(request.password, user['password']):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )
        
        # Remove password from response
        user_data = user.copy()
        user_data.pop('password', None)
        
        # Generate a simple token
        token = generate_simple_token(user_data['id'], user_data['email'])
        
        logger.info(f"User logged in successfully: {request.email}")
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "user": user_data,
                "message": "Login successful",
                "token": token
            }
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"User login failed for {request.email}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during login: {str(e)}"
        )

@router.get("/user/{user_id}", response_model=UserResponse)
async def get_user_profile(
    user_id: int,
    database: DatabaseService = Depends(get_database_service)
) -> JSONResponse:
    """Get user profile by ID.
    
    Args:
        user_id: User's ID
        database: Database service instance
        
    Returns:
        JSONResponse: User profile data
    """
    try:
        logger.info(f"Getting user profile for ID: {user_id}")
        
        # Get user by ID
        user = await database.get_user_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )
        
        # Remove password from response
        user_data = user.copy()
        user_data.pop('password', None)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "user": user_data,
                "message": "User profile retrieved successfully"
            }
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Failed to get user profile for ID {user_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@router.put("/user/{user_id}", response_model=UserResponse)
async def update_user_profile(
    user_id: int,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    phone_number: Optional[str] = None,
    database: DatabaseService = Depends(get_database_service)
) -> JSONResponse:
    """Update user profile.
    
    Args:
        user_id: User's ID
        full_name: Updated full name (optional)
        email: Updated email (optional)
        phone_number: Updated phone number (optional)
        database: Database service instance
        
    Returns:
        JSONResponse: Updated user profile data
    """
    try:
        logger.info(f"Updating user profile for ID: {user_id}")
        
        # Update user
        result = await database.update_user(user_id, full_name, email, phone_number)
        
        if not result['success']:
            raise HTTPException(
                status_code=400,
                detail=result.get('error', 'Failed to update user')
            )
        
        # Remove password from response
        user_data = result['user'].copy()
        user_data.pop('password', None)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "user": user_data,
                "message": "User profile updated successfully"
            }
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Failed to update user profile for ID {user_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@router.delete("/user/{user_id}")
async def delete_user_account(
    user_id: int,
    database: DatabaseService = Depends(get_database_service)
) -> JSONResponse:
    """Delete user account.
    
    Args:
        user_id: User's ID
        database: Database service instance
        
    Returns:
        JSONResponse: Deletion confirmation
    """
    try:
        logger.info(f"Deleting user account for ID: {user_id}")
        
        # Delete user
        result = await database.delete_user(user_id)
        
        if not result['success']:
            raise HTTPException(
                status_code=400,
                detail=result.get('error', 'Failed to delete user')
            )
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "User account deleted successfully"
            }
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Failed to delete user account for ID {user_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )