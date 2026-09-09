from fastapi import APIRouter, Depends, HTTPException, status, Cookie, Response, Body
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth
from jose import jwt, JWTError
import json
import uuid
from app.core.config import settings
from app.domain.models.user import User, FirebaseToken
from app.infrastructure.database.repository import get_refresh_token_repository
from jose import ExpiredSignatureError

router = APIRouter()
oauth2_scheme = HTTPBearer(auto_error=False)

# Initialize Firebase 
firebase_app = None

def init_firebase():
    global firebase_app
    cred_dict = settings.get_firebase_credential_dict()
    if firebase_app is None and cred_dict:
        try:
            cred = credentials.Certificate(cred_dict)
            firebase_app = firebase_admin.initialize_app(cred)
            print("Firebase initialized successfully")
        except Exception as e:
            print(f"Firebase initialization error: {e}")
            raise

# Call init_firebase at startup
init_firebase()

# Cookie constants
GUEST_COOKIE_NAME = "guest_usage_info"
GUEST_COOKIE_MAX_AGE = 60 * 60 * 24 * 3  # 3 days in seconds

def create_access_token(user_data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token for API, always has 'sub' (user_id) and 'exp'.
    """
    to_encode = user_data.copy()
    if "sub" not in to_encode and "user_id" in to_encode:
        to_encode["sub"] = to_encode["user_id"]
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def create_refresh_token(user_data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Tạo một JWT refresh token cho API, luôn có 'sub' (user_id), 'exp' và 'type'.
    """
    to_encode = user_data.copy()
    if "sub" not in to_encode and "user_id" in to_encode:
        to_encode["sub"] = to_encode["user_id"]
    expire = datetime.utcnow() + (expires_delta or timedelta(days=7))
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def get_or_create_guest_user(
    response: Response, 
    guest_cookie: Optional[str] = None
) -> User:
    """
    Get user info from cookie or create a new guest user.
    """
    guest_info = {}
    guest_id = None
    
    # Try to parse the cookie if it exists
    if guest_cookie:
        try:
            guest_info = json.loads(guest_cookie)
            guest_id = guest_info.get("guest_id")
        except (json.JSONDecodeError, ValueError):
            pass
    
    # Create a new guest ID if needed
    if not guest_id:
        guest_id = f"guest_{uuid.uuid4()}"
        
    # Update and set the cookie
    guest_info = {
        "guest_id": guest_id,
        "last_used": datetime.now().isoformat()
    }
    
    # Set/update the cookie
    response.set_cookie(
        key=GUEST_COOKIE_NAME,
        value=json.dumps(guest_info),
        max_age=GUEST_COOKIE_MAX_AGE,
        httponly=True,
        samesite="none",
        secure=True
    )
    
    return User(
        user_id=guest_id,
        email="guest@example.com",
        is_guest=True,
        usage_count=0,
        last_used=datetime.now()
    )

def verify_firebase_token(id_token: str) -> dict:
    """
    Verify Firebase token.
    """
    try:
        decoded_token = firebase_auth.verify_id_token(id_token)
        return decoded_token
    except ValueError as e:

        raise ValueError(f"Invalid token format: {str(e)}")
    except Exception as e:
        # Return error instead of raising exception
        raise ValueError(f"Token verification failed: {str(e)}")

def get_user_from_firebase(firebase_user_id: str) -> dict:
    """
    Get user info from Firebase by user ID.
    """
    try:
        user = firebase_auth.get_user(firebase_user_id)
        return user
    except firebase_auth.UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User not found: {firebase_user_id}"
        )
    except Exception as e:
        print(f"Error retrieving user from Firebase: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve user data"
        )

def format_firebase_user(firebase_user) -> User:
    """
    Format data from Firebase user to application format.
    """
    providers = [
        provider.provider_id for provider in getattr(firebase_user, "provider_data", [])
    ]
    
    return User(
        user_id=firebase_user.uid,
        email=getattr(firebase_user, "email", ""),
        display_name=getattr(firebase_user, "display_name", None),
        photo_url=getattr(firebase_user, "photo_url", None),
        is_guest=False,
        is_email_verified=getattr(firebase_user, "email_verified", False),
        providers=providers,
        usage_count=0,
        last_used=datetime.now(),
        created_at=datetime.fromtimestamp(firebase_user.user_metadata.creation_timestamp / 1000)
    )

async def get_current_user(
    response: Response,
    token: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme),
    guest_cookie: Optional[str] = Cookie(None, alias=GUEST_COOKIE_NAME)
) -> User:
    """
    Get current user info from token or cookie.
    """
    if token:
        token_value = token.credentials
        try:
            try:
                payload = jwt.decode(token_value, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
                user_id = payload.get("sub")
                if user_id:
                    firebase_user = get_user_from_firebase(user_id)
                    return format_firebase_user(firebase_user)
            except JWTError:
                try:
                    firebase_data = verify_firebase_token(token_value)
                    firebase_user = get_user_from_firebase(firebase_data["uid"])
                    return format_firebase_user(firebase_user)
                except ValueError as e:
                    print(f"Firebase token format error: {e}")
        except Exception as e:
            print(f"Authentication error: {str(e)}")
    
    # If no token or token validation failed, create or get guest user
    return get_or_create_guest_user(response, guest_cookie)


@router.post("/verify-token")
async def verify_token(token_data: FirebaseToken):
    """
    Verify Firebase token and return user info.
    """
    try:
        try:
            decoded_token = verify_firebase_token(token_data.id_token)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e)
            )
            
        user = get_user_from_firebase(decoded_token["uid"])
        user_uid = user["uid"] if isinstance(user, dict) and "uid" in user else getattr(user, "uid", None)
        if not user_uid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user object returned from Firebase"
            )
        access_token = create_access_token({"sub": user_uid})
        refresh_token = create_refresh_token({"sub": user_uid})
        # Save refresh_token to MongoDB
        repo = get_refresh_token_repository()
        await repo.create({
            "refresh_token": refresh_token,
            "user_id": user_uid,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(days=7)
        })
        return {
            "message": "Token verified",
            "user": format_firebase_user(user),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }
    except Exception as e:
        print(f"Token verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
        )

@router.get("/profile", response_model=User)
async def get_profile(current_user: User = Depends(get_current_user)):
    """
    Get the profile of the current authenticated user.
    """
    return current_user

@router.get("/usage")
async def get_usage(current_user: User = Depends(get_current_user)):
    """
    Get the usage statistics for the current user.
    """
    return {
        "user_id": current_user.user_id,
        "is_guest": current_user.is_guest,
        "usage_count": 0 if current_user.is_guest else current_user.usage_count,
        "max_usage": None if not current_user.is_guest else settings.GUEST_MAX_USAGE
    }

@router.post("/refresh-token")
async def refresh_token(
    refresh_token: str = Body(..., embed=True)
):
    """
    Refresh access token.
    """
    repo = get_refresh_token_repository()
    try:
        payload = jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        token_type = payload.get("type")
        
        if not user_id or token_type != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        token_doc = await repo.get_by_token(refresh_token)
        
        if not token_doc or token_doc.get("user_id") != user_id:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        access_token = create_access_token({"sub": user_id})
        return {"access_token": access_token, "token_type": "bearer"}
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

@router.post("/refresh-token/reset")
async def reset_refresh_tokens(current_user: User = Depends(get_current_user)):
    """
    Delete all refresh tokens of current user from MongoDB.
    """
    repo = get_refresh_token_repository()
    collection = repo.collection
    result = await collection.delete_many({"user_id": current_user.user_id})
    return {"message": f"Deleted {result.deleted_count} refresh tokens for user {current_user.user_id}"}
