from fastapi import Request, status
from fastapi.responses import JSONResponse
import traceback
from typing import Dict, Any
import time
from app.core.exceptions import RateLimitException
from app.core.config import settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from app.core.rate_limit import get_rate_limiter
from fastapi.middleware.cors import CORSMiddleware

from app.core.exceptions import AppBaseException
from app.core.logging import logger


async def exception_handler(request: Request, exception: Exception) -> JSONResponse:
    """
    Global exception handler for all endpoints.
    """
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_content: Dict[str, Any] = {
        "success": False,
        "message": "An unexpected error occurred",
        "details": {}
    }
    
    path = request.url.path
    method = request.method
    client_host = request.client.host if request.client else "unknown"
    
    if isinstance(exception, AppBaseException):
        status_code = exception.status_code
        error_content["message"] = exception.message
        error_content["details"] = exception.details
        
        if status_code >= 500:
            logger.error(
                f"Error processing request {method} {path} from {client_host}: "
                f"{exception.message}",
                extra={
                    "status_code": status_code,
                    "details": exception.details,
                    "request_path": path,
                    "request_method": method,
                    "client_host": client_host
                }
            )
        else:
            logger.warning(
                f"Error processing request {method} {path} from {client_host}: "
                f"{exception.message}",
                extra={
                    "status_code": status_code,
                    "details": exception.details,
                    "request_path": path,
                    "request_method": method,
                    "client_host": client_host
                }
            )
    else:
        exception_type = type(exception).__name__
        exception_str = str(exception)
        
        error_content["message"] = f"Unexpected error: {exception_type}"
        error_content["details"]["error"] = exception_str
        
        logger.error(
            f"Unhandled exception processing request {method} {path} from {client_host}: "
            f"{exception_type}: {exception_str}",
            extra={
                "status_code": status_code,
                "exception_type": exception_type,
                "stacktrace": traceback.format_exc(),
                "request_path": path,
                "request_method": method,
                "client_host": client_host
            }
        )
    
    return JSONResponse(
        status_code=status_code,
        content=error_content
    )


class ErrorHandlingMiddleware:
    """
    Middleware for global exception handling across the application.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            response = await exception_handler(request, exc)
            await response(scope, receive, send)

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to limit the number of requests from an IP (or guest_id) for sensitive endpoints.
    """
    def __init__(self, app: ASGIApp, max_requests: int = 10, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next):
        if request.url.path == f"{settings.API_PREFIX}/detect":
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                return await call_next(request)
            
            guest_cookie = request.cookies.get("guest_usage_info")
            guest_id = None
            if guest_cookie:
                try:
                    import json
                    guest_info = json.loads(guest_cookie)
                    guest_id = guest_info.get("guest_id")
                except Exception:
                    pass
            else:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "success": False,
                        "message": "Forbidden"
                    }
                )
            
            key = guest_id
            
            rate_limiter = get_rate_limiter()
            is_rate_limited = await rate_limiter.check_rate_limit(
                key=key,
                max_requests=self.max_requests,
                window_seconds=self.window_seconds
            )
            
            if is_rate_limited:
                rate_info = await rate_limiter.get_remaining_requests(
                    key=key,
                    max_requests=self.max_requests,
                    window_seconds=self.window_seconds
                )
                
                message = f"Rate limit exceeded: {self.max_requests} requests per day."
                logger.warning(f"Rate limit exceeded for {key}: {message}")
                
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "success": False,
                        "message": message,
                        "details": {
                            "retry_after": rate_info.reset,
                            "limit": rate_info.total,
                            "remaining": rate_info.remaining
                        }
                    },
                    headers={"Retry-After": str(rate_info.reset)}
                )
                
        response = await call_next(request)
        return response

class CustomCORSMiddleware(BaseHTTPMiddleware):
    """
    Custom middleware to ensure CORS headers are applied correctly, particularly Access-Control-Allow-Credentials and Access-Control-Allow-Origin.
    """
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.allowed_origins = []
        if settings.CORS_ORIGINS:
            self.allowed_origins = settings.CORS_ORIGINS.split(',')
            
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        
        response = await call_next(request)
        
        if origin and origin in self.allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            
        return response
