import os
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exception_handlers import http_exception_handler
import uvicorn
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager
import asyncio

from app.core.config import settings
from app.core.logging import get_logger
from app.core.middlewares import ErrorHandlingMiddleware, RateLimitMiddleware, CustomCORSMiddleware
from app.core.exceptions import AppBaseException
from app.api.routes import router as api_router
from app.auth.router import router as auth_router
from app.api.socketio import socket_manager  # Import Socket.IO manager
from app.services.database import connect_to_mongodb, close_mongodb_connection
from app.core.metrics import MetricsMiddleware, metrics_endpoint
from app.services.database import get_database
from firebase_admin import auth
from app.core.rate_limit import get_rate_limiter
from app.infrastructure.database.repository import get_refresh_token_repository
import time

favicon_path = "./favicon.ico"

# Initialize logger
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background tasks for cleanup
    cleanup_task = None
    refresh_token_cleanup_task = None
    
    async def cleanup_rate_limits():
        while True:
            try:
                rate_limiter = get_rate_limiter()
                await rate_limiter.clean_expired_records(86400)  # Clean records older than 1 day
                logger.info("Rate limit cleanup completed")
            except Exception as e:
                logger.error(f"Error in rate limit cleanup: {str(e)}")
            # Run once a day
            await asyncio.sleep(24 * 60 * 60)  # 24 hours
    
    async def cleanup_refresh_tokens():
        while True:
            try:
                refresh_token_repo = get_refresh_token_repository()
                current_time = time.time()
                deleted_count = await refresh_token_repo.delete_expired(current_time)
                logger.info(f"Refresh token cleanup completed. Deleted {deleted_count} expired tokens")
            except Exception as e:
                logger.error(f"Error in refresh token cleanup: {str(e)}")
            # Run once a day
            await asyncio.sleep(24 * 60 * 60)  # 24 hours
    
    try:
        logger.info("Starting up MongoDB connection")
        await connect_to_mongodb()
        
        # Start background cleanup tasks
        cleanup_task = asyncio.create_task(cleanup_rate_limits())
        refresh_token_cleanup_task = asyncio.create_task(cleanup_refresh_tokens())
        logger.info("Rate limit and refresh token cleanup tasks started")
        
        yield
    finally:
        logger.info("Shutting down MongoDB connection")
        await close_mongodb_connection()
        
        # Cancel background tasks
        if cleanup_task:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                logger.info("Rate limit cleanup task cancelled")
        
        if refresh_token_cleanup_task:
            refresh_token_cleanup_task.cancel()
            try:
                await refresh_token_cleanup_task
            except asyncio.CancelledError:
                logger.info("Refresh token cleanup task cancelled")


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
        
    openapi_schema = get_openapi(
        title=settings.APP_NAME,
        version="0.1.0",
        description="API for detecting emotions from facial images",
        routes=app.routes,
    )

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app = FastAPI(
    title=settings.APP_NAME,
    description="API for detecting emotions from facial images",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.openapi = custom_openapi

# Add Prometheus metrics middleware
app.add_middleware(MetricsMiddleware)

# Add error handling middleware 
app.add_middleware(ErrorHandlingMiddleware)

# Add Rate Limit middleware
app.add_middleware(
    RateLimitMiddleware,
    max_requests= settings.GUEST_MAX_USAGE,
    window_seconds= settings.GUEST_WINDOW_SECONDS
)

# Add CustomCORSMiddleware to ensure proper CORS headers for all responses
app.add_middleware(CustomCORSMiddleware)

# Configure CORS origins
origins = []
if hasattr(settings, 'CORS_ORIGINS') and settings.CORS_ORIGINS:
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(',') if o.strip()]

default_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://emd.medicalink.online",
    "https://emdbe.medicalink.online",
    "https://emd.ducbkdn.space",
    "https://emdbe.ducbkdn.space",
]
for default_origin in default_origins:
    if default_origin not in origins:
        origins.append(default_origin)

logger.info(f"CORS enabled for origins: {origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register exception handlers
@app.exception_handler(AppBaseException)
async def app_exception_handler(request: Request, exc: AppBaseException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.message,
            "details": exc.details
        }
    )

# Health check endpoints
@app.get("/healthz", tags=["Health"])
async def healthz():
    return {"status": "ok"}

@app.get("/readyz", tags=["Health"])
async def readyz():
    """
    Check if critical services are ready (MongoDB & Firebase)
    """
    try:
        # Check MongoDB connection
        db = get_database()
        await db.command('ping')
        mongo_status = "ready"
    except Exception as e:
        logger.error(f"MongoDB health check failed: {str(e)}")
        mongo_status = "not ready"

    try:
        # Check Firebase connection 
        auth.get_user_by_email("tester@email.com")
        firebase_status = "ready"
    except Exception as e:
        logger.error(f"Firebase health check failed: {str(e)}")
        firebase_status = "not ready"

    # Overall status is ready only if both services are ready
    overall_status = "ready" if mongo_status == "ready" and firebase_status == "ready" else "not ready"
    
    return {
        "status": overall_status,
        "services": {
            "mongodb": mongo_status,
            "firebase": firebase_status
        }
    }

# Prometheus metrics endpoint
@app.get("/metrics", include_in_schema=False)
def metrics():
    return metrics_endpoint()

# Routes
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(api_router, prefix=settings.API_PREFIX, tags=["Emotion Detection"])

# Root endpoint
@app.get("/")
async def root():
    scheme = "https" if getattr(settings, "HTTPS_ENABLED", False) else "http"
    # is development mode
    url_prefix = ''
    if os.getenv("ENV") != "production":
        url_prefix = f"{scheme}://{settings.HOST}:{settings.PORT}"
    else:
        url_prefix = f"{scheme}://{settings.HOST}"
    return {
        "message": "Welcome to the Face Emotion Detection API",
        "docs": f"{url_prefix}/docs",
        "redoc": f"{url_prefix}/redoc",
    }
    
@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return FileResponse(favicon_path)

# Mount Socket.IO app - sửa lại để hoạt động đúng
app.mount('/', socket_manager.app)

if __name__ == "__main__":
    # Check if HTTPS is enabled
    ssl_config = {}
    if getattr(settings, "HTTPS_ENABLED", False):
        ssl_keyfile = getattr(settings, "SSL_KEYFILE", None)
        ssl_certfile = getattr(settings, "SSL_CERTFILE", None)
        
        if ssl_keyfile and ssl_certfile:
            ssl_config.update({
                "ssl_keyfile": ssl_keyfile,
                "ssl_certfile": ssl_certfile
            })
            logger.info(f"HTTPS enabled with cert: {ssl_certfile} and key: {ssl_keyfile}")
        else:
            logger.warning("HTTPS_ENABLED is True but SSL_KEYFILE or SSL_CERTFILE not provided")
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        **ssl_config
    )
