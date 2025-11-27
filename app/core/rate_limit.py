import time
from typing import List, Optional
from app.infrastructure.database.repository import get_rate_limit_repository
from app.core.logging import logger
from app.domain.models.rate_limit import RateLimit, RateLimitInfo

class MongoRateLimiter:
    """
    Rate limiter implementation using MongoDB for persistent storage.
    """
    
    def __init__(self):
        self._repository = None
    
    async def _get_repository(self):
        """Get the rate limit repository lazily."""
        if self._repository is None:
            self._repository = get_rate_limit_repository()
        return self._repository
    
    async def check_rate_limit(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """
        Check if key has exceeded the limit and update timestamps.
        """
        repository = await self._get_repository()
        now = time.time()
        window_start = now - window_seconds
        
        rate_limit_doc = await repository.get_by_key(key)
        
        if not rate_limit_doc:
            rate_limit = RateLimit(
                key=key,
                timestamps=[now],
                last_updated=now
            )
            await repository.create(rate_limit.model_dump())
            return False
        
        timestamps: List[float] = rate_limit_doc.get("timestamps", [])
        valid_timestamps = [ts for ts in timestamps if ts > window_start]
        
        is_rate_limited = len(valid_timestamps) >= max_requests
        
        if not is_rate_limited:
            valid_timestamps.append(now)
        
        rate_limit = RateLimit(
            key=key,
            timestamps=valid_timestamps,
            last_updated=now
        )
        await repository.update(key, rate_limit.model_dump())
        
        if is_rate_limited:
            logger.warning(f"Rate limit exceeded for {key}: {max_requests} requests per {window_seconds} seconds")
            
        return is_rate_limited
    
    async def get_remaining_requests(self, key: str, max_requests: int, window_seconds: int) -> RateLimitInfo:
        """
        Get remaining requests and reset time for client.
        """
        repository = await self._get_repository()
        now = time.time()
        window_start = now - window_seconds
        
        rate_limit_doc = await repository.get_by_key(key)
        
        if not rate_limit_doc:
            return RateLimitInfo(
                remaining=max_requests,
                reset=window_seconds,
                total=max_requests
            )
        
        timestamps: List[float] = rate_limit_doc.get("timestamps", [])
        valid_timestamps = [ts for ts in timestamps if ts > window_start]
        
        remaining = max(0, max_requests - len(valid_timestamps))
        
        if valid_timestamps:
            oldest_timestamp = min(valid_timestamps)
            reset_time = oldest_timestamp + window_seconds - now
        else:
            reset_time = 0
            
        return RateLimitInfo(
            remaining=remaining,
            reset=int(reset_time),
            total=max_requests
        )
    
    async def clean_expired_records(self, older_than_seconds: int = 86400):
        """
        Clean up old records to avoid database bloating.
        """
        repository = await self._get_repository()
        cutoff_time = time.time() - older_than_seconds
        
        deleted_count = await repository.delete_expired(cutoff_time)
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} expired rate limit records")

# Singleton instance
_rate_limiter: Optional[MongoRateLimiter] = None

def get_rate_limiter() -> MongoRateLimiter:
    """Get singleton instance of MongoRateLimiter."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = MongoRateLimiter()
    return _rate_limiter 