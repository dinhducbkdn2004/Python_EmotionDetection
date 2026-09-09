import jwt
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.exceptions import AuthenticationException, ValidationException

def create_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT token with provided payload
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Dict[str, Any]:
    """
    Verify JWT token and return payload
    
    Raises:
        AuthenticationException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        
        if "exp" in payload and datetime.fromtimestamp(payload["exp"]) < datetime.utcnow():
            raise AuthenticationException("Token expired")
        
        return payload
    except jwt.PyJWTError as e:
        raise AuthenticationException(f"Invalid token: {str(e)}")
    except Exception as e:
        raise AuthenticationException(f"Authentication error: {str(e)}") 