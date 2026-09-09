import os
from pydantic import ConfigDict
from pydantic_settings import BaseSettings
from typing import Optional
from dotenv import load_dotenv
import base64
import json

# Load environment variables if in development mode
if os.getenv("ENV") != "production":
    load_dotenv()

class Settings(BaseSettings):
    # App settings
    APP_NAME: str = os.getenv("APP_NAME", "Face Emotion Detection Service")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"
    API_PREFIX: str = os.getenv("API_PREFIX", "/api")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "2508"))
    
    # HTTPS settings
    HTTPS_ENABLED: bool = os.getenv("HTTPS_ENABLED", "False").lower() == "true"
    SSL_KEYFILE: Optional[str] = os.getenv("SSL_KEYFILE", "/app/ssl/key.pem")
    SSL_CERTFILE: Optional[str] = os.getenv("SSL_CERTFILE", "/app/ssl/cert.pem")
    
    # CORS settings
    CORS_ORIGINS: Optional[str] = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,https://emd.ducbkdn.space")
    
    # MongoDB settings
    MONGODB_URI: str = os.getenv("MONGODB_URI", "")
    MONGODB_NAME: str = os.getenv("MONGODB_NAME", "emotion_detection")
    
    # Cloudinary settings
    CLOUDINARY_CLOUD_NAME: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY: str = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET: str = os.getenv("CLOUDINARY_API_SECRET", "")
    
    # Firebase settings
    FIREBASE_SERVICE_ACCOUNT_B64: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64", "")

    def get_firebase_credential_dict(self):
        if not self.FIREBASE_SERVICE_ACCOUNT_B64:
            return None
        decoded = base64.b64decode(self.FIREBASE_SERVICE_ACCOUNT_B64)
        return json.loads(decoded)
    
    # Hugging Face model
    HUGGINGFACE_MODEL: str = os.getenv("HUGGINGFACE_MODEL", "dima806/facial_emotions_image_detection")
    
    # Security settings
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    
    # Guest usage limits
    GUEST_MAX_USAGE: int = int(os.getenv("GUEST_MAX_USAGE", "3"))
    GUEST_WINDOW_SECONDS: int = int(os.getenv("GUEST_WINDOW_SECONDS", "86400"))  # 1 day
    MAX_BATCH_SIZE: int = int(os.getenv("MAX_BATCH_SIZE", "4"))
    
    # Logging settings
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_TO_FILE: bool = os.getenv("LOG_TO_FILE", "True").lower() == "true"
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")
    
    # Face detection minSize (for detectMultiScale)
    FACE_DETECT_MIN_SIZE: int = int(os.getenv("FACE_DETECT_MIN_SIZE", "64"))  # default 32px
    ENV: str = os.getenv("ENV", "development")

    # class Config:
    #     env_file = ".env"
    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore"
    }

settings = Settings()
