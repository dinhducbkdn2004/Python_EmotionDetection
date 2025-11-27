from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime

class RateLimit(BaseModel):
    """
    Model representing the rate limit for a user (or IP).
    """
    key: str
    timestamps: List[float]
    last_updated: float
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "key": "guest_123456",
                "timestamps": [1590000000.0, 1590000060.0, 1590000120.0],
                "last_updated": 1590000120.0
            }
        }
    )

class RateLimitInfo(BaseModel):
    """
    Model containing the current rate limit information for the client.
    """
    remaining: int
    reset: int
    total: int
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "remaining": 3,
                "reset": 1800,
                "total": 5
            }
        }
    ) 